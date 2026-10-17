import ctypes

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import collector, heap, roots
from pyjs.native.runtime.algorithms import _runtime
from pyjs.native.runtime.compiler import compile_runtime
from pyjs.native.runtime.pointers import (
    Pointer,
    byte_offset,
    free,
    load_pointer,
    null,
    pointer_slot,
    sort_addresses,
    store_pointer,
)
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_failure import (
    reject_native_allocations as _reject_native_allocations,
)
from tests.native.runtime_support import runtime_functions, runtime_library


@_runtime
def _sort_addresses(values: Pointer, count: int) -> None:
    sort_addresses(values, count)


def _source():
    return transpile_llvm('''
        from pyjs.native import gc_collect
        def main() -> int:
            gc_collect()
            return 0
    ''') + '\n'.join(compile_runtime({
        "pyjs.gc.test.index": collector.build_index,
        "pyjs.gc.test.sort": _sort_addresses,
    }))


OPERATIONS = {
    "try.new": collector.new_heap,
    "try.alloc.described": heap.allocate_described,
    "try.collect": collector.try_collect,
    "maybe.collect": collector.maybe_collect,
    "find": collector.find,
    "try.pin": roots.try_pin,
    "unpin": roots.unpin,
    "destroy": roots.destroy_heap,
    "collection.due": collector.collection_due,
    "index.compare": collector.compare_addresses,
    "test.index": collector.build_index,
    "test.sort": _sort_addresses,
}


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def collector_runtime(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, _source)
    return runtime_functions(OPERATIONS, library, "pyjs.gc.")


def test_pointer_ordering_uses_unsigned_addresses(collector_runtime):
    # Store synthetic addresses without dereferencing them. Real allocations
    # rarely exercise the sign bit that distinguishes unsigned pointer order.
    for left in (1, (1 << 63) - 1, 1 << 63, (1 << 64) - 1):
        for right in (1, (1 << 63) - 1, 1 << 63, (1 << 64) - 1):
            first, second = ctypes.c_void_p(left), ctypes.c_void_p(right)
            assert collector_runtime("index.compare", Pointer(ctypes.addressof(first)),
                                     Pointer(ctypes.addressof(second))) == (left > right) - (left < right)


def test_address_sorting_includes_null_and_unsigned_high_bits(collector_runtime):
    values = [None, (1 << 64) - 1, 4096, None, 1 << 63, 1]
    array = (ctypes.c_void_p * len(values))(*values)
    collector_runtime("test.sort", Pointer(ctypes.addressof(array)), len(values))
    assert list(array) == [None, None, 1, 4096, 1 << 63, (1 << 64) - 1]


def test_heap_destruction_releases_active_index_and_is_repeatable(collector_runtime):
    invoke = collector_runtime
    pointer = invoke("try.new")
    state = heap._Heap.from_address(pointer.address)
    try:
        invoke("try.alloc.described", pointer, 8, null())
        assert invoke("test.index", pointer)
        assert state.index is not None
        invoke("destroy", pointer)
        assert state.index is None and state.objects is None
        invoke("destroy", pointer)
    finally:
        invoke("destroy", pointer)
        free(pointer)


@pytest.mark.parametrize("description,edges,pins", [
    ("disconnected", [[], [], [], []], [0, 2]),
    ("chain", [[1], [2], [3], []], [0]),
    ("diamond", [[1, 2], [3], [3], []], [0, 2]),
    ("cycle", [[1], [2], [0], []], [0]),
])
def test_collector_graphs_and_repeated_lifetimes(collector_runtime, description, edges, pins):
    invoke = collector_runtime
    for _ in range(8):
        pointer = invoke("try.new")
        state = heap._Heap.from_address(pointer.address)
        try:
            assert state.enabled and state.threshold == 4096 and state.byte_threshold == 8388608
            nodes = [invoke("try.alloc.described", pointer, max(1, len(children)) * 8, null()) for children in edges]
            for node, children in zip(nodes, edges, strict=True):
                for index, child in enumerate(children):
                    # Interior pointers must retain the same graph as base pointers.
                    store_pointer(pointer_slot(node, index), byte_offset(nodes[child], 1))
            for index in pins:
                assert invoke("try.pin", pointer, nodes[index])
                assert invoke("try.pin", pointer, nodes[index])
            expected = set(pins)
            pending = list(pins)
            while pending:
                for child in edges[pending.pop()]:
                    if child not in expected:
                        expected.add(child)
                        pending.append(child)
            for _ in range(3):
                assert invoke("try.collect", pointer), description
                assert state.count == len(expected) and state.index is None
                assert state.pressure == 0 and state.bytes == 0
                assert not invoke("collection.due", pointer)
                for index in expected:
                    assert invoke("find", pointer, nodes[index]).address != 0
            for index in pins:
                invoke("unpin", pointer, nodes[index])
            assert invoke("try.collect", pointer)
            assert state.count == 0 and state.objects is None
        finally:
            invoke("destroy", pointer)
            free(pointer)


def test_descriptors_and_partial_word_boundaries(collector_runtime):
    invoke = collector_runtime
    pointer = invoke("try.new")
    state = heap._Heap.from_address(pointer.address)
    # ctypes callback models the generated read-only trace accessor. Keep it
    # and its descriptor alive until the heap has been released.
    trace_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    trace = trace_type(lambda payload, index: load_pointer(pointer_slot(Pointer(payload), index)).address)
    atomic = collector._Descriptor(0, None)
    fixed = collector._Descriptor(1, ctypes.cast(trace, ctypes.c_void_p))
    dynamic = collector._Descriptor(-1, ctypes.cast(trace, ctypes.c_void_p))
    try:
        for descriptor, retained in ((atomic, 1), (fixed, 2), (dynamic, 3)):
            owner = invoke("try.alloc.described", pointer, 23, Pointer(ctypes.addressof(descriptor)))
            for index in range(2):
                child = invoke("try.alloc.described", pointer, 8, null())
                store_pointer(pointer_slot(owner, index), child)
            # Seven trailing bytes are not a third pointer. Dynamic tracing and
            # conservative scanning must never read past the payload.
            ctypes.memset(owner.address + 16, 0xff, 7)
            assert invoke("try.pin", pointer, owner)
            assert invoke("try.collect", pointer)
            assert state.count == retained
            invoke("unpin", pointer, owner)
            assert invoke("try.collect", pointer) and state.count == 0
    finally:
        invoke("destroy", pointer)
        free(pointer)


@pytest.mark.parametrize("optimize", [0, 2])
def test_index_allocation_failure_is_retryable_without_partial_marking(tmp_path, optimize):
    source = _reject_native_allocations(_source())
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions(OPERATIONS, library, "pyjs.gc.")
    denied = ctypes.c_bool.in_dll(library, "test_deny_allocations")
    assert invoke("try.new").address == 0
    denied.value = False
    pointer = invoke("try.new")
    state = heap._Heap.from_address(pointer.address)
    try:
        value = invoke("try.alloc.described", pointer, 8, null())
        assert invoke("try.pin", pointer, value)
        invoke("try.alloc.described", pointer, 8, null())
        before = ctypes.string_at(pointer.address, ctypes.sizeof(state))
        denied.value = True
        assert not invoke("try.collect", pointer)
        assert ctypes.string_at(pointer.address, ctypes.sizeof(state)) == before
        assert not heap._Object.from_address(state.objects).marked
        # Automatic collection is best-effort, unlike an explicit collection
        # request. Failure must preserve roots and permit later recovery.
        state.threshold = 0
        before = ctypes.string_at(pointer.address, ctypes.sizeof(state))
        invoke("maybe.collect", pointer)
        assert ctypes.string_at(pointer.address, ctypes.sizeof(state)) == before
        denied.value = False
        assert invoke("try.collect", pointer) and state.count == 1
        invoke("unpin", pointer, value)
        assert invoke("try.collect", pointer) and state.count == 0
        denied.value = True
        assert invoke("try.collect", pointer)  # Empty heaps need no workspace.
    finally:
        invoke("destroy", pointer)
        free(pointer)


def test_index_capacity_overflow_does_not_allocate_or_change_heap(collector_runtime):
    state = heap._Heap()
    pointer = Pointer(ctypes.addressof(state))
    for count in (-1, 1 << 59, (1 << 63) - 1):
        state.count = count
        assert not collector_runtime("try.collect", pointer)
        assert state.index is None and state.count == count


@pytest.mark.parametrize("optimize", [0, 2])
def test_repeated_collection_and_heap_destruction_balance_native_allocations(tmp_path, optimize):
    # Instrument only this generated library, not the hosting process's libc.
    # Counting outstanding allocations avoids noisy process-RSS thresholds.
    source = _source()
    for symbol, result in (("malloc", "ptr"), ("calloc", "ptr"), ("free", "void")):
        source = source.replace(f"call {result} @{symbol}(", f"call {result} @test.{symbol}(")
    source += "\n@test_live = global i64 0\n"
    for symbol, parameters, arguments in (
        ("malloc", "i64 %size", "i64 %size"),
        ("calloc", "i64 %count, i64 %size", "i64 %count, i64 %size"),
    ):
        source += f'''
            define internal ptr @test.{symbol}({parameters}) {{
              %value = call ptr @{symbol}({arguments}) nobuiltin
              %allocated = icmp ne ptr %value, null
              %change = zext i1 %allocated to i64
              %old = load i64, ptr @test_live
              %new = add i64 %old, %change
              store i64 %new, ptr @test_live
              ret ptr %value
            }}
        '''
    source += '''
        define internal void @test.free(ptr %value) {
          %allocated = icmp ne ptr %value, null
          %change = zext i1 %allocated to i64
          %old = load i64, ptr @test_live
          %new = sub i64 %old, %change
          store i64 %new, ptr @test_live
          call void @free(ptr %value) nobuiltin
          ret void
        }
    '''
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions(OPERATIONS, library, "pyjs.gc.")
    delete = getattr(library, "pyjs.gc.delete")
    delete.argtypes, delete.restype = [ctypes.c_void_p], None
    live = ctypes.c_int64.in_dll(library, "test_live")
    for _ in range(100):
        pointer = invoke("try.new")
        try:
            for _ in range(4):
                owner = invoke("try.alloc.described", pointer, 16, null())
                child = invoke("try.alloc.described", pointer, 16, null())
                store_pointer(owner, child)
                store_pointer(child, owner)
                invoke("try.alloc.described", pointer, 8, null())
                assert invoke("try.pin", pointer, owner)
                assert invoke("try.collect", pointer)
                assert live.value == 4  # Heap, two graph objects, one pin.
                invoke("unpin", pointer, owner)
                assert invoke("try.collect", pointer)
                assert live.value == 1
            invoke("try.alloc.described", pointer, 8, null())
            assert invoke("test.index", pointer)
            assert live.value == 3  # Heap, object, and unfinished index workspace.
            invoke("destroy", pointer)
            assert heap._Heap.from_address(pointer.address).index is None
            assert live.value == 1
        finally:
            delete(pointer.address)
        assert live.value == 0
