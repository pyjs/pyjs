from tests.backend_semantics import NUMERIC_SHORT_CIRCUIT_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_numeric_short_circuit_contract():
    assert_semantics(NUMERIC_SHORT_CIRCUIT_CONTRACT.print_source + "\nmain()")
