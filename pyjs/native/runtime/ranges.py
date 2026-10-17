"""Checked range and slice arithmetic over private scalar intermediates."""

import ctypes
from functools import cache

from pyjs import int64

from .algorithms import _runtime
from .float_math import finite_integer
from .pointers import Pointer, byte_offset, is_null, store_integer, trap
from .sequences import append_slot
from .wide import (
    WideInt,
    add,
    equal,
    less,
    multiply,
    narrow,
    quotient,
    store,
    subtract,
    widen,
    widen_unsigned,
)


class _ReverseIterator(ctypes.Structure):
    _fields_ = [("current", ctypes.c_int64), ("length", ctypes.c_int64), ("step", ctypes.c_int64)]


LENGTH_OFFSET = _ReverseIterator.length.offset
STEP_OFFSET = _ReverseIterator.step.offset


@cache
def compiled_range_runtime() -> tuple[str, ...]:
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.range.length.i128": length_wide,
        "pyjs.range.length": length,
        "pyjs.range.last": last,
        "pyjs.range.get": get,
        "pyjs.range.equal": equal_ranges,
        "pyjs.range.reverse.init": reverse_initialize,
        "pyjs.range.contains": contains,
        "pyjs.range.contains.float": contains_float,
        "pyjs.range.index": index,
        "pyjs.range.index.i128": index_wide,
        "pyjs.range.slice.into": slice_range,
        "pyjs.slice.length": slice_length,
        "pyjs.slice.indices": slice_indices,
        "pyjs.range.sum.i64": sum_integer,
        "pyjs.range.sum.f64": sum_float,
        "pyjs.list.try.extend.range": extend_list,
    }, dependencies={"pyjs.list.try.append.slot": append_slot})


@_runtime
def length_wide(start: int, stop: int, step: int) -> WideInt:
    if step == 0:
        trap()
    positive = step > 0
    if start >= stop if positive else start <= stop:
        return widen(0)
    first = widen(start)
    limit = widen(stop)
    stride = widen(step)
    distance = subtract(limit, first) if positive else subtract(first, limit)
    magnitude = stride if positive else subtract(widen(0), stride)
    return add(quotient(subtract(distance, widen(1)), magnitude), widen(1))


@_runtime
def length(start: int, stop: int, step: int) -> int:
    result = length_wide(start, stop, step)
    if less(widen(9223372036854775807), result):
        trap()
    return narrow(result)


@_runtime
def last(start: int, stop: int, step: int) -> int:
    count = length_wide(start, stop, step)
    if equal(count, widen(0)):
        trap()
    return narrow(add(widen(start), multiply(subtract(count, widen(1)), widen(step))))


@_runtime
def get(start: int, stop: int, step: int, index: int) -> int:
    count = length_wide(start, stop, step)
    actual = add(count, widen(index)) if index < 0 else widen(index)
    if less(actual, widen(0)) or not less(actual, count):
        trap()
    return narrow(add(widen(start), multiply(actual, widen(step))))


@_runtime
def equal_ranges(start: int, stop: int, step: int, other_start: int, other_stop: int, other_step: int) -> bool:
    count = length_wide(start, stop, step)
    other_count = length_wide(other_start, other_stop, other_step)
    return (equal(count, other_count) and
            (equal(count, widen(0)) or (start == other_start and (equal(count, widen(1)) or step == other_step))))


@_runtime
def reverse_initialize(iterator: Pointer, start: int, stop: int, step: int) -> None:
    count = length_wide(start, stop, step)
    current = 0 if equal(count, widen(0)) else last(start, stop, step)
    store_integer(iterator, current)
    # Remaining length is an unsigned bit count in the existing iterator ABI.
    store_integer(byte_offset(iterator, LENGTH_OFFSET), narrow(count))
    store_integer(byte_offset(iterator, STEP_OFFSET), step)


@_runtime
def contains(start: int, stop: int, step: int, item: int) -> bool:
    if step == 0:
        trap()
    positive = step > 0
    if (item < start or item >= stop) if positive else (item > start or item <= stop):
        return False
    distance = subtract(widen(item), widen(start)) if positive else subtract(widen(start), widen(item))
    magnitude = widen(step) if positive else subtract(widen(0), widen(step))
    return equal(multiply(quotient(distance, magnitude), magnitude), distance)


@_runtime
def contains_float(start: int, stop: int, step: int, item: float) -> bool:
    # Test bounds before fptosi: NaN, infinities and out-of-i64 inputs must
    # simply miss, not produce poison. Never round range endpoints to float.
    if not (-9223372036854775808.0 <= item < 9223372036854775808.0):
        return False
    converted = finite_integer(item)
    return float(converted) == item and contains(start, stop, step, converted)


@_runtime
def index_wide(start: int, stop: int, step: int, item: int) -> WideInt:
    if not contains(start, stop, step, item):
        trap()
    distance = subtract(widen(item), widen(start)) if step > 0 else subtract(widen(start), widen(item))
    magnitude = widen(step) if step > 0 else subtract(widen(0), widen(step))
    return quotient(distance, magnitude)


@_runtime
def index(start: int, stop: int, step: int, item: int) -> int:
    result = index_wide(start, stop, step, item)
    if less(widen(9223372036854775807), result):
        trap()
    return narrow(result)


@_runtime
def slice_stride(step: int, present: bool) -> int:
    stride = step if present else 1
    if stride == 0:
        trap()
    return stride


@_runtime
def slice_bound(length: WideInt, bound: int, present: bool, reverse: bool, stop: bool) -> WideInt:
    minimum = widen(-1 if reverse else 0)
    maximum = subtract(length, widen(1)) if reverse else length
    if not present:
        return (minimum if reverse else maximum) if stop else (maximum if reverse else minimum)
    actual = add(widen(bound), length) if bound < 0 else widen(bound)
    if less(actual, minimum):
        return minimum
    return maximum if less(maximum, actual) else actual


@_runtime
def slice_indices(length: WideInt, start: int, start_present: bool, stop: int, stop_present: bool,
                  step: int, step_present: bool, result: Pointer) -> None:
    stride = slice_stride(step, step_present)
    store(result, slice_bound(length, start, start_present, stride < 0, False))
    store(byte_offset(result, 16), slice_bound(length, stop, stop_present, stride < 0, True))
    store(byte_offset(result, 32), widen(stride))


@_runtime
def slice_length(length: int, start: int, start_present: bool, stop: int, stop_present: bool,
                 step: int, step_present: bool) -> int:
    stride = slice_stride(step, step_present)
    first = slice_bound(widen_unsigned(length), start, start_present, stride < 0, False)
    limit = slice_bound(widen_unsigned(length), stop, stop_present, stride < 0, True)
    distance = subtract(limit, first) if stride > 0 else subtract(first, limit)
    if not less(widen(0), distance):
        return 0
    width = widen(stride) if stride > 0 else subtract(widen(0), widen(stride))
    return narrow(add(quotient(subtract(distance, widen(1)), width), widen(1)))


@_runtime
def _checked_narrow(value: WideInt) -> int:
    if less(value, widen(-9223372036854775808)) or less(widen(9223372036854775807), value):
        trap()
    return narrow(value)


@_runtime
def slice_range(start: int, stop: int, step: int, first: int, first_present: bool,
                limit: int, limit_present: bool, stride: int, stride_present: bool, result: Pointer) -> bool:
    count = length_wide(start, stop, step)
    stride = slice_stride(stride, stride_present)
    begin = slice_bound(count, first, first_present, stride < 0, False)
    end = slice_bound(count, limit, limit_present, stride < 0, True)
    new_start = add(widen(start), multiply(begin, widen(step)))
    new_stop = add(widen(start), multiply(end, widen(step)))
    new_step = multiply(widen(step), widen(stride))
    if (less(new_start, widen(-9223372036854775808)) or less(widen(9223372036854775807), new_start)
            or less(new_stop, widen(-9223372036854775808)) or less(widen(9223372036854775807), new_stop)
            or less(new_step, widen(-9223372036854775808)) or less(widen(9223372036854775807), new_step)):
        return False
    store_integer(result, narrow(new_start))
    store_integer(byte_offset(result, 8), narrow(new_stop))
    store_integer(byte_offset(result, 16), narrow(new_step))
    return True


@_runtime
def _following(current: int, stop: int, step: int) -> int:
    if step > 0:
        if current > 9223372036854775807 - step:
            return stop
    elif current < -9223372036854775808 - step:
        return stop
    return current + step


@_runtime
def extend_list(arena: Pointer, target: Pointer, start: int, stop: int, step: int) -> bool:
    if step == 0:
        trap()
    current = start
    while current < stop if step > 0 else current > stop:
        slot = append_slot(arena, target, 8)
        if is_null(slot):
            return False
        store_integer(slot, current)
        current = _following(current, stop, step)
    return True


@_runtime
def sum_integer(start: int, stop: int, step: int, initial: int) -> int:
    if step == 0:
        trap()
    current = start
    total = initial
    while current < stop if step > 0 else current > stop:
        total = int(int64(total + current))
        current = _following(current, stop, step)
    return total


@_runtime
def sum_float(start: int, stop: int, step: int, initial: float) -> float:
    if step == 0:
        trap()
    current = start
    total = initial
    while current < stop if step > 0 else current > stop:
        total += float(current)
        current = _following(current, stop, step)
    return total
