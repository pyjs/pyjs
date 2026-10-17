import ctypes
import math
import random
import struct

import pytest

from pyjs.native.runtime import norm
from pyjs.native.runtime.pointers import Pointer
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["python", "O0", "O2"])
def magnitude(request, tmp_path_factory):
    def generate():
        return "\n".join(("declare double @fma(double, double, double)",
                          "declare double @llvm.sqrt.f64(double)",
                          "declare double @llvm.fabs.f64(double)", *norm.compiled_runtime()))

    library = runtime_library(request, tmp_path_factory, generate)
    call = runtime_functions({"norm": norm.norm}, library, prefix="pyjs.math.")

    def invoke(values):
        buffer = (ctypes.c_double * len(values))(*values)
        return call("norm", Pointer(ctypes.addressof(buffer)), len(values))

    return invoke


def assert_same(actual, expected):
    assert math.isnan(actual) if math.isnan(expected) else struct.pack("d", actual) == struct.pack("d", expected)


def test_extreme_exponents_special_values_and_signed_zero(magnitude):
    values = [0.0, -0.0, 5e-324, 1e-320, 1e-310, math.nextafter(2.2250738585072014e-308, 0.0),
              2.2250738585072014e-308, 1e-200, 1.0, 1e150, 1e308,
              float.fromhex("0x1.fffffffffffffp+1023"), math.inf, -math.inf, math.nan]
    assert_same(magnitude([]), 0.0)
    for left in values:
        assert_same(magnitude([left]), math.hypot(left))
        for right in values:
            assert_same(magnitude([left, right]), math.hypot(left, right))
            assert_same(magnitude([left, right, 1.0]), math.hypot(left, right, 1.0))


def test_compensation_and_subnormal_rescaling(magnitude):
    rng = random.Random(916834)
    cases = [[1.0] + [2**-27] * 1000, [1e308, 1e308], [5e-324] * 1000]
    for _ in range(500):
        exponent = rng.randrange(-1074, 1024)
        cases.append([math.ldexp(rng.random(), exponent) for _ in range(rng.randrange(2, 90))])
    for _ in range(200):
        cases.append([struct.unpack("d", rng.getrandbits(64).to_bytes(8, "little"))[0]
                      for _ in range(rng.randrange(2, 40))])
    for values in cases:
        expected = math.hypot(*values)
        assert_same(magnitude(values), expected)
        assert_same(magnitude(values[::-1]), expected)
