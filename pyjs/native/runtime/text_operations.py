"""Owned immutable text using the existing collection allocator contract."""

import ctypes

from .algorithms import _runtime
from .arena import allocate_collection, scalar_allocator
from .pointers import (
    Pointer,
    byte_offset,
    copy,
    is_null,
    load_integer,
    load_pointer,
    null,
    store_integer,
    store_pointer,
)

STRING_DATA_OFFSET = ctypes.sizeof(ctypes.c_int64)
STRING_SIZE = STRING_DATA_OFFSET + ctypes.sizeof(ctypes.c_void_p)


@_runtime
def new_owned(arena: Pointer, allocator: Pointer, context: Pointer, length: int) -> Pointer:
    if length < 0 or length > 9223372036854775807 - STRING_SIZE:
        return null()
    # Immutable payloads never grow independently. Keep the header and bytes in
    # one owner allocation, avoiding a second failure point and GC object. The
    # public header layout is unchanged; even an empty result owns its header.
    # A caller can also allocate reference-bearing containers (split/partition).
    # Select atomic ownership here so every text payload has the same contract.
    result = allocate_collection(arena, scalar_allocator(allocator), context, STRING_SIZE + length)
    if is_null(result):
        return null()
    store_integer(result, length)
    store_pointer(byte_offset(result, STRING_DATA_OFFSET), byte_offset(result, STRING_SIZE))
    return result


@_runtime
def concat_owned(arena: Pointer, allocator: Pointer, context: Pointer, left: Pointer, right: Pointer) -> Pointer:
    first = load_integer(left)
    second = load_integer(right)
    if first < 0 or second < 0 or second > 9223372036854775807 - first:
        return null()
    result = new_owned(arena, allocator, context, first + second)
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    copy(target, load_pointer(byte_offset(left, STRING_DATA_OFFSET)), first)
    copy(byte_offset(target, first), load_pointer(byte_offset(right, STRING_DATA_OFFSET)), second)
    return result
