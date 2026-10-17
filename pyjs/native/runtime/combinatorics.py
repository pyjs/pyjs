"""Index transitions for pooled iterators; no application callbacks occur here."""

from .algorithms import _positive_quotient, _runtime
from .pointers import Pointer, byte_offset, load_integer, load_pointer, store_integer

PRODUCT = 0
COMBINATIONS = 1
REPLACEMENT = 2
PERMUTATIONS = 3


@_runtime
def product_advance(indices: Pointer, pools: Pointer, pool_count: int, size: int) -> bool:
    position = size - 1
    while position >= 0:
        slot = byte_offset(indices, position * 8)
        following = load_integer(slot) + 1
        pool_index = position - _positive_quotient(position, pool_count) * pool_count
        pool = load_pointer(byte_offset(pools, pool_index * 8))
        if following < load_integer(pool):
            store_integer(slot, following)
            return True
        store_integer(slot, 0)
        position -= 1
    return False


@_runtime
def combinations_advance(indices: Pointer, length: int, size: int, replacement: bool) -> bool:
    position = size - 1
    while position >= 0:
        slot = byte_offset(indices, position * 8)
        index = load_integer(slot)
        limit = length - 1 if replacement else length - size + position
        if index < limit:
            following = index + 1
            while position < size:
                store_integer(byte_offset(indices, position * 8), following)
                if not replacement:
                    following += 1
                position += 1
            return True
        position -= 1
    return False


@_runtime
def permutations_advance(indices: Pointer, cycles: Pointer, length: int, size: int) -> bool:
    position = size - 1
    while position >= 0:
        cycle_slot = byte_offset(cycles, position * 8)
        cycle = load_integer(cycle_slot) - 1
        store_integer(cycle_slot, cycle)
        slot = byte_offset(indices, position * 8)
        first = load_integer(slot)
        if cycle != 0:
            selected = byte_offset(indices, (length - cycle) * 8)
            store_integer(slot, load_integer(selected))
            store_integer(selected, first)
            return True
        index = position
        while index + 1 < length:
            store_integer(byte_offset(indices, index * 8), load_integer(byte_offset(indices, (index + 1) * 8)))
            index += 1
        store_integer(byte_offset(indices, index * 8), first)
        store_integer(cycle_slot, length - position)
        position -= 1
    return False
