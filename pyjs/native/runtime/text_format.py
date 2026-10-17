"""Formatting policy in Python; raw pointers only at the text-storage boundary."""

from functools import cache

from pyjs import int8, int32

from .algorithms import _positive_quotient, _runtime, character_width, codepoint_at
from .buffers import ERROR_OFFSET, STRING_DATA_OFFSET, append_bytes
from .error_messages import write_hex
from .float_math import format_buffer
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    bytes_data,
    copy,
    is_null,
    load_int8,
    load_int32,
    load_integer,
    load_pointer,
    null,
    pointer_slot,
    stack_buffer,
    store_int8,
    store_integer,
)
from .text_operations import new_owned


@_runtime
def integer(arena: Pointer, allocator: Pointer, context: Pointer, value: int,
            base: int, sign: int, alternate: bool, uppercase: bool) -> Pointer:
    """Base conversion without negating INT64_MIN or delegating to printf."""
    negative = value < 0
    magnitude = -(value + 1) if negative else value
    carry = 1 if negative else 0
    scratch = stack_buffer(64)
    size = 0
    while True:
        quotient = _positive_quotient(magnitude, base)
        digit = magnitude - quotient * base + carry
        carry = 1 if digit == base else 0
        if carry != 0:
            digit = 0
        code = 48 + digit if digit < 10 else (65 if uppercase else 97) + digit - 10
        store_int8(byte_offset(scratch, size), int8(code))
        size += 1
        magnitude = quotient
        if magnitude == 0 and carry == 0:
            break
    prefix = 2 if alternate and base != 10 else 0
    signed = 1 if negative or sign != 0 else 0
    result = new_owned(arena, allocator, context, size + signed + prefix)
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    if signed != 0:
        store_int8(target, int8(45 if negative else sign))
    if prefix != 0:
        store_int8(byte_offset(target, signed), int8(48))
        marker = 98 if base == 2 else 111 if base == 8 else 88 if uppercase else 120
        store_int8(byte_offset(target, signed + 1), int8(marker))
    offset = signed + prefix
    while size > 0:
        size -= 1
        store_int8(byte_offset(target, offset), load_int8(byte_offset(scratch, size)))
        offset += 1
    return result


@_runtime
def join(arena: Pointer, allocator: Pointer, context: Pointer, parts: Pointer, count: int) -> Pointer:
    """Join already formatted, rooted fragments with one output allocation."""
    if count < 0:
        return null()
    size = 0
    index = 0
    while index < count:
        part = load_pointer(pointer_slot(parts, index))
        length = load_integer(part)
        if length < 0 or length > 9223372036854775807 - size:
            return null()
        size += length
        index += 1
    result = new_owned(arena, allocator, context, size)
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    offset = 0
    index = 0
    while index < count:
        part = load_pointer(pointer_slot(parts, index))
        length = load_integer(part)
        copy(byte_offset(target, offset), load_pointer(byte_offset(part, STRING_DATA_OFFSET)), length)
        offset += length
        index += 1
    return result


@_runtime
def pad(arena: Pointer, allocator: Pointer, context: Pointer, value: Pointer,
        fill: Pointer, width: int, precision: int, alignment: int) -> Pointer:
    """Width/precision count code points, while allocation counts UTF-8 bytes.

    Alignment is the ASCII code of <, >, ^ or =. Sign-aware padding only
    receives numeric ASCII output. Callers validate format syntax first.
    """
    source = borrow_bytes(value)
    characters = 0
    size = 0
    while size < len(source) and (precision < 0 or characters < precision):
        size += character_width(source, size)
        characters += 1
    padding = max(0, width - characters)
    fill_size = load_integer(fill)
    if fill_size < 1 or fill_size > 4:
        return null()
    if padding > _positive_quotient(9223372036854775807 - size, fill_size):
        return null()
    result = new_owned(arena, allocator, context, size + padding * fill_size)
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    token = load_pointer(byte_offset(fill, STRING_DATA_OFFSET))
    before = 0 if alignment == 60 else _positive_quotient(padding, 2) if alignment == 94 else padding
    sign = 0
    if alignment == 61 and size > 0:
        first = codepoint_at(source, 0)
        if first == 43 or first == 45 or first == 32:
            sign = 1
        if size >= sign + 2 and codepoint_at(source, sign) == 48:
            marker = codepoint_at(source, sign + 1)
            if marker == 98 or marker == 111 or marker == 120 or marker == 88:
                sign += 2
    copy(target, data, sign)
    offset = sign
    index = 0
    while index < before:
        copy(byte_offset(target, offset), token, fill_size)
        offset += fill_size
        index += 1
    copy(byte_offset(target, offset), byte_offset(data, sign), size - sign)
    offset += size - sign
    while index < padding:
        copy(byte_offset(target, offset), token, fill_size)
        offset += fill_size
        index += 1
    return result


@_runtime
def floating(arena: Pointer, allocator: Pointer, context: Pointer,
             value: float, specification: Pointer, precision: int32) -> Pointer:
    # snprintf's variadic ABI is the only C boundary; sizing, checked
    # allocation and the native string header remain ordinary runtime Python.
    if value != value:
        # libc differs on whether '+'/' ' applies to NaN (Darwin ignores it).
        # Python ignores the NaN sign bit but honors the requested sign and
        # letter case. Handle that policy here, identically on every host.
        sign = int8(0)
        uppercase = False
        percentage = False
        index = 0
        code = load_int8(specification)
        while code != int8(0):
            if code == int8(43) or code == int8(32):
                sign = code
            if code == int8(69) or code == int8(70) or code == int8(71):
                uppercase = True
            # Generated percent formats append the C literal escape '%%'.
            if index > 0 and code == int8(37):
                percentage = True
            index += 1
            code = load_int8(byte_offset(specification, index))
        prefix = 1 if sign != int8(0) else 0
        result = new_owned(arena, allocator, context, 3 + prefix + int(percentage))
        if is_null(result):
            return null()
        data = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
        if prefix:
            store_int8(data, sign)
        copy(byte_offset(data, prefix), bytes_data(b"NAN" if uppercase else b"nan"), 3)
        if percentage:
            store_int8(byte_offset(data, prefix + 3), int8(37))
        return result
    count = int(format_buffer(null(), 0, specification, precision, value))
    # The owned-string ABI has one failure sentinel: C formatter failures,
    # like allocation failures, become catchable MemoryError at the caller.
    if count < 0:
        return null()
    result = new_owned(arena, allocator, context, count + 1)
    if is_null(result):
        return null()
    data = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    written = int(format_buffer(data, count + 1, specification, precision, value))
    if written != count:
        return null()
    store_integer(result, count)
    return result


@_runtime
def ascii_repr(output: Pointer, value: Pointer) -> None:
    """ascii() escapes non-ASCII characters in repr(), not in the original value."""
    if load_int32(byte_offset(output, ERROR_OFFSET)) != int32(0):
        return
    source = borrow_bytes(value)
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    scratch = stack_buffer(10)
    index = 0
    start = 0
    while index < len(source):
        codepoint = codepoint_at(source, index)
        width = character_width(source, index)
        if codepoint >= 128:
            append_bytes(output, byte_offset(data, start), index - start)
            digits = 2 if codepoint < 256 else 4 if codepoint < 65536 else 8
            write_hex(scratch, codepoint, digits, int8(120 if digits == 2 else 117 if digits == 4 else 85))
            append_bytes(output, scratch, digits + 2)
            start = index + width
        index += width
    append_bytes(output, byte_offset(data, start), index - start)


@cache
def compiled_runtime(include_ascii=True, include_float=True):
    from .compiler import compile_runtime

    roots = {"pyjs.format.pad": pad, "pyjs.format.join": join,
             "pyjs.format.integer": integer}
    if include_float:
        roots["pyjs.format.float"] = floating
    if include_ascii:
        roots["pyjs.format.ascii"] = ascii_repr
    return compile_runtime(roots, dependencies={
        "pyjs.string.new.owned": new_owned,
        "pyjs.native.output.append.bytes": append_bytes,
    })
