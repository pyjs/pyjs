import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pyjs.java import JVMCompilation, JVMCompiledTest
from pyjs.testing.android_device import (
    RUNNER,
    TARGET_PACKAGE,
    TEST_PACKAGE,
    AndroidDeviceTestBuilder,
    AndroidDeviceTestRunner,
    AndroidTestPackages,
)
from pyjs.testing.android_runtime import AndroidTestResult
from pyjs.tooling.android import AndroidDevice


def instrumentation_status(method, code, *, class_name="Tests$Suite", details=""):
    return (f"INSTRUMENTATION_STATUS: class={class_name}\n"
            f"INSTRUMENTATION_STATUS: test={method}\n{details}"
            f"INSTRUMENTATION_STATUS_CODE: {code}\n")


def make_device_runner(*outcomes):
    command = Mock(side_effect=outcomes)
    sdk = SimpleNamespace(adb=Path("adb"), runner=SimpleNamespace(run=command),
                          install=Mock(), prepare_for_tests=Mock(),
                          environment=lambda: {"ANDROID_HOME": "sdk"})
    runner = AndroidDeviceTestRunner(sdk, AndroidDevice("emulator-5566", "device"))
    return runner, sdk


def device_runner(compilation, outcome, *cleanup, batch_size=None):
    runner, sdk = make_device_runner(outcome, *cleanup)
    results = runner.run(compilation, AndroidTestPackages(Path("app.apk"), Path("tests.apk")),
                         timeout=7, batch_size=batch_size)
    return results, sdk.runner.run


@pytest.fixture
def three_tests():
    return JVMCompilation("Tests", {}, tuple(
        JVMCompiledTest(f"test_notes.py::test_{name}", "Tests$Suite", f"test_{name}")
        for name in ["save", "open", "close"]))


@pytest.mark.parametrize("batch_size", [None, 1, 2, 10])
def test_batches_select_each_method_once_and_install_packages_once(three_tests, batch_size):
    size = batch_size or 3
    batches = [three_tests.tests[index:index + size] for index in range(0, 3, size)]
    responses = [subprocess.CompletedProcess([], 0, "".join(
        instrumentation_status(test.method_name, 0) for test in batch), "") for batch in batches]
    runner, sdk = make_device_runner(*responses)
    progress = []
    packages = AndroidTestPackages(Path("app.apk"), Path("tests.apk"))
    results = runner.run(three_tests, packages, timeout=7, batch_size=batch_size,
                         progress=progress.append)
    assert results == {test.nodeid: AndroidTestResult("passed") for test in three_tests.tests}
    assert [call.args for call in sdk.install.call_args_list] == [
        (runner.device, packages.target), (runner.device, packages.tests)]
    sdk.prepare_for_tests.assert_called_once_with(runner.device)
    assert len(sdk.runner.run.call_args_list) == len(batches)
    for index, (call, batch) in enumerate(zip(sdk.runner.run.call_args_list, batches, strict=True), 1):
        selection = (r"Tests\$Suite" if batch_size is None else
                     ",".join(r"Tests\$Suite#" + test.method_name for test in batch))
        assert call.args[0] == [
            Path("adb"), "-s", "emulator-5566", "shell", "am", "instrument", "-w", "-r",
            "-e", "class", selection,
            f"{TEST_PACKAGE}/{RUNNER}"]
        assert call.kwargs["timeout"] == 7
        assert progress[index - 1] == (
            f"Android device batch {index}/{len(batches)}: {len(batch)} tests, 7s execution limit")


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5])
def test_invalid_batch_size_fails_before_installing(three_tests, batch_size):
    runner, sdk = make_device_runner()
    with pytest.raises(ValueError, match="batch size must be a positive integer"):
        runner.run(three_tests, AndroidTestPackages(Path("app.apk"), Path("tests.apk")),
                   batch_size=batch_size)
    sdk.install.assert_not_called()


def test_empty_device_selection_fails_before_installing():
    runner, sdk = make_device_runner()
    with pytest.raises(ValueError, match="requires selected tests"):
        runner.run(JVMCompilation("Tests", {}),
                   AndroidTestPackages(Path("app.apk"), Path("tests.apk")))
    sdk.install.assert_not_called()


@pytest.mark.parametrize("last_code", [0, 1])
def test_timed_out_batch_retains_results_and_continues_after_stopping_its_processes(three_tests, last_code):
    output = instrumentation_status("test_save", 0) + instrumentation_status("test_open", last_code)
    stopped = subprocess.CompletedProcess([], 0, "", "")
    results, command = device_runner(
        three_tests, subprocess.TimeoutExpired("adb", 7, output=output), stopped, stopped,
        subprocess.CompletedProcess([], 0, instrumentation_status("test_close", 0), ""),
        batch_size=2)
    assert results["test_notes.py::test_save"] == AndroidTestResult("passed")
    assert results["test_notes.py::test_close"] == AndroidTestResult("passed")
    error = results["test_notes.py::test_open"].error
    assert "timed out after 7 seconds" in error
    assert f"Completed: {2 if last_code == 0 else 1}/2" in error
    assert command.call_count == 4
    assert command.call_args_list[-1].args[0][-2] == r"Tests\$Suite#test_close"


def test_failed_batch_cleanup_does_not_start_another_instrumentation_process(three_tests):
    output = instrumentation_status("test_save", 0)
    results, command = device_runner(
        three_tests, subprocess.TimeoutExpired("adb", 7, output=output),
        OSError("offline"), subprocess.CompletedProcess([], 0, "", ""), batch_size=2)
    assert results["test_notes.py::test_save"] == AndroidTestResult("passed")
    assert results["test_notes.py::test_open"].outcome == "failed"
    assert results["test_notes.py::test_close"].outcome == "failed"
    assert "batch not started because cleanup failed" in results["test_notes.py::test_close"].error
    assert "offline" in results["test_notes.py::test_close"].error
    assert command.call_count == 3


@pytest.mark.parametrize("outcome", [
    subprocess.CompletedProcess([], 1, "", "disconnected"),
    subprocess.CompletedProcess([], 0, "INSTRUMENTATION_FAILED: process crashed", ""),
    subprocess.CompletedProcess([], 0, "", ""),
    OSError("cannot start adb"),
])
def test_failed_batch_does_not_replace_earlier_or_later_results(three_tests, outcome):
    stopped = subprocess.CompletedProcess([], 0, "", "")
    cleanup = [stopped, stopped] if isinstance(outcome, OSError) else []
    results, _ = device_runner(
        three_tests,
        subprocess.CompletedProcess([], 0, instrumentation_status("test_save", 0), ""),
        outcome, *cleanup,
        subprocess.CompletedProcess([], 0, instrumentation_status("test_close", 0), ""),
        batch_size=1)
    assert results["test_notes.py::test_save"] == AndroidTestResult("passed")
    assert results["test_notes.py::test_open"].outcome == "failed"
    assert results["test_notes.py::test_close"] == AndroidTestResult("passed")


@pytest.mark.parametrize("as_bytes", [False, True])
def test_device_timeout_preserves_completed_results_and_names_last_started(three_tests, as_bytes):
    output = (instrumentation_status("test_save", 0)
              + instrumentation_status("test_open", 1) + "unfinished 雪")
    if as_bytes:
        output = output.encode() + b"\xff"
    error = subprocess.TimeoutExpired("adb", 7, output=output, stderr=b"connection lost")
    stopped = subprocess.CompletedProcess([], 0, "", "")

    results, command = device_runner(three_tests, error, stopped, stopped)

    assert results["test_notes.py::test_save"] == AndroidTestResult("passed")
    for name in ["open", "close"]:
        result = results[f"test_notes.py::test_{name}"]
        assert result.outcome == "failed"
        assert "timed out after 7 seconds" in result.error
        assert "Last started: test_notes.py::test_open" in result.error
        assert "Completed: 1/3" in result.error
        assert "unfinished 雪" in result.error
        assert "connection lost" in result.error
    assert command.call_args_list[0].kwargs["timeout"] == 7
    assert [call.args[0] for call in command.call_args_list[1:]] == [
        [Path("adb"), "-s", "emulator-5566", "shell", "am", "force-stop", package]
        for package in [TARGET_PACKAGE, TEST_PACKAGE]]
    for call in command.call_args_list[1:]:
        assert call.kwargs == {"environment": {"ANDROID_HOME": "sdk"},
                               "capture_output": True, "check": False, "timeout": 10}


def test_device_timeout_after_last_result_cannot_report_success(three_tests):
    output = "".join(instrumentation_status(f"test_{name}", 0)
                     for name in ["open", "close", "save"])
    stopped = subprocess.CompletedProcess([], 0, "", "")
    results, _ = device_runner(three_tests, subprocess.TimeoutExpired("adb", 7, output=output),
                               stopped, stopped)
    assert results["test_notes.py::test_open"] == AndroidTestResult("passed")
    assert results["test_notes.py::test_close"] == AndroidTestResult("passed")
    result = results["test_notes.py::test_save"]
    assert result.outcome == "failed"
    assert "timed out after 7 seconds" in result.error
    assert "Completed: 3/3" in result.error


def test_device_timeout_retains_assertion_and_survives_cleanup_errors(three_tests):
    output = instrumentation_status("test_save", -2, details=(
        "INSTRUMENTATION_STATUS: stack=java.lang.AssertionError: expected 雪\n"
        "    at Tests.save(test_notes.py:12)\n"))
    output += "truncated output\n" * 2000 + "INSTRUMENTATION_STATUS_CODE: -"
    results, command = device_runner(
        three_tests, subprocess.TimeoutExpired("adb", 7, output=output),
        OSError("device unavailable"), subprocess.CompletedProcess([], 1, "", "offline"))
    assert command.call_count == 3
    assert results["test_notes.py::test_save"] == AndroidTestResult(
        "failed", "java.lang.AssertionError: expected 雪\n    at Tests.save(test_notes.py:12)")
    error = results["test_notes.py::test_open"].error
    assert "timed out after 7 seconds" in error
    assert "device unavailable" in error and "offline" in error
    assert len(error) < 10000


def test_device_timeout_without_output_survives_a_second_timeout(three_tests):
    results, command = device_runner(
        three_tests, subprocess.TimeoutExpired("adb", 7),
        subprocess.TimeoutExpired("adb force-stop", 10), RuntimeError("SDK disconnected"))
    assert command.call_count == 3
    assert all(result.outcome == "failed" for result in results.values())
    error = results["test_notes.py::test_save"].error
    assert "timed out after 7 seconds" in error
    assert "Last started: not reported. Completed: 0/3." in error
    assert "SDK disconnected" in error
    assert "timed out after 10 seconds" in error


@pytest.mark.parametrize(("returncode", "fatal_output", "error"), [
    (0, "", None),
    (1, "", "exited with status 1"),
    (0, "INSTRUMENTATION_FAILED: crashed during teardown", "crashed during teardown"),
])
def test_device_exit_status_is_not_hidden_by_completed_test_results(
    three_tests, returncode, fatal_output, error,
):
    output = "".join(instrumentation_status(f"test_{name}", 0)
                     for name in ["save", "open", "close"])
    results, command = device_runner(
        three_tests, subprocess.CompletedProcess([], returncode, output + fatal_output, ""))
    assert command.call_count == 1
    assert results["test_notes.py::test_save"] == AndroidTestResult("passed")
    assert results["test_notes.py::test_open"] == AndroidTestResult("passed")
    last = results["test_notes.py::test_close"]
    if error:
        assert last.outcome == "failed"
        assert error in last.error
    else:
        assert last == AndroidTestResult("passed")


def test_device_results_distinguish_identical_methods_in_different_classes():
    compilation = JVMCompilation("Tests", {}, (
        JVMCompiledTest("a.py::test_save", "Tests$A", "test_save"),
        JVMCompiledTest("b.py::test_save", "Tests$B", "test_save"),
    ))
    output = (instrumentation_status("test_save", -2, class_name="Tests$B",
                                     details="INSTRUMENTATION_STATUS: stack=failed\n")
              + instrumentation_status("test_save", 0, class_name="Tests$A"))
    assert AndroidDeviceTestRunner._results(compilation, output) == {
        "a.py::test_save": AndroidTestResult("passed"),
        "b.py::test_save": AndroidTestResult("failed", "failed"),
    }


def test_unknown_and_truncated_status_cannot_overwrite_completed_results(three_tests):
    output = (instrumentation_status("test_save", 0)
              + instrumentation_status("test_open", 0, class_name="Unknown")
              + instrumentation_status("test_save", "-")
              + "INSTRUMENTATION_FAILED: process crashed\n")
    results = AndroidDeviceTestRunner._results(three_tests, output)
    assert results["test_notes.py::test_save"] == AndroidTestResult("passed")
    for name in ["open", "close"]:
        result = results[f"test_notes.py::test_{name}"]
        assert result.outcome == "failed"
        assert "INSTRUMENTATION_FAILED: process crashed" in result.error
        assert "Completed: 1/3" in result.error


@pytest.mark.parametrize(("error", "stream"), [
    ("AssertionError: INSTRUMENTATION_FAILED: quoted text", ""),
    ("AssertionError: mismatch\n    expected INSTRUMENTATION_FAILED: quoted text", ""),
    ("AssertionError: mismatch", "printed INSTRUMENTATION_FAILED: quoted text"),
])
def test_failure_text_does_not_turn_a_later_pass_into_an_instrumentation_failure(
    three_tests, error, stream,
):
    details = f"INSTRUMENTATION_STATUS: stack={error}\n"
    if stream:
        details += f"INSTRUMENTATION_STATUS: stream={stream}\n"
    output = (instrumentation_status("test_save", -2, details=details)
              + instrumentation_status("test_open", 0)
              + instrumentation_status("test_close", 0))
    assert AndroidDeviceTestRunner._results(three_tests, output) == {
        "test_notes.py::test_save": AndroidTestResult("failed", error),
        "test_notes.py::test_open": AndroidTestResult("passed"),
        "test_notes.py::test_close": AndroidTestResult("passed"),
    }


def test_device_runner_maps_instrumentation_status_to_pytest_nodeids():
    compilation = JVMCompilation(
        "Tests",
        {},
        (
            JVMCompiledTest("test_notes.py::test_save", "Tests$Suite", "test_save"),
            JVMCompiledTest("test_notes.py::test_open", "Tests$Suite", "test_open"),
        ),
    )
    output = """\
INSTRUMENTATION_STATUS: class=Tests$Suite
INSTRUMENTATION_STATUS: current=1
INSTRUMENTATION_STATUS: test=test_save
INSTRUMENTATION_STATUS_CODE: 1
INSTRUMENTATION_STATUS: class=Tests$Suite
INSTRUMENTATION_STATUS: current=1
INSTRUMENTATION_STATUS: test=test_save
INSTRUMENTATION_STATUS_CODE: 0
INSTRUMENTATION_STATUS: class=Tests$Suite
INSTRUMENTATION_STATUS: current=2
INSTRUMENTATION_STATUS: test=test_open
INSTRUMENTATION_STATUS_CODE: 1
INSTRUMENTATION_STATUS: class=Tests$Suite
INSTRUMENTATION_STATUS: current=2
INSTRUMENTATION_STATUS: test=test_open
INSTRUMENTATION_STATUS: stack=java.lang.AssertionError: missing note
    at Tests.open(test_notes.py:12)
INSTRUMENTATION_STATUS_CODE: -2
INSTRUMENTATION_CODE: -1
"""

    assert AndroidDeviceTestRunner._results(compilation, output) == {
        "test_notes.py::test_save": AndroidTestResult("passed"),
        "test_notes.py::test_open": AndroidTestResult(
            "failed",
            "java.lang.AssertionError: missing note\n"
            "    at Tests.open(test_notes.py:12)",
        ),
    }


def test_device_manifest_targets_the_empty_test_application():
    builder = AndroidDeviceTestBuilder.__new__(AndroidDeviceTestBuilder)

    manifest = builder._test_manifest()

    assert f'android:name="{RUNNER}"' in manifest
    assert f'android:targetPackage="{TARGET_PACKAGE}"' in manifest


def test_device_packages_split_application_and_test_modules(tmp_path):
    compilation = JVMCompilation(
        "org/pyjs/testing/PyjsTests",
        {
            "org/pyjs/testing/PyjsTests": b"entry",
            "org/pyjs/testing/PyjsTests$Tests": b"junit",
            "org/pyjs/testing/PyjsView": b"bridge",
            "org/pyjs/testing/PyjsTests$module$test_notes": b"test",
            "org/pyjs/testing/PyjsTests$module$notes$NotesActivity": b"app",
        },
        (
            JVMCompiledTest(
                "test_notes.py::test_save",
                "org/pyjs/testing/PyjsTests$Tests",
                "test_save",
            ),
        ),
        test_modules=("test_notes",),
    )

    target = tmp_path / "target"
    tests = tmp_path / "tests"
    AndroidDeviceTestBuilder._write_split_classes(compilation, target, tests)

    assert (
        target
        / "org/pyjs/testing/PyjsTests$module$notes$NotesActivity.class"
    ).read_bytes() == b"app"
    assert (
        tests / "org/pyjs/testing/PyjsTests$module$test_notes.class"
    ).read_bytes() == b"test"
    assert (tests / "org/pyjs/testing/PyjsView.class").read_bytes() == b"bridge"


def test_device_package_rejects_activities_defined_in_test_modules(tmp_path):
    manifest = """\
<manifest>
  <application>
    <activity android:name="org.pyjs.testing.TestActivity" />
  </application>
</manifest>
"""

    with pytest.raises(RuntimeError, match="Move it to an application module"):
        AndroidDeviceTestBuilder._validate_target_activities(
            manifest,
            tmp_path,
        )


def test_device_target_manifest_preserves_application_owner(tmp_path):
    manifest = """\
<manifest package="org.pyjs.testing">
  <application android:name="org.pyjs.testing.App" />
</manifest>
"""
    builder = AndroidDeviceTestBuilder.__new__(AndroidDeviceTestBuilder)
    target = builder._target_manifest(manifest)
    assert f'package="{TARGET_PACKAGE}"' in target
    assert '<application android:debuggable="true" android:name=' in target
    assert 'android:name="org.pyjs.testing.App"' in target
    with pytest.raises(RuntimeError, match="Android application"):
        builder._validate_target_activities(target, tmp_path)
    app = tmp_path / "org/pyjs/testing/App.class"
    app.parent.mkdir(parents=True)
    app.touch()
    builder._validate_target_activities(target, tmp_path)
