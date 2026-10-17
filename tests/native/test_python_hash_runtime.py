import ctypes
import math
import random
import struct

import pytest

from pyjs.native.hashing import runtime
from pyjs.native.runtime import hashing
from pyjs.native.runtime.pointers import Pointer
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def hashes(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join(runtime()))
    return runtime_functions({"pyjs.hash.int": hashing.integer, "pyjs.hash.float": hashing.floating,
                              "pyjs.hash.cached.unordered": hashing.cached_unordered,
                              "pyjs.hash.range": hashing.range_value}, library)


def test_range_hash_uses_canonical_sequence_fields(hashes):
    cases = [(0, 0, 1), (7, 8, 100), (10, -8, -3), (-10, 8, 3),
             (-(1 << 63), (1 << 63) - 1, 1),
             ((1 << 63) - 1, -(1 << 63), -1),
             ((1 << 63) - 1, -(1 << 63), -(1 << 63))]
    rng = random.Random(215)
    for _ in range(100):
        start, stop, step = (rng.randrange(-(1 << 63), 1 << 63) for _ in range(3))
        cases.append((start, stop, step or 1))
    for start, stop, step in cases:
        # Python integers compute the full count even where len(range) raises.
        distance = stop - start if step > 0 else start - stop
        count = max(0, (distance - 1) // abs(step) + 1)
        expected = hashing.triple(hash(count), hash(start) if count else hashing.NONE_HASH,
                                  hash(step) if count > 1 else hashing.NONE_HASH)
        assert hashes("pyjs.hash.range", start, stop, step) == expected


def test_cached_unordered_hash_reuses_stored_values(hashes):
    for values in ([], [0], [-1, -(1 << 63), (1 << 63) - 1], [7, 2, 19]):
        storage = (ctypes.c_int64 * len(values))(*values)
        expected = 1927868237
        for item in values:
            expected = hashing.unordered(expected, item)
        expected ^= len(values)
        expected = -2 if expected == -1 else expected
        assert hashes("pyjs.hash.cached.unordered", Pointer(ctypes.addressof(storage)), len(values)) == expected


def test_numeric_hashes_cover_the_full_scalar_bit_ranges(hashes):
    rng = random.Random(1729)
    integers = [0, 1, -1, -(1 << 63), (1 << 63) - 1]
    integers += [rng.randrange(-(1 << 63), 1 << 63) for _ in range(250)]
    for value in integers:
        assert hashes("pyjs.hash.int", value) == hash(value), value
    floats = [0.0, -0.0, float("inf"), float("-inf"), float("nan")]
    floats += [struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0] for _ in range(250)]
    for value in floats:
        expected = 0 if math.isnan(value) else hash(value)
        assert hashes("pyjs.hash.float", value) == expected, value
