import ast

import pytest

from pyjs.analysis.ir import Comprehension
from pyjs.analysis.lifetime import lambda_captures
from pyjs.analysis.source import analyze_source
from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.analysis import JVM_ENVIRONMENT
from tests.java.test_context_managers import assert_text_matches_python


def test_comprehension_ir_keeps_source_and_capture_state_outside_loop_scope():
    source = '''def main() -> int:
    values = [1, 2]
    offset = 10
    result = [n + offset for n in values if n > 1]
    return result[0]
'''
    with analyze_source(source, wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        node, = [node for block in analysis.entry_point.ir.blocks for node in ast.walk(block)
                 if isinstance(node, Comprehension)]
        function = node.function
        assert ast.dump(node.source) == "Name(id='values', ctx=Load())"
        assert [value.id for value in node.captures] == ["offset"]
        assert [value.arg for value in function.args.args] == [
            "__comprehension_source", "offset", "__capture_bound",
        ]
        assert function.jvm_capture_flags == {"offset": "__capture_bound"}
        assert [value.name for value in function.obj.parameter_types] == [
            "list__int", "int", "bool",
        ]
        assert function.obj.return_type.name == "list__int"
        assert lambda_captures(function) == {}
        assert "n" not in analysis.entry_point.scope.names


@pytest.mark.parametrize("expression, result", [
    ("[n + offset for n in values if n != 2]", "str(result[0]) + ':' + str(result[1])"),
    ("{str(n): n + offset for n in values if n != 2}", 'str(result["1"]) + ":" + str(result["3"])'),
    ("{str(n % 2) for n in values}", 'str(len(result))'),
])
def test_eager_comprehension_with_outer_binding(tmp_path, expression, result):
    assert_text_matches_python(f'''def main() -> str:
    values = [1, 2, 3]
    offset = 10
    result = {expression}
    return {result}
''', tmp_path)


def test_nested_comprehensions_keep_scope_and_effect_order(tmp_path):
    assert_text_matches_python('''
def mark(events: list[int], value: int) -> int:
    events.append(value)
    return value
def main() -> str:
    events: list[int] = []
    values = [1, 2]
    n = 99
    rows = [[mark(events, n * 10 + m) for m in values if m != n] for n in values]
    table = {str(mark(events, n)): mark(events, n + 10) for n in [1, 1, 2]}
    values = [values * 2 for values in values]
    result = str(n) + ":" + str(rows[0][0]) + ":" + str(rows[1][0])
    result += ":" + str(table["1"]) + ":" + str(table["2"])
    for event in events:
        result += ":" + str(event)
    for value in values:
        result += ":" + str(value)
    return result
''', tmp_path)


def test_comprehension_failure_preserves_previous_assignment_and_effects(tmp_path):
    assert_text_matches_python('''
def checked(events: list[int], value: int) -> int:
    events.append(value)
    if value == 2:
        raise ValueError("rejected")
    return value * 2
def main() -> str:
    events: list[int] = []
    values = [42]
    try:
        values = [checked(events, value) for value in [1, 2, 3]]
    except ValueError as error:
        return str(error) + ":" + str(values[0]) + ":" + str(len(events))
    return "missing exception"
''', tmp_path)


@pytest.mark.parametrize("source", [
    '["a", "😀", "z"]',
    '"a😀z"',
    '{"a": 1, "😀": 2, "z": 3}',
])
def test_comprehension_iterates_supported_sources_in_order(tmp_path, source):
    assert_text_matches_python(f'''def main() -> str:
    source = {source}
    return ",".join([letter for letter in source if letter != "z"])
''', tmp_path)


@pytest.mark.parametrize("failure", [0, 1, 2, 3])
def test_source_filter_and_body_failures_keep_call_operand_order(tmp_path, failure):
    assert_text_matches_python(f'''
def mark(events: list[str], phase: int) -> int:
    events.append(str(phase))
    if phase == {failure}:
        raise ValueError("stopped")
    return phase
def source(events: list[str]) -> list[int]:
    mark(events, 1)
    return [0, 1]
def combine(left: int, middle: list[int], right: int) -> int:
    return left + len(middle) + right
def main() -> str:
    events: list[str] = []
    try:
        combine(mark(events, 0),
                [mark(events, 3) for value in source(events) if mark(events, 2)],
                mark(events, 4))
    except ValueError:
        pass
    return ",".join(events)
''', tmp_path)


def test_comprehension_reads_mutated_captured_objects_each_iteration(tmp_path):
    assert_text_matches_python('''
def advance(values: list[int]) -> bool:
    values[0] += 1
    return True
def main() -> str:
    values = [10]
    result = [values[0] for item in [1, 2, 3] if advance(values)]
    return str(result[0]) + ":" + str(result[2]) + ":" + str(values[0])
''', tmp_path)


@pytest.mark.parametrize("expression", [
    "[n for n in [1] if later for later in [2]]",
    "{str(n): later for n in [1] if later for later in [2]}",
])
def test_forward_comprehension_locals_do_not_read_outer_bindings(tmp_path, expression):
    assert_text_matches_python(f'''def main() -> str:
    later = "outer"
    try:
        values = {expression}
    except UnboundLocalError:
        return later
    return str(len(values))
''', tmp_path)


def test_comprehension_in_method_reads_current_receiver_and_objects(tmp_path):
    assert_text_matches_python('''
class Row:
    def __init__(self, rank: int):
        self.rank = rank
class Table:
    def __init__(self, offset: int):
        self.offset = offset
    def ranks(self, rows: list[Row]) -> list[int]:
        return [row.rank + self.offset for row in rows]
def main() -> str:
    rows = [Row(1), Row(2)]
    table = Table(10)
    first = table.ranks(rows)
    rows[0].rank = 3
    table.offset = 20
    second = table.ranks(rows)
    return str(first[0]) + ":" + str(second[0])
''', tmp_path)


@pytest.mark.parametrize("expression", [
    "[n + offset for n in source]",
    "{str(n): n + offset for n in source}",
    "[[n + offset for n in source] for row in [0]]",
    "[n + offset for n in source if n < 0]",
])
def test_outer_binding_is_checked_only_when_consumed(tmp_path, expression):
    assert_text_matches_python(f'''
def collect(bound: bool, source: list[int]) -> str:
    if bound:
        offset = 10
    try:
        values = {expression}
        return str(len(values))
    except UnboundLocalError:
        return "unbound"
def main() -> str:
    empty: list[int] = []
    return collect(False, empty) + ":" + collect(False, [1]) + ":" + collect(True, [1])
''', tmp_path)


def test_outer_range_retains_explicit_first_class_range_boundary():
    with pytest.raises(JVMUnsupported, match="unsupported JVM value type range"):
        transpile_jvm('def main() -> int:\n    return len([n for n in range(3)])\n')


def test_represented_items_are_not_erased_by_the_comprehension_frame():
    with pytest.raises(JVMUnsupported, match="JVM callbacks with represented parameters or results"):
        transpile_jvm('''from pyjs import int8
def main() -> int:
    values = [int8(127)]
    result = [n + int8(1) for n in values]
    return int(result[0])
''')
