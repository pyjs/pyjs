import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import PORTABLE_STORAGE, RANGE_LOOP_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_range_loop_contract(tmp_path, optimize):
    code = transpile_llvm(RANGE_LOOP_CONTRACT.source)
    executable = LLVM().compile(code, tmp_path, optimize=optimize)
    result = subprocess.run([executable], capture_output=True)
    assert result.returncode == 0, RANGE_LOOP_CONTRACT.failure(result.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_local_range_state_survives_reentry_recursion_and_exceptions(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        def recurse(depth: int) -> int:
            total = 0
            for i in range(3):
                if depth:
                    total += recurse(depth - 1)
                else:
                    total += i
            return total

        def bound(events: list[int], value: int) -> int:
            events.append(value)
            return value

        def main() -> str:
            events: list[int] = []
            values: list[int] = []
            for outer in range(3):
                try:
                    for i in range(bound(events, 5), bound(events, -2), bound(events, -2)):
                        try:
                            if i == 3:
                                continue
                            values.append(outer * 10 + i)
                            if outer == 1:
                                raise ValueError("stop")
                        finally:
                            events.append(i)
                except ValueError:
                    events.append(99)
            try:
                for i in range(bound(events, 1), bound(events, 2), bound(events, 0)):
                    return "bad zero step"
            except ValueError:
                events.append(100)
            # Both final increments overflow i64 but must terminate normally.
            for i in range(9223372036854775805, 9223372036854775807, 3):
                values.append(i)
            for i in range(-9223372036854775806, -9223372036854775808, -3):
                values.append(i)
            saved = range(2, 5)
            for i in saved:
                values.append(i)
                saved = range(0)
            return repr(values) + repr(events) + str(recurse(3))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def test_range_cursor_storage_is_local_unless_function_suspends():
    generated = transpile_llvm('''
        from collections.abc import Iterator
        def values() -> Iterator[int]:
            for i in range(3):
                yield i
        def main() -> int:
            total = 0
            for i in range(2):
                for j in range(3):
                    total += i + j
            return total + sum(values())
    ''')
    # Whole modules include runtime and exception scaffolding. Inspect only
    # the relevant storage instructions in the two user function bodies.
    main = generated.split("define i64 @fn.pyjs_main(", 1)[1].split("\n}", 1)[0]
    resume = generated.split("define i64 @fn.values.resume(", 1)[1].split("\n}", 1)[0]
    assert main.count("alloca %pyjs.range.iterator") == 2
    assert "alloca %pyjs.range.iterator" not in resume
    assert "call ptr @pyjs.gc.alloc.described" in resume
    entry = main.split("block.entry:", 1)[1].split("\nblock.", 1)[0]
    assert entry.count("alloca %pyjs.range.iterator") == 2


@pytest.mark.parametrize("optimize", [0, 2])
def test_checked_list_element_widths(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(PORTABLE_STORAGE.source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.returncode == 0, PORTABLE_STORAGE.failure(comparison.native.returncode)
    assert not comparison.native.stderr
