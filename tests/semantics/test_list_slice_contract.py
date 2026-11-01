from tests.backend_semantics import LIST_SLICE_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_list_slice_contract():
    assert_semantics(LIST_SLICE_CONTRACT.print_source + "\nmain()")
