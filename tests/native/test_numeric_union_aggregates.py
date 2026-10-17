import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_aggregates_convert_mixed_numeric_items_without_losing_tags(optimize):
    result = LLVM().assert_matches_python('''
        from math import fsum, dist, hypot
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        def items(values: list[int | float | bool]) -> Iterator[int | float | bool]:
            for value in values:
                gc_collect()
                yield value
        def calculate(values: list[int | float | bool]) -> str:
            zeros = [0 for value in values]
            return repr((fsum(values), fsum(items(values)),
                         dist(items(values), zeros), hypot(*items(values))))
        def main() -> str:
            gc_set_threshold(1)
            ordinary: list[int | float | bool] = [True, 2, 3.5, False, -1.5]
            extreme: list[int | float | bool] = [9007199254740993, -9007199254740992.0, 1]
            empty: list[int | float | bool] = []
            negative: list[int | float | bool] = [-3, -0.0, False, -4.0]
            return repr((fsum([1, 2.5, -1]), calculate(ordinary), calculate(extreme),
                         calculate(empty), calculate(negative)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_numeric_aggregate_failure_consumption_and_recovery(optimize):
    result = LLVM().assert_matches_python('''
        from math import fsum, dist, hypot, inf, nan
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        def values(events: list[int], marker: int) -> Iterator[int | float]:
            events.append(marker)
            yield 3
            gc_collect()
            events.append(marker + 1)
            yield 4.0
            events.append(marker + 2)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            result: list[str] = []
            overflow: list[int | float] = [1e308, 1e308, 7]
            cursor = iter(overflow)
            try: result.append(str(fsum(cursor)))
            except OverflowError as error: result.append(str(error))
            result.append(str(next(cursor)))
            specials: list[int | float] = [inf, -inf, 2]
            try: result.append(str(fsum(specials)))
            except ValueError as error: result.append(str(error))
            result.append(str(dist(values(events, 10), values(events, 20))))
            try: dist(values(events, 30), [0])
            except ValueError as error: result.append(str(error))
            mixed: list[int | float] = [nan, inf, 1]
            result.append(str(hypot(*mixed)))
            result.append(str(fsum(values(events, 40))))
            return repr((result, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_union_aggregates_keep_portable_normalization(optimize):
    result = LLVM().assert_matches_python('''
        from math import fsum, dist, hypot
        from pyjs import int8, int64, uint32, float32, StaticArray
        def main() -> str:
            small: list[int8 | float32] = [int8(130), float32(1.25), int8(1)]
            wide: list[int64 | float] = [int64(9007199254740993), -9007199254740992.0]
            unsigned: list[uint32 | float] = [uint32(-1), -4294967295.0]
            flags: list[bool | int] = [True, -2, False, 3]
            fixed = StaticArray[int | float, 3]([1, 2.5, -1])
            return repr((fsum(small), dist(small, [0, 0, 0]), hypot(*small),
                         fsum(wide), fsum(unsigned), fsum(flags), fsum(fixed)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("annotation", ["int | str", "float | None", "object"])
@pytest.mark.parametrize("expression", ["fsum(values)", "dist(values, [0])", "hypot(*values)"])
def test_aggregates_keep_nonnumeric_item_boundaries(annotation, expression):
    with pytest.raises(LLVMUnsupported, match="math aggregates require bool, int or float items, or their closed unions"):
        transpile_llvm(f'''
            from math import fsum, dist, hypot
            def calculate(values: list[{annotation}]) -> float:
                return {expression}
            def main() -> int:
                calculate([])
                return 0
        ''')


@pytest.mark.parametrize("name", ["int", "float", "bool"])
def test_aggregate_union_cannot_treat_application_names_as_scalar_tags(name):
    with pytest.raises(LLVMUnsupported, match="math aggregates require bool, int or float items, or their closed unions"):
        transpile_llvm(f'''
            from builtins import int as integer, float as floating
            from math import fsum
            class {name}:
                pass
            def calculate(values: list[{name} | floating]) -> floating:
                return fsum(values)
            def main() -> integer:
                calculate([{name}(), 1.0])
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["fsum(values)", "dist(values, [0, 0, 0])", "hypot(*values)"])
def test_numeric_union_aggregate_allocation_failure_preserves_input(tmp_path, optimize, expression):
    source = transpile_llvm(f'''
        from math import fsum, dist, hypot
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        def calculate(values: list[int | float]) -> float:
            return {expression}
        def main() -> int:
            gc_set_threshold(1)
            values: list[int | float] = [3, 4.0, 0]
            expected = calculate(values)
            caught = 0
            exhausted = False
            for stage in range(1, 100):
                result = -1.0
                try:
                    arm(stage)
                    result = calculate(values)
                    exhausted = remaining() > 0
                    arm(0)
                    assert result == expected
                except MemoryError:
                    arm(0)
                    caught += 1
                    assert result == -1.0
                finally:
                    arm(0)
                gc_collect()
                assert values == [3, 4.0, 0]
                assert calculate(values) == expected
                if exhausted:
                    break
            assert exhausted and caught > 0
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
