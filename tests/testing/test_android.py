import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from pyjs.testing.android import (
    AndroidBounds,
    AndroidTestSession,
    assert_android_image,
    extract_android_errors,
    parse_ui_tree,
)
from pyjs.testing.interaction.gesture import GestureScript
from pyjs.tooling.android import AndroidDevice, AndroidSDK

UI_TREE = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node text="0" resource-id="counter-value" class="android.widget.TextView" content-desc=""
        clickable="false" enabled="true" bounds="[120,300][960,460]" />
  <node text="Increment" resource-id="increment-button" class="android.widget.Button"
        content-desc="Increase count" clickable="true" enabled="true" checkable="true"
        checked="true" selected="false" focused="true"
        bounds="[100,500][980,640]" />
</hierarchy>
"""


def session_with_runner(
    runner: Mock,
) -> AndroidTestSession:
    sdk = AndroidSDK(root=Path("/android"), java_home=Path("/java"), runner=runner)
    return AndroidTestSession(
        sdk,
        AndroidDevice("emulator-5554", "device"),
        "org.pyjs.counter",
        activity="org.pyjs.counter.CounterActivity",
    )


def test_parse_ui_tree_exposes_native_test_ids_and_bounds():
    value, button = parse_ui_tree(UI_TREE)

    assert value.text == "0"
    assert value.test_id == "counter-value"
    assert value.bounds == AndroidBounds(120, 300, 960, 460)
    assert button.clickable
    assert button.description == "Increase count"
    assert button.checkable
    assert button.checked
    assert not button.selected
    assert button.focused
    assert button.bounds.center == (540, 570)


def test_android_image_comparison_writes_a_diff_for_meaningful_changes(tmp_path):
    expected = tmp_path / "expected.png"
    actual = tmp_path / "actual.png"
    diff = tmp_path / "diff.png"
    Image.new("RGBA", (2, 1), (10, 20, 30, 255)).save(expected)
    image = Image.new("RGBA", (2, 1), (10, 20, 30, 255))
    image.putpixel((1, 0), (255, 255, 255, 255))
    image.save(actual)

    assert_android_image(actual, expected, max_different_pixel_ratio=0.5)
    with pytest.raises(AssertionError, match="1/2 Android pixels differ"):
        assert_android_image(
            actual,
            expected,
            max_different_pixel_ratio=0.0,
            diff_path=diff,
        )

    assert diff.exists()


def test_android_session_finds_and_taps_an_element_by_test_id():
    runner = Mock()
    runner.run.side_effect = [
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    ]
    session = session_with_runner(runner)
    session.ui_tree = Mock(return_value=UI_TREE)

    element = session.tap_element(test_id="increment-button", timeout=0.01, interval=0)

    assert element.text == "Increment"
    assert runner.run.call_args_list[-1].args[0] == [
        Path("/android/platform-tools/adb"),
        "-s",
        "emulator-5554",
        "shell",
        "input",
        "tap",
        "540",
        "570",
    ]


def test_android_session_launches_the_configured_activity_directly():
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [],
        0,
        stdout="",
        stderr="",
    )
    session = session_with_runner(runner)

    session.launch()

    assert [call.args[0] for call in runner.run.call_args_list] == [
        [
            Path("/android/platform-tools/adb"),
            "-s",
            "emulator-5554",
            "logcat",
            "-c",
        ],
        [
            Path("/android/platform-tools/adb"),
            "-s",
            "emulator-5554",
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            "org.pyjs.counter/org.pyjs.counter.CounterActivity",
            "-c",
            "android.intent.category.LAUNCHER",
            "-a",
            "android.intent.action.MAIN",
        ],
    ]


def test_android_session_dispatches_a_timed_gesture_script():
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [],
        0,
        stdout="",
        stderr="",
    )
    wait = Mock()
    session = session_with_runner(runner)
    script = (
        GestureScript()
        .long_press(10.4, 20.6, 500)
        .line_to(30, 40, 60, steps=3)
        .release(30)
    )

    session.dispatch_gesture(script, settle_ms=100, wait=wait)

    actions = [call.args[0][-3:] for call in runner.run.call_args_list]
    assert actions == [
        ["DOWN", "10", "21"],
        ["MOVE", "10", "21"],
        ["MOVE", "17", "27"],
        ["MOVE", "23", "34"],
        ["MOVE", "30", "40"],
        ["UP", "30", "40"],
    ]
    assert [call.args[0] for call in wait.call_args_list] == [
        0.5,
        0.02,
        0.02,
        0.02,
        0.03,
        0.1,
    ]


def test_android_session_holds_and_releases_an_active_gesture():
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [],
        0,
        stdout="",
        stderr="",
    )
    wait = Mock()
    session = session_with_runner(runner)
    script = GestureScript().long_press(10, 20, 500).move_to(30, 40, 16)

    with session.held_gesture(script, settle_ms=200, wait=wait):
        actions = [call.args[0][-3] for call in runner.run.call_args_list]
        assert actions == ["DOWN", "MOVE", "MOVE"]

    actions = [call.args[0][-3] for call in runner.run.call_args_list]
    assert actions == ["DOWN", "MOVE", "MOVE", "UP"]
    assert [call.args[0] for call in wait.call_args_list] == [0.5, 0.016, 0.2]


def test_android_session_cancels_a_held_gesture_when_inspection_fails():
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [],
        0,
        stdout="",
        stderr="",
    )
    session = session_with_runner(runner)
    script = GestureScript().press(10, 20).hold(1)

    with pytest.raises(AssertionError, match="preview diverged"):
        with session.held_gesture(script, wait=Mock()):
            raise AssertionError("preview diverged")

    actions = [call.args[0][-3] for call in runner.run.call_args_list]
    assert actions == ["DOWN", "MOVE", "CANCEL"]


def test_android_session_captures_screenshot_ui_tree_and_logcat(tmp_path, monkeypatch):
    monkeypatch.setattr("pyjs.testing.android.uuid4", lambda: Mock(hex="capture"))
    runner = Mock()
    runner.run.side_effect = [
        subprocess.CompletedProcess([], 0, stdout=b"png", stderr=b""),
        subprocess.CompletedProcess([], 0, stdout=(
            "UI hierchary dumped to: /data/local/tmp/pyjs-window-capture.xml\n"
        ), stderr=""),
        subprocess.CompletedProcess([], 0, stdout=UI_TREE, stderr=""),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="1234\n", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="Application started\n", stderr=""),
    ]
    session = session_with_runner(runner)

    manifest = session.capture_artifacts(tmp_path, "counter failed")

    assert (tmp_path / "counter-failed.png").read_bytes() == b"png"
    assert (tmp_path / "counter-failed.xml").read_text() == UI_TREE
    assert (tmp_path / "counter-failed.logcat.txt").read_text() == "Application started\n"
    assert manifest == tmp_path / "counter-failed.manifest.json"


@pytest.mark.parametrize("failure", ["idle", "timeout"])
def test_android_dump_never_reads_old_xml_after_failure(failure):
    runner = Mock()
    session = session_with_runner(runner)

    def run(command, **kwargs):
        if "dump" in command:
            assert kwargs["timeout"] == 20
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 20)
            return subprocess.CompletedProcess(command, 0, "", "ERROR: could not get idle state.")
        assert command[-3:-1] == ["rm", "-f"]
        return subprocess.CompletedProcess(command, 0, "", "")

    runner.run.side_effect = run
    error = subprocess.TimeoutExpired if failure == "timeout" else RuntimeError
    with pytest.raises(error):
        session.ui_tree()
    assert runner.run.call_count == 2
    dumped = runner.run.call_args_list[0].args[0][-1]
    assert dumped.startswith("/data/local/tmp/pyjs-window-")
    assert runner.run.call_args_list[1].args[0][-1] == dumped


def test_android_dumps_have_unique_paths_and_cleanup_after_reading():
    runner = Mock()
    session = session_with_runner(runner)
    paths = []

    def run(command, **kwargs):
        if "dump" in command:
            paths.append(command[-1])
            return subprocess.CompletedProcess(command, 0, "UI hierchary dumped to: " + paths[-1], "")
        assert command[-1] == paths[-1]
        return subprocess.CompletedProcess(command, 0, UI_TREE if "cat" in command else "", "")

    runner.run.side_effect = run
    assert session.ui_tree() == UI_TREE
    assert session.ui_tree() == UI_TREE
    assert len(set(paths)) == 2
    assert [call.kwargs["timeout"] for call in runner.run.call_args_list] == [20, 5, 5] * 2


@pytest.mark.parametrize("capture", ["success", "idle", "read_error"])
@pytest.mark.parametrize("cleanup", ["timeout", "start_error", "exit_error"])
def test_android_cleanup_preserves_capture_result_and_reports_failure(caplog, capture, cleanup):
    runner = Mock()
    session = session_with_runner(runner)
    read_error = subprocess.CalledProcessError(1, "cat", stderr="read failed")

    def run(command, **kwargs):
        if "dump" in command:
            message = "UI hierchary dumped to: " + command[-1] if capture != "idle" else ""
            return subprocess.CompletedProcess(command, 0, message, "idle failure")
        if "cat" in command:
            if capture == "read_error":
                raise read_error
            return subprocess.CompletedProcess(command, 0, UI_TREE, "")
        assert command[-3:-1] == ["rm", "-f"]
        assert kwargs["timeout"] == 5
        assert kwargs["check"]
        if cleanup == "timeout":
            raise subprocess.TimeoutExpired(command, 5)
        if cleanup == "start_error":
            raise OSError("adb unavailable")
        raise subprocess.CalledProcessError(1, command, stderr="cleanup failed")

    runner.run.side_effect = run
    if capture == "success":
        assert session.ui_tree() == UI_TREE
    elif capture == "idle":
        with pytest.raises(RuntimeError, match="Android UI dump was not produced: idle failure"):
            session.ui_tree()
    else:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            session.ui_tree()
        assert caught.value is read_error
    assert len(caplog.records) == 1
    assert caplog.records[0].name == "pyjs.testing.android"
    assert "Could not remove Android UI dump /data/local/tmp/pyjs-window-" in caplog.text
    assert runner.run.call_args_list[-1].args[0][-3:-1] == ["rm", "-f"]


def test_android_session_reports_native_crashes_without_javascript_mapping():
    session = session_with_runner(Mock())
    session.logcat = Mock(
        return_value=(
            "I JS: CONSOLE LOG: ready\n"
            "E JS: CONSOLE ERROR: No known animation properties specified\n"
            "E AndroidRuntime: FATAL EXCEPTION: main\n"
        )
    )

    assert session.log_errors() == "E AndroidRuntime: FATAL EXCEPTION: main"


def test_android_error_extraction_retains_a_complete_runtime_crash():
    source = (
        "08-26 08:27:46.495  4874  4874 E AndroidRuntime: FATAL EXCEPTION: main\n"
        "08-26 08:27:46.495  4874  4874 E AndroidRuntime: Process: example\n"
        "08-26 08:27:46.495  4874  4874 E AndroidRuntime: "
        "java.lang.IllegalArgumentException: failed\n"
        "08-26 08:27:46.495  4874  4874 E AndroidRuntime: "
        "\tat org.pyjs.counter.PyjsAndroid.calculate(android.py:4)\n"
        "08-26 08:27:46.495  4874  4874 E AndroidRuntime: "
        "\tat android.app.ActivityThread.main(ActivityThread.java:1)\n"
        "08-26 08:27:46.497  4874  4874 W System.err: "
        "An uncaught Exception occurred on main.\n"
        "08-26 08:27:46.497  4874  4874 W System.err: "
        "java.lang.IllegalArgumentException: failed\n"
        "08-26 08:27:46.501   575  1732 D ActivityManager: process died\n"
    )

    assert extract_android_errors(source) == "\n".join(source.splitlines()[:5])


def test_android_element_wait_reports_an_early_runtime_exit():
    session = session_with_runner(Mock())
    session.find_element = Mock(return_value=None)
    session.is_running = Mock(return_value=False)
    session.log_errors = Mock(return_value="FATAL EXCEPTION: main")

    with pytest.raises(RuntimeError) as caught:
        session.wait_for_element(test_id="content", timeout=1, interval=0)

    assert str(caught.value) == (
        "Android application 'org.pyjs.counter' stopped while waiting for UI.\n"
        "FATAL EXCEPTION: main"
    )


def test_android_session_retains_python_lines_in_unstructured_jvm_stacks():
    session = session_with_runner(Mock())
    session.logcat = Mock(
        return_value=(
            "Application started\n"
            "FATAL EXCEPTION: main\n"
            "    at org.pyjs.counter.PyjsAndroid.save(android.py:2)\n"
            "Caused by: java.lang.IllegalArgumentException: failed\n"
            "    ... 3 more\n"
            "Application stopped\n"
        )
    )

    assert session.log_errors() == (
        "FATAL EXCEPTION: main\n"
        "    at org.pyjs.counter.PyjsAndroid.save(android.py:2)\n"
        "Caused by: java.lang.IllegalArgumentException: failed\n"
        "    ... 3 more"
    )


def test_android_failure_artifacts_preserve_jvm_python_line_metadata(
    tmp_path,
):
    runtime_error = (
        "E AndroidRuntime: FATAL EXCEPTION: main\n"
        "E AndroidRuntime: java.lang.IllegalArgumentException: failed\n"
        "E AndroidRuntime:     at org.pyjs.counter.PyjsAndroid.calculate(android.py:4)\n"
    )
    runner = Mock()
    runner.run.side_effect = [
        subprocess.CompletedProcess([], 0, stdout=b"png", stderr=b""),
        subprocess.CompletedProcess([], 0, stdout="1234\n", stderr=""),
        subprocess.CompletedProcess([], 0, stdout=runtime_error, stderr=""),
    ]
    session = session_with_runner(runner)
    session.ui_tree = Mock(return_value=UI_TREE)

    with pytest.raises(AssertionError) as caught:
        with session.artifacts_on_failure(tmp_path, "native failure"):
            raise AssertionError("broken")

    assert (tmp_path / "native-failure.logcat.txt").read_text() == runtime_error
    manifest = json.loads((tmp_path / "native-failure.manifest.json").read_text())
    assert set(manifest["metadata"]) == {"app_id", "activity", "device"}
    assert {item["name"] for item in manifest["artifacts"]} == {
        "screenshot", "ui_tree", "logcat",
    }
    assert caught.value.__notes__ == [
        f"Android failure artifacts: {tmp_path / 'native-failure.manifest.json'}",
        "Android runtime errors:\n" + runtime_error.rstrip(),
    ]


def test_android_failure_context_adds_manifest_to_the_error(tmp_path):
    runner = Mock()
    runner.run.side_effect = [
        subprocess.CompletedProcess([], 0, stdout=b"png", stderr=b""),
        subprocess.CompletedProcess([], 0, stdout="1234\n", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="log", stderr=""),
    ]
    session = session_with_runner(runner)
    session.ui_tree = Mock(return_value=UI_TREE)

    with pytest.raises(AssertionError) as caught:
        with session.artifacts_on_failure(tmp_path, "failure"):
            raise AssertionError("broken")

    assert caught.value.__notes__ == [
        f"Android failure artifacts: {tmp_path / 'failure.manifest.json'}"
    ]


def test_android_artifact_capture_retains_other_evidence_when_one_capture_fails(tmp_path):
    runner = Mock()
    runner.run.side_effect = [
        subprocess.CalledProcessError(1, "screencap"),
        subprocess.CompletedProcess([], 0, stdout="1234\n", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="log", stderr=""),
    ]
    session = session_with_runner(runner)
    session.ui_tree = Mock(return_value=UI_TREE)

    manifest = session.capture_artifacts(tmp_path, "partial")
    data = json.loads(manifest.read_text())

    assert [artifact["name"] for artifact in data["artifacts"]] == ["ui_tree", "logcat"]
    assert data["metadata"]["capture_errors"] == {
        "screenshot": "CalledProcessError: Command 'screencap' returned non-zero exit status 1."
    }
