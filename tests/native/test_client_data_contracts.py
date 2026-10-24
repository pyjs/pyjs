import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    AWAIT_ATTRIBUTE_SOURCE,
    EXPLICIT_SPLIT_CONTRACT,
    LIST_TRUTH_CONTRACT,
)


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT], ids=["truth", "split"])
def test_client_data_contract(contract, tmp_path):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)


def test_awaited_values_preserve_instance_attributes(tmp_path):
    result = LLVM().assert_matches_python(AWAIT_ATTRIBUTE_SOURCE + '''
def main() -> str:
    cursor = await_attributes().__await__()
    try:
        next(cursor)
    except StopIteration as error:
        return str(error.value)
    return "unexpected suspension"
''', directory=tmp_path)
    assert result.native.stdout == "readyready!ready?:-128:4"
