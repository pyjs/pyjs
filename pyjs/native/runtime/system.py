"""Private host C-runtime leaves; runtime algorithms own retry policy."""

import ctypes
import sys
from functools import cache

from pyjs import int32
from pyjs.decorators import native_operation
from pyjs.native.platform import libc

from .pointers import Pointer


@cache
def _write_function():
    function = libc()._write if sys.platform == "win32" else libc().write
    function.argtypes = [ctypes.c_int32, ctypes.c_void_p,
                         ctypes.c_uint32 if sys.platform == "win32" else ctypes.c_size_t]
    function.restype = ctypes.c_int32 if sys.platform == "win32" else ctypes.c_int64
    return function


@cache
def _invalid_parameter_handler():
    callback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t)(lambda *args: None)
    setter = libc()._set_thread_local_invalid_parameter_handler
    setter.argtypes, setter.restype = [ctypes.c_void_p], ctypes.c_void_p
    return setter, callback


@native_operation("system.write")
def write(descriptor: int32, data: Pointer, size: int) -> int:
    if sys.platform == "win32":
        setter, callback = _invalid_parameter_handler()
        previous = setter(callback)
        try:
            return _write_function()(descriptor, data.address, min(size, 2147483647))
        finally:
            saved = ctypes.get_errno()
            setter(previous)
            ctypes.set_errno(saved)
    return _write_function()(descriptor, data.address, size)


@native_operation("system.errno")
def errno() -> int32:
    return int32(ctypes.get_errno())
