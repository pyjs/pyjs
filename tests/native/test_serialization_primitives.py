import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    SCALAR_MAPPING_VALUES_CONTRACT,
    TEXT_SERIALIZATION_CONTRACT,
)


@pytest.mark.parametrize("contract", [SCALAR_MAPPING_VALUES_CONTRACT, TEXT_SERIALIZATION_CONTRACT],
                         ids=["scalar-values", "text"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_serialization_primitives(contract, optimize):
    result = LLVM().assert_matches_python(contract.source, optimize=optimize)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
