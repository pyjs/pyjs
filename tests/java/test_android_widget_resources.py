import pytest

from pyjs.android.testing import by_text, launch

from .android_widget_app import WidgetPreviewActivity

pytestmark = pytest.mark.pyjs_android_jvm


def test_resource_lookup_and_remote_views_render_native_text() -> None:
    launch(WidgetPreviewActivity)
    by_text("Widget preview 😀").assert_displayed()
