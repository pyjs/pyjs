import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    PROPERTY_CAPTURE_CONTRACT,
    PROPERTY_INSTANCE_CAPTURE_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [PROPERTY_CAPTURE_CONTRACT, PROPERTY_INSTANCE_CAPTURE_CONTRACT])
def test_captured_property_results_match_python(tmp_path, optimize, contract):
    result = LLVM().assert_matches_python(
        contract.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0
    assert not result.native.stderr
