"""Scalar runtime declarations analyzed without implicit managed state."""

from pyjs import int8, int32, int64, llvm
from pyjs.decorators import NativeDecoration, native_operation

from .pointers import Pointer, byte_offset, bytes_data, is_null, load_int8, store_int8


def _runtime(function):
    # Emission validates the body; the marker alone does not establish purity.
    function.__native__ = NativeDecoration(kind="runtime")
    return function


@llvm.inline("udiv i64 {numerator}, {denominator}")
def _positive_quotient(numerator: int, denominator: int) -> int:
    # Callers establish nonnegative operands and a nonzero divisor. Using the
    # primitive prevents bootstrapping back into the Python division runtime.
    return numerator // denominator


@native_operation("memory.byte_at")
def _byte_at(value: bytes, index: int) -> int:
    # Only used after the loop has proved a nonnegative, in-range index.
    return value[index]


@_runtime
def count_byte(value: bytes, item: int) -> int:
    count = 0
    index = 0
    length = len(value)
    while index < length:
        count += int(_byte_at(value, index) == item)
        index += 1
    return count


@llvm.inline("{value}")
def _utf8_bytes(value: str) -> bytes:
    # Native str and bytes share an immutable UTF-8 buffer header. Borrow its
    # storage without allocating; the Python fallback supplies the same bytes.
    return value.encode("utf-8")


@native_operation("memory.compare_bytes")
def _compare_bytes(left: bytes, right: bytes, start: int, other: int, size: int) -> int:
    # Callers prove both nonempty spans fit before reaching this leaf.
    first = left[start:start + size]
    second = right[other:other + size]
    return (first > second) - (first < second)


@_runtime
def _bytes_match_at(value: bytes, needle: bytes, offset: int, size: int) -> bool:
    return _compare_bytes(value, needle, offset, 0, size) == 0


@_runtime
def find_bytes(value: bytes, needle: bytes, reverse: bool) -> int:
    return find_bytes_between(value, needle, 0, len(value), reverse)


@_runtime
def find_bytes_between(value: bytes, needle: bytes, start: int, end: int, reverse: bool) -> int:
    # Callers supply 0 <= start <= end <= len(value), not Python slice indices.
    size = len(needle)
    if size == 0:
        return end if reverse else start
    limit = end - size
    offset = limit if reverse else start
    while offset >= start and offset <= limit:
        if _bytes_match_at(value, needle, offset, size):
            return offset
        if reverse:
            offset -= 1
        else:
            offset += 1
    return -1


@_runtime
def contains_byte(value: bytes, item: int) -> bool:
    index = 0
    while index < len(value):
        if _byte_at(value, index) == item:
            return True
        index += 1
    return False


@_runtime
def count_bytes(value: bytes, needle: bytes) -> int:
    length = len(value)
    size = len(needle)
    if size == 0:
        return length + 1
    limit = length - size
    offset = 0
    count = 0
    while offset <= limit:
        if _bytes_match_at(value, needle, offset, size):
            count += 1
            offset += size
        else:
            offset += 1
    return count


@_runtime
def count_string(value: str, needle: str) -> int:
    pattern = _utf8_bytes(needle)
    if len(pattern) == 0:
        return len(value) + 1
    return count_bytes(_utf8_bytes(value), pattern)


@_runtime
def bytes_equal(left: bytes, right: bytes) -> bool:
    size = len(left)
    if size != len(right):
        return False
    return size == 0 or _compare_bytes(left, right, 0, 0, size) == 0


@_runtime
def bytes_less(left: bytes, right: bytes) -> bool:
    size = len(left) if len(left) < len(right) else len(right)
    ordering = _compare_bytes(left, right, 0, 0, size) if size else 0
    return ordering < 0 or (ordering == 0 and len(left) < len(right))


@_runtime
def bytes_bool(value: bytes) -> bool:
    return len(value) != 0


@_runtime
def bytes_hash(value: bytes) -> int:
    # FNV-1a uses the existing runtime's signed-i64 contract, not Python's
    # randomized host hash. -1 remains reserved by the mapping runtime.
    result = -3750763034362895579
    index = 0
    while index < len(value):
        result = int(int64((result ^ _byte_at(value, index)) * 1099511628211))
        index += 1
    return -2 if result == -1 else result


@_runtime
def is_continuation(value: int) -> bool:
    return value & 192 == 128


@_runtime
def codepoints_before(value: bytes, limit: int) -> int:
    # The caller supplies a byte bound within valid UTF-8 storage.
    index = 0
    count = 0
    while index < limit:
        count += int(not is_continuation(_byte_at(value, index)))
        index += 1
    return count


@_runtime
def string_length(value: bytes) -> int:
    return codepoints_before(value, len(value))


@_runtime
def character_width(value: bytes, offset: int) -> int:
    # Offset is a character boundary in validated UTF-8, never the end.
    return prefix_width(_byte_at(value, offset))


@_runtime
def prefix_width(first: int) -> int:
    if first < 128:
        return 1
    if first & 224 == 192:
        return 2
    return 3 if first & 240 == 224 else 4


@_runtime
def codepoint_at(value: bytes, offset: int) -> int:
    return _positive_quotient(decode_utf8(bytes_data(value), offset), 8)


@_runtime
def decode_utf8(data: Pointer, offset: int) -> int:
    # Pack the code point and width into one scalar. The caller has already
    # established valid UTF-8 bounds.
    first = int(load_int8(byte_offset(data, offset))) & 255
    width = prefix_width(first)
    if width == 1:
        return first * 8 + 1
    result = first & (31 if width == 2 else 15 if width == 3 else 7)
    index = 1
    while index < width:
        result = result * 64 + (int(load_int8(byte_offset(data, offset + index))) & 63)
        index += 1
    return result * 8 + width


@_runtime
def encode_utf8(target: Pointer, codepoint: int32) -> int:
    value = int(codepoint)
    if value < 128:
        store_int8(target, int8(value))
        return 1
    width = 2 if value < 2048 else 3 if value < 65536 else 4
    divisor = 64 if width == 2 else 4096 if width == 3 else 262144
    prefix = 192 if width == 2 else 224 if width == 3 else 240
    store_int8(target, int8(_positive_quotient(value, divisor) | prefix))
    index = 1
    while index < width:
        divisor = _positive_quotient(divisor, 64)
        byte = (_positive_quotient(value, divisor) & 63) | 128
        store_int8(byte_offset(target, index), int8(byte))
        index += 1
    return width


@_runtime
def encode_utf8_at(target: Pointer, offset: int, codepoint: int32) -> int:
    if is_null(target):
        return 1 if codepoint < int32(128) else 2 if codepoint < int32(2048) else 3 if codepoint < int32(65536) else 4
    return encode_utf8(byte_offset(target, offset), codepoint)


@_runtime
def previous_start(value: bytes, end: int) -> int:
    # End is a nonzero character boundary in valid UTF-8.
    index = end - 1
    while is_continuation(_byte_at(value, index)):
        index -= 1
    return index


@_runtime
def character_in(value: bytes, offset: int, characters: bytes) -> bool:
    size = character_width(value, offset)
    index = 0
    while index < len(characters):
        width = character_width(characters, index)
        if size == width and _compare_bytes(value, characters, offset, index, size) == 0:
            return True
        index += width
    return False


@_runtime
def all_characters_in(value: bytes, characters: bytes) -> bool:
    if len(value) == 0:
        return False
    offset = 0
    while offset < len(value):
        if not character_in(value, offset, characters):
            return False
        offset += character_width(value, offset)
    return True


@_runtime
def is_ascii(value: bytes) -> bool:
    index = 0
    while index < len(value):
        if _byte_at(value, index) >= 128:
            return False
        index += 1
    return True


@_runtime
def starts_with(value: bytes, prefix: bytes) -> bool:
    size = len(prefix)
    return size == 0 or (size <= len(value) and _bytes_match_at(value, prefix, 0, size))


@_runtime
def ends_with(value: bytes, suffix: bytes) -> bool:
    size = len(suffix)
    return size == 0 or (size <= len(value) and _bytes_match_at(value, suffix, len(value) - size, size))


@_runtime
def contains(value: bytes, needle: bytes) -> bool:
    return find_bytes(value, needle, False) >= 0


@_runtime
def find_string(value: bytes, needle: bytes) -> int:
    offset = find_bytes(value, needle, False)
    return codepoints_before(value, offset) if offset >= 0 else -1


@_runtime
def rfind_string(value: bytes, needle: bytes) -> int:
    offset = find_bytes(value, needle, True)
    return codepoints_before(value, offset) if offset >= 0 else -1


@_runtime
def valid_utf8(value: bytes) -> bool:
    index = 0
    length = len(value)
    while index < length:
        first = _byte_at(value, index)
        if first < 128:
            index += 1
            continue
        if first >= 194 and first <= 223:
            width = 2
        elif first >= 224 and first <= 239:
            width = 3
        elif first >= 240 and first <= 244:
            width = 4
        else:
            return False
        if length - index < width:
            return False
        second = _byte_at(value, index + 1)
        # Exclude overlong encodings, surrogate code points, and values above
        # U+10FFFF before consuming any remaining continuation bytes.
        if first == 224 and second < 160:
            return False
        if first == 237 and second >= 160:
            return False
        if first == 240 and second < 144:
            return False
        if first == 244 and second >= 144:
            return False
        following = index + 1
        end = index + width
        while following < end:
            if not is_continuation(_byte_at(value, following)):
                return False
            following += 1
        index = end
    return True


@_runtime
def slice_bound(length: int, index: int, reverse: bool) -> int:
    lower = -1 if reverse else 0
    upper = length - 1 if reverse else length
    if index < 0:
        index += length
    if index < lower:
        return lower
    return upper if index > upper else index
