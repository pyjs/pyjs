import pytest

from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import OBJECT_COMPARISON_CONTRACT


def test_shared_object_comparison_contract():
    result = LLVM().assert_matches_python(OBJECT_COMPARISON_CONTRACT.source)
    assert result.native.returncode == 0, OBJECT_COMPARISON_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_mixed_numeric_comparisons_keep_integer_precision(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from math import inf, nan
        def compare(left: int, right: float) -> str:
            optional: int | None = left
            return str((left == right, right == left, left != right, right != left,
                        left < right, right > left, left <= right, right >= left,
                        left > right, right < left, left >= right, right <= left,
                        optional == right, optional != right))
        def main() -> str:
            results: list[str] = []
            for left in [-9223372036854775808, -9007199254740993, -1, 0, 1,
                         9007199254740993, 9223372036854775807]:
                for right in [-inf, -9223372036854775808.0, -9007199254740992.0,
                              -1.5, -0.0, 1.5, 9007199254740992.0,
                              9223372036854775808.0, inf, nan]:
                    results.append(compare(left, right))
                    results.append(str((True == right, right != False,
                                        True < right, right <= False)))
            # Literal/local fast paths must use the same exact comparison.
            large = 9007199254740993
            rounded = 9007199254740992.0
            assert large != rounded and rounded < large
            return '|'.join(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_object_equality_and_search(optimize):
    LLVM().assert_matches_python('''
        class Box:
            def __init__(self, value: int):
                self.value = value

            def __eq__(self, other: "Box") -> bool:
                return self.value == other.value

        def main() -> int:
            a = [Box(1), Box(2)]
            b = [Box(1), Box(2)]
            assert a == b
            assert Box(2) in a
            assert a.index(Box(2)) == 1
            assert a.count(Box(1)) == 1
            assert (Box(1), "a") == (Box(1), "a")
            assert (a, {"a": Box(2)}) == (b, {"a": Box(2)})
            assert [[Box(3)]] != [[Box(4)]]
            assert Box(2) in {"x": Box(2)}.values()
            assert ("x", Box(2)) in {"x": Box(2)}.items()
            a.remove(Box(1))
            assert a == [Box(2)]
            assert 0 < len(a) < 4
            return 4
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_chains_evaluate_operands_once_and_stop_early(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def record(events: list[int], value: int) -> int:
            events.append(value)
            gc_collect()
            return value

        def text(events: list[int], value: int) -> str:
            return "value:" + str(record(events, value))

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            assert record(events, 1) < record(events, 2) < record(events, 3)
            assert events == [1, 2, 3]
            assert not (record(events, 4) < record(events, 3) < record(events, 0))
            assert events == [1, 2, 3, 4, 3]
            assert text(events, 5) == text(events, 5) != text(events, 6)
            assert 0 < int(1 < record(events, 2) < 3) < 2
            assert events == [1, 2, 3, 4, 3, 5, 5, 6, 2]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_identity_shortcuts_and_search_bounds_do_not_call_equality(optimize):
    LLVM().assert_matches_python('''
        class Box:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: "Box") -> bool:
                self.events.append(self.value)
                if self.value == 0:
                    raise ValueError("must not compare")
                return self.value == other.value

        def main() -> str:
            events: list[int] = []
            a = Box(0, events)
            b = Box(2, events)
            values = [a, b]
            assert values == values
            assert values == [a, b]
            assert values.count(a) == 1
            assert events == [2]
            events.clear()
            assert values.index(b, 1) == 1
            assert values.index(Box(2, events), -1, 2) == 1
            assert (a, b).index(Box(2, events), 1) == 1
            assert events == [2, 2]
            try:
                values.index(b, 2, 1)
                return "missing ValueError"
            except ValueError:
                pass
            assert events == [2, 2]
            assert (Box(3, events), a) != (Box(4, events), b)
            assert [Box(3, events), a] != [Box(4, events), b]
            assert events == [2, 2, 3, 3]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_reflected_subclass_equality_and_virtual_dispatch(optimize):
    LLVM().assert_matches_python('''
        class Base:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: "Base") -> bool:
                self.events.append(self.value)
                return True

        class Child(Base):
            def __eq__(self, other: Base) -> bool:
                self.events.append(self.value * 10)
                return True

        def compare(a: Base, b: Base) -> bool:
            return [a] == [b]

        def main() -> str:
            events: list[int] = []
            a = Base(1, events)
            b = Child(2, events)
            c = Child(3, events)
            assert compare(a, b)
            assert compare(b, a)
            assert compare(b, c)
            assert events == [20, 20, 20]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["equal", "contains", "count", "index", "remove"])
@pytest.mark.parametrize("mutation", ["clear", "grow"])
def test_callbacks_resize_storage_and_collect_operands(optimize, operation, mutation, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    expression = {
        "equal": "left == right",
        "contains": "target in left",
        "count": "left.count(target)",
        "index": "left.index(target)",
        "remove": "left.remove(target)",
    }[operation]
    evaluate = f"outcome = str({expression})"
    if operation == "remove":
        evaluate = expression + '\n            outcome = "removed"'
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int, left: list["Box"], right: list["Box"]):
                self.value = value
                self.left = left
                self.right = right

            def __eq__(self, other: "Box") -> bool:
                if self.value == 1:
                    self.left.clear()
                    self.right.clear()
                    if {mutation == 'grow'}:
                        for index in range(20):
                            self.left.append(Box(2, self.left, self.right))
                            self.right.append(Box(2, self.left, self.right))
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            left: list[Box] = []
            right: list[Box] = []
            left.append(Box(1, left, right))
            right.append(Box(1, left, right))
            target = Box(1, left, right)
            {evaluate}
            gc_collect()
            return outcome + ":" + str(len(left)) + ":" + str(len(right))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_values_survive_releasing_parent_storage(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int, left: dict[str, tuple["Box", str]],
                         right: dict[str, tuple["Box", str]]):
                self.value = value
                self.left = left
                self.right = right

            def __eq__(self, other: "Box") -> bool:
                self.left.clear()
                self.right.clear()
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            left: dict[str, tuple[Box, str]] = {}
            right: dict[str, tuple[Box, str]] = {}
            left["a"] = (Box(1, left, right), "a" + str(10))
            right["a"] = (Box(1, left, right), "a" + str(10))
            # Retain only the containing values-view objects during search.
            target = (Box(1, left, right), "a" + str(10))
            assert target in left.values()
            assert len(left) == len(right) == 0
            return "passed"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_failures_restore_roots_and_iterators_remain_usable(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: "Box") -> bool:
                self.events.append(self.value)
                gc_collect()
                if self.value == 1:
                    raise ValueError("comparison failed")
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values = [Box(1, events), Box(2, events)]
            target = Box(2, events)
            cursor = iter(values)
            caught = 0
            try:
                target in cursor
            except ValueError as error:
                assert str(error) == "comparison failed"
                caught += 1
            assert target in cursor
            try:
                values.remove(target)
            except ValueError:
                caught += 1
            try:
                assert (values, "a") == ([target, target], "a")
            except ValueError:
                caught += 1
            try:
                assert {"a": values[0]} == {"a": target}
            except ValueError:
                caught += 1
            gc_collect()
            assert len(values) == 2 and caught == 4
            assert events == [1, 2, 1, 1, 1]
            values[0].value = 2
            assert values.count(target) == 2
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_float_bytes_and_recursive_collection_search(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            values = [1.5, -0.0, 2.5, 1.5]
            assert 0.0 in values and values.count(1.5) == 2
            assert values.index(1.5, 1) == 3
            values.remove(1.5)
            assert values == [-0.0, 2.5, 1.5]
            data = [b"a", b"b", b"a"]
            assert data.count(b"a") == 2
            data.remove(b"a")
            assert data.index(b"a") == 1
            assert [1, 2] in [[1, 2], [3, 4]]
            assert ((1, "a"), (2, "b")).index((2, "b")) == 1
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("result_type, value", [("int", "1"), ("str", '"equal"'), ("bool", "bool()")])
def test_non_boolean_object_equality_is_a_focused_boundary(result_type, value):
    with pytest.raises(LLVMUnsupported, match="compatible typed argument and bool result"):
        transpile_llvm(f'''
            class bool:
                pass

            class Box:
                def __eq__(self, other: "Box") -> {result_type}:
                    return {value}

            def main() -> int:
                return int([Box()] == [Box()])
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_scalar_equality_does_not_silently_return_false(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Box:
            def __eq__(self, other: int) -> bool:
                return other == 1

        def main() -> str:
            return str(((Box(), 1) == (1, 1), (2, 1) == (Box(), 1)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_equality_can_retain_a_temporary_after_the_comparing_function_returns(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int, saved: list["Box"]):
                self.value = value
                self.saved = saved

            def __eq__(self, other: "Box") -> bool:
                self.saved.append(other)
                return True

        def compare(saved: list[Box]) -> bool:
            return [Box(1, saved)] == [Box(7, saved)]

        def main() -> int:
            gc_set_threshold(1)
            saved: list[Box] = []
            assert compare(saved)
            gc_collect()
            assert len(saved) == 1
            return saved[0].value
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_application_comparison_and_identity_fallback(optimize):
    LLVM().assert_matches_python('''
        class Tree:
            def __init__(self, value: int, children: list["Tree"]):
                self.value = value
                self.children = children

            def __eq__(self, other: "Tree") -> bool:
                return self.value == other.value and self.children == other.children

        class Marker:
            pass

        def main() -> str:
            first = Tree(1, [Tree(2, []), Tree(3, [])])
            second = Tree(1, [Tree(2, []), Tree(3, [])])
            assert [first] == [second]
            second.children[1].value = 4
            assert [first] != [second]
            marker = Marker()
            assert [marker] == [marker]
            assert [marker] != [Marker()]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_reflection_from_an_identity_only_base(optimize):
    LLVM().assert_matches_python('''
        class Base:
            pass

        class Child(Base):
            def __eq__(self, other: Base) -> bool:
                return True

        def compare(a: Base, b: Base) -> bool:
            return [a] == [b]

        def main() -> str:
            assert compare(Base(), Child())
            assert compare(Child(), Base())
            assert not compare(Base(), Base())
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_chains_preserve_portable_values_and_callback_exceptions(optimize):
    LLVM().assert_matches_python('''
        from pyjs import int8, float32
        from pyjs.native import gc_collect

        class Box:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: "Box") -> bool:
                self.events.append(self.value)
                gc_collect()
                if self.value == 2:
                    raise ValueError("comparison")
                return True

        def main() -> str:
            assert int8(-3) < int8(1) < int8(4)
            assert float32(1.25) < float32(2.5) <= float32(2.5)
            events: list[int] = []
            a = Box(1, events)
            try:
                a == Box(2, events) == Box(3, events)
                return "missing exception"
            except ValueError:
                pass
            assert events == [1, 2]
            assert not (a == a != a)
            assert events == [1, 2, 1, 1]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_equality_can_clear_its_source(optimize):
    # Equality is an internal scan, not a size-checked Python iterator. The
    # current comparison retains its values even if a callback clears storage.
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Box:
            def __init__(self, values: dict[int, "Box"]):
                self.values = values

            def __eq__(self, other: "Box") -> bool:
                self.values.clear()
                gc_collect()
                return True

        def main() -> int:
            values: dict[int, Box] = {}
            values[0] = Box(values)
            matches = values == {0: Box(values)}
            return 0 if matches and len(values) == 0 else 1
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_inequality_keeps_callback_selection_under_gc(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from builtins import object as Anything
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __eq__(self, other: Anything) -> bool:
                gc_collect()
                raise ValueError("wrong equality")

            def __ne__(self, other: Anything) -> bool:
                gc_collect()
                return False

        class Child(Base):
            def __ne__(self, other: Anything) -> bool:
                gc_collect()
                return True

        class Other:
            pass

        def different(left: Base | Other, right: Base | Other) -> bool:
            return left != right

        def main() -> str:
            gc_set_threshold(1)
            item = Base()
            assert not different(item, item)
            assert not different(item, Base())
            assert not different(item, Other())
            assert not different(Other(), item)
            assert different(item, Child())
            assert different(Child(), item)
            assert different(Child(), Child())
            other = Other()
            assert not different(other, other)
            assert different(other, Other())
            return "passed"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", ["left != right", "right != left"])
def test_union_inequality_does_not_skip_custom_callbacks_on_builtin_arms(tmp_path, expression):
    result = LLVM().assert_matches_python(f'''
        class Box:
            def __ne__(self, other: object) -> bool:
                return False

        def different(left: Box | int, right: Box) -> bool:
            return {expression}

        def main() -> str:
            return str(different(1, Box()))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("operation,method", [("==", "__eq__"), ("!=", "__ne__"), ("!=", "__eq__")])
@pytest.mark.parametrize("reverse", [False, True])
def test_union_builtin_arms_do_not_skip_runtime_subclass_callbacks(tmp_path, operation, method, reverse):
    left, right = ("right", "left") if reverse else ("left", "right")
    result = LLVM().assert_matches_python(f'''
        class Base:
            pass
        class Child(Base):
            def {method}(self, other: object) -> bool:
                return False
        class Grandchild(Child):
            pass
        def compare(left: Base | int, right: Base) -> bool:
            return {left} {operation} {right}
        def main() -> str:
            return str(compare(1, Grandchild()))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inherited_inequality_reaches_equality_and_inequality_overrides(optimize):
    LLVM().assert_matches_python('''
        class Base:
            pass

        class Equal(Base):
            def __eq__(self, other: Base) -> bool:
                return True

        class Unequal(Base):
            def __ne__(self, other: Base) -> bool:
                return True

        def different(a: Base, b: Base) -> bool:
            return a != b

        def main() -> str:
            a = Base()
            assert not different(a, a)
            assert different(a, Base())
            assert not different(a, Equal())
            assert not different(Equal(), a)
            assert different(a, Unequal())
            assert different(Unequal(), a)
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_inherited_equality_still_prioritizes_the_right_subtype(optimize):
    LLVM().assert_matches_python('''
        class Base:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: "Base") -> bool:
                self.events.append(self.value)
                return True

        class Child(Base):
            pass

        def compare(a: Base, b: Base) -> bool:
            return [a] == [b] and a == b == a

        def main() -> str:
            events: list[int] = []
            assert compare(Base(1, events), Child(2, events))
            assert events == [2, 2, 2]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_reflected_comparison_preserves_source_operand_evaluation_order(optimize):
    LLVM().assert_matches_python('''
        class Base:
            def __init__(self, events: list[int]):
                self.events = events

            def __eq__(self, other: "Base") -> bool:
                self.events.append(3)
                return True

        class Child(Base):
            def __eq__(self, other: Base) -> bool:
                self.events.append(4)
                return True

        def first(events: list[int]) -> Base:
            events.append(1)
            return Base(events)

        def second(events: list[int]) -> Child:
            events.append(2)
            return Child(events)

        def main() -> str:
            events: list[int] = []
            assert first(events) == second(events)
            assert events == [1, 2, 4]
            return "passed"
    ''', optimize=optimize)


def test_explicit_default_inequality_has_a_focused_boundary():
    with pytest.raises(LLVMUnsupported, match="explicit object.__ne__ may return NotImplemented"):
        transpile_llvm('''
            class Box:
                pass

            def main() -> bool:
                return Box().__ne__(Box())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operator", ["==", "!="])
@pytest.mark.parametrize("tail", ["", " is not left"])
def test_static_reflection_defers_to_runtime_operand_types(optimize, operator, tail):
    LLVM().assert_matches_python(f'''
        class Base:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: "Base") -> bool:
                self.events.append(self.value)
                return self.value == 1

            def __ne__(self, other: "Base") -> bool:
                self.events.append(self.value)
                return self.value == 1

        class Child(Base):
            def __eq__(self, other: Base) -> bool:
                self.events.append(self.value * 10)
                return self.value == 1

            def __ne__(self, other: Base) -> bool:
                self.events.append(self.value * 10)
                return self.value == 1

        class Grandchild(Child):
            pass

        def first(value: Base) -> Base:
            value.events.append(100)
            return value

        def second(value: Child) -> Child:
            value.events.append(200)
            return value

        def compare(left: Base, right: Child) -> bool:
            return first(left) {operator} second(right){tail}

        def main() -> str:
            events: list[int] = []
            assert compare(Child(1, events), Child(2, events))
            assert events == [100, 200, 10]
            events.clear()
            assert not compare(Base(1, events), Child(2, events))
            assert events == [100, 200, 20]
            events.clear()
            assert not compare(Child(1, events), Grandchild(2, events))
            assert events == [100, 200, 20]
            events.clear()
            assert compare(Grandchild(1, events), Child(2, events))
            assert events == [100, 200, 10]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method, comparison", [
    ("__eq__", "left == right"), ("__eq__", "left != right"),
    ("__eq__", "left == right is not left"), ("__eq__", "left != right is not left"),
    ("__ne__", "left != right"), ("__ne__", "left != right is not left"),
])
def test_reflected_comparison_retains_temporary_operand(optimize, method, comparison):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, value: int):
                self.value = value

            def __eq__(self, other: "Base") -> bool:
                return False

        class Child(Base):
            def __init__(self, saved: list[Base]):
                super().__init__(1)
                self.saved = saved

            def {method}(self, other: Base) -> bool:
                self.saved.append(other)
                gc_collect()
                return True

        def retain(right: Base) -> bool:
            left = Base(7)
            return {comparison}

        def main() -> int:
            gc_set_threshold(1)
            saved: list[Base] = []
            retain(Child(saved))
            gc_collect()
            assert len(saved) == 1
            return saved[0].value
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("retaining", [False, True])
@pytest.mark.parametrize("operation", [
    "probe in items", "probe not in items", "items.__contains__(probe)",
    "items.count(probe)", "items.index(probe)", "items.remove(probe)",
    "[probe] == items", "[probe] != items", "items.__eq__([probe])",
    "probe in mapping.values()", "('k', probe) in mapping.items()",
    "{'k': probe} == mapping", "probe in tuple(items)",
    "[items[0]].count(probe)", "[[probe]] == [items]", "probe in iter(items)",
])
def test_collection_callback_lifetimes_and_retention(optimize, retaining, operation):
    source = f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, value: int):
                self.value = value

        class Child(Base):
            def __init__(self, saved: list[Base]):
                super().__init__(1)
                self.saved = saved

            def __eq__(self, other: Base) -> bool:
                {"self.saved.append(other)" if retaining else "pass"}
                gc_collect()
                return True

        def retain(items: list[Base], mapping: dict[str, Base]) -> None:
            probe = Base(7)
            {operation}

        def main() -> int:
            gc_set_threshold(1)
            saved: list[Base] = []
            items: list[Base] = [Child(saved)]
            mapping: dict[str, Base] = {{"k": Child(saved)}}
            retain(items, mapping)
            gc_collect()
            assert len(saved) == {int(retaining)}
            return saved[0].value if saved else 0
    '''
    # Base inherits object.__eq__, but element dispatch must include Child.
    # A request arena can mask a wrong LOCAL classification at runtime. Check
    # the shared IR contract as well as the retained value after collection.
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        module = analysis.entry_point.container
        lifetime = module.search("retain").ir.lifetime
        probe = lifetime.allocations[0]
        assert probe.operation.value_type.name == "Base"
        assert probe.boundary is (LifetimeBoundary.EXTERNAL if retaining else LifetimeBoundary.LOCAL)
        assert module.search("Child").find("__eq__") in dict(lifetime.call_dependencies)
    LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
