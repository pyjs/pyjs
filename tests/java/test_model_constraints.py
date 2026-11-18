import pytest

from pyjs.java.json_codegen import JSONCodegen
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex
from tests.model_constraints_contract import Entry

SOURCE = '''from tests.model_constraints_contract import check_constraints
def main() -> str:
    return check_constraints()
'''


def test_json_field_constraints_match_python(tmp_path):
    assert_text_matches_python(SOURCE, tmp_path)


@pytest.mark.parametrize("contract", ["check_grouped_constraints", "check_duplicate_constraints"])
def test_constraint_metadata_and_final_values_match_python(tmp_path, contract):
    assert_text_matches_python(f'''from tests.model_constraints_contract import {contract}
def main() -> str:
    return {contract}()
''', tmp_path)


def test_constrained_model_codecs_compile_to_android(tmp_path):
    assert_compiles_to_android_dex('''from tests.model_constraints_contract import (
    check_constraints, check_grouped_constraints, check_duplicate_constraints,
)
def main() -> str:
    return check_constraints() + check_grouped_constraints() + check_duplicate_constraints()
''', tmp_path)


def test_length_bounds_measure_each_decoded_field_once():
    generator = JSONCodegen()
    length = generator.type_name(len)
    error = generator.type_name(ValueError)
    generator.check_constraints(Entry.model_fields["title"], "title")
    assert generator.lines == [
        f"_pyjs_value_1 = {length}(title)",
        "if not (_pyjs_value_1 >= 1):",
        f"    raise {error}('Invalid JSON field constraint: min_length')",
        "if not (_pyjs_value_1 <= 2):",
        f"    raise {error}('Invalid JSON field constraint: max_length')",
    ]
