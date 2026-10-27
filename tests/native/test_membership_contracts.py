import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    INTEGER_LIST_MEMBERSHIP_CONTRACT,
    NULLABLE_STRING_LIST_MEMBERSHIP_CONTRACT,
    STRING_DICTIONARY_MEMBERSHIP_CONTRACT,
    STRING_LIST_MEMBERSHIP_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [INTEGER_LIST_MEMBERSHIP_CONTRACT, STRING_DICTIONARY_MEMBERSHIP_CONTRACT, STRING_LIST_MEMBERSHIP_CONTRACT])
def test_shared_membership_contract(tmp_path, optimize, contract):
    result = LLVM().assert_matches_python(
        contract.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0
    assert not result.native.stderr


def test_nullable_string_search_keeps_explicit_representation_boundary():
    with pytest.raises(LLVMUnsupported, match="LLVM list search requires the same item representation"):
        transpile_llvm(NULLABLE_STRING_LIST_MEMBERSHIP_CONTRACT.source)
