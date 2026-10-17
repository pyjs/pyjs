"""Public GC budgets: binding, atomic validation and actual collection pressure."""

import gc
import subprocess

import pytest

from pyjs import native
from pyjs.native.llvm import transpile_llvm_module
from pyjs.native.runtime import collector, heap
from pyjs.native.runtime.pointers import Pointer, null
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.native.allocation_support import _fail_allocations
from tests.native.runtime_support import runtime_functions


@pytest.mark.parametrize("optimize", [0, 2])
def test_exported_heap_creation_can_fail_then_render_and_destroy(tmp_path, optimize):
    module = transpile_llvm_module('''
        from pyjs.native import gc_collect
        def main() -> str:
            gc_collect()
            return "ready"
    ''', target="library")
    assert module.managed
    source = _fail_allocations(module.llvm_ir, True,
        extra=(("malloc", "i64 %size"),), only=("malloc",))
    # Exercise the exported API, not only collector.new_heap. The first malloc
    # is the heap header; resetting the shared countdown permits a real retry.
    source += '''
        define i32 @main() {
          store i64 1, ptr @test.remaining
          %failed = call ptr @pyjs_gc_new()
          %null = icmp eq ptr %failed, null
          br i1 %null, label %retry, label %unexpected
        retry:
          store i64 0, ptr @test.remaining
          %heap = call ptr @pyjs_gc_new()
          %missing = icmp eq ptr %heap, null
          br i1 %missing, label %unexpected, label %render
        render:
          %status = call i32 @pyjs_render_to_fd(ptr %heap, i32 1, ptr null)
          call void @pyjs_gc_delete(ptr %heap)
          ret i32 %status
        unexpected:
          ret i32 1
        }
    '''
    executable = LLVM().compile(source, tmp_path, optimize=optimize,
                                sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"ready"
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_collector_reuses_workspace_across_shared_cycles_and_disconnected_roots(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_pin, gc_unpin, gc_set_threshold
        class Node:
            def __init__(self, value: int):
                self.value = value
                self.next: Node | None = None
        def check(size: int) -> bool:
            shared = Node(42)
            shared.next = shared
            roots = [Node(index) for index in range(size)]
            for root in roots:
                root.next = shared
                gc_pin(root)
            valid = True
            for _ in range(3):
                gc_collect()
                for index, root in enumerate(roots):
                    child = root.next
                    valid = valid and root.value == index and child is not None
                    if child is not None:
                        valid = valid and child.value == 42 and child.next is child
            for root in roots:
                gc_unpin(root)
            return valid
        def main() -> str:
            gc_set_threshold(32)
            results: list[bool] = []
            for size in (0, 1, 64, 8, 256, 2):
                results.append(check(size))
                gc_collect()
                gc_collect()
            return str(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_python_gc_budget_fallback_validates_before_recording(monkeypatch):
    monkeypatch.setattr(native, "_gc_threshold", 10)
    monkeypatch.setattr(native, "_gc_byte_threshold", 100)
    python_thresholds = gc.get_threshold()
    for count, size, message in ((0, 64, "GC threshold"), (20, 0, "GC byte threshold"),
                                 (-1, -1, "GC threshold")):
        with pytest.raises(ValueError, match=message + " must be positive"):
            native.gc_set_threshold(count, byte_limit=size)
        assert (native._gc_threshold, native._gc_byte_threshold) == (10, 100)
    native.gc_set_threshold(byte_limit=128, value=20)
    assert (native._gc_threshold, native._gc_byte_threshold) == (20, 128)
    native.gc_set_threshold(30)
    assert (native._gc_threshold, native._gc_byte_threshold) == (30, 8_388_608)
    assert gc.get_threshold() == python_thresholds


@pytest.mark.parametrize("optimize", [0, 2])
def test_gc_budget_arguments_are_evaluated_before_validation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_set_threshold
        def mark(events: list[str], name: str, value: int) -> int:
            events.append(name)
            return value
        def fail(events: list[str]) -> int:
            events.append("raise")
            raise RuntimeError("argument failed")
        def main() -> str:
            events: list[str] = []
            gc_set_threshold(byte_limit=mark(events, "bytes", 128), value=mark(events, "count", 1000))
            try:
                gc_set_threshold(mark(events, "bad count", 0), byte_limit=mark(events, "bad bytes", 0))
            except ValueError as error:
                events.append(str(error))
            try:
                gc_set_threshold(0, byte_limit=fail(events))
            except RuntimeError as error:
                events.append(str(error))
            try:
                gc_set_threshold(1000, byte_limit=-1)
            except ValueError as error:
                events.append(str(error))
            gc_set_threshold(value=1000)
            gc_set_threshold(*[1000], **{"byte_limit": 128})
            try:
                gc_set_threshold(*[1000, 128])
            except TypeError:
                events.append("keyword-only")
            try:
                gc_set_threshold(**{"value": 1000, "unexpected": 128})
            except TypeError:
                events.append("unexpected keyword")
            gc_set_threshold(True, byte_limit=True)
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_public_gc_byte_budget_controls_collection_and_invalid_updates_are_atomic(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_set_threshold
        def configure(count: int, size: int, use_default: bool) -> str:
            if use_default:
                gc_set_threshold(value=count)
            else:
                gc_set_threshold(byte_limit=size, value=count)
            return "configured"
    ''', tmp_path, entry_point="configure", optimize=optimize)
    try:
        state = heap._Heap.from_address(library._heap)
        context = Pointer(library._heap)
        invoke = runtime_functions({
            "pyjs.gc.try.alloc.described": heap.allocate_described,
            "pyjs.gc.try.collect": collector.try_collect,
            "pyjs.gc.maybe.collect": collector.maybe_collect,
        }, library._library)
        assert library.render(1000, 128, False) == "configured"
        assert (state.threshold, state.byte_threshold) == (1000, 128)
        assert invoke("pyjs.gc.try.collect", context)
        assert state.count == 0
        # Reach the byte budget exactly with one allocation, well below 1000.
        invoke("pyjs.gc.try.alloc.described", context, 128 - heap.OBJECT_SIZE, null())
        assert state.count == 1 and state.bytes == 128
        invoke("pyjs.gc.maybe.collect", context)
        assert state.count == 0 and state.bytes == 0
        # Headers count; successful collection resets pressure rather than
        # making all subsequent safe points collect immediately.
        for expected in (1, 2, 3, 0):
            invoke("pyjs.gc.try.alloc.described", context, 1, null())
            invoke("pyjs.gc.maybe.collect", context)
            assert state.count == expected
        for count, size, message in ((0, 64, "GC threshold"), (20, 0, "GC byte threshold"),
                                     (-1, -1, "GC threshold")):
            with pytest.raises(LLVMRuntimeError, match=message + " must be positive"):
                library.render(count, size, False)
            assert (state.threshold, state.byte_threshold) == (1000, 128)
        assert library.render(30, 1, True) == "configured"
        assert (state.threshold, state.byte_threshold) == (30, 8_388_608)
    finally:
        library.close()
