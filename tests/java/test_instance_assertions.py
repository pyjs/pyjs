from tests.backend_semantics import ASSERT_INSTANCE_STATE_CONTRACT
from tests.java.test_exceptions import assert_matches_python


def test_shared_instance_assertion_contract(tmp_path):
    assert_matches_python(ASSERT_INSTANCE_STATE_CONTRACT.source, tmp_path)
