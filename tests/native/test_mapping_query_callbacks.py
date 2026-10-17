import pytest

from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("callback", ["hash", "equal-other"])
@pytest.mark.parametrize("operation", [
    "mapping.get(key)",
    "mapping.setdefault(key, 4)",
    "mapping.pop(key, 0)",
    "mapping.pop(key)",
    "del mapping[key]",
    "dict.fromkeys([stored, key], 0)",
    "members.discard(key)",
    "members.remove(key)",
    "mapping.update([(key, 4)])",
    "members.update([key])",
    "members.union([key])",
    "members.intersection([key])",
    "members.difference([key])",
    "members.symmetric_difference([key])",
    "members.intersection_update([key])",
    "members.difference_update([key])",
    "members.symmetric_difference_update([key])",
    "members.issubset([key])",
    "members.issuperset([key])",
    "members.isdisjoint([key])",
])
def test_hash_queries_retain_saved_keys_across_requests(tmp_path, optimize, callback, operation):
    source = f'''
from pyjs.native import gc_collect
class Key:
    def __init__(self, number: int, fail: bool):
        self.number, self.fail = number, fail
    def __hash__(self) -> int:
        return 1
    def __eq__(self, other: Key) -> bool:
        return False
    def save(self) -> None:
        SAVED.append(self)
        gc_collect()
        if self.fail:
            raise ValueError("saved query")
class Saving(Key):
    def __hash__(self) -> int:
        {"self.save()" if callback == "hash" else "pass"}
        return 1
    def __eq__(self, other: Key) -> bool:
        {"other.save()" if callback == "equal-other" else "pass"}
        return False
SAVED: list[Key] = []
def query(mapping: dict[Key, int], members: set[Key], stored: Key, key: Key) -> None:
    try:
        {operation}
    except KeyError:
        pass
def render(number: int, fail: bool) -> str:
    # Populate so pop actually hashes the missing query. For collision cases,
    # the stored override saves the incoming key, not an already retained seed.
    # The incoming key is never part of an earlier retaining construction.
    seed = {"Key" if callback == "hash" else "Saving"}(-1, False)
    mapping: dict[Key, int] = {{seed: 7}}
    members: set[Key] = {{seed}}
    query(mapping, members, seed, {"Saving" if callback == "hash" else "Key"}(number, fail))
    junk = [Key(999, False) for _ in range(40)]
    gc_collect()
    return str(([item.number for item in SAVED], len(junk)))
'''
    namespace = {}
    exec(source, namespace)
    requests = [(1, False), (2, True), (3, False), (4, False)]
    expected = []
    for arguments in requests:
        try:
            expected.append(namespace["render"](*arguments))
        except ValueError as error:
            expected.append(str(error))
    # Persistent ctypes libraries are unsanitized; request reset exposes dangling
    # arena keys that standalone exit-time checks can leave apparently readable.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for arguments in requests:
            try:
                actual.append(library.render(*arguments))
            except LLVMRuntimeError as error:
                actual.append(str(error))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_pop_skips_hash_but_preserves_argument_order_and_defaults(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
EVENTS: list[str] = []
class Key:
    def __hash__(self) -> int:
        EVENTS.append("hash")
        raise ValueError("hashed")
    def __repr__(self) -> str:
        return "key"
def key() -> Key:
    EVENTS.append("key")
    return Key()
def default() -> list[int]:
    EVENTS.append("default")
    gc_collect()
    return [4]
def main() -> str:
    gc_set_threshold(1)
    mapping: dict[Key, list[int]] = {}
    fallback = default()
    assert mapping.pop(key(), fallback) is fallback
    assert mapping.pop(key(), default()) == [4]
    try:
        mapping.pop(key())
    except KeyError as error:
        EVENTS.append(str(error))
    # Other empty lookup methods still hash and must raise the callback error.
    try:
        mapping.get(key())
    except ValueError as error:
        EVENTS.append(str(error))
    gc_collect()
    return ",".join(EVENTS)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
