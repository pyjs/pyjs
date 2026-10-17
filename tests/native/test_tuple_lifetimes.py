import pytest

from pyjs.tooling.llvm import LLVM

SCALAR_BOUND_PROVENANCE = '''
class Bounds:
    def __init__(self, value: int):
        self.value = value
        self.selected = slice(1, 3)

def tail(value: int) -> int:
    items = (1, 2, 3)
    return len(items[value:]) + len(items * value) + len(value * items)

def main() -> int:
    box = Bounds(1)
    items = (1, 2, 3)
    counts = [0, 1, 2]
    mapping = {"start": 1}
    assert len(items[box.value:]) == 2
    assert len(items * box.value) == 3
    assert len(box.value * items) == 3
    assert tail(box.value) == 8
    assert len(items[counts[1]:]) == 2
    assert len(items[mapping["start"]:]) == 2
    for count in counts:
        assert len(items * count) == 3 * count
    for start, stop in [(0, 2), (1, 3)]:
        assert len(items[start:stop]) == 2
    assert len(counts[slice(1, 3)]) == 2
    assert len(items[slice(1, 3)]) == 2
    assert len(counts[box.selected]) == 2
    assert len(items[box.selected]) == 2
    return 0
'''


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_bound_provenance_does_not_enable_gc(tmp_path, optimize):
    result = LLVM().assert_matches_python(SCALAR_BOUND_PROVENANCE, directory=tmp_path,
                                          optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
    # Cover the unchanged side of the lifetime optimization too: reading a
    # value from a field, item, parameter or loop must not escape its owner.
    assert "define ptr @pyjs.gc.new()" not in result.native.llvm_ir


@pytest.mark.parametrize("optimize", [0, 2])
def test_constant_tuple_items_do_not_force_a_managed_heap(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
def main() -> str:
    result = 0
    for width in (0, 7, 20):
        for index in range(width):
            result += index
    widths = (2, 3, 4)
    for index in range(widths[1]):
        result += index
    names = ("first", "second")
    return str(result) + names[1]
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
    # Allocation-domain contract, not an incidental runtime-helper snapshot.
    assert "define ptr @pyjs.gc.new()" not in result.native.llvm_ir


@pytest.mark.parametrize("optimize", [0, 2])
def test_returned_tuple_iterators_retain_nonliteral_members(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold

class Box:
    def __init__(self, value: str):
        self.value = value

def create(prefix: str) -> Iterator[Box]:
    return iter((Box(prefix + "first"), Box(prefix + "second")))

def retain(values: tuple[Box, Box]) -> Box:
    for value in values:
        return value
    raise ValueError("empty")

def main() -> str:
    gc_set_threshold(1)
    values = create("kept")
    first = next(values)
    kept = retain((Box("member"), Box("other")))
    for index in range(128):
        discarded = create(str(index))
        next(discarded)
        gc_collect()
    first.value += " changed"
    kept.value += " retained"
    return first.value + next(values).value + kept.value
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["(1, 2)[Index(value)]", "[1, 2][Index(value)]",
                                        "((1, 2) * Index(value))[1]", "(Index(value) * (1, 2))[1]",
                                        "(1, 2)[::Index(value)][1]"])
def test_retaining_index_callback_survives_return_and_collection(tmp_path, optimize, expression):
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold

class Index:
    def __init__(self, value: int):
        self.value = "retained:" + str(value)
    def __index__(self) -> int:
        saved.append(self)
        gc_collect()
        return 1

saved: list[Index] = []

def read(value: int) -> int:
    return {expression}

def main() -> str:
    gc_set_threshold(1)
    for number in range(3):
        assert read(number) == 2
        gc_collect()
    return repr([item.value for item in saved])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_tuple_copy_boundaries_and_zero_step_validation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
def main() -> str:
    results: list[str] = []
    for length in (0, 1, 3):
        values = tuple(range(length))
        mutable = list(values)
        results.append(str((mutable[:] is mutable, mutable * 1 is mutable)))
        for count in (-2, 0, 1, 2):
            repeated = values * count
            results.append(str((repeated, repeated is values)))
        for start, stop, step in ((-10, 10, 1), (0, 10, 2),
                                  (-10, 10, -1), (0, 0, 1)):
            copied = values[start:stop:step]
            results.append(str((copied, copied is values)))
        try:
            values[slice(None, None, 0)]
        except ValueError:
            results.append("zero step")
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("constructor", ['(key, "name")', "tuple([key])"], ids=["fixed", "runtime"])
def test_tuple_aliases_preserve_cached_hash_and_member_identity(tmp_path, optimize, constructor):
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold

class Key:
    def __init__(self):
        self.calls = 0
    def __hash__(self) -> int:
        self.calls += 1
        gc_collect()
        return 10

def main() -> str:
    gc_set_threshold(1)
    key = Key()
    values = {constructor}
    first = hash(values)
    for alias in [tuple(values), values[:], values[-20:20:1], values * 1]:
        assert alias is values
        assert alias[0] is key
        assert hash(alias) == first
    before = key.calls
    reversed_values = values[::-1]
    hash(reversed_values)
    return str((before, key.calls, reversed_values is values))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
