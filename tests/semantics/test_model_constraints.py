import pytest

from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("contract", ["check_grouped_constraints", "check_duplicate_constraints"])
def test_constraint_metadata_and_final_values_match_python(contract):
    assert_semantics(f'''from pyjs import js
from tests.model_constraints_contract import {contract}
@js
def main() -> None:
    print({contract}())
main()
''')


def test_json_field_constraints_match_python():
    assert_semantics('''from pyjs import js
from tests.model_constraints_contract import check_constraints
@js
def main() -> None:
    print(check_constraints())
main()
''')


def test_nonnumeric_bounds_do_not_prevent_compilation():
    assert_semantics('''from pyjs import js
from tests.lib.test_model_constraints import test_nonnumeric_bound_does_not_prevent_model_compilation
@js
def main() -> None:
    test_nonnumeric_bound_does_not_prevent_model_compilation()
    print("validated")
main()
''')
