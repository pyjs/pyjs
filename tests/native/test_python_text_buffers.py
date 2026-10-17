"""Measured writes and signed-size boundaries below allocating text kernels."""

import ctypes
from itertools import product

import pytest

from pyjs.native.runtime import sequences, text_buffers, text_extra
from pyjs.native.runtime.compiler import compile_runtime
from pyjs.native.runtime.pointers import Pointer
from tests.native.runtime_support import (
    String,
    runtime_functions,
    runtime_library,
    string,
)


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def buffer_runtime(request, tmp_path_factory):
    operations = {"test." + name: getattr(text_buffers, name) for name in (
        "join_size", "join_copy", "replacement_size", "replacement_copy",
        "scan_characters", "repeat_bytes",
    )}
    operations.update({"test.append_capacity": sequences.append_capacity,
                       "test.growth_capacity": sequences.growth_capacity,
                       "test.write_tabs": text_extra.write_tabs})
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join([
        "%pyjs.string = type { i64, ptr }",
        "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)",
        "declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)",
        "declare i32 @memcmp(ptr, ptr, i64)",
        *compile_runtime(operations),
    ]))
    return runtime_functions(operations, library)


def pointer(value):
    return Pointer(ctypes.addressof(value))


def guarded_result(expected):
    storage = ctypes.create_string_buffer(b"!" * (len(expected) + 16))
    header = String(len(expected), ctypes.addressof(storage) + 8)
    return storage, header


def test_measurement_rejects_overflow_without_reading_payloads(buffer_runtime):
    maximum = (1 << 63) - 1
    for separator_length, lengths, expected in (
        (0, [maximum, 1], -1), (maximum, [0, 0, 0], -1),
        (maximum, [0, 0], maximum), (0, [-1], -1),
        (0, [maximum - 1, 1], maximum), (-1, [], -1),
    ):
        # Intentionally null payloads: only lengths may be inspected here.
        separator = String(separator_length, None)
        headers = [String(length, None) for length in lengths]
        items = (ctypes.c_void_p * len(headers))(*(ctypes.addressof(value) for value in headers))
        values = sequences._List(len(headers), len(headers), ctypes.addressof(items))
        assert buffer_runtime("test.join_size", pointer(separator), pointer(values)) == expected
    invalid = sequences._List(-1, -1, None)
    empty = String(0, None)
    assert buffer_runtime("test.join_size", pointer(empty), pointer(invalid)) == -1
    for length, old, new, matches in product((-1, 0, 1, 2, maximum // 2, maximum), repeat=4):
        total = length + matches * (new - old)
        valid = min(length, old, new, matches) >= 0 and old * matches <= length and total <= maximum
        assert buffer_runtime("test.replacement_size", length, old, new, matches) == (total if valid else -1)


def test_join_measurement_matches_exact_guarded_write(buffer_runtime):
    for separator, values in ((b"|", []), (b"|", [b""]), (b"", [b"abc", b"", b"def"]),
                              (b"\0\xff", [b"\0", b"", b"\xff"]),
                              ("雪".encode(), ["café".encode(), b"", "🙂".encode()])):
        sep = string(separator)
        headers = [string(value) for value in values]
        items = (ctypes.c_void_p * len(headers))(*(ctypes.addressof(value) for value in headers))
        collection = sequences._List(len(headers), len(headers), ctypes.addressof(items))
        expected = separator.join(values)
        assert buffer_runtime("test.join_size", pointer(sep), pointer(collection)) == len(expected)
        storage, target = guarded_result(expected)
        buffer_runtime("test.join_copy", pointer(target), pointer(sep), pointer(collection))
        assert storage.raw == b"!" * 8 + expected + b"!" * 8 + b"\0"


def test_replacement_measurement_matches_exact_guarded_write(buffer_runtime):
    for values, patterns, replacements in (
        (["", "aaaa", "é😀é\0é"], ["", "a", "aa", "é", "missing"], ["", "<>\0", "雪"]),
        ([b"", b"aaaa", b"\xff\xc3\xa9\0", bytes(range(256))], [b"", b"a", b"aa", b"\xa9"],
         [b"", b"<>\0", b"\xff"]),
    ):
        for value, old, new, limit in product(values, patterns, replacements, (-2, 0, 1, 2, 1000)):
            binary = isinstance(value, bytes)
            expected = value.replace(old, new, limit)
            if not binary:
                expected = expected.encode()
            matches = value.count(old)
            if limit >= 0:
                matches = min(matches, limit)
            headers = [string(item if binary else item.encode()) for item in (value, old, new)]
            measured = buffer_runtime("test.replacement_size", *(header.length for header in headers), matches)
            assert measured == len(expected), (value, old, new, limit)
            storage, target = guarded_result(expected)
            buffer_runtime("test.replacement_copy", pointer(target), *(pointer(header) for header in headers),
                           matches, binary)
            assert storage.raw == b"!" * 8 + expected + b"!" * 8 + b"\0", (value, old, new, limit)


def test_character_scans_stop_at_logical_boundaries(buffer_runtime):
    for values, sets in (
        (["", "aaaa", "é😀é", "é é", "\0 雪\u3000 "], ["", "a", "é😀", "é", "\0 \u3000"]),
        ([b"", b"aaaa", b"\xc3\xa9\xff\0\x80", bytes(range(256))], [b"", b"a", b"\xa9\xff"]),
    ):
        for value, characters in product(values, sets):
            binary = isinstance(value, bytes)
            headers = [string(item if binary else item.encode()) for item in (value, characters)]
            edges = sorted({0, min(1, len(value)), max(0, len(value) - 1), len(value)})
            for start, end, reverse, member in product(edges, edges, (False, True), (False, True)):
                if start > end:
                    continue
                window = value[start:end]
                consumed = 0
                for item in reversed(window) if reverse else window:
                    if (item in characters) != member:
                        break
                    consumed += 1
                expected = end - consumed if reverse else start + consumed
                if not binary:
                    start, end, expected = (len(value[:index].encode()) for index in (start, end, expected))
                assert buffer_runtime("test.scan_characters", *(pointer(header) for header in headers),
                                      start, end, reverse, binary, member) == expected


def test_repetition_preserves_guards_and_does_not_touch_zero_width_input(buffer_runtime):
    for value, count in product((b"", b"abc\0", b"\xff"), (0, 1, 7)):
        source = ctypes.create_string_buffer(value)
        expected = value * count
        storage, target = guarded_result(expected)
        buffer_runtime("test.repeat_bytes", Pointer(target.data), pointer(source), len(value), count)
        assert storage.raw == b"!" * 8 + expected + b"!" * 8 + b"\0"
    buffer_runtime("test.repeat_bytes", Pointer(0), Pointer(0), 0, (1 << 63) - 1)


def test_capacity_growth_checks_overflow_before_exact_size_fallback(buffer_runtime):
    maximum = (1 << 63) - 1
    for capacity, item_size in product((-1, 0, 1, 2, 4, 100, maximum // 2, maximum - 1, maximum),
                                      (-1, 0, 1, 8, maximum)):
        expected = -1
        if 0 <= capacity < maximum and item_size >= 0:
            preferred = max(4, capacity * 2)
            if preferred > maximum or preferred * item_size > maximum:
                preferred = capacity + 1
            if preferred * item_size <= maximum:
                expected = preferred
        assert buffer_runtime("test.append_capacity", capacity, item_size) == expected
    for capacity, required, expected in ((4096, 5000, 8192), (4096, 10000, 10000),
                                          (maximum - 10, maximum - 1, maximum - 1), (maximum, -1, -1)):
        assert buffer_runtime("test.growth_capacity", capacity, required, 1, 0) == expected


def test_tab_measurement_matches_guarded_writes_and_checks_overflow(buffer_runtime):
    for value, tabsize in product(("", "plain", "é\t🙂", "é\tx\r\ny\t", "\t\t", "\0\t\v\t\r\t"),
                                  (-5, 0, 1, 2, 4, 8)):
        source = string(value.encode())
        expected = value.expandtabs(tabsize).encode()
        assert buffer_runtime("test.write_tabs", pointer(source), tabsize, Pointer(0)) == len(expected)
        storage, target = guarded_result(expected)
        assert buffer_runtime("test.write_tabs", pointer(source), tabsize, Pointer(target.data)) == len(expected)
        assert storage.raw == b"!" * 8 + expected + b"!" * 8 + b"\0"
    maximum = (1 << 63) - 1
    for value, expected in ((b"\t", maximum), (b"\tX", -1), (b"\t\t", -1), (b"\t\r", -1)):
        source = string(value)
        assert buffer_runtime("test.write_tabs", pointer(source), maximum, Pointer(0)) == expected
