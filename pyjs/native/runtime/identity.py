"""Call-local identity maps: arena-owned storage, never a GC root or safepoint.

Keys are non-null addresses, compared but never dereferenced. Values may be
null. A half-full table guarantees a vacant slot; deletion repairs the probe
chain without tombstones. Callers keep both keys and values rooted themselves.
"""

import ctypes

from .algorithms import _positive_quotient, _runtime
from .arena import allocate_in_arena
from .heap import address_bucket, unsigned_shift
from .pointers import (
    Pointer,
    address,
    byte_offset,
    copy,
    is_null,
    load_integer,
    load_pointer,
    null,
    same_address,
    store_integer,
    store_pointer,
)


class _Map(ctypes.Structure):
    _fields_ = [("length", ctypes.c_int64), ("capacity", ctypes.c_int64),
                ("entries", ctypes.c_void_p)]


class _Entry(ctypes.Structure):
    _fields_ = [("key", ctypes.c_void_p), ("value", ctypes.c_void_p)]


MAP_SIZE = ctypes.sizeof(_Map)
CAPACITY_OFFSET = _Map.capacity.offset
ENTRIES_OFFSET = _Map.entries.offset
ENTRY_SIZE = ctypes.sizeof(_Entry)
VALUE_OFFSET = _Entry.value.offset
MAX_CAPACITY = 9223372036854775807 // ENTRY_SIZE


@_runtime
def new_map(arena: Pointer) -> Pointer:
    result = allocate_in_arena(arena, MAP_SIZE, 8)
    if not is_null(result):
        store_integer(result, 0)
        store_integer(byte_offset(result, CAPACITY_OFFSET), 0)
        store_pointer(byte_offset(result, ENTRIES_OFFSET), null())
    return result


@_runtime
def find_slot(entries: Pointer, capacity: int, key: Pointer) -> Pointer:
    mask = capacity - 1
    index = address_bucket(address(key), mask)
    while True:
        slot = byte_offset(entries, index * ENTRY_SIZE)
        candidate = load_pointer(slot)
        if is_null(candidate) or same_address(candidate, key):
            return slot
        index = (index + 1) & mask


@_runtime
def get(mapping: Pointer, key: Pointer) -> Pointer:
    capacity = load_integer(byte_offset(mapping, CAPACITY_OFFSET))
    if capacity == 0:
        return null()
    entries = load_pointer(byte_offset(mapping, ENTRIES_OFFSET))
    slot = find_slot(entries, capacity, key)
    return load_pointer(byte_offset(slot, VALUE_OFFSET))


@_runtime
def clear_entry(slot: Pointer) -> None:
    store_pointer(slot, null())
    store_pointer(byte_offset(slot, VALUE_OFFSET), null())


@_runtime
def remove(mapping: Pointer, key: Pointer) -> bool:
    capacity = load_integer(byte_offset(mapping, CAPACITY_OFFSET))
    if capacity == 0:
        return False
    entries = load_pointer(byte_offset(mapping, ENTRIES_OFFSET))
    slot = find_slot(entries, capacity, key)
    if is_null(load_pointer(slot)):
        return False
    clear_entry(slot)
    store_integer(mapping, load_integer(mapping) - 1)
    hole = _positive_quotient(address(slot) - address(entries), ENTRY_SIZE)
    mask = capacity - 1
    index = (hole + 1) & mask
    slot = byte_offset(entries, index * ENTRY_SIZE)
    candidate = load_pointer(slot)
    while not is_null(candidate):
        home = address_bucket(address(candidate), mask)
        # Only move entries whose probe path crosses the hole, including
        # wrapped clusters. Each entry is visited once, without allocation.
        if ((hole - home) & mask) < ((index - home) & mask):
            copy(byte_offset(entries, hole * ENTRY_SIZE), slot, ENTRY_SIZE)
            clear_entry(slot)
            hole = index
        index = (index + 1) & mask
        slot = byte_offset(entries, index * ENTRY_SIZE)
        candidate = load_pointer(slot)
    return True


@_runtime
def put(arena: Pointer, mapping: Pointer, key: Pointer, value: Pointer) -> bool:
    length = load_integer(mapping)
    capacity_slot = byte_offset(mapping, CAPACITY_OFFSET)
    capacity = load_integer(capacity_slot)
    entries_slot = byte_offset(mapping, ENTRIES_OFFSET)
    entries = load_pointer(entries_slot)
    if capacity > MAX_CAPACITY:
        return False
    if capacity:
        slot = find_slot(entries, capacity, key)
        if not is_null(load_pointer(slot)):
            store_pointer(byte_offset(slot, VALUE_OFFSET), value)
            return True
    if length >= unsigned_shift(capacity, 1):
        # Reject overflow before allocating or publishing a replacement table.
        if capacity > unsigned_shift(MAX_CAPACITY, 1):
            return False
        new_capacity = capacity * 2 if capacity else 16
        created = allocate_in_arena(arena, new_capacity * ENTRY_SIZE, 8)
        if is_null(created):
            return False
        index = 0
        while index < new_capacity:
            clear_entry(byte_offset(created, index * ENTRY_SIZE))
            index += 1
        index = 0
        while index < capacity:
            old = byte_offset(entries, index * ENTRY_SIZE)
            candidate = load_pointer(old)
            if not is_null(candidate):
                copy(find_slot(created, new_capacity, candidate), old, ENTRY_SIZE)
            index += 1
        store_integer(capacity_slot, new_capacity)
        store_pointer(entries_slot, created)
        capacity = new_capacity
        entries = created
    slot = find_slot(entries, capacity, key)
    if is_null(load_pointer(slot)):
        store_integer(mapping, length + 1)
    store_pointer(slot, key)
    store_pointer(byte_offset(slot, VALUE_OFFSET), value)
    return True
