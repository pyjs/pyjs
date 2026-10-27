import pytest

from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly


def test_list_reverse_contract_keeps_explicit_wasm_boundary():
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly('''def main() -> int:
    values = [1, 2, 3]
    values.reverse()
    return values[0]
''')
    assert str(caught.value) == "WebAssembly call target reverse is not implemented at line 3"
