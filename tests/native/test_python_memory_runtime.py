import ctypes
import signal
import subprocess
import sys
import textwrap

import pytest

from pyjs import int8, llvm
from pyjs.native import gc_collect
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.native.runtime import arena, collector, heap, identity, roots
from pyjs.native.runtime.algorithms import _runtime
from pyjs.native.runtime.compiler import compile_runtime
from pyjs.native.runtime.memory import identity_map_runtime
from pyjs.native.runtime.pointers import (
    Pointer,
    byte_offset,
    copy,
    fill,
    free,
    load_integer,
    load_pointer,
    null,
    store_int8,
    store_integer,
    store_pointer,
)
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import _fail_allocations
from tests.native.runtime_failure import (
    reject_native_allocations as _reject_native_allocations,
)
from tests.native.runtime_support import runtime_functions, runtime_library


def _runtime_source():
    return transpile_llvm('''
        from pyjs.native import gc_collect

        def main() -> int:
            gc_collect()
            return 0
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_layout_constants_match_llvm_structures(tmp_path, optimize):
    source = _runtime_source() + '\n'.join(identity_map_runtime())
    checks = []
    for name, structure in (
        ("pyjs.arena", arena._Arena), ("pyjs.arena.chunk", arena._Chunk),
        ("pyjs.repr.frame", arena._ReprFrame),
        ("pyjs.gc", heap._Heap),
        ("pyjs.gc.object", heap._Object), ("pyjs.gc.frame", roots._Frame),
        ("pyjs.gc.module.root", roots._ModuleRoot), ("pyjs.gc.pin", roots._Pin),
        ("pyjs.gc.index", collector._Index), ("pyjs.gc.descriptor", collector._Descriptor),
        ("pyjs.identity", identity._Map), ("pyjs.identity.entry", identity._Entry),
    ):
        checks.append((name, "i32 1", ctypes.sizeof(structure)))
        for index, (field, _) in enumerate(structure._fields_):
            checks.append((name, f"i32 0, i32 {index}", getattr(structure, field).offset))
    checks.extend([
        ("pyjs.arena.buffer", "i32 1", arena.BUFFER_SIZE),
        ("pyjs.arena.buffer", "i32 0, i32 1", arena.BUFFER_DATA_OFFSET),
    ])
    for index, (name, indices, _) in enumerate(checks):
        source += f'''
            define i64 @test.layout.{index}() {{
              %address = getelementptr %{name}, ptr null, {indices}
              %offset = ptrtoint ptr %address to i64
              ret i64 %offset
            }}
        '''
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    for index, (name, indices, expected) in enumerate(checks):
        function = getattr(library, f"test.layout.{index}")
        function.argtypes, function.restype = [], ctypes.c_int64
        assert function() == expected, (name, indices)


@_runtime
def _copy_words(destination: Pointer, source: Pointer, size: int) -> None:
    copy(destination, source, size)
    store_integer(byte_offset(destination, size), 99)


@_runtime
def _copy_and_read(destination: Pointer, source: Pointer, size: int) -> int:
    _copy_words(destination, source, size)
    return load_integer(destination) + load_integer(byte_offset(destination, size))


@_runtime
def _write_byte(destination: Pointer, value: int) -> None:
    store_int8(destination, int8(value))


@_runtime
def _fill_bytes(destination: Pointer, value: int, size: int) -> None:
    fill(destination, int8(value), size)


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def memory_runtime(request, tmp_path_factory):
    functions = {
        "pyjs.arena.init": arena.initialize,
        "pyjs.arena.try.alloc": arena.allocate_in_arena,
        "pyjs.arena.buffer.try.new": arena.new_buffer,
        "pyjs.arena.buffer.try.resize": arena.resize_buffer,
        "pyjs.arena.destroy": arena.destroy_arena,
        "pyjs.gc.try.alloc.described": heap.allocate_described,
        "pyjs.gc.try.module.root": roots.module_root,
        "pyjs.gc.frame.push": roots.push_frame,
        "pyjs.gc.frame.try.pop": roots.try_pop_frame,
        "pyjs.gc.try.pin": roots.try_pin,
        "pyjs.gc.pin": collector.pin,
        "pyjs.gc.maybe.collect": collector.maybe_collect,
        "pyjs.gc.unpin": roots.unpin,
        "pyjs.gc.destroy": roots.destroy_heap,
        "pyjs.collection.try.alloc": arena.allocate_collection,
        "pyjs.repr.enter": arena.enter_repr,
        "pyjs.repr.try.leave": arena.leave_repr,
    }
    library = runtime_library(request, tmp_path_factory, _runtime_source)
    return runtime_functions(functions, library)


def test_collection_entry_points_respect_enablement_and_pins(memory_runtime):
    state = heap._Heap()
    pointer = Pointer(ctypes.addressof(state))
    collector.initialize(pointer)
    assert collector.try_set_threshold(pointer, 1, 1)
    try:
        value = memory_runtime("pyjs.gc.try.alloc.described", pointer, 8, null())
        memory_runtime("pyjs.gc.pin", pointer, value)
        memory_runtime("pyjs.gc.pin", pointer, value)
        assert collector.count_pins(pointer) == 1
        memory_runtime("pyjs.gc.maybe.collect", pointer)
        assert state.count == 1
        memory_runtime("pyjs.gc.unpin", pointer, value)
        memory_runtime("pyjs.gc.try.alloc.described", pointer, 8, null())
        collector.disable(pointer)
        memory_runtime("pyjs.gc.maybe.collect", pointer)
        assert state.count == 2
        collector.enable(pointer)
        memory_runtime("pyjs.gc.maybe.collect", pointer)
        assert state.count == 0
        memory_runtime("pyjs.gc.maybe.collect", pointer)
        assert state.count == 0
    finally:
        memory_runtime("pyjs.gc.destroy", pointer)


def test_repr_frames_prioritize_cycles_and_preserve_state_on_failure(memory_runtime):
    frames = (arena._ReprFrame * 1000)()
    for index, frame in enumerate(frames):
        frame.value = index + 1
        frame.parent = ctypes.addressof(frames[index - 1]) if index else None
    state = arena._Arena(repr=ctypes.addressof(frames[-1]))
    pointer = Pointer(ctypes.addressof(state))
    candidate = arena._ReprFrame(1234, 5678)
    new_frame = Pointer(ctypes.addressof(candidate))
    head = state.repr
    assert memory_runtime("pyjs.repr.enter", pointer, new_frame, Pointer(42)) == 0
    assert memory_runtime("pyjs.repr.enter", pointer, new_frame, Pointer(2000)) == 2
    assert state.repr == head and (candidate.value, candidate.parent) == (1234, 5678)
    assert not memory_runtime("pyjs.repr.try.leave", pointer, Pointer(ctypes.addressof(frames[0])))
    assert state.repr == head
    assert memory_runtime("pyjs.repr.try.leave", pointer, Pointer(head))
    assert memory_runtime("pyjs.repr.enter", pointer, new_frame, Pointer(2000)) == 1
    assert state.repr == new_frame.address and candidate.parent == ctypes.addressof(frames[-2])
    assert memory_runtime("pyjs.repr.try.leave", pointer, new_frame)
    memory_runtime("pyjs.arena.init", pointer)
    assert state.repr is None and state.chunks is None and state.counter == 0 and state.buffers is None


def test_collection_allocation_callback_owns_its_result(memory_runtime):
    state = arena._Arena()
    pointer = Pointer(ctypes.addressof(state))
    storage = (ctypes.c_uint8 * 64)()
    events = []

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        events.append((context, size))
        return ctypes.addressof(storage) if size in (1, 8) else None

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    assert memory_runtime("pyjs.collection.try.alloc", pointer, allocator, Pointer(123), 8).address == ctypes.addressof(storage)
    assert memory_runtime("pyjs.collection.try.alloc", pointer, allocator, Pointer(123), 13).address == 0
    assert memory_runtime("pyjs.collection.try.alloc", pointer, allocator, Pointer(123), 0).address == ctypes.addressof(storage)
    assert events == [(123, 8), (123, 13), (123, 1)] and state.chunks is None
    try:
        assert memory_runtime("pyjs.collection.try.alloc", pointer, Pointer(0), Pointer(0), 8).address != 0
        assert state.chunks is not None
    finally:
        memory_runtime("pyjs.arena.destroy", pointer)


def test_arena_algorithms_preserve_data_and_release_ownership(memory_runtime):
    state = arena._Arena()
    pointer = Pointer(ctypes.addressof(state))
    try:
        for size in (-1, 9223372036854775807):
            assert memory_runtime("pyjs.arena.try.alloc", pointer, size, 8).address == 0
            assert state.chunks is None
        small = memory_runtime("pyjs.arena.try.alloc", pointer, 0, 8)
        assert small.address != 0
        first_chunk = state.chunks
        large = memory_runtime("pyjs.arena.try.alloc", pointer, 70000, 8)
        assert large.address != 0 and state.chunks != first_chunk
        assert load_pointer(Pointer(state.chunks)).address == first_chunk
        buffer = memory_runtime("pyjs.arena.buffer.try.new", pointer, 16)
        assert state.buffers == buffer.address
        data = load_pointer(byte_offset(buffer, arena.BUFFER_DATA_OFFSET))
        store_integer(data, 42)
        store_integer(byte_offset(data, 8), 73)
        for size in (100000, 16):
            resized = memory_runtime("pyjs.arena.buffer.try.resize", buffer, size)
            assert resized.address == load_pointer(byte_offset(buffer, arena.BUFFER_DATA_OFFSET)).address
            assert load_integer(resized) == 42
            assert load_integer(byte_offset(resized, 8)) == 73
        assert memory_runtime("pyjs.arena.buffer.try.resize", buffer, -1).address == 0
        assert load_pointer(byte_offset(buffer, arena.BUFFER_DATA_OFFSET)).address == resized.address
        assert memory_runtime("pyjs.arena.buffer.try.resize", buffer, 0).address != 0
    finally:
        memory_runtime("pyjs.arena.destroy", pointer)
    assert state.chunks is None and state.buffers is None
    memory_runtime("pyjs.arena.destroy", pointer)


@pytest.mark.parametrize("optimize", [0, 2])
def test_buffer_failure_preserves_ownership_and_bytes_then_recovers(tmp_path, optimize):
    source = _fail_allocations(_runtime_source(), False, only=("pyjs.arena.try.alloc", "realloc"))
    source = source.replace("@test.remaining = private global", "@test.remaining = global")
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, optimize=optimize, shared=True)))
    invoke = runtime_functions({
        "pyjs.arena.buffer.try.new": arena.new_buffer,
        "pyjs.arena.buffer.try.resize": arena.resize_buffer,
        "pyjs.arena.destroy": arena.destroy_arena,
    }, library)
    remaining = ctypes.c_int64.in_dll(library, "test.remaining")
    state = arena._Arena()
    pointer = Pointer(ctypes.addressof(state))
    try:
        remaining.value = 1
        assert not invoke("pyjs.arena.buffer.try.new", pointer, -1).address
        assert remaining.value == 1  # Reject invalid sizes before allocating.
        assert not invoke("pyjs.arena.buffer.try.new", pointer, 16).address
        assert state.chunks is None and state.buffers is None
        buffer = invoke("pyjs.arena.buffer.try.new", pointer, 16)
        data = load_pointer(byte_offset(buffer, arena.BUFFER_DATA_OFFSET))
        store_integer(data, 42)
        store_integer(byte_offset(data, 8), 99)
        remaining.value = 1
        assert not invoke("pyjs.arena.buffer.try.resize", buffer, 65536).address
        remaining.value = 2  # Header succeeds, but its payload allocation fails.
        assert not invoke("pyjs.arena.buffer.try.new", pointer, 16).address
        remaining.value = 1
        assert not invoke("pyjs.arena.buffer.try.resize", buffer, -1).address
        assert remaining.value == 1
        assert state.buffers == buffer.address and load_pointer(buffer).address == 0
        assert load_pointer(byte_offset(buffer, arena.BUFFER_DATA_OFFSET)).address == data.address
        assert load_integer(data) == 42 and load_integer(byte_offset(data, 8)) == 99
        remaining.value = 0
        grown = invoke("pyjs.arena.buffer.try.resize", buffer, 65536)
        assert load_integer(grown) == 42 and load_integer(byte_offset(grown, 8)) == 99
        assert invoke("pyjs.arena.buffer.try.resize", buffer, 0).address
        second = invoke("pyjs.arena.buffer.try.new", pointer, 0)
        assert load_pointer(second).address == buffer.address
    finally:
        invoke("pyjs.arena.destroy", pointer)
    invoke("pyjs.arena.destroy", pointer)
    assert state.chunks is None and state.buffers is None


def test_arena_alignment_and_nonoverlapping_allocations(memory_runtime):
    state = arena._Arena()
    pointer = Pointer(ctypes.addressof(state))
    allocations = []
    try:
        for alignment in (0, -1, 3, 6):
            assert memory_runtime("pyjs.arena.try.alloc", pointer, 1, alignment).address == 0
            assert state.chunks is None
        for alignment in (1, 2, 4, 8, 16, 64, 4096):
            for size in (0, 1, 7, 4096, 65537):
                value = memory_runtime("pyjs.arena.try.alloc", pointer, size, alignment)
                assert value.address and value.address % alignment == 0
                length = max(1, size)
                assert all(value.address + length <= start or start + count <= value.address
                           for start, count, _ in allocations)
                marker = len(allocations) + 1
                ctypes.memset(value.address, marker, length)
                allocations.append((value.address, length, marker))
        for start, count, marker in allocations:
            assert ctypes.string_at(start, count) == bytes([marker]) * count
    finally:
        memory_runtime("pyjs.arena.destroy", pointer)


def test_heap_algorithms_initialize_before_publishing_and_saturate_pressure(memory_runtime):
    state = heap._Heap()
    state.bytes = -16  # UINT64_MAX - 15: the next allocation must saturate.
    pointer = Pointer(ctypes.addressof(state))
    descriptor = ctypes.c_int64(123)
    try:
        for size in (-1, 9223372036854775807):
            assert memory_runtime("pyjs.gc.try.alloc.described", pointer, size, null()).address == 0
            assert state.objects is None and state.count == 0 and state.pressure == 0
            assert state.bytes == -16
        value = memory_runtime("pyjs.gc.try.alloc.described", pointer, 16, Pointer(ctypes.addressof(descriptor)))
        header = heap._Object.from_address(state.objects)
        assert value.address == state.objects + ctypes.sizeof(heap._Object)
        assert header.next is None and not header.marked
        assert header.size == 16 and header.descriptor == ctypes.addressof(descriptor)
        assert ctypes.string_at(value.address, 16) == bytes(16)
        assert state.count == 1 and state.pressure == 1 and state.bytes == -1
        first = state.objects
        assert memory_runtime("pyjs.gc.try.alloc.described", pointer, 0, null()).address != 0
        assert load_pointer(Pointer(state.objects)).address == first
        assert state.count == 2 and state.pressure == 2 and state.bytes == -1
    finally:
        while state.objects:
            value = Pointer(state.objects)
            state.objects = load_pointer(value).address
            free(value)


def test_root_frames_borrow_slots_and_reject_out_of_order_pop(memory_runtime):
    state = heap._Heap()
    pointer = Pointer(ctypes.addressof(state))
    first, second = roots._Frame(), roots._Frame()
    first_pointer, second_pointer = Pointer(ctypes.addressof(first)), Pointer(ctypes.addressof(second))
    value = ctypes.c_void_p(123)
    slots = (ctypes.c_void_p * 1)(ctypes.addressof(value))
    memory_runtime("pyjs.gc.frame.push", pointer, first_pointer, Pointer(ctypes.addressof(slots)), 1)
    assert state.roots == first_pointer.address and first.previous is None
    assert first.count == 1 and first.slots == ctypes.addressof(slots)
    value.value = 456
    assert load_pointer(load_pointer(Pointer(first.slots))).address == 456
    memory_runtime("pyjs.gc.frame.push", pointer, second_pointer, null(), 0)
    assert second.previous == first_pointer.address and second.count == 0
    assert not memory_runtime("pyjs.gc.frame.try.pop", pointer, first_pointer)
    assert state.roots == second_pointer.address and second.previous == first_pointer.address
    # Heap destruction must not free caller-owned frames or their slot arrays.
    memory_runtime("pyjs.gc.destroy", pointer)
    assert state.roots == second_pointer.address
    assert memory_runtime("pyjs.gc.frame.try.pop", pointer, second_pointer)
    assert state.roots == first_pointer.address
    assert memory_runtime("pyjs.gc.frame.try.pop", pointer, first_pointer)
    assert state.roots is None
    assert not memory_runtime("pyjs.gc.frame.try.pop", pointer, first_pointer)


def test_module_root_identity_pin_set_and_owned_chain_destruction(memory_runtime):
    state = heap._Heap()
    pointer = Pointer(ctypes.addressof(state))
    try:
        values = [memory_runtime("pyjs.gc.try.alloc.described", pointer, 16, null()) for _ in range(3)]
        keys = (0, -9223372036854775808, 9223372036854775807)
        saved_slots = []
        for key, value in zip(keys, values, strict=True):
            slot = memory_runtime("pyjs.gc.try.module.root", pointer, key)
            saved_slots.append(slot.address)
            assert load_pointer(slot).address == 0
            store_pointer(slot, value)
            assert memory_runtime("pyjs.gc.try.module.root", pointer, key).address == slot.address
            assert load_pointer(slot).address == value.address
        assert [memory_runtime("pyjs.gc.try.module.root", pointer, key).address for key in keys] == saved_slots
        pinned = [values[0], byte_offset(values[0], 1), values[1]]
        for value in pinned:
            assert memory_runtime("pyjs.gc.try.pin", pointer, value)
        head = state.pins
        assert memory_runtime("pyjs.gc.try.pin", pointer, pinned[1])
        assert state.pins == head
        # Middle, head, tail, then an absent address: exactly one unlink per pin.
        remaining = [value.address for value in reversed(pinned)]
        for index in (1, 2, 0, 0):
            memory_runtime("pyjs.gc.unpin", pointer, pinned[index])
            remaining = [address for address in remaining if address != pinned[index].address]
            observed = []
            pin = state.pins
            while pin:
                node = roots._Pin.from_address(pin)
                observed.append(node.value)
                pin = node.next
            assert observed == remaining
        assert state.pins is None
        assert memory_runtime("pyjs.gc.try.pin", pointer, values[2])
    finally:
        memory_runtime("pyjs.gc.destroy", pointer)
    assert state.objects is None and state.pins is None and state.modules is None
    memory_runtime("pyjs.gc.destroy", pointer)


@pytest.mark.parametrize("optimize", [0, 2])
def test_heap_allocator_failure_preserves_state_and_allows_retry(tmp_path, optimize):
    source = _reject_native_allocations(_runtime_source())
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, optimize=optimize, shared=True)))
    allocate = getattr(library, "pyjs.gc.try.alloc.described")
    allocate.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p]
    allocate.restype = ctypes.c_void_p
    module_root = getattr(library, "pyjs.gc.try.module.root")
    module_root.argtypes = [ctypes.c_void_p, ctypes.c_int64]
    module_root.restype = ctypes.c_void_p
    pin = getattr(library, "pyjs.gc.try.pin")
    pin.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    pin.restype = ctypes.c_bool
    denied = ctypes.c_bool.in_dll(library, "test_deny_allocations")
    state = heap._Heap()
    address = ctypes.addressof(state)
    try:
        denied.value = False
        value = allocate(address, 8, None)
        assert value is not None
        slot = module_root(address, 1)
        assert slot is not None and pin(address, value)
        before = ctypes.string_at(address, ctypes.sizeof(state))
        denied.value = True
        assert allocate(address, 16, None) is None
        assert module_root(address, 2) is None
        assert not pin(address, value + 1)
        # Looking up an existing root/pin must succeed without allocating.
        assert module_root(address, 1) == slot and pin(address, value)
        assert ctypes.string_at(address, ctypes.sizeof(state)) == before
        denied.value = False
        assert allocate(address, 16, None) is not None
        assert module_root(address, 2) is not None and pin(address, value + 1)
        assert state.count == 2 and state.pressure == 2
    finally:
        roots.destroy_heap(Pointer(address))


@pytest.mark.parametrize("optimize", [0, 2])
def test_invalid_root_operations_still_trap_at_native_boundary(tmp_path, optimize):
    source = _reject_native_allocations(_runtime_source())
    path = LLVM().compile(source, tmp_path, optimize=optimize, shared=True)
    for action in ("pop_out_of_order", "pin_unmanaged", "pin_allocation_failure"):
        # A trap is the contract, not a Python exception. Isolate it from pytest
        # and disable core dumps so these checks cannot fill the workstation.
        execution = subprocess.run([sys.executable, "-c", textwrap.dedent(f'''
            import ctypes
            import resource
            from pyjs.native.runtime.heap import _Heap
            from pyjs.native.runtime.roots import _Frame

            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            library = ctypes.CDLL({str(path)!r})
            pointer = ctypes.c_void_p
            def function(name, result, arguments):
                value = getattr(library, 'pyjs.gc.' + name)
                value.restype, value.argtypes = result, arguments
                return value
            state = _Heap()
            heap = ctypes.byref(state)
            if {action!r} == 'pop_out_of_order':
                first, second = _Frame(), _Frame()
                push = function('frame.push', None, [pointer, pointer, pointer, ctypes.c_int64])
                push(heap, ctypes.byref(first), None, 0)
                push(heap, ctypes.byref(second), None, 0)
                function('frame.pop', None, [pointer, pointer])(heap, ctypes.byref(first))
            else:
                value = 1
                if {action!r} == 'pin_allocation_failure':
                    denied = ctypes.c_bool.in_dll(library, 'test_deny_allocations')
                    denied.value = False
                    value = function('alloc', pointer, [pointer, ctypes.c_int64])(heap, 8)
                    denied.value = True
                function('pin', None, [pointer, pointer])(heap, value)
        ''')], capture_output=True, timeout=10)
        assert execution.returncode in (-signal.SIGILL, -signal.SIGTRAP), (
            action, execution.returncode, execution.stderr.decode(),
        )


@pytest.mark.parametrize("optimize", [0, 2])
def test_unmanaged_copy_and_void_helper_calls(tmp_path, optimize):
    source = ("declare void @llvm.memcpy.p0.p0.i64(ptr, ptr, i64, i1)\n"
              "declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)\n") + "\n".join(
        compile_runtime({"copy_and_read": _copy_and_read, "write_byte": _write_byte, "fill_bytes": _fill_bytes}),
    )
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, optimize=optimize, shared=True)))
    function = library.copy_and_read
    function.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
    function.restype = ctypes.c_int64
    for implementation in (_copy_and_read, function):
        source = (ctypes.c_int64 * 2)(42, 73)
        destination = (ctypes.c_int64 * 3)()
        arguments = (ctypes.addressof(destination), ctypes.addressof(source))
        if implementation is _copy_and_read:
            arguments = tuple(Pointer(address) for address in arguments)
        assert implementation(*arguments, 16) == 141
        assert list(destination) == [42, 73, 99]
    for runtime in (runtime_functions({"write_byte": _write_byte}),
                    runtime_functions({"write_byte": _write_byte}, library)):
        storage = (ctypes.c_uint8 * 3)(17, 0, 19)
        for value in range(-260, 261):
            runtime("write_byte", Pointer(ctypes.addressof(storage) + 1), value)
            assert list(storage) == [17, value & 255, 19]
    operations = {"fill_bytes": _fill_bytes}
    for runtime in (runtime_functions(operations), runtime_functions(operations, library)):
        for size in (0, 1, 5):
            for value in (-257, -1, 0, 32, 255, 256):
                storage = (ctypes.c_uint8 * 7)(*([17] * 7))
                runtime("fill_bytes", Pointer(ctypes.addressof(storage) + 1), value, size)
                assert list(storage) == [17] + [value & 255] * size + [17] * (6 - size)


@llvm.inline("call ptr @malloc(i64 {size})")
def _opaque_allocate(size: int) -> Pointer:
    raise NotImplementedError


@_runtime
def _unexpected_allocate(size: int) -> Pointer:
    return _opaque_allocate(size)


@llvm.inline("store ptr {value}, ptr {slot}")
def _opaque_store(slot: Pointer, value: Pointer) -> None:
    raise NotImplementedError


@_runtime
def _unexpected_store(value: Pointer) -> None:
    _opaque_store(value, value)


@_runtime
def _unexpected_collection(value: Pointer) -> Pointer:
    gc_collect()
    return value


@pytest.mark.parametrize("function", [_unexpected_allocate, _unexpected_store, _unexpected_collection])
def test_raw_pointer_support_does_not_authorize_implicit_effects(function):
    with pytest.raises(LLVMUnsupported, match="runtime helper"):
        compile_runtime({"invalid": function})
