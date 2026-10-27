from tests.backend_semantics import MIXED_TRUTH_CONDITION_CONTRACT
from tests.semantics.helpers import assert_semantics


def test_mixed_truth_conditions():
    assert_semantics(MIXED_TRUTH_CONDITION_CONTRACT.print_source + "\nmain()\n")
