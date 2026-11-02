import pytest

from pyjs.analysis.diagnostics import CompilationError, DiagnosticCode
from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from tests.backend_semantics import (
    CALL_GUARD_NARROWING_CONTRACT,
    INITIALIZED_GUARD_CONTRACT,
    INITIALIZED_ITERABLE_CONTRACT,
    INITIALIZED_TRUTH_GUARD_CONTRACT,
)


@pytest.mark.parametrize("contract, boundary", [
    (INITIALIZED_GUARD_CONTRACT,
     "WebAssembly call target isinstance is not implemented at line 3"),
    (INITIALIZED_TRUTH_GUARD_CONTRACT,
     "WebAssembly call target __dynamic_bool__ is not implemented"),
    (INITIALIZED_ITERABLE_CONTRACT,
     "WebAssembly union value storage is not implemented"),
])
def test_initialized_guard_contract_reaches_the_wasm_boundary(contract, boundary):
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly(contract.source)
    assert str(caught.value) == boundary


def test_call_guard_contract_reaches_the_existing_exception_boundary():
    with pytest.raises(CompilationError) as caught:
        transpile_webassembly(CALL_GUARD_NARROWING_CONTRACT.source)
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == DiagnosticCode.UNSUPPORTED_SYNTAX
    assert diagnostic.message == "native IR exception handlers are not implemented"
    assert diagnostic.help == (
        "Move exception handling outside this backend until it implements shared IR exception regions.",
    )
