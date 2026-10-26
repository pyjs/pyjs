from tests.backend_semantics import LIST_REVERSE_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_list_reverse_contract():
    assert_semantics(LIST_REVERSE_CONTRACT.print_source + "\nmain()")
