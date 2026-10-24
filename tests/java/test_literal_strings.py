import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from tests.backend_semantics import LITERAL_STRING_CONTRACT
from tests.java.test_exceptions import assert_matches_python


def test_shared_literal_string_contract(tmp_path):
    assert_matches_python(LITERAL_STRING_CONTRACT.source, tmp_path)


def test_literal_types_still_reject_out_of_domain_arguments():
    with pytest.raises(CompilationError, match="Literal"):
        transpile_jvm('''from typing import Literal
def label(kind: Literal["text", "list"]) -> str:
    return kind
def main() -> str:
    return label("other")
''', filename="literal.py")
