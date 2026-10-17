import ctypes
import random
from itertools import product

import pytest

from pyjs import int64
from pyjs.native.runtime import integer_math as integers
from pyjs.native.runtime.numeric import integer_runtime
from pyjs.native.runtime.pointers import Pointer
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def integer_functions(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join(integer_runtime(include_modular_pow=True)))
    return runtime_functions({
        "pyjs.int.bit_count": integers.bit_count,
        "pyjs.int.bit_length": integers.bit_length,
        "pyjs.int.divmod.into": integers.divmod_into,
        "pyjs.int.pow": integers.power,
        "pyjs.int.round.digits": integers.round_digits,
        "pyjs.int.true.divide": integers.true_divide,
        "pyjs.int.pow.modular.into": integers.modular_power,
    }, library)


def test_bit_methods_count_absolute_magnitudes(integer_functions):
    values = {-(1 << 63), (1 << 63) - 1, 0}
    for shift in range(63):
        for offset in (-1, 0, 1):
            values.update((2**shift + offset, -(2**shift + offset)))
    randomizer = random.Random(751)
    values.update(randomizer.randint(-(1 << 63), (1 << 63) - 1) for _ in range(512))
    for value in values:
        for method in ("bit_count", "bit_length"):
            assert integer_functions("pyjs.int." + method, value) == getattr(value, method)()


def test_integer_arithmetic_preserves_extreme_signed_bounds(integer_functions):
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    bounds = (minimum, minimum + 1, -(1 << 53) - 1, -2, -1, 0, 1, 2, (1 << 53) + 1, maximum)
    randomizer = random.Random(914)
    pairs = list(product(bounds, repeat=2))
    pairs.extend((randomizer.randint(minimum, maximum), randomizer.randint(minimum, maximum)) for _ in range(512))
    for left, right in pairs:
        if right == 0:
            continue
        result = integer_functions("pyjs.int.true.divide", left, right)
        assert result.hex() == (left / right).hex()
        for wrapped in (False, True):
            if not wrapped and left == minimum and right == -1:
                continue
            output = (ctypes.c_int64 * 4)(123, 0, 0, 456)
            integer_functions("pyjs.int.divmod.into", left, right, wrapped, Pointer(ctypes.addressof(output) + 8))
            divided, remainder = divmod(left, right)
            assert list(output) == [123, int(int64(divided)), remainder, 456]


def test_rounding_and_power_match_python_with_native_result_width(integer_functions):
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    values = [minimum, maximum, -1, 0, 1]
    for digits in range(19):
        values.extend(multiplier * 10**digits for multiplier in (-5, -3, -1, 1, 3, 5)
                      if minimum <= multiplier * 10**digits <= maximum)
    for value, digits in product(values, (minimum, -20, -19, -18, -4, -2, -1, 0, 10, maximum)):
        # CPython may try to build 10**abs(ndigits); the native-i64 result is
        # necessarily zero beyond 19 decimal places without that allocation.
        expected = 0 if digits < -19 else round(value, digits)
        if minimum <= expected <= maximum:
            assert integer_functions("pyjs.int.round.digits", value, digits, False) == expected
        assert integer_functions("pyjs.int.round.digits", value, digits, True) == int(int64(expected))
    for base, exponent in product((-100, -2, -1, 0, 1, 2, 100, minimum, maximum), range(70)):
        assert integer_functions("pyjs.int.pow", base, exponent) == int(int64(pow(base, exponent)))


def test_modular_power_preserves_inverses_negative_moduli_and_failure_outputs(integer_functions):
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    for base, exponent, modulus in product(
        (minimum, -17, -2, -1, 0, 1, 2, 17, maximum),
        (minimum, -5, -1, 0, 1, 5, maximum),
        (minimum, -19, -6, -1, 1, 6, 19, maximum),
    ):
        output = (ctypes.c_int64 * 3)(123, 77, 456)
        try:
            expected = pow(base, exponent, modulus)
        except ValueError:
            assert not integer_functions("pyjs.int.pow.modular.into", base, exponent, modulus,
                                         Pointer(ctypes.addressof(output) + 8))
            assert list(output) == [123, 77, 456]
        else:
            assert integer_functions("pyjs.int.pow.modular.into", base, exponent, modulus,
                                     Pointer(ctypes.addressof(output) + 8))
            assert list(output) == [123, expected, 456]


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_true_division_preserves_signed_zero_in_application_code(tmp_path, optimize):
    LLVM().assert_matches_python('''
        def divide(left: int, right: int) -> float:
            return left / right

        def main() -> str:
            return str(divide(0, -1)) + ":" + str(divide(0, 1))
    ''', directory=tmp_path, optimize=optimize)
