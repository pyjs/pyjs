import math
import random
import struct

import pytest

from pyjs import int64
from pyjs.native.runtime import math_algorithms
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["python", "O0", "O2"])
def algorithms(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join(math_algorithms.compiled_runtime()))
    return runtime_functions({
        "gcd": math_algorithms.gcd, "lcm": math_algorithms.lcm,
        "combination": math_algorithms.combination, "isqrt": math_algorithms.isqrt,
        "nextafter": math_algorithms.nextafter,
    }, library, prefix="pyjs.math.")


def test_wide_integer_algorithms(algorithms):
    maximum = (1 << 63) - 1
    values = [-(1 << 63), -maximum, -72, -1, 0, 1, 2, 49, 72, maximum]
    for left in values:
        for right in values:
            assert algorithms("gcd", left, right) == int(int64(math.gcd(left, right)))
            expected = math.lcm(left, right)
            assert algorithms("lcm", left, right) == (expected if expected <= maximum else -1)
    for n in [0, 1, 20, 60, 66, 67, 100, maximum]:
        for k in [0, 1, 2, 5, 20, 30, 33, 67]:
            for permutation in [False, True]:
                expected = (math.perm if permutation else math.comb)(n, k)
                assert algorithms("combination", n, k, permutation) == (expected if expected <= maximum else -1)
    randoms = random.Random(5871)
    for value in [0, 1, 2, 3, 4, 8, 9, 10, maximum, *[randoms.randrange(maximum) for _ in range(100)]]:
        assert algorithms("isqrt", value) == math.isqrt(value)


def test_nextafter_ranks_match_python_including_zero_signs(algorithms):
    randoms = random.Random(9153)
    values = [-math.inf, -1e308, -1.0, -5e-324, -0.0, 0.0, 5e-324, 1.0, 1e308, math.inf, math.nan]
    pairs = [(left, right) for left in values for right in values]
    pairs.extend((struct.unpack("d", randoms.getrandbits(64).to_bytes(8, "little"))[0],
                  struct.unpack("d", randoms.getrandbits(64).to_bytes(8, "little"))[0]) for _ in range(50))
    for left, right in pairs:
        for steps in [0, 1, 2, 1000, (1 << 63) - 1]:
            expected = math.nextafter(left, right, steps=steps)
            result = algorithms("nextafter", left, right, steps)
            assert math.isnan(result) if math.isnan(expected) else struct.pack("d", result) == struct.pack("d", expected)
