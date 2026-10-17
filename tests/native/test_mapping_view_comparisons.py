import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("name", ["KeysView", "ItemsView", "set", "frozenset"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_view_namesake_comparisons_use_application_methods(tmp_path, name, optimize):
    result = LLVM().assert_matches_python(f'''
        class {name}:
            def __init__(self, number: int):
                self.number = number

            def __eq__(self, other: object) -> bool:
                if isinstance(other, {name}):
                    return self.number == other.number
                return other is None

            def __ne__(self, other: object) -> bool:
                return other is None

            def __le__(self, other: {name}) -> bool:
                return self.number <= other.number

        def main() -> str:
            left = {name}(1)
            right = {name}(2)
            return str((left == right, left == left, left <= right, right <= left,
                        left.__eq__(None), left.__ne__(None)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("other", ["KeysView", "set", "frozenset"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_item_view_relations_hash_base_values_against_subtype_peers(tmp_path, other, optimize):
    expressions = ", ".join(f"{left} {operation} {right}"
                            for left, right in [("left", "right"), ("right", "left")]
                            for operation in ("==", "!=", "<", "<=", ">", ">="))
    peer = "data.keys()" if other == "KeysView" else f"{other}(data)"
    result = LLVM().assert_matches_python(f'''
        from collections.abc import ItemsView, KeysView
        from pyjs.native import gc_collect, gc_count, gc_pin, gc_unpin

        class Value:
            def __init__(self, number: int):
                self.number = number

            def __hash__(self) -> int:
                gc_pin(self)
                gc_collect()
                return self.number

            def __eq__(self, other: Value) -> bool:
                return self.number == other.number

        class Child(Value):
            def __hash__(self) -> int:
                return self.number

        def check(left: ItemsView[int, Value], right: {other}[tuple[int, Child]]) -> str:
            return str(({expressions}))

        def main() -> str:
            value = Value(7)
            data = {{(1, Child(7)): 0}}
            result = check({{1: value}}.items(), {peer})
            gc_collect()
            result += ":" + str(gc_count())
            gc_unpin(value)
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_view_comparisons_and_search_retain_value_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_pin, gc_unpin

        class Value:
            def __init__(self, number: int):
                self.number = number

            def __eq__(self, other: Value) -> bool:
                gc_pin(self)
                gc_collect()
                return self.number == other.number

        def main() -> str:
            a, b = Value(7), Value(7)
            left, right = {1: a}.items(), {1: b}.items()
            rows = [right]
            found = ([left] == rows, (left,) == (right,), {0: left} == {0: right},
                     left in rows, rows.count(left), rows.index(left),
                     left in {0: right}.values(), (0, left) in {0: right}.items(),
                     {0: left}.items().isdisjoint({0: right}.items()))
            rows.remove(left)
            gc_collect()
            gc_unpin(a)
            gc_unpin(b)
            return str((found, rows))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("shape", ["nested", "optional", "union"])
def test_nested_view_hash_retention_survives_requests_and_failures(tmp_path, optimize, shape):
    left_type = "ItemsView[int, Value]"
    peer = "set[tuple[int, Child]]"
    right_type = {"nested": "list[KeysView[tuple[int, Child]]]",
                  "optional": peer + " | None", "union": peer + " | frozenset[tuple[int, Child]]"}[shape]
    right_value = {"nested": "[right.keys()]", "optional": "None if number == 0 else set(right)",
                   "union": "set(right) if number % 2 else frozenset(right)"}[shape]
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
def compare(left: LEFT_TYPE, right: RIGHT_TYPE) -> bool:
    return left == right
def render(number: int, fail: bool) -> str:
    left = {1: Value(number)}
    right = {(1, Child(number)): 0}
    assert compare(LEFT_VALUE, RIGHT_VALUE) == EXPECTED
    gc_collect()
    if fail:
        raise ValueError("saved before failure")
    return str([value.number for value in SAVED])
'''
    source = source.replace("LEFT_TYPE", f"list[{left_type}]" if shape == "nested" else left_type).replace(
        "RIGHT_TYPE", right_type).replace("LEFT_VALUE", "[left.items()]" if shape == "nested" else "left.items()").replace(
        "RIGHT_VALUE", right_value).replace("EXPECTED", "(number != 0)" if shape == "optional" else "True")
    namespace = {}
    exec(source, namespace)
    requests = [(1, False), (2, True), (3, False), (4, False)]
    if shape == "optional":
        requests.append((0, False))
    expected = []
    for number, fail in requests:
        if fail:
            with pytest.raises(ValueError, match="saved before failure"):
                namespace["render"](number, fail)
        else:
            expected.append(namespace["render"](number, fail))
    # Persistent ctypes libraries are unsanitized, unlike the standalone cases.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number, fail in requests:
            if fail:
                with pytest.raises(LLVMRuntimeError, match="saved before failure"):
                    library.render(number, fail)
            else:
                actual.append(library.render(number, fail))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


@pytest.mark.parametrize("view", ["keys", "items"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_views_compare_by_contents_and_cardinality(tmp_path, view, optimize):
    result = LLVM().assert_matches_python(f"""
        def main() -> str:
            left = {{1: 10, 2: 20}}.{view}()
            same = {{2: 20, 1: 10}}.{view}()
            short = {{1: 10}}.{view}()
            different = {{1: 10, 3: 30}}.{view}()
            empty = {{1: 10}}
            empty.clear()
            missing = empty.{view}()
            return str((left == same, left != same, left == different,
                        left == left, short < left, short <= left,
                        left > short, left >= short, left < same,
                        left <= same, left >= same, missing < left,
                        missing == missing, left == [1, 2], left != None))
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("view", ["keys", "items"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_views_compare_with_sets_in_both_directions(tmp_path, view, optimize):
    result = LLVM().assert_matches_python(f"""
        def main() -> str:
            view = {{1: 10, 2: 20}}.{view}()
            same = set(view)
            short = set({{1: 10}}.{view}())
            frozen = frozenset(view)
            return str((view == same, same == view, view == frozen,
                        frozen == view, view <= same, same <= view,
                        short < view, view > short, same > view,
                        same != view, short != view))
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_item_view_comparisons_do_not_hash_unhashable_values(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            data = {1: [10], 2: [20]}
            left = data.items()
            same = {2: [20], 1: [10]}.items()
            short = {1: [10]}.items()
            gc_collect()
            before = (left == same, short < left, left >= same)
            data[2] = [30]
            return str((before, left != same, left == same, short <= left))
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_view_comparisons_keep_value_callbacks_and_unwind_on_mutation(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
        from typing import ItemsView
        from pyjs.native import gc_collect, gc_set_threshold

        class Value:
            def __init__(self, events: list[str], mode: int):
                self.events = events
                self.mode = mode
                self.owner: dict[int, Value] = {}

            def __eq__(self, other: "Value") -> bool:
                self.events.append("compare")
                self.owner.clear()
                gc_collect()
                if self.mode == 2:
                    raise ValueError("callback failed")
                return self.mode == 1

        def compare(left: ItemsView[int, Value], right: ItemsView[int, Value]) -> str:
            try:
                return str(left == right)
            except RuntimeError:
                return "mutated"
            except ValueError:
                return "callback failed"

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            results: list[str] = []
            for mode in range(3):
                left = {1: Value(events, 0)}
                value = Value(events, mode)
                right = {1: value}
                value.owner = left
                results.append(compare(left.items(), right.items()))
                gc_collect()
                results.append(str({1: 10}.items() == {1: 10}.items()))
            return str((results, events))
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_key_view_comparisons_hash_aliases_and_preserve_callback_order(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, label: str, events: list[str]):
                self.label = label
                self.events = events

            def __hash__(self) -> int:
                self.events.append("hash " + self.label)
                gc_collect()
                return 1

            def __eq__(self, other: "Key") -> bool:
                self.events.append(self.label + " == " + other.label)
                gc_collect()
                return True

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            left = {Key("left", events): 1}.keys()
            right = {Key("right", events): 1}.keys()
            values = set(left)
            events.clear()
            results = (left == left, left == right, left <= right,
                       left >= right, values == right, right == values)
            return str((results, events))
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_view_comparisons_keep_mixed_numeric_keys_exact(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
        def main() -> str:
            integers = {1: 10}.keys()
            floating = {1.0: 10}.keys()
            fractional = {1.5: 10}.keys()
            wide = {9007199254740993: 10}.keys()
            rounded = {9007199254740992.0: 10}.keys()
            values = {1.0}
            return str((integers == floating, floating == integers,
                        integers == fractional, fractional <= integers,
                        wide == rounded, rounded == wide,
                        integers == values, values == integers,
                        integers <= values, values >= integers,
                        {1: 10}.items() == {1.0: 10}.items()))
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("view", ["keys", "items"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_view_identity_skips_hashing_but_direct_equality_does_not(tmp_path, view, optimize):
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __init__(self):
                self.fail = False

            def __hash__(self) -> int:
                if self.fail:
                    raise ValueError("hash called")
                return 1

        def main() -> str:
            key = Key()
            view = {{key: 2}}.{view}()
            key.fail = True
            direct = "missing failure"
            try:
                view == view
            except ValueError as error:
                direct = str(error)
            return str((direct, [view] == [view], (view,) == (view,), view in [view]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_key_view_comparison_distinguishes_pointer_layouts(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
        def main() -> str:
            return str({"key": 1}.keys() == {b"key": 1}.keys())
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["[1] < view", "view > [1]"])
def test_view_ordering_requires_setlike_operands(expression):
    with pytest.raises(LLVMUnsupported, match="view ordering requires concrete set-like operands"):
        transpile_llvm(f"""
            def main() -> bool:
                view = {{1: 2}}.keys()
                return {expression}
        """)


@pytest.mark.parametrize("view", ["keys", "items"])
@pytest.mark.parametrize("method", ["__eq__", "__ne__"])
def test_explicit_view_comparison_does_not_replace_notimplemented_with_false(view, method):
    with pytest.raises(LLVMUnsupported, match="unsupported NotImplemented"):
        transpile_llvm(f"""
            def main() -> bool:
                return {{1: 2}}.{view}().{method}([1])
        """)


@pytest.mark.parametrize("optimize", [0, 2])
def test_view_comparisons_evaluate_receivers_once_in_source_order(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
        from typing import KeysView

        def make(events: list[str], label: str) -> KeysView[int]:
            events.append(label)
            return {1: 10}.keys()

        def main() -> str:
            events: list[str] = []
            results = (make(events, "left") == make(events, "right"),
                       make(events, "first").__ge__(make(events, "second")))
            return str((results, events))
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
