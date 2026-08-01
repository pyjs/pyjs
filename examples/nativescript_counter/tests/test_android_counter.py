from pathlib import Path

import pytest
from pyjs.testing.android import AndroidTestSession
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.nativescript import NativeScriptProject
from pyjs_examples.nativescript_counter.counter import main

pytestmark = pytest.mark.pyjs_android


def test_counter_runs_on_android(request, pyjs_artifacts_dir: Path):
    android = AndroidSDK()
    project = NativeScriptProject(
        main,
        name="PyJS Counter",
        app_id="org.pyjs.counter",
        android=android,
    )
    device = project.run_android(request.config.getoption("--pyjs-android-avd"))
    session = AndroidTestSession(android, device, project.app_id)
    artifacts = pyjs_artifacts_dir / "android"

    with session.artifacts_on_failure(artifacts, "nativescript-counter"):
        session.launch()
        session.wait_for_element(test_id="counter-value", text="0")
        session.tap_element(test_id="increment-button")
        session.wait_for_element(test_id="counter-value", text="1")
        assert session.log_errors() == ""

    session.capture_artifacts(artifacts, "nativescript-counter")
