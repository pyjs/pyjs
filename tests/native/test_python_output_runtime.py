import ctypes
import errno
import tempfile

import pytest

from pyjs import int32
from pyjs.native.runtime import arena, buffers, memory, output
from pyjs.native.runtime.pointers import Pointer, byte_offset, load_integer, load_pointer
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def output_runtime(tmp_path_factory, request):
    operations = {
        "try.new": buffers.new_output,
        "append.bytes": buffers.append_bytes,
        "flush": buffers.flush,
        "try.finish.memory": buffers.finish_memory,
    }
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join([
        "declare void @llvm.trap()",
        "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)",
        "%pyjs.string = type { i64, ptr }",
        *memory.arena_runtime(), *output.write_all_runtime(), *output.output_runtime(),
    ]))
    return runtime_functions(operations, library, "pyjs.native.output.")


def _append(invoke, target, data):
    storage = ctypes.create_string_buffer(data)
    return invoke("append.bytes", target, Pointer(ctypes.addressof(storage)), len(data))


def test_memory_output_growth_and_terminal_publication(output_runtime):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    try:
        target = output_runtime("try.new", owner, int32(-1))
        assert target.address != 0
        head, buffer = state.chunks, state.buffers
        used = arena._Chunk.from_address(head).used
        chunks = (b"", b"abc\x00", b"a" * 4092, b"z" * 5000) + (b"abcd",) * 32769
        for chunk in chunks:
            assert _append(output_runtime, target, chunk) == 0
        # Realloc may move the payload; predecessor buffers must not accumulate
        # as arena allocations or extra ownership records while output grows.
        assert state.chunks == head and arena._Chunk.from_address(head).used == used
        assert state.buffers == buffer and load_pointer(Pointer(buffer)).address == 0
        assert output_runtime("flush", target) == 0
        string = output_runtime("try.finish.memory", target)
        assert string.address != 0
        data = load_pointer(byte_offset(string, buffers.STRING_DATA_OFFSET))
        assert data.address == load_pointer(byte_offset(target, buffers.DATA_OFFSET)).address
        assert ctypes.string_at(data.address, load_integer(string)) == b"".join(chunks)
    finally:
        arena.destroy_arena(owner)


def test_descriptor_output_flush_direct_write_and_sticky_error(output_runtime, tmp_path):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    try:
        with tempfile.TemporaryFile() as destination:
            target = output_runtime("try.new", owner, int32(destination.fileno()))
            chunks = (b"first", b"b" * 65531, b"fresh", b"c" * 70000, b"end")
            for chunk in chunks:
                assert _append(output_runtime, target, chunk) == 0
            assert output_runtime("flush", target) == 0
            assert output_runtime("flush", target) == 0
            destination.seek(0)
            assert destination.read() == b"".join(chunks)
        # Keep an unwritable descriptor open instead of racing descriptor reuse.
        path = tmp_path / "read-only"
        path.write_bytes(b"unchanged")
        with path.open("rb") as destination:
            target = output_runtime("try.new", owner, int32(destination.fileno()))
            assert _append(output_runtime, target, b"pending") == 0
            assert output_runtime("flush", target) == errno.EBADF
            assert load_integer(byte_offset(target, buffers.LENGTH_OFFSET)) == 7
            assert _append(output_runtime, target, b"later") == errno.EBADF
            assert _append(output_runtime, target, b"") == errno.EBADF
            assert output_runtime("flush", target) == errno.EBADF
            assert output_runtime("try.finish.memory", target).address == 0
        assert path.read_bytes() == b"unchanged"
    finally:
        arena.destroy_arena(owner)


def test_invalid_append_lengths_fail_before_reading_or_changing_storage(output_runtime):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    try:
        for size in (-1, 2**63 - 1):
            target = output_runtime("try.new", owner, int32(-1))
            assert _append(output_runtime, target, b"x") == 0
            output = buffers._Output.from_address(target.address)
            before = (output.data, output.capacity, output.length, output.owner)
            assert output_runtime("append.bytes", target, Pointer(0), size) == errno.ENOMEM
            assert (output.data, output.capacity, output.length, output.owner) == before
            assert ctypes.string_at(output.data, output.length) == b"x"
            assert output_runtime("flush", target) == errno.ENOMEM
            assert _append(output_runtime, target, b"later") == errno.ENOMEM
            assert output_runtime("try.finish.memory", target).address == 0
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("steps,status,requests,first_bytes", [
    ([2, -1, 1, 2], 0, [5, 3, 3, 2], b"accd"),
    ([2, 0], 5, [5, 3], b"ac"),
    ([2, -2], 9, [5, 3], b"ac"),
])
def test_write_all_partial_progress_interrupts_and_failures(tmp_path, optimize, steps, status, requests, first_bytes):
    # Fault injection is confined to this generated library. In particular,
    # never interpose write/errno on the hosting Python process.
    source = "\n".join([
        "declare void @llvm.trap()",
        "declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)",
        "%pyjs.string = type { i64, ptr }",
        *memory.arena_runtime(), *output.write_all_runtime(), *output.output_runtime(),
    ])
    source = source.replace("call i64 @write(", "call i64 @test.write(")
    source = source.replace("call ptr @__errno_location()", "call ptr @test.errno()")
    source += '''
        @test_steps = global [4 x i64] zeroinitializer
        @test_requests = global [4 x i64] zeroinitializer
        @test_bytes = global [4 x i8] zeroinitializer
        @test_count = global i64 0
        @test_error = global i32 0

        define private ptr @test.errno() {
            ret ptr @test_error
        }

        define private i64 @test.write(i32 %descriptor, ptr %data, i64 %length) {
            %index = load i64, ptr @test_count
            %within = icmp ult i64 %index, 4
            br i1 %within, label %record, label %unexpected
        unexpected:
            store i32 9, ptr @test_error
            ret i64 -1
        record:
            %request = getelementptr [4 x i64], ptr @test_requests, i64 0, i64 %index
            store i64 %length, ptr %request
            %first = load i8, ptr %data
            %byte = getelementptr [4 x i8], ptr @test_bytes, i64 0, i64 %index
            store i8 %first, ptr %byte
            %step = getelementptr [4 x i64], ptr @test_steps, i64 0, i64 %index
            %result = load i64, ptr %step
            %interrupted = icmp eq i64 %result, -1
            %error = select i1 %interrupted, i32 4, i32 9
            store i32 %error, ptr @test_error
            %next = add i64 %index, 1
            store i64 %next, ptr @test_count
            %failed = icmp slt i64 %result, 0
            %count = select i1 %failed, i64 -1, i64 %result
            ret i64 %count
        }
    '''
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    script = (ctypes.c_int64 * 4).in_dll(library, "test_steps")
    script[:len(steps)] = steps
    function = getattr(library, "pyjs.write.all")
    function.argtypes = [ctypes.c_int32, ctypes.c_void_p, ctypes.c_int64]
    function.restype = ctypes.c_int32
    data = ctypes.create_string_buffer(b"abcde")
    assert function(1, data, 5) == status
    assert ctypes.c_int64.in_dll(library, "test_count").value == len(steps)
    assert list((ctypes.c_int64 * 4).in_dll(library, "test_requests"))[:len(steps)] == requests
    assert bytes((ctypes.c_uint8 * 4).in_dll(library, "test_bytes"))[:len(steps)] == first_bytes
    if status:
        count = ctypes.c_int64.in_dll(library, "test_count")
        count.value = 0
        state = buffers._Output(data=ctypes.addressof(data), length=5, capacity=5, descriptor=1)
        flush = getattr(library, "pyjs.native.output.flush")
        flush.argtypes, flush.restype = [ctypes.c_void_p], ctypes.c_int32
        append = getattr(library, "pyjs.native.output.append.bytes")
        append.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
        append.restype = ctypes.c_int32
        assert flush(ctypes.byref(state)) == status
        assert state.error == status and state.length == 5
        assert flush(ctypes.byref(state)) == status
        assert append(ctypes.byref(state), None, 1) == status
        assert count.value == len(steps)  # No replay of the already-written prefix.
