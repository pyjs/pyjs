from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import POSITIONAL_MINMAX_CONTRACT


def test_shared_positional_minmax_contract():
    result = LLVM().assert_matches_python(POSITIONAL_MINMAX_CONTRACT.source)
    assert result.native.returncode == 0
