"""Arena algorithms compiled with explicit, unmanaged memory access."""

import ctypes

from pyjs import int8
from pyjs.decorators import native_operation

from .algorithms import _runtime
from .pointers import (
    Pointer,
    address,
    allocate,
    byte_offset,
    free,
    is_null,
    load_integer,
    load_pointer,
    null,
    reallocate,
    same_address,
    store_integer,
    store_pointer,
)


class _Arena(ctypes.Structure):
    _fields_ = [("chunks", ctypes.c_void_p), ("counter", ctypes.c_int64),
                ("buffers", ctypes.c_void_p), ("repr", ctypes.c_void_p)]


class _Chunk(ctypes.Structure):
    _fields_ = [("next", ctypes.c_void_p), ("capacity", ctypes.c_int64),
                ("used", ctypes.c_int64)]


class _ReprFrame(ctypes.Structure):
    _fields_ = [("value", ctypes.c_void_p), ("parent", ctypes.c_void_p)]


CHUNK_SIZE = ctypes.sizeof(_Chunk)
CHUNK_CAPACITY_OFFSET = _Chunk.capacity.offset
CHUNK_USED_OFFSET = _Chunk.used.offset
ARENA_BUFFERS_OFFSET = _Arena.buffers.offset
BUFFER_SIZE = 2 * ctypes.sizeof(ctypes.c_void_p)
BUFFER_DATA_OFFSET = ctypes.sizeof(ctypes.c_void_p)
REPR_OFFSET = _Arena.repr.offset
REPR_PARENT_OFFSET = _ReprFrame.parent.offset
ARENA_COUNTER_OFFSET = _Arena.counter.offset


@_runtime
def initialize(arena: Pointer) -> None:
    store_pointer(arena, null())
    store_integer(byte_offset(arena, ARENA_COUNTER_OFFSET), 0)
    store_pointer(byte_offset(arena, ARENA_BUFFERS_OFFSET), null())
    store_pointer(byte_offset(arena, REPR_OFFSET), null())


@native_operation("memory.invoke")
def _allocate(callback: Pointer, context: Pointer, size: int) -> Pointer:
    signature = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    return Pointer(signature(callback.address)(context.address, size) or 0)


@_runtime
def allocate_collection(arena: Pointer, allocator: Pointer, context: Pointer, size: int) -> Pointer:
    # Even an empty buffer is retained by its header; GC needs a nonempty
    # address range to trace that payload through the stored pointer.
    size = size if size else 1
    if not is_null(allocator):
        return _allocate(allocator, context, size)
    return allocate_in_arena(arena, size, 8)


@native_operation("memory.scalar.allocator")
def scalar_allocator(allocator: Pointer) -> Pointer:
    # Native lowering replaces only recognized GC callbacks. Foreign owners,
    # including the CPython reference callbacks, retain their context and ABI.
    return allocator


@native_operation("memory.allocate.atomic")
def allocate_atomic(arena: Pointer, heap: Pointer, size: int) -> Pointer:
    # The native allocation leaf selects GC atomic storage when heap is nonnull;
    # the CPython reference exercises the same algorithms with arena ownership.
    return allocate_in_arena(arena, size, 8)


@_runtime
def enter_repr(arena: Pointer, frame: Pointer, value: Pointer) -> int8:
    head = load_pointer(byte_offset(arena, REPR_OFFSET))
    current = head
    depth = 0
    while not is_null(current):
        # A null value is a depth-only scope for a user formatting method;
        # unlike builtin containers, such methods have no cycle placeholder.
        if not is_null(value) and same_address(load_pointer(current), value):
            return int8(0)
        current = load_pointer(byte_offset(current, REPR_PARENT_OFFSET))
        depth += 1
    # A repeated value at the limit is still a cycle shortcut, not an error.
    if depth >= 1000:
        return int8(2)
    store_pointer(frame, value)
    store_pointer(byte_offset(frame, REPR_PARENT_OFFSET), head)
    store_pointer(byte_offset(arena, REPR_OFFSET), frame)
    return int8(1)


@_runtime
def leave_repr(arena: Pointer, frame: Pointer) -> bool:
    slot = byte_offset(arena, REPR_OFFSET)
    if not same_address(load_pointer(slot), frame):
        return False
    store_pointer(slot, load_pointer(byte_offset(frame, REPR_PARENT_OFFSET)))
    return True


@_runtime
def resize_buffer(buffer: Pointer, size: int) -> Pointer:
    if size < 0:
        return null()
    slot = byte_offset(buffer, BUFFER_DATA_OFFSET)
    data = reallocate(load_pointer(slot), size if size else 1)
    if not is_null(data):
        # realloc failure leaves the old allocation live. Publish only success
        # so the arena can still use or destroy the original buffer on failure.
        store_pointer(slot, data)
    return data


@_runtime
def allocate_in_arena(arena: Pointer, size: int, alignment: int) -> Pointer:
    # Bound each addition before doing signed-i64 arithmetic, including the
    # header of an oversized chunk. Alignment is measured from the real address,
    # not the payload offset: the chunk header need not itself be aligned.
    if size < 0 or alignment < 1 or (alignment & (alignment - 1)) != 0:
        return null()
    size = size if size else 1
    header = CHUNK_SIZE
    maximum = 9223372036854775807 - header
    if size > maximum or alignment > maximum - size:
        return null()
    while True:
        head = load_pointer(arena)
        if not is_null(head):
            used = load_integer(byte_offset(head, CHUNK_USED_OFFSET))
            capacity = load_integer(byte_offset(head, CHUNK_CAPACITY_OFFSET))
            if used <= 9223372036854775807 - (alignment - 1):
                padding = -(address(head) + header + used) & (alignment - 1)
                offset = used + padding
                if offset <= capacity and size <= capacity - offset:
                    store_integer(byte_offset(head, CHUNK_USED_OFFSET), offset + size)
                    return byte_offset(head, header + offset)
        required = size + alignment
        capacity = required if required > 65536 else 65536
        chunk = allocate(header + capacity)
        if is_null(chunk):
            return null()
        store_pointer(chunk, head)
        store_integer(byte_offset(chunk, CHUNK_CAPACITY_OFFSET), capacity)
        store_integer(byte_offset(chunk, CHUNK_USED_OFFSET), 0)
        store_pointer(arena, chunk)


@_runtime
def new_buffer(arena: Pointer, size: int) -> Pointer:
    if size < 0:
        return null()
    buffer = allocate_in_arena(arena, BUFFER_SIZE, 8)
    if is_null(buffer):
        return null()
    store_pointer(byte_offset(buffer, BUFFER_DATA_OFFSET), null())
    if is_null(resize_buffer(buffer, size)):
        return null()
    # The ownership record stays in the arena even if creation fails, but must
    # not enter the chain of live buffers until its data allocation succeeds.
    buffers = byte_offset(arena, ARENA_BUFFERS_OFFSET)
    store_pointer(buffer, load_pointer(buffers))
    store_pointer(buffers, buffer)
    return buffer


@_runtime
def destroy_arena(arena: Pointer) -> None:
    # Movable data belongs to records inside the chunks: free data first.
    buffers = byte_offset(arena, ARENA_BUFFERS_OFFSET)
    buffer = load_pointer(buffers)
    while not is_null(buffer):
        following = load_pointer(buffer)
        free(load_pointer(byte_offset(buffer, BUFFER_DATA_OFFSET)))
        store_pointer(buffers, following)
        buffer = following
    chunk = load_pointer(arena)
    while not is_null(chunk):
        following = load_pointer(chunk)
        free(chunk)
        store_pointer(arena, following)
        chunk = following
