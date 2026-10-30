from pyjs.testing.helpers import ad, at

from .helpers import assert_semantics


def test_reused_comprehension_target_has_one_local_cell():
    assert_semantics('''
        from typing import Callable
        from pyjs import js
        @js
        def callbacks() -> list[Callable[[], int]]:
            return [lambda: value for value in [1, 2] for value in [value + 10]]
        value = 100
        for callback in callbacks():
            print(callback())
        print(value)
        values = (value for value in [1, 2] for value in [value + 10])
        for item in values:
            print(item)
        print(value)
    ''')


def test_reused_comprehension_target_analysis_and_javascript():
    at('''
        def main():
            values: list[int | None] = [None, 1]
            return [value for value in values if value is not None for value in [None, value]]
    ''', '''
        def main() -> list[None | int]:
            values: list[int | None] = [None, 1]
            return [value for value in values if value.[object]__is_not__!(None) for value in [None, value]]
    ''', '''
        export function main() {
            var values = [null, 1];
            return (($iterable)=>{const $result=[];let value;for(value of $iterable){if(value != null){for(value of [null, value]){$result.push(value);}}}return $result;})(values);
        }
    ''')


def test_list_comprehensions_materialize_iterables_and_apply_filters():
    assert_semantics(
        """\
        values = [value * 2 for value in range(6) if value % 2 == 0]
        print(len(values))
        for value in values:
            print(value)
        """
    )


def test_list_comprehension_emits_array_filter_and_map():
    at(
        """\
        def main():
            values = [value * 2 for value in range(6) if value % 2 == 0]
        """,
        """
        def main() -> None:
            values: list[int] = [value.[int]__mul__!(2) for value in range(6) if value.[int]__mod__!(2).[int]__eq__!(0)]
        """,
        """
        export function main() {
            var values = Array.from(((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)((function*(start,stop,step){for(let i=start;step>0?i<stop:i>stop;i+=step)yield i})(0,6,1))).filter(value => ((left,right)=>{if(right===0)throw new Error('division by zero');return ((left%right)+right)%right;})(value,2) == 0).map(value => value * 2);
        }
        """,
    )


def test_enumerate_and_zip_match_python_for_general_iterables():
    assert_semantics(
        """\
        names = ["Ada", "Grace", "Linus"]
        scores = (7, 9)
        for index, name in enumerate(names):
            print(index, name)
        for name, score in zip(names, scores):
            print(name, score)
        """
    )


def test_zip_strict_matches_python_for_equal_and_unequal_iterables():
    assert_semantics(
        """\
        for left, right in zip([1, 2], [3, 4], strict=True):
            print(left, right)

        try:
            print(list(zip([1, 2], [3], [4, 5], strict=True)))
        except ValueError as error:
            print(str(error))
        try:
            print(list(zip([1], [2, 3], [4], strict=True)))
        except ValueError as error:
            print(str(error))
        try:
            print(list(zip([1], [2], [3, 4], strict=True)))
        except ValueError as error:
            print(str(error))
        try:
            print(list(zip([], [1], [2], strict=True)))
        except ValueError as error:
            print(str(error))

        strict = len([1]) > 0
        try:
            print(list(zip([1], [2, 3], strict=strict)))
        except ValueError as error:
            print(str(error))
        """
    )


def test_zip_strict_has_explicit_lowering_without_changing_the_default():
    at(
        """\
        def main(strict: bool):
            ordinary = list(zip([1], [2]))
            checked = list(zip([1], [2], strict=strict))
        """,
        """
        def main(strict: bool) -> None:
            ordinary: list[tuple[int, int]] = list__tuple__int_int(zip([1], [2]))
            checked: list[tuple[int, int]] = list__tuple__int_int(zip([1], [2], strict=strict))
        """,
        """
        export function main(strict) {
            var ordinary = Array.from((function*(iterables){const iterators=iterables.map(value=>value[Symbol.iterator]());while(iterators.length){const values=iterators.map(iterator=>iterator.next());if(values.some(value=>value.done))return;yield values.map(value=>value.value)}})([[1], [2]]));
            var checked = Array.from((function*(iterables,strict){const iterators=iterables.map(value=>value[Symbol.iterator]());while(iterators.length){const values=[];const first=iterators[0].next();if(first.done){if(!strict)return;for(let index=1;index<iterators.length;index++){if(!iterators[index].next().done){const previous=index===1?'argument 1':`arguments 1-${index}`;throw new RangeError(`zip() argument ${index+1} is longer than ${previous}`);}}return;}values.push(first.value);for(let index=1;index<iterators.length;index++){const result=iterators[index].next();if(result.done){if(!strict)return;const previous=index===1?'argument 1':`arguments 1-${index}`;throw new RangeError(`zip() argument ${index+1} is shorter than ${previous}`);}values.push(result.value);}yield values;}})([[1], [2]],strict));
        }
        """,
    )


def test_map_and_filter_are_lazy_and_preserve_python_iterable_semantics():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Choice:
            def __init__(self, rank: int):
                self.rank = rank

            def __bool__(self) -> bool:
                return self.rank > 0

        @js
        def double(value: int) -> int:
            print("mapped", value)
            return value * 2

        mapped = map(double, [1, 2])
        print("ready")
        print(next(mapped))
        print(next(mapped))

        for value in filter(lambda value: value > 1, [1, 2, 3]):
            print("selected", value)
        for choice in filter(None, [Choice(0), Choice(2)]):
            print("choice", choice.rank)
        for key in map(lambda key: key.upper(), {"first": 1, "second": 2}):
            print(key)
        for key in filter(None, {"": 0, "present": 1}):
            print(key)
        """
    )


def test_map_accepts_multiple_iterables_and_stops_at_the_shortest():
    assert_semantics(
        """\
        labels = list(map(
            lambda number, label: label * number,
            [1, 2, 3],
            ["a", "b"],
        ))
        print(",".join(labels))
        totals = list(map(
            lambda first, second, third: first + second + third,
            [1, 2],
            [10],
            [100, 200],
        ))
        print(totals[0], len(totals))
        """
    )


def test_map_and_filter_infer_lambda_types_and_emit_lazy_iterators():
    at(
        """\
        def main():
            doubled = list(map(lambda value: value * 2, [1, 2]))
            selected = list(filter(lambda value: value > 2, doubled))
        """,
        """
        def main() -> None:
            doubled: list[int] = list__int(map(lambda value: value.[int]__mul__!(2), [1, 2]))
            selected: list[int] = list__int(filter(lambda value: value.[int]__gt__!(2), doubled))
        """,
        """
        import { truthy as $truthy } from './pyjs.python.js';

        export function main() {
            var doubled = Array.from((function*($function,values){for(const value of values)yield $function(value)})((value) => value * 2,[1, 2]));
            var selected = Array.from((function*($function,values){for(const value of values)if($function===null?$truthy(value):$function(value))yield value;})((value) => value > 2,doubled));
        }
        """,
    )


def test_enumerate_and_zip_infer_each_tuple_item_type():
    at(
        """\
        def main():
            for index, name in enumerate(["a", "b"], 2):
                print(index, name)
            for name, score in zip(["a"], [3]):
                print(name, score)
        """,
        """
        def main() -> None:
            for index: int, name: str in enumerate(['a', 'b'], 2):
                print(index, name)
            for name: str, score: int in zip(['a'], [3]):
                print(name, score)
        """,
        """
        export function main() {
            for (var [index, name] of (function*(values,start){let index=start;for(const value of values)yield [index++,value]})(['a', 'b'],2)) {
                console.log(index, name);
            }
            for (var [name, score] of (function*(iterables){const iterators=iterables.map(value=>value[Symbol.iterator]());while(iterators.length){const values=iterators.map(iterator=>iterator.next());if(values.some(value=>value.done))return;yield values.map(value=>value.value)}})([['a'], [3]])) {
                console.log(name, score);
            }
        }
        """,
    )


def test_structural_iterables_work_with_loops_and_iterable_consumers():
    assert_semantics(
        """\
        from collections.abc import Iterable, Iterator

        from pyjs import js

        @js
        class Numbers:
            def __init__(self):
                self.values = [2, 4]

            def __iter__(self) -> Iterator[int]:
                return iter(self.values)

        @js
        def total(values: Iterable[int]) -> int:
            result = 0
            for value in values:
                result += value
            return result

        numbers = Numbers()
        for index, value in enumerate(numbers, 1):
            print(index, value)
        iterator = numbers.__iter__()
        print(next(iterator))
        print(total(numbers))
        print("-".join(str(value) for value in numbers))
        """
    )


def test_structural_iterable_emits_symbol_iterator_and_retains_method():
    at(
        """\
        from collections.abc import Iterator

        @js
        class Numbers:
            def __init__(self):
                self.values = [1, 2]

            def __iter__(self) -> Iterator[int]:
                return iter(self.values)

        def main():
            numbers = Numbers()
            for index, value in enumerate(numbers):
                print(index, value)
        """,
        """
        class Numbers:

            def __init__() -> None:
                self.values = [1, 2]

            def __iter__() -> Iterator[int]:
                return iter(self.values)

        def main() -> None:
            numbers: Numbers = Numbers()
            for index: int, value: int in enumerate(numbers):
                print(index, value)
        """,
        """
        export class Numbers {

            constructor() {
                this.values = [1, 2];
            }

            [Symbol.iterator]() {
                return this.values[Symbol.iterator]();
            }
        }

        export function main() {
            var numbers = new Numbers();
            for (var [index, value] of (function*(values,start){let index=start;for(const value of values)yield [index++,value]})(numbers,0)) {
                console.log(index, value);
            }
        }
        """,
    )


def test_nodelist_is_a_structural_iterable():
    at(
        """\
        from pyjs.web.dom import document

        def main():
            result: list[str] = []
            for index, node in enumerate(document.querySelectorAll("div")):
                result.append(str(index) + node.textContent)
        """,
        """
        def main() -> None:
            result: list[str] = []
            for index: int, node: Element in enumerate(document.[Document]querySelectorAll('div')):
                result.[list__str]append!(index.[int]__str__!().[str]__add__!(node.textContent))
        """,
        """
        export function main() {
            var result = [];
            for (var [index, node] of (function*(values,start){let index=start;for(const value of values)yield [index++,value]})(document.querySelectorAll('div')[Symbol.iterator](),0)) {
                (result.push(String(index) + node.textContent), null);
            }
        }
        """,
    )


def test_common_iterable_builtins_match_python_semantics():
    assert_semantics(
        """\
        from typing import TypedDict

        from pyjs import js

        class Record(TypedDict):
            second: int
            first: int

        @js
        class Choice:
            def __init__(self, label: str, rank: int):
                self.label = label
                self.rank = rank

            def __bool__(self) -> bool:
                return self.rank > 0

        @js
        class SizedChoice:
            def __init__(self, size: int):
                self.size = size

            def __len__(self) -> int:
                return self.size

        @js
        def choice_key(choice: Choice) -> tuple[int, str]:
            return (choice.rank, choice.label)

        @js
        def rank_key(choice: Choice) -> int:
            return choice.rank

        @js
        def empty_mapping() -> dict[str, int]:
            return {str(value): value for value in range(0)}

        @js
        def empty_values() -> list[int]:
            return [value for value in range(0)]

        choices = [Choice("later", 2), Choice("first", 1), Choice("last", 2)]
        for choice in sorted(choices, key=choice_key):
            print(choice.label)
        for choice in sorted(choices, key=rank_key, reverse=True):
            print(choice.label)
        for choice in sorted(choices, key=lambda item: (item.rank, item.label)):
            print(choice.label)
        copied_choices = list(choices)
        copied_choices.sort(key=lambda item: (item.rank, item.label))
        print(copied_choices[0].label)
        print(min(choices, key=lambda item: item.rank).label)
        print(max(choices, key=lambda item: item.rank).label)

        pairs = zip([2, 1], [(0.0, 3.0), (0.0, 1.0)])
        ordered_pairs = sorted(pairs, key=lambda pair: pair[1][1])
        print(ordered_pairs[0][0], ordered_pairs[1][0])

        for rank, label in sorted([(2, "later"), (1, "first"), (2, "last")]):
            print(rank, label)

        for value in sorted({10, 2, 1}):
            print(value)
        for value in sorted(["😀", "\ue000"]):
            print(value)
        for value in sorted([2, 1], key=None):
            print(value)
        plain = [2, 1]
        plain.sort(key=None)
        print(plain[0], plain[1])
        for key in sorted({"second": 2, "first": 1}):
            print(key)
        for key in reversed({"first": 1, "second": 2}):
            print(key)
        record = Record(second=2, first=1)
        for key in sorted(record):
            print(key)
        for key in reversed(record):
            print(key)
        print(all(record))
        for character in reversed("A😀B"):
            print(character)

        print(all([Choice("yes", 1), Choice("no", 0)]))
        print(any([Choice("no", 0), Choice("yes", 1)]))
        print(all([SizedChoice(1), SizedChoice(0)]))
        print(any([SizedChoice(0), SizedChoice(2)]))
        print(all([]), any([]))
        print(all({"": 1}), any({"": 1, "present": 2}))
        print(all([float("nan")]))
        print(any([empty_mapping(), empty_values()]))
        numbers = {3: "three", 1: "one", 2: "two"}
        for index, key in enumerate(numbers, 5):
            print(index, key)
        for left, right in zip(numbers, {9: "nine", 8: "eight"}):
            print(left, right)
        print(sum(numbers), min(numbers), max(numbers))
        print("".join([key for key in {"a": 1, "b": 2}]))
        for key in (key for key in {"c": 3, "d": 4}):
            print(key)
        try:
            all([SizedChoice(-1)])
        except Exception as error:
            print(str(error))
        """
    )


def test_list_sort_mutates_in_place_and_matches_python_ordering():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Choice:
            def __init__(self, label: str, rank: int):
                self.label = label
                self.rank = rank

        @js
        def rank_key(choice: Choice) -> int:
            return choice.rank

        choices = [Choice("later", 2), Choice("first", 1), Choice("last", 2)]
        result = choices.sort(key=rank_key, reverse=True)
        print(result is None)
        for choice in choices:
            print(choice.label)

        numbers = [10, 2, 1]
        numbers.sort()
        for number in numbers:
            print(number)

        labels = ["😀", "\ue000"]
        labels.sort()
        for label in labels:
            print(label)

        pairs = [(2, "later"), (1, "first"), (2, "last")]
        pairs.sort()
        for rank, label in pairs:
            print(rank, label)
        """
    )


def test_dictionary_loops_and_comprehensions_iterate_keys():
    at(
        """
        def main():
            mapping = {"a": 1, "b": 2}
            for key in mapping:
                print(key)
            keys = [key for key in mapping]
        """,
        """
        def main() -> None:
            mapping: dict[str, int] = {'a': 1, 'b': 2}
            for key: str in mapping.[dict__str_int]keys():
                print(key)
            keys: list[str] = [key for key in mapping.[dict__str_int]keys()]
        """,
        """
        export function main() {
            var mapping = new Map([['a', 1], ['b', 2]]);
            for (var key of mapping.keys()) {
                console.log(key);
            }
            var keys = Array.from(mapping.keys()).map(key => key);
        }
        """,
    )


def test_dictionary_arguments_preserve_key_iteration_through_iterable_interfaces():
    at(
        """\
        from collections.abc import Iterable

        @js
        def first(values: Iterable[str]) -> str:
            for value in values:
                return value
            return ""

        def main():
            mapping = {"first": 1}
            print(first(mapping))
        """,
        """
        def first(values: Iterable__str) -> str:
            for value: str in values:
                return value
            return ''

        def main() -> None:
            mapping: dict[str, int] = {'first': 1}
            print(first(mapping))
        """,
        """
        export function first(values) {
            for (var value of ((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)(values)) {
                return value;
            }
            return '';
        }

        export function main() {
            var mapping = new Map([['first', 1]]);
            console.log(first(mapping));
        }
        """,
    )


def test_iter_and_next_preserve_iterator_state_and_defaults():
    assert_semantics(
        """\
        mapping_iterator = iter({"first": 1})
        print(next(mapping_iterator))
        print(next(mapping_iterator, "done"))

        values = iter([1, 2, 3])
        print(next(values))
        for value in values:
            print(value)

        generated = (value * 2 for value in range(3))
        print(next(generated))
        print(next(generated))
        print(next(generated))
        print(next(generated, -1))
        """
    )


def test_iterator_builtins_can_be_passed_directly_to_next():
    assert_semantics(
        """\
        index, label = next(enumerate(["first"]))
        print(index, label)
        number, name = next(zip([1], ["one"]))
        print(number, name)
        print(next(reversed([1, 2])))
        """
    )


def test_iter_and_next_preserve_item_and_default_types():
    at(
        """
        def main():
            values = iter([1, 2])
            first = next(values)
            optional = next(values, None)
        """,
        """
        def main() -> None:
            values: Iterator[int] = iter([1, 2])
            first: int = next(values)
            optional: int | None = next(values, None)
        """,
        """
        import { raise_stop_iteration as $raise_stop_iteration } from './pyjs.python.js';

        export function main() {
            var values = [1, 2][Symbol.iterator]();
            var first = ((result)=>{if(result.done){return $raise_stop_iteration();}return result.value;})(values.next());
            var optional = ((result)=>{if(result.done){return null;}return result.value;})(values.next());
        }
        """,
    )


def test_sequence_constructors_materialize_typed_iterables_independently():
    assert_semantics(
        """\
        from typing import TypedDict

        class Record(TypedDict):
            name: str
            count: int

        original = [1, 2]
        copied = list(original)
        copied.append(3)
        print(len(original), len(copied))

        for value in list(range(3)):
            print(value)
        for value in list(reversed((1, 2, 3))):
            print(value)
        for value in list("A😀"):
            print(value)
        for value in list({"first": 1, "second": 2}):
            print(value)
        for value in tuple(range(3)):
            print(value)
        for value in tuple({"first": 1, "second": 2}):
            print(value)

        original_mapping = {"first": 1}
        copied_mapping = dict(original_mapping)
        copied_mapping["second"] = 2
        print(len(original_mapping), len(copied_mapping))
        generated_mapping = dict((str(value), value) for value in range(3))
        for key, value in generated_mapping.items():
            print(key, value)
        record_mapping = dict(Record(name="test", count=2))
        print(record_mapping["name"], record_mapping["count"])
        """
    )


def test_collection_constructors_infer_items_and_empty_context():
    at(
        """
        def main():
            values = list(range(3))
            keys = list({"a": 1})
            empty: list[str] = list()
            tuple_values = tuple(range(3))
            tuple_keys = tuple({"a": 1})
            copied = dict({"a": 1})
            pairs = dict((str(value), value) for value in range(2))
            empty_mapping: dict[str, int] = dict()
        """,
        """
        def main() -> None:
            values: list[int] = list__int(range(3))
            keys: list[str] = list__str({'a': 1})
            empty: list[str] = list__str()
            tuple_values: tuple[int, ...] = tuple__int__variadic(range(3))
            tuple_keys: tuple[str, ...] = tuple__str__variadic({'a': 1})
            copied: dict[str, int] = dict__str_int({'a': 1})
            pairs: dict[str, int] = dict__str_int(((value.[int]__str__!(), value) for value in range(2)))
            empty_mapping: dict[str, int] = dict__str_int()
        """,
        """
        export function main() {
            var values = Array.from(((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)((function*(start,stop,step){for(let i=start;step>0?i<stop:i>stop;i+=step)yield i})(0,3,1)));
            var keys = Array.from(new Map([['a', 1]]).keys());
            var empty = [];
            var tuple_values = Array.from(((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)((function*(start,stop,step){for(let i=start;step>0?i<stop:i>stop;i+=step)yield i})(0,3,1)));
            var tuple_keys = Array.from(new Map([['a', 1]]).keys());
            var copied = new Map(new Map([['a', 1]]));
            var pairs = new Map((($iterator)=>(function*(){for(const value of $iterator){yield [String(value), value];}}).call(this))((((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)((function*(start,stop,step){for(let i=start;step>0?i<stop:i>stop;i+=step)yield i})(0,2,1)))[Symbol.iterator]()));
            var empty_mapping = new Map();
        }
        """,
    )


def test_sorted_key_lambda_infers_the_iterable_item_type():
    at(
        """
        def main():
            ids = [2, 1]
            points = [(0.0, 3.0), (0.0, 1.0)]
            axis = 1
            pairs = sorted(zip(ids, points), key=lambda pair: pair[1][axis])
            print(pairs[0][0])
        """,
        """
        def main() -> None:
            ids: list[int] = [2, 1]
            points: list[tuple[float, float]] = [(0.0, 3.0), (0.0, 1.0)]
            axis: int = 1
            pairs: list[tuple[int, tuple[float, float]]] = sorted(zip(ids, points), key=lambda pair: $get_tuple_item($get_tuple_item(pair, 1), axis))
            print($get_tuple_item($get_list_item(pairs, 0), 0))
        """,
        """
        import { sort_values as $sort_values, get_tuple_item as $get_tuple_item, get_list_item as $get_list_item } from './pyjs.python.js';

        export function main() {
            var ids = [2, 1];
            var points = [[0.0, 3.0], [0.0, 1.0]];
            var axis = 1;
            var pairs = $sort_values(Array.from((function*(iterables){const iterators=iterables.map(value=>value[Symbol.iterator]());while(iterators.length){const values=iterators.map(iterator=>iterator.next());if(values.some(value=>value.done))return;yield values.map(value=>value.value)}})([ids, points])),(pair) => $get_tuple_item($get_tuple_item(pair, 1), axis),false);
            console.log($get_tuple_item($get_list_item(pairs, 0), 0));
        }
        """,
    )


def test_sorted_rejects_values_without_portable_ordering():
    ad(
        """\
        def main():
            values = sorted([{"a": 1}, {"b": 2}])
        """,
        """
          File "sorted_dicts.py", line 2
            values = sorted([{"a": 1}, {"b": 2}])
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: sorted() cannot order values of type dict [PYJS2001]
        help: Use numeric, string, or sequence values, or pass a key function that returns those types.
        """,
        filename="sorted_dicts.py",
    )


def test_reversed_rejects_non_reversible_iterables():
    ad(
        """\
        def main():
            values = reversed({1, 2})
        """,
        """
          File "reversed_set.py", line 2
            values = reversed({1, 2})
                     ^^^^^^^^^^^^^^^^
        pyjs.CompilationError: reversed() requires a reversible sequence, got set [PYJS2001]
        help: Use a list, tuple, string, or dictionary.
        """,
        filename="reversed_set.py",
    )


def test_sorted_validates_key_parameter_types():
    ad(
        """\
        from pyjs import js

        @js
        def text_length(value: str) -> int:
            return len(value)

        def main():
            values = sorted([1, 2], key=text_length)
        """,
        """
          File "sorted_key.py", line 8
            values = sorted([1, 2], key=text_length)
                                        ^^^^^^^^^^^
        pyjs.CompilationError: Callable argument 'key' to sorted accepts str, but must accept int [PYJS1104]
        note: sorted_key.py:4:5: callable defined here
        help: Widen the callable parameter annotation to accept every input value.
        """,
        filename="sorted_key.py",
    )


def test_sorted_key_lambda_requires_exactly_one_parameter():
    ad(
        """\
        def main():
            values = sorted([1, 2], key=lambda left, right: left)
        """,
        """
          File "sorted_lambda.py", line 2
            values = sorted([1, 2], key=lambda left, right: left)
                                        ^^^^^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Lambda must declare exactly 1 positional parameter, got 2 [PYJS1104]
        help: Define the lambda with the callable's expected parameters.
        """,
        filename="sorted_lambda.py",
    )


def test_list_sort_rejects_values_without_portable_ordering():
    ad(
        """\
        def main():
            values = [{"a": 1}, {"b": 2}]
            values.sort()
        """,
        """
          File "list_sort_dicts.py", line 3
            values.sort()
            ^^^^^^^^^^^^^
        pyjs.CompilationError: list.sort() cannot order values of type dict [PYJS2001]
        help: Use numeric, string, or sequence values, or pass a key function that returns those types.
        """,
        filename="list_sort_dicts.py",
    )


def test_list_sort_validates_key_parameter_types():
    ad(
        """\
        from pyjs import js

        @js
        def text_length(value: str) -> int:
            return len(value)

        def main():
            values = [1, 2]
            values.sort(key=text_length)
        """,
        """
          File "list_sort_key.py", line 9
            values.sort(key=text_length)
                            ^^^^^^^^^^^
        pyjs.CompilationError: Callable argument 'key' to sort accepts str, but must accept int [PYJS1104]
        note: list_sort_key.py:4:5: callable defined here
        help: Widen the callable parameter annotation to accept every input value.
        """,
        filename="list_sort_key.py",
    )


def test_tuple_targets_and_nested_generators_match_python():
    assert_semantics(
        """\
        pairs = [("a", 1), ("b", 2), ("c", 3)]
        labels = [name + str(score) for name, score in pairs if score > 1]
        products = [
            left * right
            for left in [1, 2, 3]
            if left > 1
            for right in [3, 4]
            if right < 4
        ]
        print(len(labels), len(products))
        for label in labels:
            print(label)
        for product in products:
            print(product)
        """
    )


def test_comprehension_targets_do_not_leak_into_the_outer_scope():
    assert_semantics(
        """\
        value = 100
        values = [value * 2 for value in range(3)]
        print(value, len(values), values[0], values[2])
        """
    )


def test_async_comprehensions_have_a_focused_diagnostic():
    ad(
        """\
        async def main():
            result = [value async for value in values]
        """,
        """
          File "async_comprehension.py", line 2
            result = [value async for value in values]
                                      ^^^^^
        pyjs.CompilationError: asynchronous comprehensions are not supported [PYJS2001]
        help: Use an explicit async loop before building the collection.
        """,
        filename="async_comprehension.py",
    )


def test_complex_list_comprehensions_preserve_types_and_nested_order():
    at(
        """
        def main():
            pairs = [("a", 1), ("b", 2)]
            labels = [name + str(score) for name, score in pairs if score > 1]
            products = [
                left * right
                for left in [1, 2]
                if left > 1
                for right in [3, 4]
                if right < 4
            ]
        """,
        """
        def main() -> None:
            pairs: list[tuple[str, int]] = [('a', 1), ('b', 2)]
            labels: list[str] = [name.[str]__add__!(score.[int]__str__!()) for name, score in pairs if score.[int]__gt__!(1)]
            products: list[int] = [left.[int]__mul__!(right) for left in [1, 2] if left.[int]__gt__!(1) for right in [3, 4] if right.[int]__lt__!(4)]
        """,
        """
        export function main() {
            var pairs = [['a', 1], ['b', 2]];
            var labels = (($iterable)=>{const $result=[];for(const [name, score] of $iterable){if(score > 1){$result.push(name + String(score));}}return $result;})(pairs);
            var products = (($iterable)=>{const $result=[];for(const left of $iterable){if(left > 1){for(const right of [3, 4]){if(right < 4){$result.push(left * right);}}}}return $result;})([1, 2]);
        }
        """,
    )


def test_dict_and_set_comprehensions_match_python():
    assert_semantics(
        """\
        values = {str(value): value * value for value in range(5) if value % 2 == 0}
        latest = {value % 2: value for value in range(5)}
        unique = {value % 3 for value in range(7)}
        print(len(values), values["2"], "1" in values)
        print(len(latest), latest[0], latest[1])
        print(len(unique), 2 in unique, 4 in unique)
        """
    )


def test_comprehensions_contextually_type_empty_nested_collections():
    assert_semantics(
        """\
        adjacency: dict[int, list[int]] = {
            face: [] for face in range(2)
        }
        adjacency[0].append(3)
        print(len(adjacency[0]), adjacency[0][0], len(adjacency[1]))
        """
    )


def test_dict_and_set_comprehensions_preserve_types_and_nested_order():
    at(
        """
        def main():
            pairs = [("a", 1), ("b", 2)]
            modifiers = [("x", 2), ("y", 3)]
            lookup = {
                name + suffix: score * factor
                for name, score in pairs
                if score > 1
                for suffix, factor in modifiers
                if factor > 2
            }
            values = {score * 2 for name, score in pairs if name != "a"}
        """,
        """
        def main() -> None:
            pairs: list[tuple[str, int]] = [('a', 1), ('b', 2)]
            modifiers: list[tuple[str, int]] = [('x', 2), ('y', 3)]
            lookup: dict[str, int] = {name.[str]__add__!(suffix): score.[int]__mul__!(factor) for name, score in pairs if score.[int]__gt__!(1) for suffix, factor in modifiers if factor.[int]__gt__!(2)}
            values: set[int] = {score.[int]__mul__!(2) for name, score in pairs if name.[object]__ne__!('a')}
        """,
        """
        export function main() {
            var pairs = [['a', 1], ['b', 2]];
            var modifiers = [['x', 2], ['y', 3]];
            var lookup = (($iterable)=>{const $result=new Map();for(const [name, score] of $iterable){if(score > 1){for(const [suffix, factor] of modifiers){if(factor > 2){$result.set(name + suffix,score * factor);}}}}return $result;})(pairs);
            var values = (($iterable)=>{const $result=new Set();for(const [name, score] of $iterable){if(name !== 'a'){$result.add(score * 2);}}return $result;})(pairs);
        }
        """,
    )


def test_generator_expressions_are_lazy_and_single_use():
    assert_semantics(
        """\
        values = (value * 2 for value in range(5) if value > 1)
        print(sum(values))
        print(sum(values))
        pairs = ((name, score) for name, score in [("a", 1), ("b", 2)])
        for name, score in pairs:
            print(name, score)
        """
    )


def test_generator_expressions_evaluate_the_outer_iterable_immediately():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def source() -> list[int]:
            print("source")
            return [1, 2]

        print("before")
        values = (value * 2 for value in source())
        print("after")
        for value in values:
            print(value)
        """
    )


def test_nested_generator_expressions_preserve_item_types_and_order():
    at(
        """
        def main():
            pairs = [("a", 1), ("b", 2)]
            values = (
                name + suffix
                for name, score in pairs
                if score > 1
                for suffix in ["x", "y"]
                if suffix != "x"
            )
            for value in values:
                print(value)
        """,
        """
        def main() -> None:
            pairs: list[tuple[str, int]] = [('a', 1), ('b', 2)]
            values: Iterator[str] = (name.[str]__add__!(suffix) for name, score in pairs if score.[int]__gt__!(1) for suffix in ['x', 'y'] if suffix.[object]__ne__!('x'))
            for value: str in values:
                print(value)
        """,
        """
        export function main() {
            var pairs = [['a', 1], ['b', 2]];
            var values = (($iterator)=>(function*(){for(const [name, score] of $iterator){if(score > 1){for(const suffix of ['x', 'y']){if(suffix !== 'x'){yield name + suffix;}}}}}).call(this))((pairs)[Symbol.iterator]());
            for (var value of values) {
                console.log(value);
            }
        }
        """,
    )


def test_starred_comprehension_target_has_a_focused_diagnostic():
    ad(
        """
        def main():
            values = [(1, 2, 3)]
            result = [head for head, *tail in values]
        """,
        """
          File "starred_comprehension.py", line 4
            result = [head for head, *tail in values]
                                     ^^^^^
        pyjs.CompilationError: starred comprehension targets are not supported [PYJS2001]
        help: Use an explicit loop to collect the remaining values.
        """,
        filename="starred_comprehension.py",
    )
