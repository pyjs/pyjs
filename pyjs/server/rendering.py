"""Server-side document rendering shared by backend integrations."""

from pyjs.web.domx import HTMLElement, tag
from pyjs.web.navigation import navigation_page
from pyjs.web.ssr import render_document, render_html, write_html


class NavigationPage:
    def __init__(self, body, title, status=200, headers=None):
        self.body = body
        self.title = title
        self.status = status
        self.headers = headers or {}


def html(body, js, css, script_type, title=""):
    return tag(
        "html",
        tag(
            "head",
            tag("meta", {"charset": "utf-8"}),
            tag("title", title),
            tag("link", {"rel": "icon", "href": "data:,"}),
            tag("link", {"rel": "stylesheet", "href": css}),
        ),
        tag("body", body),
        tag("script", {"type": script_type, "src": js}, " "),
    )


def page(body, js, css, script_type="module", title=""):
    return render_document(html(body, js, css, script_type, title))


def navigation_fragment(body, title, layout_id, bundle=None):
    return render_html(
        tag(
            "div",
            tag("title", title),
            navigation_page(body, layout_id, bundle),
        )
    )


def write(parent: HTMLElement, source):
    write_html(parent, source)
