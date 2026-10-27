import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    CONDITIONAL_EMPTY_COLLECTIONS,
    CONDITIONAL_EMPTY_MAPPING,
)


@pytest.mark.parametrize("contract", [CONDITIONAL_EMPTY_COLLECTIONS, CONDITIONAL_EMPTY_MAPPING])
def test_shared_conditional_empty_collections(contract):
    result = LLVM().assert_matches_python(contract.source)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
