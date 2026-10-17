"""Opaque DOM transport retains managed wrappers, callbacks and checked types."""

import re

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, tail", [
    ("Element | str", '"text"'),
    ("Other | Element | str", '"text"'),
    ("Element | None", "None"),
    ("Element", "div()"),
])
def test_custom_union_narrowing_projects_opaque_tags_in_locals_fields_and_loops(
    tmp_path, optimize, annotation, tail,
):
    comparison = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div
class Item(CustomElement):
    def label(self) -> str:
        return "item"
class Child(Item):
    def label(self) -> str:
        return "child"
class Other(CustomElement):
    def label(self) -> str:
        return "other"
class Holder:
    def __init__(self, value: {annotation}):
        self.value = value
def erased(value: Item) -> Element:
    return value
def local(value: {annotation}) -> str:
    if isinstance(value, (Item, Other)):
        gc_collect()
        return value.label()
    return "rest"
def field(holder: Holder) -> str:
    if isinstance(holder.value, (Item, Other)):
        gc_collect()
        return holder.value.label()
    return "rest"
def main() -> str:
    gc_set_threshold(1)
    values: list[{annotation}] = [erased(Item()), erased(Child()), Other(), div(), {tail}]
    result = ""
    for value in values:
        result += local(value) + field(Holder(value))
        if isinstance(value, (Other, Item)):
            result += value.label()
    return result
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_custom_layout_needs_presence_not_another_class_check(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement
class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.n = 3
class Child(Item):
    pass
class Holder:
    def __init__(self, child: Item | None):
        self.child = child
def local(value: Item | None) -> int:
    return value.n + value.n if value is not None else 0
def field(holder: Holder) -> int:
    return holder.child.n + holder.child.n if holder.child is not None else 0
def subclass(value: Item) -> int:
    return value.n if isinstance(value, Child) else 0
def main() -> str:
    return str((local(Item()), local(None), field(Holder(Child())), field(Holder(None)), subclass(Child())))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    # Isolate application bodies from the large linked runtime, as above.
    bodies = dict(re.findall(r"define [^\n]*@fn\.(local|field|subclass)\([^\n]*\{(.*?)\n\}",
                             comparison.native.llvm_ir, re.S))
    assert set(bodies) == {"local", "field", "subclass"}
    assert "@pyjs.native.element.isinstance" not in bodies["local"]
    assert "@pyjs.native.element.isinstance" not in bodies["field"]
    assert "@pyjs.native.element.isinstance" in bodies["subclass"]


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Item | Other", "Other | Item"])
@pytest.mark.parametrize("nested, outer, call", [
    ('def getAttribute(self, name: str) -> str | None:\n        gc_collect()\n        return "nested:" + name',
     'def get_data(self, name: str) -> str | None:\n        return "other:" + name',
     'return str(value.get_data("x"))'),
    ('def setAttribute(self, name: str, value: str) -> None:\n        gc_collect()\n        super().setAttribute(name, "nested:" + value)',
     'def set_data(self, name: str, value: str) -> None:\n        pass',
     'value.set_data("x", "v")\n    return render_html(value)'),
    ('def append(self, *children: Element | str) -> None:\n        gc_collect()\n        super().append("nested:", *children)',
     'def replaceChildren(self, *children: Element | str) -> None:\n        pass',
     'value.replaceChildren("x")\n    return render_html(value)'),
], ids=["get_data", "set_data", "replaceChildren"])
def test_union_defaults_retain_hidden_callbacks_in_both_member_orders(
    tmp_path, optimize, annotation, nested, outer, call,
):
    # No direct callback calls: those would hide a missing reachability edge.
    comparison = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Item(CustomElement):
    {nested}
class Other(CustomElement):
    {outer}
def read(value: {annotation}) -> str:
    {call}
def main() -> str:
    gc_set_threshold(1)
    return read(Item()) + read(Other())
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_captured_unobserved_attribute_names_keep_their_literal_proof(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs import effect, state
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    value = state(1)
    @effect(value)
    def changed(self) -> None:
        pass
def change(value: Element) -> None:
    value.setAttribute("other", "2")
def data(value: CustomElement) -> None:
    value.set_data("other", "3")
def main() -> str:
    panel = Panel()
    change(panel)
    data(panel)
    return render_html(panel)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inherited_implementations_share_dispatch_and_exact_union_arms_do_not_reselect(tmp_path, optimize):
    leaves = "".join(f"class Leaf{index}(Child):\n    pass\n" for index in range(8))
    instances = ", ".join(f"Leaf{index}()" for index in range(8))
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
class Base(CustomElement):
    pass
class Child(Base):
    def getAttribute(self, name: str) -> str | None:
        return "child:" + name
class Other(CustomElement):
    pass
LEAVES
def read(value: Base) -> str:
    return str(value.getAttribute("x"))
def union_read(value: Base | Other) -> str:
    return str(value.getAttribute("x"))
def default_read(value: Element) -> str:
    return str(value.hasAttribute("x"))
def main() -> str:
    values: list[Base] = [Base(), Child(), INSTANCES]
    return "|".join(read(value) + union_read(value) + default_read(value)
                    for value in values) + union_read(Other())
'''.replace("LEAVES", leaves).replace("INSTANCES", instances), directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    # Full output contains the linked runtime. Inspect only these application
    # functions: runtime parity alone cannot detect redundant unreachable arms.
    bodies = dict(re.findall(r"define [^\n]*@fn\.(read|union_read|default_read)\([^\n]*\{(.*?)\n\}",
                             comparison.native.llvm_ir, re.S))
    assert set(bodies) == {"read", "union_read", "default_read"}
    assert len(re.findall(r"call [^\n]*@fn.Child.getAttribute\(", bodies["read"])) == 1
    assert "protocol.class" not in bodies["union_read"]
    assert len(re.findall(r"call [^\n]*@fn.Child.getAttribute\(", bodies["union_read"])) == 9
    assert "protocol.class" not in bodies["default_read"]


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_dom_dispatch_allocation_failures_leave_attributes_retryable(tmp_path, optimize):
    source = transpile_llvm('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, span
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm, remaining

class Ignored(CustomElement):
    def setAttribute(self, name: str, value: str) -> None:
        pass

def update(value: Ignored | Element) -> None:
    value.setAttribute("data-test", "new<&")

def main() -> int:
    update(Ignored())
    stages = 1
    failure = 0
    while failure <= stages:
        value = span("original")
        before = render_html(value)
        caught = False
        arm(1000 if failure == 0 else failure)
        try:
            update(value)
        except MemoryError:
            caught = True
        if failure == 0:
            stages = 1000 - remaining()
        arm(0)
        gc_collect()
        if not 0 < stages < 1000 or caught != (failure != 0):
            return 1
        if caught and render_html(value) != before:
            return 2
        update(value)
        gc_collect()
        update(value)
        if value.getAttribute("data-test") != "new<&":
            return 3
        failure += 1
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Element", "Element | Override"])
def test_mixed_dom_receiver_survives_last_owner_removal_and_argument_errors(tmp_path, optimize, annotation):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, span

class Override(CustomElement):
    def __init__(self):
        super().__init__()
        self.payload = "managed:" + str(42)
    def getAttribute(self, name: str) -> str | None:
        gc_collect()
        return self.payload + str(super().getAttribute(name))

class Holder:
    def __init__(self, value: ANNOTATION):
        self.value = value

def replace(holder: Holder, fail: bool) -> str:
    holder.value = span("replacement")
    gc_collect()
    if fail:
        raise ValueError("argument failed")
    return "data-test"

def read(holder: Holder, fail: bool) -> str:
    try:
        return str(holder.value.getAttribute(replace(holder, fail)))
    except ValueError:
        gc_collect()
        return "caught"

def make(custom: bool) -> Holder:
    value = Override() if custom else span("mapped")
    value.setAttribute("data-test", "saved")
    return Holder(value)

def main() -> str:
    gc_set_threshold(1)
    result = ""
    for custom in [False, True]:
        for fail in [False, True, False]:
            result += read(make(custom), fail)
            gc_collect()
    return result
'''.replace("ANNOTATION", annotation), directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"))
    # The current collector frees swept allocations; ASan detects premature
    # retirement without the historical fixture's quarantine/zeroing shim.
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_opaque_transport_keeps_override_identity_and_gc_roots(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import cast
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.count = 0
    def setAttribute(self, name: str, value: str) -> None:
        self.count += 1
        gc_collect()
        super().setAttribute(name, "custom:" + value)
    def getAttribute(self, name: str) -> str | None:
        gc_collect()
        value = super().getAttribute(name)
        return None if value is None else "read:" + value + ":" + str(self.count)

class Child(Item):
    pass

class Holder:
    def __init__(self, value: Element):
        self.value = value

def erased(value: Item) -> Element:
    return value

def selected(mode: int) -> Element | Item | None:
    if mode == 0:
        return None
    return Item() if mode == 1 else div("optional")

def optional(mode: int) -> Element | None:
    return selected(mode)

def argument(holder: Holder) -> str:
    holder.value = div("replacement")
    gc_collect()
    return "x"

def inspect(value: Element | str | int | None) -> str:
    if isinstance(value, Item):
        return "item:" + str(value.count) + str(value.getAttribute("x"))
    return "other"

def inspect_object(value: object) -> str:
    if isinstance(value, Item):
        return "boxed:" + str(value.count)
    if isinstance(value, Element):
        return render_html(value)
    return "other"

def stale(holder: Holder) -> str:
    if isinstance(holder.value, Item):
        argument(holder)
        try:
            return str(holder.value.count)
        except (TypeError, AttributeError):
            return "stale"
    return "plain"

def main() -> str:
    gc_set_threshold(1)
    item = Item()
    view = erased(item)
    assert view is item
    assert cast(Element, item) is item
    boxed: object = view
    assert boxed is item and item is boxed and boxed is view and view is boxed
    assert cast(Element, boxed) is item
    assert isinstance(boxed, Item)
    assert isinstance(view, Item)
    child_view = erased(Child())
    assert isinstance(child_view, Item) and isinstance(child_view, Child)
    assert not isinstance(view, Child)
    assert cast(Element, boxed).getAttribute("absent") is None
    unrelated: list[object] = ["", "a", b"", 1, 1.5, None]
    for other in unrelated:
        assert view is not other and other is not view
    values: list[Element] = [div("plain"), item]
    result = ""
    for value in values:
        value.setAttribute("x", "saved")
        gc_collect()
        result += str(value.getAttribute("x")) + render_html(value)
        assert value.querySelector("anything") is value
    holder = Holder(Item())
    holder.value.setAttribute("x", "retained")
    result += str(holder.value.getAttribute(argument(holder)))
    result += stale(Holder(Item()))
    for candidate in [view, div("plain"), "", 17, None]:
        result += inspect(candidate)
        result += inspect_object(candidate)
    mixed: list[Element | str | None] = [view, "text", None]
    for candidate in mixed:
        gc_collect()
        if isinstance(candidate, Element):
            result += str(candidate.getAttribute("x"))
    for mode in range(3):
        candidate = optional(mode)
        gc_collect()
        if candidate is not None:
            candidate.setAttribute("x", "optional")
            result += str(candidate.getAttribute("x")) + render_html(candidate)
    return result
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_replace_default_calls_append_per_child_after_clearing(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, span
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.events: list[str] = []
    def append(self, *children: Element | str) -> None:
        gc_collect()
        self.events.append(render_html(self) + ":" + str(len(children)))
        for child in children:
            if isinstance(child, str) and child == "reject":
                raise ValueError("append")
        super().append("prefix:", *children)

def children(fail: bool) -> Iterator[Element | str]:
    yield span("one")
    gc_collect()
    if fail:
        raise ValueError("expansion")
    yield "reject"

def replace(item: Element) -> str:
    result = ""
    for fail in [True, False]:
        try:
            item.replaceChildren(*children(fail))
        except ValueError as error:
            result += str(error) + render_html(item)
    item.replaceChildren("retry", span("done"))
    result += render_html(item)
    item.replaceChildren()
    return result + render_html(item)

def main() -> str:
    gc_set_threshold(1)
    item = Item()
    result = replace(item)
    return result + repr(item.events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_data_defaults_retain_nested_getter_and_setter_callbacks(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def setAttribute(self, name: str, value: str) -> None:
        gc_collect()
        self.calls += 1
        if value == "reject":
            raise ValueError("setter")
        super().setAttribute(name, "stored:" + value)
    def getAttribute(self, name: str) -> str | None:
        gc_collect()
        self.calls += 1
        value = super().getAttribute(name)
        return None if value is None else "read:" + value

def change(item: CustomElement) -> str:
    result = ""
    for value in ["first", "reject", "retry"]:
        try:
            item.set_data("key", value)
        except ValueError as error:
            result += str(error)
        result += str(item.get_data("key"))
    return result

def main() -> str:
    gc_set_threshold(1)
    item = Item()
    result = change(item)
    return result + str(item.calls)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
