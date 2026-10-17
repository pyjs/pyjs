"""Saved iterator values retain references without scanning scalar metadata."""

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
@pytest.mark.parametrize("body", [
    '''
from itertools import accumulate
def right(a: int | str, b: int | str) -> int | str:
    collect()
    return str(a) + '-' + str(b)
def main() -> str:
    collect()
    values: list[int | str] = [1, "second", 3]
    return repr(list(accumulate(values, right)))
''',
    '''
from typing import Iterator
class Source:
    def __init__(self):
        self.index = 0
    def pull(self) -> int | str:
        collect()
        self.index += 1
        return self.index if self.index < 3 else "stop"
def make(stop: int | str) -> Iterator[int | str]:
    return iter(Source().pull, stop)
def main() -> str:
    values = make(''.join(['st', 'op']))
    collect()
    return repr(list(values))
''',
], ids=["accumulate", "sentinel"])
def test_tagged_saved_values_allocate_their_full_layout(tmp_path, optimize, managed, body):
    prefix = ("from pyjs.native import gc_collect, gc_set_threshold\n"
              "def collect() -> None:\n    gc_set_threshold(1)\n    gc_collect()\n" if managed
              else "def collect() -> None:\n    pass\n")
    result = LLVM().assert_matches_python(prefix + body, directory=tmp_path, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_saved_references_survive_history_growth_and_collecting_keys(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from itertools import accumulate, groupby, pairwise, repeat, tee, zip_longest
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold

class Box:
    def __init__(self, value: int):
        self.value = value

def boxes() -> Iterator[Box]:
    for value in range(75):
        yield Box(value)

def history() -> Iterator[Box]:
    fast, slow = tee(boxes())
    for _ in range(65):
        next(fast)
    left, right = tee(fast)
    assert next(left).value == next(right).value == 65
    return slow

def key(value: Box) -> str:
    gc_collect()
    return 'group-' + str(value.value // 3)

def combine(left: Box, right: Box) -> Box:
    gc_collect()
    return Box(left.value + right.value)

def main() -> str:
    gc_set_threshold(1)
    saved = history()
    gc_collect()
    assert [value.value for value in saved] == list(range(75))
    repeated = repeat(Box(9), 3)
    totals = accumulate(boxes(), combine, initial=Box(0))
    paired = pairwise(boxes())
    filled = zip_longest([Box(1)], [Box(2), Box(3)], fillvalue=Box(8))
    gc_collect()
    assert [value.value for value in repeated] == [9, 9, 9]
    assert [value.value for value in totals][-1] == sum(range(75))
    assert [(a.value, b.value) for a, b in paired] == [(i, i + 1) for i in range(74)]
    assert [(a.value, b.value) for a, b in filled] == [(1, 2), (8, 3)]
    groups = groupby(boxes(), key)
    result: list[str] = []
    for name, members in groups:
        gc_collect()
        result.append(name + ':' + str([value.value for value in members]))
    return str(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr
