from tests.backend_semantics import LIST_EXTEND_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_list_extend_contract():
    assert_semantics(LIST_EXTEND_CONTRACT.print_source + "\nmain()")
