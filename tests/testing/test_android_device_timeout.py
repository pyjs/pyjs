from pathlib import Path

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


def test_device_timeout_reports_the_running_test_stops_it_and_allows_retry(request, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_wait.py").write_text('''\
from pyjs import jvm


@jvm.native("java/lang/Thread", name="sleep")
def sleep(milliseconds: int) -> None: ...


def test_ready() -> None:
    assert 6 * 7 == 42


def test_slow() -> None:
    sleep(60_000)
''')
    sdk = AndroidSDK()
    device = sdk.ensure_emulator(request.config.getoption("--pyjs-android-avd"),
                                 headless=request.config.getoption("--pyjs-android-headless"))
    runtime = AndroidRuntimeResolver(Path.home() / ".cache/pyjs/android-test").resolve_device()
    builder = AndroidJVMSuiteBuilder(project, tmp_path / "cache")
    packager = AndroidDeviceTestBuilder(sdk, sdk.platform_jar(35), runtime, 35)
    runner = AndroidDeviceTestRunner(sdk, device)
    suites = {}
    for name in ["ready", "slow"]:
        nodeid = f"test_wait.py::test_{name}"
        compilation = builder.build(
            [SelectedTest(nodeid, "test_wait", f"test_{name}")], name, robolectric=False)
        suites[name] = compilation, packager.build(compilation, tmp_path / name)

    assert runner.run(*suites["ready"], timeout=30) == {
        "test_wait.py::test_ready": AndroidTestResult("passed")}
    results = runner.run(*suites["slow"], timeout=15)
    result = results["test_wait.py::test_slow"]
    assert result.outcome == "failed"
    assert "timed out after 15 seconds" in result.error
    assert "Last started: test_wait.py::test_slow" in result.error
    for package in [TARGET_PACKAGE, TEST_PACKAGE]:
        process = sdk.runner.run(
            [sdk.adb, "-s", device.identifier, "shell", "pidof", package],
            environment=sdk.environment(), capture_output=True, check=False, timeout=5)
        assert process.returncode == 1 and not process.stdout.strip(), process
    assert runner.run(*suites["ready"], timeout=30) == {
        "test_wait.py::test_ready": AndroidTestResult("passed")}
