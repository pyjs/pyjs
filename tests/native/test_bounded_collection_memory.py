"""Real allocator pressure, separate from fault injection and sanitizer probes."""

import shutil
import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import _fail_allocations


def run_bounded(source, directory, optimize, *, stack_bytes=None, allocation_failures=False):
    limiter = shutil.which("prlimit")
    if limiter is None:
        pytest.skip("requires prlimit to isolate actual allocator failures")
    ir = transpile_llvm(source)
    if allocation_failures:
        ir = _fail_allocations(ir, False)
    executable = LLVM().compile(ir, directory, optimize=optimize)
    # Limit only the compiled child, never pytest or the compiler. ASan reserves
    # a large shadow address range and must not be combined with RLIMIT_AS.
    limits = ["--as=33554432", "--cpu=3", "--core=0"]
    if stack_bytes is not None:
        limits.append(f"--stack={stack_bytes}")
    result = subprocess.run(
        [limiter, *limits, str(executable)],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stdout == result.stderr == ""


def test_retained_case_results_keep_only_the_measured_payload(tmp_path):
    # Final data needs 16 MiB; retaining a 3x worst-case buffer needs 48 MiB.
    run_bounded('''
        def main() -> int:
            value = "A" * 131072
            results: list[str] = []
            for index in range(128):
                results.append(value.lower())
            if len(results) != 128 or len(results[-1]) != 131072:
                return 1
            return 0 if results[0][0] == results[-1][-1] == "a" else 2
    ''', tmp_path, 2)


@pytest.mark.parametrize("fail_result", [False, True], ids=["success", "failure"])
def test_repeated_unicode_slices_do_not_retain_source_sized_scratch(tmp_path, fail_result):
    # 320 offset tables (256 KiB each), or source-sized results, exceed the
    # child limit. The current scan needs no table and allocates just its result.
    run_bounded(f'''
        from tests.native.allocation_support import arm

        def main() -> int:
            value = "😀" * 32768
            for index in range(320):
                result = "unchanged"
                arm({1 if fail_result else 0})
                try:
                    result = value[1:2]
                except MemoryError:
                    arm(0)
                    if result != "unchanged":
                        return 1
                    {'continue' if fail_result else 'return 2'}
                arm(0)
                if result != "😀":
                    return 3
                {'return 4' if fail_result else 'pass'}
            return 0
    ''', tmp_path, 0, allocation_failures=True)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
@pytest.mark.parametrize("items", ["[8, 9]", "(8, 9)"])
def test_concrete_extension_reserves_before_publishing_items(tmp_path, optimize, managed, items):
    run_bounded(f'''
        from pyjs.native import gc_collect

        def main() -> int:
            values = [7] * 2097152
            alias = values
            values.pop()
            caught = 0
            try:
                values.extend({items})
                return 1
            except MemoryError:
                caught += 1
            if len(alias) != 2097151 or alias[-1] != 7:
                return 2
            try:
                values.extend(values)
                return 3
            except MemoryError:
                caught += 1
            {'gc_collect()' if managed else 'pass'}
            if values is not alias or len(values) != 2097151 or values[-1] != 7:
                return 4
            values.extend([9])
            if len(alias) != 2097152 or alias[-1] != 9:
                return 5
            return 0 if caught == 2 else 6
    ''', tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_concatenation_does_not_retain_an_intermediate_copy(tmp_path, optimize, managed):
    # Source (8 MiB) and result (16 MiB) fit; an extra left-operand copy does not.
    run_bounded(f'''
        from pyjs.native import gc_collect

        def main() -> int:
            values = [7] * 1048576
            combined = values + values
            combined[0] = 9
            {'gc_collect()' if managed else 'pass'}
            if len(combined) != 2097152 or sum(combined) != 14680066:
                return 1
            return 0 if values[0] == 7 and combined is not values else 2
    ''', tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["values.extend(source)", "values += source"])
def test_iterator_extension_retains_prefix_and_advances_failed_item(tmp_path, optimize, operation):
    run_bounded(f'''
        from pyjs.native import gc_collect

        def main() -> int:
            values = [7] * 2097152
            alias = values
            values.pop()
            source = iter([8, 9, 10])
            caught = False
            try:
                {operation}
            except MemoryError:
                caught = True
            gc_collect()
            if not caught or values is not alias or len(values) != 2097152:
                return 1
            if values[-1] != 8 or next(source) != 10:
                return 2
            values.clear()
            values.extend([1, 2, 3])
            return 0 if alias == [1, 2, 3] else 3
    ''', tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_small_extensions_keep_arena_growth_bounded(tmp_path, optimize):
    # Exact-fit growth would retain gigabytes of old payloads in the arena.
    run_bounded('''
        def main() -> int:
            values: list[int] = []
            chunk = [1, 2, 3]
            for index in range(16384):
                values.extend(chunk)
            return 0 if len(values) == 49152 and sum(values) == 98304 else 1
    ''', tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_collection_loop_uses_bounded_temporary_stack(tmp_path, optimize):
    run_bounded('''
        from pyjs.native import gc_disable

        class Key:
            def __init__(self, value: int):
                self.value = value
            def __hash__(self) -> int:
                return self.value
            def __eq__(self, other: "Key") -> bool:
                return self.value == other.value

        def main() -> int:
            gc_disable()
            left = {Key(1): 10}
            right = {Key(1): 10}
            total = 0
            for index in range(20000):
                if left == right:
                    total += 1
            return 0 if total == 20000 else 1
    ''', tmp_path, optimize, stack_bytes=262144)


@pytest.mark.parametrize("optimize", [0, 2])
def test_handled_iterator_failures_unwind_temporary_roots(tmp_path, optimize):
    run_bounded('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def values() -> Iterator[str]:
            yield "other"
            raise ValueError("stopped")

        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            for index in range(500):
                try:
                    if "missing" in values():
                        return 1
                except ValueError:
                    gc_collect()
                    caught += 1
            return 0 if caught == 500 else 2
    ''', tmp_path, optimize, stack_bytes=262144)


def test_unhandled_iterator_failure_unwinds_before_reporting_the_error():
    result = LLVM().run_source('''
        from collections.abc import Iterator
        from pyjs.native import gc_set_threshold

        def values() -> Iterator[str]:
            yield "other"
            raise ValueError("stopped")

        def main() -> int:
            gc_set_threshold(1)
            return int("missing" in values())
    ''')
    assert result.returncode < 0
    # A corrupted root stack traps without reporting the original exception.
    assert result.stderr.endswith("ValueError: stopped\n")
