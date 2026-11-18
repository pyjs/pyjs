import pytest

from pyjs.android.testing import background, by_id, launch, recreate, resume

from .android_input_app import TapActivity

pytestmark = pytest.mark.pyjs_android_jvm


def test_first_tap_after_resume_reaches_the_activity_exactly_once() -> None:
    launch(TapActivity)
    for count in range(1, 4):
        background()
        resume()
        by_id(1001).click()
        by_id(1001).assert_text(str(count))


def test_first_tap_after_recreation_and_resume_reaches_the_new_activity() -> None:
    launch(TapActivity)
    recreate()
    recreate()
    background()
    resume()
    by_id(1001).click()
    by_id(1001).assert_text("1")
