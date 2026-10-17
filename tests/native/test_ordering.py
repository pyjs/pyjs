import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import OBJECT_ORDERING_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_comparison_binding_in_sequences_and_extrema(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        class Item:
            def __init__(self, value: int):
                self.value = value
            @staticmethod
            def __lt__(other: Item) -> bool:
                return other.value > 0
        def main() -> str:
            return repr(([Item(1)] < [Item(2)], [Item(1)] < [Item(0)],
                         [value.value for value in sorted([Item(1), Item(2)])],
                         min([Item(1), Item(2)]).value, max([Item(1), Item(2)]).value))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_sequence_ordering_rejects_keyword_only_comparison_operand():
    with pytest.raises(LLVMUnsupported, match="__lt__ requires a compatible typed argument"):
        transpile_llvm('''
            class Item:
                def __lt__(self, *, other: Item) -> bool:
                    return True
            def main() -> int:
                return 1 if [Item()] < [Item()] else 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["<", "<=", ">", ">="])
def test_incompatible_sequence_ordering_keeps_source_error_order(tmp_path, optimize, operation):
    result = LLVM().assert_matches_python(f'''
        def main() -> str:
            left: list[int] = [1]
            right: tuple[int] = (1,)
            output = ""
            try:
                output += str(left {operation} right)
            except TypeError as error:
                output += str(error)
            try:
                output += str(right {operation} left)
            except TypeError as error:
                output += "|" + str(error)
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_shared_object_ordering_contract():
    result = LLVM().assert_matches_python(OBJECT_ORDERING_CONTRACT.source)
    assert result.native.returncode == 0, OBJECT_ORDERING_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_union_structural_ordering(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def pair(a: int | float, b: int | float) -> str:
            left: tuple[int | float, str] = (a, "same")
            right: tuple[int | float, str] = (b, "same")
            return str((left < right, left <= right, left > right, left >= right))

        def number(row: tuple[int | float, str]) -> int | float:
            return row[0]

        def main() -> str:
            d: dict[float | int, int] = {1: 2, 1.5: 3, -2: 4, -1.5: 5}
            result = str(sorted(d.items()))
            values: list[int | float] = [True, -1, -0.5, 0, 1.5, float("inf")]
            for a in values:
                for b in values:
                    result += pair(a, b)
                result += pair(a, float("nan")) + pair(float("nan"), a)
            result += pair(float("nan"), float("nan"))
            result += pair(int("9007199254740993"), 9007199254740992.0)
            result += pair(-9223372036854775808.0, int("-9223372036854775807"))
            result += str(([1] < [1.5], (False, "x") <= (0, "x")))
            nested: list[list[int | float]] = [[1.5], [1], [-1.0, 2]]
            result += str(sorted(nested))
            rows: list[tuple[int | float, str]] = [(2, "a"), (1.0, "b"), (1, "c")]
            result += str(sorted(rows)) + str(sorted(rows, reverse=True))
            rows.sort()
            result += str(rows) + str(min(rows)) + str(max(rows))
            result += str(sorted(rows, key=number, reverse=True))
            direct: list[int | float] = [1.5, True, 1, -1.0, False, 0.0]
            result += str(sorted(direct)) + str(sorted(direct, reverse=True))
            direct.sort()
            result += str(direct)
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("annotation, value", [("int | str", '"a"'), ("int | None", "None")])
def test_non_numeric_union_ordering_diagnoses(annotation, value):
    with pytest.raises(CompilationError, match=r"sorted\(\) cannot order values of type tuple"):
        transpile_llvm(f'''
            def main() -> str:
                rows: list[tuple[{annotation}, str]] = [(1, "a"), ({value}, "b")]
                return str(sorted(rows))
        ''')


@pytest.mark.parametrize("operation", ["values.sort()", "sorted(values)", "values < values"])
def test_application_union_ordering_dispatches_selected_members(operation):
    result = LLVM().assert_matches_python(f'''
            EVENTS: list[str] = []
            class A:
                def __lt__(self, other: object) -> bool:
                    EVENTS.append("A")
                    return True

            class B:
                def __lt__(self, other: object) -> bool:
                    EVENTS.append("B")
                    return True

            def main() -> str:
                values: list[A | B] = [A(), B()]
                {operation}
                return ",".join(EVENTS)
        ''', sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_structural_ordering_sort_and_extrema(optimize):
    LLVM().assert_matches_python('''
        class Box:
            def __init__(self, value: int, label: str):
                self.value = value
                self.label = label

            def __eq__(self, other: "Box") -> bool:
                return self.value == other.value

            def __lt__(self, other: "Box") -> bool:
                return self.value < other.value

            def __le__(self, other: "Box") -> bool:
                return self.value <= other.value

            def __gt__(self, other: "Box") -> bool:
                return self.value > other.value

            def __ge__(self, other: "Box") -> bool:
                return self.value >= other.value

        def key(value: Box) -> tuple[int, str]:
            return (value.value, value.label)

        def object_key(value: Box) -> Box:
            return value

        def labels(values: list[Box]) -> str:
            result = ""
            for value in values:
                result += value.label
            return result

        def main() -> str:
            a = Box(2, "a")
            b = Box(1, "b")
            c = Box(2, "c")
            assert b < a and b <= a and a > b and a >= b
            assert [b] < [a] and [a] <= [c] and [a] >= [c]
            assert ([b], "z") < ([a], "a")
            assert (1, "a") < (1, "b")
            assert (1,) < (1, "a") and () <= (1,)
            assert sorted([[2], [1, 2], [1]]) == [[1], [1, 2], [2]]
            assert labels(sorted([a, b, c])) == "bac"
            assert labels(sorted([a, b, c], reverse=True)) == "acb"
            values = [a, b, c]
            values.sort()
            assert labels(values) == "bac"
            values.sort(key=key, reverse=True)
            assert labels(values) == "cab"
            values.sort(key=object_key)
            assert labels(values) == "bca"
            assert min(values) is b and max(values) is c
            assert min(values, key=key) is b and max(values, key=key) is c
            assert min((2, "b"), (2, "a")) == (2, "a")
            return labels(values)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_ordering_reflection_identity_and_runtime_subtypes(optimize):
    LLVM().assert_matches_python('''
        class Base:
            def __init__(self, events: list[str]):
                self.events = events

            def __lt__(self, other: "Base") -> bool:
                self.events.append("base.lt")
                return True

            def __gt__(self, other: "Base") -> bool:
                self.events.append("base.gt")
                return False

        class Child(Base):
            def __gt__(self, other: Base) -> bool:
                self.events.append("child.gt")
                return True

        class Reflected:
            def __gt__(self, other: "Reflected") -> bool:
                return True

        class Plain:
            pass

        def compare(a: Base, b: Base) -> bool:
            return a < b

        def main() -> str:
            events: list[str] = []
            a = Base(events)
            b = Child(events)
            assert compare(a, b)
            assert compare(a, a)
            assert compare(b, a)
            assert events == ["child.gt", "base.lt", "base.lt"]
            assert Reflected() < Reflected()
            try:
                assert [Plain()] < [Plain()]
                return "missing TypeError"
            except TypeError:
                pass
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_float_nan_uses_requested_sequence_operator(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            same = [float("nan")]
            assert same <= same and same >= same
            assert not ([float("nan")] < [1.0])
            assert not ([float("nan")] <= [1.0])
            assert not ([float("nan")] > [1.0])
            assert not ([float("nan")] >= [1.0])
            assert [1.0] <= [1.0] and [1.0] >= [1.0]
            assert [b"a"] < [b"b"] and ["b"] >= ["a"]
            return "passed"
    ''', optimize=optimize)


def test_non_boolean_ordering_is_a_focused_boundary():
    with pytest.raises(LLVMUnsupported, match="compatible typed argument and bool result"):
        transpile_llvm('''
            class Box:
                def __lt__(self, other: "Box") -> int:
                    return 1

            def main() -> bool:
                return [Box()] < [Box()]
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("mutation", ["clear", "grow"])
def test_equality_mutation_reloads_ordering_operands(optimize, mutation, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int, source: list["Box"], events: list[int]):
                self.value = value
                self.source = source
                self.events = events

            def __eq__(self, other: "Box") -> bool:
                self.events.append(1)
                {"self.source.clear()" if mutation == "clear" else "self.source.extend([self] * 50)"}
                gc_collect()
                return False

            def __lt__(self, other: "Box") -> bool:
                gc_collect()
                self.events.append(self.value + other.value)
                return self.value < other.value

        def main() -> str:
            gc_set_threshold(1)
            source: list[Box] = []
            events: list[int] = []
            source.append(Box(1, source, events))
            assert source < [Box(2, source, events)]
            assert events == {[1] if mutation == "clear" else [1, 3]}
            assert len(source) == {0 if mutation == "clear" else 51}
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("keyed", [False, True])
def test_sort_comparisons_detach_restore_and_preserve_permutation(optimize, keyed):
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class State:
            def __init__(self, source: list["Box"]):
                self.source = source
                self.mutate = False
                self.fail = False
                self.calls = 0
                self.keys = 0

        class Box:
            def __init__(self, value: int, state: State):
                self.value = value
                self.state = state

            def __lt__(self, other: "Box") -> bool:
                self.state.calls += 1
                assert len(self.state.source) == 0
                if self.state.mutate:
                    self.state.source.append(self)
                    self.state.source.clear()
                gc_collect()
                if self.state.fail:
                    raise LookupError("comparison failed")
                return self.value < other.value

        def key(value: Box) -> Box:
            value.state.keys += 1
            gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            source: list[Box] = []
            state = State(source)
            for value in [3, 1, 2, 0]:
                source.append(Box(value, state))
            alias = source
            for fail in [False, True]:
                state.mutate = True
                state.fail = fail
                caught = False
                try:
                    source.sort({"key=key" if keyed else ""})
                except LookupError:
                    assert fail
                    caught = True
                except ValueError:
                    assert not fail
                    caught = True
                assert caught and len(source) == 4 and alias is source
                assert sorted([value.value for value in source]) == [0, 1, 2, 3]
                gc_collect()
            state.mutate = False
            state.fail = False
            source.sort({"key=key" if keyed else ""})
            assert [value.value for value in source] == [0, 1, 2, 3]
            assert state.calls > 0 and state.keys == {12 if keyed else 0}
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_extrema_use_gt_and_keep_new_key_alive_after_source_clear(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, events: list[int], source: list[int]):
                self.value = value
                self.events = events
                self.source = source

            def __lt__(self, other: "Key") -> bool:
                self.events.append(1)
                self.source.clear()
                gc_collect()
                return self.value < other.value

            def __gt__(self, other: "Key") -> bool:
                self.events.append(2)
                self.source.clear()
                gc_collect()
                return self.value > other.value

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            source = [1, 3, 2]
            key: Callable[[int], Key] = lambda value: Key(value, events, source)
            assert max(source, key=key) == 3
            assert source == [] and events == [2]
            source.extend([2, 1, 3])
            assert min(source, key=key) == 1
            assert source == [] and events == [2, 1]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["sorted(values)", "values.sort()", "min(values)", "max(values)"])
def test_ordering_callbacks_can_retain_members_after_function_return(optimize, operation):
    source = f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int, saved: list["Box"]):
                self.value = value
                self.saved = saved

            def __lt__(self, other: "Box") -> bool:
                self.saved.append(self)
                self.saved.append(other)
                gc_collect()
                return self.value < other.value

            def __gt__(self, other: "Box") -> bool:
                return other < self

        def retain(saved: list[Box]) -> None:
            values = [Box(7, saved), Box(9, saved)]
            {operation}

        def main() -> int:
            gc_set_threshold(1)
            saved: list[Box] = []
            retain(saved)
            gc_collect()
            assert len(saved) == 2
            return saved[0].value + saved[1].value
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        lifetime = analysis.entry_point.container.search("retain").ir.lifetime
        assert all(allocation.boundary is LifetimeBoundary.EXTERNAL for allocation in lifetime.allocations)
    LLVM().assert_matches_python(source, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_sequence_ordering_uses_replaced_items_without_repeating_equality(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int, source: list["Box"], events: list[int]):
                self.value = value
                self.source = source
                self.events = events

            def __eq__(self, other: "Box") -> bool:
                self.events.append(self.value)
                self.source[0] = Box(9, self.source, self.events)
                gc_collect()
                return False

            def __lt__(self, other: "Box") -> bool:
                self.events.append(self.value)
                self.source.clear()
                gc_collect()
                return self.value < other.value

        def main() -> str:
            gc_set_threshold(1)
            source: list[Box] = []
            events: list[int] = []
            source.append(Box(1, source, events))
            assert not (source < [Box(2, source, events)])
            assert events == [1, 9] and len(source) == 0
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_structural_sort_allocation_failure_restores_source(optimize, tmp_path):
    from tests.native.allocation_support import run_allocation_case

    llvm_ir = transpile_llvm('''
        from tests.native.allocation_support import arm, remaining
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

            def __lt__(self, other: "Box") -> bool:
                gc_collect()
                temporary = [self.value, other.value]
                return temporary[0] < temporary[1]

        def key(value: Box) -> tuple[Box, int]:
            return (Box(value.value), 0)

        def main() -> int:
            gc_set_threshold(1)
            attempt = 1
            caught = 0
            while attempt < 180:
                values = [Box(3), Box(1), Box(2)]
                alias = values
                arm(attempt)
                succeeded = False
                try:
                    values.sort(key=key)
                    succeeded = True
                except MemoryError:
                    caught += 1
                exhausted = remaining() == 0
                arm(0)
                assert values is alias and len(values) == 3
                assert sorted([value.value for value in values]) == [1, 2, 3]
                gc_collect()
                if succeeded:
                    assert values[0].value == 1 and values[2].value == 3
                if not exhausted:
                    assert succeeded and caught > 0
                    return 0
                attempt += 1
            return 1
    ''')
    run_allocation_case(llvm_ir, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_implicit_ordering_reaches_subclass_and_reflected_methods(optimize):
    LLVM().assert_matches_python('''
        class Base:
            def __init__(self, value: int):
                self.value = value

        class Child(Base):
            def __gt__(self, other: Base) -> bool:
                return self.value > other.value

        def ordered(values: list[Base]) -> list[Base]:
            return sorted(values)

        def compare(left: tuple[Base, str], right: tuple[Child, str]) -> bool:
            return left < right

        def main() -> str:
            values: list[Base] = [Child(3), Child(1), Child(2)]
            result = ordered(values)
            assert [item.value for item in result] == [1, 2, 3]
            assert min(values).value == 1 and max(values).value == 3
            assert compare((Base(1), "x"), (Child(2), "x"))
            return "passed"
    ''', optimize=optimize)


def test_ordering_only_reaches_needed_dunders():
    LLVM().assert_matches_python('''
        class Box:
            def __init__(self, value: int):
                self.value = value

            def __lt__(self, other: "Box") -> bool:
                return self.value < other.value

            def __eq__(self, other: "Box") -> bool:
                return missing_equality()

            def __le__(self, other: "Box") -> bool:
                return missing_ordering()

        def main() -> int:
            values = [Box(2), Box(1)]
            assert values[1] < values[0]
            values.sort()
            return min(values).value
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_variadic_tuples_and_large_stable_runs(optimize):
    LLVM().assert_matches_python('''
        def compare(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
            return left < right

        def empty(value: tuple[int, ...]) -> bool:
            return value >= () and not (value < ())

        def key(value: tuple[int, int]) -> tuple[int, int]:
            return (value[0], 0)

        def main() -> str:
            assert compare((1, 2), (1, 3, 0))
            assert compare((), (1,))
            assert empty(()) and empty((1, 2))
            values = [(index % 13, index) for index in range(257)]
            result = sorted(values, key=key, reverse=True)
            assert len(result) == 257
            previous = (13, -1)
            for value in result:
                assert value[0] <= previous[0]
                if value[0] == previous[0]:
                    assert value[1] > previous[1]
                previous = value
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("comparison", ["left < right", "right > left", "left <= right", "right >= left"])
def test_reflected_ordering_lifetime_retains_the_other_operand(comparison):
    source = f'''
        from pyjs.native import gc_collect

        class Base:
            def __init__(self, value: int):
                self.value = value

        class Child(Base):
            def __init__(self, saved: list[Base]):
                super().__init__(1)
                self.saved = saved

            def __gt__(self, other: Base) -> bool:
                self.saved.append(other)
                return True

            def __ge__(self, other: Base) -> bool:
                self.saved.append(other)
                return True

        def retain(right: Base) -> bool:
            left = Base(7)
            return {comparison}

        def main() -> int:
            saved: list[Base] = []
            assert retain(Child(saved))
            gc_collect()
            return saved[0].value
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        [allocation] = analysis.entry_point.container.search("retain").ir.lifetime.allocations
        assert allocation.boundary is LifetimeBoundary.CALLER
    LLVM().assert_matches_python(source, optimize=2)


@pytest.mark.parametrize("operation", ["__lt__", "__le__", "__gt__", "__ge__"])
def test_explicit_default_ordering_has_a_located_diagnostic(operation):
    with pytest.raises(LLVMUnsupported, match=f"explicit object.{operation} may return NotImplemented.*at line"):
        transpile_llvm(f'''
            class Box:
                pass

            def main() -> bool:
                return Box().{operation}(Box())
        ''')


def test_variadic_heterogeneous_ordering_reports_only_reached_type_errors():
    result = LLVM().assert_matches_python('''
            def compare(value: tuple[int, ...]) -> str:
                try:
                    return str(value < (1, "a"))
                except TypeError as error:
                    return str(error)

            def main() -> str:
                return compare(()) + "|" + compare((0, 2)) + "|" + compare((1, 2))
        ''', sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_missing_ordering_messages_match_python(optimize):
    LLVM().assert_matches_python('''
        class Plain:
            pass

        class Ordered:
            def __lt__(self, other: "Ordered") -> bool:
                return False

        def main() -> str:
            result = ""
            a = Plain()
            b = Plain()
            for case in range(9):
                try:
                    if case == 0:
                        a < b
                    elif case == 1:
                        a <= b
                    elif case == 2:
                        a > b
                    elif case == 3:
                        a >= b
                    elif case == 4:
                        Ordered() <= Ordered()
                    elif case == 5:
                        sorted([a, b])
                    elif case == 6:
                        min(a, b)
                    elif case == 7:
                        max(a, b)
                    else:
                        [a] < [b]
                except TypeError as error:
                    result += str(error) + "\\n"
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_ordering_messages_use_available_runtime_types(optimize):
    LLVM().assert_matches_python('''
        class Base:
            def __lt__(self, other: "Base") -> bool:
                return False

        class First(Base):
            pass

        class Second(Base):
            pass

        class Plain:
            pass

        def compare(a: Base, b: Base) -> str:
            # Reach the inherited method so this hierarchy has vtable identities.
            assert not (a < b)
            result = ""
            try:
                a <= b
            except TypeError as error:
                result += str(error) + "\\n"
            try:
                [a] >= [b]
            except TypeError as error:
                result += str(error) + "\\n"
            try:
                a >= Plain()
            except TypeError as error:
                result += str(error) + "\\n"
            try:
                Plain() <= a
            except TypeError as error:
                result += str(error) + "\\n"
            return result

        def main() -> str:
            return compare(First(), Second()) + compare(Second(), First()) + compare(Base(), First())
    ''', optimize=optimize)


def test_ordering_messages_use_inherited_runtime_identity_without_overrides():
    result = LLVM().run_source('''
        class Base:
            pass

        class Child(Base):
            pass

        def compare(a: Base, b: Base) -> str:
            try:
                a < b
            except TypeError as error:
                return str(error)
            return "unexpected success"

        def main() -> str:
            return compare(Child(), Base())
    ''')
    assert result.returncode == 0, result.stderr
    assert result.stdout == "'<' not supported between instances of 'Child' and 'Base'"
