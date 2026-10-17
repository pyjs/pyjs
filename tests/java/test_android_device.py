import time
from pathlib import Path

import pytest
from pyjs_examples.calculator.android_build import application as calculator_application

from pyjs.testing.android import AndroidTestSession
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_jvm import AndroidJVMApplication, AndroidJVMBuilder

pytestmark = pytest.mark.pyjs_android

ANDROID_FAILURE = Path(__file__).with_name("android_failure.py")


def test_calculator_runs_on_android(
    request,
    pyjs_artifacts_dir: Path,
):
    sdk = AndroidSDK()
    application = calculator_application()
    package = AndroidJVMBuilder(sdk).build(
        application,
        pyjs_artifacts_dir / "android" / "packages",
    )
    device = sdk.ensure_emulator(
        request.config.getoption("--pyjs-android-avd"),
        headless=request.config.getoption("--pyjs-android-headless"),
    )
    sdk.install(device, package)
    session = AndroidTestSession(
        sdk,
        device,
        application.app_id,
        activity=application.android_activity,
    )
    artifacts = pyjs_artifacts_dir / "android"

    with session.artifacts_on_failure(artifacts, "android-calculator"):
        session.launch()
        session.wait_for_element(text="PyJS Calculator")
        session.tap_element(text="7")
        session.tap_element(text="+")
        session.tap_element(text="8")
        session.tap_element(text="=")
        session.wait_for_element(text="15.0")
        assert session.log_errors() == ""

    session.capture_artifacts(artifacts, "android-calculator")


def test_android_logcat_preserves_python_failure_lines(
    request,
    pyjs_artifacts_dir: Path,
):
    sdk = AndroidSDK()
    application = AndroidJVMApplication(
        ANDROID_FAILURE,
        "tests.java.android_failure",
        "org.pyjs.failure",
        "FailureActivity",
        "PyJS Failure",
        35,
    )
    package = AndroidJVMBuilder(sdk).build(
        application,
        pyjs_artifacts_dir / "android" / "packages",
    )
    device = sdk.ensure_emulator(
        request.config.getoption("--pyjs-android-avd"),
        headless=request.config.getoption("--pyjs-android-headless"),
    )
    sdk.install(device, package)
    session = AndroidTestSession(
        sdk,
        device,
        application.app_id,
        activity=application.android_activity,
    )
    artifacts = pyjs_artifacts_dir / "android"

    with session.artifacts_on_failure(artifacts, "android-failure-lines"):
        session.launch()
        # The platform's default Button style exposes all-caps text through
        # UIAutomator even though setText() receives mixed case.
        session.tap_element(text="FAIL WITH PYTHON LINE")
        deadline = time.monotonic() + 10
        while session.is_running() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not session.is_running()
        errors = session.log_errors(10_000)
        failure_line = next(
            index
            for index, line in enumerate(ANDROID_FAILURE.read_text().splitlines(), 1)
            if "value = 1 // 0" in line
        )
        assert "java.lang.ArithmeticException" in errors
        assert f"android_failure.py:{failure_line}" in errors

    session.capture_artifacts(artifacts, "android-failure-lines")
