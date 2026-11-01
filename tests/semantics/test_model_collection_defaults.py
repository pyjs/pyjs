from tests.backend_semantics import MODEL_COLLECTION_DEFAULTS_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_collection_defaults_contract():
    assert_semantics(MODEL_COLLECTION_DEFAULTS_CONTRACT.print_source + "\nmain()")
