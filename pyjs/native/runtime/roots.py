"""Unmanaged GC roots; callers own frame storage and validate pinned values."""

import ctypes

from .algorithms import _runtime
from .heap import HEAP_INDEX_OFFSET, _Heap
from .pointers import (
    Pointer,
    allocate,
    allocate_zeroed,
    byte_offset,
    free,
    is_null,
    load_integer,
    load_pointer,
    null,
    same_address,
    store_integer,
    store_pointer,
)


class _Frame(ctypes.Structure):
    _fields_ = [("previous", ctypes.c_void_p), ("count", ctypes.c_int64),
                ("slots", ctypes.c_void_p)]


class _ModuleRoot(ctypes.Structure):
    _fields_ = [("next", ctypes.c_void_p), ("key", ctypes.c_int64),
                ("value", ctypes.c_void_p)]


class _Pin(ctypes.Structure):
    _fields_ = [("next", ctypes.c_void_p), ("value", ctypes.c_void_p)]


FRAMES_OFFSET = _Heap.roots.offset
MODULES_OFFSET = _Heap.modules.offset
PINS_OFFSET = _Heap.pins.offset
FRAME_COUNT_OFFSET = _Frame.count.offset
FRAME_SLOTS_OFFSET = _Frame.slots.offset
MODULE_ROOT_SIZE = ctypes.sizeof(_ModuleRoot)
MODULE_KEY_OFFSET = _ModuleRoot.key.offset
MODULE_VALUE_OFFSET = _ModuleRoot.value.offset
PIN_SIZE = ctypes.sizeof(_Pin)
PIN_VALUE_OFFSET = _Pin.value.offset


@_runtime
def module_root(heap: Pointer, key: int) -> Pointer:
    roots = byte_offset(heap, MODULES_OFFSET)
    head = load_pointer(roots)
    root = head
    while not is_null(root):
        if load_integer(byte_offset(root, MODULE_KEY_OFFSET)) == key:
            return byte_offset(root, MODULE_VALUE_OFFSET)
        root = load_pointer(root)
    created = allocate_zeroed(MODULE_ROOT_SIZE)
    if is_null(created):
        return null()
    store_pointer(created, head)
    store_integer(byte_offset(created, MODULE_KEY_OFFSET), key)
    store_pointer(roots, created)
    return byte_offset(created, MODULE_VALUE_OFFSET)


@_runtime
def push_frame(heap: Pointer, frame: Pointer, slots: Pointer, count: int) -> None:
    roots = byte_offset(heap, FRAMES_OFFSET)
    store_pointer(frame, load_pointer(roots))
    store_integer(byte_offset(frame, FRAME_COUNT_OFFSET), count)
    store_pointer(byte_offset(frame, FRAME_SLOTS_OFFSET), slots)
    store_pointer(roots, frame)


@_runtime
def try_pop_frame(heap: Pointer, frame: Pointer) -> bool:
    roots = byte_offset(heap, FRAMES_OFFSET)
    if not same_address(load_pointer(roots), frame):
        return False
    store_pointer(roots, load_pointer(frame))
    return True


@_runtime
def try_pin(heap: Pointer, value: Pointer) -> bool:
    # The public pin entry point proves heap membership (interiors allowed).
    # Pin identity is the supplied address, not the owning allocation's base.
    pins = byte_offset(heap, PINS_OFFSET)
    head = load_pointer(pins)
    existing = head
    while not is_null(existing):
        if same_address(load_pointer(byte_offset(existing, PIN_VALUE_OFFSET)), value):
            return True
        existing = load_pointer(existing)
    pin = allocate(PIN_SIZE)
    if is_null(pin):
        return False
    store_pointer(pin, head)
    store_pointer(byte_offset(pin, PIN_VALUE_OFFSET), value)
    store_pointer(pins, pin)
    return True


@_runtime
def unpin(heap: Pointer, value: Pointer) -> None:
    link = byte_offset(heap, PINS_OFFSET)
    pin = load_pointer(link)
    while not is_null(pin):
        if same_address(load_pointer(byte_offset(pin, PIN_VALUE_OFFSET)), value):
            store_pointer(link, load_pointer(pin))
            free(pin)
            return
        link = pin
        pin = load_pointer(link)


@_runtime
def free_chain(head: Pointer) -> None:
    # Objects, pins, and module roots put their next link first. Frame records
    # are caller-owned stack storage and must never enter this path.
    value = load_pointer(head)
    while not is_null(value):
        following = load_pointer(value)
        free(value)
        store_pointer(head, following)
        value = following


@_runtime
def destroy_heap(heap: Pointer) -> None:
    index = byte_offset(heap, HEAP_INDEX_OFFSET)
    free(load_pointer(index))
    store_pointer(index, null())
    free_chain(heap)
    free_chain(byte_offset(heap, PINS_OFFSET))
    free_chain(byte_offset(heap, MODULES_OFFSET))


@_runtime
def delete_heap(heap: Pointer) -> None:
    destroy_heap(heap)
    free(heap)
