"""Nonoverlapping floating partials for streaming math.fsum inputs.

The partials buffer is call-local and contains no GC references. The caller
supplies two doubles for the special-value and infinity totals. Status codes
are zero for success, -1 for allocation failure, -2 for intermediate overflow,
and -3 for conflicting infinities; the emitter raises in the Python frame.
"""

from functools import cache

from .algorithms import _runtime
from .float_math import INFINITY, absolute
from .pointers import (
    Pointer,
    byte_offset,
    is_null,
    load_float,
    load_integer,
    store_float,
)
from .sequences import append_slot, get, truncate


@_runtime
def add(arena: Pointer, partials: Pointer, state: Pointer, value: float) -> int:
    original = value
    length = load_integer(partials)
    read = 0
    kept = 0
    while read < length:
        partial = load_float(get(partials, read, 8))
        if absolute(value) < absolute(partial):
            temporary = value
            value = partial
            partial = temporary
        high = value + partial
        low = partial - (high - value)
        if low != 0.0:
            store_float(get(partials, kept, 8), low)
            kept += 1
        value = high
        read += 1
    truncate(partials, kept, 8)
    if not absolute(value) < INFINITY:
        if absolute(original) < INFINITY:
            return -2
        if absolute(original) == INFINITY:
            infinity = byte_offset(state, 8)
            store_float(infinity, load_float(infinity) + original)
        store_float(state, load_float(state) + original)
        truncate(partials, 0, 8)
    elif value != 0.0:
        slot = append_slot(arena, partials, 8)
        if is_null(slot):
            return -1
        store_float(slot, value)
    return 0


@_runtime
def finish(partials: Pointer, state: Pointer, output: Pointer) -> int:
    special = load_float(state)
    if special != 0.0:
        infinity = load_float(byte_offset(state, 8))
        if infinity != infinity:
            return -3
        store_float(output, special)
        return 0
    length = load_integer(partials)
    high = 0.0
    low = 0.0
    if length:
        length -= 1
        high = load_float(get(partials, length, 8))
    while length:
        length -= 1
        partial = load_float(get(partials, length, 8))
        combined = high + partial
        low = partial - (combined - high)
        high = combined
        if low != 0.0:
            break
    # Remaining same-sign partials disambiguate an exact halfway rounding.
    if length:
        remaining = load_float(get(partials, length - 1, 8))
        if low < 0.0 and remaining < 0.0 or low > 0.0 and remaining > 0.0:
            doubled = low * 2.0
            adjusted = high + doubled
            if adjusted - high == doubled:
                high = adjusted
    store_float(output, high)
    return 0


@cache
def compiled_runtime():
    from .compiler import compile_runtime

    return compile_runtime(
        {"pyjs.fsum.add": add, "pyjs.fsum.finish": finish},
        dependencies={"pyjs.list.get": get, "pyjs.list.truncate": truncate,
                      "pyjs.list.try.append.slot": append_slot},
    )
