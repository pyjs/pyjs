"""Unicode table lookup and context-sensitive case conversion over UTF-8."""

import ctypes

from pyjs import int32

from .algorithms import _positive_quotient, _runtime, decode_utf8, encode_utf8_at
from .pointers import (
    Pointer,
    byte_offset,
    is_null,
    load_int32,
    load_integer,
    load_pointer,
    null,
)
from .text_operations import STRING_DATA_OFFSET, new_owned


class _Mapping(ctypes.Structure):
    _fields_ = [("keys", ctypes.c_void_p), ("offsets", ctypes.c_void_p),
                ("values", ctypes.c_void_p), ("count", ctypes.c_int64)]


class _Context(ctypes.Structure):
    _fields_ = [("lower", ctypes.c_void_p), ("cased", ctypes.c_void_p),
                ("cased_count", ctypes.c_int64), ("ignored", ctypes.c_void_p),
                ("ignored_count", ctypes.c_int64)]


OFFSETS = _Mapping.offsets.offset
VALUES = _Mapping.values.offset
COUNT = _Mapping.count.offset
CASED = _Context.cased.offset
CASED_COUNT = _Context.cased_count.offset
IGNORED = _Context.ignored.offset
IGNORED_COUNT = _Context.ignored_count.offset


@_runtime
def lookup(mapping: Pointer, codepoint: int32) -> int:
    keys = load_pointer(mapping)
    low = 0
    high = load_integer(byte_offset(mapping, COUNT))
    while low < high:
        middle = low + _positive_quotient(high - low, 2)
        key = load_int32(byte_offset(keys, middle * 4))
        if codepoint < key:
            high = middle
        elif codepoint == key:
            return middle
        else:
            low = middle + 1
    return -1


@_runtime
def in_ranges(codepoint: int32, ranges: Pointer, count: int) -> bool:
    index = 0
    while index < count:
        start = load_int32(byte_offset(ranges, index * 8))
        stop = load_int32(byte_offset(ranges, index * 8 + 4))
        if codepoint >= start and codepoint <= stop:
            return True
        index += 1
    return False


@_runtime
def cased_in_span(data: Pointer, start: int, stop: int, last: bool, context: Pointer) -> bool:
    ignored = load_pointer(byte_offset(context, IGNORED))
    ignored_count = load_integer(byte_offset(context, IGNORED_COUNT))
    cased = load_pointer(byte_offset(context, CASED))
    cased_count = load_integer(byte_offset(context, CASED_COUNT))
    state = False
    offset = start
    while offset < stop:
        decoded = decode_utf8(data, offset)
        codepoint = int32(_positive_quotient(decoded, 8))
        if not in_ranges(codepoint, ignored, ignored_count):
            state = in_ranges(codepoint, cased, cased_count)
            if not last:
                return state
        offset += decoded & 7
    return state


@_runtime
def sigma(data: Pointer, length: int, offset: int, following: int, context: Pointer) -> int32:
    before = cased_in_span(data, 0, offset, True, context)
    after = cased_in_span(data, following, length, False, context)
    return int32(962 if before and not after else 963)


@_runtime
def write_mapping(target: Pointer, offset: int, codepoint: int32, mapping: Pointer) -> int:
    index = lookup(mapping, codepoint)
    if index < 0:
        return offset + encode_utf8_at(target, offset, codepoint)
    offsets = load_pointer(byte_offset(mapping, OFFSETS))
    values = load_pointer(byte_offset(mapping, VALUES))
    start = index
    stop = index + 1
    if not is_null(offsets):
        start = int(load_int32(byte_offset(offsets, index * 4)))
        stop = int(load_int32(byte_offset(offsets, (index + 1) * 4)))
    while start < stop:
        mapped = load_int32(byte_offset(values, start * 4))
        offset += encode_utf8_at(target, offset, mapped)
        start += 1
    return offset


@_runtime
def write_case(value: Pointer, target: Pointer, mapping: Pointer, context: Pointer, mode: int) -> int:
    # Modes: lower, table-only (upper/fold), swap, title, capitalize.
    # Inputs and tables are immutable. A null target measures the same walk.
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    length = load_integer(value)
    offset = 0
    output = 0
    previous_cased = False
    while offset < length:
        decoded = decode_utf8(data, offset)
        codepoint = int32(_positive_quotient(decoded, 8))
        following = offset + (decoded & 7)
        lower = mode == 0 or (mode == 3 and previous_cased) or (mode == 4 and offset > 0)
        if lower and codepoint == int32(304):
            output += encode_utf8_at(target, output, int32(105))
            output += encode_utf8_at(target, output, int32(775))
        elif (lower or mode == 2) and codepoint == int32(931):
            output += encode_utf8_at(target, output, sigma(data, length, offset, following, context))
        else:
            selected = load_pointer(context) if lower else mapping
            output = write_mapping(target, output, codepoint, selected)
        if mode == 3:
            previous_cased = in_ranges(codepoint, load_pointer(byte_offset(context, CASED)),
                                      load_integer(byte_offset(context, CASED_COUNT)))
        offset = following
    return output


@_runtime
def change_case(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
                mapping: Pointer, context: Pointer, mode: int) -> Pointer:
    # Every supported Unicode mapping expands by at most three bytes per
    # input byte. Bound the measurement before walking caller-owned storage.
    length = load_integer(value)
    if length < 0 or length > 3074457345618258602:
        return null()
    size = write_case(value, null(), mapping, context, mode)
    result = new_owned(arena, allocator, owner, size)
    if is_null(result):
        return null()
    write_case(value, load_pointer(byte_offset(result, STRING_DATA_OFFSET)), mapping, context, mode)
    return result


@_runtime
def all_in_ranges(value: Pointer, ranges: Pointer, count: int) -> bool:
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    length = load_integer(value)
    offset = 0
    while offset < length:
        decoded = decode_utf8(data, offset)
        if not in_ranges(int32(_positive_quotient(decoded, 8)), ranges, count):
            return False
        offset += decoded & 7
    return length > 0


@_runtime
def cased_in_ranges(value: Pointer, ranges: Pointer, count: int, context: Pointer) -> bool:
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    length = load_integer(value)
    cased = load_pointer(byte_offset(context, CASED))
    cased_count = load_integer(byte_offset(context, CASED_COUNT))
    offset = 0
    found = False
    while offset < length:
        decoded = decode_utf8(data, offset)
        codepoint = int32(_positive_quotient(decoded, 8))
        if in_ranges(codepoint, cased, cased_count):
            if not in_ranges(codepoint, ranges, count):
                return False
            found = True
        offset += decoded & 7
    return found


@_runtime
def is_identifier(value: Pointer, start: Pointer, start_count: int, following: Pointer, following_count: int) -> bool:
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    length = load_integer(value)
    offset = 0
    while offset < length:
        decoded = decode_utf8(data, offset)
        ranges = start if offset == 0 else following
        count = start_count if offset == 0 else following_count
        if not in_ranges(int32(_positive_quotient(decoded, 8)), ranges, count):
            return False
        offset += decoded & 7
    return length > 0


@_runtime
def is_title(value: Pointer, title: Pointer, title_count: int, lower: Pointer, lower_count: int, context: Pointer) -> bool:
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    length = load_integer(value)
    cased_ranges = load_pointer(byte_offset(context, CASED))
    cased_count = load_integer(byte_offset(context, CASED_COUNT))
    offset = 0
    found = False
    previous_cased = False
    while offset < length:
        decoded = decode_utf8(data, offset)
        codepoint = int32(_positive_quotient(decoded, 8))
        cased = in_ranges(codepoint, cased_ranges, cased_count)
        if cased:
            ranges = lower if previous_cased else title
            count = lower_count if previous_cased else title_count
            if not in_ranges(codepoint, ranges, count):
                return False
            found = True
        previous_cased = cased
        offset += decoded & 7
    return found
