import ctypes
from itertools import product

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import arena, text_edit
from pyjs.native.runtime.pointers import Pointer, null
from pyjs.native.runtime.sequences import _List, new_list
from pyjs.native.runtime.text import WHITESPACE
from pyjs.native.runtime.text_split import split
from tests.native.runtime_support import (
    String,
    runtime_functions,
    runtime_library,
    string,
)


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def edit_runtime(request, tmp_path_factory):
    operations = {"pyjs.string." + name: getattr(text_edit, name) for name in
                  ("search", "affix", "repeat", "replace", "join", "trim")}
    operations.update({"pyjs.string.get.character": text_edit.get_character,
                       "pyjs.string.repeat.fits": text_edit.repeat_fits,
                       "pyjs.string.search.byte": text_edit.search_byte,
                       "pyjs.string.slice": text_edit.slice_text,
                       "pyjs.string.split": split, "pyjs.list.new.owned": new_list})
    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm('''
        def main() -> str:
            return "|".join(" ".split()).strip()[::1]
    '''))
    return runtime_functions(operations, library)


@pytest.fixture
def owner():
    state = arena._Arena()
    pointer = Pointer(ctypes.addressof(state))
    try:
        yield pointer, null(), null()
    finally:
        arena.destroy_arena(pointer)


def pointer(header):
    return Pointer(ctypes.addressof(header))


def read(value):
    header = String.from_address(value.address)
    return ctypes.string_at(header.data, header.length).decode()


def test_search_bounds_match_python_including_oversized_empty_matches(edit_runtime):
    bounds = (-9223372036854775808, -9, -1, 0, 1, 2, 5, 9, 9223372036854775807)
    for value, needle in product(("", "a", "aaaa", "é😀é", "é\0"), ("", "a", "aa", "é", "😀", "\0")):
        source, pattern = string(value.encode()), string(needle.encode())
        for start, stop in product(bounds, repeat=2):
            for mode, operation in enumerate((str.find, str.rfind, str.count, str.startswith, str.endswith)):
                actual = edit_runtime("pyjs.string.search", pointer(source), pointer(pattern), start, stop, mode, False)
                assert actual == operation(value, needle, start, stop), (value, needle, start, stop, mode)


def test_integer_byte_search_and_borrowed_affix_tuples(edit_runtime):
    bounds = (-9223372036854775808, -1, 0, 2, 9, 9223372036854775807)
    for value, needle in product((b"", b"\0\xff\x80\xff", b"abc"), (0, 97, 128, 255)):
        source = string(value)
        for start, stop in product(bounds, repeat=2):
            for mode, operation in enumerate((bytes.find, bytes.rfind, bytes.count)):
                assert edit_runtime("pyjs.string.search.byte", pointer(source), needle, start, stop, mode) == \
                    operation(value, needle, start, stop)
    for binary in (False, True):
        value = b"a\xff\0a" if binary else "aé\0😀"
        patterns = (b"no", b"a", b"") if binary else ("no", "é", "")
        source = string(value if binary else value.encode())
        headers = [string(item if binary else item.encode()) for item in patterns]
        items = (ctypes.c_void_p * len(headers))(*(ctypes.addressof(item) for item in headers))
        for count in range(len(headers) + 1):
            header = _List(count, count, ctypes.addressof(items))
            for start, stop in product(bounds, repeat=2):
                for mode, operation in ((3, value.startswith), (4, value.endswith)):
                    assert edit_runtime("pyjs.string.affix", pointer(source), pointer(header),
                                        start, stop, mode, binary) == operation(patterns[:count], start, stop)


def test_slices_and_indexes_match_python_with_extreme_steps(edit_runtime, owner):
    bounds = (None, -9223372036854775808, -7, -1, 0, 1, 4, 7, 9223372036854775807)
    for value in ("", "a", "é😀é\0z"):
        source = string(value.encode())
        for index in range(-len(value), len(value)):
            assert read(edit_runtime("pyjs.string.get.character", *owner, pointer(source), index)) == value[index]
        for start, stop, step in product(bounds, bounds, (-9223372036854775808, -3, -1, 1, 2, 9223372036854775807)):
            actual = edit_runtime("pyjs.string.slice", *owner, pointer(source), start or 0,
                                  start is not None, stop or 0, stop is not None, step, False)
            assert read(actual) == value[start:stop:step], (value, start, stop, step)


def test_trim_repeat_replace_match_python(edit_runtime, owner):
    for value in ("", "aaaa", "\0é😀é\0", " \u3000abc\x85\n", "éé"):
        source = string(value.encode())
        for count in (-2, 0, 1, 3):
            assert read(edit_runtime("pyjs.string.repeat", *owner, pointer(source), count)) == value * count
        for chars in ("", "a", "é\0", WHITESPACE):
            characters = string(chars.encode())
            for left, right, operation in ((True, True, str.strip), (True, False, str.lstrip), (False, True, str.rstrip)):
                actual = edit_runtime("pyjs.string.trim", *owner, pointer(source), pointer(characters), left, right, False)
                assert read(actual) == operation(value, chars)
        for old, new, count in product(("", "a", "aa", "é", "é"), ("", "😀x", "\0"), (-1, 0, 1, 8)):
            before, after = string(old.encode()), string(new.encode())
            actual = edit_runtime("pyjs.string.replace", *owner, pointer(source), pointer(before), pointer(after), count, False)
            assert read(actual) == value.replace(old, new, count), (value, old, new, count)


def test_repeat_overflow_uses_character_count_without_allocating(edit_runtime):
    maximum = (1 << 63) - 1
    for text in ("", "a", "ab", "é", "éé", "😀", "😀😀", "é\0"):
        source = string(text.encode())
        for count in (-(1 << 63), -1, 0, 1, maximum // 4, maximum // 2, maximum):
            for binary in (False, True):
                length = len(text.encode()) if binary else len(text)
                assert edit_runtime("pyjs.string.repeat.fits", pointer(source), count, binary) == (
                    length * max(0, count) <= maximum)


def test_split_and_join_match_python(edit_runtime, owner):
    for value, separator, maximum, reverse in product(
        ("", " ", " \u3000é😀  b\x85", "aaa", "a::b::", "\0é\0"),
        (None, "a", "aa", "::", "\0"), (-1, 0, 1, 2, 99), (False, True),
    ):
        source = string(value.encode())
        delimiter = string((WHITESPACE if separator is None else separator).encode())
        result = edit_runtime("pyjs.string.split", *owner, pointer(source), pointer(delimiter), maximum, reverse, separator is None, False)
        header = _List.from_address(result.address)
        items = (ctypes.c_void_p * header.length).from_address(header.items)
        actual = [read(Pointer(address)) for address in items]
        expected = (value.rsplit if reverse else value.split)(separator, maximum)
        assert actual == expected, (value, separator, maximum, reverse)
        joiner = string("|😀".encode())
        assert read(edit_runtime("pyjs.string.join", *owner, pointer(joiner), result)) == "|😀".join(expected)


def test_invalid_raw_list_and_slice_inputs_fail_before_allocation(owner):
    # Allocation shape failures return null; invalid raw slice strides retain
    # their precondition contract. The application checks strides before calls.
    for item_size, length in ((0, 0), (-1, 0), (8, -1), (8, 9223372036854775807)):
        assert new_list(*owner, item_size, length).address == 0
    value = string(b"a")
    with pytest.raises(RuntimeError, match="precondition"):
        text_edit.slice_text(*owner, pointer(value), 0, False, 0, False, 0, False)
