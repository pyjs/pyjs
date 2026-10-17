import pytest

from pyjs.native.llvm import transpile_llvm
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_numeric_and_tuple_operations_recover_each_result_allocation(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from math import frexp, modf
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def calculate(mode: int, divisor: int, left: tuple[int, str],
                      right: tuple[int, str], bounds: slice) -> int:
            if mode == 0:
                constant = divmod(11, 3)
                return constant[0] + constant[1]
            if mode == 1:
                dynamic = divmod(11, divisor)
                return dynamic[0] + dynamic[1]
            if mode == 2:
                floating = divmod(11.5, 3.0)
                return int(floating[0] * 10 + floating[1])
            if mode == 3:
                exponent = frexp(12.0)
                return int(exponent[0] * 100) + exponent[1]
            if mode == 4:
                fraction = modf(12.25)
                return int(fraction[0] * 100 + fraction[1])
            if mode == 5:
                indices = bounds.indices(10)
                return indices[0] + indices[1] + indices[2]
            if mode == 6:
                combined = left + right
                return combined[0] + len(combined[1]) + combined[2] + len(combined[3])
            if mode == 7:
                reversed_pair = left[::-1]
                return len(reversed_pair[0]) + reversed_pair[1]
            if mode == 8:
                repeated = left * 2
                return repeated[0] + len(repeated[1]) + repeated[2] + len(repeated[3])
            if mode == 9:
                return len(left * 0)
            return len(left[:])

        def main() -> int:
            left = (1, "a")
            right = (2, "b")
            bounds = slice(1, 9, 2)
            expected = [5, 5, 32, 79, 37, 12, 5, 2, 4, 0, 2]
            for mode in range(len(expected)):
                stages = 1
                failure = 0
                while failure <= stages:
                    value = -1
                    caught = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        value = calculate(mode, 3, left, right, bounds)
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    if caught != (failure != 0):
                        return 1
                    if mode < 10 and stages < 1:
                        return 2
                    if mode == 10 and stages != 0:
                        return 3
                    if value != (-1 if caught else expected[mode]):
                        return 4
                    if calculate(mode, 3, left, right, bounds) != expected[mode]:
                        return 5
                    if left[0] != 1 or left[1] != "a" or right[0] != 2 or right[1] != "b":
                        return 6
                    failure += 1
            return 0
    ''')
    assert ("define ptr @pyjs.gc.new()" in source) == managed
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_tuple_failure_preserves_assignment_and_popitem_source(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        class Box:
            def __init__(self, value: int):
                self.value = value

        def first(events: list[int]) -> int:
            events.append(1)
            return 123

        def last(box: Box) -> Box:
            arm(1)
            return box

        def main() -> int:
            box = Box(7)
            saved = (0, "old", box)
            current = saved
            events: list[int] = []
            for repeat in range(128):
                caught = False
                try:
                    current = (first(events), "new", last(box))
                except MemoryError:
                    caught = True
                arm(0)
                {'gc_collect()' if managed else 'pass'}
                if not caught or current is not saved:
                    return 1
                if len(events) != repeat + 1:
                    return 2
                if current[0] != 0 or current[1] != "old" or current[2] is not box:
                    return 3
            current = (123, "new", box)
            {'gc_collect()' if managed else 'pass'}
            current[2].value = 8
            if current[0] != 123 or current[1] != "new" or saved[2].value != 8:
                return 4
            values = {{"first": Box(1), "last": Box(2)}}
            popped = ("saved", box)
            caught = False
            arm(1)
            try:
                popped = values.popitem()
            except MemoryError:
                caught = True
            arm(0)
            {'gc_collect()' if managed else 'pass'}
            if not caught or popped[0] != "saved" or popped[1] is not box:
                return 5
            if len(values) != 2 or values["last"].value != 2:
                return 6
            popped = values.popitem()
            {'gc_collect()' if managed else 'pass'}
            if popped[0] != "last" or popped[1].value != 2:
                return 7
            if values.popitem()[0] != "first":
                return 8
            try:
                values.popitem()
                return 9
            except KeyError:
                pass
            return 0
    ''')
    assert ("define ptr @pyjs.gc.new()" in source) == managed
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert not result.stderr
