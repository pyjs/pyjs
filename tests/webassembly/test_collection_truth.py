import pytest

from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from tests.backend_semantics import LIST_BOOL_CONTRACT


def test_list_bool_contract_retains_the_string_item_boundary():
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly(LIST_BOOL_CONTRACT.source)
    assert str(caught.value) == "WebAssembly value type str is not implemented"


def test_numeric_list_bool_has_an_explicit_call_boundary():
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly("def main() -> int:\n    values = [0]\n    return 1 if bool(values) else 0\n")
    assert str(caught.value) == "WebAssembly call target bool is not implemented at line 3"
