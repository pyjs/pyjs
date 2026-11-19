from pathlib import Path
from uuid import uuid4

import pytest

from pyjs.testing.android_device import (
    TARGET_PACKAGE,
    TEST_PACKAGE,
    AndroidDeviceTestBuilder,
    AndroidDeviceTestRunner,
)
from pyjs.testing.android_jvm import AndroidJVMSuiteBuilder
from pyjs.testing.android_runtime import AndroidRuntimeResolver, AndroidTestResult
from pyjs.testing.builder import SelectedTest
from pyjs.tooling.android import AndroidSDK

pytestmark = pytest.mark.pyjs_android


def test_device_batches_reuse_one_package_and_continue_after_timeout(request, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    preferences = "batch-" + uuid4().hex
    (project / "test_wait.py").write_text(f'''\
from pyjs import jvm
from pyjs.android.testing import application_context


@jvm.native("java/lang/Thread", name="sleep")
def sleep(milliseconds: int) -> None: ...


def test_ready() -> None:
    preferences = application_context().get_shared_preferences("{preferences}", 0)
    assert preferences.get_string("stage", "") == ""
    assert preferences.edit().put_string("stage", "ready").commit()


def test_slow() -> None:
    preferences = application_context().get_shared_preferences("{preferences}", 0)
    assert preferences.get_string("stage", "") == "ready"
    assert preferences.edit().put_string("stage", "waiting").commit()
    sleep(60_000)


def test_after_timeout() -> None:
    preferences = application_context().get_shared_preferences("{preferences}", 0)
    assert preferences.get_string("stage", "") == "waiting"
    assert preferences.edit().put_string("stage", "done").commit()
''')
    sdk = AndroidSDK()
    device = sdk.ensure_emulator(request.config.getoption("--pyjs-android-avd"),
                                 headless=request.config.getoption("--pyjs-android-headless"))
    runtime = AndroidRuntimeResolver(Path.home() / ".cache/pyjs/android-test").resolve_device()
    builder = AndroidJVMSuiteBuilder(project, tmp_path / "cache")
    packager = AndroidDeviceTestBuilder(sdk, sdk.platform_jar(35), runtime, 35)
    runner = AndroidDeviceTestRunner(sdk, device)
    selected = [SelectedTest(f"test_wait.py::test_{name}", "test_wait", f"test_{name}")
                for name in ["ready", "slow", "after_timeout"]]
    compilation = builder.build(selected, "batches", robolectric=False)
    packages = packager.build(compilation, tmp_path / "package")
    progress = []
    results = runner.run(compilation, packages, timeout=15, batch_size=1, progress=progress.append)
    assert len(progress) == 3
    assert results["test_wait.py::test_ready"] == AndroidTestResult("passed")
    assert results["test_wait.py::test_after_timeout"] == AndroidTestResult("passed")
    result = results["test_wait.py::test_slow"]
    assert result.outcome == "failed"
    assert "timed out after 15 seconds" in result.error
    assert "Last started: test_wait.py::test_slow" in result.error
    for package in [TARGET_PACKAGE, TEST_PACKAGE]:
        process = sdk.runner.run(
            [sdk.adb, "-s", device.identifier, "shell", "pidof", package],
            environment=sdk.environment(), capture_output=True, check=False, timeout=5)
        assert process.returncode == 1 and not process.stdout.strip(), process
