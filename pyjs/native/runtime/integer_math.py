"""Scalar integer algorithms with explicit fixed-width intermediate rules."""

from pyjs import int64, llvm

from .algorithms import _positive_quotient, _runtime
from .pointers import Pointer, byte_offset, store_integer, trap
from .wide import (
    WideInt,
    add,
    equal,
    less,
    multiply,
    narrow,
    quotient,
    remainder,
    shift_left,
    subtract,
    widen,
)


@llvm.inline("sdiv i64 {left}, {right}")
def _truncated_quotient(left: int, right: int) -> int:
    magnitude = abs(left) // abs(right)
    return -magnitude if (left < 0) != (right < 0) else magnitude


@llvm.inline("call i64 @llvm.ctlz.i64(i64 {value}, i1 false)")
def _leading_zeros(value: int) -> int:
    return 64 - (value & ((1 << 64) - 1)).bit_length()


@llvm.inline("call i64 @llvm.ctpop.i64(i64 {value})")
def _population_count(value: int) -> int:
    return (value & ((1 << 64) - 1)).bit_count()


@_runtime
def bit_count(value: int) -> int:
    # The minimum signed value has an unsigned magnitude of 2**63. Keep its
    # bit pattern rather than requiring an overflowing positive signed value.
    bits = int(int64(-value)) if value < 0 else value
    return _population_count(bits)


@_runtime
def bit_length(value: int) -> int:
    bits = int(int64(-value)) if value < 0 else value
    return 64 - _leading_zeros(bits)


@llvm.inline("bitcast i64 {value} to double")
def _float_bits(value: int) -> float:
    import struct
    return struct.unpack("d", struct.pack("Q", value & ((1 << 64) - 1)))[0]


@llvm.inline("shl i64 {value}, {count}")
def _shift_left(value: int, count: int) -> int:
    return int(int64(value << count))


@_runtime
def magnitude(value: int) -> WideInt:
    return subtract(widen(0), widen(value)) if value < 0 else widen(value)


@_runtime
def divmod_into(left: int, right: int, wrapped: bool, target: Pointer) -> None:
    if right == 0:
        trap()
    if left == -9223372036854775808 and right == -1:
        if not wrapped:
            trap()
        result = left
        rest = 0
    else:
        result = _truncated_quotient(left, right)
        rest = left - result * right
        if rest != 0 and (rest < 0) != (right < 0):
            result -= 1
            rest += right
    store_integer(target, result)
    store_integer(byte_offset(target, 8), rest)


@_runtime
def reject_negative_shift(value: int, negative: bool) -> int:
    if negative:
        trap()
    return value


@_runtime
def power(base: int, exponent: int) -> int:
    if exponent < 0:
        trap()
    result = 1
    while exponent > 0:
        if exponent & 1:
            result = int(int64(result * base))
        base = int(int64(base * base))
        exponent = _positive_quotient(exponent, 2)
    return result


@_runtime
def _rounded_quotient(numerator: WideInt, denominator: WideInt) -> WideInt:
    result = quotient(numerator, denominator)
    twice_rest = multiply(remainder(numerator, denominator), widen(2))
    if less(denominator, twice_rest) or (equal(denominator, twice_rest) and (narrow(result) & 1) != 0):
        result = add(result, widen(1))
    return result


@_runtime
def round_wide(value: int, digits: int) -> WideInt:
    if digits >= 0:
        return widen(value)
    if digits < -19:
        return widen(0)
    absolute = magnitude(value)
    factor = widen(1)
    index = 0
    while index < -digits:
        factor = multiply(factor, widen(10))
        index += 1
    rounded = multiply(_rounded_quotient(absolute, factor), factor)
    return subtract(widen(0), rounded) if value < 0 else rounded


@_runtime
def round_digits(value: int, digits: int, wrapped: bool) -> int:
    rounded = round_wide(value, digits)
    if not wrapped and (less(rounded, widen(-9223372036854775808)) or less(widen(9223372036854775807), rounded)):
        trap()
    return narrow(rounded)


@_runtime
def true_divide(left: int, right: int) -> float:
    return wide_true_divide(widen(left), widen(right))


@_runtime
def _wide_bit_length(value: WideInt) -> int:
    upper = narrow(quotient(value, shift_left(widen(1), widen(64))))
    return 128 - _leading_zeros(upper) if upper else 64 - _leading_zeros(narrow(value))


@_runtime
def wide_true_divide(left: WideInt, right: WideInt) -> float:
    # Inputs are signed magnitudes of at most 67 bits (ordinary integers or
    # duration microseconds). Scaling for binary64 then fits the i128 workspace.
    zero = widen(0)
    if equal(right, zero):
        trap()
    if equal(left, zero):
        return -0.0 if less(right, zero) else 0.0
    numerator = subtract(zero, left) if less(left, zero) else left
    denominator = subtract(zero, right) if less(right, zero) else right
    exponent = _wide_bit_length(numerator) - _wide_bit_length(denominator)
    below = (less(numerator, shift_left(denominator, widen(exponent))) if exponent >= 0 else
             less(shift_left(numerator, widen(-exponent)), denominator))
    if below:
        exponent -= 1
    scale = 52 - exponent
    if scale >= 0:
        numerator = shift_left(numerator, widen(scale))
    else:
        denominator = shift_left(denominator, widen(-scale))
    # Round once, before conversion to binary64. Converting the original
    # operands separately loses integer precision above 2**53.
    significand = _rounded_quotient(numerator, denominator)
    if equal(significand, widen(9007199254740992)):
        significand = quotient(significand, widen(2))
        exponent += 1
    result = float(narrow(significand)) * _float_bits(_shift_left(exponent + 971, 52))
    return -result if less(left, zero) != less(right, zero) else result


@_runtime
def _positive_modulo(value: WideInt, modulus: WideInt) -> WideInt:
    negative = less(value, widen(0))
    rest = remainder(subtract(widen(0), value) if negative else value, modulus)
    return subtract(modulus, rest) if negative and not equal(rest, widen(0)) else rest


@_runtime
def modular_power(base: int, exponent: int, modulus: int, target: Pointer) -> bool:
    if modulus == 0:
        trap()
    size = magnitude(modulus)
    factor = _positive_modulo(widen(base), size)
    remaining = magnitude(exponent)
    if exponent < 0 and not equal(size, widen(1)):
        old_r = size
        r = factor
        old_t = widen(0)
        t = widen(1)
        while not equal(r, widen(0)):
            divided = quotient(old_r, r)
            next_r = subtract(old_r, multiply(divided, r))
            next_t = subtract(old_t, multiply(divided, t))
            old_r = r
            r = next_r
            old_t = t
            t = next_t
        if not equal(old_r, widen(1)):
            return False
        factor = _positive_modulo(old_t, size)
    result = remainder(widen(1), size)
    while not equal(remaining, widen(0)):
        if narrow(remaining) & 1:
            result = remainder(multiply(result, factor), size)
        factor = remainder(multiply(factor, factor), size)
        remaining = quotient(remaining, widen(2))
    if modulus < 0 and not equal(result, widen(0)):
        result = subtract(result, size)
    store_integer(target, narrow(result))
    return True
