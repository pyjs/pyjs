import pytest

from pyjs.native.llvm import transpile_llvm
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("expression, check", [
    ("iter(values)", "next(result) == 1"),
    ("reversed(values)", "next(result) == 3"),
    ("enumerate(values, 4)", "next(result) == (4, 1)"),
    ("zip(values, words, strict=True)", 'next(result) == (1, "a")'),
    ("list(zip(values, words))", 'result[1] == (2, "é")'),
    ("list(enumerate(iter(words)))", 'result[2] == (2, "😀")'),
    ("dict(zip(words, values))", 'result == {"a": 1, "é": 2, "😀": 3}'),
    ('list(reversed("aé😀"))', 'result == ["😀", "é", "a"]'),
    ('"|".join(iter(words))', 'result == "a|é|😀"'),
    ('bytes(iter(values))', 'result == b"\\x01\\x02\\x03"'),
    ('[word + "!" for word in words if word]', 'result == ["a!", "é!", "😀!"]'),
    ('{word + "!" for word in words}', 'result == {"a!", "é!", "😀!"}'),
    ('{word: len(word) for word in words}', 'result == {"a": 1, "é": 1, "😀": 1}'),
    ('list(enumerate(map(lambda word: word + "!", words)))', 'result[2] == (2, "😀!")'),
    ('list(filter(lambda word: len(word) > 0, map(lambda word: word + "!", words)))',
     'result == ["a!", "é!", "😀!"]'),
    ('"|".join(word + "!" for word in words)', 'result == "a!|é!|😀!"'),
    ('list(generated(values))', 'result == [11, 12, 13]'),
    ('list((value, word) for value in values for word in words if value == len(word))',
     'result == [(1, "a"), (1, "é"), (1, "😀")]'),
])
@pytest.mark.parametrize("managed", [False, True], ids=["inferred", "gc-stress"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_allocation_sweep(tmp_path, expression, check, managed, optimize):
    source = f'''
from collections.abc import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def generated(values: list[int]) -> Iterator[int]:
    for value in values:
        yield value + 10

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    values = [1, 2, 3]
    words = ["a", "é", "😀"]
    failures = 0
    for attempt in range(1, 100):
        complete = False
        try:
            arm(attempt)
            result = {expression}
            arm(0)
            assert {check}
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        assert values == [1, 2, 3] and words == ["a", "é", "😀"]
        result = {expression}
        assert {check}
        if complete:
            return 0 if failures else 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_batch_row_failure_precedes_consumption_and_assignment(tmp_path, optimize):
    source = transpile_llvm('''
from itertools import batched
from pyjs.native import gc_collect
from tests.native.allocation_support import arm, remaining
class Box:
    def __init__(self, value: int):
        self.value = value
def main() -> int:
    values = [Box(index) for index in range(20)]
    saved: tuple[Box, ...] = (Box(99),)
    probe = batched(values, 16)
    arm(1000)
    row = next(probe)
    stages = 1000 - remaining()
    arm(0)
    assert 0 < stages < 1000 and len(row) == 16
    for failure in range(1, stages + 1):
        source = iter(values)
        cursor = batched(source, 16)
        row = saved
        caught = False
        arm(failure)
        try:
            for row in cursor:
                arm(0)
                return 1
        except MemoryError:
            caught = True
        arm(0)
        gc_collect()
        assert caught and row is saved and next(source).value == 0
        row = next(cursor)
        assert len(row) == 16 and row[0].value == 1 and row[15].value == 16
        row = next(cursor)
        assert len(row) == 3 and row[0].value == 17 and row[2].value == 19
        assert next(cursor, saved) is saved
        arm(1)
        assert next(cursor, saved) is saved and remaining() == 1
        arm(0)
    source = iter(values)
    huge = batched(source, 9223372036854775807)
    try:
        next(huge)
        return 2
    except MemoryError:
        assert next(source).value == 0
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""
