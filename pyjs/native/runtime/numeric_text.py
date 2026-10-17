"""Numeric text parsing with explicit Unicode tables and native buffers."""

import ctypes

from pyjs import int8, int32
from pyjs.decorators import native_operation

from .algorithms import (
    _byte_at,
    _positive_quotient,
    _runtime,
    character_width,
    codepoint_at,
)
from .arena import allocate_in_arena
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    is_null,
    load_int8,
    load_int32,
    load_pointer,
    same_address,
    stack_buffer,
    store_float,
    store_int8,
    store_integer,
)
from .text_buffers import scan_characters
from .wide import WideInt, add, less, multiply, narrow, subtract, widen


@native_operation("system.strtod")
def parse_ascii_float(value: Pointer, end: Pointer) -> float:
    function = ctypes.CDLL(None).strtod
    function.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    function.restype = ctypes.c_double
    return function(value.address, end.address)


@_runtime
def decimal_value(codepoint: int32, ranges: Pointer, count: int) -> int32:
    index = 0
    while index < count:
        start = load_int32(byte_offset(ranges, index * 8))
        stop = load_int32(byte_offset(ranges, index * 8 + 4))
        if codepoint >= start and codepoint <= stop:
            offset = int(codepoint) - int(start)
            return int32(offset - _positive_quotient(offset, 10) * 10)
        index += 1
    return int32(-1)


@_runtime
def parse_integer(text: Pointer, base: int, whitespace: Pointer, decimals: Pointer, count: int, target: Pointer) -> int8:
    # Status: zero malformed, one success, three outside signed i64; two is
    # reserved for float parsing allocation failure. Keep checking syntax
    # after overflow so a malformed suffix still reports an invalid literal.
    if base != 0 and (base < 2 or base > 36):
        return int8(0)
    source = borrow_bytes(text)
    index = scan_characters(text, whitespace, 0, len(source), False, False, True)
    if index == len(source):
        return int8(0)
    first = _byte_at(source, index)
    negative = first == 45
    if negative or first == 43:
        index += 1
    if index == len(source):
        return int8(0)
    zero = decimal_value(int32(codepoint_at(source, index)), decimals, count) == int32(0)
    prefix_base = 0
    after_prefix = index
    if zero:
        second = index + character_width(source, index)
        if second < len(source):
            marker = _byte_at(source, second) | 32
            prefix_base = 2 if marker == 98 else 8 if marker == 111 else 16 if marker == 120 else 0
            after_prefix = second + 1
    prefix = prefix_base != 0 and (base == 0 or base == prefix_base)
    zero_only = base == 0 and zero and not prefix
    if prefix:
        base = prefix_base
        index = after_prefix
    elif base == 0:
        base = 10
    allow_underscore = prefix
    saw_digit = False
    last_digit = False
    value: WideInt = widen(0)
    overflow = False
    maximum = subtract(widen(0), widen(-9223372036854775808)) if negative else widen(9223372036854775807)
    while index < len(source):
        codepoint = codepoint_at(source, index)
        width = character_width(source, index)
        digit = int(decimal_value(int32(codepoint), decimals, count))
        lower = codepoint | 32
        if digit < 0 and lower >= 97 and lower <= 122:
            digit = lower - 87
        if digit >= 0 and digit < base and (not zero_only or digit == 0):
            if not overflow:
                value = add(multiply(value, widen(base)), widen(digit))
                overflow = less(maximum, value)
            saw_digit = True
            last_digit = True
            allow_underscore = False
        elif codepoint == 95:
            if not last_digit and not allow_underscore:
                return int8(0)
            last_digit = False
            allow_underscore = False
        else:
            if not saw_digit or not last_digit:
                return int8(0)
            if scan_characters(text, whitespace, index, len(source), False, False, True) != len(source):
                return int8(0)
            break
        index += width
    if not saw_digit or not last_digit:
        return int8(0)
    if overflow:
        return int8(3)
    store_integer(target, narrow(subtract(widen(0), value) if negative else value))
    return int8(1)


@_runtime
def parse_float(arena: Pointer, text: Pointer, whitespace: Pointer, decimals: Pointer, count: int,
                target: Pointer) -> int8:
    # Status: zero invalid, one success, two allocation failure. The caller
    # must distinguish malformed input from inability to build the C buffer.
    source = borrow_bytes(text)
    if len(source) == 9223372036854775807:
        return int8(2)
    buffer = allocate_in_arena(arena, len(source) + 1, 1)
    if is_null(buffer):
        return int8(2)
    offset = 0
    written = 0
    previous_digit = False
    needs_digit = False
    while offset < len(source):
        codepoint = codepoint_at(source, offset)
        width = character_width(source, offset)
        digit = int(decimal_value(int32(codepoint), decimals, count))
        is_digit = digit >= 0
        if codepoint == 95:
            if not previous_digit:
                return int8(0)
            previous_digit = False
            needs_digit = True
            offset += width
            continue
        if is_digit:
            byte = digit + 48
        else:
            if needs_digit:
                return int8(0)
            if scan_characters(text, whitespace, offset, offset + width, False, False, True) != offset:
                byte = 32
            else:
                # strtod accepts C hex floats and nan(payload), unlike Python.
                if (codepoint >= 128 or codepoint == 0 or codepoint == 40 or codepoint == 41 or
                        codepoint == 120 or codepoint == 88 or codepoint == 112 or codepoint == 80):
                    return int8(0)
                byte = codepoint
        store_int8(byte_offset(buffer, written), int8(byte))
        written += 1
        previous_digit = is_digit
        needs_digit = False
        offset += width
    if needs_digit:
        return int8(0)
    store_int8(byte_offset(buffer, written), int8(0))
    end = stack_buffer(8)
    value = parse_ascii_float(buffer, end)
    tail = load_pointer(end)
    if same_address(tail, buffer):
        return int8(0)
    while load_int8(tail) == int8(32):
        tail = byte_offset(tail, 1)
    if load_int8(tail) != int8(0):
        return int8(0)
    store_float(target, value)
    return int8(1)
