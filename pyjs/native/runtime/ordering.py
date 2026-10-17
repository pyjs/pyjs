"""Scalar collection ordering and stable sorting over unboxed storage."""

import ctypes
from functools import cache

from pyjs import int8

from .algorithms import _positive_quotient, _runtime, bytes_equal, bytes_less
from .arena import _Arena, allocate_in_arena, destroy_arena, initialize
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    copy,
    is_null,
    load_bool,
    load_float,
    load_integer,
    load_pointer,
    null,
    same_address,
    stack_buffer,
    store_integer,
    store_pointer,
    trap,
)
from .sequences import CAPACITY, ITEMS_OFFSET, SIZE

ARENA_SIZE = ctypes.sizeof(_Arena)


@_runtime
def equal(left: Pointer, right: Pointer, kind: int8) -> bool:
    if kind == int8(1):
        return load_bool(left) == load_bool(right)
    if kind == int8(2):
        return load_integer(left) == load_integer(right)
    if kind == int8(3):
        return bytes_equal(borrow_bytes(load_pointer(left)), borrow_bytes(load_pointer(right)))
    if kind == int8(4):
        return load_float(left) == load_float(right)
    trap()
    return False


@_runtime
def less(left: Pointer, right: Pointer, kind: int8) -> bool:
    if kind == int8(1):
        return not load_bool(left) and load_bool(right)
    if kind == int8(2):
        return load_integer(left) < load_integer(right)
    if kind == int8(3):
        return bytes_less(borrow_bytes(load_pointer(left)), borrow_bytes(load_pointer(right)))
    if kind == int8(4):
        return load_float(left) < load_float(right)
    trap()
    return False


@_runtime
def compare_lists(left: Pointer, right: Pointer, size: int, kind: int8) -> int8:
    if same_address(left, right):
        return int8(0)
    left_length = load_integer(left)
    right_length = load_integer(right)
    length = left_length if left_length < right_length else right_length
    left_data = load_pointer(byte_offset(left, ITEMS_OFFSET))
    right_data = load_pointer(byte_offset(right, ITEMS_OFFSET))
    index = 0
    while index < length:
        a = byte_offset(left_data, index * size)
        b = byte_offset(right_data, index * size)
        if not equal(a, b, kind):
            if less(a, b, kind):
                return int8(-1)
            if less(b, a, kind):
                return int8(1)
            return int8(2)
        index += 1
    return int8(-1) if left_length < right_length else int8(1) if left_length > right_length else int8(0)


@_runtime
def merge_sort(data: Pointer, length: int, size: int, scratch: Pointer,
               kind: int8, reverse: bool) -> None:
    # Each complete pass is published at once. Reverse changes the comparison,
    # not the output traversal: equal elements keep their original order.
    width = 1
    while width < length:
        left = 0
        while left < length:
            middle = left + (width if width < length - left else length - left)
            right = middle + (width if width < length - middle else length - middle)
            i = left
            j = middle
            out = left
            while out < right:
                choose_right = i == middle
                if i < middle and j < right:
                    a = byte_offset(data, i * size)
                    b = byte_offset(data, j * size)
                    choose_right = less(a, b, kind) if reverse else less(b, a, kind)
                if choose_right:
                    source = byte_offset(data, j * size)
                    j += 1
                else:
                    source = byte_offset(data, i * size)
                    i += 1
                copy(byte_offset(scratch, out * size), source, size)
                out += 1
            left = right
        copy(data, scratch, length * size)
        width = length if width > _positive_quotient(length, 2) else width * 2


@_runtime
def sort(value: Pointer, size: int, kind: int8, reverse: bool) -> bool:
    length = load_integer(value)
    if length < 0:
        return False
    if length < 2:
        return True
    if size <= 0 or length > _positive_quotient(9223372036854775807, size):
        return False
    # Sorting scratch must not accumulate for the duration of a render request.
    # Scalar comparisons neither allocate nor call application code.
    arena = stack_buffer(ARENA_SIZE)
    initialize(arena)
    scratch = allocate_in_arena(arena, length * size, 8)
    success = not is_null(scratch)
    if success:
        merge_sort(load_pointer(byte_offset(value, ITEMS_OFFSET)), length, size, scratch, kind, reverse)
    destroy_arena(arena)
    return success


@_runtime
def sort_keyed(value: Pointer, keys: Pointer, size: int, key_size: int,
               kind: int8, reverse: bool) -> bool:
    length = load_integer(value)
    if length < 0 or load_integer(keys) != length:
        return False
    if length < 2:
        return True
    if size <= 0 or size > 8 or key_size <= 0 or key_size > 8:
        return False
    if length > _positive_quotient(9223372036854775807, 16):
        return False
    arena = stack_buffer(ARENA_SIZE)
    initialize(arena)
    records = allocate_in_arena(arena, length * 16, 8)
    scratch = allocate_in_arena(arena, length * 16, 8)
    success = not is_null(records) and not is_null(scratch)
    if success:
        data = load_pointer(byte_offset(value, ITEMS_OFFSET))
        key_data = load_pointer(byte_offset(keys, ITEMS_OFFSET))
        index = 0
        while index < length:
            record = byte_offset(records, index * 16)
            copy(record, byte_offset(key_data, index * key_size), key_size)
            copy(byte_offset(record, 8), byte_offset(data, index * size), size)
            index += 1
        # The stable sort compares the first field and moves the complete
        # record. Padded slots preserve alignment for every key kind. All
        # Python callbacks ran before this allocation-only runtime phase.
        merge_sort(records, length, 16, scratch, kind, reverse)
        index = 0
        while index < length:
            copy(byte_offset(data, index * size), byte_offset(records, index * 16 + 8), size)
            index += 1
    destroy_arena(arena)
    return success


@_runtime
def detach(value: Pointer, saved: Pointer) -> None:
    copy(saved, value, SIZE)
    store_integer(value, 0)
    store_integer(byte_offset(value, CAPACITY), 0)
    store_pointer(byte_offset(value, ITEMS_OFFSET), null())


@_runtime
def restore(value: Pointer, saved: Pointer) -> bool:
    # Mutating callbacks use fresh storage. Even append followed by clear must
    # count as a mutation, while reads and no-op edits leave the null buffer.
    unchanged = is_null(load_pointer(byte_offset(value, ITEMS_OFFSET)))
    copy(value, saved, SIZE)
    return unchanged


@cache
def compiled_runtime() -> tuple[str, ...]:
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.collection.equal": equal,
        "pyjs.collection.less": less,
        "pyjs.list.compare": compare_lists,
        "pyjs.list.sort": sort,
        "pyjs.list.sort.keyed": sort_keyed,
        "pyjs.collection.merge.sort": merge_sort,
        "pyjs.list.sort.detach": detach,
        "pyjs.list.sort.restore": restore,
    }, dependencies={
        "pyjs.string.equal": bytes_equal,
        "pyjs.string.less": bytes_less,
        "pyjs.arena.init": initialize,
        "pyjs.arena.try.alloc": allocate_in_arena,
        "pyjs.arena.destroy": destroy_arena,
    })
