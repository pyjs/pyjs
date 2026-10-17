"""Shortest round-tripping float formatting over explicit caller buffers."""

from pyjs import int32

from .algorithms import _runtime
from .buffers import STRING_DATA_OFFSET
from .float_math import (
    INFINITY,
    absolute,
    bits,
    fixed_format,
    format_buffer,
    general_format,
    scientific_format,
)
from .numeric_text import parse_ascii_float
from .pointers import (
    Pointer,
    byte_offset,
    copy,
    is_null,
    load_int8,
    load_pointer,
    null,
    stack_buffer,
    trap,
)
from .text_operations import new_owned


@_runtime
def format_float(buffer: Pointer, value: float) -> int:
    # Callers reserve 64 bytes, including the terminator. The shortest
    # round-tripping scientific candidate also gives an exact decimal exponent;
    # log10 can round across notation boundaries near powers of ten.
    if value != value or absolute(value) == INFINITY:
        normalized = absolute(value) if value != value else value
        return int(format_buffer(buffer, 64, general_format(), int32(17), normalized))
    precision = 1
    while True:
        count = int(format_buffer(buffer, 64, scientific_format(), int32(precision - 1), value))
        if count <= 0 or count >= 64:
            trap()
        parsed = parse_ascii_float(buffer, null())
        if bits(parsed) == bits(value):
            break
        precision += 1
        if precision > 17:
            trap()
    index = 0
    while index < count and int(load_int8(byte_offset(buffer, index))) != 101:
        index += 1
    if index == count:
        trap()
    index += 1
    negative = int(load_int8(byte_offset(buffer, index))) == 45
    index += 1  # The C scientific format always includes an exponent sign.
    exponent = 0
    while index < count:
        exponent = exponent * 10 + int(load_int8(byte_offset(buffer, index))) - 48
        index += 1
    if negative:
        exponent = -exponent
    if exponent >= -4 and exponent < 16:
        digits = precision - exponent - 1
        digits = digits if digits > 0 else 1
        count = int(format_buffer(buffer, 64, fixed_format(), int32(digits), value))
    return count


@_runtime
def from_float(arena: Pointer, allocator: Pointer, context: Pointer, value: float) -> Pointer:
    buffer = stack_buffer(64)
    count = format_float(buffer, value)
    result = new_owned(arena, allocator, context, count)
    if is_null(result):
        return null()
    copy(load_pointer(byte_offset(result, STRING_DATA_OFFSET)), buffer, count)
    return result
