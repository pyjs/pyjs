"""Index and slice domains retain their distinct result/mutation contracts."""

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("numeric,scalar,items", [("int8", "-5", "[6, 7]"),
                                              ("uint8", "0", "[6, 7]"),
                                              ("float32", "2.5", "[3.5, 4.5]")])
@pytest.mark.parametrize("index_type", ["object", "int | slice"])
def test_dynamic_assignment_normalizes_fresh_portable_literals(tmp_path, optimize, numeric, scalar, items, index_type):
    comparison = LLVM().assert_matches_python(f'''
from pyjs import {numeric}
from operator import setitem
def change(index: {index_type}, sliced: bool, mode: int) -> str:
    values: list[{numeric}] = [{numeric}(1), {numeric}(2)]
    if sliced:
        if mode == 0:
            values[index] = {items}
        elif mode == 1:
            values.__setitem__(index, {items})
        else:
            setitem(values, index, {items})
    else:
        if mode == 0:
            values[index] = {scalar}
        elif mode == 1:
            values.__setitem__(index, {scalar})
        else:
            setitem(values, index, {scalar})
    return repr(values)
def main() -> str:
    return repr([change(0, False, mode) + change(slice(1, None), True, mode) for mode in range(3)])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("numeric,ordinary", [("int8", "int"), ("float32", "float")])
@pytest.mark.parametrize("index_type", ["object", "int | slice"])
def test_dynamic_assignment_copies_nonliteral_scalar_values(tmp_path, optimize, numeric, ordinary, index_type):
    comparison = LLVM().assert_matches_python(f'''
from pyjs import {numeric}
from pyjs.native import gc_collect, gc_set_threshold
from operator import setitem
def read(value: {ordinary}, events: list[str]) -> {ordinary}:
    events.append("value")
    gc_collect()
    return value
def receiver(values: list[{numeric}], events: list[str]) -> list[{numeric}]:
    events.append("receiver")
    return values
def index(value: {index_type}, events: list[str]) -> {index_type}:
    events.append("index")
    gc_collect()
    return value
def change(position: {index_type}, number: {ordinary}, mode: int) -> str:
    values: list[{numeric}] = [{numeric}(1), {numeric}(2)]
    events: list[str] = []
    try:
        if mode == 0:
            values[position] = number
        elif mode == 1:
            values[position] = number + 1
        elif mode == 2:
            values[position] = {ordinary}(len(values))
        elif mode == 3:
            values[position] = {ordinary}(2) + {ordinary}(3)
        elif mode == 4:
            values[position] = number if number > 0 else -number
        elif mode == 5:
            receiver(values, events)[index(position, events)] = read(number, events)
        elif mode == 6:
            receiver(values, events).__setitem__(index(position, events), read(number, events))
        else:
            setitem(receiver(values, events), index(position, events), read(number, events))
        state = "ok"
    except TypeError:
        state = "type"
    except ValueError:
        state = "value"
    gc_collect()
    return repr((state, values, number, events))
def main() -> str:
    gc_set_threshold(1)
    return repr([change(0, {ordinary}(4), mode) + change(slice(None), {ordinary}(4), mode)
                 + change(slice(None, None, 0), {ordinary}(4), mode) for mode in range(8)])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("numeric,ordinary", [("int8", "int"), ("float32", "float")])
@pytest.mark.parametrize("index_type", ["object", "int | slice"])
def test_dynamic_assignment_normalizes_mixed_scalar_unions(tmp_path, optimize, numeric, ordinary, index_type):
    comparison = LLVM().assert_matches_python(f'''
from pyjs import {numeric}
from pyjs.native import gc_collect, gc_set_threshold
from operator import setitem
def change(index: {index_type}, rhs: {ordinary} | str | None, mode: int) -> str:
    values: list[{numeric} | str | None] = [{numeric}(3)]
    try:
        if mode == 0:
            values[index] = rhs
        elif mode == 1:
            values.__setitem__(index, rhs)
        else:
            setitem(values, index, rhs)
        state = 'ok'
    except TypeError as error:
        state = str(error)
    gc_collect()
    return repr((state, values, rhs))
def main() -> str:
    gc_set_threshold(1)
    return repr([change(0, {ordinary}(7), mode) + change(0, 'abc', mode)
                 + change(0, None, mode)
                 + change(slice(None), {ordinary}(7), mode)
                 + change(slice(None, None, 2), None, mode)
                 + change(slice(None), 'ab', mode) for mode in range(3)])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("literal", ["[[]]", "[[], []]", "[[[]]]"])
def test_nested_empty_literals_select_each_fresh_context(tmp_path, optimize, literal):
    item = "list[list[list[int]]]" if literal == "[[[]]]" else "list[list[int]]"
    initial = "[[[1]]]" if literal == "[[[]]]" else "[[1]]"
    comparison = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
def change(index: object, explicit: bool) -> str:
    values: list[{item}] = [{initial}, {initial}]
    if explicit:
        values.__setitem__(index, {literal})
    else:
        values[index] = {literal}
    gc_collect()
    return repr(values)
def main() -> str:
    gc_set_threshold(1)
    return repr([change(0, explicit) + change(slice(0, 1), explicit)
                 for explicit in [False, True]])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("literal", ["[[], [[number(events)]]]", "[[], borrow(child, events)]",
                                    "([], borrow(child, events))"])
@pytest.mark.parametrize("index_type", ["object", "int | slice"])
def test_slice_only_fresh_children_receive_the_selected_context(tmp_path, optimize, literal, index_type):
    comparison = LLVM().assert_matches_python(f'''
from operator import setitem
from pyjs.native import gc_collect, gc_set_threshold
def number(events: list[str]) -> int:
    events.append("number")
    gc_collect()
    return 9
def borrow(value: list[list[int]], events: list[str]) -> list[list[int]]:
    events.append("borrow")
    gc_collect()
    return value
def change(index: {index_type}, mode: int) -> str:
    values: list[list[list[int]]] = [[[1]], [[2]], [[3]], [[4]]]
    child = [[9]]
    events: list[str] = []
    error = "ok"
    try:
        if mode == 0:
            values[index] = {literal}
        elif mode == 1:
            values.__setitem__(index, {literal})
        else:
            setitem(values, index, {literal})
    except (TypeError, ValueError) as caught:
        error = str(caught)
    child[0].append(10)
    gc_collect()
    return repr((values, child, events, error))
def main() -> str:
    gc_set_threshold(1)
    return repr([change(slice(0, 1), mode) + change(slice(None, None, 2), mode)
                 + change(slice(None, None, 4), mode) + change(slice(None, None, 0), mode)
                 for mode in range(3)])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_only_literal_rejects_incompatible_item_without_mutation(tmp_path, optimize):
    # CPython accepts the untyped item store. Native storage deliberately
    # rejects its incompatible nested layout, and must leave the list intact.
    result = LLVM().run_source('''
from pyjs.native import gc_collect, gc_set_threshold
def change(index: object) -> str:
    values: list[list[list[int]]] = [[[1]], [[2]]]
    try:
        values[index] = [[], [[9]]]
    except TypeError as error:
        gc_collect()
        return str(error) + ":" + repr(values)
    return "unchecked item store"
def main() -> str:
    gc_set_threshold(1)
    return change(0)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stdout == "list assignment has incompatible item representation:[[[1]], [[2]]]"
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("literal", ["[read(events), 2]", "(read(events), 2)"])
@pytest.mark.parametrize("index_type", ["object", "int | slice"])
def test_overlapping_literal_contexts_keep_order_and_each_selected_width(tmp_path, optimize, literal, index_type):
    container = "list[int64]" if literal.startswith("[") else "tuple[int64, ...]"
    protocol_case = "+ change(Position(), mode)" if index_type == "object" else ""
    comparison = LLVM().assert_matches_python(f'''
from pyjs import int8, int64
from pyjs.native import gc_collect, gc_set_threshold
from operator import setitem
class Position:
    def __index__(self) -> int:
        gc_collect()
        return 0
def read(events: list[str]) -> int:
    events.append("value")
    gc_collect()
    return 1
def receiver(values: list[int8 | {container}], events: list[str]) -> list[int8 | {container}]:
    events.append("receiver")
    gc_collect()
    return values
def offset(index: {index_type}, events: list[str]) -> {index_type}:
    events.append("index")
    gc_collect()
    return index
def change(index: {index_type}, mode: int) -> str:
    values: list[int8 | {container}] = [int8(3)]
    events: list[str] = []
    try:
        if mode == 0:
            receiver(values, events)[offset(index, events)] = {literal}
        elif mode == 1:
            receiver(values, events).__setitem__(offset(index, events), {literal})
        else:
            setitem(receiver(values, events), offset(index, events), {literal})
        state = "ok"
    except ValueError:
        state = "value"
    gc_collect()
    return repr((state, values, events))
def main() -> str:
    gc_set_threshold(1)
    return repr([change(0, mode) + change(slice(None), mode)
                 + change(slice(None, None, 0), mode) {protocol_case} for mode in range(3)])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_overlapping_literals_do_not_narrow_before_selecting_context(tmp_path, optimize):
    # Compare against equivalent static stores: CPython ignores annotations,
    # whereas compiled int8 storage intentionally wraps. Both paths must agree.
    comparison = LLVM().assert_matches_python('''
from pyjs import int8, int64
def change(index: object, sliced: bool) -> bool:
    actual: list[int64 | list[int8]] = [int64(3)]
    expected: list[int64 | list[int8]] = [int64(3)]
    actual[index] = [257, 258]
    if sliced:
        expected[:] = [257, 258]
    else:
        expected[0] = [257, 258]
    return actual == expected
def explicit(index: object) -> str:
    values: list[int8 | list[int64]] = [int8(3)]
    values[index] = [int8(1), int8(2)]
    return repr(values)
def main() -> str:
    return repr((change(0, False), change(slice(None), True))) + explicit(slice(None))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_overlapping_empty_and_nested_literals_keep_borrowed_children(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def empty(index: object) -> str:
    values: list[list[int]] = [[1], [2]]
    values[index] = []
    gc_collect()
    return repr(values)
def nested(index: object, borrowed: list[object]) -> str:
    values: list[list[object]] = [[1], [2]]
    values[index] = [[3], borrowed]
    gc_collect()
    borrowed.append(6)
    return repr(values)
def main() -> str:
    gc_set_threshold(1)
    borrowed: list[object] = [5]
    return empty(0) + empty(slice(0, 1)) + nested(0, borrowed) + nested(slice(0, 1), borrowed)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_fresh_nested_literals_preserve_aliases(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
def change(index: object, mode: int) -> str:
    values: list[list[int8]] = [[int8(1)]]
    borrowed: list[int8] = [int8(6)]
    if mode == 0:
        values[index] = [2, 3]
    elif mode == 1:
        values[index] = [[4], [5]]
    else:
        values[index] = [borrowed]
    gc_collect()
    borrowed[0] += 1
    return repr(values)
def main() -> str:
    gc_set_threshold(1)
    return change(0, 0) + change(slice(None), 1) + change(slice(None), 2)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_assignment_trace_reports_only_actual_callers(tmp_path, optimize):
    comparison = LLVM().compare_with_python('''def first(index: object, value: object) -> None:
    values: list[object] = [1, 2]
    values[index] = value

def second(index: object, value: object) -> None:
    values: list[object] = [3, 4]
    values[index] = value

def main() -> str:
    first(0, 1)
    second(slice(None, None, 0), 5)
    return "unreachable"
''', filename="dynamic_assignment.py", directory=tmp_path, optimize=optimize)
    assert comparison.python.returncode != 0
    assert comparison.native.returncode != 0
    assert comparison.native.stderr == (
        'Traceback (native PyJS):\n'
        '  File "dynamic_assignment.py", line 11, in main\n'
        '  File "dynamic_assignment.py", line 7, in second\n'
        'ValueError: slice step cannot be zero\n'
    )


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,item,replacements", [
    ("int | None", "int | None", "[None, 7]"),
    ("int | None", "int8 | None", "[None, 7]"),
    ("int8 | None", "int8 | None", "[None, int8(127)]"),
    # None is a valid scalar reference item but never a slice replacement.
    # Splicing list[int] into list[list[int] | None] would violate its item type.
    ("list[int] | None", "list[int] | None", "[None]"),
    ("list[int] | None", "object", "[None, [7, 8]]"),
    ("str | None", "object", "[None, 'ab']"),
    ("tuple[int, ...] | None", "object", "[None, (7, 8)]"),
])
def test_optional_replacements_visit_present_and_none_arms(tmp_path, optimize, annotation, item, replacements):
    comparison = LLVM().assert_matches_python(f'''
from operator import setitem
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
def change(index: object, value: {annotation}, mode: int) -> str:
    values: list[{item}] = [None, None]
    try:
        if mode == 0:
            values[index] = value
        elif mode == 1:
            values.__setitem__(index, value)
        else:
            setitem(values, index, value)
        gc_collect()
        return "ok:" + repr(values)
    except TypeError:
        return "type:" + repr(values)
    except ValueError:
        return "value:" + repr(values)
    except IndexError:
        return "index:" + repr(values)
def main() -> str:
    gc_set_threshold(1)
    indices: list[object] = [0, -1, 9, None, slice(None), slice(None, None, 2), slice(None, None, 0)]
    replacements: list[{annotation}] = {replacements}
    return repr([change(index, value, mode) for index in indices
                 for value in replacements for mode in range(3)])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_mutations_select_scalar_or_iterable_replacements(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from operator import getitem, setitem, delitem
from pyjs.native import gc_collect, gc_set_threshold
def replace(index: object, replacement: object, mode: int) -> str:
    values: list[object] = [1, 2, 3, 4]
    try:
        if mode == 2:
            setitem(values, index, replacement)
        elif mode == 1:
            values.__setitem__(index, replacement)
        else:
            values[index] = replacement
        result = repr(values)
        result += repr(getitem(values, index))
        gc_collect()
        if mode == 2:
            delitem(values, index)
        elif mode == 1:
            values.__delitem__(index)
        else:
            del values[index]
        return result + repr(values)
    except TypeError:
        return "type" + repr(values)
    except ValueError:
        return "value" + repr(values)
    except IndexError:
        return "index" + repr(values)
def main() -> str:
    gc_set_threshold(1)
    indices: list[object] = [0, -1, 10, None, slice(1, 3), slice(None, None, 2), slice(0, 2, 0)]
    replacements: list[object] = [9, [7, 8], (5, 6), (), "ab", None]
    return repr([replace(index, replacement, mode) for index in indices
                 for replacement in replacements for mode in range(3)])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_and_tagged_subscripts_select_item_or_slice_results(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def erased(index: object) -> str:
    gc_collect()
    try:
        return repr(([2, 4, 6][index], (2, 4, 6)[index], "aé😀"[index],
                     b"abc"[index], range(2, 8, 2)[index]))
    except TypeError:
        return "type"
    except IndexError:
        return "index"
    except ValueError:
        return "value"
def explicit(index: int | slice | None) -> str:
    try:
        return repr(([2, 4, 6].__getitem__(index), (2, 4, 6).__getitem__(index),
                     "aé😀".__getitem__(index), b"abc".__getitem__(index),
                     range(2, 8, 2).__getitem__(index)))
    except TypeError:
        return "type"
def empty(index: object) -> str:
    try:
        return repr(()[index])
    except TypeError:
        return "type"
    except IndexError:
        return "index"
    except ValueError:
        return "value"
def main() -> str:
    gc_set_threshold(1)
    indexes: list[object] = [0, -1, True, 9, None, "bad", slice(1),
                             slice(None, None, -1), slice(0, 3, 0)]
    return repr(([erased(index) for index in indexes], [empty(index) for index in indexes],
                 [explicit(index) for index in [0, slice(0, 2), None]]))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_replacement_retains_callbacks_aliases_and_failure_order(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Source:
    def __init__(self, values: list[object], events: list[str], fail: bool):
        self.values, self.events, self.fail = values, events, fail
    def __iter__(self):
        self.events.append("iter")
        yield 9
        self.values.append(5)
        gc_collect()
        if self.fail:
            raise ValueError("source")
        yield 8
class Index:
    def __init__(self, values: list[object], events: list[str]):
        self.values, self.events = values, events
    def __index__(self) -> int:
        self.events.append("index")
        self.values.append(7)
        gc_collect()
        return 0
class Cursor:
    def __init__(self, events: list[str]):
        self.events = events
        self.position = 0
    def __iter__(self) -> Cursor:
        self.events.append("acquire")
        return self
    def __next__(self) -> int:
        if self.position == 2:
            raise StopIteration()
        self.position += 1
        gc_collect()
        return self.position
def change(values: list[object], index: object, replacement: object) -> str:
    try:
        values[index] = replacement
        return repr(values)
    except ValueError:
        return "failed" + repr(values)
def main() -> str:
    gc_set_threshold(1)
    rows: list[str] = []
    for fail in [False, True]:
        values: list[object] = [1, 2, 3]
        events: list[str] = []
        rows.append(change(values, slice(1, 3), Source(values, events, fail)))
        rows.append(repr(events))
    values: list[object] = [1, 2, 3]
    events: list[str] = []
    rows.append(change(values, slice(None, None, -1), values))
    rows.append(change(values, Index(values, events), [9]))
    rows.append(change(values, slice(0, 1), Cursor(events)))
    rows.append(repr(events))
    return repr(rows)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_subscript_results_keep_portable_and_reference_item_layouts(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs import int8, int64
from pyjs.native import gc_collect, gc_set_threshold
class Box:
    def __init__(self, value: int):
        self.value = value
def inspect(index: object) -> str:
    small: list[int8] = [int8(127), int8(-128)]
    wide: tuple[int64, ...] = (int64(9007199254740993), int64(-9007199254740993))
    items = [Box(1), Box(2)]
    answer = items[index]
    narrow = small[index]
    explicit = small.__getitem__(index)
    large = wide[index]
    if isinstance(narrow, list):
        wrapped = narrow[0] + int8(1)
    else:
        wrapped = narrow + int8(1)
    if isinstance(explicit, list):
        explicit_wrapped = explicit[0] + int8(1)
    else:
        explicit_wrapped = explicit + int8(1)
    if isinstance(large, int):
        exact = large + int64(1)
    else:
        exact = large[0] + int64(1)
    gc_collect()
    if isinstance(answer, list):
        same = answer[0] is items[0]
        state = answer[0].value
    else:
        same = answer is items[0]
        state = answer.value
    return repr((wrapped, explicit_wrapped, exact, same, state))
def main() -> str:
    gc_set_threshold(1)
    return inspect(0) + inspect(slice(0, 1))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_assignment_keeps_represented_and_nested_replacement_layouts(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
def represented(values: list[int8], index: object, rhs: int8 | list[int8]) -> str:
    values[index] = rhs
    values[0] += int8(1)
    gc_collect()
    return repr(values)
def flatten(values: list[object], index: object, rhs: object) -> None:
    values[index] = rhs
def main() -> str:
    gc_set_threshold(1)
    small: list[int8] = [int8(127)]
    rows = [represented(small, 0, int8(127)),
            represented(small, slice(None), [int8(127)])]
    nested: list[list[list[int]]] = [[[1, 2]]]
    result: list[object] = []
    flatten(result, slice(None), nested)
    flatten(result, slice(None), result[0])
    flatten(result, slice(None), result[0])
    rows.append(repr(result))
    widths: list[list[int8]] = [[int8(127)]]
    flatten(result, slice(None), widths)
    selected = cast(list[int8], result[0])
    selected[0] += int8(1)
    rows.append(repr((selected is widths[0], selected)))
    return repr(rows)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_slice_values_preserve_identity_fields_and_truth(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import cast
from pyjs.native import gc_collect, gc_set_threshold
def erase(value: slice) -> object:
    gc_collect()
    return value
def inspect(value: object, same: slice) -> str:
    gc_collect()
    assert isinstance(value, slice)
    selected = cast(slice, value)
    return repr((bool(value), value is same, selected is same, value == same,
                 selected.start, selected.stop, selected.step, value))
def main() -> str:
    gc_set_threshold(1)
    result: list[str] = []
    for value in [slice(None), slice(False, True), slice(1, 8, 0), slice(-4, None, -1)]:
        values: list[object] = [erase(value)]
        selected = values.pop()
        gc_collect()
        result.append(inspect(selected, value))
    return repr(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_tagged_slice_values_and_range_results_keep_their_kind(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def describe(value: slice | int | range | None) -> str:
    gc_collect()
    if isinstance(value, slice):
        return repr(("slice", value.start, value.stop, value.step))
    if isinstance(value, range):
        return repr(("range", list(value)))
    return repr(value)
def main() -> str:
    gc_set_threshold(1)
    values: list[slice | int | range | None] = [slice(0, 3), 2, range(1, 5, 2), None]
    return repr([describe(value) for value in values])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("replacement,index", [("rhs", "slice(1, 2)"),
    ("[rhs, [2, 3]]", "slice(1, 2)"), ("[rhs, [2, 3]]", "1")])
def test_dynamic_replacement_allocation_failure_keeps_destination_and_allows_retry(tmp_path, optimize, replacement, index):
    source = transpile_llvm('''
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm, remaining
def replace(values: list[object], index: object, rhs: object, failure: int) -> int:
    arm(failure)
    values[index] = REPLACEMENT
    left = remaining()
    arm(0)
    return left
def main() -> int:
    gc_set_threshold(1)
    index: object = INDEX
    rhs: object = range(10)
    values: list[object] = [1, 2, 3]
    stages = 1000 - replace(values, index, rhs, 1000)
    assert stages > 0
    expected = repr(values)
    for failure in range(1, stages + 1):
        values = [1, 2, 3]
        try:
            replace(values, index, rhs, failure)
        except MemoryError:
            arm(0)
        else:
            arm(0)
            return 1
        gc_collect()
        assert repr(values) == '[1, 2, 3]'
        replace(values, index, rhs, 0)
        assert repr(values) == expected
    return 0
'''.replace("REPLACEMENT", replacement).replace("INDEX", index))
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_boxed_index_allocation_failure_keeps_mutation_and_generator_handlers(tmp_path, optimize):
    source = transpile_llvm('''
from collections.abc import Generator
from pyjs.native import gc_collect, gc_count
from tests.native.allocation_support import arm, remaining
class Position:
    def __index__(self) -> object:
        gc_collect()
        return 0
def store(values: list[int], position: object) -> None:
    values[position] = 9
def suspended(values: list[int], position: object) -> Generator[int, int, None]:
    try:
        received = yield 1
        assert received is not None
        values[position] = received
    except MemoryError:
        yield -1
    yield values[0]
def resume(values: list[int], position: object) -> None:
    iterator = suspended(values, position)
    assert next(iterator) == 1
    arm(1)
    selected = iterator.send(9)
    arm(0)
    gc_collect()
    assert selected == -1 and values == [3] and next(iterator) == 3
    iterator.close()
def main() -> int:
    values = [3]
    position: object = Position()
    arm(1000)
    store(values, position)
    stages = 1000 - remaining()
    arm(0)
    assert stages > 0 and values == [9]
    gc_collect()
    live = gc_count()
    for failure in range(1, stages + 1):
        values[0] = 3
        arm(failure)
        try:
            store(values, position)
        except MemoryError:
            arm(0)
        else:
            arm(0)
            return 1
        gc_collect()
        assert values == [3] and gc_count() == live
        store(values, position)
        assert values == [9]
    for repeat in range(32):
        values[0] = 3
        resume(values, position)
        gc_collect()
        assert gc_count() == live
    store(values, position)
    return 0 if values == [9] else 2
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
