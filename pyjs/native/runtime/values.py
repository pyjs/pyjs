"""Unboxed equality for the native collection key subset."""

import ctypes

from pyjs import int8

from .algorithms import _runtime, bytes_equal
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    is_null,
    load_bool,
    load_float,
    load_integer,
    load_pointer,
    same_address,
    trap,
)


class _OptionalBool(ctypes.Structure):
    _fields_ = [("present", ctypes.c_bool), ("value", ctypes.c_bool)]


class _OptionalInt(ctypes.Structure):
    _fields_ = [("present", ctypes.c_bool), ("value", ctypes.c_int64)]


class _OptionalFloat(ctypes.Structure):
    _fields_ = [("present", ctypes.c_bool), ("value", ctypes.c_double)]


BOOL_VALUE = _OptionalBool.value.offset
INT_VALUE = _OptionalInt.value.offset
FLOAT_VALUE = _OptionalFloat.value.offset


@_runtime
def key_equal(left: Pointer, right: Pointer, kind: int8) -> bool:
    if kind == int8(1):
        return load_bool(left) == load_bool(right)
    if kind == int8(2):
        return load_integer(left) == load_integer(right)
    if kind == int8(9):
        return load_float(left) == load_float(right)
    if kind == int8(3) or kind == int8(4):
        first = load_pointer(left)
        second = load_pointer(right)
        if same_address(first, second):
            return True
        if is_null(first) or is_null(second):
            return False
        return bytes_equal(borrow_bytes(first), borrow_bytes(second))
    if kind == int8(5) or kind == int8(6) or kind == int8(10):
        present = load_bool(left)
        if present != load_bool(right):
            return False
        if not present:
            return True
        if kind == int8(5):
            return load_bool(byte_offset(left, BOOL_VALUE)) == load_bool(byte_offset(right, BOOL_VALUE))
        if kind == int8(10):
            return load_float(byte_offset(left, FLOAT_VALUE)) == load_float(byte_offset(right, FLOAT_VALUE))
        return load_integer(byte_offset(left, INT_VALUE)) == load_integer(byte_offset(right, INT_VALUE))
    trap()
    return False
