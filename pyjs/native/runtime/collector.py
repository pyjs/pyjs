"""Non-moving tracing collector over explicit, non-collecting primitives."""

import ctypes

from pyjs import int8, int32, int64

from .algorithms import _runtime
from .arena import allocate_in_arena
from .heap import (
    HEAP_BYTE_THRESHOLD_OFFSET,
    HEAP_BYTES_OFFSET,
    HEAP_COUNT_OFFSET,
    HEAP_ENABLED_OFFSET,
    HEAP_INDEX_OFFSET,
    HEAP_PRESSURE_OFFSET,
    HEAP_SIZE,
    HEAP_THRESHOLD_OFFSET,
    OBJECT_DESCRIPTOR_OFFSET,
    OBJECT_MARK_OFFSET,
    OBJECT_SIZE,
    OBJECT_SIZE_OFFSET,
    address_bucket,
    unsigned_less,
    unsigned_shift,
)
from .pointers import (
    Pointer,
    address,
    allocate,
    allocate_zeroed,
    byte_offset,
    fill,
    free,
    is_null,
    load_bool,
    load_integer,
    load_pointer,
    null,
    pointer_slot,
    sort_addresses,
    store_bool,
    store_integer,
    store_pointer,
    trace_reference,
    trap,
)
from .roots import (
    FRAME_COUNT_OFFSET,
    FRAME_SLOTS_OFFSET,
    FRAMES_OFFSET,
    MODULE_VALUE_OFFSET,
    MODULES_OFFSET,
    PIN_VALUE_OFFSET,
    PINS_OFFSET,
    try_pin,
)


class _Index(ctypes.Structure):
    _fields_ = [("mask", ctypes.c_int64), ("start", ctypes.c_int64),
                ("end", ctypes.c_int64), ("sorted", ctypes.c_bool)]


class _Descriptor(ctypes.Structure):
    _fields_ = [("count", ctypes.c_int64), ("trace", ctypes.c_void_p)]


INDEX_SIZE = ctypes.sizeof(_Index)
INDEX_START_OFFSET = _Index.start.offset
INDEX_END_OFFSET = _Index.end.offset
INDEX_SORTED_OFFSET = _Index.sorted.offset
DESCRIPTOR_TRACE_OFFSET = _Descriptor.trace.offset


@_runtime
def initialize(heap: Pointer) -> None:
    store_pointer(heap, null())
    store_pointer(byte_offset(heap, PINS_OFFSET), null())
    store_pointer(byte_offset(heap, FRAMES_OFFSET), null())
    store_integer(byte_offset(heap, HEAP_COUNT_OFFSET), 0)
    store_integer(byte_offset(heap, HEAP_THRESHOLD_OFFSET), 4096)
    store_bool(byte_offset(heap, HEAP_ENABLED_OFFSET), True)
    store_pointer(byte_offset(heap, MODULES_OFFSET), null())
    store_integer(byte_offset(heap, HEAP_PRESSURE_OFFSET), 0)
    store_pointer(byte_offset(heap, HEAP_INDEX_OFFSET), null())
    store_integer(byte_offset(heap, HEAP_BYTES_OFFSET), 0)
    store_integer(byte_offset(heap, HEAP_BYTE_THRESHOLD_OFFSET), 8388608)


@_runtime
def new_heap() -> Pointer:
    heap = allocate(HEAP_SIZE)
    if not is_null(heap):
        initialize(heap)
    return heap


@_runtime
def enable(heap: Pointer) -> None:
    store_bool(byte_offset(heap, HEAP_ENABLED_OFFSET), True)


@_runtime
def disable(heap: Pointer) -> None:
    store_bool(byte_offset(heap, HEAP_ENABLED_OFFSET), False)


@_runtime
def is_enabled(heap: Pointer) -> bool:
    return load_bool(byte_offset(heap, HEAP_ENABLED_OFFSET))


@_runtime
def try_set_threshold(heap: Pointer, threshold: int, byte_threshold: int) -> bool:
    if threshold <= 0 or byte_threshold <= 0:
        return False
    store_integer(byte_offset(heap, HEAP_THRESHOLD_OFFSET), threshold)
    store_integer(byte_offset(heap, HEAP_BYTE_THRESHOLD_OFFSET), byte_threshold)
    return True


@_runtime
def compare_addresses(left: Pointer, right: Pointer) -> int32:
    first = address(load_pointer(left))
    second = address(load_pointer(right))
    if unsigned_less(first, second):
        return int32(-1)
    return int32(1) if unsigned_less(second, first) else int32(0)


@_runtime
def index_slot(index: Pointer, candidate: int) -> Pointer:
    mask = load_integer(index)
    table = byte_offset(index, INDEX_SIZE)
    offset = address_bucket(candidate, mask)
    while True:
        slot = pointer_slot(table, offset)
        value = load_pointer(slot)
        if is_null(value) or address(byte_offset(value, OBJECT_SIZE)) == candidate:
            return slot
        offset = (offset + 1) & mask


@_runtime
def build_index_in(heap: Pointer, arena: Pointer) -> bool:
    # Scratch follows the header: exact-base hash table and object ranges.
    # Only the owning collector needs a mark stack; arena-backed snapshots
    # support lookup alone. Interior lookup lazily sorts the ranges.
    count = load_integer(byte_offset(heap, HEAP_COUNT_OFFSET))
    if count == 0:
        return True
    # Bounds cover capacity doubling, both auxiliary arrays, and their byte
    # size before allocation. Failure publishes no index and changes no marks.
    if count < 0 or count > unsigned_shift(9223372036854775807 - INDEX_SIZE, 5):
        return False
    minimum = count * 2
    capacity = 1
    while capacity < minimum:
        capacity *= 2
    words = capacity + count
    if is_null(arena):
        words += count
    if words > unsigned_shift(9223372036854775807 - INDEX_SIZE, 3):
        return False
    size = INDEX_SIZE + words * 8
    if is_null(arena):
        index = allocate_zeroed(size)
    else:
        index = allocate_in_arena(arena, size, 8)
        if not is_null(index):
            fill(index, int8(0), size)
    if is_null(index):
        return False
    store_integer(index, capacity - 1)
    objects = pointer_slot(byte_offset(index, INDEX_SIZE), capacity)
    value = load_pointer(heap)
    low = -1
    high = 0
    offset = 0
    while offset < count:
        start = address(byte_offset(value, OBJECT_SIZE))
        end = int(int64(start + load_integer(byte_offset(value, OBJECT_SIZE_OFFSET))))
        if unsigned_less(start, low):
            low = start
        if unsigned_less(high, end):
            high = end
        store_pointer(index_slot(index, start), value)
        store_pointer(pointer_slot(objects, offset), value)
        value = load_pointer(value)
        offset += 1
    store_integer(byte_offset(index, INDEX_START_OFFSET), low)
    store_integer(byte_offset(index, INDEX_END_OFFSET), high)
    store_pointer(byte_offset(heap, HEAP_INDEX_OFFSET), index)
    return True


@_runtime
def build_index(heap: Pointer) -> bool:
    return build_index_in(heap, null())


@_runtime
def find_indexed(index: Pointer, count: int, candidate: int) -> Pointer:
    if unsigned_less(candidate, load_integer(byte_offset(index, INDEX_START_OFFSET))) or not unsigned_less(
        candidate, load_integer(byte_offset(index, INDEX_END_OFFSET)),
    ):
        return null()
    exact = load_pointer(index_slot(index, candidate))
    if not is_null(exact):
        return exact if load_integer(byte_offset(exact, OBJECT_SIZE_OFFSET)) != 0 else null()
    objects = pointer_slot(byte_offset(index, INDEX_SIZE), load_integer(index) + 1)
    if not load_bool(byte_offset(index, INDEX_SORTED_OFFSET)):
        sort_addresses(objects, count)
        store_bool(byte_offset(index, INDEX_SORTED_OFFSET), True)
    low = 0
    high = count
    while low < high:
        middle = low + unsigned_shift(high - low, 1)
        value = load_pointer(pointer_slot(objects, middle))
        start = address(byte_offset(value, OBJECT_SIZE))
        if unsigned_less(candidate, start):
            high = middle
        elif unsigned_less(int(int64(candidate - start)), load_integer(byte_offset(value, OBJECT_SIZE_OFFSET))):
            return value
        else:
            low = middle + 1
    return null()


@_runtime
def find(heap: Pointer, candidate: Pointer) -> Pointer:
    if is_null(candidate):
        return null()
    index = load_pointer(byte_offset(heap, HEAP_INDEX_OFFSET))
    target = address(candidate)
    if not is_null(index):
        return find_indexed(index, load_integer(byte_offset(heap, HEAP_COUNT_OFFSET)), target)
    value = load_pointer(heap)
    while not is_null(value):
        start = address(byte_offset(value, OBJECT_SIZE))
        if not unsigned_less(target, start) and unsigned_less(
            int(int64(target - start)), load_integer(byte_offset(value, OBJECT_SIZE_OFFSET)),
        ):
            return value
        value = load_pointer(value)
    return null()


@_runtime
def push(heap: Pointer, candidate: Pointer, work: Pointer, top: int) -> int:
    value = find(heap, candidate)
    if not is_null(value) and not load_bool(byte_offset(value, OBJECT_MARK_OFFSET)):
        # Mark before enqueue: every allocation occupies at most one work slot,
        # even for cycles or heavily shared graphs. Capacity is the live count.
        store_bool(byte_offset(value, OBJECT_MARK_OFFSET), True)
        store_pointer(pointer_slot(work, top), value)
        return top + 1
    return top


@_runtime
def mark(heap: Pointer, candidate: Pointer) -> None:
    first = find(heap, candidate)
    if is_null(first) or load_bool(byte_offset(first, OBJECT_MARK_OFFSET)):
        return
    index = load_pointer(byte_offset(heap, HEAP_INDEX_OFFSET))
    work = pointer_slot(byte_offset(index, INDEX_SIZE), load_integer(index) + 1 + load_integer(byte_offset(heap, HEAP_COUNT_OFFSET)))
    store_bool(byte_offset(first, OBJECT_MARK_OFFSET), True)
    store_pointer(work, first)
    top = 1
    while top:
        top -= 1
        value = load_pointer(pointer_slot(work, top))
        payload = byte_offset(value, OBJECT_SIZE)
        descriptor = load_pointer(byte_offset(value, OBJECT_DESCRIPTOR_OFFSET))
        words = unsigned_shift(load_integer(byte_offset(value, OBJECT_SIZE_OFFSET)), 3)
        if is_null(descriptor):
            offset = 0
            while offset < words:
                top = push(heap, load_pointer(pointer_slot(payload, offset)), work, top)
                offset += 1
        else:
            count = load_integer(descriptor)
            if count < 0:
                count = words
            trace = load_pointer(byte_offset(descriptor, DESCRIPTOR_TRACE_OFFSET))
            offset = 0
            while offset < count:
                top = push(heap, trace_reference(trace, payload, offset), work, top)
                offset += 1


@_runtime
def mark_frames(heap: Pointer) -> None:
    frame = load_pointer(byte_offset(heap, FRAMES_OFFSET))
    while not is_null(frame):
        slots = load_pointer(byte_offset(frame, FRAME_SLOTS_OFFSET))
        count = load_integer(byte_offset(frame, FRAME_COUNT_OFFSET))
        index = 0
        while index < count:
            mark(heap, load_pointer(load_pointer(pointer_slot(slots, index))))
            index += 1
        frame = load_pointer(frame)


@_runtime
def mark_modules(heap: Pointer) -> None:
    root = load_pointer(byte_offset(heap, MODULES_OFFSET))
    while not is_null(root):
        mark(heap, load_pointer(byte_offset(root, MODULE_VALUE_OFFSET)))
        root = load_pointer(root)


@_runtime
def sweep(heap: Pointer) -> None:
    link = heap
    value = load_pointer(link)
    while not is_null(value):
        if load_bool(byte_offset(value, OBJECT_MARK_OFFSET)):
            store_bool(byte_offset(value, OBJECT_MARK_OFFSET), False)
            link = value
        else:
            store_pointer(link, load_pointer(value))
            free(value)
            count = byte_offset(heap, HEAP_COUNT_OFFSET)
            store_integer(count, load_integer(count) - 1)
        value = load_pointer(link)
    store_integer(byte_offset(heap, HEAP_PRESSURE_OFFSET), 0)
    store_integer(byte_offset(heap, HEAP_BYTES_OFFSET), 0)
    index = byte_offset(heap, HEAP_INDEX_OFFSET)
    free(load_pointer(index))
    store_pointer(index, null())


@_runtime
def try_collect(heap: Pointer) -> bool:
    if not build_index(heap):
        return False
    pin = load_pointer(byte_offset(heap, PINS_OFFSET))
    while not is_null(pin):
        mark(heap, load_pointer(byte_offset(pin, PIN_VALUE_OFFSET)))
        pin = load_pointer(pin)
    mark_modules(heap)
    mark_frames(heap)
    sweep(heap)
    return True


@_runtime
def collection_due(heap: Pointer) -> bool:
    # Survivors do not consume the next collection's budget.
    return load_bool(byte_offset(heap, HEAP_ENABLED_OFFSET)) and (
        not unsigned_less(load_integer(byte_offset(heap, HEAP_PRESSURE_OFFSET)), load_integer(byte_offset(heap, HEAP_THRESHOLD_OFFSET)))
        or not unsigned_less(load_integer(byte_offset(heap, HEAP_BYTES_OFFSET)), load_integer(byte_offset(heap, HEAP_BYTE_THRESHOLD_OFFSET)))
    )


@_runtime
def maybe_collect(heap: Pointer) -> None:
    if collection_due(heap):
        # A failed mark-work allocation leaves the heap unchanged. Automatic
        # collection can be retried later; it must not abort error unwinding.
        try_collect(heap)


@_runtime
def pin(heap: Pointer, value: Pointer) -> None:
    if is_null(find(heap, value)) or not try_pin(heap, value):
        trap()


@_runtime
def count_pins(heap: Pointer) -> int:
    pin = load_pointer(byte_offset(heap, PINS_OFFSET))
    count = 0
    while not is_null(pin):
        count += 1
        pin = load_pointer(pin)
    return count
