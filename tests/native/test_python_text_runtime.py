from itertools import product

import pytest

from pyjs.native.runtime.algorithms import (
    all_characters_in,
    bytes_equal,
    bytes_hash,
    bytes_less,
    character_in,
    character_width,
    codepoints_before,
    contains,
    contains_byte,
    count_byte,
    count_bytes,
    count_string,
    ends_with,
    find_bytes,
    find_bytes_between,
    find_string,
    is_ascii,
    previous_start,
    rfind_string,
    slice_bound,
    starts_with,
    string_length,
    valid_utf8,
)
from pyjs.native.runtime.compiler import compile_runtime
from tests.native.runtime_support import runtime_functions, runtime_library

OPERATIONS = {function.__name__: function for function in (
    all_characters_in, bytes_equal, bytes_hash, bytes_less, character_in,
    character_width, codepoints_before, contains, contains_byte, count_byte,
    count_bytes, count_string, ends_with, find_bytes, find_bytes_between,
    find_string, is_ascii, previous_start, rfind_string, slice_bound, starts_with,
    string_length, valid_utf8,
)}


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def text_runtime(request, tmp_path_factory):
    operations = {"pyjs.string.length" if name == "string_length" else name: function
                  for name, function in OPERATIONS.items()}
    def source():
        return "\n".join((
            "%pyjs.string = type { i64, ptr }",
            "declare i32 @memcmp(ptr, ptr, i64)",
            *compile_runtime(operations),
        ))
    library = runtime_library(request, tmp_path_factory, source)
    invoke = runtime_functions(operations, library)
    return lambda name, *args: invoke("pyjs.string.length" if name == "string_length" else name, *args)


def test_byte_count_python_oracle(text_runtime):
    for value in (b"", bytes(range(256)), b"\x00\xff\x00\xff\xff", b"abababa"):
        for item in range(256):
            assert text_runtime("count_byte", value, item) == value.count(item)
            assert text_runtime("contains_byte", value, item) == (item in value)


def test_slice_bounds_match_python_at_integer_edges(text_runtime):
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    for length, index, reverse in product(
        (0, 1, 5, maximum), (minimum, -6, -1, 0, 1, 6, maximum), (False, True),
    ):
        expected = slice(index, None, -1 if reverse else 1).indices(length)[0]
        assert text_runtime("slice_bound", length, index, reverse) == expected, (length, index, reverse)


def test_substring_python_algorithms_match_builtin_oracles(text_runtime):
    values = [bytes(items) for size in range(4) for items in product((0, 97, 255), repeat=size)]
    for value in values:
        for needle in values:
            assert text_runtime("find_bytes", value, needle, False) == value.find(needle)
            assert text_runtime("find_bytes", value, needle, True) == value.rfind(needle)
            assert text_runtime("count_bytes", value, needle) == value.count(needle)
            for start in range(len(value) + 1):
                for end in range(start, len(value) + 1):
                    assert text_runtime("find_bytes_between", value, needle, start, end, False) == value.find(needle, start, end)
                    assert text_runtime("find_bytes_between", value, needle, start, end, True) == value.rfind(needle, start, end)
    for value in ("", "é😀é", "éé", "\x00é\x00", "aaaa", "\u3000β"):
        for needle in ("", "é", "😀", "é", "\x00", "aa", "absent"):
            assert text_runtime("count_string", value, needle) == value.count(needle)


def test_text_runtime_python_oracles(text_runtime):
    words = ("", "a", "aa", "é😀é", "éé", "\x00é\x00", "\u3000β", "\U0010ffff")
    for word in words:
        value = word.encode()
        assert text_runtime("string_length", value) == len(word)
        assert text_runtime("is_ascii", value) == word.isascii()
        offset = 0
        for index, character in enumerate(word):
            size = len(character.encode())
            assert text_runtime("character_width", value, offset) == size
            assert text_runtime("codepoints_before", value, offset) == index
            assert text_runtime("previous_start", value, offset + size) == offset
            for characters in words:
                assert text_runtime("character_in", value, offset, characters.encode()) == (character in characters)
            offset += size
        for other in words:
            needle = other.encode()
            assert text_runtime("bytes_equal", value, needle) == (word == other)
            assert text_runtime("bytes_less", value, needle) == (word < other)
            assert text_runtime("starts_with", value, needle) == word.startswith(other)
            assert text_runtime("ends_with", value, needle) == word.endswith(other)
            assert text_runtime("contains", value, needle) == (other in word)
            assert text_runtime("find_string", value, needle) == word.find(other)
            assert text_runtime("rfind_string", value, needle) == word.rfind(other)
            assert text_runtime("all_characters_in", value, needle) == (bool(word) and all(c in other for c in word))
    for value in (b"", bytes(range(256)), b"\x00\xff" * 40):
        expected = 14695981039346656037
        for byte in value:
            expected = ((expected ^ byte) * 1099511628211) & ((1 << 64) - 1)
        if expected >= 1 << 63:
            expected -= 1 << 64
        assert text_runtime("bytes_hash", value) == (-2 if expected == -1 else expected)


def test_utf8_validation_python_oracle(text_runtime):
    # Exhaust all short inputs; then exercise long-sequence boundaries rather
    # than enumerate the much larger space of arbitrary four-byte strings.
    values = [bytes(items) for size in range(3) for items in product(range(256), repeat=size)]
    values.extend(bytes(items) for items in product(
        (0xDF, 0xE0, 0xED, 0xEF, 0xF0, 0xF4, 0xF5),
        (0x7F, 0x80, 0x8F, 0x90, 0x9F, 0xA0, 0xBF, 0xC0),
        (0x7F, 0x80, 0xBF, 0xC0), (0x7F, 0x80, 0xBF, 0xC0),
    ))
    for value in values:
        try:
            value.decode()
            expected = True
        except UnicodeDecodeError:
            expected = False
        assert text_runtime("valid_utf8", value) == expected, value
