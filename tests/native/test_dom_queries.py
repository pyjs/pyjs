import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_query_selector_is_an_effect_preserving_ssr_standin(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, input, require_element
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    pass
def selector(root: Element, events: list[str]) -> str:
    events.append("selector")
    root.setAttribute("data-called", "yes")
    gc_collect()
    return "[missing]"
def fail() -> str:
    raise ValueError("selector failure")
def check(root: Element) -> str:
    events: list[str] = []
    selected = root.querySelector(selector=selector(root, events))
    assert selected is root
    if selected is None:
        return "missing"
    selected.classList.add("selected")
    assert root.querySelector(*("[missing]",)) is root
    assert root.querySelector(**{"selector": ""}) is root
    assert require_element(root, "not a browser selector") is root
    try:
        root.querySelector(fail())
    except ValueError:
        events.append("caught")
    try:
        options = {"selector": "y"}
        root.querySelector("x", **options)
    except TypeError:
        events.append("duplicate")
    gc_collect()
    return str(events) + render_html(root)
def main() -> str:
    gc_set_threshold(1)
    return check(div("child")) + check(input()) + check(Panel())
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_query_selector_concrete_override_and_super_dispatch(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div
class Panel(CustomElement):
    def querySelector(self, selector: str) -> Element | None:
        gc_collect()
        if selector == "none":
            return None
        return super().querySelector(selector)
class Other(CustomElement):
    def querySelector(self, selector: str) -> Element | None:
        return div(selector)
def main() -> int:
    panel = Panel()
    assert panel.querySelector("self") is panel
    assert panel.querySelector("none") is None
    nodes: list[Panel | Other] = [panel, Other()]
    count = 0
    for node in nodes:
        selected = node.querySelector("text")
        if selected is not None:
            count += 1
    return count
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_opaque_query_dispatches_reached_override(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    def querySelector(self, selector: str) -> Element | None:
        return None
def query(root: Element) -> Element | None:
    return root.querySelector("x")
def main() -> int:
    return int(query(Panel()) is None)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_require_element_dispatches_reached_query_override(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, require_element
class Panel(CustomElement):
    def querySelector(self, selector: str) -> Element | None:
        return None
def main() -> int:
    panel = Panel()
    assert panel.querySelector("x") is None
    try:
        require_element(panel, "missing")
        return -1
    except ValueError as error:
        assert str(error) == "Required element not found: missing"
    return int(require_element(div(), "x") is not None)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
