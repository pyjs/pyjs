"""Scalar math with explicit wide intermediates and checked result bounds."""

from functools import cache

from .algorithms import _positive_quotient, _runtime
from .float_math import bits
from .integer_math import _float_bits, magnitude
from .wide import (
    WideInt,
    add,
    equal,
    less,
    multiply,
    narrow,
    quotient,
    remainder,
    subtract,
    widen,
)


@_runtime
def gcd(left: int, right: int) -> int:
    current = magnitude(left)
    following = magnitude(right)
    while not equal(following, widen(0)):
        rest = remainder(current, following)
        current = following
        following = rest
    return narrow(current)


@_runtime
def lcm(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    # gcd can represent 2**63 as a negative bit pattern, so widen its magnitude.
    divisor = magnitude(gcd(left, right))
    result = multiply(quotient(magnitude(left), divisor), magnitude(right))
    return -1 if less(widen(9223372036854775807), result) else narrow(result)


@_runtime
def combination(n: int, k: int, permutation: bool) -> int:
    if k > n:
        return 0
    if not permutation and k > n - k:
        k = n - k
    result: WideInt = widen(1)
    index = 0
    while index < k:
        result = multiply(result, widen(n - index))
        if not permutation:
            result = quotient(result, widen(index + 1))
        if less(widen(9223372036854775807), result):
            return -1
        index += 1
    return narrow(result)


@_runtime
def isqrt(value: int) -> int:
    if value < 2:
        return value
    candidate = value
    following = _positive_quotient(value, 2) + (value & 1)
    while following < candidate:
        candidate = following
        following = _positive_quotient(candidate + _positive_quotient(value, candidate), 2)
    return candidate


@_runtime
def nextafter(x: float, y: float, steps: int) -> float:
    if steps == 0:
        return x
    if x != x or y != y:
        return x + y
    if x == y:
        return y
    a = bits(x)
    b = bits(y)
    start = -(a & 9223372036854775807) if a < 0 else a
    stop = -(b & 9223372036854775807) if b < 0 else b
    distance = subtract(widen(stop), widen(start)) if stop > start else subtract(widen(start), widen(stop))
    if not less(widen(steps), distance):
        return y
    rank = narrow(add(widen(start), widen(steps)) if stop > start else subtract(widen(start), widen(steps)))
    # Both zero encodings share a rank. Crossing zero keeps the incoming sign.
    encoded = (-rank) | -9223372036854775808 if rank < 0 or rank == 0 and a < 0 else rank
    return _float_bits(encoded)


@cache
def compiled_runtime():
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.math.gcd": gcd, "pyjs.math.lcm": lcm,
        "pyjs.math.combination": combination, "pyjs.math.isqrt": isqrt,
        "pyjs.math.nextafter": nextafter,
    })
