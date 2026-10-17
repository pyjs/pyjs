import ctypes
from itertools import product

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import arena, sequences
from pyjs.native.runtime.pointers import Pointer
from pyjs.native.runtime.sequences import _List
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def sequence_runtime(request, tmp_path_factory):
    operations = {
        "pyjs.tuple.trace": sequences.trace_tuple,
        "pyjs.tuple.new": sequences.new_tuple,
        "pyjs.tuple.concat": sequences.concat_tuple,
        "pyjs.list.new.owned": sequences.new_list,
        "pyjs.list.try.new.owned": sequences.try_new_list,
        "pyjs.list.try.append.slot": sequences.append_slot,
        "pyjs.list.try.extend": sequences.extend,
        "pyjs.list.concat": sequences.concat_list,
        "pyjs.list.try.repeat": sequences.repeat,
        "pyjs.list.slice": sequences.slice_copy,
        "pyjs.list.try.assign.slice": sequences.assign_slice,
        "pyjs.list.remove": sequences.remove_index,
        "pyjs.list.remove.slice": sequences.remove_slice,
        "pyjs.list.reverse": sequences.reverse,
    }
    library = runtime_library(request, tmp_path_factory,
                              lambda: transpile_llvm('def main() -> int: return len([1])'))
    return runtime_functions(operations, library)


def test_tuple_trace_excludes_header_metadata(sequence_runtime):
    words = sequences.TUPLE_DATA // 8
    storage = (ctypes.c_void_p * (words + 2))(*([123] * words), 456, 789)
    pointer = Pointer(ctypes.addressof(storage))
    assert [sequence_runtime("pyjs.tuple.trace", pointer, index).address
            for index in range(words + 2)] == [*([0] * words), 456, 789]


def test_tuple_payload_is_aligned_zeroed_and_allocated_atomically(sequence_runtime):
    allocations = []
    denied = False

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        assert context == 123
        if denied:
            return None
        allocations.append(ctypes.create_string_buffer(b"x" * size))
        return ctypes.addressof(allocations[-1])

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    for size, length in ((0, 0), (2, 2), (24, 3)):
        pointer = sequence_runtime("pyjs.tuple.new", Pointer(0), allocator, Pointer(123), size, length)
        header = _List.from_address(pointer.address)
        assert header.length == header.capacity == length
        assert header.items == pointer.address + sequences.TUPLE_DATA
        assert (header.items - pointer.address) % 16 == 0
        assert ctypes.string_at(header.items, size) == bytes(size)
    assert len(allocations) == 3
    for size in (-1, 9223372036854775807):
        assert not sequence_runtime("pyjs.tuple.new", Pointer(0), allocator, Pointer(123), size, 1).address
    denied = True
    assert not sequence_runtime("pyjs.tuple.new", Pointer(0), allocator, Pointer(123), 8, 1).address
    assert len(allocations) == 3


def test_tuple_concatenation_checks_size_before_allocation_and_keeps_aliases(sequence_runtime):
    buffers, requests = [], []
    denied = False

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        assert context == 123
        requests.append(size)
        if denied:
            return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    pointers = [sequence_runtime("pyjs.tuple.new", Pointer(0), allocator, Pointer(123), n * 8, n)
                for n in (0, 2, 1)]
    empty, left, right = pointers
    left_header, right_header = [_List.from_address(pointer.address) for pointer in (left, right)]
    (ctypes.c_int64 * 2).from_address(left_header.items)[:] = [11, 22]
    ctypes.c_int64.from_address(right_header.items).value = 33
    left_header.hash_cache = 91
    right_header.hash_cache = 92

    def concat(a, b, size=8):
        return sequence_runtime("pyjs.tuple.concat", Pointer(0), allocator, Pointer(123), a, b, size)

    denied = True
    before = len(requests)
    assert concat(empty, left).address == left.address
    assert concat(right, empty).address == right.address
    assert len(requests) == before
    assert not concat(left, right).address
    denied = False
    result = _List.from_address(concat(left, right).address)
    assert result.length == result.capacity == 3 and result.hash_cache == 0
    assert list((ctypes.c_int64 * 3).from_address(result.items)) == [11, 22, 33]
    assert left_header.hash_cache == 91 and right_header.hash_cache == 92
    before = len(requests)
    for size in (-1, 0, 9223372036854775807):
        assert not concat(left, right, size).address
    for length in (-1, 9223372036854775807, (9223372036854775807 - sequences.TUPLE_DATA) // 8):
        left_header.length = length
        assert not concat(left, right).address
    left_header.length = 2
    assert len(requests) == before
    assert list((ctypes.c_int64 * 2).from_address(left_header.items)) == [11, 22]


def test_list_concatenation_allocates_only_final_storage_and_never_aliases(sequence_runtime):
    buffers, requests = [], []
    fail_at = 0

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        assert context == 123
        requests.append(size)
        if len(requests) == fail_at:
            return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    source = sequence_runtime("pyjs.list.new.owned", Pointer(0), allocator, Pointer(123), 8, 3)
    header = _List.from_address(source.address)
    items = (ctypes.c_int64 * 3).from_address(header.items)
    items[:] = [11, 22, 33]
    saved = bytes(header)

    def concat():
        return sequence_runtime("pyjs.list.concat", Pointer(0), allocator, Pointer(123), source, source, 8)

    for stage in (1, 2):
        fail_at = len(requests) + stage
        assert not concat().address
        assert bytes(header) == saved and list(items) == [11, 22, 33]
    fail_at = 0
    before = len(requests)
    result = concat()
    copied = _List.from_address(result.address)
    assert result.address != source.address and copied.items != header.items
    assert copied.length == copied.capacity == 6 and copied.hash_cache == 0
    assert requests[before:] == [sequences.SIZE, 6 * 8]
    assert list((ctypes.c_int64 * 6).from_address(copied.items)) == [11, 22, 33] * 2
    ctypes.c_int64.from_address(copied.items).value = 99
    assert list(items) == [11, 22, 33]
    header.length = 0
    empty = concat()
    assert empty.address != source.address and _List.from_address(empty.address).length == 0


def test_allocating_list_operations_preserve_aliases_and_fail_atomically(sequence_runtime):
    calls, storage = [], []
    denied = False

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        assert context == 123
        calls.append(size)
        if denied:
            return None
        buffer = ctypes.create_string_buffer(size)
        storage.append(buffer)
        return ctypes.addressof(buffer)

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    value = sequence_runtime("pyjs.list.new.owned", Pointer(0), allocator, Pointer(123), 8, 4)
    header = _List.from_address(value.address)
    data = (ctypes.c_int64 * 4).from_address(header.items)
    data[:] = [1, 2, 3, 4]
    assert calls == [ctypes.sizeof(_List), 32]
    denied = True
    before = bytes(header)
    assert sequence_runtime("pyjs.list.try.append.slot", Pointer(0), value, 8).address == 0
    assert not sequence_runtime("pyjs.list.try.extend", Pointer(0), value, value, 8)
    assert not sequence_runtime("pyjs.list.try.repeat", Pointer(0), value, value, 8, 12)
    assert bytes(header) == before and list(data) == [1, 2, 3, 4]
    denied = False
    assert sequence_runtime("pyjs.list.try.extend", Pointer(0), value, value, 8)
    assert header.length == header.capacity == 8
    assert list((ctypes.c_int64 * 8).from_address(header.items)) == [1, 2, 3, 4] * 2
    assert list(data) == [1, 2, 3, 4]
    assert sequence_runtime("pyjs.list.try.repeat", Pointer(0), value, value, 8, 24)
    assert header.length == header.capacity == 24
    assert list((ctypes.c_int64 * 24).from_address(header.items)) == [1, 2, 3, 4] * 6
    slot = sequence_runtime("pyjs.list.try.append.slot", Pointer(0), value, 8)
    ctypes.c_int64.from_address(slot.address).value = 99
    assert header.length == 25 and header.capacity == 48
    assert list((ctypes.c_int64 * 25).from_address(header.items)) == [1, 2, 3, 4] * 6 + [99]


def test_list_factory_failure_initializes_only_traceable_state(sequence_runtime):
    for fail_at in (1, 2):
        buffers = []
        calls = []

        @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
        def allocate(context, size, fail_at=fail_at, calls=calls, buffers=buffers):
            calls.append(size)
            if len(calls) == fail_at:
                return None
            buffers.append(ctypes.create_string_buffer(b"!" * size))
            return ctypes.addressof(buffers[-1])

        allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
        assert sequence_runtime("pyjs.list.try.new.owned", Pointer(0), allocator, Pointer(123), 8, 4).address == 0
        if fail_at == 2:
            header = _List.from_buffer(buffers[0])
            assert header.length == header.capacity == 0 and header.items is None
            assert header.allocator == allocator.address and header.context == 123
        for item_size, length in ((8, -1), (8, (1 << 63) - 1), ((1 << 63) - 1, 0)):
            before = len(calls)
            assert sequence_runtime("pyjs.list.try.new.owned", Pointer(0), allocator, Pointer(123), item_size, length).address == 0
            assert len(calls) == before


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("factory,implementation,size", [
    ("pyjs.list.new.owned", sequences.new_list, 8),
    ("pyjs.tuple.new", sequences.new_tuple, 32),
], ids=["list", "tuple"])
def test_managed_sequence_factory_preserves_foreign_allocator_contract(tmp_path, optimize, factory, implementation, size):
    # Enabling GC must not reinterpret a nonnull foreign context as a heap or
    # replace the caller's callback with an internal header/data allocator.
    module = transpile_llvm('''
from pyjs.native import gc_collect
def main() -> int:
    gc_collect()
    return len([1])
''')
    library = ctypes.CDLL(str(LLVM().compile(module, tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions({factory: implementation}, library)
    buffers, contexts = [], []
    denied = False

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        contexts.append(context)
        if denied:
            return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    callback = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    value = invoke(factory, Pointer(0), callback, Pointer(123), size, 4)
    header = _List.from_address(value.address)
    separate = implementation is sequences.new_list
    assert contexts == ([123, 123] if separate else [123])
    assert header.items == (ctypes.addressof(buffers[1]) if separate else value.address + sequences.TUPLE_DATA)
    assert header.allocator == callback.address and header.context == 123
    denied = True
    assert not invoke(factory, Pointer(0), callback, Pointer(123), size, 4).address
    assert contexts[-1] == 123


@pytest.mark.parametrize("step", [1, 2, -2])
def test_slice_replacement_allocation_failure_keeps_target_unchanged(sequence_runtime, step):
    buffers = []
    requests = []
    fail_at = 0

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        requests.append(size)
        if len(requests) == fail_at:
            return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    value = sequence_runtime("pyjs.list.new.owned", Pointer(0), allocator, Pointer(0), 8, 4)
    header = _List.from_address(value.address)
    data = (ctypes.c_int64 * 4).from_address(header.items)
    data[:] = [1, 2, 3, 4]
    items = (ctypes.c_int64 * 2)(8, 9)
    replacement = _List(2, 2, ctypes.addressof(items))
    arguments = (Pointer(0), value, Pointer(ctypes.addressof(replacement)), 8,
                 0, False, 0, False, step, True)
    before = bytes(header)
    for allocation in (1, 2):
        fail_at = len(requests) + allocation
        assert not sequence_runtime("pyjs.list.try.assign.slice", *arguments)
        assert bytes(header) == before and list(data) == [1, 2, 3, 4]
    fail_at = 0
    assert sequence_runtime("pyjs.list.try.assign.slice", *arguments)
    expected = [1, 2, 3, 4]
    expected[::step] = [8, 9]
    assert list((ctypes.c_int64 * header.length).from_address(header.items)) == expected


def test_slice_copy_and_assignment_extreme_bounds_match_python(sequence_runtime):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    try:
        for values, start, stop, step in product(
            ([], [11, 22, 33, 44, 55, 66]),
            (None, minimum, -1, 0, 3, maximum),
            (None, minimum, -1, 0, 3, maximum),
            (None, minimum, -2, -1, 1, 2, maximum),
        ):
            selection = slice(start, stop, step)
            storage = (ctypes.c_int64 * len(values))(*values)
            header = _List(len(values), len(values), ctypes.addressof(storage))
            source = Pointer(ctypes.addressof(header))
            bounds = (start or 0, start is not None, stop or 0, stop is not None, step or 0, step is not None)
            result = sequence_runtime("pyjs.list.slice", owner, Pointer(0), Pointer(0), source, 8, *bounds)
            result_header = _List.from_address(result.address)
            actual = list((ctypes.c_int64 * result_header.length).from_address(result_header.items))
            assert actual == values[selection]
            assert result.address != source.address
            replacement = [100 + i for i in range(3 if step in (None, 1) else len(values[selection]))]
            replacement_storage = (ctypes.c_int64 * len(replacement))(*replacement)
            replacement_header = _List(len(replacement), len(replacement), ctypes.addressof(replacement_storage))
            expected = list(values)
            expected[selection] = replacement
            assert sequence_runtime("pyjs.list.try.assign.slice", owner, source,
                                    Pointer(ctypes.addressof(replacement_header)), 8, *bounds)
            assert list((ctypes.c_int64 * header.length).from_address(header.items)) == expected
            assert list(replacement_storage) == replacement
        for step in (1, -1):
            storage = (ctypes.c_int64 * 5)(1, 2, 3, 4, 5)
            header = _List(5, 5, ctypes.addressof(storage))
            source = Pointer(ctypes.addressof(header))
            assert sequence_runtime("pyjs.list.try.assign.slice", owner, source, source, 8, 0, False, 0, False, step, True)
            assert list((ctypes.c_int64 * 5).from_address(header.items)) == [1, 2, 3, 4, 5][::step]
    finally:
        arena.destroy_arena(owner)


def test_in_place_deletion_preserves_bounds_and_clears_spare_references(sequence_runtime):
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    for values, start, stop, step in product(
        ([], [11, 22, 33, 44, 55, 66]),
        (None, minimum, -6, -1, 0, 1, 3, 7, maximum),
        (None, minimum, -6, -1, 0, 1, 3, 7, maximum),
        (None, minimum, -4, -1, 0, 1, 2, maximum),
    ):
        storage = (ctypes.c_int64 * (len(values) + 2))(-999, *values, -999)
        header = _List(len(values), len(values), ctypes.addressof(storage) + 8)
        expected = list(values)
        if step != 0:
            del expected[start:stop:step]
        assert sequence_runtime("pyjs.list.remove.slice", Pointer(ctypes.addressof(header)), 8,
                                start or 0, start is not None, stop or 0, stop is not None,
                                step or 0, step is not None) == (step != 0)
        assert header.length == len(expected)
        assert list(storage) == [-999, *expected, *([0] * (len(values) - len(expected))), -999]


def test_index_deletion_and_reversal_use_the_same_backing_store(sequence_runtime):
    for values in ([], [1], [1, 2], [1, 2, 3, 4, 5]):
        for index in (-9223372036854775808, -6, -1, 0, 3, 9223372036854775807):
            storage = (ctypes.c_int64 * (len(values) + 2))(-999, *values, -999)
            header = _List(len(values), len(values), ctypes.addressof(storage) + 8)
            pointer = Pointer(ctypes.addressof(header))
            sequence_runtime("pyjs.list.reverse", pointer, 8)
            expected = values[::-1]
            valid = -len(values) <= index < len(values)
            assert sequence_runtime("pyjs.list.remove", pointer, index, 8) == valid
            if valid:
                del expected[index]
            assert header.length == len(expected)
            assert list(storage) == [-999, *expected, *([0] * (len(values) - len(expected))), -999]
