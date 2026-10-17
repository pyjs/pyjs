import pytest

from tests.backend_semantics import (
    SEQUENCE_CONSTRUCTOR_REPRESENTATION_CONTRACT,
    SEQUENCE_STORAGE_COERCION_CONTRACT,
    UNION_STORAGE_COERCION_CONTRACT,
)

from .helpers import RuntimeResult, assert_semantics, run_javascript


def test_explicit_sequence_constructors_keep_representations():
    assert_semantics(SEQUENCE_CONSTRUCTOR_REPRESENTATION_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("contract", [SEQUENCE_STORAGE_COERCION_CONTRACT, UNION_STORAGE_COERCION_CONTRACT])
def test_sequence_storage_converts_copied_scalars(contract):
    result, generated = run_javascript(contract.print_source)
    assert result == RuntimeResult(0, "0\n", ""), generated
