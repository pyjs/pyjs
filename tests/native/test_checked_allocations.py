import pytest

from pyjs.native.llvm import transpile_llvm
from tests.native.allocation_support import run_allocation_case

# Each operation is swept until every allocation boundary has failed once.
# Native fault injection cannot be compared to CPython, so the same scenario
# checks observable preservation and reruns the operation after recovery.
CASES = [
    ('text + text', 'assert result == "café" * 2'),
    ('text * 5', 'assert result == "café" * 5'),
    ('text[::-1]', 'assert result == "éfac"'),
    ('text[slice(None, None, -1)]', 'assert result == "éfac"'),
    ('b"a\\x00\\xffb"[slice(None, None, -2)]', 'assert result == b"b\\x00"'),
    ('text[3]', 'assert result == "é"'),
    ('text.upper()', 'assert result == "CAFÉ"'),
    ('text.replace("a", "long")', 'assert result == "clongfé"'),
    ('text.strip("cé")', 'assert result == "af"'),
    ('text.split("a")', 'assert "|".join(result) == "c|fé"'),
    ('"|".join(words)', 'assert result == "café|café"'),
    ('str(number)', 'assert result == "123"'),
    ('str(decimal)', 'assert result == "1.25"'),
    ('float("1.25")', 'assert result == 1.25'),
    ('values.copy()', 'assert len(result) == 4'),
    ('values[::-1]', 'assert result[0] == 4'),
    ('values[slice(None, None, -1)]', 'assert result == [4, 3, 2, 1]'),
    ('values * 4', 'assert len(result) == 16'),
    ('values + values', 'assert len(result) == 8'),
    ('mapping.copy()', 'assert result[1] == 10'),
    ('Box(number)', 'assert result.value == 123'),
    ('(number, text)', 'assert result[0] == 123'),
    ('{number: text}', 'assert result[123] == "café"'),
    ('{number}', 'assert 123 in result'),
    ('div({"title": text}, span(text))', 'assert render_html(result).startswith("<div")'),
    ('render_html(tree)', 'assert result == "<div><span>café</span></div>"'),
]


@pytest.mark.parametrize('expression, check', CASES)
@pytest.mark.parametrize('managed', [False, True], ids=['arena', 'gc'])
@pytest.mark.parametrize('optimize', [0, 2])
def test_allocation_failure_recovers_at_every_boundary(tmp_path, expression, check, managed, optimize):
    source = f'''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import div, span
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm, remaining

class Box:
    def __init__(self, value: int):
        self.value = value

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    text = "café"
    number = 123
    decimal = 1.25
    words = [text, text]
    values = [1, 2, 3, 4]
    mapping = {{1: 10}}
    tree = div(span(text))
    attempt = 1
    caught = 0
    while attempt < 100:
        arm(attempt)
        succeeded = False
        try:
            result = {expression}
            arm(0)
            {check}
            succeeded = True
        except MemoryError:
            arm(0)
            caught += 1
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        assert text == "café"
        assert len(values) == 4 and values[0] == 1 and values[3] == 4
        assert mapping[1] == 10
        recovered = {expression}
        if succeeded:
            return 0 if caught > 0 else 1
        attempt += 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize('managed', [False, True], ids=['arena', 'gc'])
@pytest.mark.parametrize('optimize', [0, 2])
@pytest.mark.parametrize('operation', [
    'values.append(5)', 'values.insert(1, 5)', 'values.extend(other)',
    'values *= 5', 'values[1:2] = other', 'values[::-1] = values',
    'values[slice(1, 2)] = other', 'values[slice(None, None, -1)] = values',
    'values[1:2] = iter(other)', 'values[slice(1, 2)] = iter(other)',
    'mapping[5] = 50', 'mapping.update(additions)', 'members.add(5)',
])
def test_failed_mutations_preserve_existing_storage(tmp_path, managed, optimize, operation):
    source = f'''
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    attempt = 1
    caught = 0
    while attempt < 30:
        values = [1, 2, 3, 4]
        alias = values
        other = [6, 7, 8, 9, 10]
        mapping = {{1: 10, 2: 20, 3: 30, 4: 40}}
        additions = {{5: 50, 6: 60}}
        members = {{1, 2, 3, 4}}
        succeeded = False
        arm(attempt)
        try:
            {operation}
            arm(0)
            succeeded = True
        except MemoryError:
            arm(0)
            caught += 1
            assert len(alias) == 4
            assert alias[0] == 1 and alias[1] == 2 and alias[3] == 4
            assert mapping[1] == 10 and mapping[4] == 40
            assert 1 in members and 4 in members
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        {operation}
        if succeeded:
            return 0 if caught > 0 else 1
        attempt += 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)
