"""Measured splitting into the existing native list layout."""

import ctypes

from .algorithms import _runtime, find_bytes_between
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    is_null,
    load_integer,
    load_pointer,
    null,
    pointer_slot,
    store_pointer,
    trap,
)
from .sequences import ITEMS_OFFSET, new_list
from .text_buffers import scan_characters
from .text_edit import copy_span

POINTER_SIZE = ctypes.sizeof(ctypes.c_void_p)


@_runtime
def write_part(arena: Pointer, allocator: Pointer, owner: Pointer, result: Pointer,
               value: Pointer, index: int, start: int, length: int, reverse: bool) -> bool:
    if not is_null(result):
        part = copy_span(arena, allocator, owner, value, start, length)
        if is_null(part):
            return False
        position = load_integer(result) - 1 - index if reverse else index
        items = load_pointer(byte_offset(result, ITEMS_OFFSET))
        store_pointer(pointer_slot(items, position), part)
    return True


@_runtime
def scan_parts(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
               separator: Pointer, maximum: int, reverse: bool, whitespace: bool,
               binary: bool, result: Pointer) -> int:
    # The first walk counts pieces; the second publishes into preallocated
    # list storage. Neither walk invokes application code or a GC safe point.
    start = 0
    end = load_integer(value)
    count = 0
    delimiter_length = load_integer(separator)
    if not whitespace and delimiter_length == 0:
        trap()
    source = borrow_bytes(value)
    delimiter = borrow_bytes(separator)
    while True:
        if whitespace:
            edge = scan_characters(value, separator, start, end, reverse, binary, True)
            if reverse:
                end = edge
            else:
                start = edge
            if start == end:
                break
        if maximum >= 0 and count >= maximum:
            if not write_part(arena, allocator, owner, result, value, count, start, end - start, reverse):
                return -1
            count += 1
            break
        if whitespace:
            edge = scan_characters(value, separator, start, end, reverse, binary, False)
        else:
            edge = find_bytes_between(source, delimiter, start, end, reverse)
            if edge < 0:
                if not write_part(arena, allocator, owner, result, value, count, start, end - start, reverse):
                    return -1
                count += 1
                break
        next_edge = edge if whitespace or reverse else edge + delimiter_length
        first = (edge if whitespace else edge + delimiter_length) if reverse else start
        last = end if reverse else edge
        if not write_part(arena, allocator, owner, result, value, count, first, last - first, reverse):
            return -1
        count += 1
        if reverse:
            end = next_edge
        else:
            start = next_edge
    return count


@_runtime
def split(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
          separator: Pointer, maximum: int, reverse: bool, whitespace: bool, binary: bool) -> Pointer:
    count = scan_parts(arena, allocator, owner, value, separator, maximum, reverse, whitespace, binary, null())
    result = new_list(arena, allocator, owner, POINTER_SIZE, count)
    if is_null(result):
        return null()
    if scan_parts(arena, allocator, owner, value, separator, maximum, reverse, whitespace, binary, result) < 0:
        return null()
    return result
