import pytest

from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from tests.backend_semantics import (
    INITIALIZED_GUARD_CONTRACT,
    INITIALIZED_ITERABLE_CONTRACT,
    INITIALIZED_TRUTH_GUARD_CONTRACT,
)


@pytest.mark.parametrize("contract", [INITIALIZED_GUARD_CONTRACT, INITIALIZED_TRUTH_GUARD_CONTRACT,
                                      INITIALIZED_ITERABLE_CONTRACT])
def test_initialized_guard_contract_reaches_the_existing_union_storage_boundary(contract):
    with pytest.raises(WebAssemblyUnsupported) as caught:
        transpile_webassembly(contract.source)
    assert str(caught.value) == "WebAssembly union value storage is not implemented"
