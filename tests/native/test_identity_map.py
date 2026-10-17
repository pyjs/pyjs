import ctypes

import pytest

from pyjs.native.runtime import arena, identity, memory
from pyjs.native.runtime.pointers import Pointer, null
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def identity_runtime(request, tmp_path_factory):
    functions = {
        "pyjs.identity.try.new": identity.new_map,
        "pyjs.identity.try.put": identity.put,
        "pyjs.identity.get": identity.get,
        "pyjs.identity.remove": identity.remove,
        "pyjs.arena.destroy": arena.destroy_arena,
    }
    library = None
    reject, calls = ctypes.c_bool(), ctypes.c_int64()
    with pytest.MonkeyPatch.context() as patch:
        if request.param is None:
            def allocate(state, size, alignment):
                calls.value += 1
                return null() if reject.value else arena.allocate_in_arena(state, size, alignment)
            patch.setattr(identity, "allocate_in_arena", allocate)
        else:
            source = "\n".join([
                "declare void @llvm.trap()",
                *memory.arena_runtime(), *memory.identity_map_runtime(),
            ])
            source = source.replace(
                "define ptr @pyjs.arena.try.alloc(", "define ptr @test.allocate(",
            ) + '''
                @test.reject = global i1 false
                @test.calls = global i64 0
                define ptr @pyjs.arena.try.alloc(ptr %arena, i64 %size, i64 %alignment) {
                  %calls = load i64, ptr @test.calls
                  %next = add i64 %calls, 1
                  store i64 %next, ptr @test.calls
                  %reject = load i1, ptr @test.reject
                  br i1 %reject, label %failed, label %allocate
                failed:
                  ret ptr null
                allocate:
                  %result = call ptr @test.allocate(ptr %arena, i64 %size, i64 %alignment)
                  ret ptr %result
                }
            '''
            library = ctypes.CDLL(str(LLVM().compile(
                source, tmp_path_factory.mktemp("identity-runtime"), shared=True, optimize=request.param,
            )))
            reject = ctypes.c_bool.in_dll(library, "test.reject")
            calls = ctypes.c_int64.in_dll(library, "test.calls")
        yield runtime_functions(functions, library), reject, calls


@pytest.fixture
def mapping(identity_runtime):
    invoke, reject, calls = identity_runtime
    state = arena._Arena()
    pointer = Pointer(ctypes.addressof(state))
    try:
        reject.value = True
        assert invoke("pyjs.identity.try.new", pointer).address == 0
        assert state.chunks is None
        reject.value = False
        result = invoke("pyjs.identity.try.new", pointer)
        yield invoke, pointer, result, identity._Map.from_address(result.address), reject, calls
    finally:
        reject.value = False
        invoke("pyjs.arena.destroy", pointer)
        assert state.chunks is None


def _bucket(address, mask):
    product = ((address >> 3) * -7046029254386353131) & ((1 << 64) - 1)
    return (product ^ (product >> 32)) & mask


def test_identity_map_collisions_growth_and_replacement(mapping):
    invoke, owner, pointer, state, reject, _ = mapping
    # Collide at the final bucket through four sizes, including wraparound.
    # These keys are intentionally not valid allocations: never dereference.
    keys = [address for address in range(8, 1 << 17, 8) if _bucket(address, 127) == 127][:96]
    assert len(keys) == 96
    expected = {}

    def verify():
        assert state.length == len(expected)
        for key in keys:
            assert invoke("pyjs.identity.get", pointer, Pointer(key)).address == expected.get(key, 0)
        assert invoke("pyjs.identity.get", pointer, Pointer(3)).address == 0

    verify()
    for key in keys:
        if state.length >= state.capacity // 2:
            before = bytes(state)
            reject.value = True
            assert not invoke("pyjs.identity.try.put", owner, pointer, Pointer(key), Pointer(key))
            reject.value = False
            assert bytes(state) == before
            verify()
        assert invoke("pyjs.identity.try.put", owner, pointer, Pointer(key), Pointer(key))
        expected[key] = key
    assert invoke("pyjs.identity.try.put", owner, pointer, Pointer(keys[0]), Pointer(5))
    expected[keys[0]] = 5
    verify()
    for key in keys[::2] + keys[1::2]:
        assert invoke("pyjs.identity.remove", pointer, Pointer(key))
        assert not invoke("pyjs.identity.remove", pointer, Pointer(key))
        del expected[key]
        verify()


def test_replacement_at_growth_threshold_does_not_allocate(mapping):
    invoke, owner, pointer, state, reject, calls = mapping
    for key in range(1, 9):
        assert invoke("pyjs.identity.try.put", owner, pointer, Pointer(key), Pointer(key))
    assert state.length == state.capacity // 2
    before, allocations = bytes(state), calls.value
    reject.value = True
    for value in (42, 0):
        assert invoke("pyjs.identity.try.put", owner, pointer, Pointer(1), Pointer(value))
        assert invoke("pyjs.identity.get", pointer, Pointer(1)).address == value
        assert bytes(state) == before and calls.value == allocations
    assert not invoke("pyjs.identity.try.put", owner, pointer, Pointer(9), Pointer(9))
    assert bytes(state) == before and calls.value == allocations + 1
    reject.value = False
    assert invoke("pyjs.identity.try.put", owner, pointer, Pointer(9), Pointer(9))
    assert state.length == 9 and state.capacity == 32
    for key in range(1, 10):
        assert invoke("pyjs.identity.get", pointer, Pointer(key)).address == (0 if key == 1 else key)


def test_mixed_cluster_null_values_and_bounded_churn(mapping):
    invoke, owner, pointer, state, _, _ = mapping
    last = [address for address in range(8, 2048, 8) if _bucket(address, 15) == 15]
    zero = next(address for address in range(8, 2048, 8) if _bucket(address, 15) == 0)
    assert not invoke("pyjs.identity.remove", pointer, Pointer(last[0]))
    for key, value in ((last[0], 0), (zero, zero), (last[1], last[1])):
        assert invoke("pyjs.identity.try.put", owner, pointer, Pointer(key), Pointer(value))
    # Buckets 15, 0, 15 occupy 15, 0, 1. Deleting 15 must skip the key at
    # home in bucket 0, but move the key in bucket 1 across the boundary.
    assert invoke("pyjs.identity.remove", pointer, Pointer(last[0]))
    for key in (zero, last[1]):
        assert invoke("pyjs.identity.get", pointer, Pointer(key)).address == key
        assert invoke("pyjs.identity.remove", pointer, Pointer(key))
    entries = state.entries
    for key in range(8, 8192, 8):
        assert invoke("pyjs.identity.try.put", owner, pointer, Pointer(key), Pointer(key))
        assert invoke("pyjs.identity.remove", pointer, Pointer(key))
        assert (state.length, state.capacity, state.entries) == (0, 16, entries)


def test_unsigned_addresses_and_growth_overflow(mapping):
    invoke, owner, pointer, state, _, calls = mapping
    for key in (1, (1 << 63) - 1, 1 << 63, (1 << 64) - 1):
        assert invoke("pyjs.identity.try.put", owner, pointer, Pointer(key), Pointer(key))
        entries = (identity._Entry * state.capacity).from_address(state.entries)
        assert entries[_bucket(key, state.capacity - 1)].key == key
        assert invoke("pyjs.identity.get", pointer, Pointer(key)).address == key
        assert invoke("pyjs.identity.remove", pointer, Pointer(key))
    # Reject synthetic oversized metadata before touching its absent array.
    oversized = identity._Map(1 << 60, 1 << 61, None)
    before, allocations = bytes(oversized), calls.value
    assert not invoke("pyjs.identity.try.put", owner, Pointer(ctypes.addressof(oversized)), Pointer(1), Pointer(1))
    assert bytes(oversized) == before and calls.value == allocations
