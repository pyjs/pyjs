"""Byte and text operations over the common immutable span layout."""

import ctypes

from pyjs import int8

from .algorithms import (
    _byte_at,
    _positive_quotient,
    _runtime,
    character_width,
    contains_byte,
    find_bytes_between,
    string_length,
)
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    copy,
    fill,
    is_null,
    load_integer,
    load_pointer,
    null,
    pointer_slot,
    store_int8,
    store_integer,
    store_pointer,
)
from .sequences import ITEMS_OFFSET, new_list, new_tuple
from .text_buffers import repeat_bytes
from .text_edit import copy_span
from .text_operations import STRING_DATA_OFFSET, new_owned
from .text_split import write_part

POINTER_SIZE = ctypes.sizeof(ctypes.c_void_p)


@_runtime
def valid_byte_items(values: Pointer) -> bool:
    data = load_pointer(byte_offset(values, ITEMS_OFFSET))
    index = 0
    while index < load_integer(values):
        item = load_integer(byte_offset(data, index * 8))
        if item < 0 or item > 255:
            return False
        index += 1
    return True


@_runtime
def new_bytes(arena: Pointer, allocator: Pointer, owner: Pointer, count: int, values: Pointer) -> Pointer:
    result = new_owned(arena, allocator, owner, count)
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    if is_null(values):
        fill(target, int8(0), count)
    else:
        data = load_pointer(byte_offset(values, ITEMS_OFFSET))
        index = 0
        while index < count:
            store_int8(byte_offset(target, index), int8(load_integer(byte_offset(data, index * 8))))
            index += 1
    return result


@_runtime
def get_byte(value: Pointer, index: int) -> int:
    actual = index + load_integer(value) if index < 0 else index
    return _byte_at(borrow_bytes(value), actual)


@_runtime
def hex_bytes(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer) -> Pointer:
    length = load_integer(value)
    if length > 4611686018427387903:
        return null()
    result = new_owned(arena, allocator, owner, length * 2)
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    source = borrow_bytes(value)
    index = 0
    while index < length:
        byte = _byte_at(source, index)
        high = _positive_quotient(byte, 16)
        low = byte & 15
        store_int8(byte_offset(target, index * 2), int8(high + (48 if high < 10 else 87)))
        store_int8(byte_offset(target, index * 2 + 1), int8(low + (48 if low < 10 else 87)))
        index += 1
    return result


@_runtime
def repr_bytes(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer) -> Pointer:
    length = load_integer(value)
    if length > 2305843009213693951:
        return null()
    result = new_owned(arena, allocator, owner, length * 4 + 3)
    if is_null(result):
        return null()
    source = borrow_bytes(value)
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    quote = 34 if contains_byte(source, 39) and not contains_byte(source, 34) else 39
    store_int8(target, int8(98))
    store_int8(byte_offset(target, 1), int8(quote))
    index = 0
    written = 2
    while index < len(source):
        byte = _byte_at(source, index)
        if byte == quote or byte == 92 or byte == 9 or byte == 10 or byte == 13:
            escaped = 116 if byte == 9 else 110 if byte == 10 else 114 if byte == 13 else byte
            store_int8(byte_offset(target, written), int8(92))
            store_int8(byte_offset(target, written + 1), int8(escaped))
            written += 2
        elif byte >= 32 and byte < 127:
            store_int8(byte_offset(target, written), int8(byte))
            written += 1
        else:
            high = _positive_quotient(byte, 16)
            low = byte & 15
            store_int8(byte_offset(target, written), int8(92))
            store_int8(byte_offset(target, written + 1), int8(120))
            store_int8(byte_offset(target, written + 2), int8(high + (48 if high < 10 else 87)))
            store_int8(byte_offset(target, written + 3), int8(low + (48 if low < 10 else 87)))
            written += 4
        index += 1
    store_int8(byte_offset(target, written), int8(quote))
    store_integer(result, written + 1)
    return result


@_runtime
def partition(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
              separator: Pointer, reverse: bool) -> Pointer:
    length = load_integer(value)
    size = load_integer(separator)
    position = find_bytes_between(borrow_bytes(value), borrow_bytes(separator), 0, length, reverse)
    first_end = position if position >= 0 else 0 if reverse else length
    last_start = position + size if position >= 0 else 0 if reverse else length
    result = new_tuple(arena, allocator, owner, 3 * POINTER_SIZE, 3)
    if is_null(result):
        return null()
    data = load_pointer(byte_offset(result, ITEMS_OFFSET))
    first = copy_span(arena, allocator, owner, value, 0, first_end)
    if is_null(first):
        return null()
    store_pointer(data, first)
    middle = copy_span(arena, allocator, owner, separator, 0, size if position >= 0 else 0)
    if is_null(middle):
        return null()
    store_pointer(pointer_slot(data, 1), middle)
    last = copy_span(arena, allocator, owner, value, last_start, length - last_start)
    if is_null(last):
        return null()
    store_pointer(pointer_slot(data, 2), last)
    return result


@_runtime
def remove_affix(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
                 affix: Pointer, reverse: bool) -> Pointer:
    length = load_integer(value)
    size = load_integer(affix)
    start = length - size if reverse else 0
    found = size <= length and find_bytes_between(
        borrow_bytes(value), borrow_bytes(affix), start, start + size, False,
    ) == start
    offset = size if found and not reverse else 0
    return copy_span(arena, allocator, owner, value, offset, length - (size if found else 0))


@_runtime
def line_end(value: bytes, offset: int, binary: bool) -> int:
    first = _byte_at(value, offset)
    if first == 13:
        return offset + (2 if offset + 1 < len(value) and _byte_at(value, offset + 1) == 10 else 1)
    if first == 10:
        return offset + 1
    if not binary:
        if first == 11 or first == 12 or (first >= 28 and first <= 30):
            return offset + 1
        if first == 194 and _byte_at(value, offset + 1) == 133:
            return offset + 2
        if first == 226 and _byte_at(value, offset + 1) == 128:
            last = _byte_at(value, offset + 2)
            if last == 168 or last == 169:
                return offset + 3
    return offset


@_runtime
def scan_lines(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
               keepends: bool, binary: bool, result: Pointer) -> int:
    source = borrow_bytes(value)
    start = 0
    offset = 0
    count = 0
    while offset < len(source):
        end = line_end(source, offset, binary)
        if end == offset:
            offset += 1 if binary else character_width(source, offset)
        else:
            size = (end if keepends else offset) - start
            if not write_part(arena, allocator, owner, result, value, count, start, size, False):
                return -1
            count += 1
            start = end
            offset = end
    if start < offset:
        if not write_part(arena, allocator, owner, result, value, count, start, offset - start, False):
            return -1
        count += 1
    return count


@_runtime
def splitlines(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
               keepends: bool, binary: bool) -> Pointer:
    count = scan_lines(arena, allocator, owner, value, keepends, binary, null())
    result = new_list(arena, allocator, owner, POINTER_SIZE, count)
    if is_null(result):
        return null()
    if scan_lines(arena, allocator, owner, value, keepends, binary, result) < 0:
        return null()
    return result


@_runtime
def pad(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
        width: int, character: Pointer, alignment: int) -> Pointer:
    length = load_integer(value)
    count = string_length(borrow_bytes(value))
    padding = width - count if width > count else 0
    size = load_integer(character)
    if size > 0 and padding > _positive_quotient(9223372036854775807 - length, size):
        return null()
    result = new_owned(arena, allocator, owner, length + padding * size)
    if is_null(result):
        return null()
    left = padding if alignment == 1 else 0
    if alignment == 2:
        left = _positive_quotient(padding, 2) + (padding & width & 1)
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    fill_data = load_pointer(byte_offset(character, STRING_DATA_OFFSET))
    repeat_bytes(target, fill_data, size, left)
    copy(byte_offset(target, left * size), load_pointer(byte_offset(value, STRING_DATA_OFFSET)), length)
    repeat_bytes(byte_offset(target, left * size + length), fill_data, size, padding - left)
    return result


@_runtime
def zfill(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer, width: int) -> Pointer:
    source = borrow_bytes(value)
    count = string_length(source)
    padding = width - count if width > count else 0
    if padding > 9223372036854775807 - len(source):
        return null()
    result = new_owned(arena, allocator, owner, len(source) + padding)
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    offset = 0
    if len(source) > 0 and (_byte_at(source, 0) == 43 or _byte_at(source, 0) == 45):
        copy(target, data, 1)
        offset = 1
    fill(byte_offset(target, offset), int8(48), padding)
    copy(byte_offset(target, offset + padding), byte_offset(data, offset), len(source) - offset)
    return result


@_runtime
def write_tabs(value: Pointer, tabsize: int, target: Pointer) -> int:
    source = borrow_bytes(value)
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    offset = 0
    column = 0
    size = 0
    while offset < len(source):
        byte = _byte_at(source, offset)
        if byte == 9:
            spaces = tabsize - (column - _positive_quotient(column, tabsize) * tabsize) if tabsize > 0 else 0
            if spaces > 9223372036854775807 - size:
                return -1
            if not is_null(target):
                fill(byte_offset(target, size), int8(32), spaces)
            size += spaces
            column += spaces
            offset += 1
        else:
            width = character_width(source, offset)
            if width > 9223372036854775807 - size:
                return -1
            if not is_null(target):
                copy(byte_offset(target, size), byte_offset(data, offset), width)
            size += width
            column = 0 if byte == 10 or byte == 13 else column + 1
            offset += width
    return size


@_runtime
def expandtabs(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer, tabsize: int) -> Pointer:
    size = write_tabs(value, tabsize, null())
    result = new_owned(arena, allocator, owner, size)
    if is_null(result):
        return null()
    write_tabs(value, tabsize, load_pointer(byte_offset(result, STRING_DATA_OFFSET)))
    return result
