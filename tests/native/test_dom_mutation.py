import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_attribute_mutation_order_aliases_and_retained_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div
from pyjs.web.ssr import render_html

def change(element: Element, name: str, value: str) -> None:
    element.setAttribute(value=value, name=name)
    gc_collect()

def main() -> str:
    gc_set_threshold(1)
    shared = {"x": "first", "xy": "other"}
    first = div(shared, "child", {"x": "last"})
    second = div(shared)
    alias = first
    retained = first.getAttribute("x")
    change(alias, "x", "<&😀" + str(3))
    first.setAttribute("empty", "")
    before = render_html(first) + render_html(second)
    first.removeAttribute(name="missing")
    first.removeAttribute("x")
    absent = first.getAttribute("x")
    change(first, "x", "reinserted")
    return before + render_html(first) + repr((retained, absent, first.hasAttribute("empty"),
                                               first.hasAttribute("missing"), alias is first))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_attribute_methods_use_dom_view_and_ordinary_overrides(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.setAttribute("x", "initial")
        tag(self, "body")
    def setAttribute(self, name: str, value: str) -> None:
        self.calls += 1
        gc_collect()
        super().setAttribute(name, value)

def view(item: Element) -> str:
    return str(item.getAttribute("x"))

def main() -> str:
    gc_set_threshold(1)
    item = Item()
    item.setAttribute("x", "updated")
    tag(item, *[" tail"])
    result = view(item)
    item.removeAttribute("x")
    return result + render_html(item) + str(item.calls)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_attribute_argument_order_exceptions_and_later_builder_updates(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import div, tag
from pyjs.web.ssr import render_html

def receiver(item: Element, events: list[str]) -> Element:
    events.append("receiver")
    gc_collect()
    return item

def argument(text: str, events: list[str], fail: bool = False) -> str:
    events.append(text)
    gc_collect()
    if fail:
        raise ValueError(text)
    return text

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    item = div("body")
    receiver(item, events).setAttribute(value=argument("value", events), name=argument("x", events))
    try:
        receiver(item, events).setAttribute(argument("x", events), argument("failed", events, True))
    except ValueError:
        events.append(str(item.getAttribute("x")))
    tag(item, {"x": "builder"}, "tail")
    retained = item.getAttribute("x")
    item.removeAttribute("x")
    item.setAttribute("x", "final")
    return render_html(item) + str(retained) + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("method, result, signature, arguments", [
    ("setAttribute", "None", "name: str, value: str", '"x", "value"'),
    ("removeAttribute", "None", "name: str", '"x"'),
    ("getAttribute", "str | None", "name: str", '"x"'),
    ("hasAttribute", "bool", "name: str", '"x"'),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_opaque_dom_calls_dispatch_custom_overrides(tmp_path, method, result, signature, arguments, optimize):
    comparison = LLVM().assert_matches_python(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def {method}(self, {signature}) -> {result}:
        self.calls += 1
        return super().{method}({arguments})

def view(item: Element) -> str:
    return str(item.{method}({arguments}))

def main() -> str:
    item = Item()
    result = view(item)
    return result + str(item.calls)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inherited_builtin_calls_dispatch_reached_subclass_overrides(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement

class Base(CustomElement):
    pass

class Derived(Base):
    def setAttribute(self, name: str, value: str) -> None:
        super().setAttribute(name, value + "!")

def change(item: Base) -> None:
    item.setAttribute("x", "value")

def main() -> str:
    item = Derived()
    change(item)
    return str(item.getAttribute("x"))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_custom_observation_is_not_silently_ignored():
    with pytest.raises(LLVMUnsupported, match="observed-attribute callbacks are not implemented"):
        transpile_llvm('''
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    def _is_observed_attribute(self, name: str) -> bool:
        return True

def main() -> str:
    item = Item()
    item.setAttribute("x", "value")
    return str(item.getAttribute("x"))
''')


@pytest.mark.parametrize("body", [
    'item.setAttribute("x", "value"); return render_html(item)',
    'return str(item.getAttribute("x"))',
    'return render_html(item)',
])
def test_plain_html_subclasses_cannot_masquerade_as_native_dom_storage(body):
    with pytest.raises(LLVMUnsupported, match="DOM subclasses must derive from CustomElement"):
        transpile_llvm(f'''
from pyjs.web.html import HTMLDivElement
from pyjs.web.ssr import render_html

class Item(HTMLDivElement):
    pass

def main() -> str:
    item = Item()
    {body}
''')


@pytest.mark.parametrize("attributes", [
    '{"x": "value"}', 'attrs', '*[attrs]', '*parts', 'tw("active")', 'styles',
])
def test_builder_attributes_cannot_bypass_setter_override(attributes):
    with pytest.raises(LLVMUnsupported, match="attribute overrides require a concrete application method call"):
        transpile_llvm(f'''
from pyjs.web.domx import CustomElement, tag
from pyjs.web.ssr import render_html
from pyjs.web.domx import tw

class Item(CustomElement):
    def setAttribute(self, name: str, value: str) -> None:
        super().setAttribute(name, value + "!")

def main() -> str:
    item = Item()
    attrs = {{"x": "value"}}
    parts: list[str | dict[str, str]] = ["child", attrs]
    styles = tw("active")
    tag(item, {attributes})
    return render_html(item)
''')


@pytest.mark.parametrize("inside_init", [False, True])
def test_builder_guard_covers_constructor_and_opaque_views(inside_init):
    with pytest.raises(LLVMUnsupported, match="attribute overrides require a concrete application method call"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        {"tag(self, {'x': 'value'})" if inside_init else "pass"}
    def setAttribute(self, name: str, value: str) -> None:
        super().setAttribute(name, value + "!")

def view(item: Element) -> None:
    tag(item, {{"x": "value"}})

def main() -> str:
    item = Item()
    view(item)
    return render_html(item)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_builder_arguments_finish_before_publishing_mutation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import div, tag
from pyjs.web.ssr import render_html

def argument(item: Element, fail: bool) -> str:
    item.setAttribute("x", "nested")
    if fail:
        raise ValueError("argument")
    return "child"

def main() -> str:
    item = div({"x": "old"}, "body")
    tag(item, "prefix", argument(item, False), {"y": "after"})
    first = render_html(item)
    try:
        tag(item, "not-added", {"z": "not-added"}, argument(item, True))
    except ValueError:
        pass
    return first + render_html(item)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expansion", ["parts", "stream(parts)"])
def test_builder_freezes_expansion_but_retains_argument_object_aliases(tmp_path, optimize, expansion):
    result = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import div, tag
from pyjs.web.ssr import render_html

def later(parts: list[str], attrs: dict[str, str]) -> str:
    parts.clear()
    attrs["x"] = "later"
    gc_collect()
    return "tail"

def stream(parts: list[str]) -> Iterator[str]:
    for value in parts:
        yield value

def main() -> str:
    gc_set_threshold(1)
    item = div()
    attrs = {"x": "before"}
    parts = ["child" + str(1), "child" + str(2)]
    tag(item, attrs, *EXPANSION, later(parts, attrs))
    return render_html(item) + repr(parts)
'''.replace("EXPANSION", expansion), directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ['item.setAttribute(name, value)', 'tag(item, {name: value}, "added")'])
def test_public_attribute_and_builder_allocation_failures_preserve_old_state(tmp_path, optimize, operation):
    source = transpile_llvm(f'''
from pyjs.native import gc_collect
from pyjs.web.domx import div, tag
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm

def main() -> int:
    failures = 0
    for point in range(1, 40):
        item = div({{"x": "old"}}, "body")
        before = render_html(item)
        name = "x" + str(0)
        value = "new" + str(42)
        failed = False
        arm(point)
        try:
            {operation}
        except MemoryError:
            arm(0)
            failed = True
        arm(0)
        gc_collect()
        if failed:
            failures += 1
            assert render_html(item) == before
        else:
            assert item.getAttribute(name) == value
        item.setAttribute(name, "retry")
        assert item.getAttribute(name) == "retry"
    assert failures > 0
    assert failures < 39
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize,
                                 only={"pyjs.arena.try.alloc"})
    assert result.stdout == result.stderr == b""
