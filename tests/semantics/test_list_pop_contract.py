from tests.backend_semantics import LIST_POP_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_list_pop_contract():
    assert_semantics(LIST_POP_CONTRACT.print_source + "\nmain()")
