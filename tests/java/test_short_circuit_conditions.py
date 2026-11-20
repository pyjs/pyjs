import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import MIXED_TRUTH_CONDITION_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


@pytest.mark.parametrize("condition", [
    "value",
    "value if flag else other",
    "None if flag else value",
    "(value if flag else other) and text",
    "text or (value if flag else None)",
    "not (value if flag else other)",
])
@pytest.mark.parametrize("statement", ["if ({condition}): return 1", "return 1 if ({condition}) else 0"])
def test_non_truth_protocol_conditional_arms_have_a_located_diagnostic(condition, statement):
    source = '''class Plain:
    def __init__(self):
        self.value = 1
def check(flag: bool, value: Plain, other: Plain, text: str) -> int:
    ''' + statement.format(condition=condition) + '''
    return 0
def main() -> int:
    return check(True, Plain(), Plain(), "text")
'''
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(source)
    assert str(caught.value) == "JVM branch conditions must be bool at line 5"


def test_value_returning_mixed_boolean_union_remains_explicit():
    with pytest.raises(JVMUnsupported, match="JVM union has incompatible runtime types"):
        transpile_jvm('''
def choose(text: str, flag: bool) -> str | bool:
    return text and flag
def main() -> bool:
    return bool(choose("value", True))
''')


def test_shared_mixed_truth_condition_contract(tmp_path):
    assert_matches_python(MIXED_TRUTH_CONDITION_CONTRACT.source, tmp_path)


def test_mixed_truth_condition_android_dex(tmp_path):
    assert_compiles_to_android_dex(MIXED_TRUTH_CONDITION_CONTRACT.source, tmp_path)


def test_mixed_string_boolean_condition(tmp_path):
    assert_text_matches_python('''
def check(day: str, invalid: bool) -> str:
    if day and invalid:
        return "invalid"
    return "ok"
def main() -> str:
    return check("", True) + ":" + check("day", True) + ":" + check("day", False)
''', tmp_path)
