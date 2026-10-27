import ctypes
from itertools import product

import pytest

from pyjs import int8
from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import arena, mappings, values
from pyjs.native.runtime.pointers import Pointer
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions, runtime_library, string


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def mapping_runtime(request, tmp_path_factory):
    operations = {
        "pyjs.dict.new.owned": mappings.new_mapping,
        "pyjs.dict.new.typed": mappings.new_typed_mapping,
        "pyjs.dict.set.slot": mappings.set_slot,
        "pyjs.dict.append.hashed": mappings.append_hashed,
        "pyjs.dict.remove.index": mappings.remove_index,
        "pyjs.dict.find.hashed": mappings.find_hashed,
        "pyjs.dict.find": mappings.find,
        "pyjs.dict.lookup": mappings.lookup,
        "pyjs.dict.pop.into": mappings.pop_into,
        "pyjs.dict.copy": mappings.copy_mapping,
        "pyjs.dict.copy.keys": mappings.copy_keys,
        "pyjs.dict.replace": mappings.replace,
        "pyjs.dict.update": mappings.update,
        "pyjs.dict.update.hashed": mappings.update_hashed,
        "pyjs.dict.clear": mappings.clear,
        "pyjs.dict.try.reserve": mappings.reserve,
        "pyjs.dict.track.order": mappings.track_order,
        "pyjs.dict.repr.index": mappings.repr_index,
        "pyjs.dict.popitem.order": mappings.popitem_order,
        "pyjs.set.subset": mappings.subset,
        "pyjs.set.relation.hashed": mappings.relation_hashed,
        "pyjs.set.intersect": mappings.intersect,
        "pyjs.set.discard.hashed": mappings.discard_hashed,
        "pyjs.set.toggle.hashed": mappings.toggle_hashed,
        "pyjs.set.symmetric.difference": mappings.symmetric_difference,
    }
    library = runtime_library(request, tmp_path_factory,
                              lambda: transpile_llvm('def main() -> int: return len({1: 2})'))
    return runtime_functions(operations, library)


def test_integer_find_keeps_full_width_first_match_and_empty_safety(mapping_runtime):
    keys = (ctypes.c_int64 * 6)(-9223372036854775808, 0, 4294967296,
                              9223372036854775807, -1, 0)
    header = mappings._Dict(length=len(keys), capacity=len(keys), keys=ctypes.addressof(keys))
    value = Pointer(ctypes.addressof(header))
    for item, expected in [(-9223372036854775808, 0), (0, 1), (4294967296, 2),
                           (9223372036854775807, 3), (-1, 4), (1, -1), (4294967295, -1)]:
        query = ctypes.c_int64(item)
        assert mapping_runtime("pyjs.dict.find", value, Pointer(ctypes.addressof(query)), 8, int8(2)) == expected
    # Empty storage has no keys and need not dereference even the query.
    header.length = 0
    header.keys = None
    assert mapping_runtime("pyjs.dict.find", value, Pointer(0), 8, int8(2)) == -1


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_mapping_lookup_mutations_and_set_users(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def main() -> str:
            keys = [-9223372036854775808, 0, 4294967296, 9223372036854775807, -1]
            values: dict[int, int] = {}
            for key in keys:
                values[key] = values.get(key, 0) + 1
            for key in keys:
                values[key] = values[key] + 2
            before = values.copy()
            output = [repr(values)]
            for key in keys:
                output.append(str(values.pop(key)))
                output.append(str(values.get(key, -99)))
            output.append(str(len(values)))
            for key in keys:
                values.setdefault(key, 7)
                values.setdefault(key, 9)
            output.append(repr(values))
            del values[4294967296]
            values[4294967296] = 10
            output.append(repr(values))
            output.append(repr(before))
            members = {0, 4294967296, -1}
            output.append(str(1 in members))
            output.append(str(4294967296 in members))
            members.discard(4294967296)
            output.append(str(4294967296 in members))
            members.add(4294967296)
            output.append(str(4294967296 in members))
            values.clear()
            output.append(str(values.get(-1, 42)))
            return "|".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_distinct_mapping_payload_owners_survive_growth_and_failure(mapping_runtime):
    _check_mapping_payload_owners(mapping_runtime)


@pytest.mark.parametrize("optimize", [0, 2])
def test_managed_mapping_preserves_foreign_payload_owners(tmp_path, optimize):
    module = transpile_llvm('''
from pyjs.native import gc_collect
def main() -> int:
    gc_collect()
    return len({1: 2})
''')
    library = ctypes.CDLL(str(LLVM().compile(module, tmp_path, shared=True, optimize=optimize)))
    _check_mapping_payload_owners(runtime_functions({
        "pyjs.dict.new.typed": mappings.new_typed_mapping,
        "pyjs.dict.track.order": mappings.track_order,
        "pyjs.dict.try.reserve": mappings.reserve,
    }, library))


def _check_mapping_payload_owners(mapping_runtime):
    buffers, requests = [], []
    fail_value = False

    def allocation(name, context, size):
        assert context == 123
        requests.append((name, size))
        if name == "value" and fail_value:
            return None
        buffers.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(buffers[-1])

    signature = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    key_callback = signature(lambda context, size: allocation("key", context, size))
    value_callback = signature(lambda context, size: allocation("value", context, size))
    key_owner = Pointer(ctypes.cast(key_callback, ctypes.c_void_p).value)
    value_owner = Pointer(ctypes.cast(value_callback, ctypes.c_void_p).value)
    value = mapping_runtime("pyjs.dict.new.typed", Pointer(0), key_owner, value_owner, Pointer(123), 8, 8)
    header = mappings._Dict.from_address(value.address)
    assert requests == [("key", mappings.SIZE), ("key", 32), ("value", 32)]
    assert header.allocator == key_owner.address and header.value_allocator == value_owner.address
    assert mapping_runtime("pyjs.dict.track.order", Pointer(0), value)
    assert requests[-1] == ("key", 32)
    before = bytes(header)
    fail_value = True
    assert not mapping_runtime("pyjs.dict.try.reserve", Pointer(0), value, 9, 8, 8)
    assert bytes(header) == before
    assert requests[-2:] == [("key", 72), ("value", 72)]
    fail_value = False
    assert mapping_runtime("pyjs.dict.try.reserve", Pointer(0), value, 9, 8, 8)
    assert requests[-3:] == [("key", 72), ("value", 72), ("key", 72)]
    assert header.capacity == 9


def test_mapping_mutations_match_python_and_erase_dead_slots(mapping_runtime):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    key = ctypes.c_int64()
    key_pointer = Pointer(ctypes.addressof(key))
    output = ctypes.c_int64()
    output_pointer = Pointer(ctypes.addressof(output))
    try:
        value = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), 8, 8)
        header = mappings._Dict.from_address(value.address)
        expected = {}

        def check():
            keys = list((ctypes.c_int64 * header.length).from_address(header.keys))
            values = list((ctypes.c_int64 * header.length).from_address(header.values))
            assert list(zip(keys, values, strict=True)) == list(expected.items())

        for item in list(range(33)) + [2, 1, 0, 32, 10]:
            key.value = item
            slot = mapping_runtime("pyjs.dict.set.slot", owner, value, key_pointer, 8, 8, int8(2))
            expected[item] = item * 7
            ctypes.c_int64.from_address(slot.address).value = expected[item]
            check()
        for item in [0, 16, 32, -1, 99, 16]:
            key.value = item
            output.value = -42
            found = item in expected
            assert mapping_runtime("pyjs.dict.pop.into", value, key_pointer, 8, 8, int8(2), output_pointer) == found
            assert output.value == expected.pop(item, -42)
            check()
            assert ctypes.c_int64.from_address(header.keys + header.length * 8).value == 0
            assert ctypes.c_int64.from_address(header.values + header.length * 8).value == 0
        key.value = 0
        slot = mapping_runtime("pyjs.dict.set.slot", owner, value, key_pointer, 8, 8, int8(2))
        ctypes.c_int64.from_address(slot.address).value = 999
        expected[0] = 999
        check()
        duplicate = mapping_runtime("pyjs.dict.copy", owner, Pointer(0), Pointer(0), value, 8, 8, int8(2))
        other = mappings._Dict.from_address(duplicate.address)
        assert value.address != duplicate.address
        assert header.keys != other.keys and header.values != other.values
        mapping_runtime("pyjs.dict.update", owner, value, value, 8, 8, int8(2))
        check()
        old_length = header.length
        mapping_runtime("pyjs.dict.clear", value, 8, 8)
        assert header.length == 0
        assert ctypes.string_at(header.keys, old_length * 8) == bytes(old_length * 8)
        assert ctypes.string_at(header.values, old_length * 8) == bytes(old_length * 8)
        mapping_runtime("pyjs.dict.update", owner, value, duplicate, 8, 8, int8(2))
        check()
        mapping_runtime("pyjs.dict.clear", duplicate, 8, 8)
        assert mapping_runtime("pyjs.dict.replace", owner, value, duplicate, 8, 8)
        assert header.length == 0
        assert ctypes.string_at(header.keys, old_length * 8) == bytes(old_length * 8)
        assert ctypes.string_at(header.values, old_length * 8) == bytes(old_length * 8)
        assert mapping_runtime("pyjs.dict.replace", owner, value, value, 8, 8)
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("tracked", [False, True])
@pytest.mark.parametrize("hashed", [False, True])
def test_mapping_growth_failure_does_not_publish_partial_buffers(mapping_runtime, tracked, hashed):
    buffers = []
    requests = []
    fail_at = 0

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        assert context == 123
        requests.append(size)
        if len(requests) == fail_at:
            return None
        buffer = ctypes.create_string_buffer(size)
        buffers.append(buffer)
        return ctypes.addressof(buffer)

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    value = mapping_runtime("pyjs.dict.new.owned", Pointer(0), allocator, Pointer(123), 8, 8)
    header = mappings._Dict.from_address(value.address)
    key = ctypes.c_int64(123)
    if hashed:
        slot = mapping_runtime("pyjs.dict.append.hashed", Pointer(0), value,
                               Pointer(ctypes.addressof(key)), 8, 8, 321)
    else:
        slot = mapping_runtime("pyjs.dict.set.slot", Pointer(0), value, Pointer(ctypes.addressof(key)), 8, 8, int8(2))
    ctypes.c_int64.from_address(slot.address).value = 456
    if tracked:
        fail_at = len(requests) + 1
        before = bytes(header)
        assert not mapping_runtime("pyjs.dict.track.order", Pointer(0), value)
        assert bytes(header) == before
        fail_at = 0
        assert mapping_runtime("pyjs.dict.track.order", Pointer(0), value)
    original = bytes(header)
    source_keys = (ctypes.c_int64 * 9)(*range(9))
    source_values = (ctypes.c_int64 * 9)(*range(9))
    source = mappings._Dict(9, 9, ctypes.addressof(source_keys), ctypes.addressof(source_values), None, None)
    for allocation in range(1, 3 + int(tracked) + int(hashed)):
        fail_at = len(requests) + allocation
        assert not mapping_runtime("pyjs.dict.try.reserve", Pointer(0), value, 100, 8, 8)
        assert bytes(header) == original
        assert ctypes.c_int64.from_address(header.keys).value == 123
        assert ctypes.c_int64.from_address(header.values).value == 456
        if tracked:
            assert ctypes.c_int64.from_address(header.order).value == 0
        if hashed:
            assert ctypes.c_int64.from_address(header.hashes).value == 321
        fail_at = len(requests) + allocation
        assert not mapping_runtime("pyjs.dict.replace", Pointer(0), value, Pointer(ctypes.addressof(source)), 8, 8)
        assert bytes(header) == original
        assert ctypes.c_int64.from_address(header.keys).value == 123
        assert ctypes.c_int64.from_address(header.values).value == 456
    fail_at = 0
    assert mapping_runtime("pyjs.dict.try.reserve", Pointer(0), value, 100, 8, 8)
    assert header.capacity == 100 and header.length == 1
    assert ctypes.c_int64.from_address(header.keys).value == 123
    assert ctypes.c_int64.from_address(header.values).value == 456
    if hashed:
        assert ctypes.c_int64.from_address(header.hashes).value == 321
    before = len(requests)
    for required, key_size, value_size in ((-1, 8, 8), (1 << 62, 8, 8), (200, 0, 8), (200, 8, -1)):
        assert not mapping_runtime("pyjs.dict.try.reserve", Pointer(0), value, required, key_size, value_size)
    assert len(requests) == before


def test_cached_fromkeys_allocation_failure_keeps_target_empty_and_retryable(mapping_runtime):
    retained, requests = [], []
    fail_at = 0

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        requests.append(size)
        if len(requests) == fail_at:
            return None
        retained.append(ctypes.create_string_buffer(size))
        return ctypes.addressof(retained[-1])

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    source_keys = (ctypes.c_void_p * 9)(*range(1, 10))
    source_hashes = (ctypes.c_int64 * 9)(*range(101, 110))
    source = mappings._Dict(9, 9, ctypes.addressof(source_keys), None, None, None,
                            None, 0, ctypes.addressof(source_hashes))
    default = ctypes.c_int64(42)
    for failed_allocation in (1, 2, 3):
        target = mapping_runtime("pyjs.dict.new.owned", Pointer(0), allocator, Pointer(0), 8, 8)
        header = mappings._Dict.from_address(target.address)
        fail_at = len(requests) + failed_allocation
        arguments = (Pointer(0), target, Pointer(ctypes.addressof(source)), 8, 8,
                     Pointer(ctypes.addressof(default)))
        assert not mapping_runtime("pyjs.dict.copy.keys", *arguments)
        assert header.length == 0
        fail_at = 0
        assert mapping_runtime("pyjs.dict.copy.keys", *arguments)
        assert header.length == 9
        assert list((ctypes.c_int64 * 9).from_address(header.values)) == [42] * 9
        assert list((ctypes.c_void_p * 9).from_address(header.keys)) == list(source_keys)
        assert list((ctypes.c_int64 * 9).from_address(header.hashes)) == list(source_hashes)
        assert header.keys != source.keys and header.hashes != source.hashes


def test_unicode_and_boolean_keys_use_value_equality(mapping_runtime):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    try:
        for kind, key_type, keys in (
            (1, ctypes.c_bool, [True, False, True]),
            (3, ctypes.c_void_p, ["é😀\0".encode(), b"other", "é😀\0".encode()]),
        ):
            storage = []
            key_size = ctypes.sizeof(key_type)
            value = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), key_size, 8)
            for index, raw_key in enumerate(keys):
                if kind == 3:
                    storage.append(string(raw_key))
                    key = key_type(ctypes.addressof(storage[-1]))
                else:
                    key = key_type(raw_key)
                pointer = Pointer(ctypes.addressof(key))
                slot = mapping_runtime("pyjs.dict.set.slot", owner, value, pointer, key_size, 8, int8(kind))
                ctypes.c_int64.from_address(slot.address).value = index
                found = mapping_runtime("pyjs.dict.lookup", value, pointer, key_size, 8, int8(kind))
                assert found.address == slot.address
            assert mappings._Dict.from_address(value.address).length == 2
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("kind, key_type", [
    (5, values._OptionalBool), (6, values._OptionalInt), (10, values._OptionalFloat),
])
def test_optional_keys_compare_presence_before_payload(mapping_runtime, kind, key_type):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    width = ctypes.sizeof(key_type)
    try:
        value = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), width, 8)
        for index, key in enumerate([key_type(False, 0), key_type(True, 0), key_type(False, 1)]):
            slot = mapping_runtime("pyjs.dict.set.slot", owner, value,
                                   Pointer(ctypes.addressof(key)), width, 8, int8(kind))
            ctypes.c_int64.from_address(slot.address).value = index
        # Absent values ignore even a noncanonical payload; False/0 are present
        # and must remain different from None.
        assert mappings._Dict.from_address(value.address).length == 2
        for key, expected in [(key_type(False, 0), 2), (key_type(True, 0), 1)]:
            found = mapping_runtime("pyjs.dict.lookup", value, Pointer(ctypes.addressof(key)),
                                    width, 8, int8(kind))
            assert ctypes.c_int64.from_address(found.address).value == expected
    finally:
        arena.destroy_arena(owner)


def test_cached_key_hashes_follow_growth_copy_removal_and_clear(mapping_runtime):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    try:
        value = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), 8, 8)
        header = mappings._Dict.from_address(value.address)
        assert not header.hashes
        for index in range(17):
            key = ctypes.c_int64(index)
            slot = mapping_runtime("pyjs.dict.append.hashed", owner, value,
                                   Pointer(ctypes.addressof(key)), 8, 8, 1000 + index)
            ctypes.c_int64.from_address(slot.address).value = index * 2
        expected = list(range(1000, 1017))
        assert list((ctypes.c_int64 * 17).from_address(header.hashes)) == expected
        copied = mapping_runtime("pyjs.dict.copy", owner, Pointer(0), Pointer(0), value, 8, 8, int8(2))
        other = mappings._Dict.from_address(copied.address)
        assert other.hashes != header.hashes
        assert list((ctypes.c_int64 * 17).from_address(other.hashes)) == expected
        mapping_runtime("pyjs.dict.remove.index", value, 3, 8, 8)
        del expected[3]
        assert list((ctypes.c_int64 * 16).from_address(header.hashes)) == expected
        assert ctypes.c_int64.from_address(header.hashes + 16 * 8).value == 0
        assert ctypes.c_int64.from_address(other.hashes + 3 * 8).value == 1003
        mapping_runtime("pyjs.dict.clear", value, 8, 8)
        assert ctypes.string_at(header.hashes, 16 * 8) == bytes(16 * 8)
        assert mapping_runtime("pyjs.dict.replace", owner, value, copied, 8, 8)
        assert header.length == 17
        assert list((ctypes.c_int64 * 17).from_address(header.hashes)) == list(range(1000, 1017))
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("action, expected", [("none", 0), ("clear", -1), ("grow", 0),
                                               ("remove", -1), ("raise", -2)])
def test_hashed_lookup_rechecks_storage_after_callbacks(mapping_runtime, action, expected):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    exception = ctypes.c_bool(False)
    exception_pointer = Pointer(ctypes.addressof(exception))
    retained = [ctypes.c_int64(1), ctypes.c_int64(1)]
    first = ctypes.c_void_p(ctypes.addressof(retained[0]))
    query = ctypes.c_void_p(ctypes.addressof(retained[1]))
    first_pointer, query_pointer = Pointer(ctypes.addressof(first)), Pointer(ctypes.addressof(query))
    calls = []
    try:
        value = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), 8, 8)
        slot = mapping_runtime("pyjs.dict.append.hashed", owner, value, first_pointer, 8, 8, 1)
        ctypes.c_int64.from_address(slot.address).value = 10

        @ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_void_p] * 5))
        def compare(arena_pointer, heap, pending, left, right):
            calls.append((ctypes.c_void_p.from_address(left).value,
                          ctypes.c_void_p.from_address(right).value))
            if len(calls) == 1:
                if action == "clear":
                    mapping_runtime("pyjs.dict.clear", value, 8, 8)
                elif action == "remove":
                    mapping_runtime("pyjs.dict.remove.index", value, 0, 8, 8)
                elif action == "grow":
                    for index in range(10):
                        retained.append(ctypes.c_int64(index + 10))
                        key = ctypes.c_void_p(ctypes.addressof(retained[-1]))
                        extra = mapping_runtime("pyjs.dict.append.hashed", owner, value,
                                                Pointer(ctypes.addressof(key)), 8, 8, 10 + index)
                        ctypes.c_int64.from_address(extra.address).value = index
                elif action == "raise":
                    ctypes.c_bool.from_address(pending).value = True
            return 1

        callback = Pointer(ctypes.cast(compare, ctypes.c_void_p).value)
        def find(key, hashed):
            return mapping_runtime("pyjs.dict.find.hashed", owner, Pointer(0), exception_pointer,
                                    value, key, hashed, callback, 8)
        assert find(first_pointer, 1) == 0 and calls == []
        assert find(query_pointer, 99) == -1 and calls == []
        assert find(query_pointer, 1) == expected
        assert len(calls) == (2 if action == "grow" else 1)
        assert exception.value == (action == "raise")
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("action", ["tag", "payload", "unequal", "raise"])
def test_tagged_lookup_checks_both_words_without_equating_payload_bits(mapping_runtime, action):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    exception = ctypes.c_bool(False)
    key = (ctypes.c_int64 * 2)(3, 123)
    pointer = Pointer(ctypes.addressof(key))
    seen = []
    try:
        value = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), 16, 8)
        slot = mapping_runtime("pyjs.dict.append.hashed", owner, value, pointer, 16, 8, 1)
        ctypes.c_int64.from_address(slot.address).value = 10

        @ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_void_p] * 5))
        def compare(arena_pointer, heap, pending, left, right):
            words = (ctypes.c_int64 * 2).from_address(left)
            seen.append(tuple(words))
            if len(seen) == 1:
                if action in {"tag", "payload"}:
                    words[action == "payload"] += 1
                elif action == "raise":
                    ctypes.c_bool.from_address(pending).value = True
            # Identical tagged bits are not sufficient for equality (NaN).
            return int(action != "unequal")

        callback = Pointer(ctypes.cast(compare, ctypes.c_void_p).value)
        found = mapping_runtime("pyjs.dict.find.hashed", owner, Pointer(0),
                                Pointer(ctypes.addressof(exception)), value, pointer, 1, callback, 16)
        assert found == (-2 if action == "raise" else -1 if action == "unequal" else 0)
        assert seen == ([(3, 123), (4, 123)] if action == "tag" else
                        [(3, 123), (3, 124)] if action == "payload" else [(3, 123)])
        assert exception.value == (action == "raise")
    finally:
        arena.destroy_arena(owner)


@pytest.mark.parametrize("operation", ["discard", "toggle"])
@pytest.mark.parametrize("tracked", [False, True])
def test_checked_set_allocation_failure_preserves_publication_rules(mapping_runtime, operation, tracked):
    buffers = []
    fail = False

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def allocate(context, size):
        if fail:
            return None
        buffer = ctypes.create_string_buffer(size)
        buffers.append(buffer)
        return ctypes.addressof(buffer)

    @ctypes.CFUNCTYPE(ctypes.c_int64, *([ctypes.c_void_p] * 5))
    def compare(arena_pointer, heap, pending, left, right):
        return int(ctypes.c_int64.from_address(left).value == ctypes.c_int64.from_address(right).value)

    allocator = Pointer(ctypes.cast(allocate, ctypes.c_void_p).value)
    callback = Pointer(ctypes.cast(compare, ctypes.c_void_p).value)

    def build(items):
        result = mapping_runtime("pyjs.dict.new.owned", Pointer(0), allocator, Pointer(0), 8, 1)
        for item in items:
            key = ctypes.c_int64(item)
            slot = mapping_runtime("pyjs.dict.append.hashed", Pointer(0), result,
                                   Pointer(ctypes.addressof(key)), 8, 1, item)
            ctypes.c_bool.from_address(slot.address).value = True
        return result

    def keys(value):
        header = mappings._Dict.from_address(value.address)
        return list((ctypes.c_int64 * header.length).from_address(header.keys))

    target = build([0])
    source_values = list(range(20 if operation == "discard" else 6))
    source = build(source_values)
    if tracked:
        assert mapping_runtime("pyjs.dict.track.order", Pointer(0), source)
    fail = True
    assert mapping_runtime(f"pyjs.set.{operation}.hashed", Pointer(0), Pointer(0), Pointer(0),
                           target, source, callback, 8) == 0
    # Failed prefilter/cursor allocation is atomic. Once cursor storage exists,
    # toggle still publishes completed keys before a later growth failure.
    assert keys(target) == ([1, 2, 3, 4] if operation == "toggle" and tracked else [0])
    assert keys(source) == source_values
    fail = False
    before = set(keys(target))
    assert mapping_runtime(f"pyjs.set.{operation}.hashed", Pointer(0), Pointer(0), Pointer(0),
                           target, source, callback, 8) == 1
    expected = before - set(source_values) if operation == "discard" else before ^ set(source_values)
    assert set(keys(target)) == expected


def test_checked_mapping_scans_distinguish_cursor_allocation_failure(mapping_runtime):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))
    key = ctypes.c_int64(7)

    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def fail_allocate(context, size):
        return None

    try:
        left = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), 8, 1)
        right = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), 8, 1)
        for value in (left, right):
            slot = mapping_runtime("pyjs.dict.append.hashed", owner, value,
                                   Pointer(ctypes.addressof(key)), 8, 1, 7)
            ctypes.c_bool.from_address(slot.address).value = True
        header = mappings._Dict.from_address(left.address)
        header.allocator = ctypes.cast(fail_allocate, ctypes.c_void_p).value
        # Cursor setup must fail before invoking the comparison callback.
        assert mapping_runtime("pyjs.set.relation.hashed", owner, Pointer(0), Pointer(0),
                               left, right, Pointer(0), int8(0), 8) == -3
        assert mapping_runtime("pyjs.dict.update.hashed", owner, Pointer(0), Pointer(0),
                               right, left, 1, Pointer(0), 8) == 0
        assert header.length == 1 and not header.order
        assert mappings._Dict.from_address(right.address).length == 1
        header.allocator = None
        assert mapping_runtime("pyjs.dict.track.order", owner, left)
    finally:
        arena.destroy_arena(owner)


def test_set_algebra_matches_python_and_clears_removed_references(mapping_runtime):
    state = arena._Arena()
    owner = Pointer(ctypes.addressof(state))

    def build(values):
        result = mapping_runtime("pyjs.dict.new.owned", owner, Pointer(0), Pointer(0), 8, 1)
        for value in values:
            key = ctypes.c_int64(value)
            slot = mapping_runtime("pyjs.dict.set.slot", owner, result, Pointer(ctypes.addressof(key)), 8, 1, int8(2))
            ctypes.c_bool.from_address(slot.address).value = True
        return result

    def check(pointer, expected, previous_length):
        header = mappings._Dict.from_address(pointer.address)
        assert set((ctypes.c_int64 * header.length).from_address(header.keys)) == expected
        assert header.length == len(expected)
        if header.length < previous_length:
            removed = previous_length - header.length
            assert ctypes.string_at(header.keys + header.length * 8, removed * 8) == bytes(removed * 8)
            assert ctypes.string_at(header.values + header.length, removed) == bytes(removed)

    try:
        samples = [set(), {1}, {2, 3}, {1, 2, 3}, set(range(12))]
        for a, b in product(samples, repeat=2):
            left, right = build(a), build(b)
            assert mapping_runtime("pyjs.set.subset", left, right, 8, int8(2), False) == (a <= b)
            assert mapping_runtime("pyjs.set.subset", left, right, 8, int8(2), True) == a.isdisjoint(b)
            for difference in (False, True):
                value = build(a)
                mapping_runtime("pyjs.set.intersect", value, right, 8, int8(2), difference)
                check(value, a - b if difference else a & b, len(a))
            value = build(a)
            assert mapping_runtime("pyjs.dict.replace", owner, value, right, 8, 1)
            check(value, b, len(a))
            value = build(a)
            assert mapping_runtime("pyjs.set.symmetric.difference", owner, value, right, 8, int8(2))
            check(value, a ^ b, len(a))
            assert mapping_runtime("pyjs.set.symmetric.difference", owner, value, value, 8, int8(2))
            check(value, set(), len(a ^ b))
    finally:
        arena.destroy_arena(owner)
