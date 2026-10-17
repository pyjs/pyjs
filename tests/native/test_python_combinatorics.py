"""Guarded raw index transitions; cursor publication/exhaustion is tested separately."""

import ctypes
import itertools

import pytest

from pyjs.native.runtime import combinatorics
from pyjs.native.runtime.compiler import compile_runtime
from pyjs.native.runtime.pointers import Pointer
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def steps(request, tmp_path_factory):
    operations = {"test." + name: getattr(combinatorics, name) for name in (
        "product_advance", "combinations_advance", "permutations_advance",
    )}
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join(compile_runtime(operations)))
    return runtime_functions(operations, library)


def test_product_indices_respect_pool_headers_and_guarded_storage(steps):
    # Empty pools are rejected by the cursor before calling the step kernel;
    # its empty tuple and zero-repeat cases still have one initial result.
    for lengths in ((), (1,), (3,), (2, 3, 2)):
        for repeat in (0, 1, 2):
            size = len(lengths) * repeat
            indices = (ctypes.c_int64 * (size + 2))(123, *([0] * size), 456)
            pools = [ctypes.c_int64(length) for length in lengths]
            pointers = (ctypes.c_void_p * len(pools))(*(ctypes.addressof(pool) for pool in pools))
            expected = list(itertools.product(*map(range, lengths), repeat=repeat))
            arguments = (Pointer(ctypes.addressof(indices) + 8), Pointer(ctypes.addressof(pointers)),
                         len(pools), size)
            rows = [tuple(indices[1:-1])]
            while steps("test.product_advance", *arguments):
                rows.append(tuple(indices[1:-1]))
                assert len(rows) <= len(expected)
            assert rows == expected
            assert (indices[0], indices[-1]) == (123, 456)
            assert tuple(pool.value for pool in pools) == lengths
            assert list(pointers) == [ctypes.addressof(pool) for pool in pools]


def test_combinations_and_permutations_do_not_write_outside_index_buffers(steps):
    for length, size, kind in itertools.product(range(6), range(6), (
        "combinations", "combinations_with_replacement", "permutations",
    )):
        expected = list(getattr(itertools, kind)(range(length), size))
        if not expected:
            continue  # The cursor rejects these before advancing the kernel.
        initial = list(range(length)) if kind == "permutations" else list(expected[0])
        indices = (ctypes.c_int64 * (len(initial) + 2))(123, *initial, 456)
        cycles = (ctypes.c_int64 * (size + 2))(123, *range(length, length - size, -1), 456)
        pointer = Pointer(ctypes.addressof(indices) + 8)
        if kind == "permutations":
            name = "test.permutations_advance"
            arguments = pointer, Pointer(ctypes.addressof(cycles) + 8), length, size
        else:
            name = "test.combinations_advance"
            arguments = pointer, length, size, kind.endswith("with_replacement")
        rows = [tuple(indices[1:1 + size])]
        while steps(name, *arguments):
            rows.append(tuple(indices[1:1 + size]))
            assert len(rows) <= len(expected), (kind, length, size)
        assert rows == expected, (kind, length, size)
        assert (indices[0], indices[-1], cycles[0], cycles[-1]) == (123, 456, 123, 456)
