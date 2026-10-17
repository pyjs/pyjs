import ctypes

import pytest

from pyjs import int32
from pyjs.native.runtime.algorithms import decode_utf8, encode_utf8, encode_utf8_at
from pyjs.native.runtime.pointers import Pointer
from pyjs.native.runtime.text import compiled_utf8_runtime
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def utf8_runtime(request, tmp_path_factory):
    operations = {"pyjs.utf8.decode.scalar": decode_utf8, "pyjs.utf8.encode": encode_utf8,
                  "pyjs.utf8.encode.at": encode_utf8_at}
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join(compiled_utf8_runtime()))
    return runtime_functions(operations, library)


def test_utf8_scalars_measure_decode_and_encode_with_guard_bytes(utf8_runtime):
    values = set(range(0, 0x110000, 997))
    for boundary in (0, 128, 2048, 0xD800, 0xE000, 65536, 0x110000):
        values.update(range(max(0, boundary - 4), min(0x110000, boundary + 4)))
    for value in sorted(values):
        if 0xD800 <= value <= 0xDFFF:
            continue
        expected = chr(value).encode()
        size = len(expected)
        assert utf8_runtime("pyjs.utf8.encode.at", Pointer(0), 123, int32(value)) == size
        source = ctypes.create_string_buffer(b"!" * 8 + expected + b"!" * 8)
        assert utf8_runtime("pyjs.utf8.decode.scalar", Pointer(ctypes.addressof(source)), 8) == value * 8 + size
        for offset in (0, 8):
            target = ctypes.create_string_buffer(b"!" * (size + 16))
            if offset:
                written = utf8_runtime("pyjs.utf8.encode.at", Pointer(ctypes.addressof(target)), offset, int32(value))
            else:
                written = utf8_runtime("pyjs.utf8.encode", Pointer(ctypes.addressof(target) + 8), int32(value))
            assert written == size
            assert target.raw == b"!" * 8 + expected + b"!" * 8 + b"\0"
