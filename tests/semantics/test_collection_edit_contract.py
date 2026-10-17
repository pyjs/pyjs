from tests.backend_semantics import COLLECTION_EDIT_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_collection_edit_contract():
    assert_semantics(COLLECTION_EDIT_CONTRACT.print_source + "\nmain()")
