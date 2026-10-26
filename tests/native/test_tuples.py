import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    FIXED_TUPLE_ASSIGNMENT_CONTRACT,
    REFERENCE_TUPLE_CONTRACT,
    TUPLE_INDEX_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
def test_fixed_tuple_assignment_contract(optimize):
    result = LLVM().assert_matches_python(FIXED_TUPLE_ASSIGNMENT_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, FIXED_TUPLE_ASSIGNMENT_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_reference_tuple_contract(optimize):
    result = LLVM().assert_matches_python(REFERENCE_TUPLE_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, REFERENCE_TUPLE_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_tuple_index_contract(optimize):
    result = LLVM().assert_matches_python(TUPLE_INDEX_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, TUPLE_INDEX_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_tuple_results_in_locals_and_fields(optimize):
    LLVM().assert_matches_python('''
    from pyjs.native import gc_collect

    class Empty:
        def __init__(self):
            fixed = (9, 3)
            self.constructed = tuple()
            self.prefix = fixed[:0]
            self.suffix = fixed[2:]
            self.repeated = fixed * 0

    def main() -> int:
        fixed = (9, 3)
        constructed = tuple()
        prefix = fixed[:0]
        suffix = fixed[2:]
        repeated = fixed * 0
        fields = Empty()
        gc_collect()
        assert constructed == fields.constructed and constructed == ()
        assert prefix == fields.prefix and prefix == ()
        assert suffix == fields.suffix and suffix == ()
        assert repeated == fields.repeated and repeated == ()
        return len(constructed) + len(prefix) + len(suffix) + len(repeated) + len(fixed)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_tuple_dynamic_operations_evaluate_operands(optimize):
    LLVM().assert_matches_python('''
    def operand(events: list[int], value: int) -> int:
        events.append(value)
        return value

    def empty(events: list[int]) -> tuple[()]:
        events.append(99)
        return ()

    def forward_view(count: int) -> tuple[int, ...]:
        return () * count

    def reflected_view(count: int) -> tuple[int, ...]:
        return count * ()

    def sliced_view(step: int) -> tuple[int, ...]:
        return ()[::step]

    def main() -> int:
        events: list[int] = []
        for count in [-3, 0, 2]:
            assert forward_view(count) == ()
            assert reflected_view(count) == ()
            forward = empty(events) * operand(events, count)
            reflected = operand(events, count) * empty(events)
            assert forward == reflected and forward == ()
            assert events == [99, count, count, 99]
            events.clear()
            try:
                sliced = empty(events)[operand(events, -5):operand(events, 7):operand(events, count)]
                assert count != 0
                assert sliced == ()
            except ValueError as error:
                assert count == 0
                assert str(error) == "slice step cannot be zero"
            try:
                assert sliced_view(count) == ()
                assert count != 0
            except ValueError:
                assert count == 0
            assert events == [99, -5, 7, count]
            events.clear()
        flag = False
        try:
            ()[::flag]
        except ValueError:
            pass
        else:
            raise AssertionError("missing bool stride check")
        assert ()[operand(events, 1):] == ()
        assert events == [1]
        return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_construction_slicing_and_views(optimize):
    LLVM().assert_matches_python('''
    from pyjs.native import gc_collect, gc_set_threshold

    def view(value: tuple[int, ...]) -> tuple[int, ...]:
        return value

    def main() -> str:
        gc_set_threshold(1)
        fixed = (9, 3, 4)
        variable = view(fixed)
        assert variable is fixed
        assert tuple(variable) is variable
        assert tuple(fixed) is fixed
        assert tuple([9, 3, 4]) == fixed
        assert tuple(iter([9, 3, 4])) == variable
        assert tuple(range(3)) == (0, 1, 2)
        assert tuple("aé😀") == ("a", "é", "😀")
        assert tuple(b"a\\x00\\xff") == (97, 0, 255)
        assert tuple({"a": 2, "b": 3}.values()) == (2, 3)
        parts = "aéb".partition("é")
        assert view((len(parts[0]), len(parts[1]), len(parts[2]))) == (1, 1, 1)
        assert parts[::-1] == ("b", "é", "a")
        assert b"a:b".rpartition(b":")[1:] == (b":", b"b")
        assert tuple() == ()
        empty: list[int] = []
        assert tuple(empty) == ()
        assert fixed == variable and variable == fixed
        assert variable != (9, 3)
        assert variable[::-1] == (4, 3, 9)
        assert fixed[1:] == (3, 4)
        assert fixed[:] is fixed
        assert variable[-50:50:1] is variable
        assert fixed * 1 is fixed
        assert fixed[True] == 3
        assert fixed[False:True] == (9,)
        assert (fixed * 2)[3:] == variable
        assert len(fixed * 0) == 0
        assert not any(((),))
        try:
            variable[50]
        except IndexError as error:
            assert str(error) == "tuple index out of range"
        else:
            raise AssertionError("missing bounds check")
        step = 0
        try:
            variable[::step]
        except ValueError as error:
            assert str(error) == "slice step cannot be zero"
        else:
            raise AssertionError("missing stride check")
        gc_collect()
        return str(sum(variable)) + str(variable[-1]) + str(variable.count(3))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_rows_and_heterogeneous_payloads(optimize):
    LLVM().assert_matches_python('''
    from pyjs import int8, int64
    from pyjs.native import gc_collect, gc_set_threshold

    def main() -> str:
        gc_set_threshold(1)
        row = (True, False, 9, "text", 1.5)
        copied = tuple(row)
        assert copied is row
        assert copied[0] and not copied[1]
        assert copied[2] == 9 and copied[-1] == 1.5
        assert copied[::-1] == (1.5, "text", 9, False, True)
        assert copied[2:4] == (9, "text")
        assert copied[:] is copied
        assert copied * 1 is copied
        assert copied * 0 == ()
        assert (copied * 2)[5:] == copied
        result = copied[3]
        for index, value in enumerate(["a", "b"]):
            gc_collect()
            result += str(index) + value
        rows = list(zip([True, False], ["c", "d"], [3, 4]))
        gc_collect()
        for flag, text, number in rows:
            result += str(flag) + text + str(number)
        assert next(iter({"a": 3}.items())) == ("a", 3)
        represented = tuple((int8(127), int64(40)))
        assert represented[-2] + int8(1) == int8(-128)
        assert represented[-1] + int64(2) == int64(42)
        return result
    ''', optimize=optimize)


@pytest.mark.parametrize("annotation, values", [
    ("tuple[int, ...]", (9, 3, 4)),
    ("tuple[int, ...]", ()),
    ("tuple[int, int, int]", (9, 3, 4)),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_library_inputs(annotation, values, optimize, tmp_path):
    LLVM().assert_library_matches_python(f'''
    def main(values: {annotation}) -> str:
        return str(len(values)) + ":" + str(sum(values))
    ''', values, directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_host_tuples_and_retained_mutable_items(optimize, tmp_path):
    LLVM().assert_library_matches_python('''
    from pyjs.native import gc_collect

    def view(values: tuple[list[int], ...]) -> tuple[list[int], ...]:
        return values

    def main(rows: tuple[tuple[int, ...], ...]) -> str:
        values = ([1], [2])
        alias = view(values)
        repeated = values * 2
        selected = repeated[1:]
        selected[1].append(7)
        gc_collect()
        assert alias is values
        assert alias[0] is selected[1]
        assert alias[0] == [1, 7]
        return str(sum(rows[0])) + ":" + str(len(rows[1]))
    ''', ((3, 4), ()), directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("annotation", ["tuple[int, ...]", "tuple[int, int]"])
def test_tuple_views_reject_incompatible_item_widths(annotation):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
        def view(values: {annotation}) -> int:
            return sum(values)

        def main() -> int:
            flags = (True, False)
            return view(flags)
        ''')


@pytest.mark.parametrize("expression", ["row[::step]", "row * step", "row * 9223372036854775807"])
def test_dynamic_heterogeneous_tuple_shapes_have_a_diagnostic(expression):
    with pytest.raises(LLVMUnsupported, match="heterogeneous tuple"):
        transpile_llvm(f'''
        def main() -> int:
            row = (1, "text")
            step = 2
            return len({expression})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_repetition_crosses_the_fixed_tuple_limit_without_changing_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def repeated(values: tuple[str, str], count: int) -> tuple[str, ...]:
    return count * values
def main() -> str:
    gc_set_threshold(1)
    values = ("ship", "master")
    output: list[str] = []
    for count in (-2, 0, 1, 3):
        result = repeated(values, count)
        gc_collect()
        output.append(str((result, result is values)))
    fixed = (1, 2) * 128
    runtime = (1, 2) * 129
    output.append(str((len(fixed), len(runtime), sum(runtime))))
    output.append(str(runtime[-4:]))
    return "|".join(output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_tuple_repetition_converts_index_once_even_at_max_count(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
class Count:
    def __init__(self, value: int):
        self.value = value
        self.calls = 0
    def __index__(self) -> int:
        self.calls += 1
        if self.value == 0:
            raise ValueError("bad count")
        return self.value
def main() -> str:
    empty = ()
    count = Count(9223372036854775807)
    left = empty * count
    right = count * empty
    invalid = Count(0)
    small = Count(2)
    repeated = (1, 2) * small
    caught = False
    try:
        empty * invalid
    except ValueError:
        caught = True
    return str((left, right, left is empty, right is empty,
                count.calls, invalid.calls, caught, repeated, small.calls))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
