"""Sorting scratch grows with live depth/width, not repeated sibling count."""

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True])
def test_scalar_sort_allocation_delta_is_bounded_across_siblings(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        import json
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def encode(values: list[dict[str, int]], ordered: bool) -> str:
            return json.dumps(values, sort_keys=ordered)

        def main() -> int:
            {"gc_collect()" if managed else "pass"}
            small = {{"z": 2, "a": 1}}
            large = {{"z": 4, "b": 2, "a": 1, "c": 3}}
            for repetitions in (1, 100):
                values = [small, large] * repetitions
                expected = encode(values, True)
                arm(100000)
                plain = encode(values, False)
                ordinary = 100000 - remaining()
                arm(100000)
                result = encode(values, True)
                sorted_count = 100000 - remaining()
                arm(0)
                if result != expected or len(plain) != len(result):
                    return 1
                # One reusable buffer owner, its first data allocation and
                # one growth for the larger sibling: same for 2 or 200 maps.
                if sorted_count - ordinary != 3:
                    return 2
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True])
def test_scalar_sort_scratch_failure_leaves_inputs_and_retry_intact(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        import json
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def encode(values: list[dict[str, int]], ordered: bool) -> str:
            return json.dumps(values, sort_keys=ordered, indent=1)

        def main() -> int:
            {"gc_collect()" if managed else "pass"}
            values = [{{"z": 2, "a": 1}}, {{"z": 4, "b": 2, "a": 1, "c": 3}}]
            expected = encode(values, True)
            original = encode(values, False)
            arm(1000)
            result = encode(values, True)
            stages = 1000 - remaining()
            arm(0)
            if result != expected or stages < 3:
                return 1
            for failure in range(1, stages + 1):
                result = "unchanged"
                caught = False
                arm(failure)
                try:
                    result = encode(values, True)
                except MemoryError:
                    caught = True
                arm(0)
                {"gc_collect()" if managed else "pass"}
                if not caught or result != "unchanged":
                    return 2
                if encode(values, False) != original or encode(values, True) != expected:
                    return 3
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_callbacks_keep_scalar_parent_snapshots_and_reentrant_scratch(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __lt__(self, other: Key | str) -> bool:
                OUTER.clear()
                EVENTS.append(json.dumps({"z": 2, "a": 1}, sort_keys=True))
                gc_collect()
                return False
            def __gt__(self, other: Key | str) -> bool:
                return self.__lt__(other)

        OUTER: dict[str, dict[Key | str, list[str]]] = {}
        EVENTS: list[str] = []

        def main() -> str:
            gc_set_threshold(1)
            result = json.dumps({"z": 2, "a": 1}, sort_keys=True)
            for attempt in range(2):
                tail: dict[Key | str, list[str]] = {"saved": ["tail" + str(attempt)]}
                OUTER["z"] = tail
                child: dict[Key | str, list[str]] = {Key(): ["omitted"], "kept": ["live"]}
                OUTER["a"] = child
                result += json.dumps(OUTER, sort_keys=True, skipkeys=True)
                result += "|" + str(len(OUTER))
                gc_collect()
            return result + "|" + str(EVENTS)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr
