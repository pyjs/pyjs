from pyjs.testing.helpers import ad, at

from .helpers import assert_semantics


def test_print_accepts_zero_one_and_multiple_objects():
    assert_semantics(
        """\
        print()
        print("one")
        print(1, "two", 2.5)
        print(None, True, False)
        """
    )


def test_print_preserves_statically_known_float_spelling():
    assert_semantics(
        """\
        print(1.0)
        print(6 / 3)
        print(-0.0)
        """
    )


def test_print_supports_sep_and_end():
    assert_semantics(
        """\
        print("left", "right", sep="|")
        print([1, 2], {"answer": 42}, sep=" | ")
        print((1, 2), {1, 2}, end="!\\n")
        print("same", end=" ")
        print("line")
        print(end="done")
        """
    )


def test_print_formats_none_from_an_optional_value():
    assert_semantics(
        """\
        values: dict[str, int] = {"present": 1}
        print(values.get("present"), values.get("missing"))
        """
    )

    at(
        """\
        def main(value: int | None):
            print(value)
        """,
        """
        def main(value: int | None) -> None:
            print(value)
        """,
        """
        export function main(value) {
            console.log(((value)=>value===null?'None':value)(value));
        }
        """,
    )


def test_print_evaluates_expressions_that_return_none():
    assert_semantics(
        """\
        values = [1]
        print(None)
        print(values.clear())
        print(len(values))
        """
    )
    at(
        """\
        def main(values: list[int]):
            print(None)
            print(values.clear())
        """,
        """
        def main(values: list__int) -> None:
            print(None)
            print(values.[list__int]clear!())
        """,
        """
        export function main(values) {
            console.log('None');
            console.log(((values.length = 0, null), 'None'));
        }
        """,
    )


def test_print_has_concise_javascript_for_default_and_custom_separators():
    at(
        """\
        def main():
            print(1, "two")
            print("left", "right", sep="|")
        """,
        """
        def main() -> None:
            print(1, 'two')
            print('left', 'right', sep='|')
        """,
        """
        export function main() {
            console.log(1, 'two');
            console.log(['left', 'right'].join('|'));
        }
        """,
    )


def test_custom_print_text_stringifies_statically_known_containers():
    at(
        """\
        def main():
            values: list[int] = [1, 2]
            print(values, {"answer": 42}, sep=" | ")
        """,
        """
        def main() -> None:
            values: list[int] = [1, 2]
            print($repr_value(values), $repr_value({'answer': 42}), sep=' | ')
        """,
        """
        import { repr_value as $repr_value } from './pyjs.python.js';

        export function main() {
            var values = [1, 2];
            console.log([$repr_value(values), $repr_value(new Map([['answer', 42]]))].join(' | '));
        }
        """,
    )


def test_print_uses_the_float_runtime_only_for_float_values():
    at(
        """\
        def main(value: float):
            print(1, value)
        """,
        """
        def main(value: float) -> None:
            print(1, $float_string(value))
        """,
        """
        import { float_string as $float_string } from './pyjs.python.js';

        export function main(value) {
            console.log(1, $float_string(value));
        }
        """,
    )


def test_f_strings_format_common_numeric_values():
    assert_semantics(
        """\
        value = 1.234
        count = 42
        negative = -42
        ratio = 0.256
        print(f"{value:.2f}")
        print(f"{count:05d}")
        print(f"{negative:05d}")
        print(f"{ratio:.1%}")
        print(f"{-0.0:.2f}")
        print(f"{-0.0:06.2f}")
        print(f"{value:8.2f}")
        print(f"{value:f}")
        print(f"{ratio:%}")
        print(f"{value:.3e}")
        print(f"{-0.0:.2e}")
        print(f"{1200.0:12.2E}")
        print(f"{value:e}")
        print(f"{1e10:.1e}")
        print(f"{1e-10:.1e}")
        print(f"{-12.3:012.2e}")
        print(f"{float('inf'):010.2e}")
        print(f"{float('-inf'):10.2E}")
        print(f"{float('nan'):.2e}")
        """
    )


def test_numeric_f_strings_preserve_formatting_in_javascript():
    at(
        """\
        def main():
            value = 1.234
            count = 42
            fixed = f"{value:.2f}"
            padded = f"{count:05d}"
            scientific = f"{value:.3e}"
        """,
        """
        def main() -> None:
            value: float = 1.234
            count: int = 42
            fixed: str = f'{value:.2f}'
            padded: str = f'{count:05d}'
            scientific: str = f'{value:.3e}'
        """,
        """
        export function main() {
            var value = 1.234;
            var count = 42;
            var fixed = ((value)=>{const negative=value<0||Object.is(value,-0);return (negative?'-':'')+Math.abs(Number(value)).toFixed(2);})(value);
            var padded = ((value) => {const negative=value<0||Object.is(value,-0);return (negative?'-':'') + (String(Math.abs(Math.trunc(value)))).padStart(5 - (negative?1:0), '0');})(count);
            var scientific = ((value)=>{const negative=value<0||Object.is(value,-0);return (negative?'-':'')+(Number.isNaN(Math.abs(Number(value)))?'nan':Number.isFinite(Math.abs(Number(value)))?(Math.abs(Number(value)).toExponential(3)).replace(/([eE][+-])(\\d)$/,(_, exponent, digit) => exponent + '0' + digit):'inf');})(value);
        }
        """,
    )


def test_unsupported_f_string_format_has_a_focused_diagnostic():
    ad(
        """\
        def main():
            value = 42
            print(f"{value:#x}")
        """,
        """
          File "unsupported_format.py", line 3
            print(f"{value:#x}")
                          ^^^
        pyjs.CompilationError: f-string format specification '#x' is not supported [PYJS2001]
        help: Use d, e, E, f, or % with optional zero padding, width, and precision.
        """,
        filename="unsupported_format.py",
    )


def test_dynamic_f_string_format_has_a_focused_diagnostic():
    ad(
        """\
        def main():
            value = 1.25
            precision = 2
            print(f"{value:.{precision}f}")
        """,
        """
          File "dynamic_format.py", line 4
            print(f"{value:.{precision}f}")
                          ^^^^^^^^^^^^^^
        pyjs.CompilationError: dynamic f-string format specifications are not supported [PYJS2001]
        help: Use a constant d, e, E, f, or % format specification.
        """,
        filename="dynamic_format.py",
    )


def test_invalid_supported_format_combinations_have_focused_diagnostics():
    ad(
        """\
        def main():
            print(f"{42:.2d}")
        """,
        """
          File "integer_precision.py", line 2
            print(f"{42:.2d}")
                       ^^^^
        pyjs.CompilationError: precision is not allowed with integer f-string formatting [PYJS2001]
        help: Remove the precision from the d format specification.
        """,
        filename="integer_precision.py",
    )

    ad(
        """\
        def main():
            print(f"{1.25!r:.2f}")
        """,
        """
          File "formatted_conversion.py", line 2
            print(f"{1.25!r:.2f}")
                    ^^^^^^^^^^^^
        pyjs.CompilationError: f-string conversions cannot be combined with numeric formatting [PYJS2001]
        help: Apply !s or !r without a numeric format specification.
        """,
        filename="formatted_conversion.py",
    )


def test_numeric_f_string_format_rejects_incompatible_values():
    ad(
        """\
        def main():
            value = "42"
            print(f"{value:05d}")
        """,
        """
          File "incompatible_format.py", line 3
            print(f"{value:05d}")
                     ^^^^^
        pyjs.CompilationError: Format code 'd' does not support str [PYJS1104]
        help: Format a compatible numeric value.
        """,
        filename="incompatible_format.py",
    )


def test_required_function_arguments_accept_keywords():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def subtract(a: int, b: int) -> int:
            return a - b

        print(subtract(b=2, a=5))
        print(subtract(8, b=3))
        """
    )
