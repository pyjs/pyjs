import math
import signal
from textwrap import dedent

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    EMPTY_LITERAL_SUM_CONTRACT,
    MEMBERSHIP_ORDER_CONTRACT,
    REPRESENTED_ROUNDING_CONTRACT,
    SCALAR_NUMERIC_CONTRACT,
)


@pytest.mark.parametrize("contract", [MEMBERSHIP_ORDER_CONTRACT, SCALAR_NUMERIC_CONTRACT, REPRESENTED_ROUNDING_CONTRACT,
                                     EMPTY_LITERAL_SUM_CONTRACT],
                         ids=["membership-order", "scalar-numeric", "represented-rounding", "empty-literal-sum"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_contract(tmp_path, optimize, contract):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path, optimize=optimize)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", [
    pytest.param('''
        def main() -> str:
            digits = -2
            result = ""
            for value in [150, 250, 350, -150, -250]:
                result += str(round(value, digits)) + ":"
            return result + str(round(9223372036854775807, -18)) + ":" + str(round(41.2, None))
    ''', id="integer-rounding"),
    pytest.param('''
        def main() -> str:
            result = ""
            for value in [2.675, 1.005, 1250.0, 1350.0, -0.0]:
                result += str(round(value, ndigits=2)) + ":" + str(round(value, -2)) + ":"
            return result + str(round(-1.2345, -400)) + ":" + str(round(1e309, 2))
    ''', id="float-rounding"),
    pytest.param('''
        from pyjs import int8, float32

        def main() -> str:
            value = round(int8(125), -1)
            rounded = round(float32(1.23456), 2)
            return str(value) + ":" + str(rounded) + ":" + str(round(float32(3.5)))
    ''', id="represented-rounding"),
    pytest.param('''
        def main() -> str:
            result = ""
            for left in [-9, -1, 0, 1, 9]:
                for right in [-3, -2, 1, 2]:
                    pair = divmod(left, right)
                    floats = divmod(float(left), float(right))
                    result += f"{pair[0]}:{pair[1]}:{floats[0]}:{floats[1]}:"
            return result
    ''', id="divmod"),
    pytest.param('''
        from pyjs import int8, int64

        def main() -> str:
            wrapped = divmod(int8(-128), -1)
            ordinary = divmod(int64(9223372036854775807), 1.1)
            return f"{wrapped[0]}:{wrapped[1]}:{ordinary[0]}:{ordinary[1]}"
    ''', id="divmod-representations"),
    pytest.param('''
        def main() -> str:
            result = ""
            for value in [-10.5, -0.0, 0.0, 10.5, 1e30]:
                result += str(value // -2.5) + ":" + str(value % -2.5) + ":"
            return result
    ''', id="float-operators"),
    pytest.param('''
        def main() -> str:
            result = ""
            for modulus in [-19, -1, 1, 19]:
                result += str(pow(-17, -5, modulus)) + ":" + str(pow(17, 63, modulus)) + ":"
            return result + str(pow(2, 16)) + ":" + str(pow(-3, 7, None))
    ''', id="modular-power"),
    pytest.param('''
        def main() -> str:
            text = " ٠x_Ff "
            value = int(text, base=0)
            other = float("１_２.３_４")
            return f"{value}:{other}:{float(True)}:{int(-2.9)}:{float('-0.0')}"
    ''', id="numeric-parsing"),
    pytest.param('''
        class State:
            def __init__(self):
                self.calls = 0

            def number(self) -> float:
                self.calls += 1
                return 2.675

            def digits(self) -> int:
                self.calls *= 10
                return 2

        def main() -> str:
            state = State()
            result = round(state.number(), ndigits=state.digits())
            return f"{result}:{state.calls}"
    ''', id="round-argument-order"),
    pytest.param('''
        class Values:
            def __init__(self, values: range):
                self.values = values

        def make_values() -> range:
            return range(-5, 12, 3)

        def main() -> str:
            original = make_values()
            holder = Values(original)
            result = ""
            for value in holder.values:
                result += str(value) + ":"
            for value in original[::-1]:
                result += str(value) + ":"
            return result + f"{original.start}:{original.stop}:{original.step}:{len(original)}:{original[-1]}"
    ''', id="stored-ranges"),
    pytest.param('''
        def main() -> str:
            enormous = range(-9223372036854775808, 9223372036854775807, 1)
            result = str(bool(enormous)) + ":" + str(enormous[-1]) + ":"
            for value in [-9223372036854775808, 0, 9223372036854775807]:
                result += str(value in enormous) + ":"
            small = enormous[0:3]
            for value in small:
                result += str(value) + ":"
            return result
    ''', id="wide-range-length"),
    pytest.param('''
        def main() -> str:
            value = range(1, 10, 3)
            return (str(value == range(1, 9, 3)) + ":" + str(value != range(1, 10, 2))
                    + ":" + str(value.count(7)) + ":" + str(value.count(8))
                    + ":" + str(value.index(4)) + ":" + str(range(0) == range(3, 3, -1)))
    ''', id="range-comparison"),
    pytest.param('''
        def needle(events: list[int]) -> str:
            events.append(1)
            return "key"

        def values(events: list[int]) -> set[str]:
            events.append(2)
            return {"key", "other"}

        def main() -> str:
            events: list[int] = []
            found = needle(events) in values(events)
            missing = needle(events) not in values(events)
            explicit = values(events).__contains__(needle(events))
            return f"{found}:{missing}:{explicit}:{events[0]}:{events[1]}:{events[2]}:{events[3]}:{events[4]}:{events[5]}"
    ''', id="set-membership-order"),
], ids=None)
def test_native_scalar_and_range_semantics(tmp_path, optimize, source):
    LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["str(7 / 2)", "f'{7 / 2}'", "str(round(7 / 2, 1))"])
def test_integer_division_links_float_helpers_without_other_float_sources(tmp_path, optimize, expression):
    LLVM().assert_matches_python(f"def main() -> str: return {expression}", directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_round_keyword_order_and_represented_results(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs import int8, int64, float32

        def number(events: list[int]) -> float32:
            events.append(1)
            return float32(2.675)

        def digits(events: list[int]) -> int:
            events.append(2)
            return 2

        def rounded(value: int64) -> int64:
            return round(ndigits=-19, number=value)

        def main() -> str:
            events: list[int] = []
            first = round(number=number(events), ndigits=digits(events))
            second = round(ndigits=digits(events), number=number(events))
            small = round(number=int8(125), ndigits=-1)
            wide = rounded(int64(9223372036854775807))
            ordinary = round(number=2.5)
            decimal = round(number=2.675, ndigits=2)
            return f"{first}:{second}:{small}:{wide}:{ordinary}:{decimal}:{events[0]}:{events[1]}:{events[2]}:{events[3]}"
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "int('9223372036854775808')", "int('-9223372036854775809')",
    "int('99999999999999999999')", "int('0x1ffffffffffffffff', 16)",
    "int('١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨٩٠')", "round(9223372036854775807, -1)",
    "round(-9223372036854775808, -1)", "round(9223372036854775807, -19)",
])
def test_unrepresented_integer_results_outside_native_bounds_trap(tmp_path, optimize, expression):
    assert not -(1 << 63) <= eval(expression) < (1 << 63)
    result = LLVM().run_source(f"def main() -> int: return {expression}", directory=tmp_path, optimize=optimize)
    assert result.returncode in {-signal.SIGILL, -signal.SIGTRAP}


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression,error", [
    ("int('1__0')", ValueError),
    ("int('0x10', 10)", ValueError),
    ("int('1', 1)", ValueError),
    ("int('1', 37)", ValueError),
    ("int(float('nan'))", ValueError),
    ("int(float('inf'))", OverflowError),
    ("int(9223372036854775808.0)", OverflowError),
    ("round(float('nan'))", ValueError),
    ("float('nan(payload)')", ValueError),
    ("float('0x1p2')", ValueError),
    ("float('1e_2')", ValueError),
    ("float('\\x1c1')", ValueError),
    ("int('\\x1f1')", ValueError),
    ("divmod(4.0, 0.0)", ZeroDivisionError),
    ("pow(2, -1, 4)", ValueError),
    ("pow(2, 5, 0)", ValueError),
    ("len(range(-9223372036854775808, 9223372036854775807))", OverflowError),
    ("range(0, 3, 0)", ValueError),
    ("range(0)[0]", IndexError),
    ("range(3).index(4)", ValueError),
    ("range(3)[::0]", ValueError),
])
def test_native_invalid_numeric_and_range_inputs_trap(tmp_path, optimize, expression, error):
    if expression == "int(9223372036854775808.0)":
        # This conversion is valid with Python big integers, outside native i64.
        assert eval(expression) == 1 << 63
    else:
        with pytest.raises(error):
            eval(expression)
    result = LLVM().run_source(
        f"def main() -> int:\n    {expression}\n    return 0",
        directory=tmp_path, optimize=optimize,
    )
    assert result.returncode in {-signal.SIGILL, -signal.SIGTRAP}


@pytest.mark.parametrize("source", [
    "def main() -> int: return int(2.5, 10)",
    "def main() -> int: return range(3).index(2, 0)",
])
def test_unsupported_numeric_forms_have_diagnostics(source):
    from pyjs.analysis.diagnostics import CompilationError

    with pytest.raises((LLVMUnsupported, CompilationError)):
        transpile_llvm(source)


def test_float_formatting_matches_python_for_realistic_settings_values(tmp_path):
    values = [
        0.0, -0.0, 0.01, 0.1, 0.5, 1.25, 100.0, 1e-4, 1e-5, 1e15,
        1e16, 5e-324, 1e308, math.inf, -math.inf, math.nan,
    ]
    library = LLVM().compile_library(dedent("""
        def main(value: float) -> str:
            return str(value)
    """), tmp_path)
    try:
        for value in values:
            assert library.render(value) == str(value)
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_settings_render_through_the_public_dom_with_collection(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import div, span, tw
        from pyjs.web.ssr import render_html

        def main() -> str:
            gc_set_threshold(1)
            rows: list[Element] = []
            for index in range(48):
                value = round(float(index) / 10.0, 2)
                row = div(
                    tw("setting"),
                    {"data-index": str(index)},
                    span(f"setting_{index}"),
                    span(str(value)),
                    span(str(int("1_024") + index)),
                )
                rows.append(row)
                gc_collect()
            return render_html(div(tw("settings"), *rows))
    ''', directory=tmp_path, optimize=optimize)
