import pytest

from pyjs.java import JVMUnsupported, read_jvm_class, transpile_jvm
from tests.backend_semantics import STRING_AFFIX_BOUNDS_CONTRACT, STRING_FIND_CONTRACT
from tests.java.test_exceptions import assert_matches_python
from tests.semantics.helpers import run_javascript, run_python


@pytest.mark.parametrize("contract", [STRING_FIND_CONTRACT, STRING_AFFIX_BOUNDS_CONTRACT],
                         ids=["find", "affixes"])
def test_shared_string_search_contract(tmp_path, contract):
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("method", ["find", "rfind", "startswith", "endswith"])
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


@pytest.mark.parametrize("method, expected", [("find", "3"), ("startswith", "False"),
                                             ("endswith", "True")])
def test_search_arguments_are_evaluated_once_in_order(tmp_path, method, expected):
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
    result = text(events, 1, "a😀b😀").METHOD(text(events, 2, "😀"),
        bound(events, 3, 2), bound(events, 4, 4))
    assert result == EXPECTED and len(events) == 4
    for index in range(4):
        assert events[index] == index + 1
    assert "😀x".find("x", True) == 1
    assert "😀x".rfind("", False, True) == 1
    return 0
'''.replace("METHOD", method).replace("EXPECTED", expected)
    assert_matches_python(source, tmp_path)
    expected = run_python(source + "\nmain()")
    actual, _ = run_javascript(source + "\nmain()")
    assert actual == expected


def test_search_helpers_are_demand_driven():
    compiled = transpile_jvm('def main() -> int:\n    return "abc".find("b")\n')
    methods = {item.name for item in read_jvm_class(compiled.classes["PyjsProgram"]).methods}
    assert "pyjs_string_find" in methods and "pyjs_string_boundary" in methods
    assert "pyjs_string_rfind" not in methods


@pytest.mark.parametrize("method", ["startswith", "endswith"])
def test_bounded_affix_helpers_do_not_emit_search_or_copy_helpers(method):
    compiled = transpile_jvm(f'def main() -> int:\n    return int("abc".{method}("b", 1, 2))\n')
    methods = {item.name for item in read_jvm_class(compiled.classes["PyjsProgram"]).methods
               if item.name.startswith("pyjs_string_")}
    assert methods == {"pyjs_string_boundary", f"pyjs_string_{method}_bounded"}


@pytest.mark.parametrize("method", ["startswith", "endswith"])
def test_tuple_affixes_have_a_focused_jvm_boundary(method):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'def main() -> int:\n    return int("abc".{method}(("a", "b"), 1))\n')
    assert str(caught.value) == (
        "JVM string search requires a string substring at line 2 while compiling _pyjs_java_.main")


@pytest.mark.parametrize("method", ["find", "startswith", "endswith"])
def test_runtime_optional_bounds_have_a_focused_boundary(method):
    with pytest.raises(JVMUnsupported, match="string search bounds must be integers or None"):
        transpile_jvm('''
def search(start: int | None) -> int:
    return int("abc".METHOD("b", start))
def main() -> int:
    return search(None)
'''.replace("METHOD", method))
