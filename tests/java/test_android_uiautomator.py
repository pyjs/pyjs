import pytest

from pyjs.android.testing import launch
from pyjs.android.uiautomator import device, find_text

from .android_robolectric_app import GreetingActivity

pytestmark = [
    pytest.mark.pyjs_android_jvm,
    pytest.mark.pyjs_android_device,
]


def test_uiautomator_observes_launched_python_activity() -> None:
    launch(GreetingActivity)

    assert device().current_package() == "org.pyjs.testing.target"
    update = find_text("Update")
    assert update.text() == "Update"
    update.drag_to(find_text("Hello from Python"), 1_000)
    assert find_text("Update").text() == "Update"
