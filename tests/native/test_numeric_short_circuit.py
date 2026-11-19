import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import NUMERIC_SHORT_CIRCUIT_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_numeric_short_circuit_contract(optimize):
    result = LLVM().assert_matches_python(NUMERIC_SHORT_CIRCUIT_CONTRACT.source,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
