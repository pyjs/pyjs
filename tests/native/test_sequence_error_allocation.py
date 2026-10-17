import pytest

from pyjs.native.llvm import transpile_llvm
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_sequence_validation_message_allocation_failure_is_catchable(
    tmp_path, optimize, managed,
):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def invalid(values: list[int], short: list[int], bounds: slice,
                    cleanup: list[int], mode: int) -> int:
            try:
                if mode == 0:
                    values[::2] = short
                elif mode == 1:
                    values[::-2] = short
                elif mode == 2:
                    values[bounds] = short
                elif mode == 3:
                    first, last = values
                elif mode == 4:
                    first, last = short
                else:
                    first, *middle, last = short
                return 0
            finally:
                cleanup[0] += 1

        def main() -> int:
            values = [0, 1, 2, 3]
            short = [9]
            bounds = slice(None, None, 2)
            cleanup = [0]
            messages = [
                "attempt to assign sequence of size 1 to extended slice of size 2",
                "attempt to assign sequence of size 1 to extended slice of size 2",
                "attempt to assign sequence of size 1 to extended slice of size 2",
                "too many values to unpack (expected 2, got 4)",
                "not enough values to unpack (expected 2, got 1)",
                "not enough values to unpack (expected at least 2, got 1)",
            ]
            for mode in range(6):
                text = "missing"
                try:
                    invalid(values, short, bounds, cleanup, mode)
                except ValueError as error:
                    text = str(error)
                if text != messages[mode]:
                    return 10 + mode
                stages = 1
                failure = 0
                while failure <= stages:
                    result = -1
                    caught = 0
                    cleanup[0] = 0
                    arm(1000 if failure == 0 else failure)
                    try:
                        result = invalid(values, short, bounds, cleanup, mode)
                    except MemoryError:
                        caught = 1
                    except ValueError:
                        caught = 2
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    # Measure the current implementation: fewer message-building
                    # allocations are valid, but every failure stage must recover.
                    # The final allocation appends the caller trace frame.
                    # Trace OOM preserves the exception with a truncated trace;
                    # earlier allocations are needed to construct its message.
                    expected = 2 if failure == 0 or failure == stages else 1
                    if stages < 2 or caught != expected:
                        print(mode, failure, stages, caught)
                        return 20 + mode
                    if result != -1 or cleanup[0] != 1:
                        return 30 + mode
                    if values != [0, 1, 2, 3] or short != [9]:
                        return 40 + mode
                    retried = False
                    try:
                        invalid(values, short, bounds, cleanup, mode)
                    except ValueError:
                        retried = True
                    if not retried or cleanup[0] != 2:
                        return 50 + mode
                    failure += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
