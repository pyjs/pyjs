"""UTF-8 editing with explicit allocation and no intermediate text objects."""

from .algorithms import (
    _byte_at,
    _bytes_match_at,
    _positive_quotient,
    _runtime,
    character_width,
    codepoints_before,
    count_bytes,
    find_bytes_between,
    previous_start,
    slice_bound,
    string_length,
)
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    copy,
    is_null,
    load_integer,
    load_pointer,
    null,
    trap,
)
from .sequences import ITEMS_OFFSET
from .text_buffers import (
    join_copy,
    join_size,
    repeat_bytes,
    replacement_copy,
    replacement_size,
    scan_characters,
)
from .text_operations import STRING_DATA_OFFSET, new_owned


@_runtime
def character_offset(value: bytes, index: int) -> int:
    offset = 0
    character = 0
    while character < index:
        offset += character_width(value, offset)
        character += 1
    return offset



@_runtime
def search(value: Pointer, needle: Pointer, start: int, stop: int, mode: int, binary: bool) -> int:
    # Modes: find, rfind, count, startswith, endswith. Unlike slicing, an
    # oversized positive start must not match even an empty substring.
    if mode >= 3:
        return _affix(value, needle, start, stop, mode, binary, False)
    source = borrow_bytes(value)
    pattern = borrow_bytes(needle)
    length = len(source) if binary else string_length(source)
    if start > length:
        return -1 if mode < 2 else 0
    first = slice_bound(length, start, False)
    last = slice_bound(length, stop, False)
    if first > last:
        return -1 if mode < 2 else 0
    begin = first if binary else character_offset(source, first)
    end = last if binary else character_offset(source, last)
    if mode == 2 and len(pattern) == 0:
        return last - first + 1
    offset = find_bytes_between(source, pattern, begin, end, mode == 1)
    if mode < 2:
        return offset if binary or offset < 0 else codepoints_before(source, offset)
    count = 0
    while offset >= 0:
        count += 1
        begin = offset + len(pattern)
        offset = find_bytes_between(source, pattern, begin, end, False)
    return count


@_runtime
def affix(value: Pointer, needles: Pointer, start: int, stop: int, mode: int, binary: bool) -> int:
    return _affix(value, needles, start, stop, mode, binary, True)


@_runtime
def _affix(value: Pointer, needles: Pointer, start: int, stop: int,
           mode: int, binary: bool, multiple: bool) -> int:
    # Only homogeneous text-pointer tuple storage reaches this helper. Borrow
    # that immutable array or the single needle, without staging an iterator.
    count = load_integer(needles) if multiple else 1
    if count == 0:
        return 0
    source = borrow_bytes(value)
    if start == 0 and stop == 9223372036854775807:
        # Default bounds need neither Unicode length nor character offsets.
        # Anchored comparisons cost only the candidate bytes, not the haystack.
        begin = 0
        end = len(source)
    else:
        length = len(source) if binary else string_length(source)
        if start > length:
            return 0
        first = slice_bound(length, start, False)
        last = slice_bound(length, stop, False)
        if first > last:
            return 0
        begin = first if binary else character_offset(source, first)
        end = last if binary else character_offset(source, last)
    items = load_pointer(byte_offset(needles, ITEMS_OFFSET)) if multiple else null()
    index = 0
    while index < count:
        needle = load_pointer(byte_offset(items, index * 8)) if multiple else needles
        pattern = borrow_bytes(needle)
        size = len(pattern)
        offset = begin if mode == 3 else end - size
        if size <= end - begin and (size == 0 or _bytes_match_at(source, pattern, offset, size)):
            return 1
        index += 1
    return 0


@_runtime
def search_byte(value: Pointer, needle: int, start: int, stop: int, mode: int) -> int:
    source = borrow_bytes(value)
    if start > len(source):
        return 0 if mode == 2 else -1
    first = slice_bound(len(source), start, False)
    last = slice_bound(len(source), stop, False)
    result = 0 if mode == 2 else -1
    offset = last - 1 if mode == 1 else first
    step = -1 if mode == 1 else 1
    while first <= offset < last:
        if _byte_at(source, offset) == needle:
            if mode != 2:
                return offset
            result += 1
        offset += step
    return result


@_runtime
def copy_span(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
              offset: int, length: int) -> Pointer:
    result = new_owned(arena, allocator, owner, length)
    if is_null(result):
        return null()
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    source = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    copy(target, byte_offset(source, offset), length)
    return result


@_runtime
def get_character(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer, index: int) -> Pointer:
    source = borrow_bytes(value)
    length = string_length(source)
    actual = index + length if index < 0 else index
    if actual < 0 or actual >= length:
        trap()
    offset = character_offset(source, actual)
    return copy_span(arena, allocator, owner, value, offset, character_width(source, offset))


@_runtime
def write_slice(value: Pointer, target: Pointer, first: int, stop: int, step: int, binary: bool) -> int:
    # A null target measures the identical traversal. Scan UTF-8 directly
    # rather than allocating an offset table for every slice.
    source = borrow_bytes(value)
    data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    reverse = step < 0
    if (reverse and first <= stop) or (not reverse and first >= stop):
        return 0
    edge = first + 1 if reverse else first
    offset = edge if binary else character_offset(source, edge)
    index = first
    skip = 0
    written = 0
    while (reverse and index > stop) or (not reverse and index < stop):
        if reverse:
            end = offset
            offset = offset - 1 if binary else previous_start(source, offset)
            width = end - offset
        else:
            width = 1 if binary else character_width(source, offset)
        if skip == 0:
            if not is_null(target):
                copy(byte_offset(target, written), byte_offset(data, offset), width)
            written += width
            # -(INT64_MIN + 1) fits; never negate the stride itself.
            skip = -(step + 1) if reverse else step - 1
        else:
            skip -= 1
        if reverse:
            index -= 1
        else:
            index += 1
            offset += width
    return written


@_runtime
def slice_text(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
               start: int, start_present: bool, stop: int, stop_present: bool, step: int, binary: bool) -> Pointer:
    if step == 0:
        trap()
    length = load_integer(value) if binary else string_length(borrow_bytes(value))
    reverse = step < 0
    first = slice_bound(length, start, reverse) if start_present else length - 1 if reverse else 0
    last = slice_bound(length, stop, reverse) if stop_present else -1 if reverse else length
    size = write_slice(value, null(), first, last, step, binary)
    result = new_owned(arena, allocator, owner, size)
    if is_null(result):
        return null()
    write_slice(value, load_pointer(byte_offset(result, STRING_DATA_OFFSET)), first, last, step, binary)
    return result


@_runtime
def repeat_fits(value: Pointer, count: int, binary: bool) -> bool:
    length = load_integer(value)
    if count <= 0 or length == 0:
        return True
    if length < 0:
        return False
    if count <= _positive_quotient(9223372036854775807, length):
        return True
    # Python measures string overflow in code points, not UTF-8 bytes. Scan
    # only when the byte count overflows; a fitting character count with an
    # unallocatable byte buffer remains MemoryError in repeat(), not overflow.
    if not binary:
        length = string_length(borrow_bytes(value))
    return length == 0 or count <= _positive_quotient(9223372036854775807, length)


@_runtime
def repeat(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer, count: int) -> Pointer:
    length = load_integer(value)
    if count <= 0 or length == 0:
        return new_owned(arena, allocator, owner, 0)
    if length < 0 or count > _positive_quotient(9223372036854775807, length):
        return null()
    result = new_owned(arena, allocator, owner, length * count)
    if is_null(result):
        return null()
    repeat_bytes(load_pointer(byte_offset(result, STRING_DATA_OFFSET)),
                 load_pointer(byte_offset(value, STRING_DATA_OFFSET)), length, count)
    return result


@_runtime
def join(arena: Pointer, allocator: Pointer, owner: Pointer, separator: Pointer, values: Pointer) -> Pointer:
    result = new_owned(arena, allocator, owner, join_size(separator, values))
    if is_null(result):
        return null()
    join_copy(result, separator, values)
    return result


@_runtime
def replace(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
            old: Pointer, new: Pointer, limit: int, binary: bool) -> Pointer:
    length = load_integer(value)
    old_length = load_integer(old)
    matches = count_bytes(borrow_bytes(value), borrow_bytes(old))
    if old_length == 0 and not binary:
        matches = string_length(borrow_bytes(value)) + 1
    if limit >= 0 and limit < matches:
        matches = limit
    size = replacement_size(length, old_length, load_integer(new), matches)
    result = new_owned(arena, allocator, owner, size)
    if is_null(result):
        return null()
    replacement_copy(result, value, old, new, matches, binary)
    return result


@_runtime
def trim(arena: Pointer, allocator: Pointer, owner: Pointer, value: Pointer,
         characters: Pointer, left: bool, right: bool, binary: bool) -> Pointer:
    length = load_integer(value)
    first = scan_characters(value, characters, 0, length if left else 0, False, binary, True)
    last = scan_characters(value, characters, first if right else length, length, True, binary, True)
    return copy_span(arena, allocator, owner, value, first, last - first)
