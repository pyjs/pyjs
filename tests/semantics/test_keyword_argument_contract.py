from tests.backend_semantics import KEYWORD_ARGUMENT_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_keyword_argument_contract():
    assert_semantics(KEYWORD_ARGUMENT_CONTRACT.print_source + "\nmain()\n")
