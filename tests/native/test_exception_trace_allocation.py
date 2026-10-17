import ctypes
import subprocess

import pytest

from pyjs import int32
from pyjs.native.llvm import transpile_llvm, transpile_llvm_module
from pyjs.native.runtime import arena, traces
from pyjs.native.runtime.pointers import Pointer, byte_offset, load_pointer
from pyjs.tooling.llvm import LLVM, LLVMLibrary, LLVMRuntimeError
from tests.native.allocation_support import _fail_allocations, run_allocation_case
from tests.native.runtime_support import runtime_functions, runtime_library, string


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("setup, operation, message", [
    ("cursor = batched([1, 2], 2)", "next(cursor)", "native iterator allocation failed"),
    ("cursor = enumerate([1])", "next(cursor)", "native iterator allocation failed"),
    ("cursor = zip([1], ['a'])", "next(cursor)", "native iterator allocation failed"),
    ("cursor = iter('λ')", "next(cursor)", "native iterator allocation failed"),
    ("cursor = reversed('λ')", "next(cursor)", "native iterator allocation failed"),
    ("values = [1]", "for value in values:\n        pass", "native allocation failed"),
    ("value = 'text'", "repr(value)", "native text output allocation failed"),
    ("value = b'text'", "repr(value)", "native allocation failed"),
], ids=["batch", "enumerate", "zip", "character", "reverse-character", "loop",
        "repr-text", "repr-bytes"])
def test_allocation_trace_points_to_the_failing_expression(tmp_path, setup, operation, message, optimize):
    source = transpile_llvm(f'''from itertools import batched
from tests.native.allocation_support import arm
def main() -> int:
    {setup}
    arm(1)
    {operation}
    return 0
''', filename="allocation_site.py")
    executable = LLVM().compile(_fail_allocations(source, False), tmp_path, optimize=optimize)
    result = subprocess.run([executable], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0 and result.stdout == ""
    assert result.stderr == (
        'Traceback (native PyJS):\n'
        f'  File "allocation_site.py", line 6, in main\nMemoryError: {message}\n'
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_enum_repr_uses_constant_text_without_consuming_an_allocation(tmp_path, optimize):
    # Enum repr once allocated a wrapper and could fail there. Current lowering
    # selects immutable member text; retain that stronger behavior instead of
    # expecting a nonexistent allocation failure or its old traceback.
    source = transpile_llvm('''
        from enum import IntEnum, StrEnum
        from tests.native.allocation_support import arm, remaining
        class Number(IntEnum):
            READY = 1
        class Word(StrEnum):
            READY = "ready"
        def main() -> int:
            arm(1)
            first = repr(Number.READY)
            second = repr(Word.READY)
            unused = remaining()
            arm(0)
            assert unused == 1
            assert first == "<Number.READY: 1>" and second == "<Word.READY: 'ready'>"
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=False, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def trace_runtime(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm('''
        def main() -> int:
            raise ValueError("failure")
    '''))
    return runtime_functions({"pyjs.exception.prepend": traces.prepend,
                              "pyjs.exception.write.trace": traces.write_trace}, library)


def test_trace_kernel_preserves_order_and_stops_at_truncation(trace_runtime, tmp_path):
    first, second, marker, message, header, newline = map(string, (
        b"  origin\n", b"  caller\n", b"  truncated\n", "ValueError: café".encode(),
        b"Traceback (native PyJS):\n", b"\n",
    ))
    origin = traces._Trace(ctypes.addressof(first), None)
    fallback = traces._Trace(ctypes.addressof(marker), ctypes.addressof(origin))
    exception = traces._Exception(trace=ctypes.addressof(origin), fallback=ctypes.addressof(fallback))
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    error = Pointer(ctypes.addressof(exception))
    suffix = tuple(Pointer(ctypes.addressof(value)) for value in (message, header, newline))
    try:
        trace_runtime("pyjs.exception.prepend", owner, error, Pointer(ctypes.addressof(second)))
        current = Pointer(exception.trace)
        assert load_pointer(current).address == ctypes.addressof(second)
        assert load_pointer(byte_offset(current, traces.NEXT_OFFSET)).address == ctypes.addressof(origin)
        for head, expected in ((exception.trace, b"  caller\n  origin\n"),
                               (exception.fallback, b"  truncated\n  origin\n"), (0, b"")):
            with (tmp_path / "trace").open("w+b") as output:
                trace_runtime("pyjs.exception.write.trace", int32(output.fileno()), Pointer(head), *suffix)
                output.seek(0)
                assert output.read() == b"Traceback (native PyJS):\n" + expected + "ValueError: café\n".encode()
        exception.trace = exception.fallback
        # A truncated chain must not inspect an allocator or another frame.
        trace_runtime("pyjs.exception.prepend", Pointer(0), error, Pointer(0))
        assert exception.trace == exception.fallback
        trace_runtime("pyjs.exception.write.trace", int32(-1), current, *suffix)
    finally:
        arena.destroy_arena(owner)


def deny_trace_allocations(source):
    # Internal linkage keeps fault injection out of the hosting Python process.
    # Realloc must not be optimized back to the interposed malloc on recovery.
    declaration = "declare noalias ptr @malloc(i64)"
    assert source.count(declaration) == 1
    return source.replace(declaration, '''
        @deny_allocations = global i1 true
        @allocation_attempts = global i64 0
        define internal ptr @malloc(i64 %size) {
          %previous = load i64, ptr @allocation_attempts
          %next = add i64 %previous, 1
          store i64 %next, ptr @allocation_attempts
          %deny = load i1, ptr @deny_allocations
          br i1 %deny, label %failure, label %allocate
        failure:
          ret ptr null
        allocate:
          %memory = call ptr @realloc(ptr null, i64 %size) nobuiltin
          ret ptr %memory
        }
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_handlers_reraise_without_allocating_exception_snapshots(tmp_path, optimize):
    source = transpile_llvm('''
        def origin() -> int:
            raise MemoryError()

        def middle() -> int:
            return origin()

        def main() -> int:
            caught = 0
            index = 0
            while index < 32:
                try:
                    try:
                        middle()
                    except MemoryError:
                        try:
                            raise ValueError("nested")
                        except ValueError:
                            pass
                        raise
                except MemoryError:
                    caught += 1
                index += 1
            return 0 if caught == 32 else 1
    ''')
    executable = LLVM().compile(deny_trace_allocations(source), tmp_path, optimize=optimize)
    result = subprocess.run([executable], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_library_copies_truncated_trace_then_recovers(tmp_path, optimize):
    module = transpile_llvm_module('''
        def origin() -> str:
            raise ValueError("bad request")

        def middle() -> str:
            return origin()

        def main(fail: bool) -> str:
            if fail:
                return middle()
            return "ready"
    ''', target="library", filename="exhausted.py")
    assert not module.managed
    path = LLVM().compile(deny_trace_allocations(module.llvm_ir), tmp_path,
                          shared=True, optimize=optimize)
    library = LLVMLibrary(path, "", module.parameters, False, False, True, module.type_definitions)
    denied = ctypes.c_bool.in_dll(library._library, "deny_allocations")
    attempts = ctypes.c_int64.in_dll(library._library, "allocation_attempts")
    try:
        for _ in range(3):
            attempts.value = 0
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render(True)
            trace = caught.value.native_traceback
            assert "[native traceback truncated: allocation failed]" in trace
            assert '"exhausted.py", line 3, in origin' in trace
            assert "in middle" not in trace and "in main" not in trace
            assert trace.endswith("ValueError: bad request\n")
            assert attempts.value == 1
            assert library.render(False) == "ready"
        denied.value = False
        with pytest.raises(LLVMRuntimeError) as recovered:
            library.render(True)
        assert "truncated" not in recovered.value.native_traceback
        assert "in main" in recovered.value.native_traceback
        assert "in middle" in recovered.value.native_traceback
        assert caught.value.native_traceback == trace
    finally:
        library.close()
