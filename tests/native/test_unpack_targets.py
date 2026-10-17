import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import UNPACK_FIELD_CONTRACT, UNPACK_TARGET_SOURCE


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", [UNPACK_TARGET_SOURCE, UNPACK_FIELD_CONTRACT.source],
                         ids=["failures", "shared-fields"])
def test_nested_attribute_unpacking_keeps_native_order(optimize, source):
    result = LLVM().assert_matches_python(source, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert not result.native.stderr
