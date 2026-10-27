from tests.backend_semantics import DOCUMENT_COLLECTION_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_document_collection_contract():
    assert_semantics(DOCUMENT_COLLECTION_CONTRACT.print_source + "\nmain()")
