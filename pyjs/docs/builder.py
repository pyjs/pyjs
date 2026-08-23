import html
import json
import os
import posixpath
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from pyjs.transpiler import TranspiledJavaScript, bundle_with_source_map
from pyjs.web.domx import tag
from pyjs.web.ssr import raw_html, render_document

from .config import DocsConfig, load_config
from .markdown import parse_document, render_markdown
from .models import NavNode, Page
from .navigation import build_navigation, humanize, navigation_pages, route_for
from .ui import main as docs_main

LINK = re.compile(r'(?P<attribute>href|src)="(?P<url>[^"]+)"')
FIRST_HEADING = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL)
FIRST_HEADING_ID = re.compile(r'<h1[^>]*\bid="([^"]+)"')
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def _prefixed_route(route: str, prefix: str) -> str:
    prefix = prefix.strip("/")
    if not prefix:
        return route
    if route == "/":
        return f"/{prefix}/"
    return f"/{prefix}{route}"


def _page_title(html_source: str, fallback: str) -> str:
    match = FIRST_HEADING.search(html_source)
    if match is None:
        return fallback
    return html.unescape(TAG.sub("", match.group(1))).replace("¶", "").strip()


def _discover_pages(config: DocsConfig) -> list[Page]:
    if not config.docs_dir.is_dir():
        raise FileNotFoundError(f"Documentation directory does not exist: {config.docs_dir}")
    pages = []
    routes = {}
    for source_path in sorted(config.docs_dir.rglob("*.md")):
        if any(part.startswith(".") for part in source_path.relative_to(config.docs_dir).parts):
            continue
        relative_path = source_path.relative_to(config.docs_dir)
        metadata, source = parse_document(source_path)
        rendered, headings, inferred_description = render_markdown(source)
        source_route = route_for(relative_path)
        route = _prefixed_route(source_route, config.route_prefix)
        if route in routes:
            raise ValueError(f"{source_path} and {routes[route]} both produce the route {route!r}")
        routes[route] = source_path
        route_parts = route.strip("/").split("/") if route != "/" else []
        output_path = config.site_dir.joinpath(*route_parts, "index.html")
        fallback = humanize(relative_path.stem)
        default_order = 0 if source_route == "/" else 1000
        pages.append(
            Page(
                source_path=source_path,
                relative_path=relative_path,
                output_path=output_path,
                route=route,
                title=str(metadata.get("title", _page_title(rendered, fallback))),
                description=str(metadata.get("description", inferred_description)),
                order=float(metadata.get("order", default_order)),
                hidden=bool(metadata.get("hidden", False)),
                html=rendered,
                headings=headings,
            )
        )
    if not pages:
        raise ValueError(f"No Markdown pages found in {config.docs_dir}")
    return pages


def _relative_url(page: Page, target: Page, fragment: str = "") -> str:
    relative = os.path.relpath(target.output_path.parent, page.output_path.parent)
    relative = relative.replace(os.sep, "/")
    href = "./" if relative == "." else relative.rstrip("/") + "/"
    return href + fragment


def _site_root_url(page: Page, config: DocsConfig) -> str:
    relative = os.path.relpath(config.site_dir, page.output_path.parent).replace(os.sep, "/")
    return "./" if relative == "." else relative.rstrip("/") + "/"


def _docs_output_root(config: DocsConfig) -> Path:
    return config.site_dir / config.route_prefix.strip("/")


def _docs_home(pages: list[Page]) -> Page:
    return next(
        (page for page in pages if page.relative_path == Path("index.md")),
        pages[0],
    )


def _rewrite_links(page: Page, pages: list[Page], config: DocsConfig) -> str:
    by_source = {candidate.relative_path: candidate for candidate in pages}

    def replace(match: re.Match):
        url = match.group("url")
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or url.startswith(("#", "/")):
            return match.group(0)
        source_target = page.relative_path.parent / parsed.path
        normalized = Path(posixpath.normpath(source_target.as_posix()))
        target_page = by_source.get(normalized)
        if target_page is not None:
            suffix = f"#{parsed.fragment}" if parsed.fragment else ""
            rewritten = _relative_url(page, target_page, suffix)
        else:
            asset = config.docs_dir / normalized
            if not asset.is_file():
                return match.group(0)
            relative = os.path.relpath(
                _docs_output_root(config) / normalized,
                page.output_path.parent,
            ).replace(os.sep, "/")
            rewritten = relative
            if parsed.fragment:
                rewritten += f"#{parsed.fragment}"
        return f'{match.group("attribute")}="{html.escape(rewritten, quote=True)}"'

    return LINK.sub(replace, page.html)


def _render_nav_node(node: NavNode, current: Page, depth: int) -> str:
    children = "".join(_render_nav_node(child, current, depth + 1) for child in node.children)
    link = ""
    if node.page is not None:
        current_attribute = ' aria-current="page"' if node.page is current else ""
        link = (
            f'<a class="nav-link" href="{_relative_url(current, node.page)}"'
            f"{current_attribute}>{html.escape(node.title)}</a>"
        )
    elif depth > 0:
        link = f'<p class="nav-heading">{html.escape(node.title)}</p>'
    if children:
        list_class = "nav-list" if depth == 0 else "nav-nested"
        children = f'<ul class="{list_class}">{children}</ul>'
    if depth == 0:
        return children
    return f'<li class="nav-group">{link}{children}</li>'


def _render_navigation(root: NavNode, current: Page) -> str:
    return _render_nav_node(root, current, 0)


def _render_outline(page: Page, config: DocsConfig) -> str:
    links = []
    for heading in page.headings:
        if heading.level == 1:
            continue
        links.append(
            f'<li><a class="outline-link outline-level-{heading.level}" '
            f'href="#{html.escape(heading.id, quote=True)}">'
            f"{html.escape(heading.title)}</a></li>"
        )
    edit_link = ""
    if config.repo_url:
        source_path = page.source_path.relative_to(config.project_root).as_posix()
        edit_link = (
            f'<a class="outline-edit" href="{html.escape(config.repo_url, quote=True)}'
            f'/edit/main/{html.escape(source_path, quote=True)}">Edit this page on GitHub</a>'
        )
    if not links and not edit_link:
        return ""
    return (
        '<p class="outline-title">On this page</p>'
        f'<ul class="outline-list">{"".join(links)}</ul>{edit_link}'
    )


def _render_breadcrumbs(page: Page, pages: list[Page]) -> str:
    home = _docs_home(pages)
    crumbs = ['<a href="' + _relative_url(page, home) + '">Docs</a>']
    for part in page.relative_path.parent.parts:
        crumbs.append(f"<span>/</span><span>{html.escape(humanize(part))}</span>")
    return f'<nav class="breadcrumbs" aria-label="Breadcrumb">{"".join(crumbs)}</nav>'


def _pager_link(page: Page, target: Page | None, direction: str) -> str:
    if target is None:
        return "<span></span>"
    css_direction = "pager-next" if direction == "Next" else "pager-previous"
    return (
        f'<a class="pager-link {css_direction}" href="{_relative_url(page, target)}">'
        f'<span class="pager-direction">{direction}</span>'
        f'<span class="pager-title">{html.escape(target.title)}</span></a>'
    )


def _render_article(page: Page, pages: list[Page], config: DocsConfig) -> str:
    description = ""
    if page.description:
        description = f'<p class="page-description">{html.escape(page.description)}</p>'
    section = (
        humanize(page.relative_path.parts[0]) if len(page.relative_path.parts) > 1 else "Guide"
    )
    pager = (
        '<nav class="docs-pager" aria-label="Documentation pages">'
        f"{_pager_link(page, page.previous, 'Previous')}"
        f"{_pager_link(page, page.next, 'Next')}</nav>"
    )
    content = FIRST_HEADING.sub("", _rewrite_links(page, pages, config), count=1)
    title_id = ""
    title_match = FIRST_HEADING_ID.search(page.html)
    if title_match is not None:
        title_id = f' id="{html.escape(title_match.group(1), quote=True)}"'
    return (
        '<article class="docs-article">'
        f"{_render_breadcrumbs(page, pages)}"
        f'<p class="page-eyebrow">{html.escape(section)}</p>'
        f'<h1 class="page-title"{title_id}>{html.escape(page.title)}</h1>'
        f"{description}"
        f'<div class="docs-content">{content}</div>'
        f"{pager}</article>"
    )


def _search_records(pages: list[Page], current: Page) -> str:
    records = []
    for page in pages:
        text = html.unescape(SPACE.sub(" ", TAG.sub(" ", page.html))).replace("¶", "").strip()
        records.append(
            {
                "title": page.title,
                "section": humanize(page.relative_path.parent.name or "Guide"),
                "text": text[:240],
                "url": _relative_url(current, page),
            }
        )
        for heading in page.headings:
            if heading.level == 1:
                continue
            records.append(
                {
                    "title": heading.title,
                    "section": page.title,
                    "text": text[:240],
                    "url": _relative_url(current, page, f"#{heading.id}"),
                }
            )
    return json.dumps(records, separators=(",", ":")).replace("</", "<\\/")


def _render_page(
    page: Page,
    pages: list[Page],
    navigation: NavNode,
    config: DocsConfig,
) -> str:
    asset_prefix = os.path.relpath(config.site_dir / "_pyjs", page.output_path.parent)
    asset_prefix = asset_prefix.replace(os.sep, "/")
    home = _docs_home(pages)
    site_root = _site_root_url(page, config)
    site_navigation = ""
    if config.route_prefix:
        site_navigation = raw_html(
            '<nav class="site-links" aria-label="Main navigation">'
            f'<a href="{site_root}">Home</a>'
            f'<a href="{_relative_url(page, home)}" aria-current="page">Docs</a>'
            f'<a href="{site_root}components/">Components</a>'
            f'<a href="{site_root}examples/">Examples</a>'
            f'<a href="{site_root}why-pyjs/">Why PyJS</a>'
            "</nav>"
        )
    project_links = []
    if config.repo_url:
        project_links.append(
            '<a aria-label="View the project on GitHub" '
            f'class="icon-button project-button github-button" '
            f'href="{html.escape(config.repo_url, quote=True)}">'
            "GitHub</a>"
        )
    for label, url, aria_label in (
        ("Discord", config.discord_url, "Join the project Discord"),
        ("X", config.x_url, "Follow the project on X"),
    ):
        if url:
            project_links.append(
                f'<a aria-label="{aria_label}" '
                f'class="icon-button project-button social-button" '
                f'href="{html.escape(url, quote=True)}">{label}</a>'
            )
    app = docs_main(
        config.site_name,
        _relative_url(page, home),
        raw_html(_render_navigation(navigation, page)),
        raw_html(_render_article(page, pages, config)),
        raw_html(_render_outline(page, config)),
        _search_records(pages, page),
        site_root,
        site_navigation,
        raw_html("".join(project_links)),
        config.version,
    )
    canonical = config.site_url.rstrip("/") + page.route if config.site_url else ""
    head_children = [
        tag("meta", {"charset": "utf-8"}),
        tag("meta", {"name": "viewport", "content": "width=device-width, initial-scale=1"}),
        tag("title", f"{page.title} · {config.site_name}"),
        tag("meta", {"name": "description", "content": page.description}),
        tag("link", {"rel": "icon", "href": f"{asset_prefix}/favicon.svg"}),
        tag("link", {"rel": "stylesheet", "href": f"{asset_prefix}/docs.css"}),
    ]
    if canonical:
        head_children.append(tag("link", {"rel": "canonical", "href": canonical}))
    document = tag(
        "html",
        {"lang": "en"},
        tag("head", *head_children),
        tag(
            "body",
            app,
            tag("script", {"src": f"{asset_prefix}/docs.js", "type": "module"}, " "),
        ),
    )
    return render_document(document)


def _copy_assets(config: DocsConfig):
    for source in config.docs_dir.rglob("*"):
        if not source.is_file() or source.suffix == ".md":
            continue
        relative = source.relative_to(config.docs_dir)
        if any(part.startswith(".") for part in relative.parts):
            continue
        target = _docs_output_root(config) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def build(
    config: DocsConfig | None = None,
    *,
    clean: bool = True,
    client_bundle: tuple[TranspiledJavaScript, str] | None = None,
) -> Path:
    config = config or load_config()
    if config.site_dir == config.docs_dir or config.docs_dir in config.site_dir.parents:
        raise ValueError("Documentation output must be outside the source directory")
    pages = _discover_pages(config)
    navigation = build_navigation(pages)
    ordered_pages = navigation_pages(navigation)
    hidden_pages = [page for page in pages if page.hidden]
    pages = ordered_pages + hidden_pages
    for index, page in enumerate(ordered_pages):
        page.previous = ordered_pages[index - 1] if index else None
        page.next = ordered_pages[index + 1] if index + 1 < len(ordered_pages) else None

    if clean:
        shutil.rmtree(config.site_dir, ignore_errors=True)
    assets_dir = config.site_dir / "_pyjs"
    assets_dir.mkdir(parents=True)
    if client_bundle is None:
        client_bundle = bundle_with_source_map(
            docs_main,
            include_css=False,
            filename="docs.js",
        )
    generated, generated_css = client_bundle
    docs_css = Path(__file__).with_name("style.css").read_text(encoding="utf-8")
    (assets_dir / "docs.js").write_text(
        generated.with_source_mapping_url("docs.js.map"),
        encoding="utf-8",
    )
    (assets_dir / "docs.js.map").write_text(
        generated.source_map.to_json(),
        encoding="utf-8",
    )
    (assets_dir / "docs.css").write_text(generated_css + docs_css, encoding="utf-8")
    shutil.copy2(Path(__file__).with_name("favicon.svg"), assets_dir / "favicon.svg")
    _copy_assets(config)

    for page in pages:
        page.output_path.parent.mkdir(parents=True, exist_ok=True)
        page.output_path.write_text(
            _render_page(page, pages, navigation, config),
            encoding="utf-8",
        )
    home = _docs_home(pages)
    if not config.route_prefix:
        shutil.copy2(home.output_path, config.site_dir / "404.html")
    if config.nojekyll:
        (config.site_dir / ".nojekyll").touch()
    return config.site_dir
