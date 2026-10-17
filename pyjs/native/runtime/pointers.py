"""Private unmanaged memory primitives for Python-authored runtime code.

Pointers carry no automatic ownership or GC roots. Callers establish alignment,
bounds, lifetimes, and failure recovery. CPython uses the same process allocator
so the algorithms can be exercised without compiling them.

Runtime layout constants use host ctypes sizes/offsets: this is the existing
Linux-native ABI, not cross-target code generation. Tests compare every layout
against LLVM GEP offsets, including padding; a new target must supply its own
layout before reusing these algorithms.
"""

import ctypes
from functools import cache

from pyjs import int8, int32, llvm
from pyjs.decorators import native_operation


@native_operation("memory.pointer")
class Pointer:
    def __init__(self, address: int):
        self.address = address


@llvm.inline("alloca i8, i64 {size}")
def stack_buffer(size: int) -> Pointer:
    # Native storage belongs to the calling frame and must not escape it.
    # CPython retains the matching storage on its pointer handle.
    storage = ctypes.create_string_buffer(size)
    result = Pointer(ctypes.addressof(storage))
    result.storage = storage
    return result


@native_operation("memory.bytes.data")
def bytes_data(value: bytes) -> Pointer:
    # Native bytes borrow their existing payload. CPython has a different
    # layout, so retain a copy for the lifetime of this host-side pointer.
    storage = ctypes.create_string_buffer(value)
    result = Pointer(ctypes.addressof(storage))
    result.storage = storage
    return result


@cache
def _allocator():
    library = ctypes.CDLL(None)
    library.malloc.argtypes = [ctypes.c_size_t]
    library.malloc.restype = ctypes.c_void_p
    library.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    library.calloc.restype = ctypes.c_void_p
    library.realloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    library.realloc.restype = ctypes.c_void_p
    library.free.argtypes = [ctypes.c_void_p]
    library.free.restype = None
    return library


@native_operation("memory.null")
def null() -> Pointer:
    return Pointer(0)


@native_operation("memory.trap")
def trap() -> None:
    # Raw ABI precondition violations are fatal in native code. Python raises
    # instead so reference tests can inspect the same invalid-input boundary.
    raise RuntimeError("invalid native runtime precondition")


@llvm.inline("icmp eq ptr {value}, null")
def is_null(value: Pointer) -> bool:
    return value.address == 0


@llvm.inline("icmp eq ptr {left}, {right}")
def same_address(left: Pointer, right: Pointer) -> bool:
    return left.address == right.address


@llvm.inline("ptrtoint ptr {value} to i64")
def address(value: Pointer) -> int:
    return ctypes.c_int64(value.address).value


@llvm.inline("getelementptr ptr, ptr {value}, i64 {index}")
def pointer_slot(value: Pointer, index: int) -> Pointer:
    return Pointer(value.address + index * ctypes.sizeof(ctypes.c_void_p))


@llvm.inline("load i1, ptr {slot}")
def load_bool(slot: Pointer) -> bool:
    return ctypes.c_bool.from_address(slot.address).value


@native_operation("memory.store")
def store_bool(slot: Pointer, value: bool) -> None:
    ctypes.c_bool.from_address(slot.address).value = value


@llvm.inline("load double, ptr {slot}")
def load_float(slot: Pointer) -> float:
    return ctypes.c_double.from_address(slot.address).value


@native_operation("memory.sort.addresses")
def sort_addresses(values: Pointer, count: int) -> None:
    array = (ctypes.c_void_p * count).from_address(values.address)
    array[:] = sorted(array, key=lambda address: address or 0)


@native_operation("memory.trace")
def trace_reference(function: Pointer, payload: Pointer, index: int) -> Pointer:
    # Private descriptor ABI: generated accessors only. The caller guarantees
    # no allocation, collection, Python callback, or exception during tracing.
    callback = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    return Pointer(callback(function.address)(payload.address, index) or 0)


@native_operation("memory.invoke")
def invoke_checked(function: Pointer, arena: Pointer, heap: Pointer,
                   exception: Pointer, first: Pointer, second: Pointer) -> int:
    # Unlike tracing, this private callback may collect or fail. Its caller
    # roots in-flight values and passes the current call's exception context.
    callback = ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_void_p] * 5))
    return callback(function.address)(arena.address, heap.address, exception.address,
                                      first.address, second.address)


@llvm.inline("getelementptr i8, ptr {value}, i64 {offset}")
def byte_offset(value: Pointer, offset: int) -> Pointer:
    return Pointer(value.address + offset)


@llvm.inline("load ptr, ptr {slot}")
def load_pointer(slot: Pointer) -> Pointer:
    return Pointer(ctypes.c_void_p.from_address(slot.address).value or 0)


@native_operation("memory.store")
def store_pointer(slot: Pointer, value: Pointer) -> None:
    ctypes.c_void_p.from_address(slot.address).value = value.address


@llvm.inline("load i64, ptr {slot}")
def load_integer(slot: Pointer) -> int:
    return ctypes.c_int64.from_address(slot.address).value


@llvm.inline("{value}")
def borrow_bytes(value: Pointer) -> bytes:
    # Native headers borrow storage without allocation; CPython copies because
    # its bytes representation differs. The caller owns the header's lifetime.
    return ctypes.string_at(load_pointer(pointer_slot(value, 1)).address, load_integer(value))


@native_operation("memory.store")
def store_integer(slot: Pointer, value: int) -> None:
    ctypes.c_int64.from_address(slot.address).value = value


@native_operation("memory.store")
def store_float(slot: Pointer, value: float) -> None:
    ctypes.c_double.from_address(slot.address).value = value


@native_operation("memory.store")
def store_int8(slot: Pointer, value: int8) -> None:
    ctypes.c_int8.from_address(slot.address).value = value


@llvm.inline("load i8, ptr {slot}")
def load_int8(slot: Pointer) -> int8:
    return int8(ctypes.c_int8.from_address(slot.address).value)


@native_operation("memory.store")
def store_int32(slot: Pointer, value: int32) -> None:
    ctypes.c_int32.from_address(slot.address).value = value


@native_operation("memory.allocate")
def allocate(size: int) -> Pointer:
    return Pointer(_allocator().malloc(size) or 0)


@native_operation("memory.allocate.zeroed")
def allocate_zeroed(size: int) -> Pointer:
    return Pointer(_allocator().calloc(1, size) or 0)


@native_operation("memory.reallocate")
def reallocate(value: Pointer, size: int) -> Pointer:
    return Pointer(_allocator().realloc(value.address, size) or 0)


@native_operation("memory.free")
def free(value: Pointer) -> None:
    _allocator().free(value.address)


@native_operation("memory.copy")
def copy(destination: Pointer, source: Pointer, size: int) -> None:
    # memcpy, not memmove: the caller proves non-overlapping storage.
    ctypes.memmove(destination.address, source.address, size)


@native_operation("memory.move")
def move(destination: Pointer, source: Pointer, size: int) -> None:
    ctypes.memmove(destination.address, source.address, size)


@native_operation("memory.fill")
def fill(destination: Pointer, value: int8, size: int) -> None:
    ctypes.memset(destination.address, int(value), size)


@llvm.inline("load i32, ptr {slot}")
def load_int32(slot: Pointer) -> int32:
    return int32(ctypes.c_int32.from_address(slot.address).value)
