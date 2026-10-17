"""Stream HTML, JSON and Python repr escaping without intermediate strings."""

from pyjs import int8, int32

from .algorithms import (
    _byte_at,
    _positive_quotient,
    _runtime,
    _utf8_bytes,
    character_width,
    codepoint_at,
    contains_byte,
)
from .buffers import ERROR_OFFSET, STRING_DATA_OFFSET, append_bytes
from .error_messages import write_hex
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    bytes_data,
    load_int32,
    load_pointer,
    stack_buffer,
    store_int8,
)
from .unicode import in_ranges


@_runtime
def write_repr(output: Pointer, value: Pointer, printable: Pointer, count: int) -> None:
    """Quote UTF-8 like Python repr without a temporary escaped allocation."""
    if load_int32(byte_offset(output, ERROR_OFFSET)) != int32(0):
        return
    source = borrow_bytes(value)
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    quote = 34 if contains_byte(source, 39) and not contains_byte(source, 34) else 39
    scratch = stack_buffer(10)
    store_int8(scratch, int8(quote))
    append_bytes(output, scratch, 1)
    index = 0
    start = 0
    while index < len(source):
        codepoint = codepoint_at(source, index)
        width = character_width(source, index)
        short = codepoint == quote or codepoint == 92 or codepoint == 9 or codepoint == 10 or codepoint == 13
        if short or not in_ranges(int32(codepoint), printable, count):
            append_bytes(output, byte_offset(data, start), index - start)
            if short:
                escaped = 116 if codepoint == 9 else 110 if codepoint == 10 else 114 if codepoint == 13 else codepoint
                store_int8(scratch, int8(92))
                store_int8(byte_offset(scratch, 1), int8(escaped))
                length = 2
            else:
                digits = 2 if codepoint < 256 else 4 if codepoint < 65536 else 8
                write_hex(scratch, codepoint, digits, int8(120 if digits == 2 else 117 if digits == 4 else 85))
                length = digits + 2
            append_bytes(output, scratch, length)
            start = index + width
        index += width
    append_bytes(output, byte_offset(data, start), index - start)
    store_int8(scratch, int8(quote))
    append_bytes(output, scratch, 1)


@_runtime
def write_html(output: Pointer, value: Pointer, attribute: bool) -> int32:
    error = load_int32(byte_offset(output, ERROR_OFFSET))
    if error != int32(0):
        return error
    source = borrow_bytes(value)
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    index = 0
    start = 0
    while index < len(source):
        byte = _byte_at(source, index)
        entity = _utf8_bytes("")
        if byte == 38:
            entity = _utf8_bytes("&amp;")
        elif byte == 60:
            entity = _utf8_bytes("&lt;")
        elif byte == 62:
            entity = _utf8_bytes("&gt;")
        elif attribute and byte == 34:
            entity = _utf8_bytes("&quot;")
        elif attribute and byte == 39:
            entity = _utf8_bytes("&#x27;")
        if len(entity) > 0:
            error = append_bytes(output, byte_offset(data, start), index - start)
            if error != int32(0):
                return error
            error = append_bytes(output, bytes_data(entity), len(entity))
            if error != int32(0):
                return error
            start = index + 1
        index += 1
    return append_bytes(output, byte_offset(data, start), index - start)


@_runtime
def write_json(output: Pointer, value: Pointer, ensure_ascii: bool) -> None:
    # Only escapes use scratch; unchanged UTF-8 spans are copied directly.
    # append_bytes keeps failures sticky, including partially written pipes.
    if load_int32(byte_offset(output, ERROR_OFFSET)) != int32(0):
        return
    scratch = stack_buffer(12)
    source = borrow_bytes(value)
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    store_int8(scratch, int8(34))
    append_bytes(output, scratch, 1)
    index = 0
    start = 0
    while index < len(source):
        codepoint = codepoint_at(source, index)
        width = character_width(source, index)
        short = codepoint == 34 or codepoint == 92
        if short or codepoint < 32 or (ensure_ascii and codepoint >= 127):
            append_bytes(output, byte_offset(data, start), index - start)
            named = 0
            if codepoint == 8:
                named = 98
            elif codepoint == 9:
                named = 116
            elif codepoint == 10:
                named = 110
            elif codepoint == 12:
                named = 102
            elif codepoint == 13:
                named = 114
            length = 2
            if short or named != 0:
                store_int8(scratch, int8(92))
                store_int8(byte_offset(scratch, 1), int8(codepoint if short else named))
            elif codepoint <= 65535:
                write_hex(scratch, codepoint, 4, int8(117))
                length = 6
            else:
                above_plane = codepoint - 65536
                write_hex(scratch, _positive_quotient(above_plane, 1024) + 55296, 4, int8(117))
                write_hex(byte_offset(scratch, 6), (above_plane & 1023) + 56320, 4, int8(117))
                length = 12
            append_bytes(output, scratch, length)
            start = index + width
        index += width
    append_bytes(output, byte_offset(data, start), index - start)
    store_int8(scratch, int8(34))
    append_bytes(output, scratch, 1)
