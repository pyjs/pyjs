import ctypes

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime.roots import _Frame
from pyjs.tooling.llvm import LLVM


@pytest.fixture(params=[0, 2], ids=["O0", "O2"])
def gc_runtime(tmp_path, request):
    source = transpile_llvm("""
        from pyjs.native import gc_collect

        def main() -> int:
            gc_collect()
            return 0
    """) + """
        define i64 @test_live_allocations(ptr %heap) {
          %pointer = getelementptr %pyjs.gc, ptr %heap, i32 0, i32 3
          %count = load i64, ptr %pointer
          ret i64 %count
        }
    """
    library = ctypes.CDLL(str(LLVM().compile(
        source, tmp_path, optimize=request.param, shared=True,
    )))
    pointer, integer = ctypes.c_void_p, ctypes.c_int64
    functions = {}
    for name, result, arguments in (
        ("new", pointer, []),
        ("alloc", pointer, [pointer, integer]),
        ("try.alloc.described", pointer, [pointer, integer, pointer]),
        ("pin", None, [pointer, pointer]),
        ("unpin", None, [pointer, pointer]),
        ("frame.push", None, [pointer, pointer, pointer, integer]),
        ("frame.pop", None, [pointer, pointer]),
        ("try.module.root", pointer, [pointer, integer]),
        ("find", pointer, [pointer, pointer]),
        ("set.threshold", None, [pointer, integer, integer]),
        ("maybe.collect", None, [pointer]),
        ("collect", None, [pointer]),
        ("enable", None, [pointer]),
        ("disable", None, [pointer]),
        ("delete", None, [pointer]),
    ):
        function = getattr(library, f"pyjs.gc.{name}")
        function.restype = result
        function.argtypes = arguments
        functions[name] = function
    count = library.test_live_allocations
    count.restype = integer
    count.argtypes = [pointer]
    heap = functions["new"]()
    try:
        yield heap, functions, count
    finally:
        functions["delete"](heap)


def test_failed_gc_allocation_does_not_change_live_state(gc_runtime):
    heap, functions, count = gc_runtime
    saved = functions["alloc"](heap, 8)
    functions["pin"](heap, saved)
    for size in (-1, 9223372036854775807):
        assert functions["try.alloc.described"](heap, size, None) is None
        assert count(heap) == 1
        functions["collect"](heap)
        assert count(heap) == 1
    assert functions["alloc"](heap, 8) is not None
    assert count(heap) == 2


def test_collection_observes_mutated_frame_and_module_slots(gc_runtime):
    heap, functions, count = gc_runtime
    first, second = _Frame(), _Frame()
    value = ctypes.c_void_p(functions["alloc"](heap, 8))
    slots = (ctypes.c_void_p * 1)(ctypes.addressof(value))
    functions["frame.push"](heap, ctypes.byref(first), slots, 1)
    functions["frame.push"](heap, ctypes.byref(second), None, 0)
    module_slot = ctypes.c_void_p.from_address(functions["try.module.root"](heap, 7))
    module_slot.value = functions["alloc"](heap, 8)
    functions["alloc"](heap, 8)
    functions["collect"](heap)
    assert count(heap) == 2
    # The frame stores addresses of slots, not snapshots of their values.
    value.value = functions["alloc"](heap, 8)
    module_slot.value = None
    functions["collect"](heap)
    assert count(heap) == 1
    functions["frame.pop"](heap, ctypes.byref(second))
    functions["collect"](heap)
    assert count(heap) == 1
    functions["frame.pop"](heap, ctypes.byref(first))
    functions["collect"](heap)
    assert count(heap) == 0


def test_gc_threshold_counts_allocations_since_collection(gc_runtime):
    heap, functions, count = gc_runtime
    functions["set.threshold"](heap, 3, 8 * 1024 * 1024)
    for _ in range(4):
        functions["pin"](heap, functions["alloc"](heap, 8))
    functions["maybe.collect"](heap)
    assert count(heap) == 4

    # Live storage already exceeds the threshold. New garbage must survive
    # until the allocation budget, not the live-object count, reaches three.
    for expected in (5, 6, 4):
        functions["alloc"](heap, 8)
        functions["maybe.collect"](heap)
        assert count(heap) == expected
        functions["maybe.collect"](heap)
        assert count(heap) == expected

    functions["disable"](heap)
    functions["alloc"](heap, 8)
    functions["collect"](heap)
    assert count(heap) == 4
    for _ in range(3):
        functions["alloc"](heap, 8)
    functions["maybe.collect"](heap)
    assert count(heap) == 7
    functions["enable"](heap)
    functions["maybe.collect"](heap)
    assert count(heap) == 4

    functions["alloc"](heap, 8)
    functions["collect"](heap)
    assert count(heap) == 4
    for _ in range(2):
        functions["alloc"](heap, 8)
    functions["maybe.collect"](heap)
    assert count(heap) == 6
    functions["set.threshold"](heap, 1, 8 * 1024 * 1024)
    functions["maybe.collect"](heap)
    assert count(heap) == 4
    functions["alloc"](heap, 8)
    functions["maybe.collect"](heap)
    assert count(heap) == 4


def test_gc_byte_budget_counts_headers_and_resets_after_collection(gc_runtime):
    heap, functions, count = gc_runtime
    functions["set.threshold"](heap, 1000, 128)
    functions["pin"](heap, functions["alloc"](heap, 128))
    functions["maybe.collect"](heap)
    assert count(heap) == 1
    # Each one-byte payload also owns a 32-byte GC header on the native ABI.
    # Four such allocations exceed the byte budget but not the count budget.
    for expected in (2, 3, 4, 1):
        functions["alloc"](heap, 1)
        functions["maybe.collect"](heap)
        assert count(heap) == expected
    functions["alloc"](heap, 128)
    functions["maybe.collect"](heap)
    assert count(heap) == 1
    functions["disable"](heap)
    functions["alloc"](heap, 128)
    functions["maybe.collect"](heap)
    assert count(heap) == 2
    functions["enable"](heap)
    functions["maybe.collect"](heap)
    assert count(heap) == 1
    functions["alloc"](heap, 1)
    functions["collect"](heap)
    functions["alloc"](heap, 1)
    functions["maybe.collect"](heap)
    assert count(heap) == 2


def test_gc_index_traces_interiors_but_not_headers_or_one_past(gc_runtime):
    heap, functions, count = gc_runtime
    functions["collect"](heap)
    assert count(heap) == 0
    root = functions["alloc"](heap, 512 * 8)
    references = (ctypes.c_void_p * 512).from_address(root)
    functions["pin"](heap, root)
    retained = []
    for index in range(512):
        size = (0, 1, 7, 8, 17, 64)[index % 6]
        value = functions["alloc"](heap, size)
        if size and (index // 6) % 3 == 1:
            ctypes.c_uint8.from_address(value + size - 1).value = 90
            candidate = value + size - 1
            retained.append((value, size))
        elif index % 3 == 2:
            candidate = value - 1
        else:
            candidate = value + size
        # Visit allocation ranges in a different order from allocation itself.
        references[(index * 73) % 512] = candidate
    functions["collect"](heap)
    assert count(heap) == 1 + len(retained)
    for value, size in retained:
        assert functions["find"](heap, value)
        assert ctypes.c_uint8.from_address(value + size - 1).value == 90
    for candidate in (None, 1, (1 << 64) - 1):
        assert functions["find"](heap, candidate) is None

    functions["unpin"](heap, root)
    functions["collect"](heap)
    assert count(heap) == 0
    # Rebuilding after sweep must not consult entries for released addresses.
    replacement = functions["alloc"](heap, 8)
    functions["pin"](heap, replacement + 7)
    functions["collect"](heap)
    assert count(heap) == 1
    functions["unpin"](heap, replacement + 7)
    functions["collect"](heap)
    assert count(heap) == 0


def test_gc_index_rebuilds_exact_and_interior_graphs(gc_runtime):
    heap, functions, count = gc_runtime
    size = 1024
    for interior_stride in (0, 10, 1):
        root = functions["alloc"](heap, size * 8)
        references = (ctypes.c_void_p * size).from_address(root)
        functions["pin"](heap, root)
        for index in range(size):
            value = functions["alloc"](heap, 64)
            offset = 7 if interior_stride and index % interior_stride == 0 else 0
            references[(index * 73) % size] = value + offset
        for _ in range(3):
            functions["collect"](heap)
            assert count(heap) == size + 1
        for index in range(0, size, 2):
            references[index] = None
        functions["collect"](heap)
        assert count(heap) == size // 2 + 1
        functions["unpin"](heap, root)
        functions["collect"](heap)
        assert count(heap) == 0
