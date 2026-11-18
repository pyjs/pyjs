import re
import time
from pathlib import Path

import pytest

from pyjs.android.dependencies import resolve_androidx_runtime
from pyjs.testing.android import AndroidTestSession
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_jvm import AndroidJVMApplication, AndroidJVMBuilder

pytestmark = pytest.mark.pyjs_android


def wait_keyboard(session, visible):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = session.adb("shell", "dumpsys", "window", "displays").stdout
        values = re.findall(r"\bInsetsSource\b[^\n]*\btype=ime\b[^\n]*\bvisible=(true|false)\b", state)
        if values and all(value == ("true" if visible else "false") for value in values):
            return
        time.sleep(0.1)
    raise AssertionError(f"Keyboard did not become visible={visible}: {values}")


def test_window_insets_control_the_real_keyboard_without_editing_text(request, pyjs_artifacts_dir):
    sdk = AndroidSDK()
    application = AndroidJVMApplication(
        Path(__file__).with_name("android_keyboard_app.py"),
        "tests.java.android_keyboard_app", "org.pyjs.keyboard", "KeyboardActivity", "Keyboard",
        compile_sdk=35,
    )
    directory = pyjs_artifacts_dir / "android" / "keyboard"
    apk = AndroidJVMBuilder(sdk).build(application, directory / "apk",
        dependencies=resolve_androidx_runtime(Path.home() / ".cache" / "pyjs" / "android-runtime"))
    device = sdk.ensure_emulator(request.config.getoption("--pyjs-android-avd"),
                                headless=request.config.getoption("--pyjs-android-headless"))
    sdk.install(device, apk)
    session = AndroidTestSession(sdk, device, application.app_id,
                                activity=application.android_activity)
    previous = session.adb("shell", "settings", "get", "secure", "show_ime_with_hard_keyboard").stdout.strip()
    try:
        session.adb("shell", "settings", "put", "secure", "show_ime_with_hard_keyboard", "1")
        with session.artifacts_on_failure(directory, "keyboard"):
            session.launch()
            session.wait_for_element(description="Editor", text="Typed text")
            for index in range(2):
                session.tap_element(description="Show keyboard")
                wait_keyboard(session, True)
                session.tap_element(description="Inspect keyboard")
                session.wait_for_element(description="Keyboard visibility", text="Visible")
                session.wait_for_element(description="Editor", text="Typed text", focused=True)
                session.screenshot(directory / f"visible-{index}.png")
                session.tap_element(description="Hide keyboard")
                wait_keyboard(session, False)
                session.tap_element(description="Inspect keyboard")
                session.wait_for_element(description="Keyboard visibility", text="Hidden")
                session.wait_for_element(description="Editor", text="Typed text", focused=True)
                session.screenshot(directory / f"hidden-{index}.png")
            assert session.log_errors() == ""
    finally:
        try:
            session.force_stop()
        finally:
            if previous == "null":
                session.adb("shell", "settings", "delete", "secure", "show_ime_with_hard_keyboard")
            else:
                session.adb("shell", "settings", "put", "secure", "show_ime_with_hard_keyboard", previous)
