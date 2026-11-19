import pytest

from pyjs.android.testing import by_id, by_text, launch, press_back

from .android_result_app import ResultParentActivity

pytestmark = [pytest.mark.pyjs_android_jvm, pytest.mark.pyjs_android_device]


def test_activity_result_delivers_selection_and_default_cancellation() -> None:
    launch(ResultParentActivity)
    by_text("Choose").click()
    by_text("Accept selection").click()
    by_id(1001).assert_text("Chosen 日本語 😀")
    by_text("Choose").click()
    by_text("Cancel selection").click()
    by_id(1001).assert_text("Selection cancelled")
    by_text("Choose").click()
    by_text("Accept selection").click()
    by_id(1001).assert_text("Chosen 日本語 😀")
    by_text("Choose").click()
    by_text("Cancel selection").assert_displayed()
    press_back()
    by_id(1001).assert_text("Selection cancelled")
