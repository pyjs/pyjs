import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_successive_nullable_dom_guards_keep_wrappers_and_fields(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, div
        from pyjs.web.ssr import render_html

        class Panel(CustomElement):
            def __init__(self):
                super().__init__()
                self.append("panel")

        class Holder:
            def __init__(self, value: Element | str | None):
                self.value = value

        def show(value: Element | str | None) -> str:
            if value is None:
                return "missing"
            if isinstance(value, str):
                return value
            gc_collect()
            value.append("!")
            return render_html(value)

        def wrapped(value: Panel | str | None) -> str:
            assert value is not None
            if isinstance(value, str):
                return value
            return show(value)

        def field(holder: Holder) -> str:
            if holder.value is None:
                return "empty"
            if isinstance(holder.value, str):
                return holder.value.upper()
            gc_collect()
            return render_html(holder.value)

        def main() -> str:
            gc_set_threshold(1)
            panel = Panel()
            records = [show(None), show("text"), show(div("<child>")),
                       wrapped(panel), wrapped("wrapped"), field(Holder(panel)),
                       field(Holder(None)), field(Holder("field"))]
            gc_collect()
            records.append(render_html(panel))
            return repr(records)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_tagged_dom_identity_matches_wrapped_and_mapped_references(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement

        class Panel(CustomElement):
            def __init__(self):
                super().__init__()
                self.append("panel")

        def same(left: Panel | str | None, right: Element | str | None) -> bool:
            return left is right and not (right is not left)

        def concrete(left: Panel, right: Element | str | None) -> bool:
            return left is right and right is left

        def optional(left: Panel | None, right: Element | str | None) -> bool:
            return left is right and right is left

        def main() -> str:
            gc_set_threshold(1)
            panel = Panel()
            other = Panel()
            mapped: Element = panel
            other_mapped: Element = other
            gc_collect()
            if not same(panel, mapped) or not concrete(panel, mapped):
                return "lost wrapped identity"
            if same(panel, other_mapped) or concrete(panel, other_mapped):
                return "merged distinct elements"
            if not optional(panel, mapped) or optional(None, mapped):
                return "wrong nullable identity"
            if not same(None, None) or not optional(None, None):
                return "lost null identity"
            text = "shared" * 2
            if not same(text, text):
                return "lost string identity"
            if same(text, mapped) or same(panel, text):
                return "confused element and text"
            return "ok"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.stdout == "ok"


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_custom_elements_widen_without_losing_null_or_dom_identity(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement

        class Panel(CustomElement):
            def __init__(self):
                super().__init__()
                self.append("panel")

        class Holder:
            def __init__(self, value: Panel | None):
                self.value: Element | None = value

        def choose(present: bool) -> Panel | None:
            return Panel() if present else None

        def widen(value: Panel | None) -> Element | None:
            return value

        def same(value: Panel | None, mapped: Element | None) -> bool:
            return value is mapped and not (value is not mapped)

        def tagged(value: Panel | None) -> Element | str | None:
            return value

        def main() -> str:
            gc_set_threshold(1)
            for present in range(2):
                value = choose(present != 0)
                mapped = widen(value)
                holder = Holder(value)
                values: list[Element | None] = [value]
                gc_collect()
                stored = values[0]
                field = holder.value
                if not same(value, mapped):
                    return "wrong nullable identity"
                if same(value, widen(Panel())):
                    return "merged distinct identities"
                wide = tagged(value)
                gc_collect()
                if value is None:
                    if mapped is not None or stored is not None or field is not None or wide is not None:
                        return "lost null"
                else:
                    if mapped is None or stored is None or field is None:
                        return "lost element"
                    if mapped.textContent != "panel" or stored.textContent != "panel":
                        return "wrong DOM pointer"
                    field.append(" changed")
                    gc_collect()
                    if value.textContent != "panel changed":
                        return "lost alias"
                    if value is not mapped or mapped is not stored:
                        return "lost identity"
                    if isinstance(wide, Element):
                        if wide.textContent != "panel changed":
                            return "wrong tagged DOM"
                    else:
                        return "lost tagged element"
            return "ok"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.stdout == "ok"


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_element_unions_preserve_wrappers_until_mapped_upcasts(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, div

        class Panel(CustomElement):
            def __init__(self):
                super().__init__()
                self.label = "panel"
                self.append(self.label)

        class Badge(CustomElement):
            def __init__(self):
                super().__init__()
                self.label = "badge"
                self.append(self.label)

        class Fancy(Panel):
            def __init__(self):
                super().__init__()
                self.label = "fancy"
                self.textContent = self.label

        def widen(value: Panel | Badge | str) -> Element | str:
            return value

        def choose(selected: bool) -> Element:
            return Panel() if selected else div("builtin")

        def main() -> str:
            gc_set_threshold(1)
            for selected in range(4):
                value = (
                    Panel() if selected == 0 else Badge() if selected == 1
                    else "text" if selected == 2 else Fancy()
                )
                gc_collect()
                if isinstance(value, Fancy):
                    if value.label != "fancy":
                        return "lost subclass wrapper"
                elif isinstance(value, Panel):
                    if value.label != "panel":
                        return "lost Panel wrapper"
                elif isinstance(value, Badge):
                    if value.label != "badge":
                        return "lost Badge wrapper"
                elif value != "text":
                    return "lost text"
                expected = (
                    "panel" if selected == 0 else "badge" if selected == 1
                    else "text" if selected == 2 else "fancy"
                )
                if div(value).textContent != expected:
                    return "wrong concrete union DOM"
                mapped = widen(value)
                gc_collect()
                if div(mapped).textContent != expected:
                    return "wrong widened union DOM"
                values: list[Element | str] = [value]
                gc_collect()
                if div(*values).textContent != expected:
                    return "wrong collection upcast"
            if choose(True).textContent != "panel" or choose(False).textContent != "builtin":
                return "wrong conditional return"
            return "ok"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.stdout == "ok"
