from pyjs.testing.helpers import at

from .helpers import assert_semantics


def test_f_string_methods_apply_to_the_complete_expression():
    assert_semantics('''
        from pyjs import js

        @js
        def main():
            name = "NAME"
            category = "Resource Usage"
            print(f"{name} {category}".lower())
            print(f"prefix {name}".upper())
            print(f"{name} suffix".startswith("NAME"))
            print(f"{name} suffix"[0])
            print(f"{name} suffix" == "NAME suffix")
            print(f"prefix {f'{name} {category}'.lower()}".upper())
            print(f"".lower())

        main()
    ''')



def test_literal_string_replacement_matches_python_semantics():
    assert_semantics(
        """\
        print("a::a::a".replace("a", "note"))
        print("a::a::a".replace("a", "note", 2))
        print("a::a::a".replace("a", "note", 0))
        print("unchanged".replace("missing", "value"))
        print("ab".replace("", "-"))
        print("ab".replace("", "-", 2))
        print("😊".replace("", "-"))
        print("".replace("", "value"))
        """
    )


def test_str_and_repr_match_common_python_values():
    assert_semantics(
        """\
        print(str())
        print(str(None), str(True), str(12), str(1.5), str("value"))
        print(repr(None), repr(True), repr(12), repr(1.5), repr("value"))
        print(repr("it's"))
        print(str([1, "two", None, False]))
        print(repr((1,)))
        print(repr((1, "two")))
        print(str({"answer": 42, "valid": True}))
        print(repr([{"items": [1, None]}]))
        print(repr({"items": [1, None]}))
        print(str({1}), repr({1}), repr(set[int]()))
        print(f"{None}|{True}|{[1, 'two']}")
        """
    )


def test_direct_float_strings_use_python_spellings():
    assert_semantics(
        """\
        print(str(1.0), repr(-0.0))
        print(str(float("inf")), str(float("-inf")), str(float("nan")))
        print(str(1e-7), str(1e-4), str(1e16))
        print(f"{2.0}|{1.25}")
        """
    )


def test_direct_float_stringification_uses_one_runtime_formatter():
    at(
        """
        def main():
            value = 1.0
            text = str(value)
            debug = repr(value)
            rendered = f"{value}"
        """,
        """
        def main() -> None:
            value: float = 1.0
            text: str = $float_string(value)
            debug: str = $float_string(value)
            rendered: str = f'{$float_string(value)}'
        """,
        """
        import { float_string as $float_string } from './pyjs.python.js';

        export function main() {
            var value = 1.0;
            var text = $float_string(value);
            var debug = $float_string(value);
            var rendered = $float_string(value);
        }
        """,
    )


def test_repr_protects_self_referential_containers():
    assert_semantics(
        """\
        values: list[object] = []
        values.append(values)
        print(repr(values))

        mapping: dict[str, object] = {}
        mapping["self"] = mapping
        print(repr(mapping))

        outer: list[object] = []
        inner: list[object] = [outer]
        outer.append(inner)
        print(repr(outer))

        shared: list[object] = [1]
        repeated: list[object] = [shared, shared]
        print(repr(repeated))
        """
    )


def test_str_and_repr_dispatch_to_user_dunder_methods():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Label:
            def __init__(self, value: str):
                self.value = value

            def __str__(self) -> str:
                return "label: " + self.value

            def __repr__(self) -> str:
                return "Label(" + self.value + ")"

        @js
        def repr_object(value: object) -> str:
            return repr(value)

        label = Label("ready")
        print(label)
        print(str(label))
        print(repr(label))
        print(f"{label} / {label!r}")
        print(repr_object(label))
        print(repr_object([1, "two"]))
        print(repr_object({"answer": 42}))
        print(repr_object({1}))
        """
    )


def test_builtin_repr_calls_share_runtime_renderers():
    at(
        """\
        def main():
            value = "value"
            string_debug = repr(value)
            list_debug = repr([value])
            tuple_debug = repr((value,))
            mapping_debug = repr({"key": value})
            set_debug = repr({value})
        """,
        """
        def main() -> None:
            value: str = 'value'
            string_debug: str = $repr_value(value)
            list_debug: str = $repr_value([value])
            tuple_debug: str = $repr_tuple((value,))
            mapping_debug: str = $repr_value({'key': value})
            set_debug: str = $repr_value({value})
        """,
        """
        import { repr_value as $repr_value, repr_tuple as $repr_tuple } from './pyjs.python.js';

        export function main() {
            var value = 'value';
            var string_debug = $repr_value(value);
            var list_debug = $repr_value([value]);
            var tuple_debug = $repr_tuple([value]);
            var mapping_debug = $repr_value(new Map([['key', value]]));
            var set_debug = $repr_value(new Set([value]));
        }
        """,
    )


def test_object_typed_repr_uses_runtime_dunder_dispatch():
    at(
        """
        from pyjs import js

        @js
        class Label:
            def __init__(self, value: str):
                self.value = value

            def __repr__(self) -> str:
                return "Label(" + self.value + ")"

        @js
        def render(value: object) -> str:
            return repr(value)

        def main():
            custom = render(Label("ready"))
            sequence = render([1, "two"])
            mapping = render({"answer": 42})
            unique = render({1})
        """,
        """
        class Label:

            def __init__(value: str) -> None:
                self.value = value

            def __repr__() -> str:
                return 'Label('.[str]__add__!(self.value).[str]__add__!(')')

        def render(value: object) -> str:
            return $repr_value(value)

        def main() -> None:
            custom: str = render(Label('ready'))
            sequence: str = render([1, 'two'])
            mapping: str = render({'answer': 42})
            unique: str = render({1})
        """,
        """
        import { repr_value as $repr_value } from './pyjs.python.js';

        export class Label {

            constructor(value) {
                this.value = value;
            }

            __repr__() {
                return 'Label(' + this.value + ')';
            }
        }

        export function render(value) {
            return $repr_value(value);
        }

        export function main() {
            var custom = render(new Label('ready'));
            var sequence = render([1, 'two']);
            var mapping = render(new Map([['answer', 42]]));
            var unique = render(new Set([1]));
        }
        """,
    )


def test_str_and_repr_dunder_dispatch_is_preserved_in_javascript():
    at(
        """
        from pyjs import js

        @js
        class Label:
            def __init__(self, value: str):
                self.value = value

            def __str__(self) -> str:
                return "label: " + self.value

            def __repr__(self) -> str:
                return "Label(" + self.value + ")"

        def main():
            label = Label("ready")
            text = str(label)
            debug = repr(label)
            formatted = f"{label} / {label!r}"
            print(label)
        """,
        """
        class Label:

            def __init__(value: str) -> None:
                self.value = value

            def __str__() -> str:
                return 'label: '.[str]__add__!(self.value)

            def __repr__() -> str:
                return 'Label('.[str]__add__!(self.value).[str]__add__!(')')

        def main() -> None:
            label: Label = Label('ready')
            text: str = label.[Label]__str__()
            debug: str = label.[Label]__repr__()
            formatted: str = f'{label.[Label]__str__()} / {label.[Label]__repr__()}'
            print(label)
        """,
        """
        export class Label {

            constructor(value) {
                this.value = value;
            }

            __str__() {
                return 'label: ' + this.value;
            }

            __repr__() {
                return 'Label(' + this.value + ')';
            }
        }

        export function main() {
            var label = new Label('ready');
            var text = label.__str__();
            var debug = label.__repr__();
            var formatted = label.__str__()+' / '+label.__repr__();
            console.log(label.__str__());
        }
        """,
    )
