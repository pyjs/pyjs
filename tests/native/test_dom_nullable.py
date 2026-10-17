"""Nullable builder contracts retained from the foundation implementation.

Direct child calls keep their declared Element | str boundary. Expanded packs
retain their actual kinds until the selected builtin or override consumes them.
"""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_builders_evaluate_arguments_then_fail_and_recover(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import Document, gc_collect, gc_set_threshold
from pyjs.native import div as native_div
from pyjs.web.dom import Element
from pyjs.web.domx import div, span, tag
from pyjs.web.ssr import render_html
from typing import Iterator
def forwarded(*values: str | Element | None) -> Element:
    return div(*values)
def stream(events: list[int]) -> Iterator[str | None]:
    yield "stream"
    events.append(1)
    yield None
    events.append(2)
    gc_collect()
    yield "lost"
def observe(events: list[int], fail: bool = False) -> str:
    events.append(1)
    gc_collect()
    if fail:
        raise ValueError("argument first")
    return "after"
def main() -> str:
    gc_set_threshold(1)
    result = ""
    child: Element = span("child")
    strings: list[str | None] = ["first", None, "last"]
    elements: list[Element | None] = [child, None, child]
    mixed: list[str | Element | None] = ["first", child, None, "last"]
    document = Document()
    for mode in range(9):
        events: list[int] = []
        target = div("old")
        try:
            if mode == 0:
                target = div(*strings, observe(events))
            elif mode == 1:
                target = div(*elements, observe(events))
            elif mode == 2:
                target = forwarded(*mixed, observe(events))
            elif mode == 3:
                tag(target, {"phase": "kept"}, *mixed, observe(events))
            elif mode == 4:
                native_div(document, *strings, observe(events))
            elif mode == 5:
                target = div(None, observe(events))
            elif mode == 6:
                tag(target, *mixed, observe(events, True))
            elif mode == 7:
                target = div(None, observe(events, True))
            else:
                tag(target, *stream(events))
        except TypeError as error:
            result += "type:" + str(error)
        except ValueError as error:
            result += str(error)
        else:
            return "missing error"
        assert events == ([1, 2] if mode == 8 else [1])
        gc_collect()
        result += render_html(target)
        target.append("retry")
        result += render_html(target)
    present: list[str | Element | None] = ["ok", child]
    return result + render_html(forwarded(*present))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_mapping_and_proxy_children_keep_prefix_and_failure_kind(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.domx import ProxyElement, div, tag
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self):
        self.element = div("proxy")
def main() -> str:
    target = div("root")
    attrs: list[dict[str, str] | None] = [{"phase": "kept"}, None]
    children: list[ProxyElement | None] = [Box(), None]
    result = ""
    for mode in range(3):
        try:
            if mode == 0:
                tag(target, *attrs)
            else:
                tag(target, *children)
        except TypeError:
            result += "none:"
        except AttributeError:
            result += "missing:"
        else:
            return "missing error"
        gc_collect()
        result += render_html(target)
        if mode == 1:
            children[1] = ProxyElement()
    empty: list[dict[str, str] | None] = []
    return result + render_html(div(*empty))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("method", ["append", "replaceChildren"])
@pytest.mark.parametrize("value", ["None", '{"title": "ignored"}'])
def test_direct_child_methods_retain_their_declared_argument_contract(method, value):
    with pytest.raises(CompilationError, match="expects WebElement\\|str"):
        transpile_llvm('''
from pyjs.web.domx import div
def main() -> int:
    div().''' + method + '(' + value + ''')
    return 0
''')


@pytest.mark.parametrize("target", ['"div"', 'div()'])
def test_static_tag_arguments_keep_analyzer_diagnostics(target):
    with pytest.raises(CompilationError, match="Argument 'args' to tag expects"):
        transpile_llvm('''
from pyjs.web.domx import div, tag
def main() -> int:
    tag(''' + target + ''', None)
    return 0
''')


@pytest.mark.parametrize("expression", ['div(1)', 'div(*values)'])
def test_scalar_child_diagnostic_does_not_reject_optional_dom_types(expression):
    with pytest.raises(LLVMUnsupported) as caught:
        transpile_llvm('''
from pyjs.web.domx import div
def main() -> int:
    values: list[int | None] = [1, None]
    ''' + expression + '''
    return 0
''')
    assert str(caught.value) == "LLVM DOM children require elements or strings at line 3"


def test_union_argument_does_not_hide_invalid_attribute_map_keys():
    with pytest.raises(LLVMUnsupported) as caught:
        transpile_llvm('''
from pyjs.web.domx import div
def main() -> int:
    values: list[str | dict[int, str]] = ["text", {1: "value"}]
    div(*values)
    return 0
''')
    assert str(caught.value) == "LLVM DOM attributes require dict[str, str] at line 3"
