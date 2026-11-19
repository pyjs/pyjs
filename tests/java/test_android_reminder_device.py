import time
from pathlib import Path

import pytest

from pyjs.testing.android import AndroidTestSession
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_jvm import (
    AndroidJVMApplication,
    AndroidJVMBuilder,
    AndroidManifestComponent,
)

pytestmark = pytest.mark.pyjs_android


def test_reminder_permission_and_delivery_after_process_exit(request, pyjs_artifacts_dir):
    sdk = AndroidSDK()
    app = AndroidJVMApplication(
        Path(__file__).with_name("android_reminder_app.py"), "tests.java.android_reminder_app",
        "org.pyjs.reminder.acceptance", "ReminderActivity", "Reminder acceptance", compile_sdk=35,
        min_sdk=33, permissions=("android.permission.POST_NOTIFICATIONS",
                                "android.permission.SCHEDULE_EXACT_ALARM"),
        components=(AndroidManifestComponent("receiver", "ReminderReceiver"),),
    )
    artifacts = pyjs_artifacts_dir / "android" / "reminder"
    package = AndroidJVMBuilder(sdk).build(app, artifacts / "app")
    device = sdk.ensure_emulator(request.config.getoption("--pyjs-android-avd"),
                                headless=request.config.getoption("--pyjs-android-headless"))
    sdk.install(device, package)
    session = AndroidTestSession(sdk, device, app.app_id, activity=app.android_activity)
    try:
        with session.artifacts_on_failure(artifacts, "reminder"):
            session.adb("shell", "pm", "clear", app.app_id)
            session.adb("shell", "appops", "set", app.app_id, "SCHEDULE_EXACT_ALARM", "deny")
            session.launch()
            session.wait_for_element(text="Notifications disabled")
            session.tap_element(text="ENABLE NOTIFICATIONS")
            session.tap_element(test_id="permission_deny_button")
            session.wait_for_element(text="Permission denied")
            session.tap_element(text="ENABLE NOTIFICATIONS")
            session.tap_element(test_id="permission_allow_button")
            session.wait_for_element(text="Permission granted")
            session.tap_element(text="SCHEDULE REMINDER")
            session.wait_for_element(text="Exact alarms unavailable")
            session.adb("shell", "appops", "set", app.app_id, "SCHEDULE_EXACT_ALARM", "allow")
            session.tap_element(text="SCHEDULE REMINDER")
            # Force-stop cancels alarms. Kill only the now-background process.
            deadline = time.monotonic() + 10
            while session.is_running() and time.monotonic() < deadline:
                session.adb("shell", "am", "kill", app.app_id)
                time.sleep(0.2)
            assert not session.is_running(), "Reminder must survive a genuine process exit"
            session.adb("shell", "cmd", "statusbar", "expand-notifications")
            session.wait_for_element(text="Scheduled reminder arrived", timeout=40, require_running=False)
            session.tap_element(text="Scheduled reminder arrived")
            session.wait_for_element(text="Reminder opened from notification")
            session.adb("shell", "pm", "revoke", app.app_id, "android.permission.POST_NOTIFICATIONS")
            session.launch()
            session.wait_for_element(text="Notifications disabled")
            assert session.log_errors() == ""
    finally:
        session.adb("shell", "cmd", "statusbar", "collapse")
        session.force_stop()
        session.adb("uninstall", app.app_id)
