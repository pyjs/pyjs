from textwrap import indent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.lifetime import (
    LifetimeBoundary,
    LifetimeInference,
    outward_summary_key,
    refine_lifetimes,
)
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.lifetime_fixtures import PERSISTENT_ALIAS_CASES, PERSISTENT_ALIAS_DEFINITIONS


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("prefix", ["", "*, "])
@pytest.mark.parametrize("arguments, expected", [
    ("", LifetimeBoundary.EXTERNAL),
    ("target=local", LifetimeBoundary.LOCAL),
    ("**{}", LifetimeBoundary.EXTERNAL),
])
def test_default_getters_preserve_persistent_ownership_without_escaping_explicit_locals(
    environment, prefix, arguments, expected,
):
    with analyze_source(f'''
class Box:
    pass
def bucket({prefix}target: list[list[Box]] = [[]]) -> list[Box]:
    return target[0]
def main() -> int:
    local: list[list[Box]] = [[]]
    bucket({arguments}).append(Box())
    return len(local)
''', wrap=False, environment=environment) as analysis:
        for _ in range(3):
            boxes = [item for item in analysis.entry_point.ir.lifetime.allocations
                     if getattr(item.operation.value_type, "generic_name", None) == "Box"]
            assert len(boxes) == 1
            assert boxes[0].boundary is expected
            before = outward_summary_key(analysis.entry_point.ir.lifetime)
            refine_lifetimes(analysis.entry_point)
            assert outward_summary_key(analysis.entry_point.ir.lifetime) == before


@pytest.mark.parametrize("annotation, expansion", [
    ("dict[str, list[Box]]", "**options"),
    ("tuple[list[Box], ...]", "*options"),
])
def test_dynamic_expansion_can_leave_a_persistent_default_in_effect(annotation, expansion):
    # Dynamic argument expansion is currently native-only; the shared cases
    # above use literal expansion, supported by each analysis environment.
    with analyze_source(f'''
class Box:
    pass
def bucket(target: list[Box] = []) -> list[Box]:
    return target
def main(options: {annotation}) -> None:
    bucket({expansion}).append(Box())
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        [allocation] = analysis.entry_point.ir.lifetime.allocations
        assert allocation.boundary is LifetimeBoundary.EXTERNAL


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("arguments, expected", [
    ("*(local, local)", LifetimeBoundary.LOCAL),
    ("*(local,), target=local", LifetimeBoundary.LOCAL),
    ("*(local, *(local,))", LifetimeBoundary.LOCAL),
    ("*[local, local]", LifetimeBoundary.LOCAL),
    ("*(local,)", LifetimeBoundary.EXTERNAL),
])
def test_literal_positional_packs_bind_only_definite_defaults(environment, arguments, expected):
    assert_default_pack_lifetime(environment, arguments, expected)


@pytest.mark.parametrize("arguments, expected", [
    ("*(), local, local", LifetimeBoundary.LOCAL),
    ('**{"target": local}', LifetimeBoundary.LOCAL),
    ('**{"first": local}', LifetimeBoundary.EXTERNAL),
    ('**{"first": local, "target": local}', LifetimeBoundary.LOCAL),
    ('*(local,), **{"target": local}', LifetimeBoundary.LOCAL),
])
def test_native_literal_packs_bind_only_definite_defaults(arguments, expected):
    # These call shapes use native's expanded-call analysis/lowering.
    assert_default_pack_lifetime(NATIVE_ENVIRONMENT, arguments, expected)


def assert_default_pack_lifetime(environment, arguments, expected):
    with analyze_source(f'''
class Box:
    pass
def bucket(first: list[Box] = [], target: list[Box] = []) -> list[Box]:
    return target
def main() -> int:
    local: list[Box] = []
    bucket({arguments}).append(Box())
    return len(local)
''', wrap=False, environment=environment) as analysis:
        for _ in range(3):
            [box] = [item for item in analysis.entry_point.ir.lifetime.allocations
                     if item.operation.value_type.generic_name == "Box"]
            assert box.boundary is expected
            before = outward_summary_key(analysis.entry_point.ir.lifetime)
            refine_lifetimes(analysis.entry_point)
            assert outward_summary_key(analysis.entry_point.ir.lifetime) == before


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("factory, external", [
    ("list", False), ("fresh_list", False), ("shared_items", True), ("make_items", True),
])
@pytest.mark.parametrize("returned", [False, True])
def test_dataclass_factory_owners_distinguish_builtin_storage_from_user_factories(environment, factory, external, returned):
    source = f'''
from builtins import list as fresh_list
from dataclasses import dataclass, field
class Box:
    pass
SHARED: list[Box] = []
def shared_items() -> list[Box]:
    return SHARED
def make_items() -> list[Box]:
    return []
@dataclass
class Bag:
    items: list[Box] = field(default_factory={factory})
def main() -> {"Box" if returned else "int"}:
    bag = Bag()
    bag.items.append(Box())
    return {"bag.items[0]" if returned else "len(bag.items)"}
'''
    if environment is WEBASSEMBLY_ENVIRONMENT and factory == "shared_items":
        # WASM does not enable module collection state; this must remain an
        # ordinary capability diagnostic, not pretend factory-runtime coverage.
        with pytest.raises(CompilationError, match="not a client value"):
            with analyze_source(source, wrap=False, environment=environment):
                pass
        return
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        expected = (LifetimeBoundary.EXTERNAL if external else
                    LifetimeBoundary.CALLER if returned else LifetimeBoundary.LOCAL)
        for _ in range(3):
            [box] = [item for item in analysis.entry_point.ir.lifetime.allocations
                     if item.operation.value_type.generic_name == "Box"]
            assert box.boundary is expected
            before = outward_summary_key(analysis.entry_point.ir.lifetime)
            refine_lifetimes(analysis.entry_point)
            assert outward_summary_key(analysis.entry_point.ir.lifetime) == before


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("annotation, expression", [
    ("list[Box]", "[value].copy()"),
    ("list[list[Box]]", "[[value]].copy()"),
    ("dict[int, Box]", "{0: value}.copy()"),
    ("tuple[Box]", "(value,)"),
])
def test_summary_distinguishes_direct_aliases_from_contained_returns(environment, annotation, expression):
    with analyze_source(f'''
class Box:
    pass
def build(value: Box) -> {annotation}:
    return {expression}
def relay(value: Box) -> {annotation}:
    return build(value=value)
def identity(value: Box) -> Box:
    return value
def main() -> int:
    value = Box()
    result = relay(value)
    if identity(value) is not value:
        return 99
    return len(result)
''', wrap=False, environment=environment) as analysis:
        module = analysis.entry_point.container
        build, relay, identity = (module.search(name) for name in ("build", "relay", "identity"))
        for function in (build, relay):
            assert function.ir.lifetime.returned_parameters == frozenset({"value"})
            assert function.ir.lifetime.contained_return_parameters == frozenset({"value"})
        assert identity.ir.lifetime.returned_parameters == frozenset({"value"})
        assert identity.ir.lifetime.contained_return_parameters == frozenset()
        assert dict(relay.ir.lifetime.call_dependencies)[build] == outward_summary_key(build.ir.lifetime)
        [allocation] = analysis.entry_point.ir.lifetime.allocations
        assert allocation.boundary is LifetimeBoundary.LOCAL
        before = outward_summary_key(relay.ir.lifetime)
        refine_lifetimes(analysis.entry_point)
        assert outward_summary_key(relay.ir.lifetime) == before


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
def test_fresh_copy_mutation_retains_members_through_the_returned_owner(environment):
    with analyze_source('''
class Box:
    def __init__(self, number: int):
        self.number = number
def copied(value: Box) -> list[Box]:
    source: list[Box] = []
    result = source.copy()
    result.append(value)
    return result
def main(number: int, target: list[Box]) -> None:
    target.append(copied(Box(number))[0])
''', wrap=False, environment=environment) as analysis:
        summary = analysis.entry_point.container.search("copied").ir.lifetime
        assert summary.contained_return_parameters == frozenset({"value"})
        [allocation] = analysis.entry_point.ir.lifetime.allocations
        assert allocation.boundary is LifetimeBoundary.CALLER


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("annotation, empty, statement, projection", [
    ("list[list[Box]]", "[]", "target.append([value])", "[0][0]"),
    ("list[list[Box]]", "[]", "target.insert(0, [value])", "[0][0]"),
    ("list[list[Box]]", "[]", "target.extend([[value]])", "[0][0]"),
    ("dict[int, list[Box]]", "{}", "target.update({0: [value]})", "[0][0]"),
    ("dict[int, list[Box]]", "{}", "target.setdefault(0, [value])", "[0][0]"),
    ("list[tuple[list[Box]]]", "[]", "target.append(([value],))", "[0][0][0]"),
    ("list[Box]", "[]", "target.insert(0, value)", "[0]"),
    ("list[list[Box]]", "[[]]", "target[0].append(value)", "[0][0]"),
    ("list[list[Box]]", "[[]]", "target[0].insert(0, value)", "[0][0]"),
    ("dict[int, list[Box]]", "{0: []}", "target[0].append(value)", "[0][0]"),
    ("list[list[Box]]", "[[Box(0)]]", "target[0][0] = value", "[0][0]"),
    ("dict[int, dict[int, Box]]", "{0: {}}", "target[0][1] = value", "[0][1]"),
    ("list[list[Box]]", "[[]]", "member = target[0]; member.append(value)", "[0][0]"),
    ("list[list[Box]]", "[[]]", "next(iter(target)).append(value)", "[0][0]"),
    ("dict[int, list[Box]]", "{0: []}", "next(iter(target.values())).append(value)", "[0][0]"),
    ("Registry", "Registry()", "target.items.append(value)", ".items[0]"),
    ("Registry", "Registry()", "target.add(value)", ".items[0]"),
])
def test_nested_parameter_store_preserves_projection_depth(environment, annotation, empty, statement, projection):
    with analyze_source(f'''
class Box:
    def __init__(self, number: int):
        self.number = number
class Registry:
    def __init__(self):
        self.items: list[Box] = []
    def add(self, value: Box) -> None:
        self.items.append(value)
def store(target: {annotation}, value: Box) -> None:
    {statement}
def relay(target: {annotation}, value: Box) -> {annotation}:
    store(value=value, target=target)
    return target
def main(number: int) -> Box:
    target: {annotation} = {empty}
    return relay(target, Box(number)){projection}
''', wrap=False, environment=environment) as analysis:
        module = analysis.entry_point.container
        store, relay = (module.search(name) for name in ("store", "relay"))
        for function in (store, relay):
            assert function.ir.lifetime.parameter_containment == (("target", "value"),)
        assert dict(relay.ir.lifetime.call_dependencies)[store] == outward_summary_key(store.ir.lifetime)
        boxes = [item for item in analysis.entry_point.ir.lifetime.allocations
                 if item.operation.value_type.generic_name == "Box"]
        assert len(boxes) == (2 if "Box(0)" in empty else 1)
        assert boxes[-1].boundary is LifetimeBoundary.CALLER
        before = outward_summary_key(relay.ir.lifetime)
        refine_lifetimes(analysis.entry_point)
        assert outward_summary_key(relay.ir.lifetime) == before


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("result", ["left[0][0]", "right[0][0]", "value"])
@pytest.mark.parametrize("existing", [False, True])
def test_nested_store_proxies_do_not_join_independent_parameters_or_the_return(environment, result, existing):
    with analyze_source(f'''
class Box:
    def __init__(self, number: int):
        self.number = number
def store(left: list[list[Box]], a: Box, right: list[list[Box]], b: Box, value: Box) -> Box:
    {"left[0].append(a)" if existing else "left.append([a])"}
    {"right[0].append(b)" if existing else "right.append([b])"}
    return value
def main(number: int) -> Box:
    a = Box(number)
    b = Box(number + 1)
    c = Box(number + 2)
    left: list[list[Box]] = {"[[]]" if existing else "[]"}
    right: list[list[Box]] = {"[[]]" if existing else "[]"}
    value = store(left, a, right, b, c)
    return {result}
''', wrap=False, environment=environment) as analysis:
        boxes = [item.boundary for item in analysis.entry_point.ir.lifetime.allocations
                 if item.operation.value_type.generic_name == "Box"]
        expected = [LifetimeBoundary.LOCAL] * 3
        expected[["left[0][0]", "right[0][0]", "value"].index(result)] = LifetimeBoundary.CALLER
        assert boxes == expected


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
def test_parameter_member_store_does_not_escape_a_local_destination(environment):
    with analyze_source('''
class Box:
    def __init__(self, number: int):
        self.number = number
def store(target: list[list[Box]], value: Box) -> None:
    target[0].append(value)
def main() -> int:
    target: list[list[Box]] = [[]]
    store(target, Box(1))
    return len(target[0])
''', wrap=False, environment=environment) as analysis:
        allocations = analysis.entry_point.ir.lifetime.allocations
        assert len(allocations) == 3
        assert all(item.boundary is LifetimeBoundary.LOCAL for item in allocations)


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("getter", ["target[0]", "next(iter(target))"])
@pytest.mark.parametrize("result", ["left[0][0]", "right[0][0]", "other", "Box(0)"])
def test_returned_member_stores_keep_independent_sources_and_local_values(environment, getter, result):
    with analyze_source(f'''
class Box:
    def __init__(self, number: int):
        self.number = number
def bucket(target: list[list[Box]]) -> list[Box]:
    return {getter}
def relay(target: list[list[Box]]) -> list[Box]:
    return bucket(target=target)
def main() -> Box:
    a = Box(1)
    b = Box(2)
    other = Box(3)
    left: list[list[Box]] = [[]]
    right: list[list[Box]] = [[]]
    relay(left).append(a)
    row = relay(right)
    row.append(b)
    return {result}
''', wrap=False, environment=environment) as analysis:
        boxes = [item.boundary for item in analysis.entry_point.ir.lifetime.allocations
                 if item.operation.value_type.generic_name == "Box"]
        expected = [LifetimeBoundary.LOCAL] * len(boxes)
        expected[["left[0][0]", "right[0][0]", "other", "Box(0)"].index(result)] = LifetimeBoundary.CALLER
        assert boxes == expected
        functions = [analysis.entry_point, analysis.entry_point.container.search("bucket"),
                     analysis.entry_point.container.search("relay")]
        before = [outward_summary_key(function.ir.lifetime) for function in functions]
        for _ in range(3):
            refine_lifetimes(analysis.entry_point)
            assert [outward_summary_key(function.ir.lifetime) for function in functions] == before


@pytest.mark.parametrize("omitted", [False, True])
def test_returned_parameter_contract_preserves_writes_through_an_opaque_getter(omitted):
    # Metadata-only external declaration: the implementation can return any
    # member of target, not necessarily the target pointer itself.
    annotation = "list[list[Box]] | None = None" if omitted else "list[list[Box]]"
    argument = "" if omitted else "target"
    with analyze_source(f'''
from pyjs import llvm
from pyjs.decorators import ParameterLifetime
class Box:
    def __init__(self, number: int):
        self.number = number
@llvm.inline("call ptr @external_bucket(ptr {{target}})", target=ParameterLifetime.RETURNED)
def bucket(target: {annotation}) -> list[Box]:
    ...
def main() -> Box:
    target: list[list[Box]] = [[]]
    bucket({argument}).append(Box(1))
    return target[0][0]
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        boxes = [item for item in analysis.entry_point.ir.lifetime.allocations
                 if item.operation.value_type.generic_name == "Box"]
        assert len(boxes) == 1
        expected = LifetimeBoundary.EXTERNAL if omitted else LifetimeBoundary.CALLER
        assert boxes[0].boundary is expected


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("label, body, external", PERSISTENT_ALIAS_CASES,
                         ids=[case[0] for case in PERSISTENT_ALIAS_CASES])
def test_persistent_storage_provenance_survives_local_aliases(environment, label, body, external):
    # Do not return a projected field: conservative return provenance can retain
    # its owner independently of the persistent-storage behavior tested here.
    source = PERSISTENT_ALIAS_DEFINITIONS + '\ndef main(number: int) -> int:\n' + indent(body, '    ') + '\n    return 0\n'
    if environment is WEBASSEMBLY_ENVIRONMENT and (
            external and label != "conversion-effect" or label in {"constant-field", "constant-local-tuple"}):
        # WASM does not reach the application str protocol in conversion-effect;
        # its conservative argument-retention metadata is checked below, not
        # execution of that backend's unsupported conversion.
        with pytest.raises(CompilationError, match="not a client value"):
            with analyze_source(source, wrap=False, environment=environment):
                pass
        return
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        for _ in range(3):
            boxes = [item for item in analysis.entry_point.ir.lifetime.allocations
                     if item.operation.value_type.generic_name == "Box"]
            assert boxes
            assert all(item.boundary is (LifetimeBoundary.EXTERNAL if external else LifetimeBoundary.LOCAL)
                       for item in boxes)
            before = outward_summary_key(analysis.entry_point.ir.lifetime)
            refine_lifetimes(analysis.entry_point)
            assert outward_summary_key(analysis.entry_point.ir.lifetime) == before


def test_immutable_conversion_proof_stops_at_recursive_type_aliases():
    with analyze_source('''
        type Tree = int | tuple[Tree, ...]
        def main() -> Tree:
            return 0
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert not LifetimeInference.immutable_builtin_type(analysis.entry_point.return_type)


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT], ids=["llvm", "jvm"])
@pytest.mark.parametrize("annotation, expression", [
    ("str", "str(number)"),
    ("str", "str(1.5)"),
    ("bytes", "bytes(number)"),
    ("range", "range(number)"),
    ("tuple[int, ...]", "tuple([number])"),
    ("tuple[tuple[int, ...], ...]", "tuple([(number,)])"),
])
@pytest.mark.parametrize("helper", [False, True], ids=["direct", "returned"])
def test_immutable_builtin_conversions_do_not_import_external_ownership(environment, annotation, expression, helper):
    source = f'''
class Box:
    def __init__(self, number: int): self.number = number
def convert(number: int) -> {annotation}: return {expression}
class Holder:
    def __init__(self, label: {annotation}):
        self.label = label
        self.items: list[Box] = []
def main(number: int) -> int:
    holder = Holder({"convert(number)" if helper else expression})
    holder.items.append(Box(number))
    return len(holder.items)
'''
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        for _ in range(3):
            boxes = [item for item in analysis.entry_point.ir.lifetime.allocations
                     if item.operation.value_type.generic_name == "Box"]
            assert len(boxes) == 1
            assert boxes[0].boundary is LifetimeBoundary.LOCAL
            before = outward_summary_key(analysis.entry_point.ir.lifetime)
            refine_lifetimes(analysis.entry_point)
            assert outward_summary_key(analysis.entry_point.ir.lifetime) == before


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT], ids=["llvm", "jvm"])
def test_persistent_member_and_return_summaries_refine_without_escaping_local_receivers(environment):
    source = PERSISTENT_ALIAS_DEFINITIONS + '''
def main(number: int) -> int:
    local = Holder([])
    local.replace()
    local.items.append(Box(number))
    shared_holder().items.append(Box(number + 1))
    shared_items().append(Box(number + 2))
    return 0
'''
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        module = analysis.entry_point.container
        replace = module.search("Holder").find_attrs("replace")
        getters = [module.search(name) for name in ("shared_items", "shared_holder")]
        functions = [analysis.entry_point, replace, *getters]
        before = [outward_summary_key(function.ir.lifetime) for function in functions]
        for _ in range(3):
            assert replace.ir.lifetime.external_member_parameters == frozenset({"self"})
            assert not replace.ir.lifetime.external_parameters
            assert not replace.ir.lifetime.returns_external
            assert all(function.ir.lifetime.returns_external for function in getters)
            assert not analysis.entry_point.ir.lifetime.returns_external
            holders = [item for item in analysis.entry_point.ir.lifetime.allocations
                       if item.operation.value_type.generic_name == "Holder"]
            assert len(holders) == 1
            assert holders[0].boundary is LifetimeBoundary.LOCAL
            refine_lifetimes(analysis.entry_point)
            assert [outward_summary_key(function.ir.lifetime) for function in functions] == before


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT], ids=["llvm", "jvm"])
@pytest.mark.parametrize("expression", ["7", "VALUES[0]", "pick()", "len(VALUES)", "Source().number", "field()"])
def test_scalar_reads_do_not_import_persistent_ownership(environment, expression):
    with analyze_source(f'''
class Box:
    def __init__(self, number: int):
        self.number = number
VALUES: list[int] = [7]
class Source:
    def __init__(self):
        self.values = VALUES
        self.number = 7
def pick() -> int:
    return VALUES[0]
def field() -> int:
    return Source().number
class Holder:
    def __init__(self, number: int):
        self.number = number
        self.items: list[Box] = []
def main() -> int:
    holder = Holder({expression})
    holder.items.append(Box(1))
    return holder.number + len(holder.items)
''', wrap=False, environment=environment) as analysis:
        before = outward_summary_key(analysis.entry_point.ir.lifetime)
        for _ in range(3):
            assert all(item.boundary is LifetimeBoundary.LOCAL
                       for item in analysis.entry_point.ir.lifetime.allocations)
            refine_lifetimes(analysis.entry_point)
            assert outward_summary_key(analysis.entry_point.ir.lifetime) == before
