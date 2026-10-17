from pyjs.testing.helpers import at
from tests.backend_semantics import TUPLE_INDEX_CONTRACT

from .helpers import assert_semantics


def test_shared_tuple_index_contract():
    assert_semantics(TUPLE_INDEX_CONTRACT.print_source + "\nmain()\n")


def test_empty_tuple_results_in_locals_and_fields():
    assert_semantics('''
    from pyjs import js

    @js
    class Empty:
        def __init__(self):
            fixed = (9, 3)
            self.constructed = tuple()
            self.sliced = fixed[:0]
            self.repeated = fixed * 0

    fixed = (9, 3)
    constructed = tuple()
    sliced = fixed[2:]
    repeated = fixed * 0
    fields = Empty()
    print(len(constructed), len(sliced), len(repeated))
    print(fields.constructed == (), fields.sliced == (), fields.repeated == ())
    step = -2
    dynamic = ()[::step]
    print(len(dynamic), () * step == (), step * () == ())
    step = 0
    try:
        ()[::step]
    except ValueError:
        print("zero step")
    ''')


def test_tuple_constructors_and_signed_indexes_preserve_types():
    assert_semantics('''
    from pyjs import int8, int64, js

    @js
    def take_text(value: str) -> str:
        return value.upper()

    values = (7, "text")
    copied = tuple(values)
    print(take_text(copied[-1]), take_text(copied[+1]))
    print(take_text(copied.__getitem__(-1)))
    print(tuple(range(3)) == (0, 1, 2), len(tuple()))
    represented = (int8(127), int64(40))
    preserved = tuple(represented)
    print(preserved[-2] + int8(1), preserved[-1] + int64(2))
    print(preserved.__getitem__(-2) + int8(1), preserved.__getitem__(-1) + int64(2))
    ''')
    at('''
    def main():
        row = (7, "text")
        last = row[-1]
        first = row[+0]
        explicit = row.__getitem__(0)
    ''', '''
    def main() -> None:
        row: tuple[int, str] = (7, 'text')
        last: str = $get_tuple_item(row, -1)
        first: int = $get_tuple_item(row, +0)
        explicit: int = $get_tuple_item(row, 0)
    ''', '''
    import { get_tuple_item as $get_tuple_item } from './pyjs.python.js';

    export function main() {
        var row = [7, 'text'];
        var last = $get_tuple_item(row, -1);
        var first = $get_tuple_item(row, +0);
        var explicit = $get_tuple_item(row, 0);
    }
    ''')


def test_tuple_literals_are_values():
    assert_semantics(
        """\
        values = (1, 2)
        nested = ((1, 2), (3, 4))
        print(len(values))
        print(values[0], values[1])
        print(nested[1][0])
        print(values[-1])
        print(values == (1, 2))
        print(values != (1, 3))
        print(values == [1, 2])
        """
    )


def test_tuple_literals_emit_javascript_arrays():
    at(
        """\
        def main():
            values = (1, 2)
            nested = ((1, 2), (3, 4))
        """,
        """
        def main() -> None:
            values: tuple[int, int] = (1, 2)
            nested: tuple[tuple[int, int], tuple[int, int]] = ((1, 2), (3, 4))
        """,
        """
        export function main() {
            var values = [1, 2];
            var nested = [[1, 2], [3, 4]];
        }
        """,
    )


def test_empty_single_item_and_sliced_tuples_are_values():
    assert_semantics(
        """\
        empty = ()
        single = (1,)
        values = (0, 1, 2, 3, 4)
        print(len(empty), len(single), single[0])
        print(repr(values[1:4]))
        print(repr(values[::-2]))
        """
    )


def test_empty_single_item_and_sliced_tuples_emit_arrays():
    at(
        """\
        def main():
            empty = ()
            single = (1,)
            values = (0, "one", 2.0)
            selected = values[1:]
            reversed_values = values[::-1]
        """,
        """\
        def main() -> None:
            empty: tuple__ = ()
            single: tuple[int] = (1,)
            values: tuple[int, str, float] = (0, 'one', 2.0)
            selected: tuple[str, float] = values.[tuple__int_str_float]__slice__!(1, None, None)
            reversed_values: tuple[float, str, int] = values.[tuple__int_str_float]__slice__!(None, None, -1)
        """,
        """\
        import { slice_list as $slice_list } from './pyjs.python.js';

        export function main() {
            var empty = [];
            var single = [1];
            var values = [0, 'one', 2.0];
            var selected = values.slice(1);
            var reversed_values = $slice_list(values,null,null,-1);
        }
        """,
    )
