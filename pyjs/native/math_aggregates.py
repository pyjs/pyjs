"""Python-authored numeric aggregation, using scalar LLVM leaves only.

Triple-length accumulation is adapted from CPython 3.14 Modules/mathmodule.c
(tl_fma, tl_to_d and sumprod). See PYTHON-LICENSE.txt for the PSF license and
copyright notice. Preserve operation order: reassociation loses compensation.
"""

from collections.abc import Iterable

from .runtime import wide
from .runtime.float_math import INFINITY
from .runtime.math_calls import fma
from .runtime.wide import WideInt


def checked_integer(value: WideInt, operation: str) -> int:
    if (wide.less(value, wide.widen(-9223372036854775808))
            or wide.less(wide.widen(9223372036854775807), value)):
        raise OverflowError(operation + " result exceeds native int range")
    return wide.narrow(value)


def _add(a: int | float, b: int | float) -> int | float:
    if isinstance(a, int):
        if isinstance(b, int):
            return checked_integer(wide.add(wide.widen(int(a)), wide.widen(int(b))), "math.sumprod")
        return int(a) + b
    if isinstance(b, int):
        return a + int(b)
    return a + b


def _multiply(a: int | float, b: int | float) -> int | float:
    if isinstance(a, int):
        if isinstance(b, int):
            return checked_integer(wide.multiply(wide.widen(int(a)), wide.widen(int(b))), "math.sumprod")
        return int(a) * b
    if isinstance(b, int):
        return a * int(b)
    return a * b


def _sum_error(a: float, b: float, total: float) -> float:
    z = total - a
    return (a - (total - z)) + (b - z)


def _finish(hi: float, lo: float, tiny: float) -> float:
    last = lo + hi
    return tiny + _sum_error(lo, hi, last) + last


def sumprod(left: Iterable[int | float], right: Iterable[int | float]) -> int | float:
    p = iter(left)
    q = iter(right)
    total: int | float = 0
    integer_prefix = True
    compensated = True
    used = False
    hi = 0.0
    lo = 0.0
    tiny = 0.0
    while True:
        a: int | float = 0
        b: int | float = 0
        p_stopped = False
        q_stopped = False
        # Advance both sides even when the left stops. A right-side exception
        # takes precedence over length mismatch; do not catch it as exhaustion.
        try:
            a = next(p)
        except StopIteration:
            p_stopped = True
        try:
            b = next(q)
        except StopIteration:
            q_stopped = True
        if p_stopped or q_stopped:
            if p_stopped != q_stopped:
                raise ValueError("Inputs are not the same length")
            if used:
                return _add(total, _finish(hi, lo, tiny))
            return total
        if (integer_prefix and isinstance(a, int) and not isinstance(a, bool)
                and isinstance(b, int) and not isinstance(b, bool)):
            total = _add(total, _multiply(a, b))
            continue
        integer_prefix = False
        if compensated:
            if isinstance(a, float) or isinstance(b, float):
                x = float(a)
                y = float(b)
                product = x * y
                combined = hi + product
                if abs(combined) < INFINITY:
                    residual = fma(x, y, -product)
                    first = lo + residual
                    first_low = _sum_error(lo, residual, first)
                    sum_low = _sum_error(hi, product, combined)
                    second = first + sum_low
                    second_low = _sum_error(first, sum_low, second)
                    tiny = tiny + first_low + second_low
                    hi = combined
                    lo = second
                    used = True
                    continue
            # Like CPython, a non-floating pair or nonfinite partial permanently
            # ends the compensated run. Flush once, then use ordinary arithmetic.
            compensated = False
            if used:
                total = _add(total, _finish(hi, lo, tiny))
                used = False
        total = _add(total, _multiply(a, b))
