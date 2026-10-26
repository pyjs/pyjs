import pytest

from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from tests.backend_semantics import LIST_REVERSE_CONTRACT


def test_list_reverse_contract_keeps_explicit_wasm_boundary():
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly(LIST_REVERSE_CONTRACT.source)
    assert str(caught.value) == "WebAssembly value type NoneType is not implemented"
