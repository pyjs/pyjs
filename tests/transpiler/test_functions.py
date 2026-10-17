import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.javascript.transpiler import bundle_import
from pyjs.testing.helpers import (
    aat,
    ad,
    analyze_module_source,
    assert_module_transpile,
    assert_transpile,
    at,
    diagnostic_text,
)


def test_abstract_iterable_loop_selects_mapping_keys_at_acquisition():
    assert_module_transpile(
        '''
        from collections.abc import Iterable
        from pyjs import js
        @js
        def main(values: Iterable[int]) -> int:
            result = 0
            for value in values:
                result += value
            return result
        ''',
        '''
        export function main(values) {
            var result = 0;
            for (var value of ((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)(values)) {
                result = result + value;
            }
            return result;
        }
        ''',
    )


@pytest.mark.parametrize("handler, emitted", [
    ("self.show_message()", "this.show_message();"),
    ("return self.show_message()", "return this.show_message();"),
])
def test_event_registration_does_not_depend_on_handler_body(handler, emitted):
    assert_module_transpile(
        f'''
        from pyjs import js
        from pyjs.web.dom import document
        from pyjs.web.events import Event

        @js
        class App:
            def __init__(self):
                self.button = document.createElement("button")
                self.button.addEventListener("click", self.clicked)
                self.message = "ready"

            def clicked(self, event: Event):
                {handler}

            def show_message(self):
                print(self.message)
                return self.message

        def main():
            App()
        ''',
        f'''
        export class App {{

            constructor() {{
                this.button = document.createElement('button');
                this.button.addEventListener('click', this.clicked.bind(this));
                this.message = 'ready';
            }}

            clicked(event) {{
                {emitted}
            }}

            show_message() {{
                console.log(this.message);
                return this.message;
            }}
        }}

        export function main() {{
            new App();
        }}
        ''',
    )


def test_registered_unannotated_handler_body_is_still_checked():
    with pytest.raises(CompilationError, match="Attribute 'missing' is not defined on 'str'"):
        analyze_module_source('''
            from pyjs import js
            from pyjs.web.dom import document
            from pyjs.web.events import Event

            @js
            class App:
                def __init__(self):
                    self.button = document.createElement("button")
                    self.button.addEventListener("click", self.clicked)
                    self.message = "ready"

                def clicked(self, event: Event):
                    return self.message.missing()

            def main():
                App()
        ''')


@pytest.mark.parametrize("annotation", ["callable | None", "object"])
def test_keyword_registration_can_infer_fields_after_callback(annotation):
    assert_module_transpile(
        f'''
        from pyjs import js

        @js
        def register(*, callback: {annotation}) -> None:
            pass

        @js
        class App:
            def __init__(self):
                register(callback=self.clicked)
                self.message = "ready"

            def clicked(self):
                return self.message

        def main():
            App()
        ''',
        '''
        export function register({ callback} = {}) {
        }

        export class App {

            constructor() {
                register({callback: this.clicked.bind(this)});
                this.message = 'ready';
            }

            clicked() {
                return this.message;
            }
        }

        export function main() {
            new App();
        }
        ''',
    )


@pytest.mark.parametrize("argument", ["callback", "callback=callback"])
def test_typed_callback_still_checks_unannotated_return(argument):
    with pytest.raises(CompilationError, match="returns int, expected str"):
        analyze_module_source(f'''
            from pyjs import js
            from collections.abc import Callable

            @js
            def use(callback: Callable[[], str]) -> str:
                return callback()

            @js
            def start() -> str:
                return use({argument})

            @js
            def callback():
                return 42

            def main():
                print(start())
        ''')


def test_bound_method_values_keep_their_signature_and_receiver():
    at(
        '''
        from collections.abc import Callable as Callback

        @js
        class Counter:
            def __init__(self, value: int):
                self.value = value

            def read(self) -> int:
                return self.value

        @js
        def bind(counter: Counter) -> Callback[[], int]:
            return counter.read

        def main(counter: Counter) -> int:
            saved = counter.read
            return saved() + bind(counter)()
        ''',
        '''
        class Counter:

            def __init__(value: int) -> None:
                self.value = value

            def read() -> int:
                return self.value

        def bind(counter: Counter) -> Callable[[], int]:
            return counter.[Counter]read

        def main(counter: Counter) -> int:
            saved: Callable[[], int] = counter.[Counter]read
            return saved().[int]__add__!(bind(counter)())
        ''',
        '''
        export class Counter {

            constructor(value) {
                this.value = value;
            }

            read() {
                return this.value;
            }
        }

        export function bind(counter) {
            return counter.read.bind(counter);
        }

        export function main(counter) {
            var saved = counter.read.bind(counter);
            return saved() + bind(counter)();
        }
        ''',
    )


def test_infer_returns_None():
    aat(
        """
        def main():
            return
        """,
        """
        def main() -> None:
            return
        """,
        """
        export function main() {
            return;
        }
        """
    )
    at(
        """
        @js
        class Foo:
            def bar(self):
                return
        def main():
            Foo().bar()
        """,
        """
        class Foo:

            def bar() -> None:
                return

        def main() -> None:
            Foo().[Foo]bar()
        """,
        """
        export class Foo {

            bar() {
                return;
            }
        }

        export function main() {
            new Foo().bar();
        }
        """
    )


def test_infer_implicit_none_fallthrough():
    at(
        """
        @js
        def get_value(flag: bool):
            if flag:
                return 1

        def main():
            value = get_value(True)
        """,
        """
        def get_value(flag: bool) -> int | None:
            if flag:
                return 1

        def main() -> None:
            value: int | None = get_value(True)
        """,
        """
        export function get_value(flag) {
            if (flag) {
                return 1;
            }
        }

        export function main() {
            var value = get_value(true);
        }
        """
    )
    at(
        """
        @js
        def consume():
            value = 1

        def main():
            consume()
        """,
        """
        def consume() -> None:
            value: int = 1

        def main() -> None:
            consume()
        """,
        """
        export function consume() {
            var value = 1;
        }

        export function main() {
            consume();
        }
        """
    )


def test_function_and_method_docstrings_are_not_emitted():
    assert_transpile(
        '''
        @js
        class Counter:
            """Count values on the client."""

            def increment(self, value: int) -> int:
                """Return the next value."""
                return value + 1

        @js
        def doubled(value: int) -> int:
            """Double one value."""
            return value * 2

        def main():
            print(Counter().increment(doubled(2)))
        ''',
        """
        export class Counter {

            increment(value) {
                return value + 1;
            }
        }

        export function doubled(value) {
            return value * 2;
        }

        export function main() {
            console.log(new Counter().increment(doubled(2)));
        }
        """,
    )


def test_immediately_invoked_lambdas_remain_callable_values():
    at(
        """
        def main():
            first = (lambda: 3)()
            second = (lambda value: 4)(2)
        """,
        """
        def main() -> None:
            first: int = (lambda: 3)()
            second: int = (lambda value: 4)(2)
        """,
        """
        export function main() {
            var first = (() => 3)();
            var second = ((value) => 4)(2);
        }
        """,
    )


def test_instances_dispatch_calls_through_their_call_method():
    assert_transpile(
        """
        @js
        class Add:
            def __call__(self, value: int) -> int:
                return value + 1

        @js
        class Double(Add):
            def __call__(self, value: int) -> int:
                return value * 2

        def main():
            add = Add()
            first = add(2)
            second = Add()(3)
            third = Double()(4)
        """,
        """
        export class Add {

            __call__(value) {
                return value + 1;
            }
        }

        export class Double extends Add {

            __call__(value) {
                return value * 2;
            }
        }

        export function main() {
            var add = new Add();
            var first = add.__call__(2);
            var second = new Add().__call__(3);
            var third = new Double().__call__(4);
        }
        """,
    )


def test_instance_call_arguments_are_validated_against_call_method():
    ad(
        """\
        from pyjs import js

        @js
        class Add:
            def __call__(self, value: int) -> int:
                return value + 1

        def main():
            Add()("two")
        """,
        diagnostic_text(
            "callable_instance.py",
            9,
            'Add()("two")',
            "      ^^^^^",
            "pyjs.CompilationError: Argument 'value' to Add.__call__ expects "
            "int, got str [PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="callable_instance.py",
    )


def test_javascript_reserved_words_are_escaped_only_for_bindings():
    at(
        """
        @js
        def default(static: int, package: int = 1) -> int:
            delete = static + package
            return delete

        @js
        class static:
            def default(self, value: int) -> int:
                return value

        def main():
            new = default(2, package=3)
            print(static().default(new))
        """,
        """
        def default(static: int, package: int=1) -> int:
            delete: int = static.[int]__add__!(package)
            return delete

        class static:

            def default(value: int) -> int:
                return value

        def main() -> None:
            new: int = default(2, package=3)
            print(static().[static]default(new))
        """,
        """
        export function $$default($$static, { package: $$package=1} = {}) {
            var $$delete = $$static + $$package;
            return $$delete;
        }

        export class $$static {

            default(value) {
                return value;
            }
        }

        export function main() {
            var $$new = $$default(2, {package: 3});
            console.log(new $$static().default($$new));
        }
        """,
    )


def test_javascript_reserved_words_remain_class_member_names():
    assert_transpile(
        """
        @js
        class KeyCodes:
            delete = 67

        def main() -> int:
            return KeyCodes.delete
        """,
        """
        export class KeyCodes {
            static delete = 67;
        }

        export function main() {
            return KeyCodes.delete;
        }
        """,
    )


def test_infer_arg_and_return_from_default_value():
    at(
        """
        @js
        def bar(n = 1):
            return n + n
        def main():
            i = bar()
        """,
        """
        def bar(n: int=1) -> int:
            return n.[int]__add__!(n)
        
        def main() -> None:
            i: int = bar()
        """,
        """
        export function bar({ n=1} = {}) {
            return n + n;
        }

        export function main() {
            var i = bar();
        }
        """
    )
    at(
        """
        @js
        class Foo:
            def bar(self, n=1):
                return n+n
        def main():
            i = Foo().bar()
        """,
        """
        class Foo:

            def bar(n: int=1) -> int:
                return n.[int]__add__!(n)

        def main() -> None:
            i: int = Foo().[Foo]bar()
        """,
        """
        export class Foo {

            bar({ n=1} = {}) {
                return n + n;
            }
        }

        export function main() {
            var i = new Foo().bar();
        }
        """
    )


def test_positional_values_for_default_parameters_use_the_options_object():
    at(
        """
        @js
        def add(value: int, amount: int = 1):
            return value + amount
        def main():
            result = add(2, 3)
        """,
        """
        def add(value: int, amount: int=1) -> int:
            return value.[int]__add__!(amount)

        def main() -> None:
            result: int = add(2, 3)
        """,
        """
        export function add(value, { amount=1} = {}) {
            return value + amount;
        }

        export function main() {
            var result = add(2, {amount: 3});
        }
        """,
    )


def test_default_parameters_precede_varargs_at_call_site():
    at(
        """
        @js
        def format_items(prefix: str, separator: str = ", ", *items: str):
            return prefix + separator.join(items)
        def main():
            result = format_items("Items: ", " / ", "one", "two")
        """,
        """
        def format_items(prefix: str, separator: str=', ', *items: tuple__str__variadic) -> str:
            return prefix.[str]__add__!(separator.[str]join!(items))

        def main() -> None:
            result: str = format_items('Items: ', ' / ', 'one', 'two')
        """,
        """
        export function format_items(prefix, { separator=', '} = {}, ...items) {
            return prefix + items.join(separator);
        }

        export function main() {
            var result = format_items('Items: ', {separator: ' / '}, 'one', 'two');
        }
        """,
    )


def test_keyword_only_parameters_use_the_options_object():
    at(
        """
        @js
        def describe(name: str, *, prefix: str, emphasized: bool = False):
            return prefix + name if emphasized else name
        def main():
            result = describe("one", prefix="Entry", emphasized=True)
        """,
        """
        def describe(name: str, *, prefix: str, emphasized: bool=False) -> str:
            return prefix.[str]__add__!(name) if emphasized else name

        def main() -> None:
            result: str = describe('one', prefix='Entry', emphasized=True)
        """,
        """
        export function describe(name, { prefix, emphasized=false} = {}) {
            return emphasized ? prefix + name : name;
        }

        export function main() {
            var result = describe('one', {prefix: 'Entry', emphasized: true});
        }
        """,
    )


def test_required_parameters_accept_reordered_keywords():
    at(
        """
        @js
        def subtract(a: int, b: int) -> int:
            return a - b

        def main():
            reordered = subtract(b=2, a=5)
            mixed = subtract(8, b=3)
        """,
        """
        def subtract(a: int, b: int) -> int:
            return a.[int]__sub__!(b)

        def main() -> None:
            reordered: int = subtract(b=2, a=5)
            mixed: int = subtract(8, b=3)
        """,
        """
        export function subtract(a, b) {
            return a - b;
        }

        export function main() {
            var reordered = subtract(5, 2);
            var mixed = subtract(8, 3);
        }
        """,
    )


def test_positional_only_and_keyword_only_parameters_preserve_call_shape():
    at(
        """
        @js
        def adjust(
            value: int,
            amount: int = 1,
            /,
            *,
            double: bool = False,
        ) -> int:
            result = value + amount
            return result * 2 if double else result

        def main():
            result = adjust(8, 2, double=True)
        """,
        """
        def adjust(value: int, amount: int=1, /, *, double: bool=False) -> int:
            result: int = value.[int]__add__!(amount)
            return result.[int]__mul__!(2) if double else result

        def main() -> None:
            result: int = adjust(8, 2, double=True)
        """,
        """
        export function adjust(value, { $1: amount=1, double=false} = {}) {
            var result = value + amount;
            return double ? result * 2 : result;
        }

        export function main() {
            var result = adjust(8, {$1: 2, double: true});
        }
        """,
    )


def test_literal_keyword_expansion_is_statically_lowered():
    at(
        """
        @js
        def subtract(a: int, b: int) -> int:
            return a - b

        def main():
            result = subtract(**{"b": 2, "a": 5})
        """,
        """
        def subtract(a: int, b: int) -> int:
            return a.[int]__sub__!(b)

        def main() -> None:
            result: int = subtract(b=2, a=5)
        """,
        """
        export function subtract(a, b) {
            return a - b;
        }

        export function main() {
            var result = subtract(5, 2);
        }
        """,
    )


def test_keyword_lowering_does_not_mutate_the_analyzed_tree():
    expected = """\
export function subtract(a, b) {
    return a - b;
}

export function main() {
    console.log(subtract(5, 2));
}"""
    with analyze_module_source(
        """
        from pyjs import js

        @js
        def subtract(a: int, b: int) -> int:
            return a - b

        def main():
            print(subtract(b=2, a=5))
        """
    ) as analysis:
        first = analysis.javascript
        second = analysis.javascript
    assert first == expected
    assert second == expected


def test_var_keyword_arguments_use_python_dict_semantics():
    at(
        """
        @js
        def describe(*labels: str, **values: int) -> int:
            return len(labels) + values.get("count", 0)

        def main():
            result = describe("a", "b", count=3)
        """,
        """
        def describe(*labels: tuple__str__variadic, **values: dict__str_int) -> int:
            return labels.[tuple__str__variadic]__len__!().[int]__add__!(values.[dict__str_int]get!('count', 0))

        def main() -> None:
            result: int = describe('a', 'b', count=3)
        """,
        """
        export function describe({ ...$values} = {}, ...labels) {
            var values = new Map(Object.entries($values));
            return labels.length + ((mapping,key,fallback)=>mapping.has(key)?mapping.get(key):fallback)(values,'count',0);
        }

        export function main() {
            var result = describe({count: 3}, 'a', 'b');
        }
        """,
    )


def test_positional_only_names_remain_available_to_var_keywords():
    at(
        """
        @js
        def capture(value: int = 1, /, **named: int) -> int:
            return value + named.get("value", 0)

        def main():
            positional = capture(2)
            keyword = capture(value=3)
        """,
        """
        def capture(value: int=1, /, **named: dict__str_int) -> int:
            return value.[int]__add__!(named.[dict__str_int]get!('value', 0))

        def main() -> None:
            positional: int = capture(2)
            keyword: int = capture(value=3)
        """,
        """
        export function capture({ $0: value=1, ...$named} = {}) {
            var named = new Map(Object.entries($named));
            return value + ((mapping,key,fallback)=>mapping.has(key)?mapping.get(key):fallback)(named,'value',0);
        }

        export function main() {
            var positional = capture({$0: 2});
            var keyword = capture({value: 3});
        }
        """,
    )


def test_dictionary_constructor_merges_source_types_and_positional_only_keyword_names():
    at('''
        def main():
            base = {"first": 1}
            merged = dict(base, word="value")
            pairs = dict([("first", [1, 2])], word="value")
            mixed_pairs = dict((("first", [1, 2]), ("word", "value")), last="tail")
            named = dict(values=7, fields=8)
    ''', '''
        def main() -> None:
            base: dict[str, int] = {'first': 1}
            merged: dict[str, int | str] = dict__str_intUstr(base, word='value')
            pairs: dict[str, list[int] | str] = dict__str_list__intUstr([('first', [1, 2])], word='value')
            mixed_pairs: dict[str, list[int] | str] = dict__str_list__intUstr((('first', [1, 2]), ('word', 'value')), last='tail')
            named: dict[str, int] = dict__str_int(values=7, fields=8)
    ''', '''
        export function main() {
            var base = new Map([['first', 1]]);
            var merged = new Map([...base, ['word', 'value']]);
            var pairs = new Map([...[['first', [1, 2]]], ['word', 'value']]);
            var mixed_pairs = new Map([...[['first', [1, 2]], ['word', 'value']], ['last', 'tail']]);
            var named = new Map([['values', 7], ['fields', 8]]);
        }
    ''')


def test_positional_only_keyword_names_use_the_var_keyword_value_type():
    at(
        """\
        @js
        def capture(value: int = 1, /, **named: str) -> str:
            return named.get("value", "")

        def main():
            result = capture(value="keyword")
        """,
        """
        def capture(value: int=1, /, **named: dict__str_str) -> str:
            return named.[dict__str_str]get!('value', '')

        def main() -> None:
            result: str = capture(value='keyword')
        """,
        """
        export function capture({ $0: value=1, ...$named} = {}) {
            var named = new Map(Object.entries($named));
            return ((mapping,key,fallback)=>mapping.has(key)?mapping.get(key):fallback)(named,'value','');
        }

        export function main() {
            var result = capture({value: 'keyword'});
        }
        """,
    )


def test_overloads_do_not_match_positional_only_parameters_by_keyword():
    at(
        """\
        from typing import overload

        @overload
        def select(value: int, /) -> int: ...

        @overload
        def select(**named: str) -> str: ...

        @js
        def select(value: object = None, /, **named: object) -> object: ...

        def main():
            positional = select(1)
            keyword = select(value="keyword")
        """,
        """
        def select(value: object=None, /, **named: dict__str_object) -> object:
            pass

        def main() -> None:
            positional: int = select(1)
            keyword: str = select(value='keyword')
        """,
        """
        export function select({ $0: value=null, ...$named} = {}) {
            var named = new Map(Object.entries($named));
        }

        export function main() {
            var positional = select({$0: 1});
            var keyword = select({value: 'keyword'});
        }
        """,
    )


def test_union_arguments_accept_nominal_and_structural_iterable_members():
    at(
        """\
        from collections.abc import Iterable

        @js
        def accept(
            values: dict[str, int] | Iterable[tuple[str, int]],
        ) -> None: ...

        def main():
            accept({"one": 1})
            accept([("two", 2)])
        """,
        """
        def accept(values: dict[str, int] | Iterable[tuple[str, int]]) -> None:
            pass

        def main() -> None:
            accept({'one': 1})
            accept([('two', 2)])
        """,
        """
        export function accept(values) {
        }

        export function main() {
            accept(new Map([['one', 1]]));
            accept([['two', 2]]);
        }
        """,
    )


def test_lambdas_use_type_variables_bound_by_later_arguments():
    at(
        """\
        from collections.abc import Callable

        @js
        def apply[T, R](function: Callable[[T], R], value: T) -> R:
            return function(value)

        def main():
            result = apply(lambda value: value + 1, 4)
            keyword_result = apply(
                function=lambda value: value + 2,
                value=5,
            )
        """,
        """
        def apply(function: Callable[[T], R], value: T) -> R:
            return function(value)

        def main() -> None:
            result: int = apply(lambda value: value.[int]__add__!(1), 4)
            keyword_result: int = apply(function=lambda value: value.[int]__add__!(2), value=5)
        """,
        """
        export function apply($$function, value) {
            return $$function(value);
        }

        export function main() {
            var result = apply((value) => value + 1, 4);
            var keyword_result = apply((value) => value + 2, 5);
        }
        """,
    )


def test_concrete_callable_signatures_still_contextually_type_lambdas():
    at(
        """\
        from collections.abc import Callable

        def main(
            callback: Callable[[Callable[[int], str], int], str],
        ):
            label = callback(lambda value: str(value), 3)
        """,
        """
        def main(callback: Callable[[Callable[[int], str], int], str]) -> None:
            label: str = callback(lambda value: value.[int]__str__!(), 3)
        """,
        """
        export function main(callback) {
            var label = callback((value) => String(value), 3);
        }
        """,
    )


def test_filter_requires_a_boolean_predicate():
    ad(
        """\
        def main():
            values = filter(lambda value: value, [1])
        """,
        diagnostic_text(
            "filter_predicate.py",
            2,
            "values = filter(lambda value: value, [1])",
            " " * 16 + "^" * 19,
            "pyjs.CompilationError: Callable argument 'function' to filter "
            "returns int, expected bool [PYJS1104]",
            "help: Change the callable return annotation or returned values.",
        ),
        filename="filter_predicate.py",
    )


def test_map_preserves_multiple_iterable_types():
    at(
        """
        def main():
            values = map(
                lambda number, label: label * number,
                [1, 2],
                ["a", "b"],
            )
        """,
        """
        def main() -> None:
            values: Iterator[str] = map(lambda number, label: label.[str]__mul__!(number), [1, 2], ['a', 'b'])
        """,
        """
        export function main() {
            var values = (function*($function,iterables){const iterators=iterables.map(value=>value[Symbol.iterator]());while(true){const values=[];for(const iterator of iterators){const result=iterator.next();if(result.done)return;values.push(result.value);}yield $function(...values);}})((number, label) => (number <= 0 ? '' : label.repeat(number)),[[1, 2],['a', 'b']]);
        }
        """,
    )


def test_map_rejects_more_iterables_than_it_can_type_statically():
    ad(
        """\
        def main():
            values = map(
                lambda a, b, c, d, e, f: a,
                [1],
                [2],
                [3],
                [4],
                [5],
                [6],
            )
        """,
        diagnostic_text(
            "map_iterables.py",
            9,
            "[6],",
            "^" * 3,
            "pyjs.CompilationError: map() supports at most 5 iterables "
            "[PYJS2001]",
            "help: Define a typed loop when mapping more iterables in one "
            "operation.",
        ),
        filename="map_iterables.py",
    )


def test_constructor_parameters_accept_reordered_keywords():
    at(
        """
        @js
        class Span:
            def __init__(self, start: int, end: int):
                self.start = start
                self.end = end

        def main():
            span = Span(end=5, start=2)
        """,
        """
        class Span:

            def __init__(start: int, end: int) -> None:
                self.start = start
                self.end = end

        def main() -> None:
            span: Span = Span(end=5, start=2)
        """,
        """
        export class Span {

            constructor(start, end) {
                this.start = start;
                this.end = end;
            }
        }

        export function main() {
            var span = new Span(2, 5);
        }
        """,
    )


@pytest.mark.parametrize(
    ("call", "underline", "message", "help_text"),
    (
        (
            "combine(value=1, other=2)",
            " " * 14 + "^" * 7,
            "combine() parameter 'value' is positional-only",
            "Pass 'value' as a positional argument.",
        ),
        (
            "combine(1, other=2, extra=3)",
            " " * 26 + "^" * 7,
            "combine() got an unexpected keyword argument 'extra'",
            "Use a parameter name from the function signature.",
        ),
        (
            "combine(1)",
            " " * 6 + "^" * 10,
            "combine() is missing required argument(s): 'other'",
            "Pass every required argument.",
        ),
        (
            "combine(1, 2, 3)",
            " " * 20 + "^",
            "combine() received too many positional arguments",
            "Pass at most 2 positional arguments.",
        ),
    ),
)
def test_invalid_call_shapes_have_focused_diagnostics(
    call,
    underline,
    message,
    help_text,
):
    ad(
        f"""\
        from pyjs import js

        @js
        def combine(value: int, /, other: int) -> int:
            return value + other

        def main():
            print({call})
        """,
        diagnostic_text(
            "call_shape.py",
            8,
            f"print({call})",
            underline,
            f"pyjs.CompilationError: {message} [PYJS1104]",
            f"help: {help_text}",
        ),
        filename="call_shape.py",
    )


def test_duplicate_argument_has_a_focused_diagnostic():
    ad(
        """\
        from pyjs import js

        @js
        def combine(value: int, other: int) -> int:
            return value + other

        def main():
            print(combine(1, value=2, other=3))
        """,
        diagnostic_text(
            "duplicate_argument.py",
            8,
            "print(combine(1, value=2, other=3))",
            " " * 17 + "^" * 7,
            "pyjs.CompilationError: combine() received multiple values for "
            "'value' [PYJS1104]",
            "help: Pass 'value' only once.",
        ),
        filename="duplicate_argument.py",
    )


def test_dynamic_keyword_expansion_has_a_focused_diagnostic():
    ad(
        """\
        from pyjs import js

        @js
        def combine(value: int, other: int) -> int:
            return value + other

        def main():
            arguments = {"value": 1, "other": 2}
            print(combine(**arguments))
        """,
        diagnostic_text(
            "dynamic_keywords.py",
            9,
            "print(combine(**arguments))",
            " " * 16 + "^" * 9,
            "pyjs.CompilationError: dynamic ** argument expansion is not "
            "supported [PYJS2001]",
            "help: Pass named arguments or expand a literal string-keyed "
            "dictionary.",
        ),
        filename="dynamic_keywords.py",
    )


def test_keyword_only_options_precede_varargs_at_call_site():
    at(
        """
        @js
        def render(*children: str, variant: str = "default") -> str:
            return variant + ":" + "".join(children)
        def main():
            first = render("Save")
            second = render("Delete", variant="destructive")
        """,
        """
        def render(*children: tuple__str__variadic, variant: str='default') -> str:
            return variant.[str]__add__!(':').[str]__add__!(''.[str]join!(children))

        def main() -> None:
            first: str = render('Save')
            second: str = render('Delete', variant='destructive')
        """,
        """
        export function render({ variant='default'} = {}, ...children) {
            return variant + ':' + children.join('');
        }

        export function main() {
            var first = render({}, 'Save');
            var second = render({variant: 'destructive'}, 'Delete');
        }
        """,
    )


def test_keyword_only_options_precede_varargs_for_custom_element_subclasses():
    assert_transpile(
        """
        from pyjs.web.domx import CustomElement

        @js
        class Panel(CustomElement):
            def __init__(self, *children: str, variant: str = "default"):
                super().__init__()
                self.setAttribute("data-variant", variant)

        def main():
            panel = Panel("Content", variant="outline")
        """,
        """
        import { CustomElement } from './pyjs.web.domx.js';

        export class Panel extends CustomElement {

            _create({ variant='default'} = {}, ...children) {
                super._create();
                this.setAttribute('data-variant', variant);
                return this;
            }

            _hydrate() {
                super._hydrate();
            }
        }
        customElements.define('pyjs-panel', Panel)

        export function main() {
            var panel = new Panel()._create({variant: 'outline'}, 'Content');
        }
        """,
    )


def test_positional_defaults_and_keyword_only_parameters_share_options_object():
    at(
        """
        @js
        def wrap(prefix: str, separator: str = ",", *values: str, suffix: str = "") -> str:
            return prefix + separator.join(values) + suffix
        def main():
            result = wrap("[", " / ", "one", "two", suffix="]")
        """,
        """
        def wrap(prefix: str, separator: str=',', *values: tuple__str__variadic, suffix: str='') -> str:
            return prefix.[str]__add__!(separator.[str]join!(values)).[str]__add__!(suffix)

        def main() -> None:
            result: str = wrap('[', ' / ', 'one', 'two', suffix=']')
        """,
        """
        export function wrap(prefix, { separator=',', suffix=''} = {}, ...values) {
            return prefix + values.join(separator) + suffix;
        }

        export function main() {
            var result = wrap('[', {separator: ' / ', suffix: ']'}, 'one', 'two');
        }
        """,
    )


def test_partial_client_implementation_is_analyzed_as_a_normal_dependency():
    at(
        """
        from functools import partial

        @js
        def join(prefix: str, *values: str) -> str:
            return prefix + ", ".join(values)

        @js
        def format_values(*values: str) -> str:
            return ", ".join(values)

        format_values.client(partial(join, "Values: "))

        def main():
            result = format_values("one", "two")
        """,
        """
        def join(prefix: str, *values: tuple__str__variadic) -> str:
            return prefix.[str]__add__!(', '.[str]join!(values))

        def format_values(*values: tuple__str__variadic) -> str:
            return join('Values: ', *values)

        def main() -> None:
            result: str = format_values('one', 'two')
        """,
        """
        export function join(prefix, ...values) {
            return prefix + values.join(', ');
        }

        export function format_values(...values) {
            return join('Values: ', ...values);
        }

        export function main() {
            var result = format_values('one', 'two');
        }
        """,
    )


def test_builtin_default_parameters_remain_positional():
    at(
        """
        from pyjs.web.dom import DOMTokenList

        def main():
            tokens = DOMTokenList()
            active = tokens.toggle("active", True)
        """,
        """
        def main() -> None:
            tokens: DOMTokenList = DOMTokenList()
            active: bool = tokens.[DOMTokenList]toggle('active', True)
        """,
        """
        export function main() {
            var tokens = new DOMTokenList();
            var active = tokens.toggle('active', true);
        }
        """,
    )


def test_infer_return_from_annotated_arg():
    at(
        """
        @js
        def bar(n: int):
            return n + n
        def main():
            i = bar(1)
        """,
        """
        def bar(n: int) -> int:
            return n.[int]__add__!(n)
        
        def main() -> None:
            i: int = bar(1)
        """,
        """
        export function bar(n) {
            return n + n;
        }

        export function main() {
            var i = bar(1);
        }
        """
    )


def test_async_function_and_await():
    at(
        """
        @js
        async def fetch_value(value: str) -> str:
            return value

        async def main():
            pending = fetch_value("later")
            result = await fetch_value("ready")
        """,
        """
        async def fetch_value(value: str) -> str:
            return value

        async def main() -> None:
            pending: Awaitable[str] = fetch_value('later')
            result: str = await fetch_value('ready')
        """,
        """
        export async function fetch_value(value) {
            return value;
        }

        export async function main() {
            var pending = fetch_value('later');
            var result = await fetch_value('ready');
        }
        """,
    )


def test_async_method_and_await():
    at(
        """
        @js
        class Loader:
            async def load(self, value: str) -> str:
                return value

        async def main():
            loader = Loader()
            result = await loader.load("ready")
        """,
        """
        class Loader:

            async def load(value: str) -> str:
                return value

        async def main() -> None:
            loader: Loader = Loader()
            result: str = await loader.[Loader]load('ready')
        """,
        """
        export class Loader {

            async load(value) {
                return value;
            }
        }

        export async function main() {
            var loader = new Loader();
            var result = await loader.load('ready');
        }
        """,
    )


def test_aliased_import_uses_local_name():
    assert_transpile(
        """
        from pyjs.testing.client.runtime import BrowserTest
        from pyjs.testing.client.runtime import run_selected_tests as execute_tests

        def main():
            selected_tests: list[BrowserTest] = []
            execute_tests(selected_tests)
        """,
        """
        import { run_selected_tests as execute_tests } from './pyjs.testing.client.runtime.js';

        export function main() {
            var selected_tests = [];
            execute_tests(selected_tests);
        }
        """,
    )


def test_aliased_import_of_static_browser_object_resolves_builtin_global():
    assert_transpile(
        """
        from pyjs.web.storage import navigator as storage_navigator

        def main():
            return storage_navigator.storage
        """,
        """
        export function main() {
            return navigator.storage;
        }
        """,
    )


def test_bundled_aliased_import_uses_destructuring_rename():
    assert bundle_import(
        "tests.example",
        [("test_original", "test_alias"), ("test_unchanged", "test_unchanged")],
    ) == (
        "const {test_original: test_alias, test_unchanged} = "
        "__import_js__('tests.example');"
    )


def test_bundled_side_effect_import_is_deferred_until_module_is_defined():
    assert bundle_import("tests.models", []) == (
        "__import_js__.defer('tests.models');"
    )


def test_async_browser_transport_apis():
    at(
        """
        from pyjs.web.dom import localStorage, location, window
        from pyjs.web.events import MessageEvent
        from pyjs.javascript import encodeURIComponent
        from pyjs.web.network import WebSocket, fetch

        async def main():
            socket = WebSocket("ws://" + location.host + "/ws")
            socket.send("ready")
            localStorage.setItem("route", location.hash)
            location.hash = "#/active"
            event = MessageEvent("message")
            message = event.data
            response = await fetch("/bundle.js?run_id=" + encodeURIComponent("run 1"))
            source = await response.text()
            await fetch("/result", {"method": "POST", "body": source})
            await fetch("/options", window)
        """,
        """
        async def main() -> None:
            socket: WebSocket = WebSocket('ws://'.[str]__add__!(location.host).[str]__add__!('/ws'))
            socket.[WebSocket]send('ready')
            localStorage.[Storage]setItem('route', location.hash)
            location.hash = '#/active'
            event: MessageEvent = MessageEvent('message')
            message: object = event.data
            response: Response = await fetch('/bundle.js?run_id='.[str]__add__!(encodeURIComponent('run 1')))
            source: str = await response.[Response]text()
            await fetch('/result', {'method': 'POST', 'body': source})
            await fetch('/options', window)
        """,
        """
        export async function main() {
            var socket = new WebSocket('ws://' + location.host + '/ws');
            socket.send('ready');
            localStorage.setItem('route', location.hash);
            location.hash = '#/active';
            var event = new MessageEvent('message');
            var message = event.data;
            var response = await fetch('/bundle.js?run_id=' + encodeURIComponent('run 1'));
            var source = await response.text();
            await fetch('/result', (options => options instanceof Map ? Object.fromEntries(options) : options)(new Map([['method', 'POST'], ['body', source]])));
            await fetch('/options', (options => options instanceof Map ? Object.fromEntries(options) : options)(window));
        }
        """,
    )


def test_await_rejects_sync_call():
    ad(
        """\
        from pyjs import js

        @js
        def get_value() -> str:
            return "ready"

        @js
        async def main():
            result = await get_value()
        """,
        diagnostic_text(
            "await.py",
            9,
            "result = await get_value()",
            "               ^^^^^^^^^^^",
            "pyjs.CompilationError: Cannot await value of type str [PYJS1104]",
            "help: Await an Awaitable value, usually by calling an async function.",
        ),
        filename="await.py",
    )


def test_annotated_return_rejects_pass_stub():
    ad(
        """\
        from pyjs import js

        @js
        def bar() -> int:
            pass

        def main():
            i = bar()
        """,
        diagnostic_text(
            "return_pass.py",
            4,
            "def bar() -> int:",
            " " * 13 + "^^^",
            "pyjs.CompilationError: Function returns NoneType, not int [PYJS1105]",
            "help: Change the return annotation or return values so their types match.",
        ),
        filename="return_pass.py",
    )


def test_annotated_return_rejects_an_incompatible_value():
    ad(
        """\
        from pyjs import js

        @js
        def label() -> str:
            return 1

        def main():
            print(label())
        """,
        diagnostic_text(
            "return_value.py",
            4,
            "def label() -> str:",
            " " * 15 + "^^^",
            "pyjs.CompilationError: Function returns int, not str [PYJS1105]",
            "help: Change the return annotation or return values so their types match.",
        ),
        filename="return_value.py",
    )


def test_annotated_returns_infer_empty_container_types():
    at(
        """
        @js
        def empty_values() -> list[str]:
            return []

        @js
        def empty_mapping() -> dict[str, int]:
            return {}

        @js
        def empty_coordinates() -> tuple[int, ...]:
            return ()

        @js
        def empty_set() -> set[int]:
            return set()

        @js
        def optional_values(found: bool) -> list[str] | None:
            if found:
                return []
            return None

        def main():
            print(
                len(empty_values()),
                len(empty_mapping()),
                len(empty_coordinates()),
                len(empty_set()),
                optional_values(True),
            )
        """,
        """
        def empty_values() -> list[str]:
            return []

        def empty_mapping() -> dict[str, int]:
            return {}

        def empty_coordinates() -> tuple[int, ...]:
            return ()

        def empty_set() -> set[int]:
            return set__int()

        def optional_values(found: bool) -> list[str] | None:
            if found:
                return []
            return None

        def main() -> None:
            print(empty_values().[list__str]__len__!(), empty_mapping().[dict__str_int]__len__!(), empty_coordinates().[tuple__int__variadic]__len__!(), empty_set().[set__int]__len__!(), optional_values(True))
        """,
        """
        export function empty_values() {
            return [];
        }

        export function empty_mapping() {
            return new Map([]);
        }

        export function empty_coordinates() {
            return [];
        }

        export function empty_set() {
            return new Set();
        }

        export function optional_values(found) {
            if (found) {
                return [];
            }
            return null;
        }

        export function main() {
            console.log(empty_values().length, empty_mapping().size, empty_coordinates().length, empty_set().size, ((value)=>value===null?'None':value)(optional_values(true)));
        }
        """,
    )


def test_empty_return_cannot_satisfy_nonempty_fixed_tuple():
    with pytest.raises(CompilationError, match="tuple"):
        analyze_module_source('''
            def main() -> tuple[int, int]:
                return ()
        ''')


def test_call_arguments_contextually_type_collection_literals():
    at(
        """
        @js
        class Left:
            pass

        @js
        class Right:
            pass

        @js
        def count(values: list[Left | Right]) -> int:
            return len(values)

        def main():
            print(count([Left()]))
        """,
        """
        class Left:

        def count(values: list__LeftURight) -> int:
            return values.[list__LeftURight]__len__!()

        def main() -> None:
            print(count([Left()]))
        """,
        """
        export class Left {
        }

        export function count(values) {
            return values.length;
        }

        export function main() {
            console.log(count([new Left()]));
        }
        """,
    )


def test_call_arguments_contextually_type_nested_dictionary_literals():
    at(
        """
        @js
        def count(values: dict[str, object]) -> int:
            return len(values)

        def main():
            print(count({"items": [{"label": "ready"}]}))
        """,
        """
        def count(values: dict__str_object) -> int:
            return values.[dict__str_object]__len__!()

        def main() -> None:
            print(count({'items': [{'label': 'ready'}]}))
        """,
        """
        export function count(values) {
            return values.size;
        }

        export function main() {
            console.log(count(new Map([['items', [new Map([['label', 'ready']])]]])));
        }
        """,
    )


def test_optional_return_narrows_after_none_guard_returns():
    at(
        """
        @js
        class State:
            def __init__(self):
                self.name = "ready"

        @js
        def get_state(found: bool) -> State | None:
            if found:
                return State()

        def main():
            state = get_state(True)
            if state is None:
                return
            name = state.name
        """,
        """
        class State:
        
            def __init__() -> None:
                self.name = 'ready'

        def get_state(found: bool) -> State | None:
            if found:
                return State()

        def main() -> None:
            state: State | None = get_state(True)
            if state.[object]__is__!(None):
                return
            name: str = state.name
        """,
        """
        export class State {

            constructor() {
                this.name = 'ready';
            }
        }

        export function get_state(found) {
            if (found) {
                return new State();
            }
        }

        export function main() {
            var state = get_state(true);
            if (state == null) {
                return;
            }
            var name = state.name;
        }
        """
    )


def test_inline_varargs_string_placeholders():
    at(
        """
        @js.inline('wrap("head"{*args})')
        def wrap_head(*args) -> object:
            return None

        def main():
            first = wrap_head()
            second = wrap_head("a", "b")
        """,
        """
        def main() -> None:
            first: object = wrap_head()
            second: object = wrap_head('a', 'b')
        """,
        """
        export function main() {
            var first = wrap("head");
            var second = wrap("head", 'a', 'b');
        }
        """
    )


def test_callable_parameter_can_be_invoked_in_lambda():
    at(
        """
        @js
        class Target:
            def add(self, event: str, listener: callable) -> None:
                ...

        @js
        def bind(target: Target, callback: callable, value: str) -> None:
            target.add("click", lambda event: callback(value))

        def main():
            bind
        """,
        """
        class Target:

            def add(event: str, listener: callable) -> None:
                pass

        def bind(target: Target, callback: callable, value: str) -> None:
            target.[Target]add('click', lambda event: callback(value))

        def main() -> None:
            bind
        """,
        """
        export class Target {

            add(event, listener) {
            }
        }

        export function bind(target, callback, value) {
            target.add('click', (event) => callback(value));
        }

        export function main() {
            bind;
        }
        """,
    )


def test_annotated_return_rejects_implicit_none_fallthrough():
    ad(
        """\
        from pyjs import js

        @js
        class State:
            pass

        @js
        def get_state(found: bool) -> State:
            if found:
                return State()

        def main():
            get_state(True)
        """,
        diagnostic_text(
            "return_fallthrough.py",
            8,
            "def get_state(found: bool) -> State:",
            " " * 30 + "^^^^^",
            "pyjs.CompilationError: Function returns State | NoneType, not State "
            "[PYJS1105]",
            "help: Change the return annotation or return values so their types match.",
        ),
        filename="return_fallthrough.py",
    )


def test_annotated_return_accepts_non_fallthrough_while_true():
    at(
        """
        @js
        def get_value() -> int:
            while True:
                return 1

        def main():
            value = get_value()
        """,
        """
        def get_value() -> int:
            while True:
                return 1

        def main() -> None:
            value: int = get_value()
        """,
        """
        export function get_value() {
            while (true) {
                return 1;
            }
        }

        export function main() {
            var value = get_value();
        }
        """
    )


def test_annotated_return_accepts_while_true_without_a_break():
    at(
        """
        @js
        def next_name(available: bool) -> str:
            while True:
                if available:
                    return "ready"

        def main():
            print(next_name(True))
        """,
        """
        def next_name(available: bool) -> str:
            while True:
                if available:
                    return 'ready'

        def main() -> None:
            print(next_name(True))
        """,
        """
        export function next_name(available) {
            while (true) {
                if (available) {
                    return 'ready';
                }
            }
        }

        export function main() {
            console.log(next_name(true));
        }
        """,
    )


def test_nested_loop_break_does_not_make_an_outer_infinite_loop_fall_through():
    at(
        """
        @js
        def next_name(available: bool) -> str:
            while True:
                for value in [1]:
                    break
                if available:
                    return "ready"

        def main():
            print(next_name(True))
        """,
        """
        def next_name(available: bool) -> str:
            while True:
                for value: int in [1]:
                    break
                if available:
                    return 'ready'

        def main() -> None:
            print(next_name(True))
        """,
        """
        export function next_name(available) {
            while (true) {
                for (var value of [1]) {
                    break
                }
                if (available) {
                    return 'ready';
                }
            }
        }

        export function main() {
            console.log(next_name(true));
        }
        """,
    )


def test_annotated_return_rejects_while_true_with_a_break():
    ad(
        """\
        from pyjs import js

        @js
        def maybe_name(available: bool) -> str:
            while True:
                if available:
                    return "ready"
                break

        def main():
            print(maybe_name(True))
        """,
        diagnostic_text(
            "return_break.py",
            4,
            "def maybe_name(available: bool) -> str:",
            " " * 35 + "^^^",
            "pyjs.CompilationError: Function returns str | NoneType, not str "
            "[PYJS1105]",
            "help: Change the return annotation or return values so their types match.",
        ),
        filename="return_break.py",
    )


def test_indeterminate_input_type():
    ad(
        """\
        def main(value):
            return value + value
        """,
        """
          File "parameter.py", line 1
            def main(value):
                     ^^^^^
        pyjs.CompilationError: Parameter 'value' requires a type annotation [PYJS1101]
        help: Annotate 'value' with the value type expected by this function.
        """,
        filename="parameter.py",
    )


def test_explicit_string_annotations_are_analyzed_normally():
    at(
        """
        @js
        class Item:
            pass

        @js
        def identity(value: "Item") -> "Item":
            return value

        def main():
            result = identity(Item())
        """,
        """
        class Item:

        def identity(value: Item) -> Item:
            return value

        def main() -> None:
            result: Item = identity(Item())
        """,
        """
        export class Item {
        }

        export function identity(value) {
            return value;
        }

        export function main() {
            var result = identity(new Item());
        }
        """,
    )


def test_returned_callable_inputs_are_contravariant():
    assert_transpile('''
        from collections.abc import Callable
        @js
        def broad(value: object) -> int:
            return 7
        @js
        def factory() -> Callable[[int], int]:
            return broad
        def main() -> int:
            return factory()(3)
    ''', '''
        export function broad(value) {
            return 7;
        }

        export function factory() {
            return broad;
        }

        export function main() {
            return factory()(3);
        }
    ''')


def test_callable_annotations_contextually_type_lambdas_and_calls():
    at(
        """
        from collections.abc import Callable

        @js
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        def main():
            label = apply(3, lambda value: str(value))
        """,
        """
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        def main() -> None:
            label: str = apply(3, lambda value: value.[int]__str__!())
        """,
        """
        export function apply(value, transform) {
            return transform(value);
        }

        export function main() {
            var label = apply(3, (value) => String(value));
        }
        """,
    )


def test_nested_lambda_inherits_contextual_result_signature():
    at(
        '''
        from typing import Callable

        @js
        def make(offset: int) -> Callable[[int], Callable[[int], int]]:
            return lambda value: lambda extra: offset + value + extra

        def main():
            result = make(10)(2)(3)
        ''',
        '''
        def make(offset: int) -> Callable[[int], Callable[[int], int]]:
            return lambda value: lambda extra: offset.[int]__add__!(value).[int]__add__!(extra)

        def main() -> None:
            result: int = make(10)(2)(3)
        ''',
        '''
        export function make(offset) {
            return (value) => (extra) => offset + value + extra;
        }

        export function main() {
            var result = make(10)(2)(3);
        }
        ''',
    )


def test_conditional_function_values_preserve_compatible_signatures():
    assert_transpile(
        """
        @js
        def integer(value: int) -> int:
            return value

        @js
        def decimal(value: int) -> float:
            return 2.5

        def main(flag: bool):
            result: int | float = (integer if flag else decimal)(2)
            print(result)
        """,
        """
        export function integer(value) {
            return value;
        }

        export function decimal(value) {
            return 2.5;
        }

        export function main(flag) {
            var result = (flag ? integer : decimal)(2);
            console.log(result);
        }
        """,
    )


def test_conditional_function_values_reject_incompatible_signatures():
    ad(
        """\
        from pyjs import js

        @js
        def text(value: str) -> str:
            return value

        @js
        def number(value: int) -> int:
            return value

        def main(flag: bool):
            print((text if flag else number)("value"))
        """,
        diagnostic_text(
            "conditional_callable.py",
            12,
            'print((text if flag else number)("value"))',
            " " * 7 + "^^^^^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Callable value has incompatible signatures "
            "[PYJS1104]",
            "help: Narrow the value or use callables with matching positional "
            "parameter types.",
        ),
        filename="conditional_callable.py",
    )


def test_conditional_non_callable_values_have_a_located_diagnostic():
    ad(
        """\
        def main(flag: bool):
            print((1 if flag else 2)())
        """,
        diagnostic_text(
            "conditional_value.py",
            2,
            "print((1 if flag else 2)())",
            " " * 7 + "^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Value of type int is not callable [PYJS1104]",
            "help: Call a function, class, or typed Callable value.",
        ),
        filename="conditional_value.py",
    )


def test_callable_annotations_support_qualified_typing_aliases():
    at(
        """
        import typing as types

        @js
        def apply(value: int, transform: types.Callable[[int], str]) -> str:
            return transform(value)

        def main():
            label = apply(3, lambda value: str(value))
        """,
        """
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        def main() -> None:
            label: str = apply(3, lambda value: value.[int]__str__!())
        """,
        """
        export function apply(value, transform) {
            return transform(value);
        }

        export function main() {
            var label = apply(3, (value) => String(value));
        }
        """,
    )


def test_callable_annotations_accept_functions_with_optional_parameters():
    at(
        """
        from collections.abc import Callable

        @js
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        @js
        def label(value: int, suffix: str = "!") -> str:
            return str(value) + suffix

        def main():
            result = apply(3, label)
        """,
        """
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        def label(value: int, suffix: str='!') -> str:
            return value.[int]__str__!().[str]__add__!(suffix)

        def main() -> None:
            result: str = apply(3, label)
        """,
        """
        export function apply(value, transform) {
            return transform(value);
        }

        export function label(value, { suffix='!'} = {}) {
            return String(value) + suffix;
        }

        export function main() {
            var result = apply(3, label);
        }
        """,
    )


def test_callable_annotations_accept_bound_methods():
    at(
        """
        from collections.abc import Callable

        @js
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        @js
        class Formatter:
            def label(self, value: int) -> str:
                return str(value)

        def main():
            formatter = Formatter()
            result = apply(3, formatter.label)
        """,
        """
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        class Formatter:

            def label(value: int) -> str:
                return value.[int]__str__!()

        def main() -> None:
            formatter: Formatter = Formatter()
            result: str = apply(3, formatter.[Formatter]label)
        """,
        """
        export function apply(value, transform) {
            return transform(value);
        }

        export class Formatter {

            label(value) {
                return String(value);
            }
        }

        export function main() {
            var formatter = new Formatter();
            var result = apply(3, formatter.label.bind(formatter));
        }
        """,
    )


def test_callable_annotations_accept_forward_declared_bound_methods():
    at(
        """
        from collections.abc import Callable

        @js
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        @js
        class Formatter:
            def format(self, value: int) -> str:
                return apply(value, self.label)

            def label(self, value: int) -> str:
                return str(value)

        def main():
            result = Formatter().format(3)
        """,
        """
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        class Formatter:

            def format(value: int) -> str:
                return apply(value, self.[Formatter]label)

            def label(value: int) -> str:
                return value.[int]__str__!()

        def main() -> None:
            result: str = Formatter().[Formatter]format(3)
        """,
        """
        export function apply(value, transform) {
            return transform(value);
        }

        export class Formatter {

            format(value) {
                return apply(value, this.label.bind(this));
            }

            label(value) {
                return String(value);
            }
        }

        export function main() {
            var result = new Formatter().format(3);
        }
        """,
    )


def test_callable_annotations_allow_mutually_referenced_bound_methods():
    at(
        """
        from collections.abc import Callable

        @js
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        @js
        class Formatter:
            def first(self, value: int) -> str:
                apply(value, self.second)
                return str(value)

            def second(self, value: int) -> str:
                apply(value, self.first)
                return str(value)

        def main():
            result = Formatter().first(3)
        """,
        """
        def apply(value: int, transform: Callable[[int], str]) -> str:
            return transform(value)

        class Formatter:

            def first(value: int) -> str:
                apply(value, self.[Formatter]second)
                return value.[int]__str__!()

            def second(value: int) -> str:
                apply(value, self.[Formatter]first)
                return value.[int]__str__!()

        def main() -> None:
            result: str = Formatter().[Formatter]first(3)
        """,
        """
        export function apply(value, transform) {
            return transform(value);
        }

        export class Formatter {

            first(value) {
                apply(value, this.second.bind(this));
                return String(value);
            }

            second(value) {
                apply(value, this.first.bind(this));
                return String(value);
            }
        }

        export function main() {
            var result = new Formatter().first(3);
        }
        """,
    )


def test_optional_callable_keyword_binds_method_receiver():
    assert_transpile(
        """
        from collections.abc import Callable

        @js
        def apply(
            value: int,
            transform: Callable[[int], str] | None = None,
        ) -> str:
            if transform is None:
                return ""
            return transform(value)

        @js
        class Formatter:
            def label(self, value: int) -> str:
                return str(value)

        def main():
            formatter = Formatter()
            result = apply(3, formatter.label)
        """,
        """
        export function apply(value, { transform=null} = {}) {
            if (transform == null) {
                return '';
            }
            return transform(value);
        }

        export class Formatter {

            label(value) {
                return String(value);
            }
        }

        export function main() {
            var formatter = new Formatter();
            var result = apply(3, {transform: formatter.label.bind(formatter)});
        }
        """,
    )


def test_inline_calls_bind_method_receivers_in_positional_and_keyword_arguments():
    assert_transpile(
        """
        from collections.abc import Callable

        @js.inline("{callback}")
        def keep(
            callback: Callable[[int], str],
        ) -> Callable[[int], str]:
            return callback

        @js
        class Formatter:
            def label(self, value: int) -> str:
                return str(value)

        def main():
            formatter = Formatter()
            positional = keep(formatter.label)
            keyword = keep(callback=formatter.label)
            print(positional(1), keyword(2))
        """,
        """
        export class Formatter {

            label(value) {
                return String(value);
            }
        }

        export function main() {
            var formatter = new Formatter();
            var positional = formatter.label.bind(formatter);
            var keyword = formatter.label.bind(formatter);
            console.log(positional(1), keyword(2));
        }
        """,
    )


def test_callable_annotations_report_incompatible_callback_results():
    ad(
        """\
        from collections.abc import Callable
        from pyjs import js

        @js
        def apply(transform: Callable[[int], str]) -> str:
            return transform(1)

        @js
        def number(value: int) -> int:
            return value

        def main():
            apply(number)
        """,
        """
          File "callable_result.py", line 13
            apply(number)
                  ^^^^^^
        pyjs.CompilationError: Callable argument 'transform' to apply returns int, expected str [PYJS1104]
        note: callable_result.py:9:5: callable defined here
        help: Change the callable return annotation or returned values.
        """,
        filename="callable_result.py",
    )


def test_callable_annotations_report_incompatible_function_shapes():
    ad(
        """\
        from collections.abc import Callable
        from pyjs import js

        @js
        def apply(transform: Callable[[int], str]) -> str:
            return transform(1)

        @js
        def label() -> str:
            return "ready"

        def main():
            apply(label)
        """,
        diagnostic_text(
            "callable_shape.py",
            13,
            "apply(label)",
            "      ^^^^^",
            "pyjs.CompilationError: Argument 'transform' to apply expects a "
            "callable that accepts 1 positional argument [PYJS1104]",
            "note: callable_shape.py:9:5: callable defined here",
            "help: Use a callable with the annotated parameter shape.",
        ),
        filename="callable_shape.py",
    )


def test_callable_annotations_reject_async_callbacks():
    ad(
        """\
        from collections.abc import Callable
        from pyjs import js

        @js
        def apply(transform: Callable[[int], str]) -> str:
            return transform(1)

        @js
        async def label(value: int) -> str:
            return str(value)

        def main():
            apply(label)
        """,
        diagnostic_text(
            "async_callable.py",
            13,
            "apply(label)",
            "      ^^^^^",
            "pyjs.CompilationError: Argument 'transform' to apply cannot be async "
            "[PYJS1104]",
            "help: Pass a synchronous callable or expect an Awaitable result.",
        ),
        filename="async_callable.py",
    )


def test_callable_annotations_accept_async_functions_for_awaitable_results():
    at(
        """
        from collections.abc import Awaitable, Callable

        @js
        async def apply(transform: Callable[[int], Awaitable[str]]) -> str:
            return await transform(1)

        @js
        async def label(value: int) -> str:
            return str(value)

        async def main():
            result = await apply(label)
        """,
        """
        async def apply(transform: Callable[[int], Awaitable[str]]) -> str:
            return await transform(1)

        async def label(value: int) -> str:
            return value.[int]__str__!()

        async def main() -> None:
            result: str = await apply(label)
        """,
        """
        export async function apply(transform) {
            return await transform(1);
        }

        export async function label(value) {
            return String(value);
        }

        export async function main() {
            var result = await apply(label);
        }
        """,
    )


def test_generic_classes_infer_nested_types_from_async_callables():
    at(
        """
        from collections.abc import Awaitable, Callable

        @js
        class AsyncLoader[T]:
            def __init__(self, loader: Callable[..., Awaitable[T]]):
                self.loader = loader

            async def get(self) -> T:
                return await self.loader()

        @js
        async def load() -> str:
            return "loaded"

        async def main():
            query = AsyncLoader(load)
            value = await query.get()
            print(value.upper())
        """,
        """
        class AsyncLoader__str:

            def __init__(loader: Callable[..., Awaitable[str]]) -> None:
                self.loader = loader

            async def get() -> str:
                return await self.loader()

        async def load() -> str:
            return 'loaded'

        async def main() -> None:
            query: AsyncLoader[str] = AsyncLoader__str(load)
            value: str = await query.[AsyncLoader__str]get()
            print(value.[str]upper!())
        """,
        """
        export class AsyncLoader__str {

            constructor(loader) {
                this.loader = loader;
            }

            async get() {
                return await this.loader();
            }
        }

        export async function load() {
            return 'loaded';
        }

        export async function main() {
            var query = new AsyncLoader__str(load);
            var value = await query.get();
            console.log(value.toUpperCase());
        }
        """,
    )


def test_generic_classes_infer_types_from_keyword_arguments():
    at(
        """
        @js
        class Box[T]:
            def __init__(self, value: T, label: str):
                self.value = value
                self.label = label

            def get(self) -> T:
                return self.value

        def main():
            box = Box(value=1, label="one")
            print(box.get())
        """,
        """
        class Box__int:

            def __init__(value: int, label: str) -> None:
                self.value = value
                self.label = label

            def get() -> int:
                return self.value

        def main() -> None:
            box: Box[int] = Box__int(value=1, label='one')
            print(box.[Box__int]get())
        """,
        """
        export class Box__int {

            constructor(value, label) {
                this.value = value;
                this.label = label;
            }

            get() {
                return this.value;
            }
        }

        export function main() {
            var box = new Box__int(1, 'one');
            console.log(box.get());
        }
        """,
    )


def test_inferred_generic_constructors_validate_non_generic_arguments():
    ad(
        """\
        from pyjs import js

        @js
        class Box[T]:
            def __init__(self, value: T, label: str):
                self.value = value
                self.label = label

        def main():
            Box(value=1, label=2)
        """,
        diagnostic_text(
            "generic_keyword.py",
            10,
            "Box(value=1, label=2)",
            "                   ^",
            "pyjs.CompilationError: Argument 'label' to Box.__init__ expects "
            "str, got int [PYJS1104]",
            "help: Pass a value compatible with str.",
        ),
        filename="generic_keyword.py",
    )


def test_generic_classes_validate_explicit_types_against_async_callables():
    ad(
        """\
        from collections.abc import Awaitable, Callable
        from pyjs import js

        @js
        class AsyncLoader[T]:
            def __init__(self, loader: Callable[..., Awaitable[T]]):
                pass

        @js
        async def load() -> str:
            return "loaded"

        def main():
            AsyncLoader[int](load)
        """,
        diagnostic_text(
            "nested_callable.py",
            14,
            "AsyncLoader[int](load)",
            "                 ^^^^",
            "pyjs.CompilationError: Callable argument 'loader' to __init__ "
            "returns str, expected int [PYJS1104]",
            "note: nested_callable.py:10:11: callable defined here",
            "help: Change the callable return annotation or returned values.",
        ),
        filename="nested_callable.py",
    )


def test_calls_through_callable_annotations_validate_argument_types():
    ad(
        """\
        from collections.abc import Callable
        from pyjs import js

        @js
        def invoke(transform: Callable[[int], str]) -> str:
            return transform("wrong")
        """,
        diagnostic_text(
            "callable_call.py",
            6,
            "return transform('wrong')",
            "                 ^^^^^^^",
            "pyjs.CompilationError: Callable argument 1 expects int, got str "
            "[PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="callable_call.py",
    )


def test_callable_annotations_validate_forwarded_callable_signatures():
    ad(
        """\
        from collections.abc import Callable
        from pyjs import js

        @js
        def apply(transform: Callable[[int], str]) -> str:
            return transform(1)

        @js
        def relay(transform: Callable[[str], str]) -> str:
            return apply(transform)

        def main():
            relay(lambda value: value)
        """,
        diagnostic_text(
            "forwarded_callable.py",
            10,
            "return apply(transform)",
            "             ^^^^^^^^^",
            "pyjs.CompilationError: Argument 'transform' to apply expects "
            "Callable[[int], str], got Callable[[str], str] [PYJS1104]",
            "help: Pass a value compatible with Callable[[int], str].",
        ),
        filename="forwarded_callable.py",
    )


@pytest.mark.parametrize("expected", ["Callable[[int], int8]", "Callable[..., int16]", "Callable[..., int]"])
def test_forwarded_callable_preserves_constrained_numeric_representations(expected):
    with pytest.raises(CompilationError, match="Argument 'transform' to accept expects") as caught:
        analyze_module_source(f'''\
from collections.abc import Callable
from pyjs import int8, int16, js
@js
def accept(transform: {expected}) -> int:
    return 0
@js
def relay(transform: Callable[[int8], int8]) -> int:
    return accept(transform)
''')
    assert caught.value.lineno == 10


def test_calls_callable_values_read_from_collections():
    at(
        """
        from collections.abc import Callable

        @js
        def invoke(callbacks: list[Callable[[int], str]]) -> str:
            return callbacks[0](1)

        def main():
            result = invoke([lambda value: str(value)])
        """,
        """
        def invoke(callbacks: list__Callable__int__str) -> str:
            return $get_list_item(callbacks, 0)(1)

        def main() -> None:
            result: str = invoke([lambda value: value.[int]__str__!()])
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function invoke(callbacks) {
            return $get_list_item(callbacks, 0)(1);
        }

        export function main() {
            var result = invoke([(value) => String(value)]);
        }
        """,
    )


def test_generic_functions_infer_and_substitute_argument_types():
    at(
        """
        @js
        def first[T](values: list[T]) -> T:
            return values[0]

        def main():
            number = first([1, 2])
            label = first(["a", "b"])
        """,
        """
        def first(values: list__T) -> T:
            return $get_list_item(values, 0)

        def main() -> None:
            number: int = first([1, 2])
            label: str = first(['a', 'b'])
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function first(values) {
            return $get_list_item(values, 0);
        }

        export function main() {
            var number = first([1, 2]);
            var label = first(['a', 'b']);
        }
        """,
    )


def test_generic_functions_infer_types_through_specialized_base_classes():
    at(
        """
        @js.native
        class Pair[A, B]:
            def __init__(self): ...

        @js.native
        class Swapped[T, U](Pair[U, T]):
            pass

        @js.native
        class Concrete(Swapped[int, str]):
            pass

        @js.native
        def make() -> Concrete: ...

        @js
        def second[A, B](pair: Pair[A, B]) -> B: ...

        def main():
            value = second(make()) + 1
        """,
        """
        def second(pair: Pair__A_B) -> B:
            pass

        def main() -> None:
            value: int = second(make()).[int]__add__!(1)
        """,
        """
        export function second(pair) {
        }

        export function main() {
            var value = second(make()) + 1;
        }
        """,
    )


def test_generic_functions_infer_bounded_types_from_class_values():
    at(
        """
        from pyjs import js

        @js
        class Base:
            pass

        @js
        class Child(Base):
            pass

        @js
        def make[T: Base](value_type: type[T]) -> T: ...

        def main():
            value = make(Child)
        """,
        """
        class Base:

        class Child(Base):

        def make(value_type: type__T) -> T:
            pass

        def main() -> None:
            value: Child = make(Child)
        """,
        """
        export class Base {
        }

        export class Child extends Base {
        }

        export function make(value_type) {
        }

        export function main() {
            var value = make(Child);
        }
        """,
    )

    ad(
        """\
        from pyjs import js

        @js
        class Base:
            pass

        @js
        class Unrelated:
            pass

        @js
        def make[T: Base](value_type: type[T]) -> T: ...

        def main():
            value = make(Unrelated)
        """,
        diagnostic_text(
            "bounded_type.py",
            15,
            "value = make(Unrelated)",
            "        ^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Type argument Unrelated for T does not satisfy "
            "bound Base [PYJS1104]",
            "help: Pass a Base subtype for T.",
        ),
        filename="bounded_type.py",
    )


def test_bounded_generic_values_are_compatible_with_their_bound():
    at(
        """
        from pyjs import js

        @js
        class Base:
            pass

        @js
        def consume(value: Base):
            pass

        @js
        def forward[T: Base](value: T):
            consume(value)

        def main(value: Base):
            forward(value)
        """,
        """
        class Base:

        def consume(value: Base) -> None:
            pass

        def forward(value: T) -> None:
            consume(value)

        def main(value: Base) -> None:
            forward(value)
        """,
        """
        export class Base {
        }

        export function consume(value) {
        }

        export function forward(value) {
            consume(value);
        }

        export function main(value) {
            forward(value);
        }
        """,
    )


def test_generic_functions_contextually_type_callbacks_after_inference():
    at(
        """
        from collections.abc import Callable, Iterable

        @js
        def transform[T, R](
            values: Iterable[T],
            callback: Callable[[T], R],
        ) -> list[R]: ...

        def main():
            labels = transform([1, 2], lambda value: str(value))
        """,
        """
        def transform(values: Iterable__T, callback: Callable[[T], R]) -> list[R]:
            pass

        def main() -> None:
            labels: list[str] = transform([1, 2], lambda value: value.[int]__str__!())
        """,
        """
        export function transform(values, callback) {
        }

        export function main() {
            var labels = transform([1, 2], (value) => String(value));
        }
        """,
    )


def test_overloads_select_result_types_from_argument_types():
    at(
        """
        from typing import overload

        @overload
        def convert(value: int) -> str: ...

        @overload
        def convert(value: str) -> int: ...

        @js
        def convert(value: object) -> object: ...

        def main():
            label = convert(1)
            number = convert("1")
        """,
        """
        def convert(value: object) -> object:
            pass

        def main() -> None:
            label: str = convert(1)
            number: int = convert('1')
        """,
        """
        export function convert(value) {
        }

        export function main() {
            var label = convert(1);
            var number = convert('1');
        }
        """,
    )


def test_generic_overloads_infer_default_result_types():
    at(
        """
        from collections.abc import Iterator
        from typing import overload

        @overload
        def take[T](values: Iterator[T]) -> T: ...

        @overload
        def take[T, D](values: Iterator[T], default: D) -> T | D: ...

        @js
        def take(values: Iterator[object], default: object = None) -> object: ...

        def main(values: Iterator[str]):
            required = take(values)
            optional = take(values, 0)
        """,
        """
        def take(values: Iterator__object, default: object=None) -> object:
            pass

        def main(values: Iterator__str) -> None:
            required: str = take(values)
            optional: str | int = take(values, 0)
        """,
        """
        export function take(values, { default: $$default=null} = {}) {
        }

        export function main(values) {
            var required = take(values);
            var optional = take(values, {default: 0});
        }
        """,
    )


def test_annotated_parameter_is_its_type():
    from pyjs.javascript.source import compile_source

    result = compile_source(
        """
from typing import Annotated
from pyjs import js

@js
def total(items: Annotated[list[float], 4]) -> float:
    return items[0] + items[3]

@js
def main() -> float:
    return total([1.0, 2.0, 3.0, 4.0])
""",
        filename="annotated.py",
    )
    assert "function total(items)" in result.sources["annotated"]
