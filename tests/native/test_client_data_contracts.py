import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    AWAIT_ATTRIBUTE_SOURCE,
    DICTIONARY_POP_CONTRACT,
    EXPLICIT_SPLIT_CONTRACT,
    LIST_TRUTH_CONTRACT,
    NARROWED_METHOD_CONTRACT,
    REPLACED_ATTRIBUTE_CONTRACT,
)


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT, DICTIONARY_POP_CONTRACT], ids=["truth", "split", "pop"])
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


def test_narrowed_receivers_and_arguments_keep_their_refined_type(tmp_path):
    result = LLVM().assert_matches_python(NARROWED_METHOD_CONTRACT.source, directory=tmp_path)
    assert result.native.returncode == 0


def test_replaced_attributes_do_not_keep_stale_refinements(tmp_path):
    result = LLVM().assert_matches_python(REPLACED_ATTRIBUTE_CONTRACT.source, directory=tmp_path)
    assert result.native.returncode == 0
