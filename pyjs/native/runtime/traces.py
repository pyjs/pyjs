"""Best-effort traceback construction and descriptor output."""

import ctypes

from pyjs import int32

from .algorithms import _runtime
from .arena import allocate_in_arena
from .buffers import STRING_DATA_OFFSET, write_all
from .pointers import (
    Pointer,
    byte_offset,
    is_null,
    load_integer,
    load_pointer,
    same_address,
    store_pointer,
)


class _Exception(ctypes.Structure):
    # The completion marker follows the retained value through handler copies
    # and iterator wrappers. It is reset for every ordinary raised exception.
    _fields_ = [("active", ctypes.c_bool), ("type", ctypes.c_void_p),
                ("trace", ctypes.c_void_p), ("message", ctypes.c_void_p),
                ("fallback", ctypes.c_void_p), ("value", ctypes.c_void_p),
                ("represented_completion", ctypes.c_bool)]


class _Trace(ctypes.Structure):
    _fields_ = [("frame", ctypes.c_void_p), ("next", ctypes.c_void_p)]


TRACE_OFFSET = _Exception.trace.offset
FALLBACK_OFFSET = _Exception.fallback.offset
NEXT_OFFSET = _Trace.next.offset
TRACE_SIZE = ctypes.sizeof(_Trace)
EXCEPTION_SIZE = ctypes.sizeof(_Exception)


@_runtime
def prepend(arena: Pointer, exception: Pointer, frame: Pointer) -> None:
    slot = byte_offset(exception, TRACE_OFFSET)
    previous = load_pointer(slot)
    fallback = load_pointer(byte_offset(exception, FALLBACK_OFFSET))
    if same_address(previous, fallback):
        return
    trace = allocate_in_arena(arena, TRACE_SIZE, 8)
    if is_null(trace):
        # Keep the immutable raise site and do not retry in subsequent frames.
        store_pointer(slot, fallback)
        return
    store_pointer(trace, frame)
    store_pointer(byte_offset(trace, NEXT_OFFSET), previous)
    store_pointer(slot, trace)


@_runtime
def write_string(descriptor: int32, value: Pointer) -> int32:
    return write_all(descriptor, load_pointer(byte_offset(value, STRING_DATA_OFFSET)), load_integer(value))


@_runtime
def write_trace(descriptor: int32, trace: Pointer, message: Pointer,
                header: Pointer, newline: Pointer) -> None:
    # Diagnostics remain best-effort even if one write fails. Never allocate
    # here: this path must also report allocator failures.
    write_string(descriptor, header)
    current = trace
    while not is_null(current):
        write_string(descriptor, load_pointer(current))
        current = load_pointer(byte_offset(current, NEXT_OFFSET))
    write_string(descriptor, message)
    write_string(descriptor, newline)
