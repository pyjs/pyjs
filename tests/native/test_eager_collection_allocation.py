import pytest

from pyjs.native.llvm import transpile_llvm
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("expression, check", [
    ("list(values)", "assert result == values and result is not values"),
    ("tuple(values)", "assert result == (1, 2, 3, 4)"),
    ("tuple(values)[::-1] * 2", "assert result == (4, 3, 2, 1, 4, 3, 2, 1)"),
    ("math.fsum(values)", "assert result == 10.0"),
    ("list(range(9))", "assert len(result) == 9 and result[8] == 8"),
    ('list("aé😀")', 'assert "".join(result) == "aé😀"'),
    ("set(values)", "assert result == {1, 2, 3, 4}"),
    ("frozenset(values)", "assert result == frozenset([1, 2, 3, 4])"),
    ("frozenset(members).union(more)", "assert result == frozenset([1, 2, 3, 4, 5, 6])"),
    ("frozenset(members).intersection(iter(values))", "assert result == members"),
    ("dict(mapping)", "assert result == mapping and result is not mapping"),
    ("dict(pairs)", 'assert result == {"a": 1, "b": 2}'),
    ("list(mapping.items())", "assert len(result) == 4"),
    ("sorted(values, reverse=True)", "assert result == [4, 3, 2, 1]"),
    ("members | more", "assert result == {1, 2, 3, 4, 5, 6}"),
    ("members & more", "assert result == {3, 4}"),
    ("members - more", "assert result == {1, 2}"),
    ("members ^ more", "assert result == {1, 2, 5, 6}"),
    ("members.union([5, 6])", "assert result == {1, 2, 3, 4, 5, 6}"),
    ("members.intersection(iter(values))", "assert result == members"),
    ("mapping.keys()", 'assert "c" in result and len(result) == 4'),
])
@pytest.mark.parametrize("managed", [False, True], ids=["inferred", "gc-stress"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_eager_allocation_boundaries_preserve_inputs_and_retry(tmp_path, expression, check, managed, optimize):
    source = f'''
import math
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    values = [1, 2, 3, 4]
    mapping = {{"a": 1, "b": 2, "c": 3, "d": 4}}
    pairs = [("a", 1), ("b", 2)]
    members = {{1, 2, 3, 4}}
    more = {{3, 4, 5, 6}}
    attempt = 1
    failures = 0
    while attempt < 100:
        arm(attempt)
        complete = False
        try:
            result = {expression}
            arm(0)
            {check}
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        assert values == [1, 2, 3, 4]
        assert mapping == {{"a": 1, "b": 2, "c": 3, "d": 4}}
        assert members == {{1, 2, 3, 4}} and more == {{3, 4, 5, 6}}
        recovered = {expression}
        if complete:
            return 0 if failures else 1
        attempt += 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("managed", [False, True], ids=["inferred", "gc-stress"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_sort_failure_leaves_aliases_intact(tmp_path, managed, optimize):
    source = f'''
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    values = [4, 1, 3, 2]
    alias = values
    arm(1)
    caught = False
    try:
        values.sort()
    except MemoryError:
        caught = True
    finally:
        arm(0)
    assert caught and values is alias
    assert values == [4, 1, 3, 2]
    {"gc_collect()" if managed else "pass"}
    values.sort()
    assert alias == [1, 2, 3, 4]
    values.sort(reverse=True)
    return 0 if alias == [4, 3, 2, 1] else 1
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("initial, operation, repair, valid, expected", [
    ("{0}", "value.update(range(1, 12))", "value.add(0)",
     "value.issubset(range(12))", "value == set(range(12))"),
    ("{0}", "value.update(iter(range(1, 12)))", "value.add(0)",
     "value.issubset(range(12))", "value == set(range(12))"),
    ("{0, 1, 2, 3, 4}", "value.intersection_update(iter(range(2, 6)), iter([3]))", "value.update(range(5))",
     "value == {0, 1, 2, 3, 4} or value == {3}", "value == {3}"),
    ("{0}", "value.symmetric_difference_update(set(range(12)))", "value.add(0)",
     "value.issubset(range(12))", "value == set(range(1, 12))"),
    ("{0: 0}", "value.update([(1, 1), (2, 2), (3, 3), (4, 4)])", "value[0] = 0",
     "set(value.keys()).issubset(range(5))", "value == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}"),
    ('["a"]', 'value.extend("é😀xyz")', 'value.append("a")',
     '"aé😀xyz".startswith("".join(value))', '"".join(value) == "aé😀xyz"'),
], ids=["set-update", "iterator-update", "atomic-intersection", "symmetric-update", "pair-update", "character-extend"])
@pytest.mark.parametrize("managed", [False, True], ids=["inferred", "gc-stress"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_mutations_remain_valid_and_can_be_repaired(
    tmp_path, initial, operation, repair, valid, expected, managed, optimize,
):
    source = f'''
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    attempt = 1
    failures = 0
    while attempt < 100:
        value = {initial}
        alias = value
        arm(attempt)
        complete = False
        try:
            {operation}
            arm(0)
            assert {expected}
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        assert value is alias and {valid}
        value.clear()
        {repair}
        {operation}
        assert {expected}
        if complete:
            return 0 if failures else 1
        attempt += 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)
