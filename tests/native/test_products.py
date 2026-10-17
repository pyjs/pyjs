import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_prod_numeric_domains_empty_identity_and_portable_values(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from math import prod as product
        from pyjs import int8, float32
        def main() -> str:
            empty: list[float] = []
            mixed: list[int | float] = [2, 1.5, 3]
            small: list[int8] = [int8(5), int8(7), int8(8)]
            narrow: list[float32] = [float32(0.5), float32(2.0)]
            return repr((product([2, 3, 4]), math.prod((value / 2 for value in range(1, 4)), start=2),
                         product([]), product(small, start=int8(1)), product([int8(100), int8(2)]),
                         product(small, start=0.5), product([float32(0.5), float32(2.0)]), product(empty),
                         product(empty, start=True), product(mixed), product(mixed, start=0.5),
                         product([True, False]),
                         product([2, 3], start=0.5), product(narrow, start=float32(1))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_prod_preserves_iteration_order_failures_and_temporary_roots(optimize):
    result = LLVM().assert_matches_python('''
        from math import prod
        from pyjs.native import gc_collect, gc_set_threshold
        class Numbers:
            def __init__(self, events: list[str]):
                self.events = events
                self.index = 0
            def __iter__(self) -> "Numbers":
                self.events.append("iter")
                return self
            def __next__(self) -> float:
                self.index += 1
                self.events.append(str(self.index))
                gc_collect()
                if self.index == 2: raise ValueError("after zero")
                if self.index > 3: raise StopIteration()
                return 0.0 if self.index == 1 else 3.0
        def make(events: list[str]) -> Numbers:
            events.append("source")
            return Numbers(events)
        def begin(events: list[str], fail: bool = False) -> int:
            events.append("start")
            gc_collect()
            if fail: raise ValueError("start failed")
            return 2
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            message = ""
            try: prod(make(events), start=begin(events))
            except ValueError as error: message = str(error)
            try: prod(make(events), start=begin(events, True))
            except ValueError as error: message += ":" + str(error)
            cursor = Numbers(events)
            try: prod(cursor)
            except ValueError: pass
            following = next(cursor)
            recovered = prod((value / 2 for value in range(1, 4)), start=2)
            return repr((events, message, following, recovered))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_prod_concrete_sources_empty_object_starts_and_ieee_values(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from pyjs import StaticArray, int16
        def _multiply_numbers(left: int, right: int) -> int:
            return -99
        def _reduce(value: int) -> int:
            return -99
        def mixed_float(values: list[int | float]) -> float:
            return math.prod(values, start=0.5)
        def float_literal() -> float:
            return math.prod([0.5, 3.0])
        def bool_literal() -> int:
            return math.prod([True, True], start=True)
        def main() -> str:
            start = [4]
            same = math.prod([], start=start)
            assert same is start
            assert math.prod((), start=None) is None
            fixed: StaticArray[int16, 3] = [int16(2), int16(3), int16(4)]
            return repr((math.prod(range(1, 5)), math.prod(bytes([2, 3])),
                         math.prod({2: 8, 3: 9}), math.prod({2, 3}),
                         math.prod(fixed, start=int16(1)), math.prod(fixed), mixed_float([2, 1.5]),
                         math.prod([2, 3], **{"start": 4}),
                         math.prod([2, 3], start=math.prod([4, 5])),
                         math.prod([math.prod([2, 3]), math.prod([4, 5])]),
                         float_literal(), bool_literal(),
                         math.prod([-0.0]), math.prod([math.inf], start=0),
                         math.prod([math.nan]), math.prod([True], start=True)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("numeric", ["int8", "uint16", "int64", "float32", "float64"])
def test_math_prod_preserves_matching_portable_domains(numeric):
    mixed = ", prod(values, start=0.5), prod(empty, start=0.5)" if "int" in numeric else ""
    result = LLVM().assert_matches_python(f'''
        from math import prod
        from pyjs import {numeric}
        def main() -> str:
            values: list[{numeric}] = [{numeric}(2), {numeric}(3)]
            empty: list[{numeric}] = []
            result = prod(values, start={numeric}(2))
            return repr((result, result * {numeric}(3), prod(empty, start={numeric}(5)){mixed}))
    ''', sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression, message", [
    ('prod(["x"])', "requires numeric items"),
    ('prod([1], start="x")', "requires numeric items"),
    ("prod(values)", "requires matching item and start representations"),
    ("prod(values, start=int16(1))", "requires matching item and start representations"),
])
def test_math_prod_numeric_boundaries_have_located_diagnostics(expression, message):
    with pytest.raises(CompilationError, match=message):
        transpile_llvm(f'''
            from math import prod
            from pyjs import int8, int16
            def main() -> str:
                values: list[int8] = [int8(2), int8(3)]
                return repr({expression})
        ''')


@pytest.mark.parametrize("expression", [
    "prod()", "prod([1], 2)", "prod(iterable=[1])", "prod([1], extra=2)",
])
def test_math_prod_uses_the_standard_call_shape_diagnostics(expression):
    with pytest.raises(CompilationError):
        transpile_llvm(f'''
            from math import prod
            def main() -> str:
                return repr({expression})
        ''')


def test_math_prod_stored_polymorphic_reference_has_a_located_boundary():
    with pytest.raises(LLVMUnsupported, match="function values require.*fixed positional parameters at line"):
        transpile_llvm('''
            from math import prod
            def main() -> str:
                stored = prod
                return repr(stored([2, 3]))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_prod_integer_boundaries_and_float_result_contract(optimize):
    result = LLVM().assert_matches_python('''
        from math import prod
        from pyjs import int64
        def floating(values: list[float]) -> float:
            return prod(values, start=1.0)
        def main() -> str:
            lo = -9223372036854775808
            hi = 9223372036854775807
            return repr((prod([lo, 1]), prod([hi, 1]), prod([lo, 0]),
                         prod([-4611686018427387904, 2]), prod([-hi, -1]),
                         prod([True, hi]), prod([False, lo]),
                         prod([1099511627776, 1099511627776], start=1.0),
                         prod([int64(1099511627776), int64(1099511627776)]),
                         floating([]), floating([2.0, 3.0])))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_prod_integer_overflow_is_catchable_and_stops_at_failing_item(optimize):
    # CPython uses arbitrary precision here; assert the documented native
    # width boundary, separately from the in-range differential test above.
    result = LLVM().run_source('''
        from math import prod
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            for values in ([9223372036854775807, 2], [-9223372036854775808, -1],
                           [-9223372036854775808, 2], [-9223372036854775807, -2],
                           [1099511627776, 1099511627776]):
                try:
                    prod(values)
                except OverflowError as error:
                    assert str(error) == "math.prod result exceeds native int range"
                    caught += 1
            try:
                prod(range(1, 22))
            except OverflowError:
                caught += 1
            mixed: list[int | float] = [1099511627776, 1099511627776, 0.0]
            cursor = iter(mixed)
            try:
                prod(cursor, start=True)
            except OverflowError:
                caught += 1
            assert next(cursor) == 0.0
            try:
                prod([2], start=9223372036854775807)
            except OverflowError:
                caught += 1
            gc_collect()
            assert caught == 8
            assert prod([2, 3, 4]) == 24
            return 0
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_prod_allocation_failure_recovers(optimize, tmp_path):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
        from math import prod
        from tests.native.allocation_support import arm, remaining
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            for attempt in range(1, 100):
                values = [2.0, 3.0, 4.0]
                arm(attempt)
                succeeded = False
                try:
                    result = prod(iter(values), start=2)
                    assert result == 48.0
                    succeeded = True
                except MemoryError:
                    caught += 1
                exhausted = remaining() == 0
                arm(0)
                gc_collect()
                assert values == [2.0, 3.0, 4.0]
                assert prod(values, start=2) == 48.0
                if not exhausted:
                    assert succeeded and caught > 0
                    return 0
            return 1
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
