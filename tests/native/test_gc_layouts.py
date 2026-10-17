"""Typed aggregate tracing: reclamation as well as retained-reference safety."""

import pytest

from pyjs.native.runtime.heap import _Heap
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("result_type,build,live", [
    ("Holder", "result = Holder(bits)", 1),
    ("tuple[int, int]", "result = (bits, 7)", 1),
    ("range", "result = range(bits, bits + 2)", 1),
    ("range", "result = range(bits, bits + 4)[::2]", 1),
    ("Callable[[], int]", "result = lambda: bits", 2),
    ("Callable[[], int]", "result = partial(identity, bits)", 1),
    ("Iterator[int]", "result = numbers(bits)", 2),
    ("bytes", "result = bytes([(bits >> (index * 8)) & 255 for index in range(8)])", 1),
    ("list[int]", "result = [bits]", 2),
    ("list[int]", "result = [bits for _ in range(20)]", 2),
    ("list[int]", "result = ([bits] * 12 + [bits])[::2]", 2),
    ("list[int64]", "result = [int64(bits)]", 2),
    ("list[int | None]", "result = [bits, None]", 2),
    ("Iterator[int]", "result = iter(range(bits, bits + 2))", 2),
    ("Iterator[int]", "result = reversed(range(bits, bits + 2))", 2),
    ("Iterator[int]", "result = count(bits)", 1),
    ("Iterator[int]", "result = repeat(bits)", 2),
    ("Iterator[float]", "result = count(float_bits(bits), 0.0)", 2),
    ("Iterator[int]", "result = accumulate([bits, 0]); next(result)", 5),
    ("Iterator[tuple[int, int]]", "result = pairwise([bits, bits]); next(result)", 6),
    ("Iterator[int]", "left, result = tee([bits, bits]); next(left)", 5),
    ("Iterator[tuple[int, Iterator[int]]]", "result = groupby([bits, bits]); next(result)", 7),
    ("object", "result = bits", 1),
    ("object", "result = float_bits(bits)", 1),
    ("object", "result = [bits]", 3),
    ("dict[int, int]", "result = {bits: bits}", 3),
    ("dict[int, int]", "result = {index: bits for index in range(20)}", 3),
    ("dict[int, int]", "result = {bits: bits}.copy()", 3),
    ("dict[int, int]", "result = dict.fromkeys([bits], bits)", 3),
    # Object keys also own a cached-hash buffer, including identity hashes.
    ("dict[Box, int]", "result = {Box(): bits}", 5),
    ("dict[int, Box]", "result = {bits: Box()}", 4),
    ("dict[Key, int]", "result = {Key(bits): 1}", 5),
    ("set[int]", "result = {bits}", 3),
    ("frozenset[int]", "result = frozenset([bits])", 3),
    ("tuple[int, int]", "result = next(enumerate([bits], bits))", 1),
    ("tuple[int, int]", "result = next(zip([bits], [7]))", 1),
    ("tuple[int, int]", "result = next(iter({bits: bits}.items()))", 1),
    ("tuple[int, int]", "result = next(pairwise([bits, bits]))", 1),
    ("tuple[int, str]", "result = next(zip([bits], ['literal']))", 1),
    ("tuple[int, str]", "result = next(product([bits], ['literal']))", 1),
    ("tuple[int, ...]", "result = tuple([bits]) + tuple([bits])", 1),
    ("tuple[int, ...]", "result = tuple([bits]) * 3", 2),
    ("tuple[int, ...]", "result = tuple([bits, bits, bits])[::2]", 2),
    ("tuple[int, ...]", "result = next(batched([bits, bits], 2))", 1),
    ("tuple[int, ...]", "result = next(combinations([bits, bits], 2))", 1),
    ("tuple[int, int]", "result = next(zip_longest([bits], [bits, 3], fillvalue=bits))", 1),
    ("tuple[int, ...]", "result = next(permutations([bits, bits], 2))", 1),
    ("tuple[int, ...]", "result = next(product([bits], repeat=2))", 1),
    ("tuple[int, ...]", "result = next(combinations_with_replacement([bits], 2))", 1),
    ("tuple[int, ...]", "result = (bits, bits, bits)[::2]", 2),
    ("tuple[float, ...]", "result = tuple([float_bits(bits)]) + tuple([float_bits(bits)])", 1),
    ("bytes", "data = bytes([(bits >> (i * 8)) & 255 for i in range(8)]); "
     "result = (data + b'|' * 16).split(b'|' * 16)[0]", 1),
    ("bytes", "data = bytes([(bits >> (i * 8)) & 255 for i in range(8)]); "
     "result = (data + b'|' * 16).rsplit(b'|' * 16)[0]", 1),
    ("bytes", "data = bytes([(bits >> (i * 8)) & 255 for i in range(8)]); "
     "result = (data + b'|' * 16).partition(b'|' * 16)[0]", 1),
    ("bytes", "data = bytes([(bits >> (i * 8)) & 255 for i in range(8)]); "
     "result = (data + b'|' * 16).rpartition(b'|' * 16)[0]", 1),
], ids=["fields", "tuple", "range", "range-slice", "cell", "partial", "generator", "bytes",
        "list", "list-growth", "list-copy", "list-wide", "list-optional",
        "range-iterator", "reverse-range-iterator", "count-iterator",
        "repeat-saved", "count-float-saved", "accumulate-saved", "pairwise-saved", "tee-history", "group-workspace",
        "boxed-int", "boxed-float", "boxed-list",
        "dict", "dict-growth", "dict-copy", "dict-fromkeys", "dict-reference-keys",
        "dict-reference-values", "dict-cached-hash", "set", "frozenset",
        "enumerate-row", "zip-row", "items-row", "pairwise-row", "mixed-row", "product-row",
        "tuple-concat", "tuple-repeat", "tuple-slice", "batch-row", "combination-row",
        "longest-row", "permutation-row", "dynamic-product-row", "replacement-row", "fixed-slice", "float-concat",
        "split-text", "rsplit-text", "partition-text", "rpartition-text"])
def test_scalar_address_bits_do_not_retain_an_object(tmp_path, optimize, result_type, build, live):
    # CPython cannot expose this native pointer or collector state. Force a
    # real managed address into a typed integer lane, leave the producer frame,
    # and inspect live allocations (gc_count() counts pins, not heap objects).
    source = f'''
from functools import partial
from itertools import accumulate, batched, combinations, count, groupby, pairwise, product, repeat, tee
from itertools import combinations_with_replacement, permutations, zip_longest
from typing import Callable, Iterator
from pyjs import int8, int64, llvm
from pyjs.native import gc_collect, gc_pin, gc_unpin

class Box:
    def __init__(self):
        self.number = 99

class Key:
    def __init__(self, bits: int):
        self.bits = bits
    def __hash__(self) -> int:
        return self.bits

class Holder:
    def __init__(self, bits: int):
        self.small = int8(7)
        self.bits = bits
        self.optional: int | None = bits
        self.wide = int64(bits)

@llvm.inline("ptrtoint ptr {{value}} to i64")
def address(value: Box) -> int:
    return id(value)

@llvm.inline("bitcast i64 {{value}} to double")
def float_bits(value: int) -> float:
    import struct
    return struct.unpack("d", struct.pack("Q", value))[0]

def identity(value: int) -> int:
    return value

def numbers(value: int) -> Iterator[int]:
    yield value
    yield value + 1

def make() -> {result_type}:
    child = Box()
    gc_pin(child)
    bits = address(child)
    {build}
    gc_unpin(child)
    return result

def main() -> str:
    result = make()
    gc_pin(result)
    gc_collect()
    return "done"
'''
    library = LLVM().compile_library(source, tmp_path, optimize=optimize)
    try:
        assert library.render() == "done"
        assert _Heap.from_address(library._heap).count == live
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_rows_keep_references_after_the_cursors_are_gone(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from itertools import batched, combinations, pairwise, product
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold

class Box:
    def __init__(self, value: int):
        self.value = value

def rows() -> list[tuple[int, Box]]:
    result = list(enumerate([Box(1), Box(2)], 10))
    result.extend(zip([12, 13], [Box(3), Box(4)]))
    result.extend({14: Box(5), 15: Box(6)}.items())
    result.extend(product([16], [Box(7), Box(8)]))
    return result

def pairs() -> list[tuple[Box, Box]]:
    return list(pairwise([Box(9), Box(10), Box(11)]))

def tagged() -> list[tuple[int8, str | int]]:
    values: list[str | int] = ['dynamic' + str(42), 73]
    return list(zip([int8(1), int8(2)], values))

def dynamic() -> list[tuple[Box, ...]]:
    source = tuple([Box(20), Box(21), Box(22)])
    result = [source + source, source * 2, source[::-1]]
    result.extend(batched([Box(23), Box(24), Box(25)], 2))
    result.extend(combinations([Box(26), Box(27), Box(28)], 2))
    return result

def main() -> str:
    gc_set_threshold(1)
    first, second, third, fourth = rows(), pairs(), tagged(), dynamic()
    gc_collect()
    return repr(([(index, value.value) for index, value in first],
                 [(left.value, right.value) for left, right in second], third,
                 [[item.value for item in row] for row in fourth]))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.matches
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_described_fields_cells_and_partials_keep_reference_graphs(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from functools import partial
from typing import Callable
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold

class Base:
    def __init__(self, value: int):
        self.small = int8(7)
        self.value = value
        self.next: Base | None = None
    def read(self) -> int:
        return self.value

class Child(Base):
    def __init__(self, value: int):
        super().__init__(value)
        self.other: Base | int = self
    def read(self) -> int:
        return self.value + 1

def add(value: Base, amount: int) -> int:
    return value.read() + amount

def create() -> tuple[Callable[[], int], Callable[[], int], Callable[[], int], Child]:
    first = Child(20)
    second = Base(10)
    first.next = second
    second.next = first
    first.other = Base(30)
    captured = lambda: first.read()
    bound = first.read
    applied = partial(add, second, 3)
    return (captured, bound, applied, first)

def main() -> str:
    gc_set_threshold(1)
    saved = create()
    for _ in range(3):
        gc_collect()
        assert saved[0]() == 21
        assert saved[1]() == 21
        assert saved[2]() == 13
        child = saved[3].next
        assert child is not None
        assert child.next is saved[3]
        other = saved[3].other
        assert isinstance(other, Base)
        assert other.value == 30
    return "retained"
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_container_kernels_keep_their_references(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold

def create(value: str) -> tuple[list[str], list[str], tuple[str, str, str], tuple[str, str, str], list[str]]:
    source = value + "::tail\\nlast"
    return (source.split("::"), source.rsplit("::"), source.partition("::"),
            source.rpartition("::"), source.splitlines())

def main() -> str:
    gc_set_threshold(1)
    saved = create("held")
    for index in range(8):
        create(str(index))
        gc_collect()
    return repr(saved)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_temporary_managed_ranges_survive_later_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold

class Index:
    def __index__(self) -> int:
        gc_collect()
        return 1

def collect() -> int:
    gc_collect()
    return 2

def read(value: range, offset: int) -> int:
    gc_collect()
    return value[offset]

def collect_range() -> range:
    gc_collect()
    return range(10, 20)

def main() -> str:
    gc_set_threshold(1)
    pair = (range(10, 20), collect())
    values = [range(10, 20), collect_range()]
    same = range(10, 20) == collect_range()
    return repr((pair, values, same, range(10, 20)[Index()], range(10, 20)[::2][Index()],
                 read(range(10, 20), collect()), read(range(10, 20)[::2], collect()),
                 range(10, 20)[Index():Index()], range(10, 20).__getitem__(Index())))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_described_lists_keep_nested_and_tagged_items_through_growth(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold

class Box:
    def __init__(self, value: int):
        self.value = value

def create() -> tuple[list[list[Box]], list[Box | int]]:
    items: list[Box] = []
    mixed: list[Box | int] = []
    for index in range(20):
        items.append(Box(index))
        mixed.append(Box(index + 30))
        mixed.append(index)
    copied = items[::2] + items[1::2]
    items.clear()
    return ([copied, copied * 2], mixed)

def main() -> str:
    gc_set_threshold(1)
    saved = create()
    for _ in range(3):
        create()
        gc_collect()
        assert sum(item.value for item in saved[0][0]) == 190
        assert sum(item.value for item in saved[0][1]) == 380
        total = 0
        for item in saved[1]:
            if isinstance(item, Box):
                total += item.value
            else:
                total += item
        assert total == 980
    return "retained"
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_described_mappings_keep_key_and_value_graphs(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold

class Box:
    def __init__(self, number: int):
        self.number = number
    def __hash__(self) -> int:
        gc_collect()
        return self.number % 3

def create() -> tuple[dict[Box, Box | int], dict[int, Box], set[Box]]:
    mapping: dict[Box, Box | int] = {}
    values: dict[int, Box] = {}
    keys: set[Box] = set()
    for index in range(20):
        key = Box(index)
        mapping[key] = Box(index + 30) if index % 2 else index
        values[index] = key
        keys.add(key)
    copied = mapping.copy()
    mapping.clear()
    copied.update(mapping)
    return (copied, values.copy(), keys.copy())

def main() -> str:
    gc_set_threshold(1)
    saved = create()
    for _ in range(3):
        create()
        gc_collect()
        assert sum(key.number for key in saved[0]) == 190
        assert sum(value.number for value in saved[1].values()) == 190
        assert sum(key.number for key in saved[2]) == 190
        total = 0
        for value in saved[0].values():
            total += value.number if isinstance(value, Box) else value
        assert total == 490
    return "retained"
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
