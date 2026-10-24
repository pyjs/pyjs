import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import EXPLICIT_SPLIT_CONTRACT, LIST_TRUTH_CONTRACT


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT], ids=["truth", "split"])
def test_client_data_contract(contract, tmp_path):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
