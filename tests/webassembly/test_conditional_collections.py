import pytest

from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from tests.backend_semantics import (
    CONDITIONAL_EMPTY_COLLECTIONS,
    CONDITIONAL_EMPTY_MAPPING,
)
from tests.webassembly.test_transpiler import execute


def test_shared_conditional_empty_collections(tmp_path):
    result = int(execute(tmp_path, CONDITIONAL_EMPTY_COLLECTIONS.source))
    assert result == 0, CONDITIONAL_EMPTY_COLLECTIONS.failure(result)


def test_mapping_retains_the_existing_backend_boundary():
    with pytest.raises(WebAssemblyUnsupported, match="value type dict__str_int is not implemented"):
        transpile_webassembly(CONDITIONAL_EMPTY_MAPPING.source)
