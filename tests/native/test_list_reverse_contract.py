import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import LIST_REVERSE_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_list_reverse_contract(optimize):
    result = LLVM().assert_matches_python(LIST_REVERSE_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, LIST_REVERSE_CONTRACT.failure(result.native.returncode)
