import pytest

from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from tests.backend_semantics import PROPERTY_CAPTURE_CONTRACT


def test_property_capture_keeps_existing_inheritance_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="^WebAssembly class inheritance is not implemented$"):
        transpile_webassembly(PROPERTY_CAPTURE_CONTRACT.source)
