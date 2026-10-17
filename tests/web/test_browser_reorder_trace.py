import pytest

from pyjs import js
from tests.reorderable_trace_cases import assert_reorder_trace_scenarios

pytestmark = pytest.mark.pyjs_web


@js
def test_reorder_trace_records_and_replays_in_the_browser():
    assert_reorder_trace_scenarios()
