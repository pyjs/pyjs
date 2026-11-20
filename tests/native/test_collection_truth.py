import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import DICT_BOOL_CONTRACT, LIST_BOOL_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [LIST_BOOL_CONTRACT, DICT_BOOL_CONTRACT], ids=["list", "dict"])
def test_shared_collection_bool_contract(tmp_path, optimize, contract):
    LLVM().assert_matches_python(contract.source, directory=tmp_path,
                                 optimize=optimize, sanitizers=("address", "undefined"))
