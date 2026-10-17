"""Measured text writes over borrowed, caller-owned storage."""

from .algorithms import (
    _byte_at,
    _bytes_match_at,
    _positive_quotient,
    _runtime,
    character_in,
    character_width,
    contains_byte,
    previous_start,
)
from .pointers import (
    Pointer,
    borrow_bytes,
    byte_offset,
    copy,
    load_integer,
    load_pointer,
    pointer_slot,
)
from .sequences import ITEMS_OFFSET
from .text_operations import STRING_DATA_OFFSET


@_runtime
def repeat_bytes(target: Pointer, source: Pointer, length: int, count: int) -> None:
    if length == 0:
        return
    index = 0
    while index < count:
        copy(byte_offset(target, index * length), source, length)
        index += 1


@_runtime
def scan_characters(
    value: Pointer, characters: Pointer, start: int, end: int,
    reverse: bool, binary: bool, member: bool,
) -> int:
    # Bounds are normalized byte offsets, and Unicode bounds are code-point
    # boundaries. Return the unconsumed edge; no decoding of binary payloads.
    source = borrow_bytes(value)
    choices = borrow_bytes(characters)
    while start < end:
        if reverse:
            offset = end - 1 if binary else previous_start(source, end)
        else:
            offset = start
        found = contains_byte(choices, _byte_at(source, offset)) if binary else character_in(source, offset, choices)
        if found != member:
            break
        if reverse:
            end = offset
        else:
            start += 1 if binary else character_width(source, offset)
    return end if reverse else start


@_runtime
def join_size(separator: Pointer, values: Pointer) -> int:
    count = load_integer(values)
    separator_length = load_integer(separator)
    if count < 0 or separator_length < 0:
        return -1
    total = 0
    if count > 1:
        if separator_length > _positive_quotient(9223372036854775807, count - 1):
            return -1
        total = separator_length * (count - 1)
    items = load_pointer(byte_offset(values, ITEMS_OFFSET))
    index = 0
    while index < count:
        length = load_integer(load_pointer(pointer_slot(items, index)))
        if length < 0 or length > 9223372036854775807 - total:
            return -1
        total += length
        index += 1
    return total


@_runtime
def join_copy(result: Pointer, separator: Pointer, values: Pointer) -> None:
    # The allocation boundary measured and reserved the complete result first.
    # No callback or collection may mutate inputs between measuring and copying.
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    separator_data = load_pointer(byte_offset(separator, STRING_DATA_OFFSET))
    separator_length = load_integer(separator)
    items = load_pointer(byte_offset(values, ITEMS_OFFSET))
    count = load_integer(values)
    index = 0
    offset = 0
    while index < count:
        if index:
            copy(byte_offset(target, offset), separator_data, separator_length)
            offset += separator_length
        item = load_pointer(pointer_slot(items, index))
        length = load_integer(item)
        copy(byte_offset(target, offset), load_pointer(byte_offset(item, STRING_DATA_OFFSET)), length)
        offset += length
        index += 1


@_runtime
def replacement_size(length: int, old_length: int, new_length: int, matches: int) -> int:
    if length < 0 or old_length < 0 or new_length < 0 or matches < 0:
        return -1
    # Non-overlapping matches cannot remove more than the source contains.
    # Subtract before adding, so shrinking replacements near i64 max work too.
    if old_length > 0 and matches > _positive_quotient(length, old_length):
        return -1
    remaining = length - matches * old_length
    if new_length > 0 and matches > _positive_quotient(9223372036854775807 - remaining, new_length):
        return -1
    return remaining + matches * new_length


@_runtime
def replacement_copy(
    result: Pointer, value: Pointer, old: Pointer, new: Pointer, matches: int, binary: bool,
) -> None:
    # The caller reserves the measured result; all input headers/data stay live
    # and immutable until copying ends. No callbacks or GC points occur here.
    length = load_integer(value)
    old_length = load_integer(old)
    new_length = load_integer(new)
    source_data = load_pointer(byte_offset(value, STRING_DATA_OFFSET))
    new_data = load_pointer(byte_offset(new, STRING_DATA_OFFSET))
    target = load_pointer(byte_offset(result, STRING_DATA_OFFSET))
    source = borrow_bytes(value)
    pattern = borrow_bytes(old)
    offset = 0
    copied = 0
    written = 0
    if old_length == 0:
        # str inserts between UTF-8 code points; bytes inserts between raw
        # bytes, including malformed or partial UTF-8 sequences.
        while matches > 0:
            if new_length:
                copy(byte_offset(target, written), new_data, new_length)
                written += new_length
            matches -= 1
            if offset == length:
                break
            width = 1 if binary else character_width(source, offset)
            copy(byte_offset(target, written), byte_offset(source_data, offset), width)
            offset += width
            written += width
        copied = offset
    else:
        while matches > 0 and offset <= length - old_length:
            if _bytes_match_at(source, pattern, offset, old_length):
                span = offset - copied
                if span:
                    copy(byte_offset(target, written), byte_offset(source_data, copied), span)
                    written += span
                if new_length:
                    copy(byte_offset(target, written), new_data, new_length)
                    written += new_length
                offset += old_length
                copied = offset
                matches -= 1
            else:
                offset += 1
    if copied < length:
        copy(byte_offset(target, written), byte_offset(source_data, copied), length - copied)
