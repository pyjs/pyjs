import pytest

from pyjs import js
from tests.reorderable_cases import assert_hierarchical_reorder_scenarios

pytestmark = pytest.mark.pyjs_web


@js
def test_hierarchical_reorder_scenarios_in_the_browser():
    assert_hierarchical_reorder_scenarios()
