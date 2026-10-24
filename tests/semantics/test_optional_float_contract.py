from tests.backend_semantics import OPTIONAL_FLOAT_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_optional_float_contract():
    assert_semantics(OPTIONAL_FLOAT_CONTRACT.print_source + "\nmain()\n")
