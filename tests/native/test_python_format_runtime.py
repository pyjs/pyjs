"""Run formatting kernels unchanged in CPython, LLVM O0 and LLVM O2."""

import ctypes

import pytest

from pyjs import int32
from pyjs.native import gc_layouts
from pyjs.native.runtime import arena, buffers, memory, output, text, text_format
from pyjs.native.runtime.pointers import Pointer
from tests.native.runtime_support import runtime_functions, runtime_library, string


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def runtime(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join([
        "declare void @llvm.trap()",
        "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)",
        "declare i32 @snprintf(ptr, i64, ptr, ...)",
        "%pyjs.string = type { i64, ptr }",
        *memory.arena_runtime(), *output.write_all_runtime(), *output.output_runtime(),
        *text.compiled_owned_text_runtime(), *text_format.compiled_runtime(),
        *gc_layouts.scalar_allocator(False),
    ]))
    return runtime_functions({"pyjs.format.pad": text_format.pad,
                              "pyjs.format.integer": text_format.integer,
                              "pyjs.format.float": text_format.floating,
                              "pyjs.format.ascii": text_format.ascii_repr,
                              "pyjs.format.join": text_format.join,
                              "pyjs.native.output.try.new": buffers.new_output,
                              "pyjs.native.output.try.finish.memory": buffers.finish_memory}, library)


@pytest.fixture
def owner():
    state = arena._Arena()
    pointer = Pointer(ctypes.addressof(state))
    try:
        yield pointer
    finally:
        arena.destroy_arena(pointer)


def read(value):
    assert value.address
    from tests.native.runtime_support import String
    header = String.from_address(value.address)
    return ctypes.string_at(header.data, header.length).decode()


def ptr(header):
    return Pointer(ctypes.addressof(header))


def test_integer_radices(runtime, owner):
    null = Pointer(0)
    for value in [0, 1, -1, 9, 15, -16, 255, 1024, -9223372036854775808, 9223372036854775807]:
        for code, base in [("b", 2), ("o", 8), ("d", 10), ("x", 16), ("X", 16)]:
            for sign in ["", "+", " "]:
                for alternate in [False, True]:
                    result = runtime("pyjs.format.integer", owner, null, null, value, base,
                                     ord(sign) if sign else 0, alternate, code == "X")
                    assert read(result) == format(value, sign + ("#" if alternate else "") + code)


def test_floating_conversion(runtime, owner):
    null = Pointer(0)
    for value in [0.0, -0.0, 1.25, -2.675, 1e-307, 1e308, float("inf"), float("-nan")]:
        for code in ["e", "E", "f", "F", "g", "G"]:
            for precision in [0, 2, 9]:
                for sign in ["", "+", " "]:
                    specification = ctypes.create_string_buffer(("%" + sign + ".*" + code).encode())
                    result = runtime("pyjs.format.float", owner, null, null, value,
                                     ptr(specification), int32(precision))
                    assert read(result) == format(value, sign + f".{precision}" + code)


def test_unicode_padding_and_truncation(runtime, owner):
    null = Pointer(0)
    for value in ["", "ASCII", "é中😀", "e\u0301", "line\nnext", "\x00hidden"]:
        source = string(value.encode())
        for fill in [" ", "0", "é", "😀", "\x00"]:
            token = string(fill.encode())
            for alignment in "<>^":
                for precision in [-1, 0, 1, 4]:
                    for width in [0, 2, 12]:
                        result = runtime("pyjs.format.pad", owner, null, null, ptr(source), ptr(token), width, precision, ord(alignment))
                        spec = fill + alignment + str(width) + (f".{precision}" if precision >= 0 else "") + "s"
                        assert read(result) == format(value, spec)
    for value in [-42, 0, 100]:
        for code in ["d", "b", "o", "x", "X"]:
            source = string(format(value, "+#" + code).encode())
            token = string(b"0")
            result = runtime("pyjs.format.pad", owner, null, null, ptr(source), ptr(token), 20, -1, ord("="))
            assert read(result) == format(value, "+#020" + code)


def test_ascii_escaping_and_join(runtime, owner):
    null = Pointer(0)
    for value in ["", "plain", "quote'", "é中😀", "\x00\n\u2028\U0010ffff"]:
        source = string(repr(value).encode())
        target = runtime("pyjs.native.output.try.new", owner, int32(-1))
        runtime("pyjs.format.ascii", target, ptr(source))
        assert read(runtime("pyjs.native.output.try.finish.memory", target)) == ascii(value)
    parts = [string(part.encode()) for part in ["hello", "", "é中😀", "\x00", "end"]]
    array = (ctypes.c_void_p * len(parts))(*(ctypes.addressof(part) for part in parts))
    assert read(runtime("pyjs.format.join", owner, null, null, Pointer(ctypes.addressof(array)), len(parts))) == "helloé中😀\x00end"
    assert read(runtime("pyjs.format.join", owner, null, null, null, 0)) == ""


def test_checked_sizing_rejects_before_payload_access(runtime, owner):
    from tests.native.runtime_support import String
    null = Pointer(0)
    source, fill = string(b"x"), string("😀".encode())
    assert runtime("pyjs.format.pad", owner, null, null, ptr(source), ptr(fill), 9223372036854775807, -1, ord(">")).address == 0
    # These fabricated headers exercise addition overflow without touching an
    # invalid payload or trying a giant allocation.
    parts = [String(9223372036854775807, 0), String(1, 0)]
    array = (ctypes.c_void_p * 2)(*(ctypes.addressof(part) for part in parts))
    assert runtime("pyjs.format.join", owner, null, null, Pointer(ctypes.addressof(array)), 2).address == 0
