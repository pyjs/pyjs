import ctypes
import math
from itertools import product

import pytest

from pyjs.native.runtime import ordering, summation
from pyjs.native.runtime.pointers import Pointer
from pyjs.native.runtime.sequences import _List
from tests.native.runtime_support import runtime_functions, runtime_library, string


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def ordering_runtime(request, tmp_path_factory):
    from pyjs.native.llvm import transpile_llvm

    library = runtime_library(request, tmp_path_factory, lambda: transpile_llvm('''
        def main() -> int:
            return sorted([3, 1, 2])[0] + int(sum([1.5, 2.5]))
    '''))
    return runtime_functions({
        "pyjs.collection.equal": ordering.equal,
        "pyjs.collection.less": ordering.less,
        "pyjs.list.compare": ordering.compare_lists,
        "pyjs.list.sort": ordering.sort,
        "pyjs.list.sort.keyed": ordering.sort_keyed,
        "pyjs.list.sort.detach": ordering.detach,
        "pyjs.list.sort.restore": ordering.restore,
        "pyjs.sum.add": summation.add,
        "pyjs.sum.finish": summation.finish,
    }, library)


def array_header(values, scalar):
    data = (scalar * max(1, len(values)))()
    data[:len(values)] = values
    header = _List(len(values), len(data), ctypes.addressof(data), None, None)
    header.storage = data
    return header


def pointer(value):
    return Pointer(ctypes.addressof(value))


def test_sort_detachment_preserves_owner_and_detects_discarded_mutations(ordering_runtime):
    for modified in (False, True):
        items = array_header([3, 1, 2], ctypes.c_int64)
        items.allocator, items.context = 1234, 5678
        saved = _List()
        before = bytes(items)
        ordering_runtime("pyjs.list.sort.detach", pointer(items), pointer(saved))
        assert items.length == items.capacity == 0 and items.items is None
        assert (items.allocator, items.context) == (1234, 5678)
        assert bytes(saved) == before
        if modified:
            mutation = array_header([], ctypes.c_int64)
            items.items = mutation.items
            items.capacity = mutation.capacity
        assert ordering_runtime("pyjs.list.sort.restore", pointer(items), pointer(saved)) == (not modified)
        assert bytes(items) == before


@pytest.mark.parametrize("kind, scalar, samples", [
    (1, ctypes.c_bool, [False, True]),
    (2, ctypes.c_int64, [-9223372036854775808, -1, 0, 1, 9223372036854775807]),
    (4, ctypes.c_double, [-math.inf, -2.5, -0.0, 0.0, 1.5, math.inf, math.nan]),
])
def test_scalar_comparisons_match_python(ordering_runtime, kind, scalar, samples):
    for left, right in product(samples, repeat=2):
        a, b = scalar(left), scalar(right)
        assert ordering_runtime("pyjs.collection.equal", pointer(a), pointer(b), kind) == (left == right)
        assert ordering_runtime("pyjs.collection.less", pointer(a), pointer(b), kind) == (left < right)


def test_unicode_and_binary_ordering_uses_contents(ordering_runtime):
    values = [b"", b"a", b"a\x00", b"ab", "é".encode(), "😀".encode(), b"\xff"]
    for left, right in product(values, repeat=2):
        a, b = string(left), string(right)
        pa, pb = ctypes.c_void_p(ctypes.addressof(a)), ctypes.c_void_p(ctypes.addressof(b))
        assert ordering_runtime("pyjs.collection.equal", pointer(pa), pointer(pb), 3) == (left == right)
        assert ordering_runtime("pyjs.collection.less", pointer(pa), pointer(pb), 3) == (left < right)


@pytest.mark.parametrize("reverse", [False, True])
def test_key_sort_preserves_equal_order_and_does_not_change_keys(ordering_runtime, reverse):
    for count in (0, 1, 2, 7, 32, 71):
        values = list(range(count))
        keys = [(value * 11) % 7 for value in values]
        items = array_header(values, ctypes.c_int64)
        key_items = array_header(keys, ctypes.c_int64)
        before = bytes(key_items.storage)
        assert ordering_runtime("pyjs.list.sort.keyed", pointer(items), pointer(key_items), 8, 8, 2, reverse)
        assert list(items.storage)[:count] == sorted(values, key=keys.__getitem__, reverse=reverse)
        assert bytes(key_items.storage) == before


def test_key_sort_validates_headers_and_sizes_before_reading_storage(ordering_runtime):
    items = array_header([1, 2], ctypes.c_int64)
    keys = array_header([2, 1], ctypes.c_int64)
    before = bytes(items.storage)
    for size, key_size in ((0, 8), (16, 8), (8, 0), (8, 16)):
        assert not ordering_runtime("pyjs.list.sort.keyed", pointer(items), pointer(keys), size, key_size, 2, False)
    keys.length = 1
    assert not ordering_runtime("pyjs.list.sort.keyed", pointer(items), pointer(keys), 8, 8, 2, False)
    items.length = keys.length = 9223372036854775807
    assert not ordering_runtime("pyjs.list.sort.keyed", pointer(items), pointer(keys), 8, 8, 2, False)
    assert bytes(items.storage) == before


@pytest.mark.parametrize("values", [[], [1], [1, 2, 3], [3, 2, 1], [4, 2, 2, 0, -3], [7] * 33])
@pytest.mark.parametrize("reverse", [False, True])
def test_sort_matches_python_and_preserves_storage(ordering_runtime, values, reverse):
    header = array_header(values, ctypes.c_int64)
    before = bytes(header)
    assert ordering_runtime("pyjs.list.sort", pointer(header), 8, 2, reverse)
    assert list(header.storage)[:len(values)] == sorted(values, reverse=reverse)
    assert bytes(header) == before


@pytest.mark.parametrize("reverse", [False, True])
def test_merge_sort_preserves_duplicate_order_and_signed_zero(ordering_runtime, reverse):
    class Row(ctypes.Structure):
        _fields_ = [("key", ctypes.c_int64), ("ordinal", ctypes.c_int64)]

    values = [(2, 0), (1, 1), (3, 2), (2, 3), (1, 4), (2, 5), (3, 6)]
    rows = [Row(key, ordinal) for key, ordinal in values]
    header = array_header(rows, Row)
    assert ordering_runtime("pyjs.list.sort", pointer(header), ctypes.sizeof(Row), 2, reverse)
    assert [(row.key, row.ordinal) for row in header.storage] == sorted(values, key=lambda row: row[0], reverse=reverse)
    zeros = array_header([-0.0, 0.0, -0.0, 0.0], ctypes.c_double)
    before = bytes(zeros.storage)
    assert ordering_runtime("pyjs.list.sort", pointer(zeros), 8, 4, reverse)
    assert bytes(zeros.storage) == before


def test_list_comparison_distinguishes_unordered_values(ordering_runtime):
    values = [[], [0.0], [0.0, 1.0], [2.0], [float("nan")]]
    for left, right in product(values, repeat=2):
        a, b = array_header(left, ctypes.c_double), array_header(right, ctypes.c_double)
        result = ordering_runtime("pyjs.list.compare", pointer(a), pointer(b), 8, 4)
        if left and right and math.isnan(left[0]) and math.isnan(right[0]):
            assert result == 2
        else:
            expected = 0 if left == right else -1 if left < right else 1 if left > right else 2
            assert result == expected
        assert ordering_runtime("pyjs.list.compare", pointer(a), pointer(a), 8, 4) == 0


@pytest.mark.parametrize("values, start", [
    ([], -0.0), ([-0.0], -0.0), ([1e16, 1.0, -1e16], 0.0),
    ([1.0, 1e100, 1.0, -1e100], 0.0), ([0.1] * 1000, 0.0),
    ([math.inf, 1.0], 0.0), ([-math.inf], 0.0),
    ([math.inf, -math.inf], 0.0), ([math.nan, 1.0], 0.0),
    ([1e308, 1e308], 0.0), ([1.5, -2.0, 4.0], 2.0),
])
def test_compensated_summation_matches_python(ordering_runtime, values, start):
    state = (ctypes.c_double * 2)(start, 0.0)
    for value in values:
        ordering_runtime("pyjs.sum.add", pointer(state), value)
    result = ordering_runtime("pyjs.sum.finish", pointer(state))
    expected = sum(values, start)
    if math.isnan(expected):
        assert math.isnan(result)
    else:
        assert result == expected
        if expected == 0.0:
            assert math.copysign(1.0, result) == math.copysign(1.0, expected)
