import pytest

from tests.backend_semantics import (
    PROPERTY_CAPTURE_CONTRACT,
    PROPERTY_INSTANCE_CAPTURE_CONTRACT,
)

from .helpers import assert_semantics


@pytest.mark.parametrize("contract", [PROPERTY_CAPTURE_CONTRACT, PROPERTY_INSTANCE_CAPTURE_CONTRACT])
def test_captured_property_results_match_python(contract):
    assert_semantics(contract.print_source + "\nmain()\n")
