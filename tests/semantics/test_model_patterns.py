from tests.model_patterns_contract import matcher_source
from tests.semantics.helpers import assert_semantics


def test_model_patterns_match_python():
    assert_semantics('''from pyjs import js
from tests.model_patterns_contract import check_patterns
@js
def main() -> None:
    print(check_patterns())
main()
''')


def test_portable_matcher_cases_in_javascript():
    source = matcher_source().replace("def main() -> str:", "def check() -> str:")
    assert_semantics(source + "\n@js\ndef main() -> None:\n    print(check())\nmain()")


def test_large_and_grouped_patterns_in_javascript():
    assert_semantics('''from pyjs import js
from tests.model_patterns_contract import check_large_and_grouped_patterns
@js
def main() -> None:
    print(check_large_and_grouped_patterns())
main()
''')
