import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import STRING_ZFILL_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_zfill_contract(optimize):
    result = LLVM().assert_matches_python(STRING_ZFILL_CONTRACT.source,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
