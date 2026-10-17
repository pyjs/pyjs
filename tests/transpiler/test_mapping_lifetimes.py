import pytest

from pyjs.analysis.lifetime import refine_lifetimes
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", ["left | right", "left.__or__(right)", "left.__ror__(right)"])
def test_mapping_union_retains_members_of_both_sources(environment, expression):
    with analyze_source(f'''
class Box:
    pass
def combine(first: Box, second: Box) -> dict[int, Box]:
    left = {{1: first}}
    right = {{2: second}}
    return {expression}
def main() -> int:
    return len(combine(Box(), Box()))
''', wrap=False, environment=environment) as analysis:
        function = analysis.entry_point.container.search("combine")
        for _ in range(2):
            assert function.ir.lifetime.returned_parameters == {"first", "second"}
            assert not function.ir.lifetime.external_parameters
            refine_lifetimes(analysis.entry_point)


@pytest.mark.parametrize("expression", ["left | right", "left.__or__(right)", "left.__ror__(right)"])
def test_mapping_union_retains_keys_saved_by_comparison_callbacks(expression):
    with analyze_source(f'''
class Key:
    def __hash__(self) -> int:
        return 1
    def __eq__(self, other: Key) -> bool:
        SAVED.append(self)
        SAVED.append(other)
        return False
SAVED: list[Key] = []
def combine(left: dict[Key, int], right: dict[Key, int]) -> None:
    {expression}
def main() -> int:
    combine({{Key(): 1}}, {{Key(): 2}})
    return len(SAVED)
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        function = analysis.entry_point.container.search("combine")
        assert function.ir.lifetime.external_parameters == {"left", "right"}
        refine_lifetimes(analysis.entry_point)
        assert function.ir.lifetime.external_parameters == {"left", "right"}


@pytest.mark.parametrize("collection", [
    "{first, second}", "{first: payload, second: payload}",
    "{*[first, second]}", "{first, *[second]}",
    "{" + ", ".join(["first"] * 30 + ["second"]) + "}",
    "{" + ", ".join(["first: payload"] * 34 + ["second: payload"]) + "}",
    "{**empty, first: payload, second: payload}",
])
@pytest.mark.parametrize("effect", ["hash", "equal", "pure"])
@pytest.mark.parametrize("virtual", [False, True])
def test_literal_callback_summaries_retain_keys_but_not_unrelated_values(collection, effect, virtual):
    source = f'''
class Payload:
    pass
class Key:
    def __hash__(self) -> int:
        return 1
    def __eq__(self, other: Key) -> bool:
        return False
class Saving(Key):
    def __hash__(self) -> int:
        {"SAVED.append(self)" if effect == "hash" else "pass"}
        return 1
    def __eq__(self, other: Key) -> bool:
        {"SAVED.append(other)" if effect == "equal" else "pass"}
        return False
SAVED: list[Key] = []
def construct(first: {"Key" if virtual else "Saving"}, second: {"Key" if virtual else "Saving"}, payload: Payload) -> int:
    empty: dict[{"Key" if virtual else "Saving"}, Payload] = {{}}
    values = {collection}
    return len(values)
def main() -> int:
    return construct(Saving(), Saving(), Payload())
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        function = analysis.entry_point.container.search("construct")
        expected = {"first", "second"} if effect != "pure" else set()
        assert function.ir.lifetime.external_parameters == expected
        refine_lifetimes(analysis.entry_point)
        assert function.ir.lifetime.external_parameters == expected


@pytest.mark.parametrize("effect", ["hash", "equal", "pure"])
@pytest.mark.parametrize("method", [False, True], ids=["assignment", "explicit-dunder"])
def test_mapping_store_callback_effects_include_virtual_key_operands(effect, method):
    store = "mapping.__setitem__(second, payload)" if method else "mapping[second] = payload"
    source = f'''
class Key:
    def __hash__(self) -> int:
        return 1
    def __eq__(self, other: Key) -> bool:
        return False
class Saving(Key):
    def __hash__(self) -> int:
        {"SAVED.append(self)" if effect == "hash" else "pass"}
        return 1
    def __eq__(self, other: Key) -> bool:
        {"SAVED.append(self); SAVED.append(other)" if effect == "equal" else "pass"}
        return False
SAVED: list[Key] = []
def store(first: Key, second: Key, payload: list[int]) -> int:
    mapping: dict[Key, list[int]] = {{}}
    mapping[first] = payload
    {store}
    return len(mapping)
def main() -> int:
    return store(Saving(), Saving(), [1])
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        function = analysis.entry_point.container.search("store")
        for _ in range(2):
            external = function.ir.lifetime.external_parameters
            if effect == "pure":
                assert not external
            else:
                assert {"first", "second"} <= external
            refine_lifetimes(analysis.entry_point)


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("assignment", ["mapping[key] = value", "mapping.__setitem__(key, value)"])
def test_mapping_stores_retain_both_key_and_value(environment, assignment):
    with analyze_source(f'''
class Box:
    pass
def store(mapping: dict[Box, Box], key: Box, value: Box) -> None:
    {assignment}
def main() -> int:
    mapping: dict[Box, Box] = {{}}
    store(mapping, Box(), Box())
    return len(mapping)
''', wrap=False, environment=environment) as analysis:
        store = analysis.entry_point.container.search("store")
        assert store.ir.lifetime.parameter_containment == (("mapping", "key"), ("mapping", "value"))


@pytest.mark.parametrize("effect", ["hash", "equal-other", "pure"])
@pytest.mark.parametrize("operation", [
    "mapping.get(key)", "mapping.setdefault(key, 1)", "mapping.pop(key, 0)",
    "del mapping[key]", "dict.fromkeys([key], 0)", "members.discard(key)", "members.remove(key)",
    "mapping.update([(key, 4)])", "members.update([key])", "members.union([key])",
    "members.intersection([key])", "members.difference([key])", "members.symmetric_difference([key])",
    "members.intersection_update([key])", "members.difference_update([key])",
    "members.symmetric_difference_update([key])", "members.issubset([key])",
    "members.issuperset([key])", "members.isdisjoint([key])",
])
def test_hash_query_callback_summaries_keep_saved_operands(effect, operation):
    with analyze_source(f'''
class Key:
    def __hash__(self) -> int:
        return 1
    def __eq__(self, other: Key) -> bool:
        return False
class Saving(Key):
    def __hash__(self) -> int:
        {"SAVED.append(self)" if effect == "hash" else "pass"}
        return 1
    def __eq__(self, other: Key) -> bool:
        {"SAVED.append(other)" if effect == "equal-other" else "pass"}
        return False
SAVED: list[Key] = []
def query(mapping: dict[Key, int], members: set[Key], key: Key) -> None:
    {operation}
def main() -> int:
    mapping: dict[Key, int] = {{}}
    members: set[Key] = set()
    query(mapping, members, Saving())
    return len(SAVED)
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        query = analysis.entry_point.container.search("query")
        for _ in range(2):
            external = query.ir.lifetime.external_parameters
            assert ("key" in external) == (effect != "pure")
            if effect == "pure":
                assert not external
            refine_lifetimes(analysis.entry_point)


@pytest.mark.parametrize("effect", ["hash", "equal", "pure"])
@pytest.mark.parametrize("operation", [
    "left | right", "left & right", "left - right", "left ^ right",
    "left |= right", "left &= right", "left -= right", "left ^= right",
    "left == right", "left != right", "left < right", "left <= right",
    "left > right", "left >= right",
])
def test_set_operator_callbacks_retain_operand_members(effect, operation):
    with analyze_source(f'''
class Key:
    def __hash__(self) -> int:
        {"SAVED.append(self)" if effect == "hash" else "pass"}
        return 1
    def __eq__(self, other: Key) -> bool:
        {"SAVED.append(other)" if effect == "equal" else "pass"}
        return False
SAVED: list[Key] = []
def query(left: set[Key], right: set[Key]) -> None:
    {operation}
def main() -> int:
    query({{Key()}}, {{Key()}})
    return len(SAVED)
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        query = analysis.entry_point.container.search("query")
        expected = {"left", "right"} if effect != "pure" else set()
        assert query.ir.lifetime.external_parameters == expected
        refine_lifetimes(analysis.entry_point)
        assert query.ir.lifetime.external_parameters == expected


@pytest.mark.parametrize("operation", [
    "mapping.clear()", "mapping.copy()", "mapping.keys()", "len(mapping)",
    "mapping.popitem()", "members.clear()", "members.copy()", "members.pop()",
])
def test_non_hashing_mapping_methods_do_not_acquire_callback_escapes(operation):
    with analyze_source(f'''
class Key:
    def __hash__(self) -> int:
        SAVED.append(self)
        return 1
    def __eq__(self, other: Key) -> bool:
        SAVED.append(other)
        return False
SAVED: list[Key] = []
def query(mapping: dict[Key, int], members: set[Key]) -> None:
    {operation}
def main() -> int:
    key = Key()
    query({{key: 1}}, {{key}})
    return len(SAVED)
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        query = analysis.entry_point.container.search("query")
        assert not query.ir.lifetime.external_parameters


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
def test_sequence_and_application_setitem_do_not_implicitly_store_the_key(environment):
    with analyze_source('''
class Box:
    pass
class Store:
    def __init__(self):
        self.value: Box | None = None
    def __setitem__(self, key: Box, value: Box) -> None:
        self.value = value
def sequence(values: list[Box], key: int, value: Box) -> None:
    values[key] = value
def custom(store: Store, key: Box, value: Box) -> None:
    store[key] = value
def main() -> int:
    values = [Box()]
    sequence(values, 0, Box())
    custom(Store(), Box(), Box())
    return len(values)
''', wrap=False, environment=environment) as analysis:
        module = analysis.entry_point.container
        assert module.search("sequence").ir.lifetime.parameter_containment == (("values", "value"),)
        assert module.search("custom").ir.lifetime.parameter_containment == (("store", "value"),)
