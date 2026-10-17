"""String key diagnostics over borrowed UTF-8, without Python objects."""

from pyjs import int8, int32

from .algorithms import (
    _positive_quotient,
    _runtime,
    character_width,
    codepoint_at,
    contains_byte,
)
from .buffers import STRING_DATA_OFFSET
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    copy,
    is_null,
    load_pointer,
    null,
    store_int8,
)
from .text_operations import new_owned
from .unicode import in_ranges


@_runtime
def write_hex(target: Pointer, codepoint: int, digits: int, prefix: int8) -> None:
    store_int8(target, int8(92))
    store_int8(byte_offset(target, 1), prefix)
    index = 0
    while index < digits:
        store_int8(byte_offset(target, digits + 1 - index), int8(48 + (codepoint & 15) if (codepoint & 15) < 10 else 87 + (codepoint & 15)))
        codepoint = _positive_quotient(codepoint, 16)
        index += 1


@_runtime
def _repr_content(value: Pointer, quote: int, printable: Pointer, count: int, target: Pointer) -> int:
    source = borrow_bytes(value)
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    writing = not is_null(target)
    if writing:
        store_int8(target, int8(quote))
    offset = 0
    written = 1
    while offset < len(source):
        codepoint = codepoint_at(source, offset)
        width = character_width(source, offset)
        short = codepoint == quote or codepoint == 92 or codepoint == 9 or codepoint == 10 or codepoint == 13
        plain = not short and in_ranges(int32(codepoint), printable, count)
        digits = 2 if codepoint < 256 else 4 if codepoint < 65536 else 8
        addition = 2 if short else width if plain else digits + 2
        if addition > 9223372036854775806 - written:
            return -1
        if writing:
            output = byte_offset(target, written)
            if short:
                escaped = 116 if codepoint == 9 else 110 if codepoint == 10 else 114 if codepoint == 13 else codepoint
                store_int8(output, int8(92))
                store_int8(byte_offset(output, 1), int8(escaped))
            elif plain:
                copy(output, byte_offset(data, offset), width)
            else:
                prefix = 120 if digits == 2 else 117 if digits == 4 else 85
                write_hex(output, codepoint, digits, int8(prefix))
        written += addition
        offset += width
    if writing:
        store_int8(byte_offset(target, written), int8(quote))
    return written + 1


@_runtime
def repr_string(arena: Pointer, value: Pointer, printable: Pointer, count: int) -> Pointer:
    source = borrow_bytes(value)
    quote = 34 if contains_byte(source, 39) and not contains_byte(source, 34) else 39
    length = _repr_content(value, quote, printable, count, null())
    result = new_owned(arena, null(), null(), length)
    if is_null(result):
        return null()
    if not is_null(result):
        _repr_content(value, quote, printable, count, load_pointer(byte_offset(result, STRING_DATA_OFFSET)))
    return result
