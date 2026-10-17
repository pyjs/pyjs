"""Type ancestry and truthiness over explicit erased-object layouts."""

import ctypes
from functools import cache

from .algorithms import _runtime
from .pointers import (
    Pointer,
    byte_offset,
    is_null,
    load_float,
    load_integer,
    load_pointer,
    null,
    same_address,
)


class _Type(ctypes.Structure):
    _fields_ = [("parent", ctypes.c_void_p)]


class _Scalar(ctypes.Structure):
    _fields_ = [("type", ctypes.c_void_p), ("value", ctypes.c_int64)]


class _Reference(ctypes.Structure):
    _fields_ = [("type", ctypes.c_void_p), ("value", ctypes.c_void_p),
                ("length", ctypes.c_int64), ("tag", ctypes.c_int64)]


POINTER_SIZE = ctypes.sizeof(ctypes.c_void_p)
VALUE_OFFSET = _Scalar.value.offset
REFERENCE_OFFSET = _Reference.value.offset
LENGTH_OFFSET = _Reference.length.offset


@_runtime
def contains_type(value: Pointer, types: Pointer, count: int) -> bool:
    index = 0
    while index < count:
        if same_address(value, load_pointer(byte_offset(types, index * POINTER_SIZE))):
            return True
        index += 1
    return False


@_runtime
def type_of(value: Pointer, types: Pointer, count: int) -> Pointer:
    if not is_null(value):
        actual = load_pointer(value)
        # Untagged headers can hold a length or another non-type pointer.
        # Only module-known type identities may be walked as ancestry nodes.
        if contains_type(actual, types, count):
            return actual
    return null()


@_runtime
def is_instance(value: Pointer, expected: Pointer, types: Pointer, count: int) -> bool:
    candidate = type_of(value, types, count)
    while not is_null(candidate):
        if same_address(candidate, expected):
            return True
        candidate = load_pointer(candidate)
    return False


@_runtime
def reference_value(value: Pointer, types: Pointer, count: int) -> Pointer:
    if not is_null(value) and contains_type(load_pointer(value), types, count):
        return load_pointer(byte_offset(value, REFERENCE_OFFSET))
    return value


@_runtime
def reference_truth(value: Pointer, types: Pointer, count: int) -> bool:
    unboxed = reference_value(value, types, count)
    if same_address(value, unboxed):
        return not is_null(value)
    fixed = load_integer(byte_offset(value, LENGTH_OFFSET))
    return fixed != 0 if fixed >= 0 else load_integer(unboxed) != 0


@_runtime
def scalar_truth(value: Pointer, boolean: Pointer, integer: Pointer, floating: Pointer,
                 references: Pointer, count: int) -> bool:
    if is_null(value):
        return False
    actual = load_pointer(value)
    if same_address(actual, boolean) or same_address(actual, integer):
        return load_integer(byte_offset(value, VALUE_OFFSET)) != 0
    if same_address(actual, floating):
        return load_float(byte_offset(value, VALUE_OFFSET)) != 0.0
    return reference_truth(value, references, count)


@_runtime
def callable_identity(value: Pointer, adapters: Pointer, count: int) -> Pointer:
    # Only convention adapters are transparent. Ordinary closure/bound-method
    # contexts have their own identity and must never be followed as descriptors.
    current = value
    while not is_null(current):
        if not contains_type(load_pointer(current), adapters, count):
            break
        current = load_pointer(byte_offset(current, POINTER_SIZE))
    return current


@cache
def compiled_callable_runtime() -> tuple[str, ...]:
    from .compiler import compile_runtime

    return compile_runtime({"pyjs.callable.identity.with.adapters": callable_identity})


@cache
def compiled_object_runtime() -> tuple[str, ...]:
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.runtime.typeof.with.types": type_of,
        "pyjs.runtime.isinstance.with.types": is_instance,
        "pyjs.object.reference.value.with.types": reference_value,
        "pyjs.object.reference.truth.with.types": reference_truth,
        "pyjs.object.scalar.truth.with.types": scalar_truth,
    })
