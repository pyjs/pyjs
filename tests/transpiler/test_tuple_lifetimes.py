import pytest

from pyjs.analysis.lifetime import LifetimeBoundary, refine_lifetimes
from pyjs.analysis.source import analyze_source
from pyjs.decorators import ParameterLifetime, configure_parameter_lifetimes
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
def test_literal_tuple_members_do_not_retain_the_container(environment):
    with analyze_source('''
def whole() -> tuple[int, int]:
    return (4, 5)
def indexed() -> int:
    values = (1, 2, 3)
    return values[0]
def iterated() -> int:
    for value in (4, 5):
        return value
    return 0
def unknown(values: tuple[int, ...]) -> int:
    return values[0]
def main() -> int:
    return indexed() + iterated() + unknown(whole())
''', wrap=False, environment=environment) as analysis:
        module = analysis.entry_point.container
        for name, boundary in (("whole", LifetimeBoundary.CALLER),
                               ("indexed", LifetimeBoundary.LOCAL),
                               ("iterated", LifetimeBoundary.LOCAL)):
            allocations = module.search(name).ir.lifetime.allocations
            assert len(allocations) == 1
            assert allocations[0].boundary is boundary
        # An unboxed integer is copied out even when its source is unknown;
        # unlike a reference member it cannot retain that source container.
        assert module.search("unknown").ir.lifetime.returned_parameters == frozenset()


@pytest.mark.parametrize("expression", ["(1, 2)[Index()]", "[1, 2][Index()]",
                                        "((1, 2) * Index())[0]", "(Index() * (1, 2))[0]",
                                        "(1, 2)[::Index()][0]"])
def test_index_callback_is_not_borrowed_with_its_container(expression):
    with analyze_source(f'''
class Index:
    def __index__(self) -> int:
        saved.append(self)
        return 1
saved: list[Index] = []
def main() -> int:
    return {expression}
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        allocations = analysis.entry_point.ir.lifetime.allocations
        index = next(item for item in allocations if item.operation.value_type.name == "Index")
        assert index.boundary is LifetimeBoundary.EXTERNAL


@pytest.mark.parametrize("expression", ["values[:]", "values[slice(None)]", "values * 1", "1 * values"])
def test_returned_full_tuple_slice_retains_its_source(expression):
    with analyze_source(f'''
def main() -> tuple[int, ...]:
    values = (1, 2)
    return {expression}
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        allocation = analysis.entry_point.ir.lifetime.allocations[0]
        assert allocation.boundary is not LifetimeBoundary.LOCAL


def test_explicit_contracts_supplement_analyzed_body_effects():
    with analyze_source('''
class Box:
    pass
def select(first: Box, second: Box) -> Box:
    return second
def main(first: Box, second: Box) -> Box:
    return select(first, second)
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        function = analysis.entry_point
        assert function.ir.lifetime.returned_parameters == frozenset({"second"})
        # Model an interface's external implementation after ordinary body
        # analysis. No mocked summary: refine the real reached call graph.
        select = function.container.search("select")
        configure_parameter_lifetimes(select.py_func, {
            "first": ParameterLifetime.RETURNED,
            "second": ParameterLifetime.BORROWED,
        })
        refine_lifetimes(function)
        assert function.ir.lifetime.returned_parameters == frozenset({"first", "second"})


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("annotation, retained", [("int", False), ("bool", False),
    ("float", False), ("None", False), ("int8", False), ("int | None", False),
    ("str", True), ("bytes", True), ("list[int]", True), ("int | str", True)])
def test_external_contract_keeps_reference_but_not_scalar_provenance(environment, annotation, retained):
    with analyze_source(f'''
from pyjs import int8
def consume(value: {annotation}) -> None:
    pass
def main(value: {annotation}) -> None:
    consume(value)
''', wrap=False, environment=environment) as analysis:
        function = analysis.entry_point
        consume = function.container.search("consume")
        configure_parameter_lifetimes(consume.py_func, {"value": ParameterLifetime.EXTERNAL})
        refine_lifetimes(function)
        expected = frozenset({"value"}) if retained else frozenset()
        assert function.ir.lifetime.external_parameters == expected
