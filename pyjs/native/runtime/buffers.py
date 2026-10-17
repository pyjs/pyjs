"""Buffered output algorithms over explicit memory and system-call leaves."""

import ctypes

from pyjs import int32

from .algorithms import _runtime
from .arena import BUFFER_DATA_OFFSET, allocate_in_arena, new_buffer, resize_buffer
from .pointers import (
    Pointer,
    byte_offset,
    copy,
    is_null,
    load_int32,
    load_integer,
    load_pointer,
    null,
    store_int32,
    store_integer,
    store_pointer,
)
from .sequences import growth_capacity
from .system import errno, write


class _Output(ctypes.Structure):
    _fields_ = [("arena", ctypes.c_void_p), ("data", ctypes.c_void_p),
                ("length", ctypes.c_int64), ("capacity", ctypes.c_int64),
                ("descriptor", ctypes.c_int32), ("error", ctypes.c_int32),
                ("owner", ctypes.c_void_p)]


OUTPUT_SIZE = ctypes.sizeof(_Output)
STRING_SIZE = ctypes.sizeof(ctypes.c_int64) + ctypes.sizeof(ctypes.c_void_p)
STRING_DATA_OFFSET = ctypes.sizeof(ctypes.c_int64)
DATA_OFFSET = _Output.data.offset
LENGTH_OFFSET = _Output.length.offset
CAPACITY_OFFSET = _Output.capacity.offset
DESCRIPTOR_OFFSET = _Output.descriptor.offset
ERROR_OFFSET = _Output.error.offset
OWNER_OFFSET = _Output.owner.offset


@_runtime
def write_all(descriptor: int32, data: Pointer, length: int) -> int32:
    offset = 0
    while offset < length:
        count = write(descriptor, byte_offset(data, offset), length - offset)
        if count > 0:
            offset += count
        elif count == 0:
            return int32(5)  # EIO: a successful zero-byte write cannot progress.
        else:
            status = errno()
            if status != int32(4):  # EINTR retries the unwritten suffix.
                return status
    return int32(0)


@_runtime
def new_output(arena: Pointer, descriptor: int32) -> Pointer:
    output = allocate_in_arena(arena, OUTPUT_SIZE, 8)
    if is_null(output):
        return null()
    owner = null()
    capacity = 65536 if descriptor >= int32(0) else 4096
    if descriptor >= int32(0):
        data = allocate_in_arena(arena, capacity, 8)
    else:
        owner = new_buffer(arena, capacity)
        if is_null(owner):
            return null()
        data = load_pointer(byte_offset(owner, BUFFER_DATA_OFFSET))
    if is_null(data):
        return null()
    store_pointer(output, arena)
    store_pointer(byte_offset(output, DATA_OFFSET), data)
    store_integer(byte_offset(output, LENGTH_OFFSET), 0)
    store_integer(byte_offset(output, CAPACITY_OFFSET), capacity)
    store_int32(byte_offset(output, DESCRIPTOR_OFFSET), descriptor)
    store_int32(byte_offset(output, ERROR_OFFSET), int32(0))
    store_pointer(byte_offset(output, OWNER_OFFSET), owner)
    return output


@_runtime
def flush(output: Pointer) -> int32:
    error = load_int32(byte_offset(output, ERROR_OFFSET))
    if error != int32(0):
        return error
    descriptor = load_int32(byte_offset(output, DESCRIPTOR_OFFSET))
    length = load_integer(byte_offset(output, LENGTH_OFFSET))
    if descriptor < int32(0) or length == 0:
        return int32(0)
    status = write_all(descriptor, load_pointer(byte_offset(output, DATA_OFFSET)), length)
    store_int32(byte_offset(output, ERROR_OFFSET), status)
    if status == int32(0):
        store_integer(byte_offset(output, LENGTH_OFFSET), 0)
    return status


@_runtime
def reserve_memory(output: Pointer, required: int) -> Pointer:
    # Memory-backed outputs only. Publication of the written length belongs
    # to the caller; failure preserves both existing contents and that length.
    if load_int32(byte_offset(output, ERROR_OFFSET)) != int32(0):
        return null()
    if required < 0:
        store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
        return null()
    capacity = load_integer(byte_offset(output, CAPACITY_OFFSET))
    data = load_pointer(byte_offset(output, DATA_OFFSET))
    if required > capacity:
        following = growth_capacity(capacity, required, 1, 0)
        owner = load_pointer(byte_offset(output, OWNER_OFFSET))
        data = resize_buffer(owner, following)
        if is_null(data):
            store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
            return null()
        store_pointer(byte_offset(output, DATA_OFFSET), data)
        store_integer(byte_offset(output, CAPACITY_OFFSET), following)
    return data


@_runtime
def append_bytes(output: Pointer, source: Pointer, size: int) -> int32:
    error = load_int32(byte_offset(output, ERROR_OFFSET))
    if error != int32(0):
        return error
    if size == 0:
        return int32(0)
    length = load_integer(byte_offset(output, LENGTH_OFFSET))
    if size < 0 or length < 0 or size > 9223372036854775807 - length:
        store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
        return int32(12)
    required = length + size
    capacity = load_integer(byte_offset(output, CAPACITY_OFFSET))
    data = load_pointer(byte_offset(output, DATA_OFFSET))
    descriptor = load_int32(byte_offset(output, DESCRIPTOR_OFFSET))
    if required > capacity:
        if descriptor < int32(0):
            data = reserve_memory(output, required)
            if is_null(data):
                return int32(12)
        else:
            status = flush(output)
            if status != int32(0):
                return status
            if size > capacity:
                status = write_all(descriptor, source, size)
                store_int32(byte_offset(output, ERROR_OFFSET), status)
                return status
            length = 0
            required = size
    # Input must not alias the output buffer: resize may move it, and copy has
    # memcpy semantics. A failed flush is sticky, preventing duplicate output
    # after a partially successful system write.
    copy(byte_offset(data, length), source, size)
    store_integer(byte_offset(output, LENGTH_OFFSET), required)
    return int32(0)


@_runtime
def append_string(output: Pointer, string: Pointer) -> int32:
    return append_bytes(output, load_pointer(byte_offset(string, STRING_DATA_OFFSET)), load_integer(string))


@_runtime
def finish_memory(output: Pointer) -> Pointer:
    if load_int32(byte_offset(output, ERROR_OFFSET)) != int32(0):
        return null()
    string = allocate_in_arena(load_pointer(output), STRING_SIZE, 8)
    if is_null(string):
        store_int32(byte_offset(output, ERROR_OFFSET), int32(12))
        return null()
    # Finishing is terminal: the result borrows the final data until arena
    # destruction. Appending after this point could invalidate that pointer.
    store_integer(string, load_integer(byte_offset(output, LENGTH_OFFSET)))
    store_pointer(byte_offset(string, STRING_DATA_OFFSET), load_pointer(byte_offset(output, DATA_OFFSET)))
    return string
