"""Run the same raw-memory algorithm scenarios in CPython and native code."""

import ctypes
import inspect

from pyjs import int8, int32
from pyjs.native.runtime.pointers import Pointer
from pyjs.tooling.llvm import LLVM


class String(ctypes.Structure):
    _fields_ = [("length", ctypes.c_int64), ("data", ctypes.c_void_p)]


def string(value):
    storage = ctypes.create_string_buffer(value)
    header = String(len(value), ctypes.addressof(storage))
    header.storage = storage
    return header


def runtime_library(request, tmp_path_factory, generate):
    if request.param is None:
        return None
    directory = tmp_path_factory.mktemp(request.fixturename)
    return ctypes.CDLL(str(LLVM().compile(
        generate(), directory, shared=True, optimize=request.param,
    )))


def runtime_functions(functions, library=None, prefix=""):
    if library is None:
        return lambda name, *arguments: functions[name](*arguments)
    types = {Pointer: ctypes.c_void_p, int: ctypes.c_int64, float: ctypes.c_double,
             int8: ctypes.c_int8, int32: ctypes.c_int32, bool: ctypes.c_bool, None: None,
             bytes: ctypes.c_void_p, str: ctypes.c_void_p}
    compiled = {}
    for name, implementation in functions.items():
        signature = inspect.signature(implementation)
        function = getattr(library, prefix + name)
        function.argtypes = [types[parameter.annotation] for parameter in signature.parameters.values()]
        function.restype = types[signature.return_annotation]
        compiled[name] = function

    def invoke(name, *arguments):
        function = compiled[name]
        storage = [string(arg.encode() if isinstance(arg, str) else arg)
                   if isinstance(arg, (str, bytes)) else arg for arg in arguments]
        result = function(*[arg.address if isinstance(arg, Pointer)
                            else ctypes.byref(arg) if isinstance(arg, String)
                            else arg for arg in storage])
        return Pointer(result or 0) if function.restype is ctypes.c_void_p else result

    return invoke
