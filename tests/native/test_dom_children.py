import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_child_mutations_preserve_attributes_aliases_and_retained_children(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div, span, tag
from pyjs.web.ssr import render_html

def mutate(element: Element, child: Element) -> None:
    element.append("<&😀" + str(42), child)
    gc_collect()

def main() -> str:
    gc_set_threshold(1)
    empty = div()
    empty.replaceChildren()
    empty.append()
    void = tag("input", "temporary")
    void.replaceChildren()
    attrs = {"x": "first", "xy": "other"}
    child = span("kept")
    item = div(attrs, "old", child, {"x": "last"})
    sibling = div(attrs, "sibling")
    alias = item
    mutate(alias, span("tail"))
    before = render_html(item)
    item.replaceChildren("new", child)
    child.append("!")
    after = render_html(alias) + render_html(child) + render_html(sibling)
    item.replaceChildren()
    item.append()
    return before + after + render_html(item) + render_html(empty) + render_html(void)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["append", "replaceChildren"])
def test_child_argument_order_expansions_and_raising_callbacks(tmp_path, optimize, method):
    result = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div, span
from pyjs.web.ssr import render_html

def receiver(item: Element, events: list[str]) -> Element:
    events.append("receiver")
    gc_collect()
    return item

def stream(parts: list[Element | str], events: list[str]) -> Iterator[Element | str]:
    for part in parts:
        events.append("yield")
        gc_collect()
        yield part

def later(item: Element, parts: list[Element | str], events: list[str], fail: bool = False) -> str:
    events.append("later")
    parts.clear()
    item.setAttribute("late", "yes")
    item.append("callback")
    gc_collect()
    if fail:
        raise ValueError("argument")
    return "tail"

def main() -> str:
    gc_set_threshold(1)
    item = div("old")
    events: list[str] = []
    parts: list[Element | str] = [span("child"), "first" + str(1)]
    receiver(item, events).METHOD(*stream(parts, events), later(item, parts, events))
    successful = render_html(item)
    try:
        receiver(item, events).METHOD("not-published", later(item, parts, events, True))
    except ValueError:
        events.append("caught")
    failed = render_html(item)
    item.METHOD(**{})
    return successful + failed + render_html(item) + repr(events) + str(len(parts))
'''.replace("METHOD", method), directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["append", "replaceChildren"])
def test_child_overrides_and_super_calls(tmp_path, optimize, method):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, span
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def METHOD(self, *nodes: Element | str) -> None:
        self.calls += 1
        gc_collect()
        super().METHOD(*nodes)

def main() -> str:
    gc_set_threshold(1)
    item = Item()
    item.METHOD("first", span("nested"))
    before = render_html(item)
    item.METHOD("second")
    return before + render_html(item) + str(item.calls)
'''.replace("METHOD", method), directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_children_unwrap_application_elements_without_losing_their_fields(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div
from pyjs.web.ssr import render_html

class Child(CustomElement):
    def __init__(self, label: str):
        super().__init__()
        self.label = label
        self.append(label)

def main() -> str:
    gc_set_threshold(1)
    child = Child("body")
    item = div({"x": "kept"})
    parts: list[Element | str] = [child, "tail"]
    item.append(*parts)
    before = render_html(item)
    item.replaceChildren(child, "new")
    child.label = "changed"
    child.append(child.label)
    gc_collect()
    return before + render_html(item) + child.label + str(parts[0] is child)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("method", ["append", "replaceChildren"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_child_calls_dispatch_opaque_overrides(tmp_path, method, optimize):
    comparison = LLVM().assert_matches_python(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html

class Base(CustomElement):
    pass

class Item(Base):
    def {method}(self, *nodes: Element | str) -> None:
        super().{method}("override:", *nodes)

def mutate(item: Element) -> None:
    item.{method}("child")

def main() -> str:
    item = Item()
    mutate(item)
    return render_html(item)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_replace_children_dispatches_fallback_append_override(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def append(self, *nodes: Element | str) -> None:
        super().append("overridden", *nodes)

def main() -> str:
    item = Item()
    item.replaceChildren("child")
    return render_html(item)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_child_method_rejects_attribute_dictionaries_as_children():
    with pytest.raises(CompilationError, match="expects"):
        transpile_llvm('''
from pyjs.web.domx import div
from pyjs.web.ssr import render_html

def main() -> str:
    item = div()
    item.append({"x": "not-an-attribute-call"})
    return render_html(item)
''')


@pytest.mark.parametrize("method", ["append", "replaceChildren"])
@pytest.mark.parametrize("receiver", ["Element", "Alias", "Base"])
@pytest.mark.parametrize("inside_method", [False, True])
def test_unbound_child_calls_have_a_located_diagnostic(method, receiver, inside_method):
    with pytest.raises(LLVMUnsupported, match=r"(?m)instance methods require an instance or super.* at line \d+$"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html

Alias = Element

class Base(CustomElement):
    def {method}(self, *nodes: Element | str) -> None:
        super().{method}(*nodes)

class Item(Base):
    def change(self) -> None:
        {receiver}.{method}(self, "child")

def main() -> str:
    item = Item()
    {"item.change()" if inside_method else f'{receiver}.{method}(item, "child")'}
    return render_html(item)
''')


def test_unbound_application_variadic_method_has_a_located_diagnostic():
    with pytest.raises(LLVMUnsupported, match=r"(?m)instance methods require an instance or super.* at line \d+$"):
        transpile_llvm('''
class Item:
    def add(self, *values: object) -> int:
        return len(values)

def main() -> int:
    item = Item()
    return Item.add(item, 3)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_class_static_bound_and_super_calls_remain_supported(tmp_path, optimize):
    LLVM().assert_matches_python('''
class Base:
    def add(self, *values: int) -> int:
        return sum(values)

    @staticmethod
    def static(*values: int) -> int:
        return sum(values) + 10

    @classmethod
    def named(cls, *values: int) -> int:
        return sum(values) + 100

class Child(Base):
    def add(self, *values: int) -> int:
        return super().add(*values) + 1000

def main() -> str:
    child = Child()
    return str(Base.static(1, 2)) + ":" + str(Base.named(3, 4)) + ":" + str(child.add(5, 6))
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_incremental_append_loop_matches_python(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.web.domx import div
from pyjs.web.ssr import render_html

def main() -> str:
    item = div({"title": "kept"})
    for index in range(10000):
        item.append(str(index), "|")
    return render_html(item)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", ["append", "replaceChildren"])
def test_child_allocation_failures_preserve_published_state(tmp_path, optimize, method):
    source = transpile_llvm(f'''
from pyjs.native import gc_collect
from pyjs.web.domx import div, span
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm

def main() -> int:
    failures = 0
    for point in range(1, 50):
        item = div({{"x": "kept"}}, "old", span("original"))
        before = render_html(item)
        child = span("new-child")
        text = "new" + str(42)
        failed = False
        arm(point)
        try:
            item.{method}(text, child)
        except MemoryError:
            arm(0)
            failed = True
        arm(0)
        gc_collect()
        if failed:
            failures += 1
            assert render_html(item) == before
        else:
            assert text in render_html(item)
        item.replaceChildren("retry")
        assert render_html(item) == '<div x="kept">retry</div>'
    assert failures > 0
    assert failures < 49
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""
