import html
import os

from pyjs.decorators import ParameterLifetime, native_operation
from pyjs.web._dom_storage import _sync_attribute_nodes
from pyjs.web.dom import Element

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
_NOT_ELEMENT = object()


class RawHTML(str):
    """HTML that has been explicitly marked as trusted by server code."""


def raw_html(value: str) -> RawHTML:
    return RawHTML(value)


def _escape(value: str, *, quote: bool) -> str:
    if (
        "&" not in value
        and "<" not in value
        and ">" not in value
        and ((not quote) or ('"' not in value and "'" not in value))
    ):
        return value
    return html.escape(value, quote=quote)


def _html_fragments(root: Element):
    fragments = []
    stack = []
    dynamic_tags = {}
    item = root
    while True:
        item_type = type(item)
        if item_type is str:
            fragments.append(_escape(item, quote=False))
        else:
            if isinstance(item, Element):
                tag_name = item_type.__pyjs_ssr_tag_name__
            else:
                tag_name = _NOT_ELEMENT
                if isinstance(item, RawHTML):
                    fragments.append(item)
                elif isinstance(item, str):
                    fragments.append(_escape(item, quote=False))
                else:
                    value = item.data
                    fragments.append(
                        value
                        if isinstance(value, RawHTML)
                        else _escape(value, quote=False)
                    )
            if tag_name is not _NOT_ELEMENT:
                if tag_name is None:
                    raw_tag_name = item.tagName
                    cached_tag = dynamic_tags.get(raw_tag_name)
                    if cached_tag is None:
                        tag_name = raw_tag_name.lower()
                        cached_tag = (
                            tag_name,
                            f"<{tag_name}",
                            f"</{tag_name}>",
                        )
                        dynamic_tags[raw_tag_name] = cached_tag
                    tag_name, open_tag, close_tag = cached_tag
                else:
                    open_tag = item_type.__pyjs_ssr_open__
                    close_tag = item_type.__pyjs_ssr_close__
                try:
                    parts = item._pyjs_parts
                except AttributeError:
                    parts = None
                attribute_count = 0 if parts is None else parts[0]
                materialized_attributes = attribute_count < 0
                if materialized_attributes:
                    attribute_count = -attribute_count
                child_offset = 1 + attribute_count
                if materialized_attributes:
                    _sync_attribute_nodes(item, parts)
                fragments.append(open_tag)
                # A 350-row settings benchmark found individual
                # appends faster for the common one-to-four-attribute case;
                # slicing plus extend remains faster for larger groups.
                if attribute_count == 1:
                    fragments.append(parts[1])
                elif attribute_count == 2:
                    fragments.append(parts[1])
                    fragments.append(parts[2])
                elif attribute_count == 3:
                    fragments.append(parts[1])
                    fragments.append(parts[2])
                    fragments.append(parts[3])
                elif attribute_count == 4:
                    fragments.append(parts[1])
                    fragments.append(parts[2])
                    fragments.append(parts[3])
                    fragments.append(parts[4])
                elif attribute_count:
                    fragments.extend(parts[1:child_offset])
                if parts is not None and child_offset < len(parts):
                    fragments.append(">")
                    stack.append(parts)
                    stack.append(child_offset + 1)
                    stack.append(close_tag)
                    item = parts[child_offset]
                    continue
                if tag_name not in VOID_ELEMENTS:
                    fragments.append(">")
                    fragments.append(close_tag)
                else:
                    fragments.append("/>")
        while stack:
            parts = stack[-3]
            child_index = stack[-2]
            if child_index < len(parts):
                stack[-2] = child_index + 1
                item = parts[child_index]
                break
            fragments.append(stack[-1])
            del stack[-3:]
        else:
            return fragments


def write_html(parent: Element, output):
    output.write("".join(_html_fragments(parent)))


@native_operation(
    "write_html_fd",
    element=ParameterLifetime.BORROWED,
    descriptor=ParameterLifetime.BORROWED,
)
def write_html_fd(element: Element, descriptor: int) -> int:
    """Write one rendered element to a POSIX descriptor.

    Native compilation streams the DOM directly without first materializing a
    CPython string.  The ordinary implementation preserves the same short
    write, interruption, and errno behavior for parity tests and server use.
    """
    data = memoryview(render_html(element).encode())
    try:
        while data:
            try:
                written = os.write(descriptor, data)
            except InterruptedError:
                continue
            if written <= 0:
                return 5
            data = data[written:]
    except OSError as error:
        return error.errno or 5
    return 0


@native_operation("render_html", element=ParameterLifetime.BORROWED)
def render_html(element: Element) -> str:
    return "".join(_html_fragments(element))


@native_operation("render_document", element=ParameterLifetime.BORROWED)
def render_document(element: Element) -> str:
    return "<!doctype html>\n" + render_html(element)
