import math

import pytest

from pyjs.analysis.ir import build_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native import math as native_math
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("operation", ["isqrt", "factorial", "perm"])
@pytest.mark.parametrize("called", [False, True])
def test_python_math_helpers_are_reached_by_indirect_calls_not_imports(operation, called):
    expression = f"list(map({operation}, [4]))[0]" if called else "4"
    with analyze_source(f'''
from math import {operation}
def main() -> int:
    return {expression}
''', entry_point="main", wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        functions = build_program_ir(analysis.entry_point).functions
        # Check the actual model function's identity, not a generated symbol
        # spelling. Native math bodies must still enter ordinary Python IR.
        helper = getattr(native_math, f"_{operation}")
        assert any(function.py_func is helper for function in functions) is called


@pytest.mark.parametrize("optimize", [0, 2])
def test_isqrt_indirect_values_preserve_index_effects_and_recovery(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
import math
from collections.abc import Callable
from itertools import starmap
from pyjs.native import gc_collect, gc_set_threshold
class Index:
    def __init__(self, value: int, events: list[int]):
        self.value, self.events = value, events
    def __index__(self) -> int:
        gc_collect()
        self.events.append(self.value)
        if self.value == -2:
            raise LookupError('index failure')
        return self.value
def callback() -> Callable[[object], int]:
    return math.isqrt
def collect(function: Callable[[object], int], values: list[object]) -> list[int]:
    return list(map(function, values))
def main() -> str:
    gc_set_threshold(1)
    events: list[int] = []
    function = callback()
    values: list[object] = [True, 2, Index(81, events)]
    output = str(collect(function, values))
    for value in [Index(-1, events), Index(-2, events), Index(16, events)]:
        try:
            output += str(function(value)) + ';'
        except ValueError as error:
            output += str(error) + ';'
        except LookupError as error:
            output += str(error) + ';'
    for bad in [1.5, '4', None]:
        try:
            function(bad)
            output += 'missed TypeError;'
        except TypeError:
            output += 'TypeError;'
    output += str(list(starmap(math.isqrt, [(4,), (9,), (25,)])))
    # Direct calls lower to the model helper without the callable adapter.
    for number in [0, 2, 81, -1, -2, 16]:
        try:
            output += str(math.isqrt(Index(number, events))) + ';'
        except ValueError as error:
            output += str(error) + ';'
        except LookupError as error:
            output += str(error) + ';'
    output += str(list(map(math.isqrt, [0, 1, 2, 3, 4, 8, 9, 15, 16, 17,
                                      9223372030926249000, 9223372030926249001,
                                      9223372036854775807])))
    gc_collect()
    return output + str(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_permutation_nullable_count_and_errors(optimize):
    LLVM().assert_matches_python('''
        import math
        from pyjs import int8

        def choose(n: int, k: int | None) -> int:
            return math.perm(n, k)

        def optional_flag(flag: bool | None) -> int:
            return math.perm(5, flag)

        def count(events: list[str]) -> int:
            events.append("count")
            return -1

        def main() -> str:
            result = ""
            for n in range(21):
                result += str(math.factorial(n)) + ":" + str(math.perm(n)) + ":" + str(choose(n, None))
                for k in range(22):
                    result += ":" + str(choose(n, k))
            assert math.perm(9223372036854775807, 0) == 1
            assert math.perm(9223372036854775807, 1) == 9223372036854775807
            assert math.perm(True, False) == 1
            assert math.perm(int8(5), int8(2)) == 20
            assert optional_flag(True) == 5
            assert optional_flag(False) == 1
            assert optional_flag(None) == 120
            events: list[str] = []
            try:
                math.perm(-1, count(events))
            except ValueError as error:
                result += str(error)
            assert events == ["count"]
            try:
                math.perm(1, -1)
            except ValueError as error:
                result += str(error)
            try:
                choose(-1, None)
            except ValueError as error:
                result += str(error)
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_first_class_math_module_aliases(optimize):
    LLVM().assert_matches_python('''
        import math
        import math as m
        from math import perm

        def main() -> str:
            first = math.perm
            second = m.comb
            third = perm
            fourth = m.sqrt
            return str(first(5, 2)) + str(second(5, 2)) + str(third(4, None)) + str(fourth(9.0))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("expression", ["math.perm(21)", "math.perm(9223372036854775807, 2)",
                                         "math.perm(9223372036854775807, 3)"])
def test_permutation_overflow_is_catchable(expression):
    source = f'''
        import math

        def main() -> int:
            try:
                {expression}
            except OverflowError:
                return 0
            return 1
    '''
    result = LLVM().run_source(source, optimize=2, sanitizers=("address", "undefined"))
    assert result.returncode == 0 and result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_logarithm_errors_preserve_input_kinds_and_evaluation_order(optimize):
    cases = ["log(0)", "log(-1)", "log(10, 0)", "log(10.0, -2)",
             "log2(0)", "log10(-1)", "log(0.0)", "log(10, 0.0)",
             "log2(-0.0)", "log10(-1.0)", "log(False)", "log(int8(-1))"]
    statements = "\n".join(f'''    try:
        math.{expression}
    except ValueError as error:
        result += str(error) + ";"
''' for expression in cases)
    LLVM().assert_matches_python(f'''
import math
from pyjs import int8

def later(events: list[int]) -> int:
    events.append(1)
    return -2

def fail() -> int:
    raise RuntimeError("later argument wins")

def main() -> str:
    result = ""
{statements}
    events: list[int] = []
    try:
        math.log(0, later(events))
    except ValueError as error:
        result += str(error) + str(len(events))
    try:
        math.log(0, fail())
    except RuntimeError as error:
        result += str(error)
    return result
''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "math.gcd(24, 18, 12)", "math.lcm(12, 18, 24)",
    "math.isqrt(9223372036854775807)", "math.comb(60, 30)",
    "math.factorial(20)", "math.sqrt(4)", "math.nextafter(0, 1, steps=2)",
])
def test_math_integer_and_scalar_boundaries(expression, optimize):
    LLVM().assert_matches_python(f'''
    import math

    def main() -> str:
        return str({expression})
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_scalar_family(optimize):
    unary = {
        "sqrt": 2.0, "sin": 0.4, "cos": 0.4, "tan": 0.4,
        "asin": 0.4, "acos": 0.4, "atan": 0.4, "acosh": 2.0,
        "asinh": 0.4, "atanh": 0.4, "cbrt": -2.0,
        "exp": 0.4, "exp2": 0.4, "expm1": 0.4,
        "log": 2.0, "log2": 2.0, "log10": 2.0, "log1p": 0.4,
        "fabs": -0.4, "radians": 45.0, "degrees": 0.4,
        "erf": 0.4, "erfc": 0.4, "tanh": 0.4, "sinh": 0.4,
        "cosh": 0.4, "gamma": 2.5, "lgamma": 2.5, "ulp": 1.0,
    }
    checks = []
    for name, value in unary.items():
        expected = getattr(math, name)(value)
        checks.append(f'assert math.isclose(math.{name}({value!r}), {expected!r}, rel_tol=1e-14), "{name}"')
    body = "\n        ".join(checks)
    LLVM().assert_matches_python(f'''
    import math

    def main() -> int:
        {body}
        assert math.floor(-1.5) == -2
        assert math.ceil(-1.5) == -1
        assert math.trunc(-1.5) == -1
        assert math.floor(9007199254740993) == 9007199254740993
        assert math.frexp(12.0) == (0.75, 4)
        assert math.modf(-1.5) == (-0.5, -1.0)
        assert math.ldexp(0.75, 4) == 12.0
        assert math.fmod(-7, 2) == -1.0
        assert math.remainder(7, 2) == -1.0
        assert math.copysign(2, -1) == -2.0
        assert math.pow(2, 3) == 8.0
        assert math.fma(2, 3, 4) == 10.0
        assert math.atan2(0, -1) == math.pi
        return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_errors_and_recovery(optimize):
    cases = {
        "ValueError": ["sqrt(-1)", "log(0)", "log2(-1)", "log10(0)",
                       "log1p(-1)", "asin(2)", "acos(-2)", "acosh(0)",
                       "atanh(1)", "sin(inf)", "cos(inf)", "tan(inf)",
                       "gamma(0)", "lgamma(-2)", "fmod(1, 0)",
                       "remainder(inf, 1)", "pow(-2, 0.5)", "pow(0, -1)",
                       "fma(0, inf, 1)", "isclose(1, 2, rel_tol=-1.0)",
                       "floor(nan)", "ceil(nan)", "trunc(nan)",
                       "factorial(-1)", "isqrt(-1)", "comb(-1, 0)",
                       "comb(2, -1)", "nextafter(0, 1, steps=-1)"],
        "OverflowError": ["exp(1000)", "exp2(1024)", "expm1(1000)",
                          "sinh(1000)", "cosh(1000)", "gamma(172)",
                          "ldexp(1, 9223372036854775807)", "pow(1e308, 2)",
                          "fma(1e308, 2, 0)", "floor(inf)", "trunc(-inf)"],
        "ZeroDivisionError": ["log(2, 1)"],
    }
    statements = []
    for error, expressions in cases.items():
        for expression in expressions:
            expression = expression.replace("inf", "math.inf").replace("nan", "math.nan")
            statements.append(f'''    try:
        math.{expression}
    except {error}:
        count += 1
''')
    body = "".join(statements)
    LLVM().assert_matches_python(f'''import math

def main() -> int:
    count = 0
{body}
    assert count == {sum(map(len, cases.values()))}
    assert math.sqrt(4) == 2.0
    return 0
''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_special_values_aliases_and_rounding(optimize):
    LLVM().assert_matches_python('''
    import math as m
    from math import sqrt as root, floor as down, pi
    from pyjs import float32, int64

    def number(events: list[int], marker: int) -> int:
        events.append(marker)
        return marker

    def main() -> str:
        events: list[int] = []
        assert m.isclose(b=number(events, 2), a=number(events, 1), abs_tol=number(events, 3))
        assert events == [2, 1, 3]
        assert m.isclose(**{'b': number(events, 2), 'a': number(events, 1), 'abs_tol': number(events, 3)})
        assert events == [2, 1, 3, 2, 1, 3]
        assert root(int64(4)) == 2.0
        assert root(float32(4)) == 2.0
        assert down(int64(9007199254740993)) == 9007199254740993
        assert m.pi == pi and m.tau == 2 * pi
        assert m.isnan(m.sqrt(m.nan)) and m.isnan(m.log(m.nan))
        assert m.isinf(m.exp(m.inf)) and m.exp(-m.inf) == 0.0
        assert not m.isfinite(m.nan) and not m.isfinite(m.inf)
        assert m.isclose(m.inf, m.inf) and not m.isclose(m.inf, -m.inf)
        assert not m.isclose(m.nan, m.nan)
        assert m.gcd() == 0 and m.lcm() == 1
        assert m.gcd(True, int64(2)) == 1
        assert m.isqrt(True) == 1 and m.factorial(int64(5)) == 120
        assert m.ldexp(2, True) == 4.0
        assert m.gcd(-9223372036854775808, 2) == 2
        assert m.gcd(-9223372036854775808, 0, 3) == 1
        assert m.lcm(9223372036854775807, 2, 0) == 0
        assert m.factorial(0) == 1 and m.comb(4, 5) == 0
        assert m.isqrt(0) == 0 and m.isqrt(1) == 1
        assert m.nextafter(0, 1, steps=9223372036854775807) == 1.0
        assert m.ulp(0) == 5e-324
        assert m.isinf(m.ulp(m.inf)) and m.isnan(m.ulp(m.nan))
        return (str(root(-0.0)) + str(m.modf(-0.0)[0]) + str(m.modf(-0.0)[1])
                + str(m.frexp(-0.0)[0]) + str(m.nextafter(-5e-324, 1))
                + str(m.nextafter(-0.0, 0.0, steps=0))
                + str(m.nextafter(-0.0, 0.0)) + str(m.ldexp(-0.0, 10)))
    ''', optimize=optimize)


@pytest.mark.parametrize("expression", [
    "math.factorial(21)", "math.factorial(100)", "math.comb(67, 33)",
    "math.gcd(-9223372036854775808)", "math.lcm(9223372036854775807, 2)",
])
def test_math_integer_results_report_native_width_limit(expression):
    source = f'''import math

def main() -> int:
    try:
        {expression}
    except OverflowError:
        return 0
    return 1
'''
    result = LLVM().run_source(source)
    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.parametrize("optimize", [0, 2])
def test_math_tuple_results_survive_collection(optimize):
    LLVM().assert_matches_python('''
    import math
    from pyjs.native import gc_collect, gc_set_threshold

    def main() -> str:
        gc_set_threshold(1)
        fraction = math.modf(-1.5)
        exponent = math.frexp(12)
        gc_collect()
        return str(fraction[0]) + str(fraction[1]) + str(exponent[0]) + str(exponent[1])
    ''', optimize=optimize)


@pytest.mark.parametrize("expression", ["math.sqrt(*[4])"])
def test_math_argument_unpacking_has_a_located_diagnostic(expression):
    with pytest.raises(LLVMUnsupported, match="argument unpacking.*at line"):
        transpile_llvm(f"import math\ndef main() -> str:\n    return str({expression})\n")
