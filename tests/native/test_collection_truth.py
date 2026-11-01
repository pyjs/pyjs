import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import LIST_BOOL_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_list_bool_contract(tmp_path, optimize):
    LLVM().assert_matches_python(LIST_BOOL_CONTRACT.source, directory=tmp_path,
                                 optimize=optimize, sanitizers=("address", "undefined"))
