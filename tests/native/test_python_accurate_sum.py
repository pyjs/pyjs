import ctypes
import math
import random
import struct

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime import accurate_sum
from pyjs.native.runtime.pointers import Pointer
from pyjs.native.runtime.sequences import _List
from tests.native.runtime_support import runtime_functions, runtime_library


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["python", "O0", "O2"])
def summation(request, tmp_path_factory):
    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm('''
        import math

        def main() -> int:
            return int(math.fsum([1.0]))
    '''))
    return runtime_functions({"pyjs.fsum.add": accurate_sum.add,
                              "pyjs.fsum.finish": accurate_sum.finish}, library)


def test_fsum_random_cancellation_matches_python_bits(summation):
    randoms = random.Random(3512)
    cases = [[], [-0.0], [0.0], [5e-324, -5e-324], [math.inf, -math.inf],
             [math.nan, math.inf, -math.inf], [1e308, 1e308], [math.nan]]
    for _ in range(200):
        values = [math.ldexp(randoms.uniform(-1, 1), randoms.randrange(-1070, 1024))
                  for _ in range(40)]
        values.extend(-value for value in values[:20])
        randoms.shuffle(values)
        cases.append(values)
    for values in cases:
        partials = (ctypes.c_double * 128)()
        header = _List(0, 128, ctypes.addressof(partials), None, None)
        state = (ctypes.c_double * 2)()
        output = ctypes.c_double()
        pointer = Pointer(ctypes.addressof(header))
        status = 0
        for value in values:
            status = summation("pyjs.fsum.add", Pointer(0), pointer, Pointer(ctypes.addressof(state)), value)
            if status:
                break
        if not status:
            status = summation("pyjs.fsum.finish", pointer, Pointer(ctypes.addressof(state)),
                               Pointer(ctypes.addressof(output)))
        try:
            expected = math.fsum(values)
        except (ValueError, OverflowError) as error:
            assert status == (-3 if isinstance(error, ValueError) else -2), values
        else:
            assert status == 0, values
            assert math.isnan(output.value) if math.isnan(expected) else (
                struct.pack("d", output.value) == struct.pack("d", expected)
            ), values


def test_fsum_partial_growth_failure_reports_allocation_status(summation):
    @ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64)
    def deny(context, size):
        return None

    header = _List(0, 0, None, ctypes.cast(deny, ctypes.c_void_p).value, None)
    state = (ctypes.c_double * 2)()
    status = summation("pyjs.fsum.add", Pointer(0), Pointer(ctypes.addressof(header)),
                       Pointer(ctypes.addressof(state)), 1.0)
    assert status == -1
    assert header.length == header.capacity == 0 and header.items is None
