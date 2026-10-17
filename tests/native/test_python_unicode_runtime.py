import ctypes

import pytest

from pyjs import int32
from pyjs.native import unicode_data
from pyjs.native.llvm import transpile_llvm
from pyjs.native.runtime.compiler import compile_runtime
from pyjs.native.runtime.pointers import Pointer
from pyjs.native.runtime.unicode import (
    _Context,
    _Mapping,
    change_case,
    in_ranges,
    lookup,
    write_case,
)
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import runtime_functions, runtime_library, string


def mapping(name):
    entries = {codepoint: (codepoint + delta,)
               for start, stop, stride, delta in getattr(unicode_data, name + "_RANGES")
               for codepoint in range(start, stop + 1, stride or 1)}
    if name != "LOWERCASE":
        entries.update(dict(getattr(unicode_data, name + "_SPECIAL")))
    keys = sorted(entries)
    offsets = [0]
    values = []
    for key in keys:
        values.extend(entries[key])
        offsets.append(len(values))
    arrays = [(ctypes.c_int32 * len(items))(*items) for items in (keys, offsets, values)]
    result = _Mapping(*[ctypes.addressof(array) for array in arrays], len(keys))
    if name == "LOWERCASE":
        result.offsets = None
    result.arrays = arrays
    return result


@pytest.fixture(scope="module", params=[None, 0, 2], ids=["CPython", "O0", "O2"])
def unicode_runtime(request, tmp_path_factory):
    operations = {"write_case": write_case, "in_ranges": in_ranges, "lookup": lookup}
    library = runtime_library(request, tmp_path_factory, lambda: "\n".join(compile_runtime(operations)))
    return runtime_functions(operations, library)


def test_case_tables_and_context_measure_and_write_identically(unicode_runtime):
    maps = {name: mapping(name) for name in ("LOWERCASE", "UPPERCASE", "CASEFOLD", "SWAPCASE", "TITLECASE")}
    cased = (ctypes.c_int32 * (2 * len(unicode_data.CASED_RANGES)))(
        *[value for pair in unicode_data.CASED_RANGES for value in pair])
    ignored = (ctypes.c_int32 * (2 * len(unicode_data.CASE_IGNORABLE_RANGES)))(
        *[value for pair in unicode_data.CASE_IGNORABLE_RANGES for value in pair])
    context = _Context(ctypes.addressof(maps["LOWERCASE"]), ctypes.addressof(cased), len(cased) // 2,
                       ctypes.addressof(ignored), len(ignored) // 2)
    values = ("", "A\0B", "İΣßﬃǄa界😀", "ΟΣ", "ΟΣΑ", "AΣ́", "AΣ́1", "AΣ'", "1Σ", "foóbar", "they're BILL'S")
    changed = {key for table in maps.values() for key in table.arrays[0]}
    changed.update(codepoint for codepoint, _ in unicode_data.LOWERCASE_SPECIAL)
    # Exercise every stored case mapping in both isolated and adjacent context.
    characters = [chr(codepoint) for codepoint in sorted(changed)]
    values += ("|".join(characters), "".join(characters))
    for name, mode, method in (("LOWERCASE", 0, str.lower), ("UPPERCASE", 1, str.upper),
                               ("CASEFOLD", 1, str.casefold), ("SWAPCASE", 2, str.swapcase),
                               ("TITLECASE", 3, str.title), ("TITLECASE", 4, str.capitalize)):
        for value in values:
            header = string(value.encode())
            arguments = Pointer(ctypes.addressof(maps[name])), Pointer(ctypes.addressof(context)), mode
            expected = method(value).encode()
            assert unicode_runtime("write_case", Pointer(ctypes.addressof(header)), Pointer(0), *arguments) == len(expected)
            storage = ctypes.create_string_buffer(b"!" * (len(expected) + 16))
            assert unicode_runtime("write_case", Pointer(ctypes.addressof(header)),
                                   Pointer(ctypes.addressof(storage) + 8), *arguments) == len(expected)
            assert storage.raw == b"!" * 8 + expected + b"!" * 8 + b"\0"


def test_lookup_and_range_edges_do_not_read_empty_tables(unicode_runtime):
    empty = _Mapping(None, None, None, 0)
    assert unicode_runtime("lookup", Pointer(ctypes.addressof(empty)), int32(65)) == -1
    assert not unicode_runtime("in_ranges", int32(65), Pointer(0), 0)
    keys = (ctypes.c_int32 * 3)(65, 90, 0x10FFFF)
    table = _Mapping(ctypes.addressof(keys), None, None, 3)
    ranges = (ctypes.c_int32 * 4)(65, 90, 100, 110)
    for value in (0, 64, 65, 66, 89, 90, 91, 99, 100, 110, 111, 0x10FFFF):
        expected = list(keys).index(value) if value in keys else -1
        assert unicode_runtime("lookup", Pointer(ctypes.addressof(table)), int32(value)) == expected
        assert unicode_runtime("in_ranges", int32(value), Pointer(ctypes.addressof(ranges)), 2) == (65 <= value <= 90 or 100 <= value <= 110)


def test_case_tables_fit_the_measurement_overflow_bound():
    # change_case bounds input length using a threefold UTF-8 expansion limit.
    # Keep that safety assumption checked when generated Unicode data changes.
    for name in ("LOWERCASE", "UPPERCASE", "CASEFOLD", "SWAPCASE", "TITLECASE"):
        for start, stop, stride, delta in getattr(unicode_data, name + "_RANGES"):
            for source in range(start, stop + 1, stride or 1):
                assert len(chr(source + delta).encode()) <= 3 * len(chr(source).encode())
        for source, targets in getattr(unicode_data, name + "_SPECIAL"):
            assert sum(len(chr(target).encode()) for target in targets) <= 3 * len(chr(source).encode())


@pytest.mark.parametrize("optimize", [None, 0, 2], ids=["CPython", "O0", "O2"])
def test_case_conversion_rejects_invalid_lengths_before_reading_storage(tmp_path, optimize):
    library = None
    if optimize is not None:
        source = transpile_llvm('def main() -> str: return "a".lower()')
        library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions({"pyjs.unicode.change.case": change_case}, library)
    for length in (-1, (1 << 63) // 3 + 1, (1 << 63) - 1):
        header = string(b"")
        header.length = length
        header.data = None
        for mode in range(5):
            # All storage, tables and owners are absent: rejection must happen
            # before reading a byte or attempting to allocate the result.
            result = invoke("pyjs.unicode.change.case", Pointer(0), Pointer(0), Pointer(0),
                            Pointer(ctypes.addressof(header)), Pointer(0), Pointer(0), mode)
            assert not result.address
