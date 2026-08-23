from pathlib import Path

import pytest
from pyjs.testing.android import AndroidTestSession
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.nativescript import NativeScriptProject
from pyjs_examples.calculator.android import android_main

pytestmark = pytest.mark.pyjs_android


def test_calculator_runs_on_android(request, pyjs_artifacts_dir: Path):
    android = AndroidSDK()
    project = NativeScriptProject(
        android_main,
        name="PyJS Calculator",
        app_id="org.pyjs.calculator",
        android=android,
    )
    device = project.run_android(request.config.getoption("--pyjs-android-avd"))
    session = AndroidTestSession(android, device, project.app_id)
    artifacts = pyjs_artifacts_dir / "android"

    with session.artifacts_on_failure(artifacts, "calculator"):
        session.launch()
        session.wait_for_element(test_id="calculator-display", text="0")
        session.tap_element(test_id="key-1")
        session.tap_element(test_id="key-+")
        session.tap_element(test_id="key-2")
        session.tap_element(test_id="key-=")
        session.wait_for_element(test_id="calculator-display", text="3.0")
        assert session.log_errors() == ""

    session.capture_artifacts(artifacts, "calculator")
