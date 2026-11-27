import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
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


@pytest.mark.parametrize("body", [
    "if isinstance(error.value, str):\n            return error.value.upper()",
    "assert isinstance(error.value, str)\n        return error.value.upper()",
])
def test_builtin_property_reads_also_require_capture_before_narrowing(body):
    with pytest.raises(CompilationError, match="Attribute 'upper' is not defined"):
        transpile_llvm(f'''
def main() -> str:
    try:
        raise StopIteration("ready")
    except StopIteration as error:
        {body}
    return ""
''')
