import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("expression", [
    "op.iadd(left, right)", "op.__iadd__(left, right)", "op.imul(left, 2)",
    "list(map(op.iadd, [left], [right]))", "list(map(op.imul, [left], [2]))",
])
def test_inplace_operator_static_arrays_keep_the_whole_array_diagnostic(expression):
    with pytest.raises(CompilationError, match="Static arrays do not support whole-array augmented assignment") as caught:
        transpile_llvm(f'''import operator as op
from pyjs import StaticArray, int32
def main() -> object:
    left = StaticArray[int32, 2]([1, 2])
    right = StaticArray[int32, 1]([3])
    return {expression}
''', filename="operator_array.py")
    assert caught.value.lineno == 6
    assert caught.value.diagnostic.help == ("Assign individual items or create another static array.",)


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_searches_preserve_boxed_nan_identity(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            value: object = float("nan")
            other: object = float("nan")
            values: list[object] = [other, value, 1, value]
            gc_collect()
            return repr((op.countOf(values, value), op.indexOf(values, value),
                         op.countOf(values, other), op.indexOf(values, other)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_searches_report_erased_equality_boundaries_and_recover(optimize):
    # This is the documented native object-view boundary, not CPython parity:
    # only the selected non-identity callback needs the erased ABI contract.
    result = LLVM().run_source('''
        import operator as op
        from pyjs.native import gc_collect, gc_set_threshold
        class Narrow:
            def __eq__(self, other: "Narrow") -> bool: return True
        class NonBoolean:
            def __eq__(self, other: object) -> int: return 1
        def main() -> int:
            gc_set_threshold(1)
            first = Narrow()
            second = NonBoolean()
            assert op.countOf([first], first) == 1
            assert op.indexOf([second], second) == 0
            caught = 0
            try: op.countOf([first], Narrow())
            except TypeError as error:
                assert "callbacks require an object parameter" in str(error)
                caught += 1
            try: op.indexOf([second], NonBoolean())
            except TypeError as error:
                assert "callbacks require a builtin bool result" in str(error)
                caught += 1
            gc_collect()
            assert caught == 2
            assert op.countOf([first], first) == 1
            assert op.indexOf([second], second) == 0
            assert op.countOf([1, 2, 1], 1) == 2
            return 0
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_inplace_operator_results_mutation_and_aliases(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from pyjs import int8, float32
        def main() -> str:
            numbers = [1, 2]
            alias = numbers
            added = op.iadd(numbers, [3])
            repeated = op.imul(numbers, 2)
            values = {1, 2, 3}
            intersection = op.iand(values, {2, 3, 4})
            union = op.ior(values, {5})
            difference = op.isub(values, {2})
            symmetric = op.ixor(values, {3, 7})
            settings = {"workers": 2}
            merged = op.ior(settings, {"workers": 4, "threads": 8})
            scalars = (op.iadd(2, 3), op.iand(7, 3), op.ifloordiv(-7, 3),
                       op.ilshift(1, 4), op.imod(-7, 3), op.imul(6, 7), op.ior(4, 1),
                       op.ipow(3, 4), op.irshift(-8, 2), op.isub(7, 3),
                       op.itruediv(7, 2), op.ixor(7, 3),
                       int(op.iadd(int8(127), int8(1))),
                       float(op.imul(float32(1.5), float32(2.0))))
            return repr((numbers, sorted(values), settings, scalars,
                         numbers is alias, added is numbers, repeated is numbers,
                         intersection is values, union is values, difference is values,
                         symmetric is values, merged is settings))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_searches_use_identity_then_equality_and_keep_cursor(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int, events: list[int]):
                self.value, self.events = value, events
            def __eq__(self, other: object) -> bool:
                self.events.append(self.value)
                gc_collect()
                return isinstance(other, Value) and self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            target = Value(2, events)
            values = [Value(1, events), target, Value(2, events)]
            count = op.countOf(values, target)
            counted = list(events)
            events.clear()
            cursor = iter(values)
            position = op.indexOf(cursor, target)
            indexed = list(events)
            rest = next(cursor).value
            primitives = (op.countOf(("a", "b", "a"), "a"),
                          op.countOf((value % 3 for value in range(10)), 1),
                          op.indexOf("taskmaster", "m"), op.countOf(b"ababa", 97),
                          op.indexOf(map(lambda value: value * 2, range(6)), 8))
            missing = ""
            try: op.indexOf(range(3), 9)
            except ValueError as error: missing = str(error)
            return repr((count, counted, position, indexed, rest, primitives, missing))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_inplace_operator_application_dispatch_results_and_effect_order(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int, events: list[str]):
                self.value, self.events = value, events
            def __iadd__(self, other: int) -> "Value":
                self.events.append("inplace")
                gc_collect()
                self.value += other
                return self
        class Child(Value):
            def __iadd__(self, other: int) -> Value:
                self.events.append("child")
                gc_collect()
                return Value(self.value + other * 2, self.events)
        class Binary:
            def __init__(self, value: int): self.value = value
            def __add__(self, other: int) -> int: return self.value + other
        class Changing:
            def __iadd__(self, other: int) -> str:
                gc_collect()
                return "changed-" + str(other)
        def left(events: list[str], value: Value) -> Value:
            events.append("left")
            gc_collect()
            return value
        def right(events: list[str], fail: bool) -> int:
            events.append("right")
            gc_collect()
            if fail: raise ValueError("operand")
            return 3
        def update(value: Value, events: list[str]) -> str:
            changed = op.iadd(left(events, value), right(events, False))
            return repr((value.value, changed.value, changed is value))
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            value = Value(4, events)
            direct = update(value, events)
            child = update(Child(4, events), events)
            try: op.iadd(left(events, value), right(events, True))
            except ValueError: events.append("caught")
            callback = list(map(op.iadd, [Value(1, events)], [2]))
            return repr((direct, child, value.value, events, callback[0].value,
                         op.iadd(Binary(5), 3), op.iadd(Changing(), 9),
                         op.itruediv(3, 2)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_search_errors_and_partial_mutation_preserve_iterators(optimize):
    result = LLVM().assert_matches_python('''
        import operator as op
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, value: int): self.value = value
            def __eq__(self, other: object) -> bool:
                gc_collect()
                if self.value == 2: raise ValueError("comparison")
                return isinstance(other, Value) and self.value == other.value
        def failing() -> Iterator[int]:
            yield 3
            gc_collect()
            raise ValueError("iterator")
        def main() -> str:
            gc_set_threshold(1)
            errors: list[str] = []
            cursor = iter([Value(1), Value(2), Value(3)])
            try: op.countOf(cursor, Value(9))
            except ValueError as error: errors.append(str(error))
            rest = next(cursor).value
            values = [1, 2]
            alias = values
            try: op.iadd(values, failing())
            except ValueError as error: errors.append(str(error))
            try: op.indexOf(failing(), 9)
            except ValueError as error: errors.append(str(error))
            try: op.ifloordiv(1, 0)
            except ZeroDivisionError: errors.append("division")
            try: op.ilshift(1, -1)
            except ValueError: errors.append("shift")
            return repr((errors, rest, values, values is alias,
                         op.countOf(iter([1, 1]), 1), op.indexOf(iter([3, 4]), 4)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_search_and_mutation_allocation_failures_leave_valid_inputs(tmp_path, optimize):
    source = transpile_llvm('''
        import operator as op
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        class Value:
            def __init__(self, value: int): self.value = value
            def __eq__(self, other: object) -> bool:
                gc_collect()
                return isinstance(other, Value) and self.value == other.value
        def main() -> int:
            gc_set_threshold(1)
            failures = 0
            exhausted = False
            for stage in range(1, 200):
                values = [Value(1), Value(2)]
                additions = [Value(3), Value(2)]
                target = Value(2)
                try:
                    arm(stage)
                    op.iadd(values, additions)
                    count = op.countOf(values, target)
                    position = op.indexOf(values, target)
                    exhausted = remaining() > 0
                    arm(0)
                    assert count == 2 and position == 1
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                # Growth may partially commit before failure, but existing
                # elements, ownership and subsequent iteration remain valid.
                actual = [value.value for value in values]
                assert actual == [1, 2] or actual == [1, 2, 3] or actual == [1, 2, 3, 2]
                assert [value.value for value in additions] == [3, 2]
                assert op.indexOf(values, target) == 1
                if exhausted: break
            assert exhausted and failures > 0
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
