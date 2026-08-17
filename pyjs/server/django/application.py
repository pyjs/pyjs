from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path

from django.apps import apps
from django.http import HttpRequest, HttpResponse
from django.templatetags.static import static
from django.utils.cache import patch_vary_headers

from pyjs.server import navigation_fragment
from pyjs.transpiler import bundle
from pyjs.web.dom import Element
from pyjs.web.domx import tag
from pyjs.web.navigation import NAVIGATION_HEADER
from pyjs.web.ssr import render_document

EntryPoint = Callable[..., object]
Shell = Callable[[Element], Element]


class PyJSApplication:
    def __init__(
        self,
        entry_point: EntryPoint,
        *,
        name: str,
        pages: tuple[EntryPoint, ...] = (),
        layout_id: str | None = None,
        javascript_name: str = "app.js",
        stylesheet_name: str = "app.css",
        head: tuple[Element, ...] = (),
        html_attributes: Mapping[str, str] | None = None,
        body_attributes: Mapping[str, str] | None = None,
    ):
        self.entry_point = entry_point
        self.name = name
        self.pages = pages
        self.layout_id = layout_id
        self.javascript_name = javascript_name
        self.stylesheet_name = stylesheet_name
        self.head = head
        self.html_attributes = (
            {"lang": "en"} if html_attributes is None else dict(html_attributes)
        )
        self.body_attributes = dict(body_attributes or {})

    def static_path(self, filename: str) -> str:
        return f"{self.name}/{filename}"

    def build(self, output_directory: str | Path | None = None) -> tuple[Path, Path]:
        if output_directory is None:
            output_directory = self.default_output_directory()
        output_directory = Path(output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)

        javascript, stylesheet = bundle(
            self.entry_point,
            additional_entry_points=self.pages,
        )
        javascript_output = output_directory / self.javascript_name
        stylesheet_output = output_directory / self.stylesheet_name
        javascript_output.write_text(javascript, encoding="utf-8")
        stylesheet_output.write_text(stylesheet, encoding="utf-8")
        return javascript_output, stylesheet_output

    def default_output_directory(self) -> Path:
        module = import_module(self.entry_point.__module__)
        module_file = getattr(module, "__file__", None)
        if module_file is None:
            raise ValueError(
                "Cannot locate the Django application for this PyJS entry point; "
                "pass output_directory to build()."
            )
        app_config = apps.get_containing_app_config(str(Path(module_file).resolve()))
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
    ) -> Element:
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
                        "src": static(self.static_path(self.javascript_name)),
                        "type": "module",
                    },
                    " ",
                ),
            ),
        )

    def response(
        self,
        request: HttpRequest,
        content: Element,
        *,
        title: str,
        shell: Shell | None = None,
        head: tuple[Element, ...] = (),
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        if shell is not None:
            content = shell(content)
        source = render_document(self.create_document(content, title=title, head=head))
        return HttpResponse(
            source,
            status=status,
            content_type="text/html; charset=utf-8",
            headers=headers,
        )

    def navigation_response(
        self,
        request: HttpRequest,
        content: Element,
        *,
        title: str,
        shell: Shell,
        head: tuple[Element, ...] = (),
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        if self.layout_id is None:
            raise ValueError("navigation_response() requires layout_id")

        if request.headers.get(NAVIGATION_HEADER) == "1":
            source = navigation_fragment(content, title, self.layout_id)
            response = HttpResponse(
                source,
                status=status,
                content_type="text/html; charset=utf-8",
                headers=headers,
            )
        else:
            response = self.response(
                request,
                content,
                title=title,
                shell=shell,
                head=head,
                status=status,
                headers=headers,
            )
        patch_vary_headers(response, (NAVIGATION_HEADER,))
        return response
