"""Mapping result metadata and explicit nullable value conversions."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import MAPPING_LOOKUP_REPRESENTATION_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_results_preserve_compound_arithmetic(tmp_path, optimize):
    contract = MAPPING_LOOKUP_REPRESENTATION_CONTRACT
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path, optimize=optimize,
                                           sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("shape,value", [("list[Nest | None]", "[None]"),
                                        ("tuple[int, Nest | None]", "(1, None)")])
def test_mapping_nullable_stores_defaults_and_update(tmp_path, optimize, shape, value):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        type Nest = {shape}
        def main() -> str:
            gc_set_threshold(1)
            value: Nest = {value}
            values: dict[str, Nest | None] = {{}}
            values["store"] = value
            values["empty"] = None
            values.setdefault("default", value)
            values.setdefault("store", None)
            values.update({{"update": value}})
            values.update([("pair", value)])
            assert values.get("missing", value) is value
            assert values.pop("missing", value) is value
            assert values.pop("pair", None) is value
            gc_collect()
            return repr(values) + str(values["store"] is values["update"])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("replace", [False, True], ids=["shrink", "same-size-replacement"])
@pytest.mark.parametrize("destination", ["Nest | None", "object"])
@pytest.mark.parametrize("operation", ["target.update(source)", "target = target | source",
                                      "target = source | target"])
def test_converted_mapping_merge_retains_captured_entry_and_cached_hash(
    tmp_path, optimize, replace, destination, operation,
):
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold
        type Nest = list[Nest | None]
        class Key:
            def __init__(self, value: int, sources: list[dict[Key, Nest]], events: list[str]):
                self.value = value
                self.sources = sources
                self.events = events
            def __hash__(self) -> int:
                self.events.append("hash")
                return 0
            def __eq__(self, other: Key) -> bool:
                self.events.append("equal")
                if self.sources:
                    source = self.sources.pop()
                    source.clear()
                    REPLACE_SOURCE
                    gc_collect()
                return self.value == other.value
        def fresh() -> Nest:
            return [None]
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            sources: list[dict[Key, Nest]] = []
            target: dict[Key, DESTINATION] = {Key(0, sources, events): None}
            source: dict[Key, Nest] = {Key(1, sources, events): fresh()}
            sources.append(source)
            events.clear()
            error = ""
            try:
                MERGE
            except RuntimeError as caught:
                error = str(caught)
            gc_collect()
            return repr(list(target.values())) + repr(events) + error
    '''.replace("DESTINATION", destination).replace("MERGE", operation).replace(
        "REPLACE_SOURCE", "source[Key(2, self.sources, self.events)] = fresh()" if replace else "pass")
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                           sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_converted_mapping_update_empty_copy_keeps_newly_equal_keys(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int, events: list[str]):
                self.value = value
                self.events = events
            def __hash__(self) -> int:
                self.events.append("hash")
                return 0
            def __eq__(self, other: Key) -> bool:
                self.events.append("equal")
                gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            first = Key(1, events)
            second = Key(2, events)
            source = {first: 10, second: 20}
            second.value = 1
            events.clear()
            target: dict[Key, int | None] = {}
            target.update(source)
            gc_collect()
            return repr(list(target.values())) + repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["get", "setdefault", "pop"])
def test_mapping_defaults_root_fresh_boxes_across_key_callbacks(tmp_path, optimize, operation):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int):
                self.value = value
            def __hash__(self) -> int:
                gc_collect()
                return 0
            def __eq__(self, other: Key) -> bool:
                gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            values: dict[Key, object] = {{Key(1): "old"}}
            missed = values.{operation}(Key(2), [10, 20])
            found = values.{operation}(Key(1), 1000)
            gc_collect()
            return repr(missed) + repr(found)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_pair_update_keeps_converted_value_when_hash_clears_source(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, pairs: list[tuple[Key, list[int]]]):
                self.pairs = pairs
            def __hash__(self) -> int:
                self.pairs.clear()
                gc_collect()
                return 0
        def main() -> str:
            gc_set_threshold(1)
            pairs: list[tuple[Key, list[int]]] = []
            pairs.append((Key(pairs), [1, 2]))
            target: dict[Key, object] = {}
            target.update(pairs)
            gc_collect()
            return repr(list(target.values())) + str(len(pairs))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("update", ["source", "list(source.items())"])
def test_mapping_update_does_not_erase_item_representation(update):
    with pytest.raises(CompilationError, match="incompatible representation"):
        transpile_llvm(f'''
            from pyjs import int8
            def main() -> int:
                source = {{"key": int8(1)}}
                target: dict[str, object] = {{}}
                target.update({update})
                return len(target)
        ''')


_REPRESENTED_VALUES = [
    ("list[int8]", "list[int]", "[int8(127)]", "value[0] + 1 == int8(-128)"),
    ("dict[str, list[int8]]", "dict[str, list[int]]", "{'v': [int8(127)]}",
     "value['v'][0] + 1 == int8(-128)"),
    ("tuple[int8, list[float32]]", "tuple[int, list[float]]", "(int8(127), [float32(16777216.0)])",
     "value[0] + 1 == int8(-128) and value[1][0] + float32(1.0) == float32(16777216.0)"),
]


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("represented,ordinary,initial,check", _REPRESENTED_VALUES)
def test_converted_mapping_update_preserves_boxed_nested_representation(
        tmp_path, optimize, represented, ordinary, initial, check):
    result = LLVM().assert_matches_python(f'''
        from typing import cast
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> int:
            gc_set_threshold(1)
            source = {{"k": {initial}}}
            target: dict[str, object] = {{}}
            target.update(source)
            source.clear()
            gc_collect()
            value = cast({represented}, target["k"])
            return 0 if {check} else 1
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0 and not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("represented,ordinary,initial,check", _REPRESENTED_VALUES)
def test_converted_mapping_update_rejects_incompatible_boxed_container_cast(
        tmp_path, optimize, represented, ordinary, initial, check):
    # Native casts validate erased layouts; Python's typing.cast is a no-op.
    result = LLVM().run_source(f'''
        from typing import cast
        from pyjs import int8, float32
        def main() -> int:
            source = {{"k": {initial}}}
            target: dict[str, object] = {{}}
            target.update(source)
            try:
                cast({ordinary}, target["k"])
            except TypeError:
                return 0
            return 1
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0 and not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("update", ["source", "list(source.items())"])
def test_converted_update_allocation_failure_keeps_source_and_recovers(tmp_path, optimize, update):
    source = f'''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        def main() -> int:
            gc_set_threshold(1)
            empty: dict[str, list[int]] = {{}}
            unused: dict[str, object] = {{}}
            arm(1)
            unused.update(empty)
            assert remaining() == 1
            arm(0)
            source = {{"a": [1], "b": [2], "c": [3]}}
            failures = 0
            for attempt in range(1, 100):
                target: dict[str, object] = {{}}
                complete = False
                arm(attempt)
                try:
                    target.update({update})
                    complete = True
                except MemoryError:
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert source == {{"a": [1], "b": [2], "c": [3]}}
                target.update({update})
                gc_collect()
                assert repr(target) == "{{'a': [1], 'b': [2], 'c': [3]}}"
                if complete:
                    return 0 if failures else 1
            return 2
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)
