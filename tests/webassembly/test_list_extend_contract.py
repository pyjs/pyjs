import pytest

from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly


def test_list_extend_keeps_explicit_wasm_boundary():
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly('''def main() -> int:
    values = [1]
    values.extend([2])
    return len(values)
''')
    assert str(caught.value) == "WebAssembly call target extend is not implemented at line 3"
