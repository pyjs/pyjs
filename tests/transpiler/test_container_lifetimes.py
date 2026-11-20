import pytest

from pyjs.analysis.lifetime import LifetimeBoundary, refine_lifetimes
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

ENVIRONMENTS = [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT]


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("annotation, statement", [
    ("dict[Box, Box]", "target.setdefault(value, value)"),
    ("dict[Box, Box]", "target.update({value: value})"),
    ("dict[Box, Box]", "target.update([(value, value)])"),
    ("dict[Box, Box]", "target.__ior__({value: value})"),
    ("list[Box]", "target.insert(0, value)"),
    ("list[Box]", "target.extend([value])"),
    ("list[Box]", "target.__iadd__([value])"),
    ("list[Box]", "target[:] = [value]"),
    ("set[Box]", "target.add(value)"),
    ("set[Box]", "target.update([value], {value})"),
    ("set[Box]", "target.intersection_update({value})"),
    ("set[Box]", "target.symmetric_difference_update({value})"),
    ("set[Box]", "target.__ior__({value})"),
    ("set[Box]", "target.__iand__({value})"),
    ("set[Box]", "target.__ixor__({value})"),
])
def test_builtin_stores_propagate_through_application_wrappers(environment, annotation, statement):
    # Test the shared call contract directly. Only NativeInferenceVisitor
    # currently rewrites collection augmented syntax to these in-place calls.
    with analyze_source(f'''
class Box:
    pass
def store(target: {annotation}, value: Box) -> None:
    {statement}
def main(target: {annotation}, value: Box) -> None:
    store(target, value)
''', wrap=False, environment=environment) as analysis:
        for function in (analysis.entry_point, analysis.entry_point.container.search("store")):
            assert function.ir.lifetime.parameter_containment == (("target", "value"),)
        # Dependency refinement is repeatable, not dependent on discovery order.
        refine_lifetimes(analysis.entry_point)
        assert analysis.entry_point.ir.lifetime.parameter_containment == (("target", "value"),)


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("annotation, expression, names", [
    ("dict[Box, Box]", "source.copy()", {"source"}),
    ("dict[Box, Box]", "source | {value: value}", {"source", "value"}),
    ("dict[Box, Box]", "dict.fromkeys([value], value)", {"value"}),
    ("Box", "source.setdefault(value, value)", {"source", "value"}),
    ("list[Box]", "[value].copy()", {"value"}),
    ("list[Box]", "[value] + [value]", {"value"}),
    ("list[Box]", "[value] * 2", {"value"}),
    ("set[Box]", "{value}.copy()", {"value"}),
    ("set[Box]", "{value}.union({value}, [value])", {"value"}),
    ("set[Box]", "{value} & {value}", {"value"}),
    ("set[Box]", "{value} - set[Box]()", {"value"}),
    ("frozenset[Box]", "frozen.copy()", {"frozen"}),
])
def test_builtin_results_retain_members(environment, annotation, expression, names):
    with analyze_source(f'''
class Box:
    pass
def main(source: dict[Box, Box], value: Box, frozen: frozenset[Box]) -> {annotation}:
    return {expression}
''', wrap=False, environment=environment) as analysis:
        assert analysis.entry_point.ir.lifetime.returned_parameters == frozenset(names)


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["llvm", "jvm", "wasm"])
def test_local_builtin_stores_and_copies_do_not_force_heap_allocation(environment):
    with analyze_source('''
class Box:
    pass
def main() -> int:
    value = Box()
    items: list[Box] = []
    items.insert(0, value)
    items.extend([value])
    copied = items.copy()
    cursor = iter(copied)
    next(cursor)
    return len(copied)
''', wrap=False, environment=environment) as analysis:
        allocations = analysis.entry_point.ir.lifetime.allocations
        assert allocations
        assert all(item.boundary is LifetimeBoundary.LOCAL for item in allocations)


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["llvm", "jvm", "wasm"])
def test_application_names_and_nonstoring_queries_do_not_acquire_builtin_effects(environment):
    with analyze_source('''
class Box:
    pass
class Store:
    def add(self, value: Box) -> None:
        pass
    def copy(self) -> Box:
        return Box()
def sorted(value: Box) -> int:
    return 0
def next(value: Box) -> int:
    return 0
def main(store: Store, items: list[Box], value: Box) -> Box:
    store.add(value)
    items.count(value)
    sorted(value)
    next(value)
    return store.copy()
''', wrap=False, environment=environment) as analysis:
        summary = analysis.entry_point.ir.lifetime
        assert summary.parameter_containment == ()
        assert summary.returned_parameters == frozenset()


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("call", ["store(target, value)", "store(value=value, target=target)",
                                 "store(*(target, value))"])
def test_bound_arguments_and_shallow_copy_precision(environment, call):
    with analyze_source(f'''
class Box:
    pass
def store(target: list[Box], value: Box) -> None:
    target.extend([value])
def copy_local() -> list[Box]:
    return [Box()].copy()
def main(target: list[Box], value: Box) -> list[Box]:
    {call}
    return copy_local()
''', wrap=False, environment=environment) as analysis:
        # A literal positional pack has exact positions, just like ordinary
        # arguments; it must not invent reverse retention of target by value.
        assert analysis.entry_point.ir.lifetime.parameter_containment == (("target", "value"),)
        allocations = analysis.entry_point.container.search("copy_local").ir.lifetime.allocations
        assert {item.operation.value_type.generic_name: item.boundary for item in allocations} == {
            "list": LifetimeBoundary.LOCAL,
            "Box": LifetimeBoundary.CALLER,
        }


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["llvm", "jvm", "wasm"])
def test_indexing_a_copy_preserves_the_container_member_level(environment):
    with analyze_source('''
class Child:
    pass
class Box:
    def __init__(self, child: Child):
        self.child = child
def main() -> Box:
    source = [Box(Child())]
    return source.copy()[0]
''', wrap=False, environment=environment) as analysis:
        assert {item.operation.value_type.generic_name: item.boundary
                for item in analysis.entry_point.ir.lifetime.allocations} == {
            "list": LifetimeBoundary.LOCAL,
            "Box": LifetimeBoundary.CALLER,
            "Child": LifetimeBoundary.CALLER,
        }


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("annotation, expression", [
    ("list[Box]", "iter(source)"),
    ("list[Box]", "reversed(source)"),
    ("list[Box]", "source[:]"),
    ("list[Box]", "sorted(source, key=lambda box: 0)"),
    ("dict[int, Box]", "source.values()"),
    ("dict[Box, int]", "source.keys()"),
])
def test_view_and_iterator_sources_propagate_wrapper_containment(environment, annotation, expression):
    with analyze_source(f'''
class Box:
    pass
def store(target: list[Box], source: {annotation}) -> None:
    target.extend({expression})
def main(target: list[Box], source: {annotation}) -> None:
    store(target, source)
''', wrap=False, environment=environment) as analysis:
        for function in (analysis.entry_point, analysis.entry_point.container.search("store")):
            assert function.ir.lifetime.parameter_containment == (("target", "source"),)


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", [
    "{0: Box()}.popitem()[1]",
    "list({0: Box()}.values())[0]",
    "[Box()][:][0]",
    "next(enumerate([Box()]))[1]",
    "next(zip([Box()]))[0]",
])
def test_projected_result_keeps_the_member_not_only_its_fields(environment, expression):
    with analyze_source(f'''
class Box:
    def __init__(self):
        self.number = 1
def main() -> Box:
    return {expression}
''', wrap=False, environment=environment) as analysis:
        boxes = [item for item in analysis.entry_point.ir.lifetime.allocations
                 if item.operation.value_type.generic_name == "Box"]
        assert boxes
        # The list constructor has an opaque runtime body and already uses
        # conservative EXTERNAL retention. Neither path may strand the Box in
        # this function's local arena, even if its scalar fields need no owner.
        expected = LifetimeBoundary.EXTERNAL if expression.startswith("list(") else LifetimeBoundary.CALLER
        assert all(item.boundary is expected for item in boxes)
