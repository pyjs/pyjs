"""Calls and accessors must summarize every reached implementation."""

import pytest

from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.lifetime import LifetimeBoundary
from tests.transpiler.test_ir import analyze_ir


@pytest.mark.parametrize("annotation", ["", ": str"])
def test_property_assignment_uses_setter_not_getter_effects(annotation):
    with analyze_ir(f'''
        from pyjs.native import gc_pin
        class Holder:
            def __init__(self, value: str):
                self._value = value
            @property
            def value(self) -> str:
                gc_pin(self)
                return self._value
            @value.setter
            def value(self, value: str) -> None:
                self._value = value
        def main(holder: Holder, value: str, other: Holder) -> str:
            holder.value{annotation} = value
            return other.value
    ''') as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        summary = analysis.entry_point.ir.lifetime
        assert summary.external_parameters == {"other"}
        assert summary.parameter_containment == (("holder", "value"),)


@pytest.mark.parametrize("annotation", ["", ": str"])
def test_property_override_and_effectful_operands_remain_visible(annotation):
    with analyze_ir(f'''
        from pyjs.native import gc_pin
        class Base:
            @property
            def value(self) -> str:
                return ""
            @value.setter
            def value(self, value: str) -> None:
                pass
        class Retaining(Base):
            @property
            def value(self) -> str:
                return ""
            @value.setter
            def value(self, value: str) -> None:
                gc_pin(self)
                gc_pin(value)
        def receiver(item: Base, witness: list[int]) -> Base:
            gc_pin(witness)
            return item
        def replacement(value: str, witness: list[str]) -> str:
            gc_pin(witness)
            return value
        def store(holder: Base, value: str, left: list[int], right: list[str]) -> None:
            receiver(holder, left).value{annotation} = replacement(value, right)
        def main(value: str) -> None:
            store(Base(), value, [], [])
            store(Retaining(), value, [], [])
    ''') as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        summary = analysis.entry_point.container.search("store").ir.lifetime
        assert summary.external_parameters == {"holder", "value", "left", "right"}


def test_method_on_call_result_includes_virtual_override_effects():
    with analyze_ir('''
        from pyjs.native import gc_pin
        class Base:
            def publish(self) -> None:
                pass
        class Child(Base):
            def publish(self) -> None:
                gc_pin(self)
        def identity(value: Base) -> Base:
            return value
        def expose(value: Base) -> None:
            identity(value).publish()
        def main() -> None:
            expose(Child())
    ''') as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.entry_point.container.search("expose").ir.lifetime.external_parameters == {"value"}


@pytest.mark.parametrize("declaration", [False, True])
def test_property_contract_does_not_erase_body_or_unknown_runtime_effects(declaration):
    decorator = '@native_operation("test.store")' if declaration else ""
    contract = "" if declaration else '''
configure_parameter_lifetimes(Holder.value.fset, {
    "self": ParameterLifetime.BORROWED, "value": ParameterLifetime.BORROWED,
})
'''
    source = f'''
from pyjs.decorators import ParameterLifetime, configure_parameter_lifetimes, native_operation
from pyjs.native import gc_pin
class Holder:
    @property
    def value(self) -> str:
        return ""
    @value.setter
    {decorator}
    def value(self, value: str) -> None:
        gc_pin(self)
        gc_pin(value)
{contract}
def main(holder: Holder, value: str) -> None:
    holder.value = value
'''
    with analyze_ir(source) as analysis:
        assert analysis.entry_point.ir.lifetime.external_parameters == {"holder", "value"}


def test_builtin_setter_placeholders_are_not_borrowing_proofs():
    # Form value is real native state now, not the historical discarded SSR
    # write. Both builtin setters lack explicit borrowing contracts.
    with analyze_ir('''
        from pyjs.web.html import HTMLInputElement
        def main(control: HTMLInputElement, text: HTMLInputElement, value: str) -> None:
            control.value = value
            text.textContent = value
    ''') as analysis:
        assert analysis.entry_point.ir.lifetime.external_parameters == {"control", "text", "value"}


def test_union_methods_merge_return_containment_and_virtual_effects():
    with analyze_ir('''
        from pyjs.native import gc_pin
        class Box:
            def __init__(self, value: int):
                self.value = value
        class First:
            def alias(self, value: Box) -> Box:
                return Box(1)
            def keep(self, value: Box) -> None:
                pass
        class Second:
            def __init__(self):
                self.saved = Box(2)
            def alias(self, value: Box) -> Box:
                return value
            def keep(self, value: Box) -> None:
                self.saved = value
        class Child(Second):
            def keep(self, value: Box) -> None:
                gc_pin(value)
        def alias(owner: First | Second, value: Box) -> Box:
            return owner.alias(value)
        def keep(owner: First | Second, value: Box) -> None:
            owner.keep(value)
        def create(owner: First | Second) -> Box:
            value = Box(3)
            return alias(owner, value)
        def main() -> Box:
            first = First()
            second = Second()
            keep(first, Box(4))
            keep(second, Box(5))
            keep(Child(), Box(6))
            create(first)
            return create(second)
    ''') as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        module = analysis.entry_point.container
        assert module.search("alias").ir.lifetime.returned_parameters == {"value"}
        kept = module.search("keep").ir.lifetime
        assert kept.external_parameters == {"value"}
        assert kept.parameter_containment == (("owner", "value"),)
        assert module.search("create").ir.lifetime.allocations[0].boundary is LifetimeBoundary.CALLER
