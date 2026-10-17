"""Live class-token queries and atomic mutation over the request-owned DOM."""

import ctypes

from pyjs import int8

from .algorithms import (
    _compare_bytes,
    _runtime,
    bytes_equal,
    character_in,
    character_width,
)
from .arena import _Arena, destroy_arena, initialize
from .dom_storage import ARGUMENTS_OFFSET, attribute_get, change_attribute, new_attribute
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    copy,
    is_null,
    load_integer,
    load_pointer,
    null,
    pointer_slot,
    stack_buffer,
    store_int8,
    store_integer,
    store_pointer,
)
from .sequences import ITEMS_OFFSET, append_slot, remove_index, try_new_list
from .text_operations import STRING_DATA_OFFSET, STRING_SIZE, new_owned

ARENA_SIZE = ctypes.sizeof(_Arena)


@_runtime
def _class_mutate(arena: Pointer, scratch: Pointer, element: Pointer, inputs: Pointer,
                  input_count: int, remove: bool, class_name: Pointer, whitespace: Pointer, empty: Pointer) -> bool:
    tokens = try_new_list(scratch, null(), null(), STRING_SIZE, 0)
    if is_null(tokens):
        return False
    arguments = load_pointer(byte_offset(element, ARGUMENTS_OFFSET))
    current = attribute_get(arguments, class_name)
    if is_null(current):
        current = empty
    value = borrow_bytes(current)
    spaces = borrow_bytes(whitespace)
    data = load_pointer(byte_offset(current, STRING_DATA_OFFSET))
    offset = 0
    while offset < len(value):
        if character_in(value, offset, spaces):
            offset += character_width(value, offset)
        else:
            end = offset
            while end < len(value) and not character_in(value, end, spaces):
                end += character_width(value, end)
            slot = append_slot(scratch, tokens, STRING_SIZE)
            if is_null(slot):
                return False
            store_integer(slot, end - offset)
            store_pointer(byte_offset(slot, STRING_DATA_OFFSET), byte_offset(data, offset))
            offset = end
    changed = False
    index = 0
    while index < input_count:
        token = load_pointer(pointer_slot(inputs, index))
        length = load_integer(tokens)
        data = load_pointer(byte_offset(tokens, ITEMS_OFFSET))
        found = -1
        read = 0
        while read < length and found < 0:
            if bytes_equal(borrow_bytes(byte_offset(data, read * STRING_SIZE)), borrow_bytes(token)):
                found = read
            read += 1
        if found >= 0 and remove:
            # Python list.remove drops the first occurrence, not all matches.
            remove_index(tokens, found, STRING_SIZE)
            changed = True
        elif found < 0 and not remove:
            slot = append_slot(scratch, tokens, STRING_SIZE)
            if is_null(slot):
                return False
            copy(slot, token, STRING_SIZE)
            changed = True
        index += 1
    if not changed:
        return True
    length = load_integer(tokens)
    size = length - 1 if length > 0 else 0
    data = load_pointer(byte_offset(tokens, ITEMS_OFFSET))
    index = 0
    while index < length:
        amount = load_integer(byte_offset(data, index * STRING_SIZE))
        if amount > 9223372036854775807 - size:
            return False
        size += amount
        index += 1
    joined = new_owned(arena, null(), null(), size)
    if is_null(joined):
        return False
    target = load_pointer(byte_offset(joined, STRING_DATA_OFFSET))
    index = 0
    written = 0
    while index < length:
        if index > 0:
            store_int8(byte_offset(target, written), int8(32))
            written += 1
        token = byte_offset(data, index * STRING_SIZE)
        amount = load_integer(token)
        copy(byte_offset(target, written), load_pointer(byte_offset(token, STRING_DATA_OFFSET)), amount)
        written += amount
        index += 1
    attribute = new_attribute(arena, class_name, joined)
    if is_null(attribute):
        return False
    # change_attribute allocates before publishing, preserving batch atomicity.
    return change_attribute(arena, element, class_name, attribute)


@_runtime
def class_mutate(arena: Pointer, element: Pointer, inputs: Pointer,
                 input_count: int, remove: bool, class_name: Pointer, whitespace: Pointer, empty: Pointer) -> bool:
    if input_count == 0:
        return True
    # Split once per call and borrow inline headers; tokens can themselves be
    # empty or contain whitespace. Only the final joined string belongs to DOM.
    scratch = stack_buffer(ARENA_SIZE)
    initialize(scratch)
    result = _class_mutate(arena, scratch, element, inputs, input_count, remove, class_name, whitespace, empty)
    destroy_arena(scratch)
    return result


@_runtime
def class_query(element: Pointer, token: Pointer, class_name: Pointer, whitespace: Pointer) -> int:
    # A null token requests count; otherwise return its first index or -1.
    # Compare borrowed spans without creating split strings or GC roots.
    arguments = load_pointer(byte_offset(element, ARGUMENTS_OFFSET))
    current = attribute_get(arguments, class_name)
    count_only = is_null(token)
    if is_null(current):
        return 0 if count_only else -1
    value = borrow_bytes(current)
    spaces = borrow_bytes(whitespace)
    offset = 0
    count = 0
    while offset < len(value):
        if character_in(value, offset, spaces):
            offset += character_width(value, offset)
        else:
            end = offset
            while end < len(value) and not character_in(value, end, spaces):
                end += character_width(value, end)
            if not count_only:
                wanted = borrow_bytes(token)
                if len(wanted) == end - offset and _compare_bytes(value, wanted, offset, 0, end - offset) == 0:
                    return count
            count += 1
            offset = end
    return count if count_only else -1
