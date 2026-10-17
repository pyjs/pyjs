"""Heap bookkeeping without implicit allocation or collection points."""

import ctypes

from pyjs import int64, llvm

from .algorithms import _runtime
from .pointers import (
    Pointer,
    allocate_zeroed,
    byte_offset,
    is_null,
    load_integer,
    load_pointer,
    null,
    store_integer,
    store_pointer,
)


class _Heap(ctypes.Structure):
    _fields_ = [("objects", ctypes.c_void_p), ("pins", ctypes.c_void_p),
                ("roots", ctypes.c_void_p), ("count", ctypes.c_int64),
                ("threshold", ctypes.c_int64), ("enabled", ctypes.c_bool),
                ("modules", ctypes.c_void_p), ("pressure", ctypes.c_int64),
                ("index", ctypes.c_void_p), ("bytes", ctypes.c_int64),
                ("byte_threshold", ctypes.c_int64)]


class _Object(ctypes.Structure):
    _fields_ = [("next", ctypes.c_void_p), ("size", ctypes.c_int64),
                ("marked", ctypes.c_bool), ("descriptor", ctypes.c_void_p)]


OBJECT_SIZE = ctypes.sizeof(_Object)
OBJECT_SIZE_OFFSET = _Object.size.offset
OBJECT_DESCRIPTOR_OFFSET = _Object.descriptor.offset
OBJECT_MARK_OFFSET = _Object.marked.offset
HEAP_SIZE = ctypes.sizeof(_Heap)
HEAP_THRESHOLD_OFFSET = _Heap.threshold.offset
HEAP_ENABLED_OFFSET = _Heap.enabled.offset
HEAP_INDEX_OFFSET = _Heap.index.offset
HEAP_BYTE_THRESHOLD_OFFSET = _Heap.byte_threshold.offset
HEAP_COUNT_OFFSET = _Heap.count.offset
HEAP_PRESSURE_OFFSET = _Heap.pressure.offset
HEAP_BYTES_OFFSET = _Heap.bytes.offset


@llvm.inline("icmp ult i64 {left}, {right}")
def unsigned_less(left: int, right: int) -> bool:
    return (left & ((1 << 64) - 1)) < (right & ((1 << 64) - 1))


@llvm.inline("lshr i64 {value}, {bits}")
def unsigned_shift(value: int, bits: int) -> int:
    return (value & ((1 << 64) - 1)) >> bits


@_runtime
def address_bucket(value: int, mask: int) -> int:
    # Mix alignment bits away before masking a power-of-two pointer table.
    product = int(int64(unsigned_shift(value, 3) * -7046029254386353131))
    return (product ^ unsigned_shift(product, 32)) & mask


@_runtime
def allocate_described(heap: Pointer, size: int, descriptor: Pointer) -> Pointer:
    header = OBJECT_SIZE
    if size < 0 or size > 9223372036854775807 - header:
        return null()
    total = header + size
    value = allocate_zeroed(total)
    if is_null(value):
        return null()
    store_pointer(value, load_pointer(heap))
    store_integer(byte_offset(value, OBJECT_SIZE_OFFSET), size)
    store_pointer(byte_offset(value, OBJECT_DESCRIPTOR_OFFSET), descriptor)
    store_pointer(heap, value)
    count = byte_offset(heap, HEAP_COUNT_OFFSET)
    store_integer(count, int(int64(load_integer(count) + 1)))
    pressure = byte_offset(heap, HEAP_PRESSURE_OFFSET)
    store_integer(pressure, int(int64(load_integer(pressure) + 1)))
    bytes_slot = byte_offset(heap, HEAP_BYTES_OFFSET)
    previous = load_integer(bytes_slot)
    following = int(int64(previous + total))
    # Byte pressure is an unsigned, saturating counter. It schedules a future
    # safe-point collection; allocation itself must never invoke the collector.
    store_integer(bytes_slot, -1 if unsigned_less(following, previous) else following)
    return byte_offset(value, header)
