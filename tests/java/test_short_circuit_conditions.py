import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import MIXED_TRUTH_CONDITION_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


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
