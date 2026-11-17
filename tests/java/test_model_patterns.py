from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex
from tests.model_patterns_contract import matcher_source

SOURCE = '''from tests.model_patterns_contract import check_patterns
def main() -> str:
    return check_patterns()
'''


def test_model_patterns_match_python(tmp_path):
    assert_text_matches_python(SOURCE, tmp_path)


def test_model_patterns_compile_to_android(tmp_path):
    assert_compiles_to_android_dex(SOURCE, tmp_path)


def test_portable_matcher_cases_on_jvm(tmp_path):
    assert_text_matches_python(matcher_source(), tmp_path)
