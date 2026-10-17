import pytest

from pyjs import js
from pyjs.testing.helpers import at
from pyjs.web.dom import Comment, Node, ProcessingInstruction, Text
from pyjs.web.domx import div, span
from pyjs.web.ssr import raw_html, render_html


@js
def check_element_text_content():
    child = span("nested")
    text = Text("tail")
    parent = div({"title": "kept"}, "first", child)
    parent.append(Comment("ignored"), text)
    assert parent.textContent == "firstnestedtail"
    text.data = "updated"
    assert parent.textContent == "firstnestedupdated"
    nodes = parent.childNodes
    children = parent.children
    first = nodes[0]
    parent.textContent = "<b>& café"
    assert parent.textContent == "<b>& café"
    assert parent.getAttribute("title") == "kept"
    assert nodes.length == 1
    assert children.length == 0
    assert child.parentNode is None
    assert text.parentNode is None
    assert first.parentNode is None
    parent.textContent = None
    assert parent.textContent == ""
    assert nodes.length == 0
    parent.textContent = ""
    assert nodes.length == 0


def test_element_text_content_replaces_children_and_preserves_attributes():
    check_element_text_content()


@pytest.mark.pyjs_web
@js
def test_browser_element_text_content():
    check_element_text_content()


def test_text_content_keeps_native_property_syntax_and_types():
    at('''
from pyjs import js
from pyjs.web.dom import Element, Node

@js
def read_node(node: Node) -> str | None:
    return node.textContent

def main(element: Element) -> str:
    read_node(element)
    element.textContent = None
    return element.textContent
''', '''
def read_node(node: Node) -> str | None:
    return node.textContent

def main(element: Element) -> str:
    read_node(element)
    element.textContent = None
    return element.textContent
''', '''
export function read_node(node) {
    return node.textContent;
}

export function main(element) {
    read_node(element);
    element.textContent = null;
    return element.textContent;
}
''')


def test_node_fallback_storage_is_independent_of_element_text():
    node = Node()
    assert node.textContent == ""
    node.textContent = "fallback"
    assert node.textContent == "fallback"
    node.textContent = None
    assert node.textContent is None
    element = div("element")
    assert element.textContent == "element"


def test_text_content_is_iterative_and_ignores_non_text_data():
    element = div("<&")
    element.append(Text("text"), Comment("comment"), ProcessingInstruction("target", "instruction"))
    for _ in range(3000):
        element = div(element)
    assert element.textContent == "<&text"


def test_text_content_conversion_precedes_mutation_and_strips_trust():
    child = span("old")
    element = div({"title": "kept"}, child)

    class Failing:
        def __str__(self):
            element.setAttribute("changed", "yes")
            raise ValueError("conversion")

    with pytest.raises(ValueError, match="conversion"):
        element.textContent = Failing()
    assert element.textContent == "old"
    assert child.parentNode is element
    assert element.getAttribute("changed") == "yes"
    element.textContent = raw_html("<b>&</b>")
    assert render_html(element) == '<div title="kept" changed="yes">&lt;b&gt;&amp;&lt;/b&gt;</div>'
    assert child.parentNode is None

    class MarkupResult(str):
        def __str__(self):
            return raw_html("<em>text</em>")

    element.textContent = MarkupResult("ignored")
    assert element.textContent == "<em>text</em>"
    assert render_html(element) == '<div title="kept" changed="yes">&lt;em&gt;text&lt;/em&gt;</div>'
    # RawHTML already stored as a child remains an opaque SSR fragment: this
    # fallback is not an HTML parser. Assigning it above strips its trust marker.
    assert div(raw_html("<b>opaque</b>")).textContent == "<b>opaque</b>"
