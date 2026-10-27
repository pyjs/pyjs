from tests.backend_semantics import POSITIONAL_MINMAX_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_positional_minmax_contract():
    assert_semantics(POSITIONAL_MINMAX_CONTRACT.print_source + "\nmain()")
