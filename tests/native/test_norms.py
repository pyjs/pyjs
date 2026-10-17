import subprocess
import sys

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


def check(source, optimize):
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_norms_concrete_numeric_sources_and_precision(optimize):
    check('''
        import math
        from pyjs import int8, int64, float32

        def main() -> str:
            assert math.hypot() == 0.0
            assert math.hypot(True, 2, 2.0) == 3.0
            assert math.hypot(int8(3), int64(4)) == 5.0
            assert math.hypot(float32(3), float32(4)) == 5.0
            assert math.dist((), ()) == 0.0
            assert math.dist((1, True, 2.0), (4.0, 1, -2)) == 5.0
            assert math.dist(range(4), [0, 1, 2, 3]) == 0.0
            assert math.dist(b"ABC", [65, 66, 67]) == 0.0
            assert math.dist({0: 1, 1: 2}.values(), [1, 2]) == 0.0
            assert math.dist({1: 0, 2: 0}, [1, 2]) == 0.0
            result = str(math.hypot(-0.0))
            result += str(math.hypot(1e308, 1e308))
            result += str(math.hypot(5e-324, 5e-324, 5e-324))
            result += str(math.dist([1e308], [-1e308]))
            result += str(math.hypot(math.nan, math.inf))
            assert math.isnan(math.hypot(math.nan, 1.0))
            assert math.isnan(math.dist([math.inf], [math.inf]))
            result += str(math.dist([1.0] + [7.450580596923828e-09] * 1000, [0.0] * 1001))
            left = [5e-324, 5e-324]
            right = [0.0, 0.0]
            result += str(math.dist(left, right))
            assert left == [5e-324, 5e-324] and right == [0.0, 0.0]
            return result
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_aggregate_represented_coordinate_carriers(optimize):
    check('''
        from math import dist, fsum
        from pyjs import int8, int64, uint32, float32, StaticArray

        def main() -> str:
            assert dist([int8(3), int8(4)], [0, 0]) == 5.0
            assert dist([0, 0], [int8(3), int8(4)]) == 5.0
            assert dist((float32(3), float32(4)), (0.0, 0.0)) == 5.0
            wide = StaticArray[int64, 2]([int64(3), int64(4)])
            assert dist(wide, [0, 0]) == 5.0
            assert dist([0, 0], wide) == 5.0
            assert dist(iter([int64(3), int64(4)]), [0.0, 0.0]) == 5.0
            values = {"x": float32(3), "y": float32(4)}
            assert dist([0, 0], values.values()) == 5.0
            assert fsum(wide) == 7.0
            assert fsum(values.values()) == 7.0
            assert dist([uint32(-1)], [0]) == 4294967295.0
            # Values must keep their represented normalization before the
            # float conversion, including values past binary64's exact range.
            return str(dist([int64(9007199254740993)], [0])) + str(fsum([int8(128), int8(-129)]))
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_dist_consumption_callbacks_and_error_order(optimize):
    check('''
        import math
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Points:
            def __init__(self, items: list[float], events: list[str], name: str) -> None:
                self.items = items
                self.events = events
                self.name = name

            def __iter__(self) -> Iterator[float]:
                self.events.append(self.name)
                gc_collect()
                return iter(self.items)

        def values(events: list[str], name: str, count: int, fail: bool) -> Iterator[float]:
            for index in range(count):
                events.append(name + str(index))
                gc_collect()
                yield float(index)
            if fail:
                raise RuntimeError(name)
            events.append(name + "end")

        def argument(events: list[str], name: str, count: int, fail: bool) -> Iterator[float]:
            events.append(name)
            return values(events, name, count, fail)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            assert math.dist(Points([0.0, 0.0], events, "left"),
                             Points([3.0, 4.0], events, "right")) == 5.0
            assert events == ["left", "right"]
            events.clear()
            assert math.dist(argument(events, "p", 3, False), argument(events, "q", 3, False)) == 0.0
            for count in [1, 4]:
                left = argument(events, "p", 3, False)
                right = argument(events, "q", count, False)
                try:
                    math.dist(left, right)
                except ValueError as error:
                    events.append(str(error))
                assert next(left, -1.0) == -1.0
                assert next(right, -1.0) == -1.0
            for fail_left in [True, False]:
                left = argument(events, "p", 1, fail_left)
                right = argument(events, "q", 2, True)
                try:
                    math.dist(left, right)
                except RuntimeError as error:
                    events.append(str(error))
                if fail_left:
                    assert next(right) == 0.0
            gc_collect()
            assert math.dist([0.0, 0.0], [3.0, 4.0]) == 5.0
            return "|".join(events)
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_hypot_expansion_order_recovery_and_live_sources(optimize):
    check('''
        import math
        from collections.abc import Iterator
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        def values(events: list[int]) -> Iterator[int]:
            for item in [3, 4]:
                events.append(item)
                gc_collect()
                yield item

        def later(events: list[int]) -> int:
            events.append(9)
            return 0

        def fail(events: list[int]) -> dict[str, float]:
            events.append(8)
            raise RuntimeError("keyword operand")

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            assert math.hypot(*values(events), later(events)) == 5.0
            assert events == [3, 4, 9]
            events.clear()
            try:
                math.hypot(*values(events), **fail(events))
            except RuntimeError:
                pass
            # A lone star operand is materialized after keyword expressions.
            assert events == [8]
            empty: dict[str, float] = {}
            assert math.hypot(*[3, 4], **empty) == 5.0
            assert math.hypot(*[int8(3), int8(4)]) == 5.0
            assert math.hypot(*[float32(3), float32(4)]) == 5.0
            assert math.hypot(*(True, 2, 2.0)) == 3.0
            try:
                math.hypot(*[3, 4], **{"unexpected": 1.0})
            except TypeError:
                events.append(7)
            gc_collect()
            return str(math.hypot(*range(5))) + str(math.hypot(*[5e-324] * 100)) + str(len(events))
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["math.dist(left, right)", "math.hypot(*right)"])
def test_norm_allocation_failure_recovery(tmp_path, optimize, expression):
    source = transpile_llvm('''
        import math
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining

        def main() -> int:
            gc_set_threshold(1)
            failures = 0
            successes = 0
            left = [0.0] * 40
            right = [1.0] * 40
            for fail_at in range(1, 30):
                arm(fail_at)
                try:
                    value = EXPR
                    reached = remaining() == 0
                    arm(0)
                    assert not reached
                    assert value > 6.0
                    successes += 1
                except MemoryError:
                    arm(0)
                    failures += 1
                gc_collect()
                assert math.hypot(3.0, 4.0) == 5.0
                assert left[0] == 0.0 and right[-1] == 1.0
            assert failures > 0 and successes > 0
            return 0
    '''.replace("EXPR", expression))
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("expression", ['math.dist(["3"], ["4"])', 'math.dist([None], [None])'])
def test_unsupported_coordinate_types_fail_before_ir_compilation(expression):
    with pytest.raises(LLVMUnsupported, match="bool, int or float items, or their closed unions") as caught:
        transpile_llvm("import math\ndef main() -> float:\n    return " + expression)
    assert "at line" in str(caught.value)


@pytest.mark.parametrize("expression", ["math.dist(*([1], [2]))", "math.fsum(*([1],))"])
def test_fixed_arity_aggregate_unpacking_has_a_located_diagnostic(expression):
    with pytest.raises(LLVMUnsupported, match="statically known parameters") as caught:
        transpile_llvm("import math\ndef main() -> float:\n    return " + expression)
    assert "at line" in str(caught.value)


@pytest.mark.parametrize("expression, expected", [("math.dist(p, q)", 5.0), ("math.fsum(p)", 6.0)])
def test_repeated_aggregates_bound_scratch_memory(tmp_path, expression, expected):
    # An enclosing entry may contain arbitrarily many aggregate calls. Keep
    # the real child under a generous address-space cap, not a timing bound or
    # an allocation mock. Old request-arena scratch exceeded 100 MiB here.
    source = f'''
        import math

        def main() -> int:
            p = [1.0, 2.0, 3.0]
            q = [4.0, 6.0, 3.0]
            total = 0.0
            for _ in range(1500000):
                total += {expression}
            assert total == {expected * 1500000!r}
            return 0
    '''
    executable = LLVM().compile(transpile_llvm(source), tmp_path, optimize=2)
    # Do not combine ASan with RLIMIT_AS: its shadow reserves a huge address
    # space. Separate application scenarios already run with sanitizers.
    result = subprocess.run([sys.executable, "-c", '''
import os, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (64 * 1024 * 1024, 64 * 1024 * 1024))
os.execv(sys.argv[1], [sys.argv[1]])
''', str(executable)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
