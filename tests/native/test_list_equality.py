import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import SCALAR_LIST_EQUALITY_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_scalar_list_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python(
        SCALAR_LIST_EQUALITY_CONTRACT.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0
    assert not result.native.stderr
