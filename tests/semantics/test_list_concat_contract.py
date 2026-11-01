from tests.backend_semantics import LIST_CONCAT_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_list_concatenation_contract():
    assert_semantics(LIST_CONCAT_CONTRACT.print_source + "\nmain()")
