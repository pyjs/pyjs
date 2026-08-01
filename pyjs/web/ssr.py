import html
from io import StringIO

from pyjs.web.domx import HTMLElement

VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class RawHTML(str):
    """HTML that has been explicitly marked as trusted by server code."""


def raw_html(value: str) -> RawHTML:
    return RawHTML(value)


def write_html(parent: HTMLElement, output):
    tag_name = parent.tagName.lower()
    start = [f"<{tag_name}"]
    for attribute in parent.attributes:
        name = attribute.name
        value = attribute.value
        if value is not None:
            start.append(f' {name}="{html.escape(str(value), quote=True)}"')
    for name, value in parent.dataset.map.items():
        if value is not None:
            start.append(f' data-{name}="{html.escape(str(value), quote=True)}"')

    if parent.childNodes:
        start.append(">")
        output.write("".join(start))
        for child in parent.childNodes:
            if isinstance(child, HTMLElement):
                write_html(child, output)
            else:
                value = child.data
                if isinstance(value, RawHTML):
                    output.write(value)
                else:
                    output.write(html.escape(value, quote=False))
        output.write(f"</{tag_name}>")
    elif tag_name not in VOID_ELEMENTS:
        output.write("".join(start) + f"></{tag_name}>")
    else:
        output.write("".join(start) + "/>")


def render_html(element: HTMLElement) -> str:
    output = StringIO()
    write_html(element, output)
    return output.getvalue()


def render_document(element: HTMLElement) -> str:
    return "<!doctype html>\n" + render_html(element)
