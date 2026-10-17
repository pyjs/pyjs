from pyjs.javascript.source import analyze_source
from pyjs.testing.helpers import (
    ad,
    assert_compilation_diagnostic,
    at,
    diagnostic_text,
)

from .helpers import assert_semantics


def test_modulo_uses_the_divisor_sign():
    assert_semantics(
        """\
        print(-5 % 3)
        print(5 % -3)
        print(-5 % -3)
        """
    )


def test_float_floor_division_and_modulo_match_python():
    assert_semantics(
        """\
        print(5.5 // 2 == 2.0)
        print(-5.5 // 2 == -3.0)
        print(5 // 2.0 == 2.0)
        print(1.0 // 0.1 == 9.0)
        print(-5.5 % 3 == 0.5)
        print(5.5 % -3 == -0.5)
        print(5 % 2.0 == 1.0)
        print(str(0.0 % -1.0))
        print(str(-0.0 // 1.0))
        print(str(float("inf") // 2.0))
        print(str(1.0 // float("inf")))
        integer_floor, integer_remainder = divmod(-5, 3)
        print(integer_floor == -2, integer_remainder == 1)
        float_floor, float_remainder = divmod(1.0, 0.1)
        print(float_floor == 9.0, float_remainder == 0.09999999999999995)
        """
    )


def test_round_uses_half_even_ties():
    assert_semantics(
        """\
        print(round(1.5))
        print(round(2.5))
        print(round(-1.5))
        print(round(-2.5))
        """
    )


def test_nan_uses_python_truthiness():
    assert_semantics(
        """\
        value = float("nan")
        print(bool(value))
        print("truthy" if value else "falsey")
        print((value or 1.0) != 1.0)
        """
    )


def test_round_with_ndigits_uses_decimal_half_even_semantics():
    assert_semantics(
        """\
        print(round(2.675, 2))
        print(round(2.685, ndigits=2))
        print(round(25, -1), round(35, -1))
        print(round(-25, -1), round(-35, -1))
        print(round(2.5, 0) == 2.0)
        print(round(3.5, 0) == 4.0)
        print(round(1.25, 1), round(1.35, 1))
        print(round(1.2, None))
        print(round(1.25, 400) == 1.25)
        print(str(round(-1.0, -400)))
        """
    )


def test_round_handles_non_finite_floats_like_python():
    assert_semantics(
        """\
        infinity = float("inf")
        not_a_number = float("nan")
        try:
            round(infinity)
        except Exception as error:
            print(str(error))
        try:
            round(not_a_number)
        except Exception as error:
            print(str(error))
        print(str(round(infinity, 2)))
        print(str(round(not_a_number, 2)))
        """
    )


def test_round_matches_python_across_float_magnitudes_and_precisions():
    assert_semantics(
        """\
        values = [
            -1234.5678,
            -35.0,
            -2.675,
            -0.0,
            0.0,
            0.125,
            1.35,
            2.675,
            35.0,
            1234.5678,
            1e-300,
            1e300,
        ]
        precisions = [-400, -301, -10, -2, -1, 0, 1, 2, 10, 301, 400]
        for value in values:
            for precision in precisions:
                print(str(round(value, precision)))
        """
    )


def test_safe_integer_boundaries_are_preserved():
    assert_semantics(
        """\
        print(9007199254740991)
        print(-9007199254740991)
        print(4503599627370495 + 4503599627370496)
        """
    )


def test_unsafe_integer_literals_are_rejected():
    assert_compilation_diagnostic(
        """\
        def main():
            print(9007199254740992)
        """,
        """
          File "unsafe_integer.py", line 2
            print(9007199254740992)
                  ^^^^^^^^^^^^^^^^
        pyjs.CompilationError: constant integer expression exceeds JavaScript's safe integer range [PYJS2001]
        help: Keep statically known integers between -9007199254740991 and 9007199254740991.
        """,
        filename="unsafe_integer.py",
    )


def test_unsafe_constant_integer_arithmetic_is_rejected():
    assert_compilation_diagnostic(
        """\
        def main():
            print(2 ** 53)
        """,
        """
          File "unsafe_arithmetic.py", line 2
            print(2 ** 53)
                  ^^^^^^^
        pyjs.CompilationError: constant integer expression exceeds JavaScript's safe integer range [PYJS2001]
        help: Keep statically known integers between -9007199254740991 and 9007199254740991.
        """,
        filename="unsafe_arithmetic.py",
    )


def test_unsafe_constant_integer_shift_is_rejected():
    assert_compilation_diagnostic(
        """\
        def main():
            print(1 << 53)
        """,
        """
          File "unsafe_shift.py", line 2
            print(1 << 53)
                  ^^^^^^^
        pyjs.CompilationError: constant integer expression exceeds JavaScript's safe integer range [PYJS2001]
        help: Keep statically known integers between -9007199254740991 and 9007199254740991.
        """,
        filename="unsafe_shift.py",
    )


def test_unsafe_javascript_integer_range_does_not_limit_analysis():
    with analyze_source(
        "def main():\n    print(2 ** 53)\n",
        filename="backend_integer.py",
        wrap=False,
    ):
        pass


def test_integer_inversion_uses_python_arithmetic_semantics():
    assert_semantics(
        """\
        print(~0)
        print(~5)
        print(~-5)
        print(~4294967296)
        """
    )


def test_custom_unary_operators_dispatch_to_dunder_methods():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Value:
            def __init__(self, number: int):
                self.number = number

            def __pos__(self) -> int:
                return self.number + 1

            def __neg__(self) -> int:
                return self.number - 1

            def __invert__(self) -> int:
                return self.number * 2

        value = Value(4)
        print(+value, -value, ~value)
        """
    )


def test_math_module_matches_python_for_supported_functions_and_constants():
    assert_semantics(
        """\
        import math

        print(math.sqrt(9.0) == 3.0, math.sin(0.0) == 0.0)
        print(math.cos(0.0) == 1.0, math.tan(0.0) == 0.0)
        print(math.asin(0.0) == 0.0, math.atan(0.0) == 0.0)
        print(math.atan2(0.0, 1.0) == 0.0)
        print(math.radians(180.0) == math.pi, math.ceil(1.2) == 2)
        print(math.isfinite(math.inf), math.isfinite(1.0))
        print(math.hypot(3.0, 4.0) == 5.0)
        print(math.dist((0.0, 0.0), (3.0, 4.0)) == 5.0)
        print(math.isclose(1.0, 1.0000000001))
        print(math.isclose(math.inf, math.inf))
        print(math.tau == math.pi * 2.0)
        print(math.pow(2.0, 10.0) == 1024.0, math.pow(4.0, 0.5) == 2.0)
        print(math.floor(1.7) == 1, math.floor(-1.2) == -2)
        print(math.exp(0.0) == 1.0, math.exp(1.0) > 2.718)
        print(math.fmod(7.0, 3.0) == 1.0, math.fmod(-7.0, 3.0) == -1.0)
        print(math.fmod(7.0, -3.0) == 1.0, math.fmod(5.5, 2.0) == 1.5)
        print(math.log(1.0) == 0.0, math.log(math.exp(2.0)) == 2.0)
        print(math.acos(1.0) == 0.0, math.acos(-1.0) == math.pi)
        """
    )


def test_direct_math_imports_use_the_same_implementations():
    assert_semantics(
        """\
        from math import hypot, isclose, pi

        print(hypot(5.0, 12.0) == 13.0)
        print(isclose(0.1 + 0.2, 0.3))
        print(pi)
        """
    )


def test_math_functions_accept_portable_int64_values():
    assert_semantics(
        """
        from collections.abc import Callable
        import math
        from pyjs import int64, js

        @js.inline("Math.sqrt({value})")
        def root(value: float) -> float:
            return value**0.5

        @js
        def half(value: float) -> float:
            return value / 2.0

        @js
        def apply(
            function: Callable[[float], float],
            value: int64,
        ) -> float:
            return function(value)

        @js
        def union_root(value: int64 | float) -> float:
            return math.sqrt(value)

        @js
        def main() -> None:
            print(math.sqrt(int64(9)))
            print(math.atan2(int64(0), int64(1)))
            print(math.hypot(int64(3), int64(4)))
            print(math.fmod(int64(7), int64(3)))
            print(math.ceil(int64(7)), math.floor(int64(-7)))
            print(math.isfinite(int64(9)))
            print(math.isclose(int64(9), 9.0))
            print(root(int64(16)))
            print(half(int64(8)))
            print(apply(half, int64(8)))
            print(union_root(int64(25)), union_root(36.0))

        main()
        """
    )


def test_chained_comparisons_short_circuit_and_evaluate_operands_once():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def record(events: list[str], name: str, value: int) -> int:
            events.append(name)
            return value

        failed_events: list[str] = []
        failed = (
            record(failed_events, "left", 3)
            < record(failed_events, "middle", 2)
            < record(failed_events, "right", 1)
        )
        print(
            failed,
            len(failed_events),
            failed_events[0],
            failed_events[1],
        )

        passed_events: list[str] = []
        passed = (
            record(passed_events, "left", 1)
            < record(passed_events, "middle", 2)
            < record(passed_events, "right", 3)
        )
        print(
            passed,
            len(passed_events),
            passed_events[0],
            passed_events[1],
            passed_events[2],
        )

        longer_events: list[str] = []
        longer = (
            record(longer_events, "first", 0)
            < record(longer_events, "second", 1)
            < record(longer_events, "third", 2)
            < record(longer_events, "fourth", 3)
        )
        print(
            longer,
            len(longer_events),
            longer_events[0],
            longer_events[1],
            longer_events[2],
            longer_events[3],
        )
        print(0 < 1 in (1, 2))

        __pyjs_compare_0 = 100
        print(1 < 2 < __pyjs_compare_0)
        """
    )


def test_min_and_max_support_values_iterables_keys_and_defaults():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def value_length(value: str):
            return len(value)

        @js
        def numeric_key(value: int) -> int:
            return value

        print(min(3, 1, 2), max(3, 1, 2))
        print(min([4, -2, 8]), max((4, -2, 8)))
        print(min([4, -2, 8], key=None))
        print(min("cab"), max(range(4)))
        print(min(["three", "a", "two"], key=value_length))
        print(len("three"), min(["three", "a", "two"], key=len))
        print(max("long", "x", "medium", key=len))
        print(abs(-5), min(-5, -2, 3, key=abs))
        print(max([1, -2.5], key=abs))
        mapping = {"a": 1, "b": 2}
        values = [1]
        selected = min(mapping, values, key=len)
        print("values" if selected is values else "mapping")
        print(numeric_key(3), "true" if max([False, True], key=numeric_key) else "false")
        print(max([], default=7))
        try:
            min([])
        except Exception as error:
            print(str(error))
        try:
            max()
        except Exception as error:
            print(str(error))
        try:
            min(1, 2, default=0)
        except Exception as error:
            print(str(error))
        """
    )


def test_range_and_extreme_failures_use_python_exception_types():
    assert_semantics(
        """\
        step = 0
        try:
            range(0, 3, step)
        except ValueError as error:
            print(str(error))

        try:
            min([])
        except ValueError as error:
            print(str(error))

        try:
            max()
        except TypeError as error:
            print(str(error))

        try:
            min(1, 2, default=0)
        except TypeError as error:
            print(str(error))
        """
    )


def test_bitwise_and_shift_operations_preserve_safe_integer_width():
    assert_semantics(
        """\
        high = 2**40
        mask = 2**35 + 3
        print(high | mask)
        print((high | mask) & (high + 7))
        print((high | mask) ^ high)
        print(high | True, high & True, high ^ True)

        shift = 40
        shifted = 1 << shift
        print(shifted, shifted >> shift)
        print(-8 >> 2, -1 >> 100, 7 >> 100)
        print(0 << 100)

        count = -1
        try:
            1 << count
        except ValueError as error:
            print(str(error))
        try:
            1 >> count
        except ValueError as error:
            print(str(error))
        """
    )


def test_bitwise_and_shift_operations_have_explicit_safe_lowering():
    at(
        """\
        def main(left: int, right: int, count: int):
            either = left | right
            both = left & right
            changed = left ^ right
            shifted_left = left << count
            shifted_right = left >> count
        """,
        """
        def main(left: int, right: int, count: int) -> None:
            either: int = left.[int]__or__!(right)
            both: int = left.[int]__and__!(right)
            changed: int = left.[int]__xor__!(right)
            shifted_left: int = left.[int]__lshift__!(count)
            shifted_right: int = left.[int]__rshift__!(count)
        """,
        """
        export function main(left, right, count) {
            var either = Number(BigInt(left) | BigInt(right));
            var both = Number(BigInt(left) & BigInt(right));
            var changed = Number(BigInt(left) ^ BigInt(right));
            var shifted_left = ((value,count)=>{if(count<0)throw new RangeError('negative shift count');if(count>52){if(value===0)return 0;throw new RangeError('integer result exceeds JavaScript safe integer range');}const result=Number(BigInt(value)<<BigInt(count));if(!Number.isSafeInteger(result))throw new RangeError('integer left shift exceeds JavaScript safe integer range');return result;})(left,count);
            var shifted_right = ((value,count)=>{if(count<0)throw new RangeError('negative shift count');if(count>52){return value<0?-1:0;}const result=Number(BigInt(value)>>BigInt(count));if(!Number.isSafeInteger(result))throw new RangeError('integer right shift exceeds JavaScript safe integer range');return result;})(left,count);
        }
        """,
    )


def test_min_and_max_use_sequence_and_custom_ordering_protocols():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Ranked:
            def __init__(self, rank: int):
                self.rank = rank

            def __lt__(self, other: "Ranked") -> bool:
                return self.rank < other.rank

        print(min([[2], [10]])[0])
        print(min([Ranked(2), Ranked(1)]).rank)
        print(max([Ranked(2), Ranked(1)]).rank)
        for value in sorted([Ranked(3), Ranked(1), Ranked(2)]):
            print(value.rank)
        """
    )


def test_min_and_max_validate_key_parameter_types():
    ad(
        """\
        from pyjs import js

        @js
        def text_length(value: str) -> int:
            return len(value)

        def main():
            value = min([1, 2], key=text_length)
        """,
        """
          File "min_key.py", line 8
            value = min([1, 2], key=text_length)
                                    ^^^^^^^^^^^
        pyjs.CompilationError: Callable argument 'key' to min accepts str, but must accept int [PYJS1104]
        note: min_key.py:4:5: callable defined here
        help: Widen the callable parameter annotation to accept every input value.
        """,
        filename="min_key.py",
    )


def test_min_and_max_validate_every_union_member_against_user_key():
    ad(
        """\
        from pyjs import js

        @js
        def integer_key(value: int) -> int:
            return value

        @js
        def values() -> list[int | float]:
            return [1, 2.5]

        def main():
            selected = min(values(), key=integer_key)
        """,
        diagnostic_text(
            "min_union_key.py",
            12,
            "selected = min(values(), key=integer_key)",
            "                             ^^^^^^^^^^^",
            "pyjs.CompilationError: Callable argument 'key' to min accepts int, "
            "but must accept int|float [PYJS1104]",
            "note: min_union_key.py:4:5: callable defined here",
            "help: Widen the callable parameter annotation to accept every input value.",
        ),
        filename="min_union_key.py",
    )


def test_supported_division_operations_raise_on_zero():
    assert_semantics(
        """\
        try:
            print(1 / 0)
        except Exception as error:
            print(str(error))
        try:
            print(1 // 0)
        except Exception as error:
            print(str(error))
        try:
            print(1 % 0)
        except Exception as error:
            print(str(error))
        try:
            print(1.0 / 0.0)
        except Exception as error:
            print(str(error))
        try:
            print(1.0 // 0.0)
        except Exception as error:
            print(str(error))
        try:
            print(1.0 % 0.0)
        except Exception as error:
            print(str(error))
        """
    )


def test_bool_is_an_int_for_isinstance_checks():
    assert_semantics(
        """\
        print(isinstance(True, int))
        print(isinstance(False, int))
        print(isinstance(True, float))
        print(isinstance(1, bool))
        """
    )


def test_numeric_isinstance_preserves_static_float_identity():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def floating() -> float:
            print("called")
            return 1.0

        @js
        def float_or_text(decimal: bool) -> float | str:
            return 1.0 if decimal else "one"

        @js
        def int_or_text(integer: bool) -> int | str:
            return 1 if integer else "one"

        @js
        def number(decimal: bool) -> int | float:
            return 1.0 if decimal else 1

        print(isinstance(floating(), int))
        print(isinstance(floating(), float))
        print(isinstance(float_or_text(True), float))
        print(isinstance(float_or_text(False), float))
        print(isinstance(int_or_text(True), int))
        print(isinstance(int_or_text(False), int))
        print(isinstance(number(True), (int, float)))
        print(isinstance(number(False), (int, float)))
        """
    )


def test_ambiguous_numeric_isinstance_is_rejected():
    ad(
        """\
        from pyjs import js

        @js
        def value() -> int | float:
            return 1

        def main():
            print(isinstance(value(), int))
        """,
        diagnostic_text(
            "numeric_isinstance.py",
            8,
            "print(isinstance(value(), int))",
            "      ^^^^^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: isinstance() cannot distinguish int from "
            "float after JavaScript lowering [PYJS1104]",
            "help: Narrow the value statically before testing its numeric type.",
        ),
        filename="numeric_isinstance.py",
    )

    ad(
        """\
        from pyjs import js

        @js
        def value() -> object:
            return 1.0

        def main():
            print(isinstance(value(), float))
        """,
        diagnostic_text(
            "object_isinstance.py",
            8,
            "print(isinstance(value(), float))",
            "      ^^^^^^^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: isinstance() cannot distinguish int from "
            "float after JavaScript lowering [PYJS1104]",
            "help: Narrow the value statically before testing its numeric type.",
        ),
        filename="object_isinstance.py",
    )


def test_boolean_and_numeric_equality_match_python():
    assert_semantics(
        """\
        print(1 == 1.0, 1.0 == 1)
        print(1.0 == True, 0.0 == False)
        print(2.0 != True, 1.0 != True)
        """
    )


def test_tuple_isinstance_checks_evaluate_the_value_once():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def make_value() -> int:
            print("called")
            return 1

        print(isinstance(make_value(), (int, (float, bool))))
        print(isinstance(make_value(), ()))
        print(isinstance([], (list, dict)))
        print(isinstance({}, (list, dict)))
        """
    )


def test_tuple_isinstance_narrowing_supports_numeric_operations():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def calculate(value: object) -> int | float:
            if isinstance(value, (int, float)):
                return (value + 1) * 2
            return 0

        print(calculate(2) == 6)
        print(calculate(2.5) == 7.0)
        print(calculate("other") == 0)
        """
    )


def test_bitwise_operators_preserve_python_bool_and_int_semantics():
    assert_semantics(
        """\
        print(True | False, 2 | True, True | 2)
        print(True & False, 2 & True, True & 2)
        print(True ^ False, 2 ^ True, True ^ 2)
        """
    )


def test_common_integer_and_float_conversions_match_python():
    assert_semantics(
        """\
        print(int() == 0)
        print(int("12") == 12)
        print(int("-1_000") == -1000)
        print(int(1.9) == 1)
        print(int(True) == 1)
        print(float() == 0.0)
        print(float("1.25") == 1.25)
        print(float(True) == 1.0)
        print(float("nan") != float("nan"))
        try:
            int("12px")
        except ValueError as error:
            print(str(error))
        try:
            float("not-a-number")
        except ValueError as error:
            print(str(error))
        """
    )


def test_integer_string_bases_match_python():
    assert_semantics(
        """\
        cases = [
            ("101", 2),
            ("0xff", 0),
            ("0X_ff", 16),
            ("010", 10),
            ("00", 0),
            ("z", 36),
            ("-11", 8),
        ]
        for text, base in cases:
            print(int(text, base))

        for text, base in [("010", 0), ("2", 2), ("10", 1)]:
            try:
                print(int(text, base))
            except Exception as error:
                print(str(error))

        try:
            print(int(12, 2))
        except Exception as error:
            print(str(error))
        """
    )


def test_integer_true_division_is_inferred_as_float():
    at(
        """\
        def main():
            value = 5 / 2
        """,
        """
        def main() -> None:
            value: float = 5.[int]__truediv__!(2)
        """,
        """
        export function main() {
            var value = ((left,right)=>{if(right===0)throw new Error('division by zero');return left/right;})(5,2);
        }
        """,
    )


def test_integer_base_strings_preserve_signs_and_boolean_values():
    assert_semantics(
        """\
        print(bin(-10), oct(-10), hex(-10))
        print(bin(True), oct(True), hex(True))
        """
    )


def test_sum_supports_integer_float_and_generator_values():
    assert_semantics(
        """\
        print(sum([1, 2, 3]))
        print(sum([1.5, 2.25]))
        print(sum([1, 2], 0.5))
        print(sum((value / 2 for value in range(4)), 0.25))
        """
    )


def test_divmod_matches_python_across_operand_signs_and_numeric_types():
    assert_semantics(
        """\
        print(divmod(7, 3) == (2, 1))
        print(divmod(-7, 3) == (-3, 2))
        print(divmod(7, -3) == (-3, -2))
        print(divmod(-7, -3) == (2, -1))
        print(divmod(7.5, 3.0) == (2.0, 1.5))
        print(divmod(-7.5, 3.0) == (-3.0, 1.5))
        print(divmod(7.5, -3.0) == (-3.0, -1.5))
        print(divmod(-7.5, -3.0) == (2.0, -1.5))
        """
    )


def test_inline_math_arguments_keep_their_grouping():
    assert_semantics(
        """\
        import math

        a = 4.0
        print(math.fmod(a, math.pi * 2))
        print(math.fmod(a + 3.0, 2.0 + 1.0))
        print(math.radians(a + 2.0))
        print(math.hypot(a + 1.0, 2.0 * 2.0))
        print(math.floor(a / 3.0))
        """
    )


def test_shader_conversions_and_hash_match_python():
    assert_semantics(
        """\
        from pyjs import js
        from pyjs.shader import i32, u32

        @js
        def ihash_xy(cx: float, cy: float, salt: u32) -> float:
            h = u32(i32(cx) + 1048576) * 73856093 ^ u32(i32(cy) + 1048576) * 19349663 ^ salt * 83492791
            h = h ^ (h >> 16)
            h = h * 2135587861
            h = h ^ (h >> 15)
            h = h * 2246822507
            h = h ^ (h >> 16)
            return float(h >> 8) / 16777216.0

        print(u32(i32(-1)) + 0, i32(-3.7), i32(3.7))
        print((u32(2135587861) * 4000000000) + 0)
        print(ihash_xy(0.0, 0.0, u32(0)), ihash_xy(3.0, -4.0, u32(7)), ihash_xy(-1000000.0, 999999.0, u32(3)))
        """
    )


def test_shader_vectors_use_value_equality_in_python_and_javascript():
    assert_semantics(
        """\
        from pyjs.shader import vec2f, vec3f, vec4f

        print(vec2f(1.0, 2.0) == vec2f(1.0, 2.0))
        print(vec2f(1.0, 2.0) != vec2f(1.0, 3.0))
        print(vec3f(1.0, 2.0, 3.0) == vec3f(1.0, 2.0, 3.0))
        print(vec3f(1.0, 2.0, 3.0) != vec3f(1.0, 2.0, 4.0))
        print(vec4f(1.0, 2.0, 3.0, 4.0) == vec4f(1.0, 2.0, 3.0, 4.0))
        print(vec4f(1.0, 2.0, 3.0, 4.0) != vec4f(1.0, 2.0, 3.0, 5.0))
        """
    )
