import pytest

from tests.backend_semantics import EXPLICIT_SPLIT_CONTRACT, LIST_TRUTH_CONTRACT
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT], ids=["truth", "split"])
def test_client_data_contract(contract):
    assert_semantics(contract.print_source + "\nmain()\n")
