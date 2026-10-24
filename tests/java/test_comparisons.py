from tests.backend_semantics import CHAINED_COMPARISON_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


def test_shared_chained_comparison_contract(tmp_path):
    assert_matches_python(CHAINED_COMPARISON_CONTRACT.source, tmp_path)


def test_nested_chains_preserve_outer_bindings_and_representations(tmp_path):
    assert_text_matches_python('''
from pyjs import int8, float32
def main() -> str:
    assert "a" < "b" < ("c" if 0 < 1 < 2 else "a")
    assert 1 < (2 if "a" < "b" < "c" else 0) < 3
    assert int8(-1) < int8(0) < int8(1)
    assert float32(-1.5) < float32(0.5) < float32(1.5)
    assert 0 < 1 in [1, 2]
    value = "value"
    assert None is None is not value
    return "matched"
''', tmp_path)


def test_string_order_uses_code_points_not_utf16_units(tmp_path):
    values = ["", "a", "ab", "é", "雪", "\ud800", "\udfff", "\ue000", "😀", "a😀"]
    checks = []
    for left in values:
        for right in values:
            checks.extend(f"    assert ({left!r} {operator} {right!r}) == {expected!r}"
                          for operator, expected in (
                              ("<", left < right), ("<=", left <= right),
                              (">", left > right), (">=", left >= right),
                          ))
    assert_text_matches_python(
        "def main() -> str:\n" + "\n".join(checks) + '\n    return "matched"\n', tmp_path,
    )


def test_chained_comparisons_retain_virtual_calls_and_exception_order(tmp_path):
    assert_text_matches_python('''
class Value:
    def __init__(self, number: int, events: list[int]):
        self.number = number
        self.events = events
    def __lt__(self, other: Value) -> bool:
        self.events.append(self.number)
        if other.number == 99:
            raise ValueError("comparison failed")
        return self.number < other.number
def fail(events: list[int]) -> Value:
    events.append(99)
    raise ValueError("operand failed")
def main() -> str:
    events: list[int] = []
    first = Value(1, events)
    second = Value(2, events)
    third = Value(3, events)
    assert first < second < third
    assert len(events) == 2 and events[0] == 1 and events[1] == 2
    assert not second < first < fail(events)
    assert len(events) == 3 and events[2] == 2
    try:
        first < Value(99, events) < fail(events)
    except ValueError as error:
        assert str(error) == "comparison failed"
    else:
        return "missed comparison failure"
    assert len(events) == 4 and events[3] == 1
    try:
        first < second < fail(events)
    except ValueError as error:
        assert str(error) == "operand failed"
    else:
        return "missed operand failure"
    assert len(events) == 6 and events[4] == 1 and events[5] == 99
    return "matched"
''', tmp_path)
