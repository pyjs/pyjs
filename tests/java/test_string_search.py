import pytest

from pyjs.java import JVMUnsupported, read_jvm_class, transpile_jvm
from tests.backend_semantics import STRING_FIND_CONTRACT
from tests.java.test_exceptions import assert_matches_python
from tests.semantics.helpers import run_javascript, run_python


def test_shared_string_find_contract(tmp_path):
    assert_matches_python(STRING_FIND_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("method", ["find", "rfind"])
def test_unicode_bounds_match_python(tmp_path, method):
    cases = []
    for value, needle in [("", ""), ("aaa", "aa"), ("aé😀é", "é"),
                          ("aé😀é", "😀"), ("aé😀é", ""), ("a\0b\0", "\0"),
                          ("😀x\ud83dy", "\ud83d"), ("😀x\ude00y", "\ude00"),
                          ("😀", "\ud83d"), ("😀", "\ude00"), ("abc", "abcdef")]:
        for start, end in [(-99, 99), (0, 99), (1, 3), (3, 1), (4, 4), (5, 99),
                           (-3, -1), (0, -99), (True, False), (None, None),
                           (-9223372036854775808, 9223372036854775807),
                           (9223372036854775807, 9223372036854775807)]:
            expected = getattr(value, method)(needle, start, end)
            cases.append(f"    assert {value!r}.{method}({needle!r}, {start!r}, {end!r}) == {expected}")
    source = "def main() -> int:\n" + "\n".join(cases) + "\n    return 0\n"
    assert_matches_python(source, tmp_path)


def test_search_arguments_are_evaluated_once_in_order(tmp_path):
    source = '''
from pyjs import js
@js
def text(events: list[int], index: int, value: str) -> str:
    events.append(index)
    return value
@js
def bound(events: list[int], index: int, value: int) -> int:
    events.append(index)
    return value
def main() -> int:
    events: list[int] = []
    result = text(events, 1, "a😀b😀").find(text(events, 2, "😀"),
        bound(events, 3, 2), bound(events, 4, 4))
    assert result == 3 and len(events) == 4
    for index in range(4):
        assert events[index] == index + 1
    assert "😀x".find("x", True) == 1
    assert "😀x".rfind("", False, True) == 1
    return 0
'''
    assert_matches_python(source, tmp_path)
    expected = run_python(source + "\nmain()")
    actual, _ = run_javascript(source + "\nmain()")
    assert actual == expected


def test_search_helpers_are_demand_driven():
    compiled = transpile_jvm('def main() -> int:\n    return "abc".find("b")\n')
    methods = {item.name for item in read_jvm_class(compiled.classes["PyjsProgram"]).methods}
    assert "pyjs_string_find" in methods and "pyjs_string_boundary" in methods
    assert "pyjs_string_rfind" not in methods


def test_runtime_optional_bounds_have_a_focused_boundary():
    with pytest.raises(JVMUnsupported, match="string search bounds must be integers or None"):
        transpile_jvm('''
def search(start: int | None) -> int:
    return "abc".find("b", start)
def main() -> int:
    return search(None)
''')
