import signal
import textwrap

import pytest

from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import COLLECTION_EDIT_CONTRACT


@pytest.mark.parametrize("return_type, result, boundary, lowered", [
    ("int", "values[0]", "local", "values.[list__int]__getitem__(0)"),
    ("list[int]", "values", "caller", "values"),
])
def test_native_collection_analysis_preserves_inplace_and_assignment_contracts(return_type, result, boundary, lowered):
    with analyze_source(f'''
        def main() -> {return_type}:
            values = [1, 2]
            values += values
            values *= 2
            values[0] = 4
            values[1:2] = values
            values.__setitem__(0, 5)
            return {result}
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        # Returning an unboxed element does not return its container; returning
        # the edited list itself must still promote it into caller ownership.
        assert analysis.types == textwrap.dedent(f'''\
            def main() -> {return_type}:
                block entry:
                    values: list[int] = new[{boundary}] list[int](1, 2)
                    values = values.[list__int]__iadd__(values)
                    values = values.[list__int]__imul__(2)
                    values.[list__int]__setitem__(0, 4)
                    $assignment1: list[int] = values
                    values.[list__int]__setslice__($assignment1, 1, 2, None)
                    values.[list__int]__setitem__(0, 5)
                    return {lowered}
        ''').rstrip()


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_collection_edits(optimize):
    result = LLVM().assert_matches_python(COLLECTION_EDIT_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, COLLECTION_EDIT_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_list_edits_aliases_and_snapshots(optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value
                self.children: list[Box] = []

        def show(values: list[int]) -> str:
            result = ""
            for value in values:
                result += str(value) + ","
            return result + "|"

        def main() -> str:
            gc_set_threshold(1)
            values = [0, 1, 2, 3]
            alias = values
            result = show(values)
            values.extend(values)
            values.insert(-99, 9)
            values.insert(99, 8)
            result += show(alias) + str(values.pop()) + str(values.pop(-2))
            copied = values.copy()
            copied.reverse()
            result += show(copied) + show(values)
            copied.clear()
            copied.append(42)
            result += show(copied)
            result += show(values + [4, 5]) + show(2 * values)
            values += values
            values *= 2
            gc_collect()
            result += show(alias)
            values *= 0
            values.append(7)
            result += show(alias) + show([1, 2] * -3)
            for count in (-2, 0, 1, 2, 3, 5, 8, 17):
                shared = Box(7)
                boxes = [shared, Box(2), shared]
                original = boxes
                repeated = count * boxes
                boxes *= count
                gc_collect()
                shared.value += 1
                total = 0
                for box in repeated:
                    total += box.value
                result += str((len(boxes), total, repeated == boxes,
                               boxes is original, repeated is boxes))
            parent = Box(3)
            parent.children.append(parent)
            parent.children *= 5
            gc_collect()
            parent.children[3].value = 9
            result += str((parent.value, parent.children[4] is parent))
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_list_slices_and_deletion(optimize):
    LLVM().assert_matches_python('''
        def show(values: list[int]) -> str:
            result = ""
            for value in values:
                result += str(value) + ","
            return result + "|"

        def main() -> str:
            values = [0, 1, 2, 3, 4, 5]
            result = show(values[::-1]) + show(values[-99:99:2])
            values[1:3] = values
            result += show(values)
            values[::2] = values[1::2]
            result += show(values)
            values[::-1] = values
            result += show(values)
            del values[1:-1:2]
            result += show(values)
            del values[-1]
            result += show(values)
            del values[::-2]
            result += show(values)
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_mutations_preserve_order_and_defaults(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def show(values: dict[str, str]) -> str:
            result = ""
            for key in values:
                result += key + ":" + values[key] + "|"
            return result

        def main() -> str:
            gc_set_threshold(1)
            values = {"a": "é", "b": "😀", "c": "end"}
            alias = values
            result = values.pop("b") + values.pop("missing", "fallback")
            values["b"] = "again"
            result += show(values)
            result += values.setdefault("a", "unused")
            result += values.setdefault("d", "new")
            copied = values.copy()
            copied.update({"a": "changed", "e": "last"})
            copied.update(copied)
            del copied["c"]
            gc_collect()
            result += show(copied) + show(alias)
            copied.clear()
            copied["new"] = "after clear"
            result += show(copied)
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_set_mutations(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            values = {1, 2, 3}
            values.discard(99)
            values.remove(2)
            copied = values.copy()
            copied.update({3, 4, 5})
            copied.update(copied)
            result = str(len(copied)) + str(2 in copied) + str(4 in copied)
            copied.clear()
            copied.add(7)
            return result + str(len(values)) + str(7 in copied)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_removed_pointer_slots_and_copies_survive_collection(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values: list[str] = []
            for index in range(15):
                values.append("text" + str(index))
            copied = values[::-2]
            repeated = copied * 3
            removed = values.pop(3)
            values.clear()
            gc_collect()
            result = removed + "|".join(copied) + "|".join(repeated)
            mapping = {"key" + str(1): "value" + str(2)}
            mapping_copy = mapping.copy()
            popped = mapping.pop("key1")
            mapping.clear()
            gc_collect()
            return result + popped + mapping_copy["key1"]
    ''', optimize=optimize)


@pytest.mark.parametrize("statement", [
    "values.pop(99)", "del values[99]", "values[::0]",
    "values[::2] = [1]", "del values[::0]", "values * 9223372036854775807",
    "values.remove(99)", "values.index(99)",
    'mapping.pop("missing")', 'del mapping["missing"]', "items.remove(99)",
])
def test_invalid_collection_edits_trap(statement):
    result = LLVM().run_source(f'''
        def main() -> int:
            values = [0, 1, 2, 3]
            mapping = {{"a": 1}}
            items = {{1}}
            {statement}
            return 0
    ''')
    assert result.returncode in {-signal.SIGILL, -signal.SIGTRAP}, result.stderr


def test_list_extension_accepts_concrete_tuple_storage():
    result = LLVM().assert_matches_python('''
        def main() -> int:
            values = [1]
            values.extend((2, 3))
            return values[2]
    ''')
    assert result.native.returncode == 3


@pytest.mark.parametrize(("expression", "message"), [
    ('values.get("missing", True)', "LLVM dict.get default has incompatible type"),
    ('values.setdefault("missing", True)', "LLVM dict.setdefault default has incompatible type"),
])
def test_dictionary_default_diagnostics_identify_the_operation(expression, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
            def main() -> int:
                values = {{"key": 1}}
                {expression}
                return 0
        ''')


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize(("statement", "message"), [
    ("values.extend(values=[])", "require positional arguments"),
    ("len([])", "has no concrete item type"),
    ("len({})", "allocation requires a concrete type"),
    ("bool({})", "allocation requires a concrete type"),
])
def test_untyped_empty_collections_have_diagnostics_before_allocation(managed, statement, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
            from pyjs.native import gc_set_threshold

            def main() -> int:
                {"gc_set_threshold(1)" if managed else "pass"}
                values = [1]
                {statement}
                return len(values)
        ''')


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_contextual_empty_edits_execute_and_preserve_failed_assignment(managed, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_set_threshold
        def main() -> str:
            {"gc_set_threshold(1)" if managed else "pass"}
            values = [1, 2, 3]
            alias = values
            values.extend([])
            values += []
            assert values == [1, 2, 3]
            values[0:1] = []
            assert values == [2, 3]
            try:
                values[::2] = []
            except ValueError as error:
                return repr((str(error), values, alias is values))
            raise AssertionError('missing extended slice mismatch')
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_typed_empty_collection_edits_match_python(managed, optimize):
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_set_threshold

        def main() -> str:
            {"gc_set_threshold(1)" if managed else "pass"}
            empty: list[str] = []
            values = ["first", "second"]
            alias = values
            values.extend(empty)
            values += empty
            copied = values + empty
            values[0:1] = empty
            values[0:0:2] = empty
            mapping: dict[str, str] = {{}}
            mapping.update({{"key": "value"}})
            return "|".join(alias) + ":" + "|".join(copied) + mapping["key"]
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_list_search_bounds_and_representation(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            words = ["é", "😀", "é", "end", "é"]
            result = str(words.index("é", -2, 99)) + str(words.index("é", -99, 3))
            for word in ["é", "😀", "absent"]:
                result += str(words.count(word)) + str(word in words)
            words.remove("é")
            result += "|".join(words)
            integers = [1, 2, 3, 2]
            flags = [True, False, True]
            return result + str(integers.count(2)) + str(flags.count(True)) + str(False in flags)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_assignment_and_explicit_calls_preserve_distinct_evaluation_order(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def target(events: list[str], values: list[str]) -> list[str]:
            events.append("target")
            gc_collect()
            return values

        def bound(events: list[str], value: int) -> int:
            events.append("bound" + str(value))
            gc_collect()
            return value

        def replacement(events: list[str]) -> list[str]:
            events.append("replacement")
            return ["new" + str(1)]

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values = ["a", "b"]
            target(events, values)[bound(events, 0):bound(events, 1)] = replacement(events)
            target(events, values).__setitem__(bound(events, 0), replacement(events)[0])
            target(events, values)[bound(events, 1)] = replacement(events)[0]
            return "|".join(events) + "|".join(values)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize(("expression", "expected"), [
    ("len(item(values, events) * snapshot(values, events))", "4:item|snapshot"),
    ("len(snapshot(values, events).__rmul__(item(values, events)))", "2:snapshot|item"),
    ("int(item(values, events) in snapshot(values, events))", "1:item|snapshot"),
    ("int(snapshot(values, events).__contains__(item(values, events)))", "0:snapshot|item"),
    ("int(item(values, events) not in snapshot(values, events))", "0:item|snapshot"),
    ("int(not snapshot(values, events).__contains__(item(values, events)))", "1:snapshot|item"),
])
def test_list_operator_syntax_and_explicit_calls_have_distinct_order(optimize, managed, expression, expected):
    comparison = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        def item(values: list[int], events: list[str]) -> int:
            events.append("item")
            values.append(2)
            {"gc_collect()" if managed else "pass"}
            return 2

        def snapshot(values: list[int], events: list[str]) -> list[int]:
            events.append("snapshot")
            {"gc_collect()" if managed else "pass"}
            return values.copy()

        def main() -> str:
            {"gc_set_threshold(1)" if managed else "pass"}
            values = [1]
            events: list[str] = []
            result = {expression}
            return str(result) + ":" + "|".join(events)
    ''', optimize=optimize)
    assert comparison.native.stdout == expected


@pytest.mark.parametrize("optimize", [0, 2])
def test_membership_roots_the_first_operand_while_evaluating_the_second(optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def item(events: list[str]) -> str:
            events.append("item")
            gc_collect()
            return "value" + str(2)

        def values(events: list[str]) -> list[str]:
            events.append("values")
            gc_collect()
            return ["value" + str(2)]

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            present = item(events) in values(events)
            absent = item(events) not in values(events)
            explicit = values(events).__contains__(item(events))
            return str(int(present)) + str(int(absent)) + str(int(explicit)) + ":" + "|".join(events)
    ''', optimize=optimize)
    assert comparison.native.stdout == "101:item|values|item|values|values|item"


@pytest.mark.parametrize("optimize", [0, 2])
def test_borrowed_inputs_can_be_copied_mutated_and_rendered_repeatedly(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold

        def main(lines: list[str]) -> str:
            gc_set_threshold(1)
            selected = lines.copy()
            selected.reverse()
            selected.insert(0, "header")
            metadata = {"source": "input", "name": lines[0]}
            copied = metadata.copy()
            copied.update({"source": "native"})
            gc_collect()
            result = "|".join(selected)
            for key in copied:
                result += key + "=" + copied[key] + "|"
            selected.clear()
            copied.clear()
            gc_collect()
            return result
    '''
    lines = ["é", "😀", "line\\0"]
    comparison = LLVM().assert_library_matches_python(
        source, lines, directory=tmp_path, optimize=optimize,
    )
    try:
        for _ in range(10):
            assert comparison.library.render(lines) == comparison.python
        assert lines == ["é", "😀", "line\\0"]
    finally:
        comparison.library.close()
