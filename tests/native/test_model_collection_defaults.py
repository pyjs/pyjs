import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm_module
from tests.backend_semantics import MODEL_COLLECTION_DEFAULTS_CONTRACT


def test_model_construction_keeps_host_only_native_boundary():
    with pytest.raises(CompilationError) as caught:
        transpile_llvm_module(MODEL_COLLECTION_DEFAULTS_CONTRACT.source)
    assert caught.value.diagnostic.code == "PYJS2001"
    assert caught.value.diagnostic.message == (
        "construct and validate Pydantic models in Python before calling native code"
    )
