"""Sorted JSON observes entry snapshots and implicit comparison ownership."""

import pytest

from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_sorts_entry_pairs_with_equality_before_ordering(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        EVENTS: list[str] = []
        class Key:
            def __init__(self, value: int):
                self.value = value
            def __hash__(self) -> int:
                return self.value
            def __eq__(self, other: Key) -> bool:
                EVENTS.append("eq")
                return self.value == other.value
            def __lt__(self, other: Key) -> bool:
                EVENTS.append("lt")
                return self.value < other.value
        def main() -> str:
            first, second = Key(2), Key(1)
            mapping = {first: 7, second: 8}
            output = json.dumps(mapping, sort_keys=True, skipkeys=True)
            # Mutated key equality makes item sorting inspect the values;
            # it must not invoke key.__lt__ once equality succeeds.
            second.value = 2
            output += json.dumps(mapping, sort_keys=True, skipkeys=True)
            return output + str(EVENTS)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_sorted_entries_survive_callback_mutation_and_collection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __lt__(self, other: Key | str) -> bool:
                MAPPING.clear()
                gc_collect()
                return False

            def __gt__(self, other: Key | str) -> bool:
                MAPPING.clear()
                gc_collect()
                return False

        MAPPING: dict[Key | str, list[str]] = {}

        def main() -> str:
            gc_set_threshold(1)
            MAPPING[Key()] = ["omitted"]
            MAPPING["kept"] = ["value" + str(7)]
            # Sorting clears the source, but CPython visits the saved entries.
            output = json.dumps([MAPPING], sort_keys=True, skipkeys=True)
            gc_collect()
            return output + "|" + str(len(MAPPING))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("mutation", [
    "OUTER.clear()",
    "del OUTER[1:]",
    'OUTER[2] = {"replacement": ["new"]}',
    'OUTER.append({"appended": ["new"]})',
], ids=["clear", "shrink-below-index", "replace", "grow"])
def test_nested_comparison_mutates_parent_with_list_iterator_semantics(tmp_path, optimize, mutation):
    comparison = LLVM().assert_matches_python(f'''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        def mutate() -> bool:
            {mutation}
            gc_collect()
            return False

        class Key:
            def __lt__(self, other: Key | str) -> bool:
                return mutate()
            def __gt__(self, other: Key | str) -> bool:
                return mutate()

        OUTER: list[dict[Key | str, list[str]]] = []

        def main() -> str:
            gc_set_threshold(1)
            OUTER.append({{"prefix": ["first"]}})
            OUTER.append({{Key(): ["omitted"], "kept": ["live" + str(7)]}})
            OUTER.append({{"tail": ["last"]}})
            result = json.dumps(OUTER, sort_keys=True, skipkeys=True, indent=1)
            gc_collect()
            return result + "|" + str(len(OUTER))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("virtual", [False, True])
def test_json_ordering_retains_nested_keys_across_failed_requests(tmp_path, optimize, virtual):
    declaration = "class Saving(Key):" if virtual else "class Key:"
    base = ("class Key:\n    def __init__(self, value: int, fail: bool):\n"
            "        self.value, self.fail = value, fail\n"
            "    def __lt__(self, other: Key) -> bool: return False") if virtual else ""
    constructor = "Saving" if virtual else "Key"
    source = f'''
import json
from pyjs.native import gc_collect
{base}
{declaration}
    def __init__(self, value: int, fail: bool):
        self.value, self.fail = value, fail
    def __lt__(self, other: Key) -> bool:
        SAVED.append(self)
        SAVED.append(other)
        gc_collect()
        if self.fail:
            raise ValueError("saved sorting")
        return False
SAVED: list[Key] = []
def render(n: int, fail: bool) -> str:
    mapping: dict[Key, int] = {{{constructor}(n, False): 1, {constructor}(n + 10, fail): 2}}
    result = json.dumps({{"nested": [mapping]}}, sort_keys=True, skipkeys=True)
    gc_collect()
    return result + "|" + str([key.value for key in SAVED])
'''
    namespace = {}
    exec(source, namespace)
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        for arguments in ((1, False), (2, True), (3, False), (4, False)):
            try:
                expected = namespace["render"](*arguments)
            except ValueError as error:
                expected = str(error)
            try:
                actual = library.render(*arguments)
            except LLVMRuntimeError as error:
                actual = str(error)
            assert actual == expected
            assert heap._Heap.from_address(library._heap).roots is None
    finally:
        library.close()


@pytest.mark.parametrize("retains", [False, True])
def test_json_key_callback_effects_do_not_force_pure_keys_to_escape(retains):
    source = f'''
        import json
        class Key:
            def __lt__(self, other: Key) -> bool:
                {"SAVED.append(self)" if retains else "pass"}
                return False
        SAVED: list[Key] = []
        def main() -> str:
            return json.dumps({{Key(): 1, Key(): 2}}, sort_keys=True, skipkeys=True)
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        allocations = analysis.entry_point.ir.lifetime.allocations
        assert allocations
        expected = LifetimeBoundary.EXTERNAL if retains else LifetimeBoundary.LOCAL
        assert all(item.boundary is expected for item in allocations)
