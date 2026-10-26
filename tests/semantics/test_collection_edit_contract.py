import pytest

from tests.backend_semantics import (
    COLLECTION_EDIT_CONTRACT,
    CONDITIONAL_EMPTY_COLLECTIONS,
    CONDITIONAL_EMPTY_MAPPING,
    LIST_COPY_CONTRACT,
)
from tests.semantics.helpers import assert_semantics


def test_shared_collection_edit_contract():
    assert_semantics(COLLECTION_EDIT_CONTRACT.print_source + "\nmain()")


def test_shared_list_copy_contract():
    assert_semantics(LIST_COPY_CONTRACT.print_source + "\nmain()")


@pytest.mark.parametrize("contract", [CONDITIONAL_EMPTY_COLLECTIONS, CONDITIONAL_EMPTY_MAPPING])
def test_shared_conditional_empty_collections(contract):
    assert_semantics(contract.print_source + "\nmain()")
