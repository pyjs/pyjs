"""Erased child packs share binding, but not domx's attribute interpretation."""

import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_exact_optional_child_receiver_selects_nonuniform_override(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, span
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def append(self, *nodes: Element | str) -> None:
        super().append("base", *nodes)
class Changed(Panel):
    def append(self, first: Element | str = "first", *nodes: Element | str, tail: str = "tail") -> None:
        gc_collect()
        super().append(first, *nodes, tail)
def update(item: Panel | None, nodes: list[object]) -> str:
    if item is None:
        return "absent"
    item.append(*nodes)
    item.append(*[])
    gc_collect()
    return render_html(item)
def main() -> str:
    gc_set_threshold(1)
    result = update(Panel(), ["one", span("two")])
    result += update(Changed(), ["three", span("four")])
    opaque: Element = Changed()
    if isinstance(opaque, Panel):
        values: list[object] = ["narrowed", span("child")]
        opaque.append(*values)
        result += render_html(opaque)
    return result + update(None, [])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["append", "replaceChildren"])
@pytest.mark.parametrize("annotation, fallback", [
    ("Element", 'div("old")'),
    ("Element | Panel", 'div("old")'),
    ("Panel | Element", 'div("old")'),
    ("Panel | Child", "Child()"),
    ("Child | Panel", "Child()"),
    ("Panel", "Panel()"),
])
def test_erased_children_project_into_typed_overrides(tmp_path, optimize, method, annotation, fallback):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, span
from pyjs.web.ssr import render_html
class Child(CustomElement):
    pass
class Panel(CustomElement):
    def __init__(self, *children):
        super().__init__()
        self.calls = 0
        self.replaceChildren(*children)
    def append(self, *children: Element | str) -> None:
        self.calls += 1
        gc_collect()
        super().append("<", *children, ">")
def stream(values: list[object], events: list[str]) -> Iterator[object]:
    for value in values:
        events.append("yield")
        gc_collect()
        yield value
def later(values: list[object], events: list[str]) -> str:
    values.clear()
    events.append("later")
    gc_collect()
    return "tail"
def update(item: ANNOTATION, values: list[object], events: list[str]) -> None:
    item.METHOD(*stream(values, events), later(values, events))
    direct: list[object] = ["direct", span("nested"), Child()]
    item.METHOD(*direct)
def main() -> str:
    gc_set_threshold(1)
    panel = Panel("constructor", span("initial"), Child())
    result = render_html(panel)
    items: list[ANNOTATION] = [panel, FALLBACK]
    events: list[str] = []
    for item in items:
        values: list[object] = ["<&", span("node"), Child()]
        update(item, values, events)
        assert not values
        result += render_html(item)
    return result + repr(events) + str(panel.calls)
'''.replace("METHOD", method).replace("ANNOTATION", annotation).replace("FALLBACK", fallback),
        directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Element", "Element | Panel", "Panel"])
def test_erased_override_binding_projects_fixed_keyword_and_variadic_values(tmp_path, optimize, annotation):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, span
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def append(self, first: Element | str, *children: Element | str,
               tail: Element | str = "default", **extras: Element | str) -> None:
        self.calls += 1
        gc_collect()
        super().append(first, *children, tail)
        for value in extras.values():
            super().append(value)
def invoke(item: VIEW, values: list[object], keywords: dict[str, object]) -> None:
    item.append(*values, **keywords)
def direct(item: VIEW, values: list[object]) -> None:
    item.replaceChildren(*values)
def invalid(events: list[str]) -> Iterator[object]:
    events.append("invalid")
    yield 42
    events.append("exhausted")
def raising(events: list[str]) -> str:
    events.append("raising")
    gc_collect()
    raise ValueError("later operand")
def failed(item: VIEW, events: list[str]) -> None:
    item.append(*invalid(events), raising(events))
def main() -> str:
    gc_set_threshold(1)
    panel = Panel()
    values: list[object] = [span("first"), "second"]
    keywords: dict[str, object] = {"tail": span("tail"), "extra": "extra"}
    invoke(panel, values, keywords)
    direct(panel, values)
    invoke(panel, [], {"first": "named"})
    result = render_html(panel)
    events: list[str] = []
    try:
        failed(panel, events)
    except ValueError:
        events.append("caught")
    try:
        invoke(panel, [42], {"first": "duplicate"})
    except TypeError as error:
        assert "multiple values" in str(error)
        events.append("duplicate")
    try:
        invoke(panel, [], {})
    except TypeError:
        events.append("missing")
    assert panel.calls == 4
    assert render_html(panel) == result
    invoke(panel, ["retry"], {})
    return result + render_html(panel) + repr(events)
'''.replace("VIEW", annotation), directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method, calls", [("append", 0), ("replaceChildren", 1)])
@pytest.mark.parametrize("annotation", ["Element", "Panel | Element", "Panel"])
def test_invalid_erased_override_child_checks_before_consumption(tmp_path, optimize, method, calls, annotation):
    # CPython ignores annotations; native typed overrides must reject an int
    # rather than feed its bits into Element | str storage. Check that boundary
    # explicitly, including evaluation order and replaceChildren's cleared prefix.
    source = '''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def append(self, *children: Element | str) -> None:
        self.calls += 1
        gc_collect()
        super().append(*children)
def stream(values: list[object], events: list[str]) -> Iterator[object]:
    for value in values:
        events.append("yield")
        yield value
def later(events: list[str]) -> str:
    events.append("later")
    gc_collect()
    return "tail"
def update(item: VIEW, values: list[object], events: list[str]) -> None:
    item.METHOD(*stream(values, events), later(events))
def main() -> int:
    gc_set_threshold(1)
    panel = Panel()
    events: list[str] = []
    values: list[object] = ["first", 42, "last"]
    try:
        update(panel, values, events)
    except TypeError:
        pass
    else:
        return 1
    assert panel.calls == CALLS
    assert events == ["yield", "yield", "yield", "later"]
    assert ("first" in render_html(panel)) == (CALLS == 1)
    assert "last" not in render_html(panel)
    assert "tail" not in render_html(panel)
    assert len(values) == 3
    update(panel, ["retry"], events)
    assert "retry" in render_html(panel)
    assert "tail" in render_html(panel)
    return 0
'''.replace("METHOD", method).replace("CALLS", str(calls)).replace("VIEW", annotation)
    executable = LLVM().compile(transpile_llvm(source), tmp_path, optimize=optimize,
                                sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, timeout=15)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_constructor_forwards_untyped_children_and_keywords(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement, div
from pyjs.web.ssr import render_html
class Child(CustomElement):
    def __init__(self):
        super().__init__()
        self.label = "kept"
        self.append(self.label)
class Panel(CustomElement):
    def __init__(self, caption: str, *children, **attributes: str):
        super().__init__()
        gc_collect()
        self.append(caption, *children)
        for name, value in attributes.items():
            self.setAttribute(name, value)
def stream(events: list[int]) -> Iterator[str]:
    events.append(1)
    yield "first"
    events.append(2)
    yield "second"
def observe(events: list[int], value: int) -> str:
    events.append(value)
    gc_collect()
    return str(value)
def main() -> str:
    gc_set_threshold(1)
    child = Child()
    items = ("title", "text", child, div("opaque"))
    panel = Panel(*items, title="<&")
    events: list[int] = []
    pending = stream(events)
    duplicate = {"title": "duplicate"}
    try:
        Panel(*pending, title=observe(events, 3), **duplicate,
              later=observe(events, 99))
    except TypeError:
        events.append(4)
    following = next(pending)
    other = Panel(*stream(events), title=observe(events, 5))
    gc_collect()
    return render_html(panel) + render_html(other) + following + repr(events) + child.label
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_child_packs_keep_each_arm_and_erased_filter(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div, span
from pyjs.web.ssr import render_html
def update(item: Element, children: list[object] | tuple[str, str]) -> None:
    item.append(*children)
    gc_collect()
def main() -> str:
    gc_set_threshold(1)
    item = div()
    children: list[object] = [span("node"), 42, "tail", {"id": "ignored"}]
    update(item, children)
    update(item, ("<&", "two"))
    return render_html(item)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["append", "replaceChildren"])
def test_erased_child_super_calls_and_keyword_errors(tmp_path, optimize, method):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement, div
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def METHOD(self, *values):
        self.calls += 1
        gc_collect()
        super().METHOD(*values)
def ordinary(item: Panel, *values, **keywords: str) -> None:
    item.METHOD(*values, **keywords)
def main() -> str:
    gc_set_threshold(1)
    panel = Panel()
    ordinary(panel, "first", div("child"))
    before = render_html(panel)
    try:
        ordinary(panel, "not-published", unexpected="rejected")
    except TypeError:
        pass
    else:
        return "missing keyword error"
    assert panel.calls == 1
    assert render_html(panel) == before
    ordinary(panel, "last", **{})
    return before + render_html(panel) + str(panel.calls)
'''.replace("METHOD", method), directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["append", "replaceChildren"])
def test_erased_child_allocation_failure_does_not_publish_staged_values(tmp_path, optimize, method):
    source = transpile_llvm('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, span
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm, remaining
class Child(CustomElement):
    pass
def update(item: Element, *values) -> None:
    item.METHOD(*values)
def main() -> int:
    gc_set_threshold(1)
    child = Child()
    child.append("custom")
    values: list[object] = ["text", span("opaque"), child]
    point = 0
    stages = 1
    while point <= stages:
        item = div({"title": "kept"}, "old")
        before = render_html(item)
        failed = False
        arm(1000 if point == 0 else point)
        try:
            update(item, *values)
        except MemoryError:
            failed = True
        if point == 0:
            stages = 1000 - remaining()
        arm(0)
        assert stages > 0
        assert failed == (point != 0)
        gc_collect()
        if failed:
            assert render_html(item) == before
            update(item, *values)
        assert "text<span>opaque</span>" in render_html(item)
        item.replaceChildren("retry")
        assert render_html(item) == '<div title="kept">retry</div>'
        point += 1
    return 0
'''.replace("METHOD", method))
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["append", "replaceChildren"])
def test_erased_children_keep_python_body_filter_and_argument_order(tmp_path, optimize, method):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ProxyElement, div, span
from pyjs.web.ssr import render_html
class Child(CustomElement):
    pass
class Ignored:
    pass
def stream(values: list[object], events: list[str]) -> Iterator[object]:
    for value in values:
        events.append("yield")
        gc_collect()
        yield value
def later(item: Element, values: list[object], events: list[str], fail: bool = False) -> str:
    values.clear()
    item.append("callback")
    item.setAttribute("title", "late")
    events.append("later")
    gc_collect()
    if fail:
        raise ValueError("argument")
    return "tail"
def update(item: Element, values: list[object], events: list[str], fail: bool = False) -> None:
    item.METHOD(*stream(values, events), later(item, values, events, fail))
def main() -> str:
    gc_set_threshold(1)
    child = Child()
    child.append("custom")
    item = div({"title": "old"}, "initial")
    values: list[object] = ["<&", span("opaque"), child, {"title": "not-attributes"},
                            42, None, Ignored(), ProxyElement()._hydrate(div("not-a-node"))]
    events: list[str] = []
    update(item, values, events)
    result = render_html(item)
    retry: list[object] = ["unpublished"]
    try:
        update(item, retry, events, True)
    except ValueError:
        events.append("caught")
    gc_collect()
    return result + render_html(item) + repr(events) + str(len(values))
'''.replace("METHOD", method), directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
