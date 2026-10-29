"""Server-side document rendering shared by backend integrations."""

from pyjs.web.domx import HTMLElement, tag
from pyjs.web.navigation import navigation_page
from pyjs.web.ssr import render_document, render_html, write_html


class NavigationPage:
    """Server response metadata for progressively navigated content."""

    def __init__(
        self, body: HTMLElement, title: str, status: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.body = body
        self.title = title
        self.status = status
        self.headers: dict[str, str] = headers if headers else {}


def html(body, js, css, script_type, title=""):
    """Create an HTML document element around a body and generated assets."""
    return tag(
        "html",
        tag(
            "head",
            tag("meta", {"charset": "utf-8"}),
            tag("meta", {"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            tag("title", title),
            tag("link", {"rel": "icon", "href": "data:,"}),
            tag("link", {"rel": "stylesheet", "href": css}),
        ),
        tag("body", body),
        tag("script", {"type": script_type, "src": js}, " "),
    )


def page(body, js, css, script_type="module", title=""):
    """Serialize a complete server-rendered application page."""
    return render_document(html(body, js, css, script_type, title))


def navigation_fragment(body, title, layout_id, bundle=None):
    """Serialize content and metadata for progressive page navigation."""
    return render_html(
        tag(
            "div",
            tag("title", title),
            navigation_page(body, layout_id, bundle),
        )
    )


def write(parent: HTMLElement, source):
    """Replace a DOM parent's children from trusted server-rendered HTML."""
    write_html(parent, source)
