from tests.backend_semantics import ASSERT_INSTANCE_STATE_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_shared_instance_assertion_contract():
    assert_semantics(ASSERT_INSTANCE_STATE_CONTRACT.print_source + "\nmain()")
