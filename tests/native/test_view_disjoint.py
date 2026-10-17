import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_view_membership_preserves_cross_numeric_key_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def main() -> str:
            integers = {1: 2, 0: 3, 9007199254740993: 4}
            floats = {1.0: 2, -0.0: 3, 9007199254740992.0: 4}
            flags = {True: 2, False: 3}
            queries: list[float | str | None] = [None, 1.0, 1.5, "1"]
            return str((
                [key in integers.keys() for key in [1.0, 1.5, -0.0, 9007199254740992.0,
                                                    float("nan"), float("inf")]],
                [(key, 2) in integers.items() for key in [1.0, 1.5]],
                [key in floats.keys() for key in [1, 2, 0, 9007199254740993]],
                [(key, 2) in floats.items() for key in [1, 2]],
                True in integers.keys(), (False, 3) in integers.items(),
                1 in flags.keys(), (0.0, 3) in flags.items(),
                None in integers.keys(), (None, 3) in integers.items(),
                "1" in integers.keys(), (b"1", 2) in integers.items(),
                [key in integers.keys() for key in queries],
                [(key, 2) in integers.items() for key in queries]
            ))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_annotated_portable_item_views_match_constructed_views(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import ItemsView
        from pyjs import int8, int64
        from pyjs.native import gc_collect

        def inspect(view: ItemsView[int8, int64]) -> str:
            rows: list[tuple[int8, int64]] = [(int8(127), int64(127))]
            found = not view.isdisjoint(rows)
            captured = list(view)
            cursor = iter(view)
            key, value = next(cursor)
            explicit = list(view.__iter__())
            gc_collect()
            return str((found, (int8(127), int64(127)) in view,
                        key + 1, value + 1, captured[0][0] + 1, captured[0][1] + 1,
                        explicit[0][0] + 1, explicit[0][1] + 1))

        def main() -> str:
            values = {int8(127): int64(127)}
            key = next(values.keys().__iter__())
            value = next(values.values().__iter__())
            return str((inspect(values.items()), key + 1, value + 1))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_view_callbacks_retain_members_across_requests_and_failure(tmp_path, optimize):
    source = '''
from collections.abc import KeysView
from pyjs.native import gc_collect
class Key:
    def __init__(self, value: int):
        self.value = value
    def __hash__(self) -> int:
        SAVED.append(self)
        gc_collect()
        return self.value
    def __eq__(self, other: Key) -> bool:
        return self.value == other.value
SAVED: list[Key] = []
def check(view: KeysView[Key], queries: list[Key]) -> bool:
    return view.isdisjoint(queries)
def render(number: int, fail: bool) -> str:
    values = {Key(number): number}
    assert check(values.keys(), [Key(number + 100)])
    gc_collect()
    if fail:
        raise ValueError("retained before failure")
    return str([key.value for key in SAVED])
'''
    _assert_retained_view_calls(source, tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("other", ["KeysView", "set", "frozenset"])
@pytest.mark.parametrize("value_type", ["Value", "Child"])
def test_item_view_values_escape_when_hashed_by_a_key_container(tmp_path, optimize, other, value_type):
    source = '''
from collections.abc import ItemsView, KeysView
from pyjs.native import gc_collect
class Value:
    def __init__(self, number: int):
        self.number = number
    def __hash__(self) -> int:
        SAVED.append(self)
        gc_collect()
        return self.number
    def __eq__(self, other: Value) -> bool:
        return self.number == other.number
class Child(Value):
    def __hash__(self) -> int:
        return self.number
SAVED: list[Value] = []
def check(left: ItemsView[int, Value], right: OTHER[tuple[int, VALUE_TYPE]]) -> bool:
    return left.isdisjoint(right)
def render(number: int, fail: bool) -> str:
    left = {number: Value(number)}
    right = {(number + 1, VALUE_TYPE(number + 101)): 0,
             (number + 2, VALUE_TYPE(number + 102)): 0}
    assert check(left.items(), PEER)
    gc_collect()
    if fail:
        raise ValueError("retained before failure")
    return str([value.number for value in SAVED])
'''
    source = source.replace("OTHER", other).replace("VALUE_TYPE", value_type).replace(
        "PEER", "right.keys()" if other == "KeysView" else f"{other}(right)")
    # With Child peers, no construction otherwise reaches Value.__hash__.
    # This checks callback discovery as well as persistence across requests.
    _assert_retained_view_calls(source, tmp_path, optimize)


def _assert_retained_view_calls(source, tmp_path, optimize):
    namespace = {}
    exec(source, namespace)
    expected = []
    for number, fail in [(1, False), (2, True), (3, False), (4, False)]:
        if fail:
            with pytest.raises(ValueError, match="retained before failure"):
                namespace["render"](number, fail)
        else:
            expected.append(namespace["render"](number, fail))
    # ctypes libraries are unsanitized; standalone tests cover sanitizer paths.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number, fail in [(1, False), (2, True), (3, False), (4, False)]:
            if fail:
                with pytest.raises(LLVMRuntimeError, match="retained before failure"):
                    library.render(number, fail)
            else:
                actual.append(library.render(number, fail))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_item_view_membership_checks_variadic_pair_length_before_reading(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def check(values: list[tuple[int, ...]]) -> str:
            mapping = {1: 2, 3: 4}
            found = [pair in mapping.items() for pair in values]
            gc_collect()
            return str(found)

        def main() -> str:
            gc_set_threshold(1)
            return "|".join([check([(), (1,), (1, 2, 3), (1, 2), (3, 4)]),
                             check([(), (1,), (1, 3), (1, 2, 3)])])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_view_disjoint_short_circuits_without_consuming_the_remaining_input(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            data = {1: "one", 2: "two"}
            keys = data.keys()
            items = data.items()
            candidates = iter([3, 1, 4])
            pairs = iter([(3, "three"), (2, "two"), (4, "four")])
            result = [str(keys.isdisjoint(candidates)), str(next(candidates)),
                      str(items.isdisjoint(pairs)), str(next(pairs))]
            gc_collect()
            result.extend([str(keys.isdisjoint([3, 4])), str(items.isdisjoint([])),
                           str(keys.isdisjoint(keys)), str(items.isdisjoint(items)),
                           str(keys.isdisjoint({3, 4, 5})),
                           str(items.isdisjoint({(3, "three")})),
                           str(keys.isdisjoint({1: 9}.keys())),
                           str(items.isdisjoint({1: "other"}.items()))])
            data.clear()
            remaining = iter([1, 2])
            result.extend([str(keys.isdisjoint(keys)), str(keys.isdisjoint(remaining)),
                           str(next(remaining, -1))])
            return "|".join(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_view_disjoint_preserves_hash_order_and_the_identity_shortcut(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __hash__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                return self.value

            def __eq__(self, other: Key) -> bool:
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = {Key(1, events): 10}
            second = {Key(2, events): 20, Key(3, events): 30}
            view = first.keys()
            events.clear()
            result = [str(view.isdisjoint(view)), str(events)]
            result.extend([str(view.isdisjoint(second.keys())), str(events)])
            events.clear()
            result.extend([str(second.keys().isdisjoint(view)), str(events)])
            events.clear()
            result.extend([str(view.isdisjoint(first.keys())), str(events)])
            return "|".join(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_item_view_disjoint_handles_unhashable_values_and_collecting_failures(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Value:
            def __init__(self, owner: dict[int, Value], fail: bool):
                self.owner = owner
                self.fail = fail

            def __eq__(self, other: Value) -> bool:
                self.owner.clear()
                gc_collect()
                if self.fail:
                    raise ValueError("comparison failed")
                return True

        def main() -> str:
            gc_set_threshold(1)
            lists = {1: [2, 3]}
            output = [str(lists.items().isdisjoint([(1, [2, 3])])),
                      str(lists.items().isdisjoint([(1, [4])]))]
            owner: dict[int, Value] = {}
            owner[1] = Value(owner, True)
            query = Value(owner, False)
            remaining = iter([(1, query), (2, query)])
            try:
                owner.items().isdisjoint(remaining)
            except ValueError as error:
                output.append(str(error))
            else:
                raise AssertionError("missing failure")
            gc_collect()
            output.append(str(next(remaining)[0]))
            owner[1] = Value(owner, False)
            output.append(str(owner.items().isdisjoint([(1, query)])))
            output.append(str(len(owner)))
            gc_collect()
            return "|".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_disjoint_views_keep_fixed_width_items_and_lazy_input_order(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64
        from pyjs.native import gc_collect

        def main() -> str:
            data = {int8(-1): int64(9007199254740993)}
            source = ((int8(value), int64(9007199254740993)) for value in [2, -1, 3])
            result = data.items().isdisjoint(source)
            gc_collect()
            return str((result, next(source), data.keys().isdisjoint([int8(-1)])))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_disjoint_allocation_failures_preserve_result_and_allow_retry(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def check(data: dict[int, str], other: dict[int, str], mode: int) -> bool:
            if mode == 0:
                return data.keys().isdisjoint(other.keys())
            if mode == 1:
                return data.items().isdisjoint(other.items())
            return data.items().isdisjoint((pair for pair in other.items()))

        def main() -> int:
            data = {1: "one", 2: "two"}
            other = {2: "two"}
            mode = 0
            while mode < 3:
                arm(1000)
                probe = check(data, other, mode)
                stages = 1000 - remaining()
                arm(0)
                if probe or stages < 1:
                    return 1
                failure = 1
                while failure <= stages:
                    result = True
                    caught = False
                    arm(failure)
                    try:
                        result = check(data, other, mode)
                    except MemoryError:
                        caught = True
                    arm(0)
                    gc_collect()
                    if not caught or not result:
                        return 2
                    if check(data, other, mode) or len(data) != 2 or len(other) != 1:
                        return 3
                    failure += 1
                mode += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
