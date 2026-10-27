import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import MIXED_TRUTH_CONDITION_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_truth_conditions(optimize):
    contract = MIXED_TRUTH_CONDITION_CONTRACT
    result = LLVM().assert_matches_python(contract.source, optimize=optimize)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
