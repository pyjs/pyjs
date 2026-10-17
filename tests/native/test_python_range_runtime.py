import ctypes
import math
from itertools import product

import pytest

from pyjs import int64
from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import ranges
from pyjs.native.runtime.pointers import Pointer
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def range_runtime(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm('def main() -> int: return len(range(3))'))
    return runtime_functions({
        "pyjs.range.length": ranges.length,
        "pyjs.range.last": ranges.last,
        "pyjs.range.get": ranges.get,
        "pyjs.range.equal": ranges.equal_ranges,
        "pyjs.range.contains": ranges.contains,
        "pyjs.range.contains.float": ranges.contains_float,
        "pyjs.range.index": ranges.index,
        "pyjs.range.reverse.init": ranges.reverse_initialize,
        "pyjs.range.sum.i64": ranges.sum_integer,
        "pyjs.range.sum.f64": ranges.sum_float,
        "pyjs.range.slice.into": ranges.slice_range,
        "pyjs.slice.length": ranges.slice_length,
    }, library)


def test_range_arithmetic_handles_lengths_beyond_signed_i64(range_runtime):
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    for start, stop, step in product((minimum, -1, 0, 1, maximum), repeat=3):
        if step == 0:
            continue
        value = range(start, stop, step)
        count = max(0, (stop - start - 1) // step + 1) if step > 0 else max(0, (start - stop - 1) // -step + 1)
        if count <= maximum:
            assert range_runtime("pyjs.range.length", start, stop, step) == count
        for index in (minimum, -1, 0, 1, maximum):
            if -count <= index < count:
                assert range_runtime("pyjs.range.get", start, stop, step, index) == value[index]
        for item in (minimum, -1, 0, 1, maximum):
            assert range_runtime("pyjs.range.contains", start, stop, step, item) == (item in value)
            if item in value and value.index(item) <= maximum:
                assert range_runtime("pyjs.range.index", start, stop, step, item) == value.index(item)
        if count:
            assert range_runtime("pyjs.range.last", start, stop, step) == value[-1]
        iterator = ranges._ReverseIterator()
        range_runtime("pyjs.range.reverse.init", Pointer(ctypes.addressof(iterator)), start, stop, step)
        assert iterator.current == (value[-1] if count else 0)
        assert iterator.length == int(int64(count)) and iterator.step == step
        assert range_runtime("pyjs.range.equal", start, stop, step, start, stop, step)
        assert range_runtime("pyjs.range.equal", start, stop, step, 0, 0, 1) == (value == range(0))


def test_float_range_membership_uses_exact_integer_values(range_runtime):
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    # Tiny ranges make CPython's linear float search safe even at i64 edges.
    values = (range(-5, 6, 2), range(6, -6, -2), range(0),
              range(2**53 - 3, 2**53 + 4), range(minimum, minimum + 4),
              range(maximum - 3, maximum), range(minimum, maximum, 2**62))
    items = (-0.0, 0.0, -1.0, 1.0, -1.5, 1.5, 5e-324, -5e-324,
             float(2**53 - 1), float(2**53), float(2**53 + 1), float(2**53 + 2),
             float(minimum), math.nextafter(float(minimum), -math.inf),
             math.nextafter(float(maximum), 0.0), float(maximum),
             math.inf, -math.inf, math.nan)
    for value, item in product(values, items):
        actual = range_runtime("pyjs.range.contains.float", value.start, value.stop, value.step, item)
        assert actual == (item in value), (value, item)


def test_range_slice_and_sum_match_python_at_extreme_boundaries(range_runtime):
    minimum, maximum = -(1 << 63), (1 << 63) - 1
    for original, start, stop, step in product(
        (range(-10, 10, 3), range(10, -10, -3), range(minimum, maximum), range(0)),
        (None, minimum, -1, 0, 1, maximum),
        (None, minimum, -1, 0, 1, maximum),
        (None, minimum, -2, -1, 1, 2, maximum),
    ):
        sliced = original[slice(start, stop, step)]
        expected = sliced.start, sliced.stop, sliced.step
        if all(minimum <= item <= maximum for item in expected):
            output = (ctypes.c_int64 * 5)(123, 0, 0, 0, 456)
            range_runtime("pyjs.range.slice.into", original.start, original.stop, original.step,
                          start or 0, start is not None, stop or 0, stop is not None,
                          step or 0, step is not None, Pointer(ctypes.addressof(output) + 8))
            assert list(output) == [123, *expected, 456]
    for value in (range(10), range(10, -10, -2), range(maximum - 2, maximum), range(minimum + 2, minimum, -1), range(0)):
        assert range_runtime("pyjs.range.sum.i64", value.start, value.stop, value.step, maximum) == int(int64(sum(value, maximum)))
        expected = 0.25
        for item in value:
            expected += float(item)
        assert range_runtime("pyjs.range.sum.f64", value.start, value.stop, value.step, 0.25) == expected
    for start, stop, step in product((None, minimum, -1, 0, maximum), repeat=3):
        if step != 0:
            assert range_runtime("pyjs.slice.length", 6, start or 0, start is not None,
                                 stop or 0, stop is not None, step or 0, step is not None) == len(range(6)[slice(start, stop, step)])
