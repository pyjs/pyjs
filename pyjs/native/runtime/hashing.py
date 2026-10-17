"""Python numeric hash invariants over bounded native scalars."""

from pyjs import int64, llvm

from .algorithms import _positive_quotient, _runtime
from .integer_math import _shift_left, _truncated_quotient
from .pointers import Pointer, byte_offset, load_integer
from .ranges import length_wide
from .wide import equal, less, narrow, remainder, widen

MODULUS = 2305843009213693951
NONE_HASH = 425899384


@llvm.inline("bitcast double {value} to i64")
def _bits(value: float) -> int:
    import struct
    return struct.unpack("q", struct.pack("d", value))[0]


@llvm.inline("lshr i64 {value}, {count}")
def _shift_right(value: int, count: int) -> int:
    return (value & ((1 << 64) - 1)) >> count


@_runtime
def integer(value: int) -> int:
    result = value - _truncated_quotient(value, MODULUS) * MODULUS
    return -2 if result == -1 else result


@_runtime
def floating(value: float) -> int:
    bits = _bits(value)
    exponent = _shift_right(bits, 52) & 2047
    mantissa = bits & 4503599627370495
    if exponent == 2047:
        # NaN has no numeric equality invariant; native unboxed NaNs use one
        # stable hash, not CPython's per-object identity hash.
        if mantissa:
            return 0
        return -314159 if bits < 0 else 314159
    if exponent:
        mantissa |= 4503599627370496
    else:
        exponent = 1
    # Modulo 2**61-1, multiplying by a power of two rotates 61 bits. The
    # explicit wrapped left shift keeps the same low bits in Python and LLVM.
    # Adding 18 full rotations keeps the dividend nonnegative even for a
    # subnormal; the proven nonzero divisor needs no checked exception ABI.
    shift = exponent + 23
    shift -= _positive_quotient(shift, 61) * 61
    result = (_shift_left(mantissa, shift) & MODULUS) | _shift_right(mantissa, 61 - shift)
    if bits < 0:
        result = -result
    return -2 if result == -1 else result


@_runtime
def ordered(previous: int, item: int) -> int:
    return int(int64((previous ^ item) * int64(1099511628211)))


@_runtime
def unordered(previous: int, item: int) -> int:
    return int(int64(previous) + int64(item ^ _shift_left(item, 16)))


@_runtime
def triple(first: int, second: int, third: int) -> int:
    result = ordered(ordered(ordered(1469598103934665603, first), second), third) ^ 3
    return -2 if result == -1 else result


@_runtime
def range_value(start: int, stop: int, step: int) -> int:
    # Equal ranges ignore start/step when empty and step when singleton.
    # The count can exceed signed i64 even though all elements fit; reduce it
    # before narrowing rather than calling len() or wrapping its signed value.
    length = length_wide(start, stop, step)
    count_hash = narrow(remainder(length, widen(MODULUS)))
    start_hash = NONE_HASH if equal(length, widen(0)) else integer(start)
    step_hash = NONE_HASH if less(length, widen(2)) else integer(step)
    return triple(count_hash, start_hash, step_hash)


@_runtime
def cached_unordered(hashes: Pointer, length: int) -> int:
    result = 1927868237
    index = 0
    while index < length:
        result = unordered(result, load_integer(byte_offset(hashes, index * 8)))
        index += 1
    result ^= length
    return -2 if result == -1 else result
