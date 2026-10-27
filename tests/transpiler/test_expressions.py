import pytest

from pyjs.testing.helpers import (
    ad,
    assert_analysis,
    assert_module_analysis_transpile,
    assert_transpile,
    at,
    diagnostic_text,
)


def test_set_literal_context_preserves_the_javascript_constructor_and_calls():
    at(
        '''
        def main() -> int:
            values: set[int | str] = {1}
            values.add('word')
            return len(values)
        ''',
        '''
        def main() -> int:
            values: set[int | str] = {1}
            values.[set__intUstr]add!('word')
            return values.[set__intUstr]__len__!()
        ''',
        '''
        export function main() {
            var values = new Set([1]);
            (values.add('word'), null);
            return values.size;
        }
        ''',
    )


def test_f_string_receiver_groups_the_complete_javascript_concatenation():
    at(
        '''
        def main(name: str, category: str) -> str:
            return f"{name} {category}".lower()
        ''',
        '''
        def main(name: str, category: str) -> str:
            return f'{name.[str]__str__!()} {category.[str]__str__!()}'.[str]lower!()
        ''',
        '''
        export function main(name, category) {
            return (name+' '+category).toLowerCase();
        }
        ''',
    )



def test_date_now_uses_the_native_javascript_builtin():
    at(
        """
        from pyjs.javascript import Date

        def main():
            timestamp = Date.now()
        """,
        """
        def main() -> None:
            timestamp: int = Date.[Date]now()
        """,
        """
        export function main() {
            var timestamp = Date.now();
        }
        """,
    )


def test_membership_uses_contains_without_requiring_iteration():
    at(
        """
        from pyjs import js

        @js
        class Bag:
            def __init__(self, limit: int):
                self.limit = limit

            def __contains__(self, item: int) -> bool:
                return 0 <= item < self.limit

        @js
        def main():
            bag = Bag(5)
            print(3 in bag)
            print(9 not in bag)
        """,
        """
        class Bag:

            def __init__(limit: int) -> None:
                self.limit = limit

            def __contains__(item: int) -> bool:
                return $chained_compare(0, item, self.limit; $compare0.[int]__le__!($compare1) and $compare1.[int]__lt__!($compare2))

        def main() -> None:
            bag: Bag = Bag(5)
            print(bag.[Bag]__contains__(3))
            print(not bag.[Bag]__contains__(9))
        """,
        """
        export class Bag {

            constructor(limit) {
                this.limit = limit;
            }

            __contains__(item) {
                return (($compare0) => (($compare1) => $compare0 <= $compare1 && (($compare2) => $compare1 < $compare2)(this.limit))(item))(0);
            }
        }

        export function main() {
            var bag = new Bag(5);
            console.log((bag.__contains__(3) ? 'True' : 'False'));
            console.log((!bag.__contains__(9) ? 'True' : 'False'));
        }
        """,
    )


def test_date_construction_and_accessors_use_the_native_javascript_builtin():
    at(
        """
        from pyjs.javascript import Date

        def main():
            current = Date()
            epoch = Date(0)
            release = Date("2026-08-30T00:00:00")
            iso = epoch.toISOString()
            localized = release.toLocaleDateString()
            month = current.getMonth()
            day = current.getDate()
            year = current.getFullYear()
            hour = current.getHours()
            minute = current.getMinutes()
        """,
        """
        def main() -> None:
            current: Date = Date()
            epoch: Date = Date(0)
            release: Date = Date('2026-08-30T00:00:00')
            iso: str = epoch.[Date]toISOString()
            localized: str = release.[Date]toLocaleDateString()
            month: int = current.[Date]getMonth()
            day: int = current.[Date]getDate()
            year: int = current.[Date]getFullYear()
            hour: int = current.[Date]getHours()
            minute: int = current.[Date]getMinutes()
        """,
        """
        export function main() {
            var current = new Date();
            var epoch = new Date(0);
            var release = new Date('2026-08-30T00:00:00');
            var iso = epoch.toISOString();
            var localized = release.toLocaleDateString();
            var month = current.getMonth();
            var day = current.getDate();
            var year = current.getFullYear();
            var hour = current.getHours();
            var minute = current.getMinutes();
        }
        """,
    )


def test_dictionary_unpacking_preserves_ordered_overwrites():
    at(
        """
        def main():
            left = {"a": 1, "b": 2}
            values = {**left, "b": 3, "c": 4}
        """,
        """
        def main() -> None:
            left: dict[str, int] = {'a': 1, 'b': 2}
            values: dict[str, int] = {**left, 'b': 3, 'c': 4}
        """,
        """
        export function main() {
            var left = new Map([['a', 1], ['b', 2]]);
            var values = new Map([...left, ['b', 3], ['c', 4]]);
        }
        """,
    )


def test_dictionary_unpacking_rejects_non_dictionary_values():
    ad(
        """\
        def main():
            values = {**{1, 2}}
        """,
        diagnostic_text(
            "dict_unpack.py",
            2,
            "values = {**{1, 2}}",
            "            ^^^^^^",
            "pyjs.CompilationError: dictionary unpacking requires a dict value "
            "[PYJS1104]",
            "help: Unpack a dict with known key and value types or construct "
            "the result explicitly.",
        ),
        filename="dict_unpack.py",
    )


@pytest.mark.parametrize(
    ("operator", "method"),
    [
        ("|", "__or__"),
        ("&", "__and__"),
        ("^", "__xor__"),
    ],
)
def test_bitwise_operators_preserve_bool_and_mixed_int_result_types(operator, method):
    at(
        f"""
        def main(integer: int, boolean: bool):
            flags = integer {operator} 8
            enabled = boolean {operator} False
            int_bool = integer {operator} boolean
            bool_int = boolean {operator} integer
        """,
        f"""
        def main(integer: int, boolean: bool) -> None:
            flags: int = integer.[int]{method}!(8)
            enabled: bool = boolean.[bool]{method}!(False)
            int_bool: int = integer.[int]{method}!(boolean)
            bool_int: int = integer.[int]__r{method[2:]}!(boolean)
        """,
        f"""
        export function main(integer, boolean) {{
            var flags = Number(BigInt(integer) {operator} BigInt(8));
            var enabled = Boolean(boolean {operator} false);
            var int_bool = Number(BigInt(integer) {operator} BigInt(boolean));
            var bool_int = Number(BigInt(boolean) {operator} BigInt(integer));
        }}
        """,
    )


def test_binary_operator_prefers_a_subclass_reflected_override():
    at(
        """
        @js
        class Base:
            def __or__(self, other: "Base") -> str:
                return "base"

        @js
        class Child(Base):
            def __ror__(self, other: Base) -> str:
                return "child"

        def main(base: Base, child: Child):
            result = base | child
        """,
        """
        class Base:

        class Child(Base):

            def __ror__(other: Base) -> str:
                return 'child'

        def main(base: Base, child: Child) -> None:
            result: str = child.[Child]__ror__(base)
        """,
        """
        export class Base {
        }

        export class Child extends Base {

            __ror__(other) {
                return 'child';
            }
        }

        export function main(base, child) {
            var result = child.__ror__(base);
        }
        """,
    )


def test_generic_base_arguments_do_not_change_runtime_subclass_priority():
    at(
        '''
        @js
        class Base[T]:
            def __or__(self, other: object) -> str:
                return "base"
        @js
        class Child(Base[int]):
            def __ror__(self, other: object) -> str:
                return "child"
        def main(base: Base[str], child: Child):
            result = base | child
        ''',
        '''
        class Base__int:

        class Base__str:

        class Child(Base__int):

            def __ror__(other: object) -> str:
                return 'child'

        def main(base: Base__str, child: Child) -> None:
            result: str = child.[Child]__ror__(base)
        ''',
        '''
        export class Base__int {
        }

        export class Base__str {
        }

        export class Child extends Base__int {

            __ror__(other) {
                return 'child';
            }
        }

        export function main(base, child) {
            var result = child.__ror__(base);
        }
        ''',
    )


def test_structural_compatibility_does_not_give_reflected_priority():
    at(
        '''
        @js
        class Left:
            __pyjs_structural__ = True
            def __add__(self, other: "Right") -> str:
                return "forward"
        @js
        class Right:
            def __radd__(self, other: Left) -> str:
                return "reflected"
        def main(left: Left, right: Right):
            result = left + right
        ''',
        '''
        class Left:

            def __add__(other: Right) -> str:
                return 'forward'

        class Right:

        def main(left: Left, right: Right) -> None:
            result: str = left.[Left]__add__(right)
        ''',
        '''
        export class Left {

            __add__(other) {
                return 'forward';
            }
        }

        export class Right {
        }

        export function main(left, right) {
            var result = left.__add__(right);
        }
        ''',
    )


def test_binary_operators_wait_for_each_generic_specialization_signature():
    at(
        """
        strings: list[str] = []
        integers: list[int] = []
        strings_differ = strings != ["x"]
        integers_differ = integers != [1]
        """,
        """
        strings: list[str] = []
        integers: list[int] = []
        strings_differ: bool = strings.[list__str]__ne__!(['x'])
        integers_differ: bool = integers.[list__int]__ne__!([1])
        """,
        """
        import { equal_value as $equal_value } from './pyjs.python.js';

        var strings = [];
        var integers = [];
        var strings_differ = !$equal_value(strings,['x']);
        var integers_differ = !$equal_value(integers,[1]);
        """,
    )


@pytest.mark.parametrize(
    ("py_op", "func_op", "js_op"),
    [
        ("+", "__add__", "a + b"),
        ("-", "__sub__", "a - b"),
        ("*", "__mul__", "a * b"),
        (
            "/",
            "__truediv__",
            "((left,right)=>{if(right===0)throw new Error('division by zero');"
            "return left/right;})(a,b)",
        ),
        (
            "//",
            "__floordiv__",
            "((left,right)=>{if(right===0)throw new Error('division by zero');"
            "return Math.floor(left/right);})(a,b)",
        ),
        (
            "%",
            "__mod__",
            "((left,right)=>{if(right===0)throw new Error('division by zero');"
            "return ((left%right)+right)%right;})(a,b)",
        ),
        ("**", "__pow__", "a ** b"),
    ],
)
def test_arithmetic_int_operators(py_op, func_op, js_op):
    result_type = "float" if py_op == "/" else "int"
    at(
        f"""
        a = 1
        b = 2
        c = a {py_op} b
        """,
        f"""
        a: int = 1
        b: int = 2
        c: {result_type} = a.[int]{func_op}!(b)
        """,
        f"""
        var a = 1;
        var b = 2;
        var c = {js_op};
        """,
    )


def test_nested_inline_operators_preserve_python_grouping():
    at(
        """
        print((1 + 2) * 3)
        print((1 < 2) + 3)
        print(1 - (2 - 3))
        print((2 ** 3) ** 2)
        print(2 ** (3 ** 2))
        """,
        """
        print(1.[int]__add__!(2).[int]__mul__!(3))
        print(1.[int]__lt__!(2).[int]__add__!(3))
        print(1.[int]__sub__!(2.[int]__sub__!(3)))
        print(2.[int]__pow__!(3).[int]__pow__!(2))
        print(2.[int]__pow__!(3.[int]__pow__!(2)))
        """,
        """
        console.log((1 + 2) * 3);
        console.log((1 < 2) + 3);
        console.log(1 - (2 - 3));
        console.log((2 ** 3) ** 2);
        console.log(2 ** 3 ** 2);
        """,
    )


def test_dict_pop():
    at(
        """
        values: dict[str, str] = {"name": "value"}
        result = values.pop("name")
        fallback = values.pop("missing", 7)
        optional = values.pop("absent", None)
        """,
        """
        values: dict[str, str] = {'name': 'value'}
        result: str = values.[dict__str_str]pop!('name')
        fallback: str | int = values.[dict__str_str]pop!('missing', 7)
        optional: str | None = values.[dict__str_str]pop!('absent', None)
        """,
        """
        import { pop_dict_item as $pop_dict_item } from './pyjs.python.js';

        var values = new Map([['name', 'value']]);
        var result = $pop_dict_item(values,'name',false,null);
        var fallback = $pop_dict_item(values,'missing',true,7);
        var optional = $pop_dict_item(values,'absent',true,null);
        """,
    )


def test_dict_reads_use_map_protocol():
    at(
        """
        values = {"name": "value"}
        direct = values["name"]
        missing = values.get("missing")
        fallback = values.get("missing", 7)
        """,
        """
        values: dict[str, str] = {'name': 'value'}
        direct: str = $get_dict_item(values, 'name')
        missing: str | None = values.[dict__str_str]get!('missing')
        fallback: str | int = values.[dict__str_str]get!('missing', 7)
        """,
        """
        import { get_dict_item as $get_dict_item } from './pyjs.python.js';

        var values = new Map([['name', 'value']]);
        var direct = $get_dict_item(values, 'name');
        var missing = ((mapping,key,fallback)=>mapping.has(key)?mapping.get(key):fallback)(values,'missing',null);
        var fallback = ((mapping,key,fallback)=>mapping.has(key)?mapping.get(key):fallback)(values,'missing',7);
        """,
    )


def test_dict_setdefault_uses_map_protocol_and_preserves_the_value_type():
    at(
        """
        values: dict[str, list[int]] = {}
        items = values.setdefault("items", [])
        items.append(1)
        """,
        """
        values: dict[str, list[int]] = {}
        items: list[int] = values.[dict__str_list__int]setdefault!('items', [])
        items.[list__int]append!(1)
        """,
        """
        var values = new Map([]);
        var items = ((mapping,key,value)=>{if(!mapping.has(key))mapping.set(key,value);return mapping.get(key);})(values,'items',[]);
        (items.push(1), null);
        """,
    )


def test_dict_setdefault_without_default_returns_optional_value():
    at(
        """\
        def main(values: dict[str, int]):
            value = values.setdefault("missing")
        """,
        """
        def main(values: dict__str_int) -> None:
            value: int | None = values.[dict__str_int]setdefault!('missing')
        """,
        """
        export function main(values) {
            var value = ((mapping,key,value)=>{if(!mapping.has(key))mapping.set(key,value);return mapping.get(key);})(values,'missing',null);
        }
        """,
    )


def test_dict_defaults_use_the_receiver_value_type_as_context():
    at(
        """
        def main():
            values: dict[int, list[int]] = {}
            missing: list[int] = values.get(1, [])
            removed: list[int] = values.pop(2, [])
            label: list[int] | str = values.get(3, "missing")
        """,
        """
        def main() -> None:
            values: dict[int, list[int]] = {}
            missing: list[int] = values.[dict__int_list__int]get!(1, [])
            removed: list[int] = values.[dict__int_list__int]pop!(2, [])
            label: list[int] | str = values.[dict__int_list__int]get!(3, 'missing')
        """,
        """
        import { pop_dict_item as $pop_dict_item } from './pyjs.python.js';

        export function main() {
            var values = new Map([]);
            var missing = ((mapping,key,fallback)=>mapping.has(key)?mapping.get(key):fallback)(values,1,[]);
            var removed = $pop_dict_item(values,2,true,[]);
            var label = ((mapping,key,fallback)=>mapping.has(key)?mapping.get(key):fallback)(values,3,'missing');
        }
        """,
    )


def test_empty_collection_comparisons_have_concrete_operand_types():
    at(
        """
        def main():
            values: list[int] = []
            sequence_is_empty = values == []
            mapping: dict[str, int] = {}
            mapping_is_empty = mapping == {}
        """,
        """
        def main() -> None:
            values: list[int] = []
            sequence_is_empty: bool = values.[list__int]__eq__!([])
            mapping: dict[str, int] = {}
            mapping_is_empty: bool = $equal_value(mapping, {})
        """,
        """
        import { equal_value as $equal_value } from './pyjs.python.js';

        export function main() {
            var values = [];
            var sequence_is_empty = $equal_value(values,[]);
            var mapping = new Map([]);
            var mapping_is_empty = $equal_value(mapping, new Map([]));
        }
        """,
    )


def test_starred_expansion_preserves_union_item_types():
    at(
        """
        from pyjs import js

        @js
        def values() -> list[int | str]:
            return [1, "two"]

        def main():
            expanded: list[int | str] = [0, *values()]
        """,
        """
        def values() -> list[int | str]:
            return [1, 'two']

        def main() -> None:
            expanded: list[int | str] = [0, *values()]
        """,
        """
        export function values() {
            return [1, 'two'];
        }

        export function main() {
            var expanded = [0, ...values()];
        }
        """,
    )


def test_list_remove_uses_the_typed_python_semantics_helper():
    at(
        """
        values = [1, 2]
        values.remove(1)
        """,
        """
        values: list[int] = [1, 2]
        $remove_list_item(values, 1)
        """,
        """
        import { remove_list_item as $remove_list_item } from './pyjs.python.js';

        var values = [1, 2];
        $remove_list_item(values, 1);
        """,
    )


def test_sequence_index_uses_the_typed_python_semantics_helper():
    at(
        """
        values = [1, 2, 1]
        coordinates = (1, 2, 1)
        first = values.index(1)
        later = values.index(1, 1)
        limited = values.index(1, 1, 3)
        coordinate = coordinates.index(2)
        """,
        """
        values: list[int] = [1, 2, 1]
        coordinates: tuple[int, int, int] = (1, 2, 1)
        first: int = $sequence_index(values, 1)
        later: int = $sequence_index(values, 1, 1)
        limited: int = $sequence_index(values, 1, 1, 3)
        coordinate: int = $sequence_index(coordinates, 2)
        """,
        """
        import { sequence_index as $sequence_index } from './pyjs.python.js';

        var values = [1, 2, 1];
        var coordinates = [1, 2, 1];
        var first = $sequence_index(values, 1);
        var later = $sequence_index(values, 1, {start: 1});
        var limited = $sequence_index(values, 1, {start: 1, stop: 3});
        var coordinate = $sequence_index(coordinates, 2);
        """,
    )


def test_custom_getitem_dispatches_to_the_python_dunder():
    at(
        """\
        @js
        class Lookup:
            def __getitem__(self, key: str) -> int:
                return 42 if key == "answer" else 0

        def main():
            value = Lookup()["answer"]
        """,
        """\
        class Lookup:

            def __getitem__(key: str) -> int:
                return 42 if key.[object]__eq__!('answer') else 0

        def main() -> None:
            value: int = Lookup().[Lookup]__getitem__('answer')
        """,
        """\
        export class Lookup {

            __getitem__(key) {
                return key === 'answer' ? 42 : 0;
            }
        }

        export function main() {
            var value = new Lookup().__getitem__('answer');
        }
        """,
    )


def test_typed_list_and_dict_copy_and_mapping_update():
    at(
        """
        values = [1, 2]
        copied_values = values.copy()
        mapping = {"one": 1}
        copied_mapping = mapping.copy()
        mapping.update({"two": 2})
        """,
        """
        values: list[int] = [1, 2]
        copied_values: list[int] = values.[list__int]copy!()
        mapping: dict[str, int] = {'one': 1}
        copied_mapping: dict[str, int] = mapping.[dict__str_int]copy!()
        mapping.[dict__str_int]update!({'two': 2})
        """,
        """
        import { update_dict as $update_dict } from './pyjs.python.js';

        var values = [1, 2];
        var copied_values = [...values];
        var mapping = new Map([['one', 1]]);
        var copied_mapping = new Map(mapping);
        ($update_dict(mapping,new Map([['two', 2]])),null);
        """,
    )


def test_dict_constructor_infers_keyword_values_and_combines_a_source():
    at(
        """
        def main(source: dict[str, int]):
            keyword_only = dict(one=1, two=2)
            copied = dict(source, three=3)
        """,
        """
        def main(source: dict__str_int) -> None:
            keyword_only: dict[str, int] = dict__str_int(one=1, two=2)
            copied: dict[str, int] = dict__str_int(source, three=3)
        """,
        """
        export function main(source) {
            var keyword_only = new Map([['one', 1], ['two', 2]]);
            var copied = new Map([...source, ['three', 3]]);
        }
        """,
    )


def test_dict_update_keywords_and_empty_calls_have_explicit_lowering():
    at(
        """\
        def main(values: dict[str, int]):
            empty = values.update()
            mixed = values.update({"one": 1}, two=2)
            named_like_argument = values.update(values=3)
        """,
        """
        def main(values: dict__str_int) -> None:
            empty: None = values.[dict__str_int]update!()
            mixed: None = values.[dict__str_int]update!({'one': 1}, two=2)
            named_like_argument: None = values.[dict__str_int]update!(values=3)
        """,
        """
        import { update_dict as $update_dict } from './pyjs.python.js';

        export function main(values) {
            var empty = (null);
            var mixed = ($update_dict(values,new Map([['one', 1]])),values.set('two',2),null);
            var named_like_argument = (values.set('values',3),null);
        }
        """,
    )


def test_dict_update_rejects_an_explicit_none_source():
    ad(
        """\
        def main(values: dict[str, int]):
            values.update(None)
        """,
        """
          File "dict_update.py", line 2
            values.update(None)
                          ^^^^
        pyjs.CompilationError: Argument 'values' to dict.update expects dict[str, int]|Iterable[tuple[str, int]], got NoneType [PYJS1104]
        help: Pass a value compatible with dict[str, int]|Iterable[tuple[str, int]].
        """,
        filename="dict_update.py",
    )


def test_dict_update_iterable_pairs_have_explicit_lowering():
    at(
        """\
        def main(values: dict[str, int], pairs: list[tuple[str, int]]):
            result = values.update(pairs)
        """,
        """
        def main(values: dict__str_int, pairs: list__tuple__str_int) -> None:
            result: None = values.[dict__str_int]update!(pairs)
        """,
        """
        import { update_dict as $update_dict } from './pyjs.python.js';

        export function main(values, pairs) {
            var result = ($update_dict(values,pairs),null);
        }
        """,
    )


def test_dict_update_rejects_malformed_iterable_pairs():
    ad(
        """\
        def main(values: dict[str, int]):
            values.update([("one", 1, 2)])
        """,
        """
          File "dict_update_pairs.py", line 2
            values.update([("one", 1, 2)])
                          ^^^^^^^^^^^^^^^
        pyjs.CompilationError: Argument 'values' to dict.update expects dict[str, int]|Iterable[tuple[str, int]], got list[tuple[str, int, int]] [PYJS1104]
        help: Pass a value compatible with dict[str, int]|Iterable[tuple[str, int]].
        """,
        filename="dict_update_pairs.py",
    )


def test_dict_popitem_uses_the_runtime_semantics_helper():
    at(
        """\
        def main(values: dict[str, int]):
            pair = values.popitem()
        """,
        """
        def main(values: dict__str_int) -> None:
            pair: tuple[str, int] = $pop_dict_pair(values)
        """,
        """
        import { pop_dict_pair as $pop_dict_pair } from './pyjs.python.js';

        export function main(values) {
            var pair = $pop_dict_pair(values);
        }
        """,
    )


def test_arithmetic_str_operators():
    at(
        """
        a = 'a'
        b = a * 3
        c = 3 * a
        """,
        """
        a: str = 'a'
        b: str = a.[str]__mul__!(3)
        c: str = a.[str]__rmul__!(3)
        """,
        """
        var a = 'a';
        var b = a.repeat(3);
        var c = a.repeat(3);
        """,
    )
    at(
        """
        a = 'a'
        b = a + 'b'
        """,
        """
        a: str = 'a'
        b: str = a.[str]__add__!('b')
        """,
        """
        var a = 'a';
        var b = a + 'b';
        """,
    )


def test_string_ordering_uses_the_python_comparator():
    at(
        """\
        def main(left: str, right: str):
            result = left < right
        """,
        """
        def main(left: str, right: str) -> None:
            result: bool = left.[str]__lt__!(right)
        """,
        """
        import { compare_strings as $compare_strings } from './pyjs.python.js';

        export function main(left, right) {
            var result = $compare_strings(left,right) < 0;
        }
        """,
    )


def test_list_and_tuple_repetition_preserves_the_sequence_type():
    at(
        """
        values = [1, 2]
        repeated = values * 2
        reflected = 2 * values
        coordinates = (1, 2)
        tuple_repeated = coordinates * 2
        """,
        """
        values: list[int] = [1, 2]
        repeated: list[int] = values.[list__int]__mul__!(2)
        reflected: list[int] = values.[list__int]__rmul__!(2)
        coordinates: tuple[int, int] = (1, 2)
        tuple_repeated: tuple[int, int, int, int] = coordinates.[tuple__int_int]__mul__!(2)
        """,
        """
        var values = [1, 2];
        var repeated = ((values,times)=>{const result=[];for(let index=0;index<times;index++)result.push(...values);return result;})(values,2);
        var reflected = ((values,times)=>{const result=[];for(let index=0;index<times;index++)result.push(...values);return result;})(values,2);
        var coordinates = [1, 2];
        var tuple_repeated = ((values,times)=>{const result=[];for(let index=0;index<times;index++)result.push(...values);return result;})(coordinates,2);
        """,
    )


def test_typed_list_concatenation():
    at(
        """
        values: list[float] = [1.0]
        suffix: list[float] = [2.0]
        combined = values + suffix
        """,
        """
        values: list[float] = [1.0]
        suffix: list[float] = [2.0]
        combined: list[float] = values.[list__float]__add__!(suffix)
        """,
        """
        var values = [1.0];
        var suffix = [2.0];
        var combined = values.concat(suffix);
        """,
    )


def test_arithmetic_float_operators_accept_python_numeric_types():
    at(
        """
        a = 1.0
        b = 2.0
        count = 3
        difference = a - b
        product = b * count
        centered = a + (count - b) / 2
        floor = b // a
        remainder = count % a
        """,
        """
        a: float = 1.0
        b: float = 2.0
        count: int = 3
        difference: float = a.[float]__sub__!(b)
        product: float = b.[float]__mul__!(count)
        centered: float = a.[float]__add__!(b.[float]__rsub__!(count).[float]__truediv__!(2))
        floor: float = b.[float]__floordiv__!(a)
        remainder: float = a.[float]__rmod__!(count)
        """,
        """
        import { float_divmod as $float_divmod } from './pyjs.python.js';

        var a = 1.0;
        var b = 2.0;
        var count = 3;
        var difference = a - b;
        var product = b * count;
        var centered = a + ((left,right)=>{if(right===0)throw new Error('division by zero');return left/right;})((count - b),2);
        var floor = $float_divmod(b,a)[0];
        var remainder = $float_divmod(count,a)[1];
        """,
    )


def test_binary_operators_preserve_union_receiver_types():
    assert_module_analysis_transpile(
        """\
        from pyjs import js

        @js
        def increment(value: int | float) -> int | float:
            return value + 1

        def main():
            integer = increment(2)
            decimal = increment(2.5)
        """,
        """
        def increment(value: int | float) -> int | float:
            return value.[int]__add__!(1)

        def main() -> None:
            integer: int | float = increment(2)
            decimal: int | float = increment(2.5)
        """,
        """
        export function increment(value) {
            return value + 1;
        }

        export function main() {
            var integer = increment(2);
            var decimal = increment(2.5);
        }
        """,
    )


def test_divmod_preserves_integer_and_float_result_types():
    at(
        """\
        def main():
            integers = divmod(5, 2)
            floats = divmod(5.5, 2)
        """,
        """
        def main() -> None:
            integers: tuple[int, int] = divmod(5, 2)
            floats: tuple[float, float] = divmod(5.5, 2)
        """,
        """
        import { float_divmod as $float_divmod, integer_index as $integer_index } from './pyjs.python.js';

        export function main() {
            var integers = $float_divmod(5,2);
            var floats = $float_divmod(5.5,2);
        }
        """,
    )


def test_union_binary_operator_requires_every_member_to_support_it():
    ad(
        """\
        def main(value: int | str):
            return value + 1
        """,
        """
          File "union_operator.py", line 2
            return value + 1
                   ^^^^^^^^^
        pyjs.CompilationError: Operator '+' is not supported for every combination of int|str and int [PYJS1104]
        help: Narrow either operand before applying the operator.
        """,
        filename="union_operator.py",
    )


def test_concrete_binary_operator_requires_compatible_operand_types():
    ad(
        """\
        def main():
            values = [1] + ["two"]
        """,
        diagnostic_text(
            "concrete_operator.py",
            2,
            'values = [1] + ["two"]',
            " " * 9 + "^" * 13,
            "pyjs.CompilationError: Operator '+' is not supported for "
            "list[int] and list[str] [PYJS1104]",
            "help: Use operands with compatible types or define the "
            "corresponding __add__() method.",
        ),
        filename="concrete_operator.py",
    )


def test_union_binary_operator_rejects_incompatible_inline_lowering():
    ad(
        """\
        from pyjs import js

        @js
        class Left:
            @js.inline("{self}.left({other})")
            def __add__(self, other: int) -> str: ...

        @js
        class Right:
            @js.inline("{self}.right({other})")
            def __add__(self, other: int) -> str: ...

        def main(value: Left | Right):
            return value + 1
        """,
        diagnostic_text(
            "union_operator_lowering.py",
            14,
            "return value + 1",
            " " * 7 + "^" * 9,
            "pyjs.CompilationError: Operator '+' has incompatible client "
            "lowering across Left|Right and int [PYJS2001]",
            "help: Narrow either operand before applying the operator.",
        ),
        filename="union_operator_lowering.py",
    )
    ad(
        """\
        def main(value: int | float):
            return 1 - value
        """,
        diagnostic_text(
            "union_reflected_operator.py",
            2,
            "return 1 - value",
            " " * 7 + "^" * 9,
            "pyjs.CompilationError: Operator '-' has incompatible client "
            "lowering across int and int|float [PYJS2001]",
            "help: Narrow either operand before applying the operator.",
        ),
        filename="union_reflected_operator.py",
    )


def test_float_comparators_accept_python_numeric_types():
    at(
        """
        low = 1.5
        high = 2
        below = low < high
        reached = low >= 1.5
        equal = low == 1.5
        different = low != high
        """,
        """
        low: float = 1.5
        high: int = 2
        below: bool = low.[float]__lt__!(high)
        reached: bool = low.[float]__ge__!(1.5)
        equal: bool = low.[float]__eq__!(1.5)
        different: bool = low.[float]__ne__!(high)
        """,
        """
        var low = 1.5;
        var high = 2;
        var below = low < high;
        var reached = low >= 1.5;
        var equal = low == 1.5;
        var different = low != high;
        """,
    )


def test_chained_comparisons_bind_each_operand_once():
    at(
        """
        def main(value: int):
            in_range = 0 <= value <= 10
        """,
        """
        def main(value: int) -> None:
            in_range: bool = $chained_compare(0, value, 10; $compare0.[int]__le__!($compare1) and $compare1.[int]__le__!($compare2))
        """,
        """
        export function main(value) {
            var in_range = (($compare0) => (($compare1) => $compare0 <= $compare1 && (($compare2) => $compare1 <= $compare2)(10))(value))(0);
        }
        """,
    )


def test_awaited_chained_comparison_has_one_async_evaluation_scope():
    at(
        '''
        @js
        async def value(item: int) -> int:
            return item
        async def main() -> bool:
            return 1 < await value(2) < 3
        ''',
        '''
        async def value(item: int) -> int:
            return item

        async def main() -> bool:
            return $chained_compare(1, await value(2), 3; $compare0.[int]__lt__!($compare1) and $compare1.[int]__lt__!($compare2))
        ''',
        '''
        export async function value(item) {
            return item;
        }

        export async function main() {
            return (await (async () => { const $compare0 = 1; const $compare1 = await value(2); const $comparison1 = $compare0 < $compare1; if (!$comparison1) return $comparison1; const $compare2 = 3; return $compare1 < $compare2; })());
        }
        ''',
    )


def test_positive_and_negative_numeric_values():
    at(
        """
        positive = +1
        negative = -1.5
        """,
        """
        positive: int = +1
        negative: float = -1.5
        """,
        """
        var positive = +1;
        var negative = -1.5;
        """,
    )


def test_integer_inversion_uses_the_typed_dunder_implementation():
    at(
        """
        inverted = ~5
        """,
        """
        inverted: int = 5.[int]__invert__!()
        """,
        """
        var inverted = (-(5)-1);
        """,
    )


def test_round_result_type_depends_on_value_and_ndigits():
    assert_analysis(
        """
        def main():
            whole: int = round(2.5)
            explicit_none: int = round(2.5, None)
            decimal: float = round(2.5, 1)
            integer: int = round(25, -1)
        """,
        """
        def main() -> None:
            whole: int = 2.5.[float]__round__!()
            explicit_none: int = 2.5.[float]__round__!()
            decimal: float = $round_ndigits(2.5, 1, True)
            integer: int = $round_ndigits(25, -1, False)
        """,
    )

    assert_analysis(
        """
        from pyjs import js

        @js
        def precision() -> int | None:
            return None

        def main():
            value: int | float = round(2.5, precision())
        """,
        """
        def precision() -> int | None:
            return None

        def main() -> None:
            value: int | float = $round_ndigits(2.5, precision(), True)
        """,
    )


def test_round_rejects_non_integer_ndigits_during_compilation():
    ad(
        """\
        def main():
            print(round(1.2, 1.2))
        """,
        """
          File "round_ndigits.py", line 2
            print(round(1.2, 1.2))
                             ^^^
        pyjs.CompilationError: Argument 'ndigits' to round expects int|NoneType, got float [PYJS1104]
        help: Pass a value compatible with int|NoneType.
        """,
        filename="round_ndigits.py",
    )


def test_round_dispatches_custom_implementations_before_builtin_type_checks():
    assert_analysis(
        """
        from pyjs import js

        @js
        class Price:
            @js
            def __round__(self, ndigits: int | None = None) -> int:
                return 7

        def main():
            value: int = round(Price(), 2)
        """,
        """
        class Price:

            def __round__(ndigits: int | None=None) -> int:
                return 7

        def main() -> None:
            value: int = Price().[Price]__round__(2)
        """,
    )


def test_str_split_with_explicit_separator():
    at(
        """
        value = "module::test_name"
        parts = value.split("::")
        """,
        """
        value: str = 'module::test_name'
        parts: list[str] = $split_string(value, '::')
        """,
        """
        import { split_string as $split_string } from './pyjs.python.js';

        var value = 'module::test_name';
        var parts = $split_string(value, {separator: '::'});
        """,
    )


def test_str_split_without_separator_uses_python_whitespace_semantics():
    at(
        """
        value = "  one  two   three  "
        parts = value.split()
        """,
        """
        value: str = '  one  two   three  '
        parts: list[str] = $split_string(value)
        """,
        """
        import { split_string as $split_string } from './pyjs.python.js';

        var value = '  one  two   three  ';
        var parts = $split_string(value);
        """,
    )


def test_str_prefix_suffix_and_literal_replacement():
    at(
        """
        def main():
            name = "example.json"
            starts = name.startswith("example")
            ends = name.endswith(".json")
            stem = name.removesuffix(".json")
            unqualified = name.removeprefix("example.")
            unchanged = name.removesuffix("")
            cleaned = "a::a::a".replace("a", "note", 2)
            spaced = "ab".replace("", "-", 2)
        """,
        """
        def main() -> None:
            name: str = 'example.json'
            starts: bool = name.[str]startswith!('example')
            ends: bool = name.[str]endswith!('.json')
            stem: str = name.[str]removesuffix!('.json')
            unqualified: str = name.[str]removeprefix!('example.')
            unchanged: str = name.[str]removesuffix!('')
            cleaned: str = $replace_string('a::a::a', 'a', 'note', 2)
            spaced: str = $replace_string('ab', '', '-', 2)
        """,
        """
        import { replace_string as $replace_string } from './pyjs.python.js';

        export function main() {
            var name = 'example.json';
            var starts = name.startsWith('example');
            var ends = name.endsWith('.json');
            var stem = ((value,suffix)=>suffix.length&&value.endsWith(suffix)?value.slice(0,-suffix.length):value)(name,'.json');
            var unqualified = ((value,prefix)=>value.startsWith(prefix)?value.slice(prefix.length):value)(name,'example.');
            var unchanged = ((value,suffix)=>suffix.length&&value.endsWith(suffix)?value.slice(0,-suffix.length):value)(name,'');
            var cleaned = $replace_string('a::a::a', 'a', 'note', {count: 2});
            var spaced = $replace_string('ab', '', '-', {count: 2});
        }
        """,
    )


def test_str_prefix_checks_reject_non_string_tuple_items():
    ad(
        """\
        def main(value: str):
            print(value.startswith(("valid", 1)))
        """,
        """
          File "string_prefix.py", line 2
            print(value.startswith(("valid", 1)))
                                   ^^^^^^^^^^^^
        pyjs.CompilationError: Argument 'prefix' to str.startswith expects str|tuple[str, ...], got tuple[str, int] [PYJS1104]
        help: Pass a value compatible with str|tuple[str, ...].
        """,
        filename="string_prefix.py",
    )


def test_hasattr_uses_the_object_argument():
    at(
        """
        @js
        class Value:
            pass

        def main(value: Value):
            present = hasattr(value, "name")
        """,
        """
        class Value:

        def main(value: Value) -> None:
            present: bool = hasattr(value, 'name')
        """,
        """
        export class Value {
        }

        export function main(value) {
            var present = 'name' in value;
        }
        """,
    )


def test_bool_and_isinstance_use_python_primitive_relationships():
    at(
        """
        def main():
            empty = bool()
            values = bool([1])
            mapping = bool({"a": 1})
            text = bool("value")
            integer = isinstance(True, int)
        """,
        """
        def main() -> None:
            empty: bool = bool()
            values: bool = bool([1])
            mapping: bool = bool({'a': 1})
            text: bool = bool('value')
            integer: bool = isinstance(True, int)
        """,
        """
        export function main() {
            var empty = false;
            var values = [1].length!==0;
            var mapping = new Map([['a', 1]]).size!==0;
            var text = 'value'.length!==0;
            var integer = ((value)=>typeof value==='boolean'||Number.isInteger(value))(true);
        }
        """,
    )


def test_numeric_isinstance_uses_the_static_float_type():
    at(
        """
        from pyjs import js

        @js
        def floating() -> float:
            return 1.0

        def main():
            integer = isinstance(floating(), int)
            decimal = isinstance(floating(), float)
        """,
        """
        def floating() -> float:
            return 1.0

        def main() -> None:
            integer: bool = isinstance(floating(), int)
            decimal: bool = isinstance(floating(), float)
        """,
        """
        export function floating() {
            return 1.0;
        }

        export function main() {
            var integer = (floating(),false);
            var decimal = (typeof floating() === 'number');
        }
        """,
    )


def test_isinstance_accepts_a_typed_runtime_class_value():
    at(
        """
        def main(error: object, expected: type[Exception]) -> bool:
            return isinstance(error, expected)
        """,
        """
        def main(error: object, expected: type__Exception) -> bool:
            return isinstance(error, expected)
        """,
        """
        export function main(error, expected) {
            return (error instanceof expected);
        }
        """,
    )


def test_tuple_isinstance_narrows_to_matching_types():
    assert_transpile(
        """
        from pyjs import js

        @js
        class Left:
            def side(self) -> str:
                return "left"

        @js
        class Right:
            def side(self) -> str:
                return "right"

        @js
        def identify(value: Left | Right | str) -> str:
            if not isinstance(value, (Left, Right)):
                return "text"
            return value.side()

        def main():
            print(identify(Left()))
            print(identify(Right()))
            print(identify("other"))
        """,
        """
        export class Left {

            side() {
                return 'left';
            }
        }

        export class Right {

            side() {
                return 'right';
            }
        }

        export function identify(value) {
            if (!(($value) => ($value instanceof Left) || ($value instanceof Right))(value)) {
                return 'text';
            }
            return value.side();
        }

        export function main() {
            console.log(identify(new Left()));
            console.log(identify(new Right()));
            console.log(identify('other'));
        }
        """,
    )


def test_common_numeric_string_conversions_validate_input():
    at(
        """
        def main():
            integer = int("12")
            binary = int("101", base=2)
            decimal = float("1.25")
        """,
        """
        def main() -> None:
            integer: int = int('12')
            binary: int = int('101', base=2)
            decimal: float = float('1.25')
        """,
        r"""
        import { parse_integer as $parse_integer } from './pyjs.python.js';

        export function main() {
            var integer = $parse_integer('12',null);
            var binary = $parse_integer('101',2);
            var decimal = ((value)=>{const text=value.trim();if(/^[+-]?nan$/i.test(text))return NaN;if(/^[+-]?inf(?:inity)?$/i.test(text))return text[0]==='-'?-Infinity:Infinity;if(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(text))throw new RangeError(`could not convert string to float: '${value}'`);return Number(text);})('1.25');
        }
        """,
    )


def test_range_supports_python_argument_forms():
    range_generator = (
        "(function*(start,stop,step){for(let i=start;step>0?i<stop:i>stop;"
        "i+=step)yield i})"
    )
    at(
        """
        def main():
            for index in range(3):
                print(index)
            for index in range(2, 6):
                print(index)
            for index in range(6, 0, -2):
                print(index)
        """,
        """
        def main() -> None:
            for index: int in range(3):
                print(index)
            for index: int in range(2, 6):
                print(index)
            for index: int in range(6, 0, -2):
                print(index)
        """,
        f"""
        export function main() {{
            for (var index of ((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)({range_generator}(0,3,1))) {{
                console.log(index);
            }}
            for (var index of ((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)({range_generator}(2,6,1))) {{
                console.log(index);
            }}
            for (var index of ((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)({range_generator}(6,0,-2))) {{
                console.log(index);
            }}
        }}
        """,
    )


def test_range_checks_a_dynamic_step_when_the_range_is_created():
    at(
        """
        def main(step: int):
            values = range(0, 3, step)
        """,
        """
        def main(step: int) -> None:
            values: Iterable[int] = range(0, 3, step)
        """,
        """
        export function main(step) {
            var values = ((start,stop,step)=>{if(step===0)throw new RangeError('range() arg 3 must not be zero');return (function*(){for(let i=start;step>0?i<stop:i>stop;i+=step)yield i})()})(0,3,step);
        }
        """,
    )


def test_sum_supports_numeric_iterables_and_start_value():
    at(
        """
        total = sum(range(10))
        started = sum([1, 2, 3], 4)
        keyword_started = sum([1, 2, 3], start=4)
        empty = sum([], 5)
        floats = sum([1.5, 2.25])
        mixed = sum([1, 2], 0.5)
        """,
        """
        total: int = sum(range(10))
        started: int = sum([1, 2, 3], 4)
        keyword_started: int = sum([1, 2, 3], start=4)
        empty: int = sum([], 5)
        floats: float = sum([1.5, 2.25])
        mixed: float = sum([1, 2], 0.5)
        """,
        """
        var total = ((values,total)=>{for(const value of values)total=total+value;return total;})(((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)((function*(start,stop,step){for(let i=start;step>0?i<stop:i>stop;i+=step)yield i})(0,10,1)),0);
        var started = ([1, 2, 3]).reduce((total,value)=>total+value,4);
        var keyword_started = ([1, 2, 3]).reduce((total,value)=>total+value,4);
        var empty = ([]).reduce((total,value)=>total+value,5);
        var floats = ([1.5, 2.25]).reduce((total,value)=>total+value,0);
        var mixed = ([1, 2]).reduce((total,value)=>total+value,0.5);
        """,
    )


def test_sum_rejects_non_numeric_iterables():
    ad(
        """\
        def main():
            print(sum(["a", "b"]))
        """,
        """
          File "sum_values.py", line 2
            print(sum(["a", "b"]))
                      ^^^^^^^^^^
        pyjs.CompilationError: Argument 'values' to sum expects Iterable[int | float], got list[str] [PYJS1104]
        help: Pass a value compatible with Iterable[int | float].
        """,
        filename="sum_values.py",
    )


def test_common_iterable_builtins_preserve_types_and_emit_complete_lowering():
    at(
        """
        def main():
            values = sorted([3, 1, 2], reverse=True)
            backwards = reversed(values)
            complete = all([True, False])
            present = any([False, True])
        """,
        """
        def main() -> None:
            values: list[int] = sorted([3, 1, 2], reverse=True)
            backwards: Iterator[int] = reversed(values)
            complete: bool = all([True, False])
            present: bool = any([False, True])
        """,
        """
        import { sort_values as $sort_values, truthy as $truthy } from './pyjs.python.js';

        export function main() {
            var values = $sort_values(Array.from([3, 1, 2]),null,true);
            var backwards = (function*(values){const items=Array.from(values);for(let index=items.length-1;index>=0;index--)yield items[index];})(values);
            var complete = ((values)=>{for(const value of values){if($truthy(value)!==true)return false;}return true;})([true, false]);
            var present = ((values)=>{for(const value of values){if($truthy(value)===true)return true;}return false;})([false, true]);
        }
        """,
    )


def test_iter_and_list_clear_use_the_collection_protocol():
    at(
        """
        def main():
            values = [1, 2]
            iterator = iter(values)
            cleared = values.clear()
        """,
        """
        def main() -> None:
            values: list[int] = [1, 2]
            iterator: Iterator[int] = iter(values)
            cleared: None = values.[list__int]clear!()
        """,
        """
        export function main() {
            var values = [1, 2];
            var iterator = values[Symbol.iterator]();
            var cleared = (values.length = 0, null);
        }
        """,
    )


def test_list_sort_mutates_in_place_and_returns_none():
    at(
        """
        from pyjs import js

        @js
        def size(value: str) -> int:
            return len(value)

        def main():
            values = [3, 1, 2]
            result = values.sort(reverse=True)
            labels = ["aa", "b"]
            labels.sort(key=size)
            labels.sort(key=len)
        """,
        """
        def size(value: str) -> int:
            return value.[str]__len__!()

        def main() -> None:
            values: list[int] = [3, 1, 2]
            result: None = values.[list__int]sort!(reverse=True)
            labels: list[str] = ['aa', 'b']
            labels.[list__str]sort!(key=size)
            labels.[list__str]sort!(key=$len)
        """,
        """
        import { sort_values as $sort_values, len as $len } from './pyjs.python.js';

        export function size(value) {
            return [...value].length;
        }

        export function main() {
            var values = [3, 1, 2];
            var result = ($sort_values(values,null,true), null);
            var labels = ['aa', 'b'];
            ($sort_values(labels,size,false), null);
            ($sort_values(labels,$len,false), null);
        }
        """,
    )


def test_max_uses_one_compatible_dunder_key_lowering_for_union_values():
    at(
        """
        from pyjs import js

        @js
        def values() -> list[int | float]:
            return [1, -2.5]

        def main():
            selected = max(values(), key=abs)
            print(selected)
        """,
        """
        def values() -> list[int | float]:
            return [1, -2.5]

        def main() -> None:
            selected: int | float = max(values(), key=$abs)
            print(selected)
        """,
        """
        import { compare_values as $compare_values, abs as $abs } from './pyjs.python.js';

        export function values() {
            return [1, -2.5];
        }

        export function main() {
            var selected = ((values,key,hasDefault,defaultValue)=>{let found=false;let best;let bestKey;for(const value of values){const valueKey=key===null?value:key(value);if(!found||$compare_values(valueKey,bestKey)>0){found=true;best=value;bestKey=valueKey;}}if(!found){if(hasDefault)return defaultValue;throw new RangeError('max() iterable argument is empty');}return best;})(values(),$abs,false,null);
            console.log(selected);
        }
        """,
    )


def test_dunder_builtin_values_retain_reachable_custom_implementations():
    assert_transpile(
        """
        @js
        class Box:
            def __init__(self, size: int):
                self.size = size

            def __len__(self) -> int:
                return self.size

        @js
        class Distance:
            def __init__(self, magnitude: int):
                self.magnitude = magnitude

            def __abs__(self) -> int:
                return self.magnitude

        @js
        class Unused:
            def __len__(self) -> int:
                return 100

        def main():
            boxes = [Box(5), Box(2)]
            distances = [Distance(5), Distance(2)]
            print(min(boxes, key=len).size)
            print(min(distances, key=abs).magnitude)
        """,
        """
        import { compare_values as $compare_values, len as $len, abs as $abs } from './pyjs.python.js';

        export class Box {

            constructor(size) {
                this.size = size;
            }

            __len__() {
                return this.size;
            }
        }

        export class Distance {

            constructor(magnitude) {
                this.magnitude = magnitude;
            }

            __abs__() {
                return this.magnitude;
            }
        }

        export function main() {
            var boxes = [new Box(5), new Box(2)];
            var distances = [new Distance(5), new Distance(2)];
            console.log(((values,key,hasDefault,defaultValue)=>{let found=false;let best;let bestKey;for(const value of values){const valueKey=key===null?value:key(value);if(!found||$compare_values(valueKey,bestKey)<0){found=true;best=value;bestKey=valueKey;}}if(!found){if(hasDefault)return defaultValue;throw new RangeError('min() iterable argument is empty');}return best;})(boxes,$len,false,null).size);
            console.log(((values,key,hasDefault,defaultValue)=>{let found=false;let best;let bestKey;for(const value of values){const valueKey=key===null?value:key(value);if(!found||$compare_values(valueKey,bestKey)<0){found=true;best=value;bestKey=valueKey;}}if(!found){if(hasDefault)return defaultValue;throw new RangeError('min() iterable argument is empty');}return best;})(distances,$abs,false,null).magnitude);
        }
        """,
    )


def test_string_list_and_tuple_membership_use_value_semantics():
    at(
        """
        def main():
            has_text = "save" in "save all"
            has_number = 2 in [1, 2, 3]
            has_tuple_number = 2 in (1, 2, 3)
            has_nested_list = [1, 2] in ([1, 2], [3, 4])
            lacks_text = "delete" not in "save all"
            lacks_number = 4 not in [1, 2, 3]
            lacks_tuple_number = 4 not in (1, 2, 3)
        """,
        """
        def main() -> None:
            has_text: bool = 'save all'.[str]__contains__!('save')
            has_number: bool = $contains_equal_sequence_item([1, 2, 3], 2)
            has_tuple_number: bool = $contains_equal_sequence_item((1, 2, 3), 2)
            has_nested_list: bool = $contains_equal_sequence_item(([1, 2], [3, 4]), [1, 2])
            lacks_text: bool = not 'save all'.[str]__contains__!('delete')
            lacks_number: bool = not $contains_equal_sequence_item([1, 2, 3], 4)
            lacks_tuple_number: bool = not $contains_equal_sequence_item((1, 2, 3), 4)
        """,
        """
        import { contains_equal_sequence_item as $contains_equal_sequence_item } from './pyjs.python.js';

        export function main() {
            var has_text = 'save all'.includes('save');
            var has_number = $contains_equal_sequence_item([1, 2, 3], 2);
            var has_tuple_number = $contains_equal_sequence_item([1, 2, 3], 2);
            var has_nested_list = (($compare_left0, $compare_right1) => $contains_equal_sequence_item($compare_right1, $compare_left0))([1, 2], [[1, 2], [3, 4]]);
            var lacks_text = !('save all'.includes('delete'));
            var lacks_number = !$contains_equal_sequence_item([1, 2, 3], 4);
            var lacks_tuple_number = !$contains_equal_sequence_item([1, 2, 3], 4);
        }
        """,
    )


def test_string_python_transformations():
    at(
        """
        def main():
            value = "PyJS"
            lower = value.lower()
            capitalized = "eXAMPLE".capitalize()
            titled = "sample primitive".title()
            prefix = value[:2]
            first = value[0]
        """,
        """
        def main() -> None:
            value: str = 'PyJS'
            lower: str = value.[str]lower!()
            capitalized: str = 'eXAMPLE'.[str]capitalize!()
            titled: str = $title_string('sample primitive')
            prefix: str = value.[str]__slice__!(None, 2, None)
            first: str = $get_string_item(value, 0)
        """,
        r"""
        import { title_string as $title_string, get_string_item as $get_string_item } from './pyjs.python.js';

        export function main() {
            var value = 'PyJS';
            var lower = value.toLowerCase();
            var capitalized = ((value)=>value.length?value.charAt(0).toUpperCase()+value.slice(1).toLowerCase():value)('eXAMPLE');
            var titled = $title_string('sample primitive');
            var prefix = [...value].slice(0,2).join('');
            var first = $get_string_item(value, 0);
        }
        """,
    )


def test_str_join():
    at(
        """
        values = ["one", "two"]
        joined = " ".join(values)
        """,
        """
        values: list[str] = ['one', 'two']
        joined: str = ' '.[str]join!(values)
        """,
        """
        var values = ['one', 'two'];
        var joined = values.join(' ');
        """,
    )


def test_browser_json_methods():
    at(
        """
        from pyjs.javascript import JSON, JSONObject

        class Payload(JSONObject):
            name: str

        def main():
            encoded = JSON.stringify(Payload(name="PyJS"))
            decoded: Payload = JSON.parse(encoded)
        """,
        """
        def main() -> None:
            encoded: str = JSON.[JSON]stringify(Payload(name='PyJS'))
            decoded: Payload = JSON.[JSON]parse(encoded)
        """,
        """
        export function main() {
            var encoded = JSON.stringify(({name: 'PyJS'}));
            var decoded = JSON.parse(encoded);
        }
        """,
    )


def test_iframe_window_function_constructor():
    at(
        """
        from pyjs.web.html import HTMLIFrameElement

        def main():
            frame = HTMLIFrameElement()
            frame_window = frame.contentWindow
            if frame_window is None:
                return
            run_bundle = frame_window.Function("return true")
            run_bundle()
        """,
        """
        def main() -> None:
            frame: HTMLIFrameElement = HTMLIFrameElement()
            frame_window: Window | None = frame.contentWindow
            if frame_window.[object]__is__!(None):
                return
            run_bundle: callable = frame_window.[Window]Function!('return true')
            run_bundle()
        """,
        """
        export function main() {
            var frame = new HTMLIFrameElement();
            var frame_window = frame.contentWindow;
            if (frame_window == null) {
                return;
            }
            var run_bundle = new frame_window.Function('return true');
            run_bundle();
        }
        """,
    )


@pytest.mark.parametrize(
    ("py_op", "left_func", "right_func"),
    [
        ("+", "__add__", "__radd__"),
        ("-", "__sub__", "__rsub__"),
        ("*", "__mul__", "__rmul__"),
        ("/", "__truediv__", "__rtruediv__"),
        ("//", "__floordiv__", "__rfloordiv__"),
        ("%", "__mod__", "__rmod__"),
        ("**", "__pow__", "__rpow__"),
    ],
)
def test_arithmetic_overloaded_operators(py_op, left_func, right_func):
    at(
        f"""
        @js
        class B:
            def {right_func}(self, other: str):
              return other
        @js
        class A:
            def {left_func}(self, other: B):
              return self
        @js
        def main():
            a = A();b = B();c = a {py_op} b
        """,
        f"""
        class B:

        class A:

            def {left_func}(other: B) -> A:
                return self

        def main() -> None:
            a: A = A()
            b: B = B()
            c: A = a.[A]{left_func}(b)
        """,
        f"""
        export class B {{
        }}

        export class A {{

            {left_func}(other) {{
                return this;
            }}
        }}

        export function main() {{
            var a = new A();
            var b = new B();
            var c = a.{left_func}(b);
        }}
        """,
    )
    # left side has the correct function but it accepts
    # wrong argument type (str), therefore right
    # func should be used instead
    at(
        f"""
        @js
        class A:
          def {left_func}(self, other: str):
            return self
        @js
        class B:
          def {right_func}(self, other: A):
            return other
        @js
        def main():
            a = A();b = B();c = a {py_op} b
        """,
        f"""
        class A:

        class B:

            def {right_func}(other: A) -> A:
                return other

        def main() -> None:
            a: A = A()
            b: B = B()
            c: A = b.[B]{right_func}(a)
        """,
        f"""
        export class A {{
        }}

        export class B {{

            {right_func}(other) {{
                return other;
            }}
        }}

        export function main() {{
            var a = new A();
            var b = new B();
            var c = b.{right_func}(a);
        }}
        """,
    )


@pytest.mark.parametrize(
    ("py_op", "func_op"),
    [
        ("<", "__lt__"),
        ("<=", "__le__"),
        (">", "__gt__"),
        (">=", "__ge__"),
        ("==", "__eq__"),
        ("!=", "__ne__"),
    ],
)
def test_int_comparators(py_op, func_op):
    at(
        f"""
        a = 1
        b = 2
        c = a {py_op} b
        """,
        f"""
        a: int = 1
        b: int = 2
        c: bool = a.[int]{func_op}!(b)
        """,
        f"""
        var a = 1;
        var b = 2;
        var c = a {py_op} b;
        """,
    )


def test_none_identity_uses_nullish_equality_only_for_none():
    at(
        """
        def main():
            value: object | None = None
            is_missing = value is None
            is_also_missing = None is value
            is_present = value is not None
            is_also_present = None is not value
            not_missing = not (value is None)
            same = True is True
            different = True is not False
        """,
        """
        def main() -> None:
            value: object | None = None
            is_missing: bool = value.[object]__is__!(None)
            is_also_missing: bool = None.[object]__is__!(value)
            is_present: bool = value.[object]__is_not__!(None)
            is_also_present: bool = None.[object]__is_not__!(value)
            not_missing: bool = not value.[object]__is__!(None)
            same: bool = True.[object]__is__!(True)
            different: bool = True.[object]__is_not__!(False)
        """,
        """
        export function main() {
            var value = null;
            var is_missing = value == null;
            var is_also_missing = null == value;
            var is_present = value != null;
            var is_also_present = null != value;
            var not_missing = !(value == null);
            var same = true === true;
            var different = true !== false;
        }
        """,
    )


def test_optional_values_inheriting_object_equality_use_identity_comparison():
    at(
        """
        def main(left: str | None, right: str | None):
            equal = left == right
            different = left != right
        """,
        """
        def main(left: str | None, right: str | None) -> None:
            equal: bool = left.[object]__eq__!(right)
            different: bool = left.[object]__ne__!(right)
        """,
        """
        export function main(left, right) {
            var equal = left === right;
            var different = left !== right;
        }
        """,
    )


def test_optional_containers_retain_dynamic_equality():
    at(
        """
        def main(left: list[int] | None, right: list[int] | None):
            equal = left == right
            different = left != right
        """,
        """
        def main(left: list[int] | None, right: list[int] | None) -> None:
            equal: bool = $equal_value(left, right)
            different: bool = $not_equal_value(left, right)
        """,
        """
        import { equal_value as $equal_value, not_equal_value as $not_equal_value } from './pyjs.python.js';

        export function main(left, right) {
            var equal = $equal_value(left, right);
            var different = $not_equal_value(left, right);
        }
        """,
    )


@pytest.mark.parametrize(
    ("py_op", "left_func", "right_func"),
    [
        ("<", "__lt__", "__gt__"),
        ("<=", "__le__", "__ge__"),
        (">", "__gt__", "__lt__"),
        (">=", "__ge__", "__le__"),
        ("==", "__eq__", "__eq__"),
        ("!=", "__ne__", "__ne__"),
    ],
)
def test_overloaded_comparators(py_op, left_func, right_func):
    at(
        f"""
        @js
        class B:
          pass
        @js
        class A:
          def {left_func}(self, other: B) -> bool:
            return False
        @js
        def main():
            a = A();b = B();c = a {py_op} b
        """,
        f"""
        class B:

        class A:

            def {left_func}(other: B) -> bool:
                return False

        def main() -> None:
            a: A = A()
            b: B = B()
            c: bool = a.[A]{left_func}(b)
        """,
        f"""
        export class B {{
        }}

        export class A {{

            {left_func}(other) {{
                return false;
            }}
        }}

        export function main() {{
            var a = new A();
            var b = new B();
            var c = a.{left_func}(b);
        }}
        """,
    )
    at(
        f"""
        @js
        class A:
          pass
        @js
        class B:
          def {right_func}(self, other: A) -> bool:
            return False
        @js
        def main():
            a = A();b = B();c = a {py_op} b
        """,
        f"""
        class A:

        class B:

            def {right_func}(other: A) -> bool:
                return False

        def main() -> None:
            a: A = A()
            b: B = B()
            c: bool = b.[B]{right_func}(a)
        """,
        f"""
        export class A {{
        }}

        export class B {{

            {right_func}(other) {{
                return false;
            }}
        }}

        export function main() {{
            var a = new A();
            var b = new B();
            var c = b.{right_func}(a);
        }}
        """,
    )
