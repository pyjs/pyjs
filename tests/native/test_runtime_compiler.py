import ctypes
import sys

import pytest

from pyjs import float32, int8, int32
from pyjs.decorators import native_operation
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.native.runtime.algorithms import _byte_at, _runtime
from pyjs.native.runtime.compiler import compile_runtime
from pyjs.native.runtime.pointers import Pointer
from pyjs.native.runtime.wide import (
    add,
    load,
    multiply,
    narrow,
    store,
    widen,
    widen_unsigned,
)
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions


@_runtime
def _shared_increment(value: int32) -> int32:
    return value + int32(1)


@_runtime
def _provided_increment(value: int32) -> int32:
    return _shared_increment(value)


@_runtime
def _consumer_increment(value: int32) -> int32:
    return _provided_increment(value) + _shared_increment(value)


@_runtime
def _unsafe_provided(value: int) -> int:
    return len([value])


@_runtime
def _unsafe_consumer(value: int) -> int:
    return _unsafe_provided(value)


@_runtime
def _scaled_float(value: float32) -> float32:
    return value * float32(1.5)


@_runtime
def _float_consumer(value: float) -> float:
    return float(_scaled_float(float32(value))) + 0.25


@_runtime
def _wide_roundtrip(high: int, low: int, target: Pointer) -> int:
    base = add(widen_unsigned(-1), widen(1))
    value = add(multiply(widen(high), base), widen_unsigned(low))
    store(target, value)
    return narrow(load(target))


@pytest.mark.parametrize("optimize", [0, 2])
def test_private_wide_scalars_roundtrip_unaligned_storage_without_boxing(tmp_path, optimize):
    operations = {"roundtrip": _wide_roundtrip}
    source = "\n".join(compile_runtime(operations))
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    for runtime in (runtime_functions(operations), runtime_functions(operations, library)):
        for high in (-(1 << 63), -1, 0, (1 << 63) - 1):
            for low in (-(1 << 63), -1, 0, (1 << 63) - 1):
                storage = (ctypes.c_uint8 * 18)(*([77] * 18))
                assert runtime("roundtrip", high, low, Pointer(ctypes.addressof(storage) + 1)) == low
                expected = ((high & ((1 << 64) - 1)) << 64) | (low & ((1 << 64) - 1))
                assert bytes(storage) == b"M" + expected.to_bytes(16, sys.byteorder) + b"M"
    # The private scalar must not acquire a managed runtime ABI or box itself.
    assert "alloca i128" in source and "__heap" not in source and "__arena" not in source


@_runtime
def _clamp(value: int, low: int, high: int) -> int:
    return min(max(value, low), high)


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_extrema_remain_usable_without_managed_runtime(tmp_path, optimize):
    source = "\n".join(compile_runtime({"clamp": _clamp}))
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions({"clamp": _clamp}, library)
    for value in (-9223372036854775808, -3, 0, 7, 9223372036854775807):
        assert invoke("clamp", value, -3, 7) == _clamp(value, -3, 7)


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_float_abi_preserves_narrow_calls_and_returns(tmp_path, optimize):
    source = "\n".join(compile_runtime({"scaled": _scaled_float, "consumer": _float_consumer}))
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    library.scaled.argtypes, library.scaled.restype = [ctypes.c_float], ctypes.c_float
    library.consumer.argtypes, library.consumer.restype = [ctypes.c_double], ctypes.c_double
    for value in (-123456789.25, -0.0, 0.1, 1.0, 16777217.0):
        assert library.scaled(value) == _scaled_float(float32(value))
        assert library.consumer(value) == _float_consumer(value)
    assert "define float @scaled(float " in source
    assert "define double @consumer(double " in source


@native_operation("memory.invoke")
def _narrow_callback(callback: Pointer, small: int8, large: int32) -> int8:
    signature = ctypes.CFUNCTYPE(ctypes.c_int8, ctypes.c_int8, ctypes.c_int32)
    return int8(signature(callback.address)(int(small), int(large)))


@_runtime
def _invoke_narrow(callback: Pointer, value: int) -> int:
    return int(_narrow_callback(callback, int8(value), int32(value * 3)))


@pytest.mark.parametrize("optimize", [0, 2])
def test_raw_callbacks_preserve_argument_and_result_widths(tmp_path, optimize):
    operations = {"invoke": _invoke_narrow}
    source = "\n".join(compile_runtime(operations))
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    arguments = []

    @ctypes.CFUNCTYPE(ctypes.c_int8, ctypes.c_int8, ctypes.c_int32)
    def callback(small, large):
        arguments.append((small, large))
        return int(int8(small + large))

    pointer = Pointer(ctypes.cast(callback, ctypes.c_void_p).value)
    for runtime in (runtime_functions(operations), runtime_functions(operations, library)):
        for value in (-2147483648, -257, -128, -1, 0, 127, 128, 255, 2147483647):
            expected = int(int8(value)), int(int32(value * 3))
            assert runtime("invoke", pointer, value) == int(int8(sum(expected)))
            assert arguments[-1] == expected


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_libraries_link_portable_abis_and_isolate_private_helpers(tmp_path, optimize):
    first = compile_runtime({"provided": _provided_increment})
    second = compile_runtime({"consumer": _consumer_increment}, dependencies={"provided": _provided_increment})
    assert not any(line.startswith("define i32 @provided(") for line in second)
    assert any(line.startswith("define internal i32 @pyjs.runtime.") for line in second)
    library = ctypes.CDLL(str(LLVM().compile("\n".join((*first, *second)), tmp_path, shared=True, optimize=optimize)))
    consumer = library.consumer
    consumer.argtypes = [ctypes.c_int32]
    consumer.restype = ctypes.c_int32
    for value in (-2147483648, -1, 0, 2147483647):
        assert consumer(value) == _consumer_increment(int32(value))


def test_runtime_libraries_validate_dependency_bodies_and_linker_names():
    with pytest.raises(LLVMUnsupported, match="runtime helper"):
        compile_runtime({"consumer": _unsafe_consumer}, dependencies={"provided": _unsafe_provided})
    with pytest.raises(LLVMUnsupported, match="distinct symbols"):
        compile_runtime({"entry": _consumer_increment}, dependencies={"entry": _provided_increment})
    with pytest.raises(LLVMUnsupported, match="one linker symbol"):
        compile_runtime({"entry": _consumer_increment}, dependencies={"other": _consumer_increment})


def test_runtime_library_rejects_missing_roots():
    for roots in ({}, {"invalid": len}):
        with pytest.raises(LLVMUnsupported, match="runtime library roots"):
            compile_runtime(roots)
    # A failed private library compilation must release its analyzer roots.
    assert "define i64 @fn.pyjs_main()" in transpile_llvm("def main() -> int: return 7")


@_runtime
def _literal_length() -> int:
    return len("library storage")


@_runtime
def _other_literal_length() -> int:
    return len("independent")


@_runtime
def _literal_byte() -> int:
    return _byte_at(b"\xff\0", 0) + len(b"")


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_literal_libraries_link_without_symbol_collisions(tmp_path, optimize):
    first = compile_runtime({"first": _literal_length})
    second = compile_runtime({"second": _other_literal_length})
    third = compile_runtime({"byte": _literal_byte})
    source = transpile_llvm('def main() -> str: return "application"')
    library = ctypes.CDLL(str(LLVM().compile(
        source + "\n".join((*first, *second, *third)), tmp_path,
        shared=True, optimize=optimize,
    )))
    for name, expected in (("first", _literal_length()), ("second", _other_literal_length()),
                           ("byte", _literal_byte())):
        function = getattr(library, name)
        function.argtypes, function.restype = [], ctypes.c_int64
        assert function() == expected
    assert compile_runtime({"first": _literal_length}) == first


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_helpers_borrow_managed_bytes_without_managed_abi(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.native.runtime.algorithms import _runtime, count_byte
        @_runtime
        def score(value: bytes, *, item: int) -> int:
            return count_byte(value, item) * 2 + 1
        def main() -> str:
            gc_set_threshold(1)
            values: list[int] = []
            for size in range(8):
                data = bytes([255, 0]) * size
                gc_collect()
                values.append(score(data, item=255))
                gc_collect()
            return str(values)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
    # Inspect only the helper; its caller legitimately needs GC scaffolding.
    helper = result.native.llvm_ir.split("define i64 @fn.score(", 1)[1].split("\n}", 1)[0]
    assert helper.startswith("ptr %arg.value, i64 %arg.item) {")
    assert "@fn.pyjs.native.runtime.algorithms.count_byte(ptr " in helper
    assert all(marker not in helper for marker in ("__heap", "__arena", "__exception", "@pyjs.gc."))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind", ["int8", "uint8", "int16", "uint16", "int32", "uint32", "int64"])
def test_unmanaged_helpers_keep_portable_widths_inside_managed_callers(tmp_path, optimize, kind):
    result = LLVM().assert_matches_python(f'''
        from pyjs import {kind}
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.native.runtime.algorithms import _runtime
        @_runtime
        def increment(value: {kind}) -> {kind}:
            return value + {kind}(1)
        @_runtime
        def twice(value: {kind}) -> {kind}:
            return increment(value) * {kind}(2)
        def main() -> str:
            gc_set_threshold(1)
            result: list[int] = []
            for value in [-1, 0, 127, 65535, 2147483647, 9223372036854775807]:
                result.append(int(twice({kind}(value))))
                gc_collect()
            return str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("inline", ["call i64 @unvalidated(ptr {value})", "store i64 1, ptr {value}"])
def test_runtime_helper_validates_opaque_inline_effects(inline):
    with pytest.raises(LLVMUnsupported, match="runtime helper") as caught:
        transpile_llvm(f'''
            from pyjs import llvm
            from pyjs.native.runtime.algorithms import _runtime
            @llvm.inline({inline!r})
            def operation(value: bytes) -> {"None" if inline.startswith("store") else "int"}:
                pass
            @_runtime
            def helper(value: bytes) -> int:
                operation(value)
                return 0
            def main() -> int:
                return helper(b"abc")
        ''')
    assert caught.value.node.lineno is not None


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind,value", [("int", "4"), ("int8", "127"), ("float32", "16777216.0")])
def test_runtime_helpers_use_checked_adapters_as_managed_callbacks(tmp_path, optimize, kind, value):
    # On x86-64 the floating operand has its own register bank: that variant
    # checks width conversion, while int/int8 expose shifted hidden contexts.
    source = '''
        from collections.abc import Callable
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.native.runtime.algorithms import _runtime
        @_runtime
        def helper(value: KIND) -> KIND:
            return value + KIND(1)
        def ordinary(value: KIND) -> KIND:
            gc_collect()
            return value * KIND(2)
        def invoke(callback: Callable[[KIND], KIND]) -> KIND:
            gc_collect()
            return callback(KIND(INPUT))
        def main() -> str:
            gc_set_threshold(1)
            callbacks: list[Callable[[KIND], KIND]] = [helper, ordinary, helper]
            return str([invoke(callback) for callback in callbacks])
    '''.replace("KIND", kind).replace("INPUT", value)
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_helper_callbacks_preserve_mixed_register_classes(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Callable
from pyjs import int8, float32
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.native.runtime.algorithms import _runtime
@_runtime
def helper(value: float32, delta: int8) -> float32:
    return value * float32(2) + float32(delta)
def main() -> str:
    gc_set_threshold(1)
    callback: Callable[[float32, int8], float32] = helper
    results: list[float32] = []
    for value in [float32(1.25), float32(16777216)]:
        for delta in [int8(-7), int8(127), int8(128)]:
            gc_collect()
            results.append(callback(value, delta))
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("signature,body,argument,reason", [
    ("value: list[int]) -> int", "return len(value)", "[1]", "borrowed immutable text"),
    ("value: bytes) -> bytes", "return value", "b'a'", "scalar int, float or bool result"),
    ("value: int = 1) -> int", "return value", "2", "without defaults"),
])
def test_runtime_helper_signature_limits(signature, body, argument, reason):
    with pytest.raises(LLVMUnsupported, match=reason):
        transpile_llvm(f'''
            from pyjs.native.runtime.algorithms import _runtime
            @_runtime
            def helper({signature}:
                {body}
            def main() -> int:
                helper({argument})
                return 0
        ''')
