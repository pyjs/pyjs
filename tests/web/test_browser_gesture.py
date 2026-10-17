import pytest

from pyjs import js
from tests.gesture_cases import assert_gesture_scenarios

pytestmark = pytest.mark.pyjs_web


@js
def test_gesture_scripts_run_in_the_browser():
    assert_gesture_scenarios()
