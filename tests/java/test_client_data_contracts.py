import pytest

from tests.backend_semantics import (
    AWAIT_ATTRIBUTE_SOURCE,
    DICTIONARY_POP_CONTRACT,
    EXPLICIT_SPLIT_CONTRACT,
    LIST_TRUTH_CONTRACT,
)
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT, DICTIONARY_POP_CONTRACT], ids=["truth", "split", "pop"])
def test_client_data_contract(contract, tmp_path):
    assert_matches_python(contract.source, tmp_path)


def test_awaited_values_preserve_instance_attributes(tmp_path):
    assert_text_matches_python(AWAIT_ATTRIBUTE_SOURCE + '''
from pyjs.java import run_sync
def main() -> str:
    return run_sync(await_attributes())
''', tmp_path)
