"""Private i128 intermediates, not a public arbitrary-precision integer type.

Range lengths can exceed signed i64 even when every item fits. These scalar
leaves keep their algorithms in Python without allocating boxed big integers.
Callers establish division and narrowing bounds; operations wrap at 128 bits.
"""

import ctypes
import sys

from pyjs import int64, llvm
from pyjs.decorators import native_operation

from .pointers import Pointer


@native_operation("memory.wide.integer")
class WideInt:
    def __init__(self, value: int):
        self.value = ((value + (1 << 127)) & ((1 << 128) - 1)) - (1 << 127)


@llvm.inline("sext i64 {value} to i128")
def widen(value: int) -> WideInt:
    return WideInt(value)


@llvm.inline("zext i64 {value} to i128")
def widen_unsigned(value: int) -> WideInt:
    return WideInt(value & ((1 << 64) - 1))


@llvm.inline("trunc i128 {value} to i64")
def narrow(value: WideInt) -> int:
    return int(int64(value.value))


@llvm.inline("add i128 {left}, {right}")
def add(left: WideInt, right: WideInt) -> WideInt:
    return WideInt(left.value + right.value)


@llvm.inline("sub i128 {left}, {right}")
def subtract(left: WideInt, right: WideInt) -> WideInt:
    return WideInt(left.value - right.value)


@llvm.inline("mul i128 {left}, {right}")
def multiply(left: WideInt, right: WideInt) -> WideInt:
    return WideInt(left.value * right.value)


@llvm.inline("udiv i128 {left}, {right}")
def quotient(left: WideInt, right: WideInt) -> WideInt:
    # Like LLVM udiv, interpret the full bit pattern as unsigned. Callers must
    # establish a nonzero divisor, including after any wrapping arithmetic.
    mask = (1 << 128) - 1
    return WideInt((left.value & mask) // (right.value & mask))


@llvm.inline("urem i128 {left}, {right}")
def remainder(left: WideInt, right: WideInt) -> WideInt:
    mask = (1 << 128) - 1
    return WideInt((left.value & mask) % (right.value & mask))


@llvm.inline("shl i128 {value}, {count}")
def shift_left(value: WideInt, count: WideInt) -> WideInt:
    return WideInt(value.value << count.value)


@llvm.inline("icmp eq i128 {left}, {right}")
def equal(left: WideInt, right: WideInt) -> bool:
    return left.value == right.value


@llvm.inline("icmp slt i128 {left}, {right}")
def less(left: WideInt, right: WideInt) -> bool:
    return left.value < right.value


@llvm.inline("load i128, ptr {slot}, align 1")
def load(slot: Pointer) -> WideInt:
    return WideInt(int.from_bytes(ctypes.string_at(slot.address, 16), sys.byteorder, signed=True))


@native_operation("memory.store")
def store(slot: Pointer, value: WideInt) -> None:
    ctypes.memmove(slot.address, value.value.to_bytes(16, sys.byteorder, signed=True), 16)
