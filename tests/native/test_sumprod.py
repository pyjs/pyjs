import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["sumprod([1, 2], (0.5, 1.5))", "sumprod([], ())"])
def test_sumprod_prepares_cold_cursor_types_without_other_numeric_sources(optimize, expression):
    result = LLVM().assert_matches_python(f'''
        from math import sumprod
        def main() -> str:
            return repr({expression})
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_sumprod_numeric_sources_result_kinds_and_extended_precision(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from math import sumprod
        from itertools import count, islice
        from pyjs import StaticArray
        def integer_result(values: list[int]) -> int:
            return sumprod(values, values)
        def floating_result() -> float:
            return sumprod([1.5], [2])
        def array_result(values: StaticArray[float, 2]) -> float:
            return sumprod(values, [2, 3])
        def main() -> str:
            fixed: StaticArray[float, 2] = [1.5, 2.0]
            values: list[list[float]] = [
                [1e16, 1.0, -1e16], [1e100, 1e-100, -1e100],
                [1e308, 1e308], [math.inf, -math.inf], [math.nan, 1.0],
                [-0.0], [], [1.0000000000000002, -1.0],
            ]
            factors: list[list[float]] = [
                [1.0, 1.0, 1.0], [1e-100, 1e100, 1e-100], [1.0, 1.0],
                [1.0, 1.0], [1.0, 1.0], [1.0], [],
                [1.0000000000000002, 1.0000000000000004],
            ]
            output: list[str] = []
            for index in range(len(values)):
                output.append(repr(sumprod(values[index], factors[index])))
            mixed: list[int | float] = [1, 1e16, 1.0, -1e16, 3, 1e16, 1.0, -1e16]
            booleans: list[int | float] = [True, 1e16, 1.0, -1e16]
            output.append(repr(sumprod(mixed, [1.0] * len(mixed))))
            output.append(repr(sumprod(mixed, [1] * len(mixed))))
            output.append(repr(sumprod(booleans, [1, 1, 1, 1])))
            return repr((output, math.sumprod([1, 2, 3], (4, 5, 6)),
                         sumprod(islice(count(1), 4), range(4, 8)),
                         sumprod(bytes([2, 3]), {4: 1, 5: 2}),
                         sumprod({2, 3}, {2, 3}), array_result(fixed),
                         sumprod([], []), sumprod((), ()),
                         integer_result([]), integer_result([2, 3]), floating_result()))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "sumprod()", "sumprod([1])", "sumprod([1], [1], [1])",
    "sumprod(p=[1], q=[1])", "sumprod([1], [1], extra=1)",
    'sumprod(["a"], [1])', "sumprod([int8(2)], [int8(3)])",
])
def test_sumprod_rejects_unsupported_call_and_numeric_boundaries(expression):
    with pytest.raises(CompilationError):
        transpile_llvm(f'''
            from math import sumprod
            from pyjs import int8
            def main() -> str:
                return repr({expression})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_sumprod_protocol_order_aliases_exceptions_and_gc(optimize):
    result = LLVM().assert_matches_python('''
        from math import sumprod
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self, label: str, values: list[int | float], events: list[str], fail: int):
                self.label = label
                self.values = values
                self.events = events
                self.index = 0
                self.fail = fail
            def __iter__(self) -> "Cursor":
                self.events.append(self.label + " iter")
                gc_collect()
                if self.fail == -2:
                    raise ValueError(self.label + " acquisition")
                return self
            def __next__(self) -> int | float:
                self.events.append(self.label + str(self.index))
                gc_collect()
                if self.index == self.fail:
                    self.index += 1
                    raise ValueError(self.label + " failure")
                if self.index == len(self.values):
                    raise StopIteration("done")
                value = self.values[self.index]
                self.index += 1
                return value
        def make(label: str, values: list[int | float], events: list[str]) -> Cursor:
            events.append("make " + label)
            gc_collect()
            return Cursor(label, values, events, -1)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            result = sumprod(make("p", [1, 2.5], events), make("q", [3, 4], events))
            messages: list[str] = []
            empty: list[int | float] = []
            try:
                sumprod(Cursor("e", empty, events, -1), Cursor("r", [3], events, 0))
            except ValueError as error:
                messages.append(str(error))
            right = Cursor("right", [1, 2, 3], events, -1)
            try:
                sumprod(Cursor("left", [1], events, -1), right)
            except ValueError as error:
                messages.append(str(error))
            remaining = next(right)
            try:
                sumprod(make("rooted", [1], events), Cursor("qfail", [1], events, -2))
            except ValueError as error:
                messages.append(str(error))
            for failure in [-2, 0]:
                try:
                    sumprod(Cursor("fail", [1], events, failure), Cursor("unused", [1], events, -1))
                except ValueError as error:
                    messages.append(str(error))
            cursor = iter([1, 2, 3, 4])
            alias = sumprod(cursor, cursor)
            cursor2 = iter([1, 2, 3])
            try:
                sumprod(cursor2, cursor2)
            except ValueError as error:
                messages.append(str(error))
            for mode in [0, 1]:
                try:
                    if mode == 0:
                        sumprod([], [1])
                    else:
                        sumprod([1], ())
                except ValueError as error:
                    messages.append(str(error))
            recovered = sumprod([2.0], [3])
            return repr((result, events, messages, remaining, alias, recovered))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_sumprod_checks_integer_width_and_recovers(optimize):
    # The native math contract bounds integer intermediates, unlike CPython.
    result = LLVM().run_source('''
        from math import sumprod
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            cases: list[tuple[list[int | float], list[int]]] = [
                ([9223372036854775807], [2]), ([-9223372036854775808], [-1]),
                ([9223372036854775807, 1], [1, 1]), ([-9223372036854775808, -1], [1, 1]),
                ([True, 9223372036854775807, 1], [1, 1, 1])]
            for left, right in cases:
                try:
                    sumprod(left, right)
                except OverflowError as error:
                    assert str(error) == "math.sumprod result exceeds native int range"
                    caught += 1
                gc_collect()
            values: list[int | float] = [9223372036854775807, 1, 0.0]
            cursor = iter(values)
            try:
                sumprod(cursor, [1, 1, 0])
            except OverflowError:
                caught += 1
            assert next(cursor) == 0.0
            assert caught == 6
            assert sumprod([-9223372036854775808], [1]) == -9223372036854775808
            assert sumprod([9223372036854775807], [1]) == 9223372036854775807
            assert sumprod([2, 3], [4, 5]) == 23
            return 0
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.parametrize("optimize", [0, 2])
def test_sumprod_allocation_failure_preserves_inputs_and_recovers(optimize, tmp_path):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
        from math import sumprod
        from tests.native.allocation_support import arm, remaining
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            for attempt in range(1, 150):
                left = [2.0, 3.0, 4.0]
                right = [3, 4, 5]
                arm(attempt)
                succeeded = False
                try:
                    assert sumprod(iter(left), iter(right)) == 38.0
                    succeeded = True
                except MemoryError:
                    caught += 1
                exhausted = remaining() == 0
                arm(0)
                gc_collect()
                assert left == [2.0, 3.0, 4.0] and right == [3, 4, 5]
                assert sumprod(left, right) == 38.0
                if not exhausted:
                    assert succeeded and caught > 0
                    return 0
            return 1
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
