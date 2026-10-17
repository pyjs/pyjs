"""Explicit DOM views and wrapper-aware inherited property defaults."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("dom", [False, True], ids=["application", "dom"])
def test_conditional_subclasses_keep_base_storage_and_inherited_constructor_types(tmp_path, optimize, dom):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement

class Base(BASE):
    def __init__(self, events: list[str]):
        INITIALIZE
        self.events = events
        self.events.append("init")
    @property
    def label(self) -> str:
        return "base"
class Child(Base):
    @property
    def label(self) -> str:
        return "child"
class Grandchild(Child):
    pass

def read(item: Base) -> str:
    gc_collect()
    return item.label + str(item.events)
def choose(child: bool) -> Base:
    return Grandchild([]) if child else Base([])
def optional(child: bool) -> Base | None:
    return Grandchild([]) if child else None
def mixed_optional(mode: int) -> Base | None:
    return (Grandchild([]) if mode == 1 else Base([])) if mode else None
def main() -> str:
    gc_set_threshold(1)
    result = ""
    for child in [False, True]:
        values: list[Base] = [Grandchild([]) if child else Base([])]
        value: Base = Grandchild([]) if child else Base([])
        values.append(value)
        gc_collect()
        result += read(values[0]) + read(value) + read(choose(child))
        maybe = optional(child)
        if maybe is not None:
            result += read(maybe)
        else:
            result += "none"
    for mode in range(3):
        maybe = mixed_optional(mode)
        if maybe is not None:
            result += read(maybe)
        else:
            result += "none"
    return result
'''.replace("BASE", "CustomElement" if dom else "object").replace(
        "INITIALIZE", "super().__init__()" if dom else "pass")
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_dispatch_keeps_captured_receiver_rhs_and_super_semantics(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import CustomElement
        from pyjs.web.ssr import render_html

        class Base(CustomElement):
            def __init__(self, events: list[str]):
                super().__init__()
                self.events = events
                self.append("base")

        class Child(Base):
            @property
            def textContent(self) -> str:
                self.events.append("get")
                gc_collect()
                return "child:" + super().textContent

            @textContent.setter
            def textContent(self, value: str | None) -> None:
                self.events.append("set")
                gc_collect()
                if value == "fail":
                    raise ValueError("rejected")
                self.replaceChildren("none" if value is None else value)

        class Grandchild(Child):
            pass

        def rhs(events: list[str], owner: list[Base]) -> str:
            events.append("rhs")
            owner.clear()
            gc_collect()
            return "<&" + str(len(events))

        def capture(owner: list[Base], events: list[str]) -> Base:
            events.append("owner")
            return owner[0]

        def update(owner: list[Base], events: list[str]) -> str:
            # The only container reference disappears during augmented RHS.
            capture(owner, events).textContent += rhs(events, owner)
            return str(events) + str(len(owner))

        def nullable(item: Base, value: str | None) -> str:
            try:
                item.textContent = value
            except ValueError as error:
                return str(error) + item.textContent
            return item.textContent + render_html(item)

        def main() -> str:
            gc_set_threshold(1)
            result = ""
            for child in [False, True]:
                events: list[str] = []
                # No local wrapper alias survives the list construction.
                owner: list[Base] = []
                if child:
                    owner.append(Grandchild(events))
                else:
                    owner.append(Base(events))
                result += update(owner, events)
            more_events: list[str] = []
            item = Grandchild(more_events)
            result += nullable(item, None) + nullable(item, "fail") + nullable(item, "retry")
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_and_override_allocation_failures_preserve_retryable_dom(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from pyjs.web.domx import CustomElement
        from pyjs.web.ssr import render_html
        from tests.native.allocation_support import arm, remaining

        class Base(CustomElement):
            def __init__(self):
                super().__init__()
                self.append("before<&" * 100)

        class Child(Base):
            @property
            def textContent(self) -> str:
                return super().textContent

            @textContent.setter
            def textContent(self, value: str | None) -> None:
                self.replaceChildren("" if value is None else value)

        def operation(item: Base, read: bool, value: str) -> str:
            if read:
                return item.textContent
            item.textContent = value
            return "written"

        def check(item: Base, read: bool) -> None:
            before = render_html(item)
            expected = "before<&" * 100 if read else "written"
            stages = 0
            for failure in range(50):
                new = "replacement" + str(failure)
                caught = False
                result = "unchanged"
                arm(1000 if failure == 0 else failure)
                try:
                    result = operation(item, read, new)
                except MemoryError:
                    caught = True
                allocations = (1000 - remaining()) if failure == 0 else 0
                arm(0)
                gc_collect()
                if failure == 0:
                    assert not caught and allocations > 0 and allocations < 49
                    stages = allocations
                else:
                    assert caught
                    assert result == "unchanged" and render_html(item) == before
                if failure == 0 or failure == stages:
                    assert operation(item, read, new) == expected
                # Restore before the next armed attempt, outside injection.
                item.replaceChildren("before<&" * 100)
                if failure != 0 and failure == stages:
                    return
            raise AssertionError("allocation sweep did not finish")

        def main() -> int:
            for read in [False, True]:
                check(Base(), read)
                check(Child(), read)
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize(("override", "operation", "diagnostic"), [
    ("""
    @property
    def textContent(self) -> str:
        return "read-only"
    """, 'item.textContent = "new"', "preserve the accessed property"),
    ("""
    @property
    def textContent(self) -> list[str]:
        return ["not text"]
    """, "return item.textContent", "incompatible accessor type"),
    ("""
    @property
    def textContent(self) -> str:
        return "text"
    @textContent.setter
    def textContent(self, value: int) -> None:
        self.append(str(value))
    """, 'item.textContent = "new"', "incompatible accessor type"),
    ("""
    @property
    def textContent(self) -> str:
        return "text"
    @textContent.setter
    def textContent(self, value: str) -> None:
        self.append(value)
    """, "item.textContent = None", "incompatible accessor type"),
])
def test_inherited_default_cannot_bypass_an_incompatible_property(override, operation, diagnostic):
    with pytest.raises(LLVMUnsupported, match=diagnostic + " at line "):
        transpile_llvm(f'''
from pyjs.web.domx import CustomElement

class Base(CustomElement):
    pass

class Child(Base):
{override}

def update(item: Base) -> str:
    {operation}
    return "done"

def main() -> str:
    return update(Child())
''')


def test_type_query_only_subclass_still_participates_in_property_validation():
    with pytest.raises(LLVMUnsupported, match="preserve the accessed property"):
        transpile_llvm('''
            from pyjs.web.domx import CustomElement
            class Base(CustomElement):
                pass
            class Child(Base):
                @property
                def textContent(self) -> str:
                    return "read-only"
            def update(item: Base) -> str:
                item.textContent = "new"
                return item.textContent
            def main() -> str:
                item = Base()
                assert not isinstance(item, Child)
                return update(item)
        ''')


@pytest.mark.parametrize("container", ["list", "Box"])
def test_optional_base_upcasts_do_not_widen_aliased_container_payloads(container):
    with pytest.raises(LLVMUnsupported, match="optional storage requires matching concrete payload types"):
        transpile_llvm(f'''
            class Base:
                pass
            class Child(Base):
                pass
            class Box[T]:
                def __init__(self, value: T):
                    self.value = value
            def widen(value: {container}[Child] | None) -> {container}[Base] | None:
                return value
            def main() -> int:
                widen(None)
                return 0
        ''')


@pytest.mark.parametrize("source", [
    """
from typing import cast
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div
class Child(CustomElement):
    pass
def main() -> str:
    value: Element = div()
    return cast(Child, value).textContent
""",
    """
from typing import cast
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
class Child(CustomElement):
    @property
    def textContent(self) -> str:
        return "override"
def main() -> str:
    return cast(Element, Child()).textContent
""",
])
def test_dom_cast_does_not_recover_wrappers_or_hide_overrides(source):
    with pytest.raises(LLVMUnsupported, match="concrete casts|textContent overrides"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_element_upcasts_share_dom_across_storage_boundaries(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, div, ref
        from pyjs.web.ssr import render_html

        class Badge(CustomElement):
            def __init__(self):
                super().__init__()
                self.append("badge")

        class Holder:
            def __init__(self, element: Element):
                self.element = element

        class Panel(CustomElement):
            def __init__(self, badge: Badge):
                super().__init__()
                self.badge: Element = ref(badge)
                self.append(self.badge)

        def identity(element: Element) -> Element:
            return element

        def main() -> str:
            original = Badge()
            local: Element = original
            holder = Holder(original)
            passed = identity(original)
            converted = cast(Element, original)
            nodes: list[Element] = [original, local, holder.element, passed, converted]
            concrete = [original]
            copied = list[Element](concrete)
            nodes.extend(copied)
            holder.element = original
            panel = Panel(original)
            gc_collect()
            local.setAttribute("title", "shared")
            if local is not original or passed is not original:
                return "lost identity"
            return render_html(div(*nodes, holder.element, original, panel))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.returncode == 0
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_dom_properties_preserve_application_and_subclass_overrides(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import CustomElement
        from pyjs.web.ssr import render_html

        class First(CustomElement):
            def __init__(self):
                super().__init__()
                self.saved = "first"

        class Child(First):
            @property
            def textContent(self) -> str:
                gc_collect()
                return "child:" + self.saved

            @textContent.setter
            def textContent(self, value: str) -> None:
                gc_collect()
                if value == "fail":
                    raise ValueError("child rejected")
                self.saved = value

        class Second(CustomElement):
            def __init__(self):
                super().__init__()
                self.saved = "second"

            @property
            def textContent(self) -> str:
                gc_collect()
                return "second:" + self.saved

            @textContent.setter
            def textContent(self, value: str) -> None:
                gc_collect()
                if value == "fail":
                    raise ValueError("second rejected")
                self.saved = value

        def update(value: First | Second) -> str:
            result = value.textContent
            for text in ["new", "fail", "retry"]:
                try:
                    value.textContent = text
                except ValueError as error:
                    result += str(error)
                gc_collect()
                result += value.textContent + value.saved + render_html(value)
            return result

        def main() -> str:
            gc_set_threshold(1)
            return update(First()) + update(Child()) + update(Second())
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.returncode == 0
    assert comparison.native.stderr == ""
