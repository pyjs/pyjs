import pytest

from pyjs.android.testing import by_text, launch

from .android_context_app import ContextLauncher

pytestmark = [pytest.mark.pyjs_android_jvm, pytest.mark.pyjs_android_device]


def test_application_context_starts_an_explicit_activity_with_extras() -> None:
    launch(ContextLauncher)
    by_text("Open through application context").click()
    by_text("Opened from context 日本語").assert_displayed()
