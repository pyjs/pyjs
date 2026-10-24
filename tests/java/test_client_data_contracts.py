import pytest

from tests.backend_semantics import EXPLICIT_SPLIT_CONTRACT, LIST_TRUTH_CONTRACT
from tests.java.test_exceptions import assert_matches_python


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT], ids=["truth", "split"])
def test_client_data_contract(contract, tmp_path):
    assert_matches_python(contract.source, tmp_path)
