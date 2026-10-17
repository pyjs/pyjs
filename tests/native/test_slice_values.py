import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import SLICE_VALUE_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_slice_value_contract(optimize):
    result = LLVM().assert_matches_python(SLICE_VALUE_CONTRACT.source,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("bound", ['"deferred string"', '1.5', '[1]'])
def test_slice_bounds_keep_a_typed_integer_boundary(bound):
    with pytest.raises(LLVMUnsupported, match="slice bounds support only integers, booleans and None"):
        transpile_llvm(f'def main() -> str:\n    return repr(slice({bound}))\n')


def test_slice_explicit_unlike_comparison_has_a_notimplemented_boundary():
    with pytest.raises(LLVMUnsupported, match="explicit slice comparison may return NotImplemented"):
        transpile_llvm("def main() -> bool:\n    return slice(1).__eq__(1)\n")


def test_slice_ordering_stays_unsupported():
    with pytest.raises(LLVMUnsupported, match="slice.__lt__ is not supported"):
        transpile_llvm("def main():\n    return slice(1) < slice(2)\n")


def test_slice_fields_are_read_only():
    with pytest.raises(CompilationError, match="Property 'start' is read-only"):
        transpile_llvm("def main():\n    value = slice(1)\n    value.start = 2\n")


@pytest.mark.parametrize("replacement", ["iter([3.0])", "(3.0,)", "[3.0]", "3"])
def test_slice_replacement_requires_compatible_iterable_items(replacement):
    with pytest.raises(CompilationError, match="No overload|Argument 'value' to list.__setitem__ expects|Type 'int' is not iterable"):
        transpile_llvm(f"def main():\n    values = [1, 2]\n    values[slice(1)] = {replacement}\n")


@pytest.mark.parametrize("sequence", ["[1, 2, 3]", "(1, 2, 3)", "'abc'", "b'abc'", "range(3)", "Shade.RED"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_syntactic_slices_check_tagged_bounds_before_consuming_payloads(sequence, optimize):
    # Former compile-time rejection matrix: strings now raise TypeError, while
    # application objects invoke __index__. Neither pointer becomes an index.
    result = LLVM().assert_matches_python(f'''
        from enum import StrEnum
        from pyjs.native import gc_collect, gc_set_threshold
        class Shade(StrEnum):
            RED = "crimson"
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return -1
        def selected(bound: int | str | Index | None) -> str:
            rows: list[str] = []
            try:
                rows.append(repr({sequence}[bound:]))
            except TypeError:
                rows.append("bad start")
            try:
                rows.append(repr({sequence}[:bound]))
            except TypeError:
                rows.append("bad stop")
            try:
                rows.append(repr({sequence}[::bound]))
            except TypeError:
                rows.append("bad step")
            return '|'.join(rows)
        def main() -> str:
            gc_set_threshold(1)
            return '|'.join([selected(1), selected(None), selected(Index()), selected("bad")])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_syntactic_slice_enum_receivers_and_bounds_keep_scalar_semantics(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum, StrEnum
        from pyjs.native import gc_collect, gc_set_threshold
        class Index(IntEnum):
            ZERO = 0
            ONE = 1
            TWO = 2
            REVERSE = -1
        class Shade(StrEnum):
            RED = "crimson"
        def selected(values: list[int], start: Index, step: Index | None) -> list[int]:
            return values[start::step]
        def main() -> str:
            gc_set_threshold(1)
            values = [0, 1, 2, 3]
            rows = [repr((values[Index.ONE:Index.TWO], selected(values, Index.ONE, None),
                          selected(values, Index.ONE, Index.TWO),
                          (0, 1, 2, 3)[Index.ONE:], range(10)[Index.ONE::Index.TWO],
                          'abcd'[Index.ONE:], b'abcd'[Index.ONE:],
                          Shade.RED[Index.ONE::Index.TWO], Shade.RED[::Index.REVERSE]))]
            values[Index.ONE:Index.TWO] = [9, 9]
            gc_collect()
            rows.append(repr(values))
            del values[Index.ONE:]
            rows.append(repr(values))
            try:
                Shade.RED[::Index.ZERO]
            except ValueError as error:
                rows.append(str(error))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_stored_slice_bounds_do_not_erase_enum_identity():
    with pytest.raises(LLVMUnsupported, match="slice bounds support only integers, booleans and None"):
        transpile_llvm('''
            from enum import IntEnum
            class Index(IntEnum):
                ONE = 1
            def main() -> str:
                return repr(slice(Index.ONE).stop)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_comparisons_keep_original_operand_order(optimize):
    result = LLVM().assert_matches_python('''
        def chosen(n: int, events: list[int]) -> slice:
            events.append(n)
            return slice(n)
        def integer(n: int, events: list[int]) -> int:
            events.append(n)
            return n
        def main() -> str:
            events: list[int] = []
            a = chosen(1, events) == integer(2, events)
            b = integer(3, events) == chosen(4, events)
            c = chosen(5, events) != integer(6, events)
            d = integer(7, events) != chosen(8, events)
            return repr((a, b, c, d, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_values_fields_reads_normalization_and_identity(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def selected(start: int | bool | None, stop: int | bool | None,
                     step: int | bool | None) -> slice:
            return slice(start, stop, step)
        def main() -> str:
            gc_set_threshold(1)
            choices = [selected(None, -1, 2), selected(True, None, None),
                       selected(None, None, -1), selected(-9223372036854775808, 9223372036854775807, 2),
                       selected(None, None, -9223372036854775808), slice(0), slice(None)]
            rows: list[str] = []
            for choice in choices:
                gc_collect()
                values = [0, 1, 2, 3, 4, 5]
                rows.append(repr((choice, choice.start, choice.stop, choice.step,
                                  choice.indices(6), values[choice], "aébc😀d"[choice],
                                  b"ab\\x00c\\xffd"[choice], list(range(6)[choice]), bool(choice),
                                  tuple(values)[choice], (0, 1, 2, 3, 4, 5)[choice], ()[choice])))
            first = slice(True, None, -1)
            same = first
            second = slice(1, None, -1)
            gc_collect()
            rows.append(repr((first == second, first != slice(1), first is same,
                              first is second, id(first) == id(same), id(first) == id(second))))
            return "|".join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_assignment_deletion_failure_order_and_optional_syntax(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def bound(value: int | None, events: list[int]) -> int | None:
            events.append(1)
            gc_collect()
            return value
        def target(values: list[int], events: list[int]) -> list[int]:
            events.append(2)
            return values
        def replacement(events: list[int]) -> list[int]:
            events.append(3)
            return [8, 9]
        def optional(values: list[int], text: str, binary: bytes, start: int | None,
                     stop: int | None, step: int | None) -> str:
            return repr((values[start:stop:step], text[start:stop:step],
                         binary[start:stop:step], list(range(6)[start:stop:step])))
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values = [0, 1, 2, 3, 4, 5]
            target(values, events)[slice(bound(1, events), bound(4, events), 2)] = replacement(events)
            rows = [repr((values, events))]
            values[slice(1, 2)] = values
            rows.append(repr(values))
            del values[slice(None, None, 3)]
            rows.append(repr(values))
            values[slice(1, 2)] = []
            rows.append(repr(values))
            for stride in [0, 2]:
                before = repr(values)
                try:
                    values[slice(None, None, stride)] = [7]
                except ValueError as error:
                    rows.append(str(error))
                rows.append(str(repr(values) == before))
            rows.append(optional([0, 1, 2, 3, 4, 5], "aébc😀d", b"abcdef", None, -1, None))
            rows.append(optional([0, 1, 2, 3, 4, 5], "aébc😀d", b"abcdef", None, None, -1))
            for length in [-1, 0, 6]:
                try:
                    rows.append(repr(slice(None, None, False).indices(length)))
                except ValueError as error:
                    rows.append(str(error))
            return "|".join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_values_preserve_numeric_and_managed_item_layouts(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __init__(self, number: int):
                self.number = number
        class Selection:
            def __init__(self, value: slice):
                self.value = value
        def reverse(values: list[int8], selected: slice) -> list[int8]:
            return values[selected]
        def reverse_tuple(values: tuple[int8, ...], selected: slice) -> tuple[int8, ...]:
            return values.__getitem__(selected)
        def main() -> str:
            gc_set_threshold(1)
            values: list[int8] = [int8(1), int8(2), int8(3)]
            selection = Selection(slice(None, None, -1))
            gc_collect()
            selected = selection.value
            result = reverse(values, selected)
            explicit = values.__getitem__(slice(0, 2))
            tuple_copy = tuple(values)[selected]
            explicit_tuple = reverse_tuple(tuple(values), selected)
            values[slice(1, 2)] = result
            floats: list[float32] = [float32(1.25), float32(2.5)]
            copied = floats[selected]
            items = [Item(1), Item(2), Item(3)]
            kept = items[selected]
            del items[slice(None)]
            gc_collect()
            kept[0].number = 9
            return repr((result, explicit, tuple_copy, explicit_tuple, (1, 2, 3).__getitem__(selected),
                         (1, 2, 3).__getitem__(1), values, copied, [item.number for item in kept],
                         selected == 1, selected != None, bool(slice(0, 1, 0))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_slice_value_allocation_failure_preserves_binding(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from tests.native.allocation_support import arm
        from pyjs.native import gc_collect
        def main() -> int:
            {'gc_collect()' if managed else 'pass'}
            original = slice(2)
            result = original
            arm(1)
            caught = False
            try:
                result = slice(1, 5, 2)
            except MemoryError:
                caught = True
            arm(0)
            {'gc_collect()' if managed else 'pass'}
            if not caught or result is not original:
                return 1
            if slice(1, 5, 2) != slice(1, 5, 2):
                return 2
            return 0
    ''')
    assert ("define ptr @pyjs.gc.try.alloc.described(" in source) is managed
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert result.returncode == 0
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("value", ['"aé\\x00界😀é"', 'b"a\\x00\\xffb"',
                                  '[Item(1), Item(2), Item(3)]', 'tuple([Item(1), Item(2), Item(3)])'])
def test_failed_slice_reads_preserve_binding_and_managed_items(tmp_path, optimize, value):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        class Item:
            def __init__(self, number: int):
                self.number = number
        def main() -> int:
            gc_set_threshold(1)
            original = {value}
            selected = slice(None, None, -1)
            expected = original[selected]
            result = original
            arm(1000)
            result = original[selected]
            stages = 1000 - remaining()
            arm(0)
            if stages < 1 or result != expected:
                return 1
            for stage in range(1, stages + 1):
                result = original
                caught = False
                arm(stage)
                try:
                    result = original[selected]
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or result is not original:
                    return 2
                result = original[selected]
                gc_collect()
                if result != expected:
                    return 3
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
