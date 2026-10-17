import ctypes
import math
import random
import struct
from itertools import product

import pytest

from pyjs import int32
from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import arena, float_math, float_text, numeric_text
from pyjs.native.runtime.numeric import WHITESPACE
from pyjs.native.runtime.pointers import Pointer
from pyjs.native.unicode_data import DECIMAL_RANGES
from tests.native.runtime_support import runtime_functions, runtime_library, string


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def parsers(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm('''
        def parse(value: str) -> str:
            return str(int(value)) + str(float(value))
        def main() -> str:
            return parse("1")
    '''))
    invoke = runtime_functions({
        "pyjs.unicode.decimal.value.with.table": numeric_text.decimal_value,
        "pyjs.int.from.string.into": numeric_text.parse_integer,
        "pyjs.float.from.string.into": numeric_text.parse_float,
        "pyjs.string.format.f64": float_text.format_float,
        "pyjs.float.divide": float_math.divide,
        "pyjs.float.integer.order": float_math.integer_order,
        "pyjs.float.divmod.into": float_math.divmod_into,
        "pyjs.float.round.digits": float_math.round_digits,
    }, library)
    table = (ctypes.c_int32 * (len(DECIMAL_RANGES) * 2))(*[item for pair in DECIMAL_RANGES for item in pair])
    spaces = string(WHITESPACE.encode())
    context = Pointer(ctypes.addressof(spaces)), Pointer(ctypes.addressof(table)), len(DECIMAL_RANGES)
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    try:
        yield invoke, context, owner
    finally:
        arena.destroy_arena(owner)


def test_exact_mixed_numeric_ordering(parsers):
    invoke, _, _ = parsers
    integers = (-2**63, -2**63 + 1, -2**53 - 1, -2**53, -1, 0, 1,
                2**53, 2**53 + 1, 2**63 - 1)
    floats = (-math.inf, -2**63 * 1.0, -2**53 * 1.0, -1.5, -0.0,
              math.nextafter(0.0, 1.0), 1.5, 2**53 * 1.0,
              math.nextafter(2**63 * 1.0, 0.0), 2**63 * 1.0, math.inf, math.nan)
    for integer, floating in product(integers, floats):
        expected = 2 if math.isnan(floating) else (integer > floating) - (integer < floating)
        assert invoke("pyjs.float.integer.order", integer, floating) == expected, (integer, floating)


def test_integer_parser_handles_unicode_prefixes_underscores_and_checked_bounds(parsers):
    invoke, context, _ = parsers
    cases = ("", " ", "+", "-", "0", "00", "01", "0_0", "0_1", "-0", "١_٢٣", "\u2003-42\xa0",
             "0b101", "٠b_101", "0B__1", "0x_Ff", "０xFF", "0x", "0x_", "0o77", "ff", "1z", "zZ",
             "1_2", "_1", "1_", "1__2", "1 2", "1\x00", "²", "1é", "\u3000+１２３\u3000",
             "9223372036854775807", " -9223372036854775808 ",
             "9223372036854775808", "-9223372036854775809", "1234567890" * 10,
             "0x1ffffffffffffffff", "١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨٩٠",
             "9" * 100 + "!", "9" * 100 + "_", "9" * 100 + "__1",
             "\x1c1", "1\x1f", "\u001e2")
    for value, base in product(cases, (0, 2, 3, 8, 10, 16, 36)):
        header = string(value.encode())
        result = (ctypes.c_int64 * 3)(123, 77, 456)
        status = invoke("pyjs.int.from.string.into", Pointer(ctypes.addressof(header)), base, *context,
                       Pointer(ctypes.addressof(result) + 8))
        try:
            expected = int(value, base)
        except ValueError:
            assert status == 0, (value, base)
            assert list(result) == [123, 77, 456]
        else:
            if not -(1 << 63) <= expected < (1 << 63):
                assert status == 3, (value, base)
                assert list(result) == [123, 77, 456]
                continue
            assert status == 1, (value, base)
            assert list(result) == [123, expected, 456]
    for character in "0123456789٠١٢٣٤٥٦٧٨٩０１２３４５６７８９abc²":
        expected = int(character) if character.isdecimal() else -1
        assert invoke("pyjs.unicode.decimal.value.with.table", int32(ord(character)), *context[1:]) == int32(expected)


def test_float_parser_rejects_c_only_syntax_and_preserves_special_values(parsers):
    invoke, context, owner = parsers
    cases = ("", " ", "+", "-", ".", "0", "-0", "1.25", "2.675", "1e309", "-1e309", "1e-400",
             "1_2.5_0e+1", "\u2003١٢.٥\xa0", "\u3000+１２３.４\u3000", "inf", "Infinity", "-INF", "nan", "-NaN",
             "nan(foo)", "nan()", "0x1p2", "0X1P2", "_1", "1_", "1__2", "1_.2", "1._2", "1e_2",
             "1_e2", "1e+_2", "1 2", "1\x00", "١_٢", "١_é", "²", "１_２.３_４",
             "\x1c1", "1\x1f", "\u001e2")
    for value in cases:
        header = string(value.encode())
        result = (ctypes.c_double * 3)(123.5, 77.25, 456.5)
        valid = invoke("pyjs.float.from.string.into", owner, Pointer(ctypes.addressof(header)), *context,
                       Pointer(ctypes.addressof(result) + 8))
        try:
            expected = float(value)
        except ValueError:
            assert not valid, value
            assert list(result) == [123.5, 77.25, 456.5]
        else:
            assert valid, value
            assert result[0] == 123.5 and result[2] == 456.5
            assert math.isnan(result[1]) if math.isnan(expected) else result[1].hex() == expected.hex()


def test_float_formatter_preserves_roundtrips_notation_and_guard_bytes(parsers):
    invoke, _, _ = parsers
    values = [0.0, -0.0, 1.0, -1.0, math.inf, -math.inf, math.nan, -math.nan, 5e-324, -5e-324]
    for exponent in (-308, -20, -5, -4, -3, 0, 15, 16, 17, 20, 308):
        value = 10.0**exponent
        values.extend((value, math.nextafter(value, 0.0), math.nextafter(value, math.inf)))
    randomizer = random.Random(915)
    values.extend(struct.unpack("d", struct.pack("Q", randomizer.getrandbits(64)))[0] for _ in range(512))
    for value in values:
        storage = ctypes.create_string_buffer(b"!" * 66, 66)
        count = invoke("pyjs.string.format.f64", Pointer(ctypes.addressof(storage) + 1), value)
        expected = str(value).encode()
        assert storage.raw[0:1] == storage.raw[-1:] == b"!"
        assert count == len(expected)
        assert storage.raw[1:count + 2] == expected + b"\0"


def test_float_divmod_and_rounding_preserve_signs_and_special_values(parsers):
    invoke, _, _ = parsers
    values = (0.0, -0.0, -5e-324, 5e-324, -10.5, -2.5, -1.0, 1.0, 2.5, 10.5,
              1e30, -1e30, math.inf, -math.inf, math.nan)
    for left, right in product(values, repeat=2):
        if right == 0.0:
            continue
        result = invoke("pyjs.float.divide", left, right)
        expected = left / right
        assert math.isnan(result) if math.isnan(expected) else result.hex() == expected.hex()
        output = (ctypes.c_double * 4)(123.5, 0.0, 0.0, 456.5)
        invoke("pyjs.float.divmod.into", left, right, Pointer(ctypes.addressof(output) + 8))
        assert output[0] == 123.5 and output[3] == 456.5
        for result, expected in zip(output[1:3], divmod(left, right), strict=True):
            assert math.isnan(result) if math.isnan(expected) else result.hex() == expected.hex()
    for value, digits in product((*values, 2.675, 1.005, 1250.0, 1350.0), (-400, -308, -20, -2, -1, 0, 2, 20, 323, 400)):
        expected = round(value, digits)
        result = invoke("pyjs.float.round.digits", value, digits)
        assert math.isnan(result) if math.isnan(expected) else result.hex() == expected.hex()


def test_negative_decimal_rounding_does_not_round_binary_values_twice(parsers):
    invoke, _, _ = parsers
    cases = [
        (-3.2238653178564467e249, -45),
        (999.5, -1), (995.0, -1), (985.0, -1), (500.0, -3),
        (math.nextafter(500.0, math.inf), -3),
        (math.nextafter(500.0, 0.0), -3), (1500.0, -3),
        (-500.0, -3), (-1500.0, -3),
    ]
    randomizer = random.Random(99)
    cases.extend(
        (randomizer.uniform(-1, 1) * 10.0 ** randomizer.randrange(-20, 300),
         -randomizer.randrange(1, 309))
        for _ in range(512)
    )
    for value, digits in cases:
        assert invoke("pyjs.float.round.digits", value, digits).hex() == round(value, digits).hex()
