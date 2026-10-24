import pytest

from tests.backend_semantics import (
    SCALAR_MAPPING_VALUES_CONTRACT,
    TEXT_SERIALIZATION_CONTRACT,
)
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("contract", [SCALAR_MAPPING_VALUES_CONTRACT, TEXT_SERIALIZATION_CONTRACT],
                         ids=["scalar-values", "text"])
def test_shared_serialization_primitives(contract):
    assert_semantics(contract.print_source + "\nmain()")
