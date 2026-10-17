import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import ERASED_EQUALITY_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_iterator_callback_results_are_not_iterator_descriptors(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def box(value: int) -> object:
            gc_collect()
            return [value]

        def forward() -> Iterator[object]:
            for value in map(box, [3, 4]):
                yield value

        def main() -> str:
            gc_set_threshold(1)
            item = [7]
            objects: list[object] = [None, 0, "", item]
            mapped = list(map(box, [1, 2]))
            selected = list(filter(None, objects))
            gc_collect()
            return str((mapped, selected, list(forward()), selected[0] is item))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("value", ["function", "iter([1])", "iterable()"])
@pytest.mark.parametrize("expression, items", [
    ("value == other", "[]"), ("(value,) == other", "[]"),
    ("value in objects", "[]"), ("value in objects", "[1, 'x']"),
])
def test_erased_comparisons_reject_descriptor_boxing(value, expression, items):
    with pytest.raises(LLVMUnsupported, match="callable erasure|iterator handles|Iterable views") as caught:
        transpile_llvm(f'''
            from collections.abc import Iterable
            def function() -> int:
                return 1
            def iterable() -> Iterable[int]:
                return [1]
            def main() -> str:
                value = {value}
                other: object = 1
                objects: list[object] = {items}
                return str({expression})
        ''')
    assert caught.value.node.lineno is not None


@pytest.mark.parametrize("value", ["function", "iter([1])", "iterable()"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_descriptor_identity_does_not_require_erased_boxing(value, optimize, tmp_path):
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterable
        def function() -> int:
            return 1
        def iterable() -> Iterable[int]:
            return [1]
        def main() -> str:
            value = {value}
            other: object = 1
            return str((value is other, value is value))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_shared_erased_equality_contract(tmp_path):
    result = LLVM().assert_matches_python(ERASED_EQUALITY_CONTRACT.source, directory=tmp_path)
    assert result.native.returncode == 0, ERASED_EQUALITY_CONTRACT.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("empty_first", [False, True])
def test_empty_tuple_dispatch_is_not_a_layout_wildcard(tmp_path, optimize, empty_first):
    values = "(), (1,), (1, 'a'), (True,)" if empty_first else "(1,), (1, 'a'), (True,), ()"
    result = LLVM().assert_matches_python(f'''
        def main() -> str:
            values: list[object] = [{values}]
            results: list[bool] = []
            for left in values:
                for right in values:
                    results.append(left == right)
                    results.append(left != right)
            return repr(values) + str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_unrelated_boxed_layouts_do_not_poison_valid_comparisons(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8

        def equal(left: object, right: object) -> bool:
            return left == right

        def main() -> str:
            unrelated: list[object] = [{1: 2}, {"one": 2}, {1}, {"one"}, [int8(1)]]
            results = [equal(None, None), equal(1, 1), equal([1], [1])]
            for item in unrelated:
                results.append(equal(item, None))
                results.append(equal(None, item))
                results.append(None in [item])
            return repr(unrelated) + str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("left,right,message", [
    ("{1: 2}", "{'one': 2}", "matching key types"),
    ("{1}", "{'one'}", "matching item types"),
])
def test_unsupported_erased_pair_is_a_checked_runtime_boundary(tmp_path, optimize, left, right, message):
    # Native layout adapters are intentionally narrower than CPython. An
    # unsupported selected pair raises; unrelated equality and recovery work.
    result = LLVM().run_source(f'''
        from pyjs.native import gc_collect

        def equal(left: object, right: object, different: bool) -> bool:
            if different:
                return left != right
            return left == right

        def main() -> int:
            for mode in range(3):
                try:
                    equal({left}, {right}, mode == 1)
                except TypeError as error:
                    assert {message!r} in str(error)
                else:
                    return 1
                gc_collect()
                assert equal(1, 1, False)
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stderr == ""


def test_erased_callback_result_requires_builtin_bool(tmp_path):
    result = LLVM().run_source('''
        class bool:
            pass

        class Box:
            def __eq__(self, other: object) -> bool:
                return bool()

        def equal(left: object, right: object):
            return left == right

        def main() -> int:
            try:
                equal(Box(), Box())
            except TypeError as error:
                assert "builtin bool result" in str(error)
                return 0
            return 1
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method,value", [("__eq__", "None"), ("__ne__", "None"), ("__eq__", "42")])
def test_disabled_comparison_methods_preserve_selection_and_member_identity(tmp_path, optimize, method, value):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect

        class Disabled:
            {method} = {value}

        class Inherited(Disabled):
            pass

        class Reflected(Disabled):
            def __eq__(self, other: object) -> bool:
                gc_collect()
                return True
            def __ne__(self, other: object) -> bool:
                return False

        class Callable:
            def __eq__(self, other: object) -> bool:
                return True
            def __ne__(self, other: object) -> bool:
                return False

        class Shadowed(Callable):
            {method} = {value}

        def compare(left: object, right: object, mode: int) -> str:
            try:
                if mode == 0:
                    return str(left == right)
                if mode == 1:
                    return str(left != right)
                if mode == 2:
                    return str([left] == [right])
                return str(left in [right])
            except TypeError as error:
                return str(error)

        def typed(left: Callable, right: Callable, mode: int) -> str:
            try:
                if mode == 0:
                    return str([left] == [right])
                if mode == 1:
                    return str(left == right)
                return str(left != right)
            except TypeError as error:
                return str(error)

        def main() -> str:
            first = Disabled()
            values: list[object] = [first, Disabled(), Inherited(), Reflected(),
                                    Callable(), Shadowed(), 1, None]
            results: list[str] = []
            for left in values:
                for right in values:
                    for mode in range(4):
                        results.append(compare(left, right, mode))
            shadowed = Shadowed()
            for mode in range(3):
                results.append(typed(shadowed, shadowed, mode))
                results.append(typed(Callable(), shadowed, mode))
                results.append(typed(shadowed, Callable(), mode))
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_records_and_temporary_closed_union_operands(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass
        from pyjs.native import gc_collect, gc_set_threshold

        @dataclass
        class Record:
            value: int

        def temporary(flag: bool) -> list[int] | str:
            gc_collect()
            if flag:
                return [1, 2]
            return "one" + str(2)

        def equal(left: object, right: object) -> bool:
            return left == right

        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [Record(1), Record(2), None, [1, 2], "one2"]
            results = [None == values[2], values[2] != None,
                       equal(values[0], Record(1)), equal(values[0], values[0]),
                       equal(values[0], values[1]), equal(values[0], values[2])]
            for flag in [True, False]:
                for value in values:
                    results.append(value == temporary(flag))
                    results.append(temporary(flag) != value)
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_ranges_and_sequence_layouts(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def equal(left: object, right: object) -> bool:
            return left == right

        def main() -> str:
            values: list[object] = [[1, 2],
                range(0), range(10, 10), range(0, 4, 2), range(0, 3, 2),
                range(-9223372036854775808, 9223372036854775807)]
            results: list[bool] = []
            for left in values:
                for right in values:
                    results.append(equal(left, right))
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("value", ["[int8(1)]", "[[float32(1.0)]]"])
def test_erased_comparison_does_not_discard_numeric_representations(tmp_path, value):
    result = LLVM().run_source(f'''
            from pyjs import int8, float32

            def equal(left: object, right: object) -> bool:
                return left == right

            def main() -> int:
                try:
                    equal({value}, {value})
                except TypeError as error:
                    assert "ordinary item representations" in str(error)
                    return 0 if equal(1, 1) else 2
                return 1
        ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stderr == ""


@pytest.mark.parametrize("value", ["int8(1)", "[float32(1.0)]"])
def test_direct_erased_comparison_checks_numeric_representations(value):
    with pytest.raises(CompilationError, match="erased equality requires ordinary numeric representations"):
        transpile_llvm(f'''
            from pyjs import int8, float32

            def compare(value: object) -> bool:
                return {value} == value

            def main() -> bool:
                return compare(1)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_callback_recursion_and_nested_formatting_recover(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Equal:
            def __init__(self):
                self.recurse = False
                self.saved = ""

            def __eq__(self, other: object) -> bool:
                if self.recurse:
                    return self == other
                gc_collect()
                self.saved = repr(other)
                return True

        def equal(left: object, right: object) -> bool:
            return left == right

        def main() -> str:
            gc_set_threshold(1)
            value = Equal()
            results = [equal([[value]], [[(42, "nested")]])]
            value.recurse = True
            try:
                equal(value, 1)
            except RecursionError:
                results.append(True)
            value.recurse = False
            gc_collect()
            results.append(equal(value, "after"))
            return str((results, value.saved))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_boxed_cycles_raise_and_allow_recovery(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def equal(left: object, right: object) -> bool:
            return left == right

        def main() -> str:
            gc_set_threshold(1)
            left: list[object] = []
            right: list[object] = []
            left.append(left)
            right.append(right)
            results = [equal(left, left)]
            try:
                results.append(equal(left, right))
            except RecursionError:
                results.append(True)
            gc_collect()
            right.clear()
            results.append(equal(left, right))
            left.clear()
            results.append(equal(left, right))
            first: dict[str, object] = {}
            second: dict[str, object] = {}
            first["self"] = first
            second["self"] = second
            try:
                equal(first, second)
            except RecursionError:
                results.append(True)
            gc_collect()
            second.clear()
            results.append(equal(first, second))
            first.clear()
            results.append(equal(first, second))
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""

@pytest.mark.parametrize("value", ["Custom()", "[Custom()]", "{'one': Custom()}"])
def test_erased_callbacks_with_narrow_annotations_are_rejected(tmp_path, value):
    result = LLVM().run_source(f'''
            class Custom:
                def __eq__(self, other: int) -> bool:
                    return False

            def equal(left: object, right: object) -> bool:
                return left == right

            def main() -> int:
                try:
                    equal({value}, {value})
                except TypeError as error:
                    assert "callbacks require an object parameter" in str(error)
                    return 0 if equal(1, 1) else 2
                return 1
        ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stderr == ""

@pytest.mark.parametrize("optimize", [0, 2])
def test_boxed_container_equality_uses_concrete_layouts(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def equal(left: object, right: object) -> bool:
            return left == right

        def main() -> str:
            integers = [1, 2]
            erased: list[object] = [1, 2]
            mapping: dict[str, object] = {"one": 1}
            values: list[object] = [integers, [1.0, 2.0], erased, [3],
                    (1, "two"), (1.0, "two"), {1, 2}, frozenset([1, 2]),
                {"one": 1}, mapping, [[1], [2]], [[1], [3]], None, 1, "text"]
            gc_collect()
            results: list[bool] = []
            for left in values:
                for right in values:
                    results.append(equal(left, right))
            nested: list[object] = [(1, 2)]
            results.append(equal(nested, [(1, 2)]))
            integers.append(3)
            results.append(equal(values[0], erased))
            cycle: list[object] = []
            other: list[object] = []
            cycle.append(cycle)
            other.append(other)
            try:
                equal(cycle, other)
            except RecursionError:
                results.append(True)
            gc_collect()
            cycle.clear()
            other.clear()
            results.append(equal(cycle, other))
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""

@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_boxing_inside_container_comparison_unwinds_and_retries(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def main() -> int:
            items: list[object] = [42]
            first: object = [42]
            second: object = items
            result = False
            caught = False
            arm(1)
            try:
                result = first == second
            except MemoryError:
                caught = True
            arm(0)
            {'gc_collect()' if managed else 'pass'}
            if not caught or result or len(items) != 1:
                return 1
            return 0 if first == second else 2
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)

@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_groupby_keys_without_explicit_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import groupby
        from pyjs.native import gc_collect, gc_set_threshold

        def key(value: int) -> object:
            gc_collect()
            return [value // 2]

        def main() -> str:
            gc_set_threshold(1)
            output: list[int] = []
            for value, group in groupby([0, 1, 2, 3, 4], key):
                output.append(len(list(group)))
            values: list[object] = [[1], [1], [2]]
            for object_value, object_group in groupby(values):
                output.append(len(list(object_group)))
            return str(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""

@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_callable_sentinel_without_explicit_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Source:
            def __init__(self):
                self.position = 0

            def poll(self) -> object:
                gc_collect()
                self.position += 1
                return [self.position]

        def main() -> str:
            gc_set_threshold(1)
            source = Source()
            sentinel: object = [3]
            values = list(iter(source.poll, sentinel))
            return str(values)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""

@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_nested_comparisons_retain_callback_operands(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        class Payload:
            def __init__(self, value: int):
                self.value = value

        class Owner:
            def __init__(self):
                self.saved: object = None

            def __eq__(self, other: object) -> bool:
                self.saved = other
                gc_collect()
                return True

        def compare(left: object, right: object) -> bool:
            return left == right

        def retain(owner: Owner, reflected: bool) -> None:
            value = Payload(42)
            if reflected:
                compare([[value]], [[owner]])
            else:
                compare([[owner]], [[value]])

        def main() -> str:
            gc_set_threshold(1)
            owner = Owner()
            results: list[int] = []
            for reflected in [False, True]:
                retain(owner, reflected)
                gc_collect()
                extra = Payload(-1)
                results.append(cast(Payload, owner.saved).value)
                results.append(extra.value)
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""

@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_erased_comparison_box_failures_preserve_results_and_collections(
    tmp_path, optimize, managed,
):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def main() -> int:
            values: list[object] = [42, "text"]
            for mode in range(3):
                result = False
                caught = False
                arm(1)
                try:
                    if mode == 0:
                        result = 42 == values[0]
                    elif mode == 1:
                        result = "text" == values[1]
                    else:
                        values.remove(42)
                except MemoryError:
                    caught = True
                arm(0)
                {'gc_collect()' if managed else 'pass'}
                if not caught or result or len(values) != 2:
                    return 1
            if not (42 == values[0] and "text" == values[1]):
                return 2
            values.remove(42)
            return 0 if len(values) == 1 else 3
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)

def test_declared_erased_callbacks_do_not_silently_use_identity(tmp_path):
    result = LLVM().run_source('''
            from pyjs import llvm

            class Box:
                @llvm.inline("icmp ne ptr {self}, {other}")
                def __eq__(self, other: object) -> bool:
                    return self is not other

            def equal(left: object, right: object) -> bool:
                return left == right

            def main() -> int:
                value = Box()
                try:
                    equal(value, value)
                except TypeError as error:
                    assert "requires a lowered body" in str(error)
                    return 0 if equal(1, 1) else 2
                return 1
        ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stderr == ""

@pytest.mark.parametrize("method", ["__eq__", "__ne__"])
def test_explicit_erased_dunders_do_not_silently_replace_not_implemented(method):
    with pytest.raises(LLVMUnsupported, match="dunder calls require NotImplemented"):
        transpile_llvm(f'''
            def equal(left: object, right: object) -> bool:
                return left.{method}(right)

            def main() -> bool:
                return equal(1, "one")
        ''')

@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_search_callbacks_mutate_collect_fail_and_retry(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Mutator:
            def __init__(self, items: list[object], action: str):
                self.items = items
                self.action = action
                self.calls = 0

            def __eq__(self, other: object) -> bool:
                self.calls += 1
                if self.action == "grow":
                    self.items.append(42)
                else:
                    self.items.clear()
                gc_collect()
                if self.action == "error":
                    raise ValueError("comparison")
                return self.action == "hit"

        def main() -> str:
            gc_set_threshold(1)
            results: list[int] = []
            for action in ["clear", "grow", "hit", "error"]:
                for mode in range(7):
                    items: list[object] = []
                    mutator = Mutator(items, action)
                    items.append(mutator)
                    try:
                        if mode == 0:
                            results.append(items.count(42))
                        elif mode == 1:
                            results.append(items.index(42))
                        elif mode == 2:
                            results.append(int(42 in items))
                        elif mode == 3:
                            items.remove(42)
                            results.append(10)
                        elif mode == 4:
                            results.append(items.index(42, 0, 1))
                        elif mode == 5:
                            results.append(items.index(42, -99, 100))
                        else:
                            results.append(items.index(42, 0, -1))
                    except ValueError:
                        results.append(-1)
                    gc_collect()
                    results.append(len(items))
                    results.append(mutator.calls)
                    items.clear()
                    items.append(42)
                    results.append(items.count(42))
            temporary: list[object] = []
            temporary.append(Mutator(temporary, "hit"))
            results.append(temporary.count(42))
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""

@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_iterator_callbacks_and_inherited_inequality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import groupby
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value

            def __eq__(self, other: object) -> bool:
                gc_collect()
                if isinstance(other, Key):
                    return self.value == other.value
                return False

        class Source:
            def __init__(self):
                self.position = 0

            def poll(self) -> object:
                self.position += 1
                return Key(self.position)

        def key(value: int) -> object:
            return Key(value // 2)

        def different(left: object, right: object) -> bool:
            return left != right

        def main() -> str:
            gc_set_threshold(1)
            results: list[int] = []
            for value, group in groupby([0, 1, 2, 3, 4], key):
                results.append(len(list(group)))
            source = Source()
            sentinel: object = Key(3)
            results.append(len(list(iter(source.poll, sentinel))))
            results.append(int(different(Key(1), Key(1))))
            results.append(int(different(Key(1), Key(2))))
            results.append(int(different(Key(1), 1)))
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""



@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_primitive_equality_matches_python(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def equal(left: object, right: object) -> bool:
            gc_collect()
            return left == right

        def different(left: object, right: object) -> bool:
            return left != right

        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [None, False, True, 0, 1, -1, 1.0, 2.5,
                9007199254740993, 9007199254740992.0, float("nan"),
                float("inf"), "café", "ca" + "fé", b"bytes", b"by" + b"tes"]
            output: list[bool] = []
            for left in values:
                for right in values:
                    output.append(equal(left, right))
                    output.append(different(left, right))
            return str(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_sequence_members_keep_boxed_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Marker:
            pass

        def equal(left: object, right: object) -> bool:
            return left == right

        def main() -> str:
            marker = Marker()
            values: list[object] = [float("nan"), 42, "text", marker]
            copied = values.copy()
            gc_collect()
            output = [values == copied, values[0] in copied,
                      equal(values[0], copied[0]), equal(values[3], copied[3]),
                      equal(Marker(), Marker()), 42 == values[1],
                      values[1] == 42, "text" == values[2],
                      values[2] != "other", values.count(values[0]) == 1,
                      values.index("text") == 2, values.count(42) == 1]
            copied.remove(42)
            output.append(42 not in copied)
            return str(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_custom_callbacks_preserve_priority_and_boxed_arguments(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, events: list[str]):
                self.events = events
            def __eq__(self, other: object) -> bool:
                gc_collect()
                self.events.append("base.eq")
                return isinstance(other, Box)
            def __ne__(self, other: object) -> bool:
                gc_collect()
                self.events.append("base.ne")
                return False

        class Child(Box):
            def __eq__(self, other: object) -> bool:
                gc_collect()
                self.events.append("child.eq")
                return False
            def __ne__(self, other: object) -> bool:
                gc_collect()
                self.events.append("child.ne")
                return True

        class Marker:
            pass

        def compare(left: object, right: object) -> list[bool]:
            return [left == right, left != right]

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            base = Box(events)
            values: list[object] = [base, Child(events), Marker(), 42, "text", None]
            results: list[bool] = []
            for left in values:
                for right in values:
                    results.extend(compare(left, right))
            return str((results, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""
