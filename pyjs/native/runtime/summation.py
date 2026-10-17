"""Compensated binary64 summation for ordinary Python float iterables."""

from functools import cache

from .algorithms import _runtime
from .pointers import Pointer, byte_offset, load_float, store_float

INFINITY = float("inf")


@_runtime
def add(state: Pointer, value: float) -> None:
    high = load_float(state)
    low = load_float(byte_offset(state, 8))
    total = high + value
    magnitude = -high if high < 0.0 else high
    other = -value if value < 0.0 else value
    correction = (high - total) + value if magnitude >= other else (value - total) + high
    store_float(state, total)
    store_float(byte_offset(state, 8), low + correction)


@_runtime
def finish(state: Pointer) -> float:
    high = load_float(state)
    low = load_float(byte_offset(state, 8))
    # Nonfinite additions must retain ordinary IEEE results; correction would
    # otherwise turn a single infinity into NaN. Avoid losing a signed zero.
    if low != 0.0 and low < INFINITY and low > -INFINITY:
        return high + low
    return high


@cache
def compiled_runtime() -> tuple[str, ...]:
    from .compiler import compile_runtime

    return compile_runtime({"pyjs.sum.add": add, "pyjs.sum.finish": finish})
