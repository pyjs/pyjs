import time
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path

from django.apps import apps
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.utils.cache import patch_vary_headers

from pyjs.javascript.transpiler import (
    BundleTarget,
    bundle_targets_with_source_maps,
    bundle_with_source_map,
)
from pyjs.server.application import (
    ApplicationContent,
    ApplicationNode,
    ApplicationPage,
    ApplicationSection,
    EntryPoint,
)
from pyjs.server.build import BuildStats
from pyjs.server.rendering import navigation_fragment
from pyjs.tooling.npm import ManagedNpmProject
from pyjs.web.dom import Element
from pyjs.web.domx import tag
from pyjs.web.navigation import NAVIGATION_HEADER
from pyjs.web.ssr import render_document


class PyJSApplication:
    """Compile and render a split-bundle PyJS application in Django.

    Args:
        entry_point: Root UI function or declarative application section.
        name: Django static directory used for generated assets.
        mounts: Pages and sections mounted below a root function.
        layout_id: Hydrated navigation layout receiving page fragments.
        javascript_name: Filename for the root JavaScript bundle.
        stylesheet_name: Filename for the shared stylesheet.
        head: Elements included in every document head.
        html_attributes: Attributes for the document element.
        body_attributes: Attributes for the document body.
        development_reload_url: Optional development-only reload script.
    """

    def __init__(
        self,
        entry_point: EntryPoint | ApplicationSection,
        *,
        name: str,
        mounts: tuple[ApplicationNode, ...] = (),
        layout_id: str | None = None,
        javascript_name: str = "app.js",
        stylesheet_name: str = "app.css",
        head: tuple[Element, ...] = (),
        html_attributes: Mapping[str, str] | None = None,
        body_attributes: Mapping[str, str] | None = None,
        development_reload_url: str | None = None,
    ):
        if isinstance(entry_point, ApplicationSection):
            if mounts:
                raise ValueError(
                    "An application section root already defines its mounted children."
                )
            mounts = entry_point.children
            entry_point = entry_point.entry_point
        self.entry_point = entry_point
        self.name = name
        self.mounts = mounts
        self.layout_id = layout_id
        self.javascript_name = javascript_name
        self.stylesheet_name = stylesheet_name
        self.head = head
        self.html_attributes = (
            {"lang": "en"} if html_attributes is None else dict(html_attributes)
        )
        self.body_attributes = dict(body_attributes or {})
        self.development_reload_url = development_reload_url
        self.build_stats: BuildStats | None = None
        self._page_sections: dict[ApplicationPage, tuple[ApplicationSection, ...]] = {}
        self._target_names: dict[ApplicationNode, str] = {}
        self._bundle_targets = self._index_mounts()

    def _index_mounts(self) -> tuple[BundleTarget, ...]:
        seen: set[ApplicationNode] = set()
        entry_points = {self.entry_point}
        targets = [BundleTarget(self.bundle_stem, self.entry_point)]

        def visit(
            nodes: tuple[ApplicationNode, ...],
            parent: str,
            sections: tuple[ApplicationSection, ...],
        ) -> None:
            names: set[str] = set()
            for node in nodes:
                if not node.name or "." in node.name or "/" in node.name:
                    raise ValueError(
                        "Application node names must be non-empty path segments."
                    )
                if node.name in names:
                    raise ValueError(
                        f"Application node name {node.name!r} is duplicated under "
                        f"{parent!r}."
                    )
                names.add(node.name)
                if node in seen:
                    raise ValueError(
                        f"Application node {node.name!r} may only be mounted once."
                    )
                seen.add(node)
                if node.entry_point in entry_points:
                    raise ValueError(
                        "Each application node requires a distinct entry point."
                    )
                entry_points.add(node.entry_point)
                target_name = f"{parent}.{node.name}"
                self._target_names[node] = target_name
                targets.append(BundleTarget(target_name, node.entry_point, parent))
                if isinstance(node, ApplicationPage):
                    self._page_sections[node] = sections
                else:
                    visit(node.children, target_name, (*sections, node))

        visit(self.mounts, self.bundle_stem, ())
        return tuple(targets)

    def static_path(self, filename: str) -> str:
        return f"{self.name}/{filename}"

    @property
    def bundle_stem(self) -> str:
        return Path(self.javascript_name).stem

    @property
    def bundle_suffix(self) -> str:
        return Path(self.javascript_name).suffix

    def bundle_targets(self) -> tuple[BundleTarget, ...]:
        return self._bundle_targets

    def bundle_filename(self, page: ApplicationPage | None = None) -> str:
        if page is None:
            return self.javascript_name
        try:
            return f"{self._target_names[page]}{self.bundle_suffix}"
        except KeyError:
            raise ValueError(
                f"Page {page.name!r} is not mounted in this application."
            ) from None

    def _resolve_content(
        self,
        content: Element | ApplicationContent,
    ) -> tuple[Element, ApplicationPage | None]:
        if not isinstance(content, ApplicationContent):
            return content, None
        if content.page not in self._page_sections:
            raise ValueError(
                f"Page {content.page.name!r} is not mounted in this application."
            )
        result = content.content
        for section in reversed(self._page_sections[content.page]):
            result = section.entry_point(result)
        return result, content.page

    def build(self, output_directory: str | Path | None = None) -> tuple[Path, Path]:
        """Compile application bundles, source maps, and the shared stylesheet.

        Args:
            output_directory: Destination directory, or the containing Django
                application's static directory when omitted.

        Returns:
            Paths to the root JavaScript bundle and shared stylesheet.
        """
        started = time.perf_counter()
        if output_directory is None:
            output_directory = self.default_output_directory()
        output_directory = Path(output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)

        targets = self.bundle_targets()
        javascript_output = output_directory / self.javascript_name
        stylesheet_output = output_directory / self.stylesheet_name
        if len(targets) == 1:
            generated, stylesheet = bundle_with_source_map(
                self.entry_point,
                additional_entry_points=(),
                filename=self.javascript_name,
            )
            generated_targets = {self.bundle_stem: generated}
        else:
            generated_targets, stylesheet = bundle_targets_with_source_maps(
                targets,
                filename_suffix=self.bundle_suffix,
            )
        javascript_bytes = 0
        for target_name, generated in generated_targets.items():
            filename = f"{target_name}{self.bundle_suffix}"
            source_map_name = f"{filename}.map"
            source = generated.with_source_mapping_url(source_map_name)
            target_output = output_directory / filename
            target_output.write_text(
                source,
                encoding="utf-8",
                newline="\n",
            )
            javascript_bytes += len(source.encode("utf-8"))
            (output_directory / source_map_name).write_text(
                generated.source_map.to_json(),
                encoding="utf-8",
                newline="\n",
            )
        npm_imports = tuple(
            sorted(
                {
                    value
                    for generated in generated_targets.values()
                    for value in generated.npm_imports
                }
            )
        )
        javascript_files = len(generated_targets)
        if npm_imports:
            module = import_module(self.entry_point.__module__)
            module_file = getattr(module, "__file__", None)
            start = Path(module_file) if module_file is not None else Path.cwd()
            vendor_output = output_directory / "pyjs-vendor.js"
            ManagedNpmProject.for_project(start).copy_vendor(
                npm_imports,
                vendor_output,
            )
            javascript_bytes += vendor_output.stat().st_size
            javascript_files += 1
        stylesheet_output.write_text(stylesheet, encoding="utf-8", newline="\n")
        self.build_stats = BuildStats(
            time.perf_counter() - started,
            javascript_files,
            javascript_bytes,
            len(stylesheet.encode("utf-8")),
        )
        return javascript_output, stylesheet_output

    def default_output_directory(self) -> Path:
        module_name = self.entry_point.__module__
        app_config = apps.get_containing_app_config(module_name)
        if app_config is None:
            raise ValueError(
                "The PyJS entry point is not inside an installed Django application; "
                "pass output_directory to build()."
            )
        return Path(app_config.path) / "static" / self.name

    def create_document(
        self,
        body: Element,
        *,
        title: str,
        head: tuple[Element, ...] = (),
        page: ApplicationPage | None = None,
    ) -> Element:
        bundle_url = static(self.static_path(self.bundle_filename(page)))
        return tag(
            "html",
            self.html_attributes,
            tag(
                "head",
                tag("meta", {"charset": "utf-8"}),
                tag(
                    "meta",
                    {
                        "content": "width=device-width, initial-scale=1",
                        "name": "viewport",
                    },
                ),
                tag("title", title),
                tag("link", {"href": bundle_url, "rel": "modulepreload"}),
                tag(
                    "link",
                    {
                        "href": static(self.static_path(self.stylesheet_name)),
                        "rel": "stylesheet",
                    },
                ),
                *self.head,
                *head,
            ),
            tag(
                "body",
                self.body_attributes,
                body,
                tag(
                    "script",
                    {
                        "src": bundle_url,
                        "type": "module",
                    },
                    " ",
                ),
                *(
                    (
                        tag(
                            "script",
                            {
                                "src": self.development_reload_url,
                                "type": "module",
                            },
                            " ",
                        ),
                    )
                    if self.development_reload_url is not None
                    else ()
                ),
            ),
        )

    def response(
        self,
        request: HttpRequest,
        content: Element | ApplicationContent,
        *,
        title: str,
        shell_args: tuple[object, ...] = (),
        head: tuple[Element, ...] = (),
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Render a full document or progressive navigation fragment.

        Args:
            request: Current Django request.
            content: Page content or the result of calling an application page.
            title: Browser document title.
            shell_args: Request-scoped values passed to the root shell.
            head: Elements included in this response's document head.
            status: HTTP response status.
            headers: Additional HTTP response headers.

        Returns:
            A Django response containing SSR HTML and bundle metadata.
        """
        content, page = self._resolve_content(content)
        if page is not None and self.layout_id is not None:
            if request.headers.get(NAVIGATION_HEADER) == "1":
                response = self._navigation_fragment_response(
                    content,
                    title=title,
                    status=status,
                    headers=headers,
                    page=page,
                )
            else:
                response = self._document_response(
                    request,
                    self.entry_point(content, *shell_args),
                    title=title,
                    head=head,
                    status=status,
                    headers=headers,
                    page=page,
                )
            patch_vary_headers(response, (NAVIGATION_HEADER,))
            return response

        if page is not None:
            content = self.entry_point(content, *shell_args)

        return self._document_response(
            request,
            content,
            title=title,
            head=head,
            status=status,
            headers=headers,
            page=page,
        )

    def _document_response(
        self,
        request: HttpRequest,
        content: Element,
        *,
        title: str,
        head: tuple[Element, ...],
        status: int,
        headers: Mapping[str, str] | None,
        page: ApplicationPage | None,
    ) -> HttpResponse:
        csrf = tag(
            "meta",
            {
                "content": get_token(request),
                "name": "csrf-token",
            },
        )
        source = render_document(
            self.create_document(
                content,
                title=title,
                head=(csrf, *head),
                page=page,
            )
        )
        return HttpResponse(
            source,
            status=status,
            content_type="text/html; charset=utf-8",
            headers=headers,
        )

    def _navigation_fragment_response(
        self,
        content: Element,
        *,
        title: str,
        status: int,
        headers: Mapping[str, str] | None,
        page: ApplicationPage,
    ) -> HttpResponse:
        bundle = static(self.static_path(self.bundle_filename(page)))
        source = navigation_fragment(content, title, self.layout_id, bundle)
        return HttpResponse(
            source,
            status=status,
            content_type="text/html; charset=utf-8",
            headers=headers,
        )
