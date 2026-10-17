import ctypes
from itertools import combinations, combinations_with_replacement, permutations, product

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import heap, iteration, roots
from pyjs.native.runtime.combinatorics import (
    COMBINATIONS,
    PERMUTATIONS,
    PRODUCT,
    REPLACEMENT,
)
from pyjs.native.runtime.pointers import Pointer
from pyjs.native.runtime.sequences import _List
from pyjs.native.runtime.traces import _Exception
from tests.native.runtime_support import runtime_functions, runtime_library, string


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def iterator_runtime(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm('''
        def main() -> int:
            return next(iter([1]))
    '''))
    return runtime_functions({"pyjs.iterator.new": iteration.create, "pyjs.iterator.pooled": iteration.create_pool,
                              "pyjs.iterator.tee": iteration.create_tee,
                              "pyjs.iterator.tee.typed": iteration.create_typed_tee,
                              "pyjs.iterator.group": iteration.create_group,
                              "pyjs.iterator.group.typed": iteration.create_typed_group,
                              "pyjs.iterator.group.trace": iteration.trace_group_workspace,
                              "pyjs.iterator.next": iteration.advance,
                              "pyjs.iterator.next.context": iteration.advance_context,
                              "pyjs.iterator.consume.stop": iteration.consume_stop}, library)


def test_consumed_stop_clears_payload_roots_but_other_statuses_preserve_the_record(iterator_runtime):
    error = _Exception(True, 123, 456, 789, 100, 200)
    context = (ctypes.c_void_p * 3)(None, None, ctypes.addressof(error))
    original = bytes(error)
    for status in (1, 0, iteration.CALLBACK_ERROR):
        assert iterator_runtime("pyjs.iterator.consume.stop", status, Pointer(ctypes.addressof(context))) == status
        assert bytes(error) == original
    assert iterator_runtime("pyjs.iterator.consume.stop", iteration.CALLBACK_STOP,
                            Pointer(ctypes.addressof(context))) == 0
    assert bytes(error) == bytes(ctypes.sizeof(error))


@pytest.fixture
def iterator_memory(iterator_runtime):
    buffers = []
    state = {"remaining": 0}

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(owner, size):
        assert owner == 123
        if state["remaining"]:
            state["remaining"] -= 1
            if not state["remaining"]:
                return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    def create(kind, source, index=0, limit=0, step=1, size=8):
        if kind == iteration.TUPLE:
            source = _List(limit, limit, ctypes.addressof(source), None, None)
            buffers.append(source)
        pointer = iterator_runtime("pyjs.iterator.new", Pointer(0),
                                   Pointer(ctypes.cast(allocate, ctypes.c_void_p).value), Pointer(123),
                                   kind, Pointer(ctypes.addressof(source)), index, limit, step, size)
        return pointer, iteration._State.from_address(pointer.address) if pointer.address else None

    return create, state


def test_rows_have_an_independent_foreign_owner_and_retry_before_advancing(iterator_runtime, iterator_memory):
    create, allocations = iterator_memory
    values = (ctypes.c_int64 * 2)(5, 6)
    source, source_header = create(iteration.TUPLE, values, limit=2)
    parent, header = create(iteration.ENUMERATE, source_header, index=10)
    offset = ctypes.c_int64(8)
    header.row_size, header.offsets = 16, ctypes.addressof(offset)
    buffers, owners = [], []

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate_row(owner, size):
        owners.append(owner)
        if len(owners) == 1:
            return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    header.row_allocator = ctypes.cast(allocate_row, ctypes.c_void_p).value
    allocations["remaining"] = 1  # The auxiliary allocator must not be called.
    output = ctypes.c_void_p()
    arguments = (parent, Pointer(ctypes.addressof(output)))
    assert iterator_runtime("pyjs.iterator.next", *arguments) == -1
    assert (header.index, source_header.index) == (10, 0)
    assert iterator_runtime("pyjs.iterator.next", *arguments) == 1
    row = _List.from_address(output.value)
    assert row.length == 2
    assert tuple((ctypes.c_int64 * 2).from_address(row.items)) == (10, 5)
    assert owners == [123, 123] and allocations["remaining"] == 1


def test_tee_block_failure_is_retryable_and_nested_forks_share_history(iterator_runtime, iterator_memory):
    create, allocations = iterator_memory
    values = (ctypes.c_int64 * 70)(*range(70))
    source, source_header = create(iteration.TUPLE, values, limit=70)

    def fork(source, count):
        row = iterator_runtime("pyjs.iterator.tee", Pointer(0), Pointer(source_header.allocator), Pointer(123),
                               source, count, 8)
        data = _List.from_address(row.address).items
        return [Pointer(value) for value in (ctypes.c_void_p * count).from_address(data)]

    first, second = fork(source, 2)
    header = iteration._State.from_address(first.address)
    original = header.source
    output = ctypes.c_int64()

    def read(cursor):
        status = iterator_runtime("pyjs.iterator.next", cursor, Pointer(ctypes.addressof(output)))
        return status, output.value

    for value in range(iteration.TEE_CAPACITY):
        assert read(first) == (1, value)
    allocations["remaining"] = 1
    assert read(first)[0] == -1
    assert header.source == original and source_header.index == iteration.TEE_CAPACITY
    assert read(first) == (1, iteration.TEE_CAPACITY)
    assert header.source != original
    third, fourth = fork(first, 2)
    for cursor in (third, fourth):
        child = iteration._State.from_address(cursor.address)
        assert child.source == header.source and child.index == header.index
    assert read(second) == (1, 0)
    for cursor in (first, third, fourth):
        assert read(cursor) == (1, iteration.TEE_CAPACITY + 1)
    assert source_header.index == iteration.TEE_CAPACITY + 2


def test_typed_tee_history_has_an_independent_retryable_owner(iterator_runtime, iterator_memory):
    create, allocations = iterator_memory
    values = (ctypes.c_int64 * 40)(*range(40))
    source, header = create(iteration.TUPLE, values, limit=40)
    buffers, owners = [], []

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def history(owner, size):
        owners.append(owner)
        if len(owners) == 2:
            return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    row = iterator_runtime("pyjs.iterator.tee.typed", Pointer(0), Pointer(header.allocator), Pointer(123),
                           source, 1, 8, Pointer(ctypes.cast(history, ctypes.c_void_p).value))
    cursor = Pointer(ctypes.c_void_p.from_address(_List.from_address(row.address).items).value)
    output = ctypes.c_int64()
    arguments = (cursor, Pointer(ctypes.addressof(output)))
    allocations["remaining"] = 1  # Cursor allocator must not allocate history.
    for value in range(iteration.TEE_CAPACITY):
        assert iterator_runtime("pyjs.iterator.next", *arguments) == 1
        assert output.value == value
    assert iterator_runtime("pyjs.iterator.next", *arguments) == -1
    assert header.index == iteration.TEE_CAPACITY
    assert iterator_runtime("pyjs.iterator.next", *arguments) == 1
    assert output.value == iteration.TEE_CAPACITY
    assert owners == [123, 123, 123] and allocations["remaining"] == 1


def test_group_trace_selects_only_active_and_typed_payload_lanes(iterator_runtime):
    # Keep this wire-format oracle independent of the emitter/runtime constants:
    # exercise all scalar/reference/tagged pairs, not a shared decoding helper.
    stride = 16
    words = (ctypes.c_int64 * ((iteration.GROUP_VALUES + 3 * stride) // 8))()
    words[0] = stride
    words[iteration.GROUP_ACTIVE // 8] = 101
    words[iteration.GROUP_KEY_ALLOCATOR // 8] = 202
    start = iteration.GROUP_VALUES // 8
    words[start:] = [301, 302, 401, 402, 501, 502]
    for item in range(3):
        for key in range(3):
            words[iteration.GROUP_LAYOUT // 8] = item | (key << 2)
            expected = [101, (0, 301, 302)[item], (0, 401, 402)[key], (0, 501, 502)[key]]
            actual = [iterator_runtime("pyjs.iterator.group.trace", Pointer(ctypes.addressof(words)), i).address
                      for i in range(4)]
            assert actual == expected


@pytest.mark.parametrize("failure", [1, 2, 3], ids=["cursor", "target", "row"])
@pytest.mark.parametrize("item_words,key_words", [(1, 1), (1, 2), (2, 1), (2, 2)])
def test_group_publication_failure_keeps_pending_item(iterator_runtime, iterator_memory, failure, item_words, key_words):
    create, allocations = iterator_memory
    # Distinct tag/payload words make truncation or overlap observable without
    # depending on compiler tag assignments. Use the real workspace constructor.
    item_type = ctypes.c_int64 * item_words
    key_type = ctypes.c_int64 * key_words
    values = (item_type * 3)(*(item_type(*([123] * (item_words - 1) + [value])) for value in range(1, 4)))
    source, source_header = create(iteration.TUPLE, values, limit=3, size=ctypes.sizeof(item_type))
    parent = iterator_runtime("pyjs.iterator.group", Pointer(0), Pointer(source_header.allocator), Pointer(123),
                              source, ctypes.sizeof(item_type), ctypes.sizeof(key_type))
    header = iteration._State.from_address(parent.address)
    stride = ctypes.c_int64.from_address(header.children).value
    assert stride == 8 * max(item_words, key_words)
    header.row_size, header.strict = ctypes.sizeof(key_type) + 8, ctypes.sizeof(key_type)
    seen = []
    observed_roots = []
    compared = []

    @ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_void_p] * 5))
    def key(arena, heap, exception, state, output):
        value = item_type.from_address(output)[-1]
        seen.append(value)
        key_type.from_address(output + stride)[:] = [456] * (key_words - 1) + [(value - 1) // 2 + 7]
        frame = roots._Frame.from_address(managed.roots)
        addresses = (ctypes.c_void_p * frame.count).from_address(frame.slots)
        # Scratch starts after the rooted state pointer. Both complete padded
        # slots must stay rooted across callbacks, including each payload word.
        observed_roots.append((frame.count, list(addresses)[1:] == list(range(output, output + 2 * stride, 8))))
        return 1

    @ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_void_p] * 5))
    def equal(arena, heap, exception, left, right):
        pair = list(key_type.from_address(left)), list(key_type.from_address(right))
        compared.append(pair)
        return 2 if pair[0] == pair[1] else 1

    header.advance = ctypes.cast(key, ctypes.c_void_p).value
    header.offsets = ctypes.cast(equal, ctypes.c_void_p).value
    managed = heap._Heap()
    context = (ctypes.c_void_p * 3)(123, ctypes.addressof(managed), 456)
    output = ctypes.c_void_p()

    def read(cursor, output):
        return iterator_runtime("pyjs.iterator.next.context", cursor, Pointer(ctypes.addressof(output)),
                                Pointer(ctypes.addressof(context)))

    allocations["remaining"] = failure
    assert read(parent, output) == -1
    assert source_header.index == 1 and seen == [1]
    assert header.index == 1 and header.limit == 0
    assert read(parent, output) == 1
    row = _List.from_address(output.value).items
    assert list(key_type.from_address(row)) == [456] * (key_words - 1) + [7] and seen == [1]
    group = Pointer(ctypes.c_void_p.from_address(row + header.strict).value)
    item = item_type()
    assert read(group, item) == 1 and list(item) == [123] * (item_words - 1) + [1]
    allocations["remaining"] = failure
    assert read(parent, output) == -1
    # A failed parent advance invalidates its old cursor immediately, before
    # the next group is published, without consuming the pending item again.
    comparison_count = len(compared)
    assert read(group, item) == 0
    assert len(compared) == comparison_count
    assert source_header.index == 3 and seen == [1, 2, 3] and header.index == 1
    assert read(parent, output) == 1
    row = _List.from_address(output.value).items
    assert list(key_type.from_address(row)) == [456] * (key_words - 1) + [8]
    following = Pointer(ctypes.c_void_p.from_address(row + header.strict).value)
    assert read(following, item) == 1 and list(item) == [123] * (item_words - 1) + [3]
    assert read(group, item) == 0
    assert seen == [1, 2, 3] and managed.roots is None
    assert observed_roots == [(1 + 2 * stride // 8, True)] * len(seen)


def test_callback_context_roots_partial_rows_and_propagates_failures(iterator_runtime, iterator_memory):
    create, _ = iterator_memory
    observed = []
    status = {"value": 1}
    managed = heap._Heap()
    context = (ctypes.c_void_p * 3)(123, ctypes.addressof(managed), 456)

    @ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_void_p] * 5))
    def callback(arena, current_heap, exception, state, output):
        frame = roots._Frame.from_address(managed.roots)
        addresses = (ctypes.c_void_p * frame.count).from_address(frame.slots)
        rooted = [ctypes.c_void_p.from_address(address).value for address in addresses]
        observed.append((arena, current_heap, exception, frame.count, all(rooted)))
        ctypes.c_int64.from_address(output).value = 42
        return status["value"]

    source = (ctypes.c_int64 * 2)(10, 20)
    first, header = create(iteration.CALLBACK, source)
    header.advance = ctypes.cast(callback, ctypes.c_void_p).value
    second, second_header = create(iteration.TUPLE, source, limit=2)
    children = (ctypes.c_void_p * 2)(first.address, second.address)
    offsets = (ctypes.c_int64 * 2)(0, 8)
    parent, header = create(iteration.ZIP, source)
    header.children = ctypes.addressof(children)
    header.count = 2
    header.offsets = ctypes.addressof(offsets)
    header.row_size = 16
    output = ctypes.c_void_p()
    result = iterator_runtime("pyjs.iterator.next.context", parent, Pointer(ctypes.addressof(output)),
                              Pointer(ctypes.addressof(context)))
    assert result == 1 and second_header.index == 1 and managed.roots is None
    row = _List.from_address(output.value)
    assert list((ctypes.c_int64 * 2).from_address(row.items)) == [42, 10]
    status["value"] = iteration.CALLBACK_ERROR
    result = iterator_runtime("pyjs.iterator.next.context", parent, Pointer(ctypes.addressof(output)),
                              Pointer(ctypes.addressof(context)))
    assert result == iteration.CALLBACK_ERROR and second_header.index == 1
    assert observed == [(123, ctypes.addressof(managed), 456, 2, True)] * 2
    assert managed.roots is None


def test_range_iteration_near_machine_boundaries(iterator_runtime, iterator_memory):
    create, _ = iterator_memory
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    for start, stop, step, reverse in product(
        (minimum, -1, 0, maximum), (minimum, 0, 1, maximum), (minimum, -3, 1, maximum), (False, True),
    ):
        source = (ctypes.c_int64 * 3)(start, stop, step)
        pointer, header = create(iteration.REVERSE_RANGE if reverse else iteration.RANGE, source, start, stop, step)
        expected = reversed(range(start, stop, step)) if reverse else iter(range(start, stop, step))
        output = (ctypes.c_int64 * 3)(123, 0, 456)
        for _ in range(5):
            value = next(expected, None)
            status = iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output) + 8))
            assert output[0] == 123 and output[2] == 456
            assert status == (0 if value is None else 1)
            if value is not None:
                assert output[1] == value
            else:
                assert header.exhausted and header.source is None


def test_text_allocation_failures_retry_the_same_character(iterator_runtime, iterator_memory):
    create, allocator = iterator_memory
    source = string("é😀".encode())
    allocator["remaining"] = 1
    assert create(iteration.TEXT, source)[0].address == 0
    for reverse in (False, True):
        pointer, header = create(iteration.TEXT, source, source.length - 1 if reverse else 0,
                                 source.length, -1 if reverse else 1)
        output = ctypes.c_void_p()
        for value in reversed("é😀") if reverse else "é😀":
            # A character header and its UTF-8 data share one allocation.
            before = bytes(header)
            allocator["remaining"] = 1
            status = iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output)))
            assert status == -1
            assert bytes(header) == before
            assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 1
            text = ctypes.cast(output, ctypes.POINTER(type(source))).contents
            assert ctypes.string_at(text.data, text.length).decode() == value
        assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 0
        assert header.source is None


def test_enumerate_row_failure_and_overflow_keep_child_state_coherent(iterator_runtime, iterator_memory):
    create, allocator = iterator_memory
    source = (ctypes.c_int64 * 2)(10, 20)
    child, child_header = create(iteration.TUPLE, source, limit=2)
    offsets = (ctypes.c_int64 * 1)(8)
    pointer, header = create(iteration.ENUMERATE, source, index=(1 << 63) - 1)
    header.source = child.address
    header.offsets = ctypes.addressof(offsets)
    header.row_size = 16
    output = ctypes.c_void_p()
    allocator["remaining"] = 1
    assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == -1
    assert child_header.index == 0
    assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 1
    row = _List.from_address(output.value)
    assert row.length == 2
    assert list((ctypes.c_int64 * 2).from_address(row.items)) == [(1 << 63) - 1, 10]
    assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == -3
    assert child_header.index == 2
    assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 0
    assert header.source is None and header.children is None


def test_pooled_runtime_allocation_atomicity_and_terminal_exhaustion(iterator_runtime):
    buffers = []
    countdown = {"remaining": 0}

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(owner, size):
        if countdown["remaining"]:
            countdown["remaining"] -= 1
            if not countdown["remaining"]:
                return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    items = (ctypes.c_int64 * 3)(10, 20, 30)
    pool = _List(3, 3, ctypes.addressof(items), None, None)
    pools = (ctypes.c_void_p * 2)(ctypes.addressof(pool), ctypes.addressof(pool))
    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    for mode, expected in ((PRODUCT, list(product(items, repeat=2))),
                           (COMBINATIONS, list(combinations(items, 2))),
                           (REPLACEMENT, list(combinations_with_replacement(items, 2))),
                           (PERMUTATIONS, list(permutations(items, 2)))):
        for failure in range(1, 6):
            countdown["remaining"] = failure
            pointer = iterator_runtime("pyjs.iterator.pooled", Pointer(0), allocator, Pointer(0), mode,
                                       Pointer(ctypes.addressof(pools)), 2 if mode == PRODUCT else 1, 2, 8)
            if pointer.address:
                break
        else:
            pytest.fail("pooled constructor did not recover from allocation failures")
        countdown["remaining"] = 0
        header = iteration._State.from_address(pointer.address)
        output = ctypes.c_void_p()
        rows = []
        retained = []
        for _ in range(len(expected) + 1):
            before = bytes(header)
            countdown["remaining"] = 1
            assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == -1
            assert bytes(header) == before
            countdown["remaining"] = 0
            status = iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output)))
            if status == 0:
                break
            assert status == 1
            row = _List.from_address(output.value)
            retained.append(row)
            rows.append(tuple((ctypes.c_int64 * row.length).from_address(row.items)))
        assert rows == expected
        assert [tuple((ctypes.c_int64 * row.length).from_address(row.items)) for row in retained] == expected
        assert header.exhausted and header.source is None and header.children is None
        assert header.offsets is None
        assert list(items) == [10, 20, 30]
        before = len(buffers)
        for _ in range(3):
            assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 0
        assert len(buffers) == before


def test_slice_roots_source_released_by_nested_exhaustion(iterator_runtime, iterator_memory):
    create, _ = iterator_memory
    managed = heap._Heap()
    context = (ctypes.c_void_p * 3)(123, ctypes.addressof(managed), 456)
    nesting = {"active": False, "status": 1}
    observed = []

    @ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_void_p] * 5))
    def callback(arena, current_heap, exception, state, output):
        if nesting["active"]:
            return 0
        nesting["active"] = True
        nested = ctypes.c_int64()
        status = iterator_runtime("pyjs.iterator.next.context", pointer, Pointer(ctypes.addressof(nested)),
                                  Pointer(ctypes.addressof(context)))
        frame = roots._Frame.from_address(managed.roots)
        slots = (ctypes.c_void_p * frame.count).from_address(frame.slots)
        rooted = [ctypes.c_void_p.from_address(slot).value for slot in slots]
        observed.append((status, header.source, header.exhausted, rooted))
        ctypes.c_int64.from_address(output).value = 42
        return nesting["status"]

    source = (ctypes.c_int64 * 1)(0)
    child, child_header = create(iteration.CALLBACK, source)
    child_header.advance = ctypes.cast(callback, ctypes.c_void_p).value
    for status in (1, 0, iteration.CALLBACK_ERROR):
        pointer, header = create(iteration.ISLICE, source, limit=-1)
        header.source = child.address
        nesting.update(active=False, status=status)
        output = ctypes.c_int64()
        assert iterator_runtime("pyjs.iterator.next.context", pointer, Pointer(ctypes.addressof(output)),
                                Pointer(ctypes.addressof(context))) == status
        assert observed[-1] == (0, None, 1, [child.address, pointer.address])
        assert managed.roots is None
        if status == 1:
            assert output.value == 42


def test_slice_limits_consume_without_overflow(iterator_runtime, iterator_memory):
    create, _ = iterator_memory
    for start, stop, step in ((0, 2, (1 << 63) - 1), (3, 1, 1), (1, -1, 2)):
        source = (ctypes.c_int64 * 5)(0, 1, 2, 3, 4)
        child, child_header = create(iteration.TUPLE, source, limit=5)
        pointer, header = create(iteration.ISLICE, source, index=start, limit=stop, step=step)
        header.source = child.address
        header.count = start
        output = ctypes.c_int64()
        values = []
        while iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 1:
            values.append(output.value)
        assert values == list(range(5))[start:None if stop < 0 else stop:step]
        assert child_header.index == (5 if stop < 0 else max(start, stop))
        assert header.exhausted and header.source is None


@pytest.mark.parametrize("strict", [False, True])
def test_batch_row_failure_is_retryable_and_strict_tail_is_terminal(iterator_runtime, iterator_memory, strict):
    create, allocator = iterator_memory
    source = (ctypes.c_int64 * 3)(10, 20, 30)
    child, child_header = create(iteration.TUPLE, source, limit=3)
    pointer, header = create(iteration.BATCHED, source)
    header.source, header.count, header.row_size, header.strict = child.address, 2, 16, strict
    output = ctypes.c_void_p()
    allocator["remaining"] = 1
    assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == -1
    assert child_header.index == 0 and not header.exhausted
    assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 1
    row = _List.from_address(output.value)
    assert row.length == 2 and list((ctypes.c_int64 * 2).from_address(row.items)) == [10, 20]
    result = iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output)))
    assert result == (iteration.INCOMPLETE_BATCH if strict else 1)
    if not strict:
        row = _List.from_address(output.value)
        assert row.length == 1 and ctypes.c_int64.from_address(row.items).value == 30
    assert header.exhausted and header.source is None
    assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 0


def test_batch_row_overflow_precedes_allocator_and_child_access(iterator_runtime, iterator_memory):
    create, allocator = iterator_memory
    source = (ctypes.c_int64 * 2)(10, 20)
    child, child_header = create(iteration.TUPLE, source, limit=2)
    pointer, header = create(iteration.BATCHED, source)
    header.source, header.count = child.address, (1 << 63) - 1
    output = ctypes.c_void_p(123)
    allocator["remaining"] = 1
    for _retry in range(2):
        assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == -1
        assert output.value == 123 and child_header.index == 0
        assert not header.exhausted and allocator["remaining"] == 1
    # The private runtime state remains usable; public callers cannot resize it.
    header.count = 2
    allocator["remaining"] = 0
    assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 1
    row = _List.from_address(output.value)
    assert row.length == 2 and list((ctypes.c_int64 * 2).from_address(row.items)) == [10, 20]


def test_repeat_returns_same_pointer_and_releases_it_on_exhaustion(iterator_runtime, iterator_memory):
    create, _ = iterator_memory
    item = ctypes.c_int64(123)
    source = ctypes.c_void_p(ctypes.addressof(item))
    for count in (0, 2, -1):
        pointer, header = create(iteration.REPEAT, source, limit=count)
        output = ctypes.c_void_p()
        for index in range(3):
            status = iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output)))
            assert status == int(count < 0 or index < count)
            if status:
                assert output.value == ctypes.addressof(item)
            else:
                assert header.exhausted and header.source is None


def test_zip_partial_child_failure_is_retryable_without_rewinding(iterator_runtime, iterator_memory):
    create, allocator = iterator_memory
    # The tuple row and coallocated character each allocate once.
    for failure in (1, 2):
        numbers = (ctypes.c_int64 * 3)(1, 2, 3)
        text = string("é😀".encode())
        left, left_state = create(iteration.TUPLE, numbers, limit=3)
        right, right_state = create(iteration.TEXT, text, limit=text.length)
        children = (ctypes.c_void_p * 2)(left.address, right.address)
        offsets = (ctypes.c_int64 * 2)(0, 8)
        pointer, header = create(iteration.ZIP, numbers)
        header.children = ctypes.addressof(children)
        header.offsets = ctypes.addressof(offsets)
        header.count = 2
        header.row_size = 16
        output = ctypes.c_void_p()
        allocator["remaining"] = failure
        assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == -1
        assert left_state.index == (0 if failure == 1 else 1)
        assert right_state.index == 0
        assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 1
        row_header = _List.from_address(output.value)
        assert row_header.length == 2
        row = (ctypes.c_int64 * 2).from_address(row_header.items)
        assert row[0] == (1 if failure == 1 else 2)
        character = type(text).from_address(row[1])
        assert ctypes.string_at(character.data, character.length).decode() == "é"


def test_cycle_growth_failure_and_cached_storage(iterator_runtime, iterator_memory):
    create, allocator = iterator_memory
    numbers = (ctypes.c_int64 * 6)(1, 2, 3, 4, 5, 6)
    source, source_header = create(iteration.TUPLE, numbers, limit=6)
    pointer, header = create(iteration.CYCLE, numbers)
    saved = _List(0, 0, None, header.allocator, header.owner)
    header.source = source.address
    header.children = ctypes.addressof(saved)
    output = ctypes.c_int64()
    target = Pointer(ctypes.addressof(output))
    for value in range(1, 5):
        assert iterator_runtime("pyjs.iterator.next", pointer, target) == 1
        assert output.value == value
    allocator["remaining"] = 1
    assert iterator_runtime("pyjs.iterator.next", pointer, target) == -1
    assert saved.length == 4 and source_header.index == 5
    assert iterator_runtime("pyjs.iterator.next", pointer, target) == 1 and output.value == 6
    assert saved.length == 5
    for expected in [1, 2, 3, 4, 6] * 2:
        assert iterator_runtime("pyjs.iterator.next", pointer, target) == 1
        assert output.value == expected
        assert header.source is None and header.children == ctypes.addressof(saved)
    assert iterator_runtime("pyjs.iterator.next", source, target) == 0


def test_zip_longest_allocation_failure_vs_source_failure(iterator_runtime, iterator_memory):
    create, allocator = iterator_memory
    numbers = (ctypes.c_int64 * 3)(1, 2, 3)
    text = string("é😀".encode())
    filler = (ctypes.c_int64 * 2)(0, 0)
    offsets = (ctypes.c_int64 * 3)(0, 8, 16)
    for failure in (1, 2):
        left, left_header = create(iteration.TUPLE, numbers, limit=3)
        right, right_header = create(iteration.TEXT, text, limit=text.length)
        children = (ctypes.c_void_p * 2)(left.address, right.address)
        pointer, header = create(iteration.ZIP_LONGEST, numbers, limit=2)
        header.children = ctypes.addressof(children)
        header.callback = ctypes.addressof(filler)
        header.count = 2
        header.offsets = ctypes.addressof(offsets)
        header.row_size = 16
        output = ctypes.c_void_p()
        allocator["remaining"] = failure
        target = Pointer(ctypes.addressof(output))
        assert iterator_runtime("pyjs.iterator.next", pointer, target) == -1
        if failure == 1:
            assert left_header.index == 0 and right_header.index == 0
            assert not header.exhausted
            assert iterator_runtime("pyjs.iterator.next", pointer, target) == 1
            row = _List.from_address(output.value)
            assert ctypes.c_int64.from_address(row.items).value == 1
        else:
            assert left_header.index == 1 and right_header.index == 0
            assert header.exhausted and header.children is None and header.callback is None
            assert iterator_runtime("pyjs.iterator.next", pointer, target) == 0


@pytest.mark.parametrize("left_words,right_words", [(1, 2), (2, 1)])
@pytest.mark.parametrize("short_left", [False, True])
def test_zip_longest_copies_complete_column_fill_slots(iterator_runtime, iterator_memory,
                                                     left_words, right_words, short_left):
    create, _ = iterator_memory
    left = (ctypes.c_int64 * (2 * left_words))(*range(11, 11 + 2 * left_words))
    right = (ctypes.c_int64 * (2 * right_words))(*range(21, 21 + 2 * right_words))
    filler = (ctypes.c_int64 * (left_words + right_words))(*range(101, 101 + left_words + right_words))
    offsets = (ctypes.c_int64 * 3)(0, left_words * 8, ctypes.sizeof(filler))
    a, _ = create(iteration.TUPLE, left, limit=1 if short_left else 2, size=left_words * 8)
    b, _ = create(iteration.TUPLE, right, limit=2 if short_left else 1, size=right_words * 8)
    children = (ctypes.c_void_p * 2)(a.address, b.address)
    cursor, header = create(iteration.ZIP_LONGEST, left, limit=2)
    header.children = ctypes.addressof(children)
    header.callback = ctypes.addressof(filler)
    header.count = 2
    header.offsets = ctypes.addressof(offsets)
    header.row_size = ctypes.sizeof(filler)
    output = ctypes.c_void_p()
    target = Pointer(ctypes.addressof(output))
    for index in range(2):
        assert iterator_runtime("pyjs.iterator.next", cursor, target) == 1
        row = _List.from_address(output.value)
        expected_left = list(filler[:left_words]) if index and short_left else list(left[index * left_words:(index + 1) * left_words])
        expected_right = list(filler[left_words:]) if index and not short_left else list(right[index * right_words:(index + 1) * right_words])
        assert list((ctypes.c_int64 * (left_words + right_words)).from_address(row.items)) == expected_left + expected_right
    assert iterator_runtime("pyjs.iterator.next", cursor, target) == 0


def test_count_scalar_state_and_machine_boundary(iterator_runtime, iterator_memory):
    create, _ = iterator_memory
    unused = ctypes.c_int64()
    pointer, header = create(iteration.COUNT_INT, unused, index=2**63-2, step=1)
    output = ctypes.c_int64()
    for expected in [2**63-2, 2**63-1, -(2**63), -(2**63)+1]:
        assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 1
        assert output.value == expected
        assert not header.exhausted
    values = (ctypes.c_double * 2)(1.5, -0.25)
    pointer, _ = create(iteration.COUNT_FLOAT, values)
    output = ctypes.c_double()
    for expected in [1.5, 1.25, 1.0, 0.75]:
        assert iterator_runtime("pyjs.iterator.next", pointer, Pointer(ctypes.addressof(output))) == 1
        assert output.value == expected
