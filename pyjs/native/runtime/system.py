"""Private Linux system-call leaves; runtime algorithms own retry policy."""

import ctypes
from functools import cache

from pyjs import int32
from pyjs.decorators import native_operation

from .pointers import Pointer


@cache
def _library():
    library = ctypes.CDLL(None, use_errno=True)
    library.write.argtypes = [ctypes.c_int32, ctypes.c_void_p, ctypes.c_size_t]
    library.write.restype = ctypes.c_int64
    return library


@native_operation("system.write")
def write(descriptor: int32, data: Pointer, size: int) -> int:
    return _library().write(descriptor, data.address, size)


@native_operation("system.errno")
def errno() -> int32:
    return int32(ctypes.get_errno())
