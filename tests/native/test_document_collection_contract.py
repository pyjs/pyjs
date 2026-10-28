from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import DOCUMENT_COLLECTION_CONTRACT


def test_shared_document_collection_contract():
    result = LLVM().assert_matches_python(DOCUMENT_COLLECTION_CONTRACT.source)
    assert result.native.returncode == 0, DOCUMENT_COLLECTION_CONTRACT.failure(result.native.returncode)
