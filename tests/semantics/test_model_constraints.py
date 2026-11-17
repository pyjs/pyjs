from tests.semantics.helpers import assert_semantics


def test_json_field_constraints_match_python():
    assert_semantics('''from pyjs import js
from tests.model_constraints_contract import check_constraints
@js
def main() -> None:
    print(check_constraints())
main()
''')
