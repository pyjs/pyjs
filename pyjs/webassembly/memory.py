"""Portable reference behavior for direct WebAssembly linear memory."""

import struct

PAGE_BYTES = 65_536

_memory = bytearray(PAGE_BYTES)


def _check_range(offset: int, width: int) -> None:
    if offset < 0 or offset + width > len(_memory):
        raise IndexError("linear-memory access is outside the allocated pages")


def memory_byte_length() -> int:
    return len(_memory)


def grow_memory(pages: int) -> int:
    """Grow by WebAssembly pages and return the previous page count."""
    if pages < 0:
        return -1
    previous = len(_memory) // PAGE_BYTES
    _memory.extend(bytes(pages * PAGE_BYTES))
    return previous


def load_i32(offset: int) -> int:
    _check_range(offset, 4)
    return struct.unpack_from("<i", _memory, offset)[0]


def load_f32(offset: int) -> float:
    _check_range(offset, 4)
    return struct.unpack_from("<f", _memory, offset)[0]


def load_f64(offset: int) -> float:
    _check_range(offset, 8)
    return struct.unpack_from("<d", _memory, offset)[0]


def store_i32(offset: int, value: int) -> None:
    _check_range(offset, 4)
    wrapped = (value + 2**31) % 2**32 - 2**31
    struct.pack_into("<i", _memory, offset, wrapped)


def store_f32(offset: int, value: float) -> None:
    _check_range(offset, 4)
    struct.pack_into("<f", _memory, offset, value)


def store_f64(offset: int, value: float) -> None:
    _check_range(offset, 8)
    struct.pack_into("<d", _memory, offset, value)


def memory_bytes(offset: int = 0, length: int | None = None) -> bytes:
    """Read reference-runtime bytes for CPython tests and adapters."""
    end = len(_memory) if length is None else offset + length
    return bytes(_memory[offset:end])


def reset_memory() -> None:
    """Reset CPython reference state without changing its first page."""
    global _memory
    _memory = bytearray(PAGE_BYTES)
