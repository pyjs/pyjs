"""One raw form-encoding implementation under CPython and LLVM."""

import ctypes
from urllib.parse import quote_plus, urlencode

import pytest

from pyjs.native import gc_layouts
from pyjs.native.runtime import arena, memory, text, url
from pyjs.native.runtime.buffers import STRING_DATA_OFFSET
from pyjs.native.runtime.mappings import _Dict
from pyjs.native.runtime.pointers import Pointer
from tests.native.runtime_support import String, runtime_functions, runtime_library, string


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def runtime(request, tmp_path_factory):
    from pyjs.native.runtime.compiler import compile_runtime

    operations = {"query": url.encode_query, "size": url.component_size,
                  "copy": url.copy_component, "query_size": url.query_size}
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join([
        "declare void @llvm.trap()",
        "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)",
        "%pyjs.string = type { i64, ptr }",
        *memory.arena_runtime(), *text.compiled_owned_text_runtime(),
        *gc_layouts.scalar_allocator(False),
        *compile_runtime(operations, dependencies={
            "pyjs.string.new.owned": url.new_owned,
        }),
    ]))
    return runtime_functions(operations, library)


def test_all_ascii_and_unicode_components(runtime):
    characters = "".join(map(chr, range(128))) + "é雪😀é"
    for values in ({}, {"": ""}, {"a": characters}, {characters: characters, "last": "=+&% "}):
        keys = [string(key.encode()) for key in values]
        items = [string(value.encode()) for value in values.values()]
        key_storage = (ctypes.c_void_p * len(keys))(*(ctypes.addressof(key) for key in keys))
        value_storage = (ctypes.c_void_p * len(items))(*(ctypes.addressof(value) for value in items))
        mapping = _Dict(length=len(values), capacity=len(values), keys=ctypes.addressof(key_storage),
                        values=ctypes.addressof(value_storage))
        owner = arena._Arena()
        owner_pointer = Pointer(ctypes.addressof(owner))
        sizes = []

        @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
        def allocate(context, size):
            assert context == owner_pointer.address
            sizes.append(size)
            return arena.allocate_in_arena(owner_pointer, size, 8).address

        try:
            result = runtime("query", owner_pointer, Pointer(0), Pointer(0), Pointer(ctypes.addressof(mapping)))
            assert result.address
            count = ctypes.c_int64.from_address(result.address).value
            data = ctypes.c_void_p.from_address(result.address + STRING_DATA_OFFSET).value
            expected = urlencode(values).encode()
            assert count == len(expected)
            assert ctypes.string_at(data, count) == expected
            # The callback path must also make exactly one final-size allocation,
            # not retain a worst-case URL-encoding buffer or temporary key list.
            result = runtime("query", Pointer(0), Pointer(ctypes.cast(allocate, ctypes.c_void_p).value),
                             owner_pointer, Pointer(ctypes.addressof(mapping)))
            header = String.from_address(result.address)
            assert ctypes.string_at(header.data, header.length) == expected
            assert sizes == [ctypes.sizeof(String) + len(expected)]
        finally:
            arena.destroy_arena(owner_pointer)


def test_oversized_headers_reject_before_dereferencing(runtime):
    # Only a length exists. Invalid counts must reject before loading arrays
    # or allocating; no huge memory request or forged readable payload is needed.
    for count in (-1, 4611686018427387905, 9223372036854775807):
        header = ctypes.c_int64(count)
        result = runtime("query", Pointer(0), Pointer(0), Pointer(0), Pointer(ctypes.addressof(header)))
        assert not result.address
    header = ctypes.c_int64(100)
    assert runtime("size", Pointer(ctypes.addressof(header)), 99) == -1
    text = string("é".encode())
    pointer = Pointer(ctypes.addressof(text))
    assert runtime("size", pointer, 5) == -1
    assert runtime("size", pointer, 6) == 6


def test_component_writes_preserve_canaries_and_query_measurement_guards(runtime):
    for value in (b"", bytes(range(256)), b"AZaz09-._~ +&=%\0", "é雪🙂".encode()):
        header = string(value)
        argument = Pointer(ctypes.addressof(header))
        expected = quote_plus(value).encode()
        assert runtime("size", argument, len(expected)) == len(expected)
        assert runtime("size", argument, len(expected) - 1) == -1
        storage = ctypes.create_string_buffer(b"!" * (len(expected) + 16))
        assert runtime("copy", Pointer(ctypes.addressof(storage)), 8, argument) == len(expected) + 8
        assert storage.raw == b"!" * 8 + expected + b"!" * 8 + b"\0"

    maximum = (1 << 63) - 1
    for count in (-1, (1 << 62) + 1, maximum):
        assert runtime("query_size", count, Pointer(0), Pointer(0)) == -1
    assert runtime("query_size", 0, Pointer(0), Pointer(0)) == 0
    for length in (-1, maximum):
        header = String(length, None)
        assert runtime("size", Pointer(ctypes.addressof(header)), maximum - 1) == -1
    empty, huge = string(b""), String(maximum, None)
    for key, value in ((huge, empty), (empty, huge)):
        keys = (ctypes.c_void_p * 1)(ctypes.addressof(key))
        values = (ctypes.c_void_p * 1)(ctypes.addressof(value))
        assert runtime("query_size", 1, Pointer(ctypes.addressof(keys)), Pointer(ctypes.addressof(values))) == -1
