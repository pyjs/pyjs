from pathlib import Path

import pytest

from pyjs.android.dependencies import resolve_androidx_runtime
from pyjs.testing.android import AndroidTestSession
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_jvm import AndroidJVMApplication, AndroidJVMBuilder

pytestmark = pytest.mark.pyjs_android


def test_file_share_crosses_app_boundary_without_exposing_other_files(request, pyjs_artifacts_dir):
    sdk = AndroidSDK()
    directory = Path(__file__).parent
    artifacts = pyjs_artifacts_dir / "android" / "file-share"
    dependencies = resolve_androidx_runtime(Path.home() / ".cache" / "pyjs" / "android-runtime")
    sender = AndroidJVMApplication(
        directory / "android_file_share_app.py", "tests.java.android_file_share_app",
        "org.pyjs.share.sender", "SendActivity", "File sender", compile_sdk=35,
        resources=(directory / "file_share_resources",),
        manifest_overlays=(directory / "file_share_manifest.xml",),
    )
    receiver = AndroidJVMApplication(
        sender.source, sender.module_name, "org.pyjs.share.receiver", "ReceiveActivity",
        "File receiver", compile_sdk=35,
    )
    packages = [(app, AndroidJVMBuilder(sdk).build(app, artifacts / app.app_id,
                                                 dependencies=dependencies))
                for app in (sender, receiver)]
    device = sdk.ensure_emulator(request.config.getoption("--pyjs-android-avd"),
                                headless=request.config.getoption("--pyjs-android-headless"))
    for _, package in packages:
        sdk.install(device, package)
    send = AndroidTestSession(sdk, device, sender.app_id, activity=sender.android_activity)
    receive = AndroidTestSession(sdk, device, receiver.app_id, activity=receiver.android_activity)
    try:
        with send.artifacts_on_failure(artifacts, "sender"), receive.artifacts_on_failure(artifacts, "receiver"):
            receive.force_stop()
            send.force_stop()
            send.launch()
            send.tap_element(text="SEND WITHOUT GRANT")
            receive.wait_for_element(text="File unavailable without a read grant")
            send.adb("shell", "input", "keyevent", "4")
            send.tap_element(text="SEND WITH GRANT")
            receive.wait_for_element(text="Complete Unicode file received; writes denied")
            receive.force_stop()
            send.tap_element(text="SEND WITHOUT GRANT")
            receive.wait_for_element(text="File unavailable without a read grant")
            assert send.log_errors() == "" and receive.log_errors() == ""
    finally:
        receive.force_stop()
        send.force_stop()
