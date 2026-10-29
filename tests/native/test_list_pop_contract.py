import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import LIST_POP_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_list_pop_contract(optimize):
    result = LLVM().assert_matches_python(LIST_POP_CONTRACT.source, optimize=optimize)
    assert result.native.returncode == 0, LIST_POP_CONTRACT.failure(result.native.returncode)
