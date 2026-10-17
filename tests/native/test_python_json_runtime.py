"""The escaping and indentation kernels run unchanged in CPython and LLVM."""

import ctypes
import errno
import json as reference

import pytest

from pyjs import int8, int32
from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import (
    arena,
    buffers,
    escaping,
    formatting,
    identity,
    json_state,
    sequences,
    text,
)
from pyjs.native.runtime.pointers import Pointer, byte_offset, load_integer, load_pointer
from tests.native.runtime_support import runtime_functions, runtime_library, string


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def json_runtime(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory,
                              lambda: transpile_llvm('import json\ndef main() -> str: return json.dumps([1])'))
    return runtime_functions({"pyjs.json.write.string": escaping.write_json,
                              "pyjs.repr.write.string": escaping.write_repr,
                              "pyjs.json.indent": formatting.indent,
                              "pyjs.text.output.initialize": formatting.initialize,
                              "pyjs.text.output.finish": formatting.finish,
                              "pyjs.text.output.destroy": formatting.destroy,
                              "pyjs.native.output.try.new": buffers.new_output,
                              "pyjs.native.output.try.finish.memory": buffers.finish_memory,
                              "pyjs.identity.try.new": identity.new_map,
                              "pyjs.list.new.owned": sequences.new_list,
                              "pyjs.json.push": json_state.push, "pyjs.json.pop": json_state.pop,
                              "pyjs.json.scalar.index": json_state.scalar_index,
                              "pyjs.json.run": json_state.run}, library)


@pytest.mark.parametrize("check_circular", [False, True])
def test_json_frames_bound_depth_detect_cycles_and_reuse_siblings(json_runtime, check_circular):
    scratch = arena._Arena()
    owner = Pointer(ctypes.addressof(scratch))
    state = json_state._State(scratch=owner.address, check_circular=check_circular)
    pointer = Pointer(ctypes.addressof(state))
    try:
        state.active = json_runtime("pyjs.identity.try.new", owner).address
        assert state.active
        for depth in range(1000):
            assert json_runtime("pyjs.json.push", pointer, Pointer(0), Pointer(depth + 1), depth) == 0
        assert json_runtime("pyjs.json.push", pointer, Pointer(0), Pointer(1001), 1000) == 2
        # A repeated value is a cycle even at the depth limit, if enabled.
        assert json_runtime("pyjs.json.push", pointer, Pointer(0), Pointer(1), 1000) == (1 if check_circular else 2)
        for _ in range(1000):
            json_runtime("pyjs.json.pop", pointer)
        assert not state.head and identity._Map.from_address(state.active).length == 0
        reusable = state.free
        for _ in range(1000):
            assert json_runtime("pyjs.json.push", pointer, Pointer(0), Pointer(1), 0) == 0
            assert state.head == reusable
            frame = json_state._Frame.from_address(state.head)
            assert frame.written == 0 and not frame.snapshot and not frame.indices
            frame.written = 7  # The next sibling must not inherit punctuation state.
            frame.snapshot, frame.indices = 99, 100
            json_runtime("pyjs.json.pop", pointer)
            assert state.free == reusable
    finally:
        arena.destroy_arena(owner)


def test_json_pending_roots_follow_active_frames_and_clear_popped_slots(json_runtime):
    scratch = arena._Arena()
    owner = Pointer(ctypes.addressof(scratch))
    roots = json_runtime("pyjs.list.new.owned", owner, Pointer(0), Pointer(0), 8, 0)
    state = json_state._State(scratch=owner.address, roots=roots.address)
    pointer = Pointer(ctypes.addressof(state))
    try:
        for value in range(1, 8):
            assert json_runtime("pyjs.json.push", pointer, Pointer(0), Pointer(value), value - 1) == 0
            header = sequences._List.from_address(roots.address)
            slots = (ctypes.c_void_p * header.length).from_address(header.items)
            assert list(slots) == [item for previous in range(1, value + 1) for item in (previous, None)]
        for remaining in range(6, -1, -1):
            header = sequences._List.from_address(roots.address)
            slots = (ctypes.c_void_p * header.length).from_address(header.items)
            slots[-1] = 123  # A walker installs a snapshot in the current frame's second slot.
            json_runtime("pyjs.json.pop", pointer)
            assert header.length == remaining * 2
            assert list(slots)[-2:] == [None, None]
        assert not state.head
    finally:
        arena.destroy_arena(owner)


def test_scalar_json_sort_reuses_sibling_buffer_and_bounds_growth(json_runtime):
    scratch = arena._Arena()
    owner = Pointer(ctypes.addressof(scratch))
    state = json_state._State(scratch=owner.address)
    state_pointer = Pointer(ctypes.addressof(state))
    saved_owner = None
    try:
        for values in ([2, 1], [4, 2, 1, 3], [3, 1, 1], [2, 1]) * 20:
            assert json_runtime("pyjs.json.push", state_pointer, Pointer(0), Pointer(1), 0) == 0
            frame = json_state._Frame.from_address(state.head)
            keys = (ctypes.c_int64 * len(values))(*values)
            positions = [json_runtime("pyjs.json.scalar.index", state_pointer, Pointer(state.head),
                                     Pointer(ctypes.addressof(keys)), len(values), 8, int8(2), index, True)
                         for index in range(len(values))]
            assert positions == sorted(range(len(values)), key=values.__getitem__)
            if saved_owner is not None:
                assert frame.sort_owner == saved_owner
                assert frame.sort_capacity == 4
            saved_owner = frame.sort_owner
            assert scratch.buffers == saved_owner
            assert load_pointer(Pointer(saved_owner)).address == 0  # Only one owner record.
            json_runtime("pyjs.json.pop", state_pointer)
        # Disabled sorting must not touch even invalid storage or allocate.
        empty = json_state._Frame()
        for index in range(4):
            assert json_runtime("pyjs.json.scalar.index", state_pointer, Pointer(ctypes.addressof(empty)),
                                Pointer(0), 4, 8, int8(2), index, False) == index
        assert not empty.sort_owner and empty.sort_capacity == 0
        # Reject impossible sizes before touching source pointers or resizing.
        assert json_runtime("pyjs.json.scalar.index", state_pointer, Pointer(ctypes.addressof(empty)),
                            Pointer(0), 288230376151711744, 8, int8(2), 0, True) == -1
        assert not empty.sort_owner
    finally:
        arena.destroy_arena(owner)
    assert not scratch.buffers


def test_json_driver_observes_error_and_keeps_pending_frames_for_cleanup(json_runtime):
    scratch = arena._Arena()
    owner = Pointer(ctypes.addressof(scratch))
    state = json_state._State(scratch=owner.address, check_circular=True)
    pointer = Pointer(ctypes.addressof(state))
    error = ctypes.c_bool(False)
    error_pointer = Pointer(ctypes.addressof(error))
    visits = []

    @ctypes.CFUNCTYPE(None, *([ctypes.c_void_p] * 6))
    def step(_arena, _heap, error_address, _output, state_address, frame_address):
        frame = json_state._Frame.from_address(frame_address)
        visits.append(frame.value)
        if frame.value == 1:
            # A parent schedules one child then returns to the driver.
            assert json_runtime("pyjs.json.push", Pointer(state_address),
                                Pointer(ctypes.cast(step, ctypes.c_void_p).value), Pointer(2), 1) == 0
        else:
            ctypes.c_bool.from_address(error_address).value = True

    try:
        state.active = json_runtime("pyjs.identity.try.new", owner).address
        assert json_runtime("pyjs.json.push", pointer, Pointer(ctypes.cast(step, ctypes.c_void_p).value), Pointer(1), 0) == 0
        json_runtime("pyjs.json.run", Pointer(0), Pointer(0), error_pointer, Pointer(0), pointer)
        assert visits == [1, 2] and error.value and state.head
        assert identity._Map.from_address(state.active).length == 2
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("value", ["", "'", '"', "both'\"", "".join(map(chr, range(512))),
                                  "é中😀\u2028\u200b\uffff\U0010ffff" * 400])
def test_python_representation_escaping(json_runtime, value):
    # The same Python-authored writer executes in CPython, O0 and O2; this
    # covers quote choice, every ASCII byte, Unicode categories and growth.
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    table = (ctypes.c_int32 * (2 * len(text.PRINTABLE_RANGES)))(
        *(item for pair in text.PRINTABLE_RANGES for item in pair))
    source = string(value.encode())
    try:
        target = json_runtime("pyjs.native.output.try.new", owner, int32(-1))
        json_runtime("pyjs.repr.write.string", target, Pointer(ctypes.addressof(source)),
                     Pointer(ctypes.addressof(table)), len(text.PRINTABLE_RANGES))
        result = json_runtime("pyjs.native.output.try.finish.memory", target)
        data = load_pointer(byte_offset(result, buffers.STRING_DATA_OFFSET))
        assert ctypes.string_at(data.address, load_integer(result)).decode() == repr(value)
    finally:
        arena.destroy_arena(owner)


def test_call_local_scratch_is_released_without_retaining_arena_buffers(json_runtime):
    state = arena._Arena()
    destination = Pointer(ctypes.addressof(state))
    output_record = buffers._Output()
    owner_record = (ctypes.c_void_p * 2)()
    target = Pointer(ctypes.addressof(output_record))
    owner = Pointer(ctypes.addressof(owner_record))
    source = string(b"hello")
    try:
        for _attempt in range(20):
            json_runtime("pyjs.text.output.initialize", target, owner)
            json_runtime("pyjs.json.write.string", target, Pointer(ctypes.addressof(source)), True)
            result = json_runtime("pyjs.text.output.finish", target, destination, Pointer(0), Pointer(0))
            json_runtime("pyjs.text.output.destroy", target)
            assert not output_record.data and not owner_record[1]
            assert not state.buffers
            data = load_pointer(byte_offset(result, buffers.STRING_DATA_OFFSET))
            assert ctypes.string_at(data.address, load_integer(result)) == b'"hello"'
    finally:
        arena.destroy_arena(destination)


@pytest.mark.parametrize("ensure_ascii", [False, True])
def test_escaping_boundaries_and_buffer_growth(json_runtime, ensure_ascii):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    # Include every ASCII control, UTF-8 width boundary and non-BMP surrogates.
    value = ("".join(map(chr, range(128))) + "é߿ࠀ中\uffff𐀀😀\U0010ffff") * 100
    source = string(value.encode())
    try:
        target = json_runtime("pyjs.native.output.try.new", owner, int32(-1))
        json_runtime("pyjs.json.write.string", target, Pointer(ctypes.addressof(source)), ensure_ascii)
        result = json_runtime("pyjs.native.output.try.finish.memory", target)
        data = load_pointer(byte_offset(result, buffers.STRING_DATA_OFFSET))
        assert ctypes.string_at(data.address, load_integer(result)).decode() == reference.dumps(value, ensure_ascii=ensure_ascii)
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("token,count,depth", [(None, 2, 3), (" ", 2, 3), ("→", 2, 3), ("", 2**63 - 1, 8),
                                              ("x", 0, 2**63 - 1), ("x", 2**63 - 1, 0)])
def test_indentation_without_intermediate_strings(json_runtime, token, count, depth):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    source = string(token.encode()) if token is not None else None
    try:
        target = json_runtime("pyjs.native.output.try.new", owner, int32(-1))
        json_runtime("pyjs.json.indent", target, Pointer(ctypes.addressof(source)) if source is not None else Pointer(0), count, depth)
        result = json_runtime("pyjs.native.output.try.finish.memory", target)
        data = load_pointer(byte_offset(result, buffers.STRING_DATA_OFFSET))
        expected = "" if token is None else "\n" + (token * (count * depth) if token and count and depth else "")
        assert ctypes.string_at(data.address, load_integer(result)).decode() == expected
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("length,count,depth", [(0, 2**63 - 1, 2), (0, 2**63 - 1, 1),
                                               (2**63 - 1, 0, 0), (0, -1, 1)])
def test_indentation_overflow_is_sticky_and_preserves_storage(json_runtime, length, count, depth):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    source = string(b"xx")
    try:
        target = json_runtime("pyjs.native.output.try.new", owner, int32(-1))
        buffer = buffers._Output.from_address(target.address)
        buffer.length = length
        before = (buffer.data, buffer.capacity, buffer.length, buffer.owner)
        json_runtime("pyjs.json.indent", target, Pointer(ctypes.addressof(source)), count, depth)
        assert buffer.error == errno.ENOMEM
        assert (buffer.data, buffer.capacity, buffer.length, buffer.owner) == before
        # Once failed, subsequent calls must not touch even invalid inputs.
        json_runtime("pyjs.json.indent", target, Pointer(0), 1, 1)
        json_runtime("pyjs.json.write.string", target, Pointer(0), True)
        assert json_runtime("pyjs.native.output.try.finish.memory", target).address == 0
    finally:
        arena.destroy_arena(owner)
