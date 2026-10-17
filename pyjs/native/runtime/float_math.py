"""Floating-point algorithms with small explicit IEEE and libc leaves."""

import ctypes
import math
import struct

from pyjs import int8, int32, llvm
from pyjs.decorators import native_operation

from .algorithms import _runtime
from .numeric_text import parse_ascii_float
from .pointers import (
    Pointer,
    byte_offset,
    bytes_data,
    load_int8,
    null,
    stack_buffer,
    store_float,
    store_int8,
    trap,
)

INFINITY = 1e309


@llvm.inline("fptosi double {value} to i64")
def finite_integer(value: float) -> int:
    # Caller proves finite signed-i64 range before this conversion.
    return int(value)


@_runtime
def integer_equal(integer: int, floating: float) -> bool:
    if floating != floating or floating >= 9223372036854775808.0 or floating < -9223372036854775808.0:
        return False
    converted = finite_integer(floating)
    return integer == converted and float(converted) == floating


@_runtime
def integer_order(integer: int, floating: float) -> int:
    """Exact signed-i64 versus binary64 ordering; 2 denotes unordered (NaN)."""
    if floating != floating:
        return 2
    if floating >= 9223372036854775808.0:
        return -1
    if floating < -9223372036854775808.0:
        return 1
    converted = finite_integer(floating)
    if integer < converted:
        return -1
    if integer > converted:
        return 1
    # Only the fractional remainder remains. Large integral doubles convert
    # back exactly; small truncated integers are exactly representable too.
    if float(converted) < floating:
        return -1
    if float(converted) > floating:
        return 1
    return 0


@llvm.inline("fdiv double {left}, {right}")
def ieee_divide(left: float, right: float) -> float:
    return left / right


@llvm.inline("frem double {left}, {right}")
def ieee_remainder(left: float, right: float) -> float:
    try:
        return math.fmod(left, right)
    except ValueError:
        return math.nan


@llvm.inline("call double @llvm.fabs.f64(double {value})")
def absolute(value: float) -> float:
    return abs(value)


@llvm.inline("call double @llvm.copysign.f64(double {value}, double {sign})")
def copy_sign(value: float, sign: float) -> float:
    return math.copysign(value, sign)


@llvm.inline("call double @llvm.floor.f64(double {value})")
def floor(value: float) -> float:
    return float(math.floor(value)) if math.isfinite(value) else value


@llvm.inline("call double @llvm.roundeven.f64(double {value})")
def round_even(value: float) -> float:
    return copy_sign(float(round(value)), value) if math.isfinite(value) else value


@llvm.inline("call double @pow(double {value}, double {exponent})")
def power(value: float, exponent: float) -> float:
    return math.pow(value, exponent)


@llvm.inline("bitcast double {value} to i64")
def bits(value: float) -> int:
    return struct.unpack("q", struct.pack("d", value))[0]


@llvm.inline("getelementptr i8, ptr @pyjs.float.round.format, i64 0")
def fixed_format() -> Pointer:
    return bytes_data(b"%.*f\0")


@llvm.inline("getelementptr i8, ptr @pyjs.string.float.general, i64 0")
def general_format() -> Pointer:
    return bytes_data(b"%.*g\0")


@llvm.inline("getelementptr i8, ptr @pyjs.string.float.scientific, i64 0")
def scientific_format() -> Pointer:
    return bytes_data(b"%.*e\0")


@native_operation("system.format.float")
def format_buffer(buffer: Pointer, capacity: int, format: Pointer, precision: int32, value: float) -> int32:
    function = ctypes.CDLL(None).snprintf
    # Keep the actual variadic C ABI; treating snprintf as a fixed-signature
    # callback loses floating-argument bookkeeping on some native targets.
    function.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    function.restype = ctypes.c_int
    return int32(function(buffer.address, capacity, format.address, ctypes.c_int(int(precision)), ctypes.c_double(value)))


@_runtime
def divide(left: float, right: float) -> float:
    if right == 0.0:
        trap()
    return ieee_divide(left, right)


@_runtime
def round_digits(value: float, digits: int) -> float:
    if value != value or absolute(value) == INFINITY or digits > 323:
        return value
    if digits < -308:
        return copy_sign(0.0, value)
    if digits >= 0:
        buffer = stack_buffer(768)
        format_buffer(buffer, 768, fixed_format(), int32(digits), value)
        return parse_ascii_float(buffer, null())
    # Scaling a binary float down and back up can introduce a second rounding,
    # even when ndigits should leave a large value unchanged. Format its exact
    # decimal expansion, then round at the requested integer digit instead.
    # 1074 fractional digits suffice for every binary64, including subnormals.
    storage = stack_buffer(1408)
    buffer = byte_offset(storage, 1)
    count = int(format_buffer(buffer, 1407, fixed_format(), int32(1074), absolute(value)))
    if count < 0 or count >= 1407:
        trap()
    point = 0
    while point < count and load_int8(byte_offset(buffer, point)) != int8(46):
        point += 1
    if point == count:
        trap()
    keep = point + digits
    if keep < 0:
        return copy_sign(0.0, value)
    first = int(load_int8(byte_offset(buffer, keep)))
    following = keep + 1
    nonzero = False
    while following < count:
        character = int(load_int8(byte_offset(buffer, following)))
        if character != 48 and character != 46:
            nonzero = True
        following += 1
    previous = 0 if keep == 0 else int(load_int8(byte_offset(buffer, keep - 1))) - 48
    increment = first > 53 or (first == 53 and (nonzero or (previous & 1) != 0))
    index = keep
    while index < point:
        store_int8(byte_offset(buffer, index), int8(48))
        index += 1
    store_int8(byte_offset(buffer, point), int8(0))
    if increment:
        index = keep - 1
        while index >= 0 and load_int8(byte_offset(buffer, index)) == int8(57):
            store_int8(byte_offset(buffer, index), int8(48))
            index -= 1
        if index < 0:
            store_int8(storage, int8(49))
            buffer = storage
        else:
            digit = load_int8(byte_offset(buffer, index))
            store_int8(byte_offset(buffer, index), int8(int(digit) + 1))
    result = copy_sign(parse_ascii_float(buffer, null()), value)
    # The application boundary distinguishes finite-input overflow from
    # infinity passed through unchanged; preserve the result for that check.
    return result


@_runtime
def divmod_into(left: float, right: float, target: Pointer) -> None:
    if right == 0.0:
        trap()
    rest = ieee_remainder(left, right)
    divided = ieee_divide(left - rest, right)
    if rest != 0.0:
        if (rest < 0.0) != (right < 0.0):
            rest += right
            divided -= 1.0
    else:
        rest = copy_sign(0.0, right)
    if divided != 0.0:
        result = floor(divided)
        if divided - result > 0.5:
            result += 1.0
    else:
        result = copy_sign(0.0, ieee_divide(left, right))
    store_float(target, result)
    store_float(byte_offset(target, 8), rest)
