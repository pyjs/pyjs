"""Two-pass form-query encoding over stable borrowed string mappings.

Measure before allocating, then fill one exact-sized payload. Neither pass
calls application code or collects; keys and values cannot change between them.
"""

from functools import cache

from pyjs import int8

from .algorithms import _byte_at, _positive_quotient, _runtime, _utf8_bytes
from .buffers import STRING_DATA_OFFSET
from .mappings import KEYS, VALUES
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    is_null,
    load_integer,
    load_pointer,
    null,
    pointer_slot,
    store_int8,
)
from .text_operations import new_owned


@_runtime
def safe_byte(value: int) -> bool:
    return (48 <= value <= 57 or 65 <= value <= 90 or 97 <= value <= 122
            or value == 45 or value == 46 or value == 95 or value == 126)


@_runtime
def component_size(value: Pointer, available: int) -> int:
    length = load_integer(value)
    # Reject synthetic oversized headers before examining the payload.
    if length < 0 or length > available:
        return -1
    source = borrow_bytes(value)
    index = 0
    size = 0
    while index < length:
        byte = _byte_at(source, index)
        width = 1 if safe_byte(byte) or byte == 32 else 3
        if width > available - size:
            return -1
        size += width
        index += 1
    return size


@_runtime
def query_size(count: int, keys: Pointer, values: Pointer) -> int:
    if count < 0 or count > 4611686018427387904:
        return -1
    size = count + (count - 1) if count else 0
    index = 0
    while index < count:
        key = component_size(load_pointer(pointer_slot(keys, index)), 9223372036854775807 - size)
        if key < 0:
            return -1
        size += key
        value = component_size(load_pointer(pointer_slot(values, index)), 9223372036854775807 - size)
        if value < 0:
            return -1
        size += value
        index += 1
    return size


@_runtime
def copy_component(target: Pointer, offset: int, value: Pointer) -> int:
    source = borrow_bytes(value)
    digits = _utf8_bytes("0123456789ABCDEF")
    index = 0
    while index < len(source):
        byte = _byte_at(source, index)
        if safe_byte(byte) or byte == 32:
            store_int8(byte_offset(target, offset), int8(43 if byte == 32 else byte))
            offset += 1
        else:
            store_int8(byte_offset(target, offset), int8(37))
            store_int8(byte_offset(target, offset + 1), int8(_byte_at(digits, _positive_quotient(byte, 16))))
            store_int8(byte_offset(target, offset + 2), int8(_byte_at(digits, byte & 15)))
            offset += 3
        index += 1
    return offset


@_runtime
def encode_query(arena: Pointer, allocator: Pointer, context: Pointer, dictionary: Pointer) -> Pointer:
    count = load_integer(dictionary)
    # Bound the separators before loading possibly absent entry arrays.
    if count < 0 or count > 4611686018427387904:
        return null()
    keys = load_pointer(byte_offset(dictionary, KEYS))
    values = load_pointer(byte_offset(dictionary, VALUES))
    result = new_owned(arena, allocator, context, query_size(count, keys, values))
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    index = 0
    offset = 0
    while index < count:
        if index:
            store_int8(byte_offset(target, offset), int8(38))
            offset += 1
        offset = copy_component(target, offset, load_pointer(pointer_slot(keys, index)))
        store_int8(byte_offset(target, offset), int8(61))
        offset = copy_component(target, offset + 1, load_pointer(pointer_slot(values, index)))
        index += 1
    return result


@cache
def compiled_runtime():
    from .compiler import compile_runtime

    return compile_runtime({"pyjs.urlencode": encode_query}, dependencies={
        "pyjs.string.new.owned": new_owned,
    })
