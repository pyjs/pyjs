import ctypes
import subprocess
import sys
import textwrap
from itertools import product

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import arena, text_edit, text_extra
from pyjs.native.runtime.pointers import Pointer, null
from pyjs.native.runtime.sequences import _List
from pyjs.native.runtime.text import BYTE_WHITESPACE
from pyjs.native.runtime.text_split import split
from tests.native.runtime_support import (
    String,
    runtime_functions,
    runtime_library,
    string,
)


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def text_library(request, tmp_path_factory):
    return runtime_library(request, tmp_path_factory, lambda: transpile_llvm(
        'def main() -> str: return b"".split()[0].hex()',
    ))


@pytest.fixture(scope="module")
def text_runtime(text_library):
    operations = {"pyjs.text." + name: getattr(text_extra, name) for name in (
        "hex_bytes", "repr_bytes", "partition", "remove_affix", "splitlines",
        "pad", "zfill", "expandtabs", "get_byte",
    )}
    operations.update({"pyjs.string." + name: getattr(text_edit, name) for name in (
        "search", "replace", "trim", "slice_text",
    )})
    operations["pyjs.string.slice"] = operations.pop("pyjs.string.slice_text")
    operations["pyjs.string.split"] = split
    return runtime_functions(operations, text_library)


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
    return ctypes.string_at(header.data, header.length)


def read_list(value):
    header = _List.from_address(value.address)
    items = (ctypes.c_void_p * header.length).from_address(header.items)
    return [read(Pointer(address)) for address in items]


def test_binary_search_and_slices_preserve_arbitrary_bytes(text_runtime, owner):
    bounds = (-9223372036854775808, -9, -1, 0, 1, 4, 9, 9223372036854775807)
    for value in (b"", b"aaaa", b"\xff\xc3\xa9\0\x80"):
        source = string(value)
        for needle, start, stop in product((b"", b"a", b"aa", b"\xa9", b"\0"), bounds, bounds):
            pattern = string(needle)
            for mode, operation in enumerate((bytes.find, bytes.rfind, bytes.count, bytes.startswith, bytes.endswith)):
                actual = text_runtime("pyjs.string.search", pointer(source), pointer(pattern), start, stop, mode, True)
                assert actual == operation(value, needle, start, stop), (value, needle, start, stop, mode)
        for start, stop, step in product((None, *bounds), (None, *bounds), (-9223372036854775808, -2, -1, 1, 3, 9223372036854775807)):
            actual = text_runtime("pyjs.string.slice", *owner, pointer(source), start or 0,
                                  start is not None, stop or 0, stop is not None, step, True)
            assert read(actual) == value[start:stop:step], (value, start, stop, step)


def test_byte_repr_and_hex_cover_every_byte_and_quote_choice(text_runtime, owner):
    for value in (b"", bytes(range(256)), b"a'b", b'a"b', b"a'\"b", b"\\\t\r\n"):
        source = string(value)
        assert read(text_runtime("pyjs.text.hex_bytes", *owner, pointer(source))).decode() == value.hex()
        assert read(text_runtime("pyjs.text.repr_bytes", *owner, pointer(source))).decode() == repr(value)
        for index in range(-len(value), len(value)):
            assert text_runtime("pyjs.text.get_byte", pointer(source), index) == value[index]


def test_text_writers_preserve_foreign_owner_guards_and_unused_capacity(text_runtime):
    storage = []

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        assert context == 123
        data = ctypes.create_string_buffer(b"!" * (size + 16))
        storage.append((data, size))
        return ctypes.addressof(data) + 8

    owner = null(), Pointer(ctypes.cast(allocate, ctypes.c_void_p).value), Pointer(123)

    def check(name, arguments, expected):
        storage.clear()
        result = text_runtime("pyjs.text." + name, *owner, *arguments)
        assert len(storage) == 1  # Immutable header and payload share ownership.
        data, size = storage[0]
        assert result.address == ctypes.addressof(data) + 8
        header = String.from_address(result.address)
        assert header.data == result.address + ctypes.sizeof(String)
        assert read(result) == expected
        written = ctypes.sizeof(String) + len(expected)
        assert data.raw[:8] == b"!" * 8
        assert data.raw[8 + written:] == b"!" * (size - written + 8) + b"\0"

    for prefix, byte in product((b"", b"'", b'"', b"'\""), range(256)):
        value = prefix + bytes([byte])
        source = string(value)
        check("repr_bytes", (pointer(source),), repr(value).encode())
        check("hex_bytes", (pointer(source),), value.hex().encode())
    for value, fill, width in product(("", "é🙂", "é", "+", "-猫", "\0"), (" ", "😀", "\0"), (0, 3, 4, 7)):
        source, character = string(value.encode()), string(fill.encode())
        for alignment, method in enumerate((str.ljust, str.rjust, str.center)):
            check("pad", (pointer(source), width, pointer(character), alignment), method(value, width, fill).encode())
        check("zfill", (pointer(source), width), value.zfill(width).encode())


def test_splitlines_does_not_consume_trailing_storage_outside_logical_input(text_runtime, owner):
    source = string(b"\r\n")
    source.length = 1
    for binary, keepends in product((False, True), repeat=2):
        result = text_runtime("pyjs.text.splitlines", *owner, pointer(source), keepends, binary)
        assert read_list(result) == ([b"\r"] if keepends else [b""])


def test_binary_splitting_trimming_and_replacement(text_runtime, owner):
    for value in (b"", b" \xff \xc3\xa9\t", b"a::b::", b"aaaa", b"\x85\x1c\0"):
        source = string(value)
        for separator, maximum, reverse in product((None, b"a", b"::", b"\xff"), (-1, 0, 1, 5), (False, True)):
            delimiter = string(BYTE_WHITESPACE if separator is None else separator)
            actual = text_runtime("pyjs.string.split", *owner, pointer(source), pointer(delimiter),
                                  maximum, reverse, separator is None, True)
            expected = (value.rsplit if reverse else value.split)(separator, maximum)
            assert read_list(actual) == expected, (value, separator, maximum, reverse)
        for characters in (b"", b" \xff", BYTE_WHITESPACE):
            choices = string(characters)
            for left, right, operation in ((True, True, bytes.strip), (True, False, bytes.lstrip), (False, True, bytes.rstrip)):
                actual = text_runtime("pyjs.string.trim", *owner, pointer(source), pointer(choices), left, right, True)
                assert read(actual) == operation(value, characters)
        for old, new, count in product((b"", b"a", b"\xff"), (b"", b"\0\x80"), (-1, 0, 1, 9)):
            before, after = string(old), string(new)
            actual = text_runtime("pyjs.string.replace", *owner, pointer(source), pointer(before), pointer(after), count, True)
            assert read(actual) == value.replace(old, new, count)


def test_partition_and_affix_boundaries(text_runtime, owner):
    for value, separator, reverse in product((b"", b"ababa", b"\xff\0\xff"), (b"aba", b"x", b"\xff"), (False, True)):
        source, pattern = string(value), string(separator)
        actual = text_runtime("pyjs.text.partition", *owner, pointer(source), pointer(pattern), reverse)
        header = _List.from_address(actual.address)
        assert header.length == 3
        parts = (ctypes.c_void_p * 3).from_address(header.items)
        assert tuple(read(Pointer(address)) for address in parts) == (value.rpartition if reverse else value.partition)(separator)
        removed = text_runtime("pyjs.text.remove_affix", *owner, pointer(source), pointer(pattern), reverse)
        assert read(removed) == (value.removesuffix if reverse else value.removeprefix)(separator)
    source, pattern = string(b"ab"), string(b"")
    for reverse in (False, True):
        assert read(text_runtime("pyjs.text.remove_affix", *owner, pointer(source), pointer(pattern), reverse)) == b"ab"


def test_unicode_padding_and_tab_columns(text_runtime, owner):
    for value in ("", "a", "ab", "é😀", "é", "-é", "+", "\0"):
        source = string(value.encode())
        for width in (-9223372036854775808, -1, 0, 1, 2, 3, 4, 5, 9):
            assert read(text_runtime("pyjs.text.zfill", *owner, pointer(source), width)).decode() == value.zfill(width)
            for character in (" ", "😀", "é", "\0"):
                fillchar = string(character.encode())
                for mode, operation in enumerate((str.ljust, str.rjust, str.center)):
                    actual = text_runtime("pyjs.text.pad", *owner, pointer(source), width, pointer(fillchar), mode)
                    assert read(actual).decode() == operation(value, width, character)
    for value, size in product(("", "é\t😀\t", "a\t\r\n\tb", "a\v\tb", "\t\t"), (-1, 0, 1, 2, 4, 8)):
        source = string(value.encode())
        assert read(text_runtime("pyjs.text.expandtabs", *owner, pointer(source), size)).decode() == value.expandtabs(size)


def test_all_line_boundaries_and_trailing_empty_rules(text_runtime, owner):
    for value in ("", "a", "\n", "\r\n\r", "a\n\nb\n", "é\v\f\x1c\x1d\x1e\x85\u2028\u2029😀"):
        source = string(value.encode())
        for keepends, binary in product((False, True), repeat=2):
            actual = text_runtime("pyjs.text.splitlines", *owner, pointer(source), keepends, binary)
            expected = value.encode().splitlines(keepends) if binary else [part.encode() for part in value.splitlines(keepends)]
            assert read_list(actual) == expected


def test_expansion_overflow_is_rejected_before_allocation(text_runtime):
    allocations = []

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        allocations.append(size)
        return None

    owner = (null(), Pointer(ctypes.cast(allocate, ctypes.c_void_p).value), null())
    maximum = 9223372036854775807
    source, fillchar, tabs = string("é".encode()), string("😀".encode()), string(b"\t\t")
    single_tab = string(b"\t")
    cases = (
        ("pad", pointer(source), maximum, pointer(fillchar), 2),
        ("zfill", pointer(source), maximum),
        ("expandtabs", pointer(tabs), maximum),
        # Payload fits signed i64, but payload plus the immutable header does not.
        ("expandtabs", pointer(single_tab), maximum),
    )
    for operation, *arguments in cases:
        assert text_runtime("pyjs.text." + operation, *owner, *arguments).address == 0
    assert allocations == []


def test_invalid_pointer_overflow_probe_without_resource_or_fork(text_library):
    # A fresh interpreter contains bad dereferences without inheriting ctypes
    # callbacks or requiring fork. Blocking both imports also checks that this
    # module remains collectable when Unix-only facilities are unavailable.
    library_path = text_library._name if text_library is not None else None
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(f'''
        import sys
        sys.modules["resource"] = None
        sys.modules["multiprocessing"] = None

        from tests.native.test_python_text_bytes import (
            ctypes, text_extra, Pointer, null, pointer, String, runtime_functions,
        )

        path = {library_path!r}
        library = ctypes.CDLL(path) if path is not None else None
        invoke = runtime_functions({{
            "pyjs.text.hex_bytes": text_extra.hex_bytes,
            "pyjs.text.repr_bytes": text_extra.repr_bytes,
        }}, library)
        allocations = []

        @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
        def allocate(context, size):
            allocations.append(size)
            return None

        owner = null(), Pointer(ctypes.cast(allocate, ctypes.c_void_p).value), null()
        # Include a multiplication that fits but overflows after adding the
        # output header. Neither case may dereference data or call an allocator.
        for length in (9223372036854775807, 4611686018427387903):
            huge = String(length, None)
            for operation in ("hex_bytes", "repr_bytes"):
                assert invoke("pyjs.text." + operation, *owner, pointer(huge)).address == 0
        assert allocations == []
    ''')], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
