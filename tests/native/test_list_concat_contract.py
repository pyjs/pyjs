import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import LIST_CONCAT_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_list_concatenation_contract(tmp_path, optimize):
    result = LLVM().assert_matches_python(
        LIST_CONCAT_CONTRACT.source, directory=tmp_path, optimize=optimize)
    assert result.native.returncode == 0, LIST_CONCAT_CONTRACT.failure(result.native.returncode)
