import asyncio
import base64
import io
import json
import os
import signal
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from pyjs.testing import pytest_plugin
from pyjs.testing.android_runtime import AndroidTestResult
from pyjs.testing.builder import SelectedTest
from pyjs.testing.protocol import failed_run, format_run_failure
from pyjs.testing.pytest_plugin import (
    AndroidJVMResults,
    BrowserResults,
    BrowserTestConfig,
    add_daemon_diagnostics,
    add_failure_artifacts,
    android_dependency_locks,
    android_dependency_sets,
    daemon_matches_project,
    exchange_run_request,
    get_daemon_health,
    is_android_jvm_test,
    is_android_jvm_test_for_runtime,
    is_web_test,
    pytest_pyfunc_call,
    pytest_runtest_setup,
    read_log_tail,
    selected_test_from_item,
    send_run_request,
    terminate_daemon_process,
    verify_render_artifact,
)


def render_data_url(colors):
    image = Image.new("RGBA", (len(colors), 1))
    image.putdata(colors)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def render_item(tmp_path, update=False):
    cache = SimpleNamespace(mkdir=lambda name: tmp_path / ".pytest_cache" / name)
    config = SimpleNamespace(
        cache=cache,
        getoption=lambda name: update if name == "--pyjs-update-renders" else None,
        getini=lambda name: False if name == "pyjs_headed" else "",
        rootpath=tmp_path,
    )
    return SimpleNamespace(
        path=tmp_path / "test_cube.py",
        nodeid="test_cube.py::test_cube",
        config=config,
    )


def test_daemon_startup_waits_for_cold_runner_compilation(tmp_path, monkeypatch):
    settings = BrowserTestConfig.from_pytest(pytest_config(tmp_path))
    # The old ten-second socket-start deadline expired before a cold build.
    clock = iter((0, 1, 15, 40))
    monkeypatch.setattr(pytest_plugin.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(pytest_plugin.time, "time", lambda: next(clock))
    monkeypatch.setattr(pytest_plugin.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pytest_plugin, "get_daemon_health", Mock(return_value=None))
    matches = Mock(side_effect=[False, False, False, True])
    monkeypatch.setattr(pytest_plugin, "daemon_matches_project", matches)
    launch = Mock(return_value=Mock(poll=Mock(return_value=None)))
    monkeypatch.setattr(pytest_plugin.subprocess, "Popen", launch)

    pytest_plugin.ensure_daemon_running(8765, 120, tmp_path, tmp_path / "cache", settings, "signature")

    launch.assert_called_once()
    assert matches.call_count == 4


def test_daemon_startup_reports_process_failure_without_waiting(tmp_path, monkeypatch):
    settings = BrowserTestConfig.from_pytest(pytest_config(tmp_path))
    monkeypatch.setattr(pytest_plugin, "get_daemon_health", Mock(return_value=None))
    monkeypatch.setattr(pytest_plugin.subprocess, "Popen", Mock(return_value=Mock(poll=Mock(return_value=1))))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "daemon.log").write_text("Failed to build browser runner page: invalid runner code\n")

    with pytest.raises(RuntimeError, match="exited during startup.*", check=lambda exc: "invalid runner code" in str(exc)):
        pytest_plugin.ensure_daemon_running(8765, 120, tmp_path, cache, settings, "signature")


def test_browser_filename_has_no_implicit_pyjs_behavior():
    item = SimpleNamespace(
        path="tests/test_browser_external_service.py",
        config=SimpleNamespace(getoption=lambda name: None),
        get_closest_marker=lambda name: None,
    )

    pytest_runtest_setup(item)


def test_explicit_web_marker_skips_normal_python_run():
    item = SimpleNamespace(
        config=SimpleNamespace(getoption=lambda name: None),
        get_closest_marker=lambda name: object() if name == "pyjs_web" else None,
    )

    with pytest.raises(pytest.skip.Exception, match="web-only test"):
        pytest_runtest_setup(item)


def test_unmarked_test_skips_web_run():
    item = SimpleNamespace(
        config=SimpleNamespace(getoption=lambda name: "web" if name == "--pyjs-target" else None),
        get_closest_marker=lambda name: None,
    )

    with pytest.raises(pytest.skip.Exception, match="not a web test"):
        pytest_runtest_setup(item)


def test_explicit_web_marker_runs_with_web_target():
    item = SimpleNamespace(
        config=SimpleNamespace(getoption=lambda name: "web" if name == "--pyjs-target" else None),
        get_closest_marker=lambda name: object() if name == "pyjs_web" else None,
    )

    pytest_runtest_setup(item)


def test_web_test_selection_excludes_other_explicit_targets():
    web_item = SimpleNamespace(
        get_closest_marker=lambda name: object() if name == "pyjs_web" else None,
    )
    python_item = SimpleNamespace(
        get_closest_marker=lambda name: object()
        if name in {"pyjs_web", "pyjs_python"}
        else None,
    )
    android_item = SimpleNamespace(
        get_closest_marker=lambda name: object()
        if name in {"pyjs_web", "pyjs_android"}
        else None,
    )

    assert is_web_test(web_item)
    assert not is_web_test(python_item)
    assert not is_web_test(android_item)


def test_infrastructure_failure_is_not_cached_for_later_tests(monkeypatch):
    selected = SimpleNamespace(nodeid="tests/test_app.py::test_value")
    state = BrowserResults()
    state.eligible_tests = [selected]
    config = SimpleNamespace(
        _pyjs_web_results=state,
        getoption=lambda name: "web" if name == "--pyjs-target" else None,
    )
    item = SimpleNamespace(
        cls=None,
        config=config,
        module=SimpleNamespace(__name__="tests.test_app"),
        name="test_value",
        nodeid=selected.nodeid,
        originalname=None,
    )
    responses = iter(
        [
            failed_run("bundle_build", "cannot compile test"),
            {
                "type": "run_tests_result",
                "status": "ok",
                "results": [{"nodeid": selected.nodeid, "outcome": "passed"}],
            },
        ]
    )
    monkeypatch.setattr(
        "pyjs.testing.pytest_plugin.run_browser_target",
        lambda *args: next(responses),
    )

    with pytest.raises(pytest.fail.Exception, match="cannot compile test"):
        pytest_pyfunc_call(item)

    assert pytest_pyfunc_call(item) is True


def test_android_target_skips_tests_without_android_marker():
    item = SimpleNamespace(
        config=SimpleNamespace(
            getoption=lambda name: "android" if name == "--pyjs-target" else None
        ),
        get_closest_marker=lambda name: None,
    )

    with pytest.raises(pytest.skip.Exception, match="not a host-driven Android test"):
        pytest_runtest_setup(item)


def test_android_marker_skips_normal_python_run():
    item = SimpleNamespace(
        config=SimpleNamespace(getoption=lambda name: None),
        get_closest_marker=lambda name: object() if name == "pyjs_android" else None,
    )

    with pytest.raises(pytest.skip.Exception, match="Android-only test"):
        pytest_runtest_setup(item)


def test_robolectric_target_selects_compiled_android_tests():
    item = SimpleNamespace(
        config=SimpleNamespace(
            getoption=lambda name: {
                "--pyjs-target": "android",
                "--pyjs-android-runtime": "robolectric",
            }.get(name)
        ),
        get_closest_marker=lambda name: (
            object() if name == "pyjs_android_jvm" else None
        ),
    )

    assert is_android_jvm_test(item)
    pytest_runtest_setup(item)


def test_robolectric_skips_device_only_compiled_android_tests():
    item = SimpleNamespace(
        config=SimpleNamespace(
            getoption=lambda name: {
                "--pyjs-target": "android",
                "--pyjs-android-runtime": "robolectric",
            }.get(name)
        ),
        get_closest_marker=lambda name: (
            object()
            if name in {"pyjs_android_jvm", "pyjs_android_device"}
            else None
        ),
    )

    assert not is_android_jvm_test_for_runtime(item, "robolectric")
    assert is_android_jvm_test_for_runtime(item, "device")
    with pytest.raises(pytest.skip.Exception, match="device-only Android test"):
        pytest_runtest_setup(item)


def test_pytest_reports_cached_robolectric_results():
    state = AndroidJVMResults()
    nodeid = "tests/test_notes.py::test_title"
    state.eligible_tests = [SelectedTest(nodeid, "tests.test_notes", "test_title")]
    state.results = {nodeid: AndroidTestResult("passed")}
    config = SimpleNamespace(
        _pyjs_android_jvm_results=state,
        getoption=lambda name: {
            "--pyjs-target": "android",
            "--pyjs-android-runtime": "robolectric",
        }.get(name),
    )
    item = SimpleNamespace(
        config=config,
        get_closest_marker=lambda name: (
            object() if name == "pyjs_android_jvm" else None
        ),
        nodeid=nodeid,
    )

    assert pytest_pyfunc_call(item) is True


def test_pytest_reports_cached_device_results():
    state = AndroidJVMResults()
    nodeid = "tests/test_notes.py::test_title"
    state.eligible_tests = [SelectedTest(nodeid, "tests.test_notes", "test_title")]
    state.results = {nodeid: AndroidTestResult("passed")}
    config = SimpleNamespace(
        _pyjs_android_jvm_results=state,
        getoption=lambda name: {
            "--pyjs-target": "android",
            "--pyjs-android-runtime": "device",
        }.get(name),
    )
    item = SimpleNamespace(
        config=config,
        get_closest_marker=lambda name: (
            object() if name == "pyjs_android_jvm" else None
        ),
        nodeid=nodeid,
    )

    assert pytest_pyfunc_call(item) is True


def test_host_android_runtime_leaves_mixed_tests_to_pytest():
    item = SimpleNamespace(
        config=SimpleNamespace(
            getoption=lambda name: {
                "--pyjs-target": "android",
                "--pyjs-android-runtime": "host",
            }.get(name)
        ),
        get_closest_marker=lambda name: (
            object()
            if name in {"pyjs_android", "pyjs_android_jvm"}
            else None
        ),
    )

    pytest_runtest_setup(item)
    assert pytest_pyfunc_call(item) is None


def test_android_suite_failure_is_cached_for_the_remaining_tests(monkeypatch):
    first = SelectedTest("tests/test_notes.py::test_first", "test_notes", "test_first")
    second = SelectedTest(
        "tests/test_notes.py::test_second",
        "test_notes",
        "test_second",
    )
    state = AndroidJVMResults()
    state.eligible_tests = [first, second]
    config = SimpleNamespace(
        _pyjs_android_jvm_results=state,
        getoption=lambda name: {
            "--pyjs-target": "android",
            "--pyjs-android-runtime": "robolectric",
        }.get(name),
    )
    item = SimpleNamespace(
        config=config,
        get_closest_marker=lambda name: (
            object() if name == "pyjs_android_jvm" else None
        ),
        nodeid=first.nodeid,
    )
    run = Mock(side_effect=RuntimeError("suite compilation failed"))
    monkeypatch.setattr(pytest_plugin, "run_robolectric_target", run)

    with pytest.raises(pytest.fail.Exception, match="suite compilation failed"):
        pytest_pyfunc_call(item)

    item.nodeid = second.nodeid
    with pytest.raises(pytest.fail.Exception, match="suite compilation failed"):
        pytest_pyfunc_call(item)
    assert run.call_count == 1


def test_pytest_plugin_does_not_load_android_compilers_until_selected():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import pyjs.testing.pytest_plugin; "
            "print('pyjs.java.transpiler' in sys.modules); "
            "print('pyjs.testing.android_device' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "False\nFalse\n"


def test_selected_test_uses_collected_module_instead_of_nodeid_path():
    item = SimpleNamespace(
        cls=None,
        module=SimpleNamespace(__name__="project.tests.test_example"),
        name="test_value[param]",
        nodeid="src/project/tests/test_example.py::test_value[param]",
        originalname="test_value",
        iter_markers=lambda name: (),
    )

    selected = selected_test_from_item(item)

    assert selected.nodeid == "src/project/tests/test_example.py::test_value[param]"
    assert selected.module_name == "project.tests.test_example"
    assert selected.function_name == "test_value"


def test_selected_test_collects_android_application_dependencies():
    markers = [
        SimpleNamespace(args=("androidx",), kwargs={}),
        SimpleNamespace(args=("androidx",), kwargs={}),
    ]
    item = SimpleNamespace(
        cls=None,
        module=SimpleNamespace(__name__="tests.test_notes"),
        name="test_drag",
        nodeid="tests/test_notes.py::test_drag",
        originalname=None,
        iter_markers=lambda name: (
            markers if name == "pyjs_android_dependencies" else ()
        ),
    )

    selected = selected_test_from_item(item)

    assert selected.android_dependencies == ("androidx",)


def test_selected_test_rejects_invalid_android_dependency_markers():
    item = SimpleNamespace(
        cls=None,
        module=SimpleNamespace(__name__="tests.test_notes"),
        name="test_drag",
        nodeid="tests/test_notes.py::test_drag",
        originalname=None,
        iter_markers=lambda name: (
            [SimpleNamespace(args=(42,), kwargs={})]
            if name == "pyjs_android_dependencies"
            else ()
        ),
    )

    with pytest.raises(pytest.UsageError, match="positional strings"):
        selected_test_from_item(item)


def test_android_dependency_sets_reject_unknown_names_before_building():
    selected = SelectedTest(
        "tests/test_notes.py::test_drag",
        "tests.test_notes",
        "test_drag",
        ("androidx", "unknown"),
    )

    with pytest.raises(pytest.UsageError, match="unknown Android dependency set"):
        android_dependency_sets([selected])


def test_android_dependency_sets_accept_project_locks(tmp_path):
    lock = tmp_path / "android" / "markdown.json"
    lock.parent.mkdir()
    lock.write_text('{"version": 1, "artifacts": []}')
    config = SimpleNamespace(
        rootpath=tmp_path,
        getini=lambda name: (
            ["markdown=android/markdown.json"]
            if name == "pyjs_android_dependency_sets"
            else []
        ),
    )

    locks = android_dependency_locks(config)
    selected = SelectedTest(
        "tests/test_notes.py::test_markdown",
        "tests.test_notes",
        "test_markdown",
        ("markdown", "androidx"),
    )

    assert locks["markdown"] == lock
    assert android_dependency_sets([selected], frozenset(locks)) == frozenset(
        {"androidx", "markdown"}
    )


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (["MissingSeparator"], "NAME=PATH"),
        (["androidx=custom.json"], "duplicate"),
        (["UPPER=custom.json"], "NAME=PATH"),
        (["missing=custom.json"], "was not found"),
    ],
)
def test_android_dependency_lock_configuration_is_validated(
    tmp_path,
    entries,
    message,
):
    config = SimpleNamespace(
        rootpath=tmp_path,
        getini=lambda _name: entries,
    )

    with pytest.raises(pytest.UsageError, match=message):
        android_dependency_locks(config)


def test_selected_test_rejects_class_methods():
    item = SimpleNamespace(cls=object, nodeid="tests/test_example.py::ExampleTests::test_value")

    with pytest.raises(ValueError, match="module-level test functions"):
        selected_test_from_item(item)


def test_render_artifact_update_creates_a_baseline(tmp_path):
    artifact = {
        "name": "cube",
        "dataUrl": render_data_url([(10, 20, 30, 255)]),
        "pixelThreshold": 8,
        "maxDifferentPixelRatio": 0.01,
    }

    assert verify_render_artifact(render_item(tmp_path, update=True), artifact) is None
    assert (tmp_path / "renders" / "cube.png").exists()
    assert verify_render_artifact(render_item(tmp_path), artifact) is None


def test_render_artifact_reports_a_missing_baseline(tmp_path):
    artifact = {
        "name": "cube",
        "dataUrl": render_data_url([(10, 20, 30, 255)]),
    }

    error = verify_render_artifact(render_item(tmp_path), artifact)

    assert "Missing expected render" in error
    assert "--pyjs-update-renders" in error


def test_render_artifact_reports_capture_errors(tmp_path):
    artifact = {"name": "card", "error": "The rendered element was not found"}

    error = verify_render_artifact(render_item(tmp_path), artifact)

    assert error == "Could not capture render artifact 'card': The rendered element was not found"


def test_render_artifact_allows_small_per_channel_differences(tmp_path):
    expected = {
        "name": "cube",
        "dataUrl": render_data_url([(10, 20, 30, 255)]),
        "pixelThreshold": 8,
        "maxDifferentPixelRatio": 0.0,
    }
    verify_render_artifact(render_item(tmp_path, update=True), expected)
    actual = {**expected, "dataUrl": render_data_url([(18, 12, 37, 255)])}

    assert verify_render_artifact(render_item(tmp_path), actual) is None


def test_render_artifact_mismatch_writes_actual_and_diff_images(tmp_path):
    expected = {
        "name": "cube",
        "dataUrl": render_data_url([(0, 0, 0, 255)]),
        "pixelThreshold": 8,
        "maxDifferentPixelRatio": 0.0,
    }
    verify_render_artifact(render_item(tmp_path, update=True), expected)
    actual = {**expected, "dataUrl": render_data_url([(255, 255, 255, 255)])}

    error = verify_render_artifact(render_item(tmp_path), actual)

    assert "1/1 pixels differ" in error
    output_dir = tmp_path / ".pytest_cache" / "pyjs" / "artifacts" / "renders"
    assert list(output_dir.glob("*-actual.png"))
    assert list(output_dir.glob("*-diff.png"))


def test_render_artifact_mismatch_records_webgpu_diagnostics(tmp_path):
    expected = {
        "name": "cube",
        "dataUrl": render_data_url([(0, 0, 0, 255)]),
        "pixelThreshold": 8,
        "maxDifferentPixelRatio": 0.0,
    }
    verify_render_artifact(render_item(tmp_path, update=True), expected)
    actual = {
        **expected,
        "dataUrl": render_data_url([(255, 255, 255, 255)]),
        "diagnostics": "vendor=Example; architecture=software; canvas=1x1",
    }

    error = verify_render_artifact(render_item(tmp_path), actual)

    assert "WebGPU diagnostics: vendor=Example" in error
    output_dir = tmp_path / ".pytest_cache" / "pyjs" / "artifacts" / "renders"
    diagnostics = list(output_dir.glob("*-diagnostics.txt"))
    assert len(diagnostics) == 1
    assert diagnostics[0].read_text() == (
        "vendor=Example; architecture=software; canvas=1x1\n"
    )


def pytest_config(tmp_path, *, options=None, ini=None):
    options = options or {}
    ini = ini or {}
    return SimpleNamespace(
        rootpath=tmp_path,
        cache=SimpleNamespace(mkdir=lambda name: tmp_path / ".pytest_cache" / name),
        getoption=lambda name: options.get(name),
        getini=lambda name: ini.get(name, False if name == "pyjs_headed" else ""),
    )


def test_browser_configuration_defaults_preserve_the_system_browser_workflow(tmp_path):
    settings = BrowserTestConfig.from_pytest(pytest_config(tmp_path))

    assert settings == BrowserTestConfig(
        "system",
        False,
        1440,
        1000,
        "system",
        (tmp_path / ".pytest_cache" / "pyjs" / "artifacts").resolve(),
        30,
        10,
    )


def test_browser_configuration_uses_ini_values_and_resolves_artifacts_from_project(tmp_path):
    config = pytest_config(
        tmp_path,
        ini={
            "pyjs_browser": "managed",
            "pyjs_headed": True,
            "pyjs_browser_width": "390",
            "pyjs_browser_height": "844",
            "pyjs_color_scheme": "dark",
            "pyjs_artifacts_dir": "build/browser-artifacts",
            "pyjs_timeout": "12.5",
            "pyjs_retained_iframes": "3",
        },
    )

    settings = BrowserTestConfig.from_pytest(config)

    assert settings == BrowserTestConfig(
        "managed",
        True,
        390,
        844,
        "dark",
        (tmp_path / "build" / "browser-artifacts").resolve(),
        12.5,
        3,
    )


def test_browser_command_line_overrides_ini_values(tmp_path):
    config = pytest_config(
        tmp_path,
        options={
            "--pyjs-browser": "managed",
            "pyjs_headed": False,
            "--pyjs-browser-width": 1280,
        },
        ini={
            "pyjs_browser": "system",
            "pyjs_headed": True,
            "pyjs_browser_width": "390",
        },
    )

    settings = BrowserTestConfig.from_pytest(config)

    assert settings.mode == "managed"
    assert settings.headed is False
    assert settings.width == 1280


def test_managed_only_browser_configuration_is_rejected_for_system_browser(tmp_path):
    config = pytest_config(tmp_path, ini={"pyjs_color_scheme": "dark"})

    with pytest.raises(pytest.UsageError, match="requires pyjs_browser"):
        BrowserTestConfig.from_pytest(config)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("pyjs_browser_width", "0", "positive integer"),
        ("pyjs_timeout", "later", "positive number"),
        ("pyjs_retained_iframes", "-1", "non-negative integer"),
    ],
)
def test_browser_configuration_validates_numeric_values(tmp_path, name, value, message):
    config = pytest_config(tmp_path, ini={name: value})

    with pytest.raises(pytest.UsageError, match=message):
        BrowserTestConfig.from_pytest(config)


def test_daemon_must_match_project_and_cache(tmp_path):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    health = {
        "signature": "signature",
        "project_root": str(project_root),
        "cache_dir": str(cache_dir),
        "artifacts_dir": str(cache_dir / "artifacts"),
    }
    settings = BrowserTestConfig(
        "system",
        False,
        1440,
        1000,
        "system",
        cache_dir / "artifacts",
        30,
        10,
    )

    assert daemon_matches_project(health, "signature", project_root, cache_dir, settings)
    health["reusable"] = False
    assert not daemon_matches_project(health, "signature", project_root, cache_dir, settings)
    health["reusable"] = True
    assert not daemon_matches_project(health, "signature", tmp_path / "other", cache_dir, settings)
    assert not daemon_matches_project(
        health, "signature", project_root, tmp_path / "other-cache", settings
    )
    assert not daemon_matches_project(
        {**health, "browser_mode": "managed"},
        "signature",
        project_root,
        cache_dir,
        settings,
    )


def test_daemon_health_treats_socket_timeout_as_not_ready(monkeypatch):
    def time_out(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr("pyjs.testing.pytest_plugin.urlopen", time_out)

    assert get_daemon_health(8765) is None


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_forced_daemon_shutdown_terminates_its_process_group(monkeypatch):
    calls = []
    monkeypatch.setattr("pyjs.testing.pytest_plugin.os.getpgid", lambda pid: pid)
    monkeypatch.setattr(
        "pyjs.testing.pytest_plugin.os.killpg",
        lambda process_group, shutdown_signal: calls.append(
            (process_group, shutdown_signal)
        ),
    )
    monkeypatch.setattr("pyjs.testing.pytest_plugin.shutil.which", lambda name: None)

    terminate_daemon_process(8765, 123)

    assert calls == [(123, signal.SIGTERM)]


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_forced_daemon_shutdown_does_not_terminate_a_shared_process_group(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr("pyjs.testing.pytest_plugin.os.getpgid", lambda pid: 456)
    monkeypatch.setattr(
        "pyjs.testing.pytest_plugin.os.kill",
        lambda pid, shutdown_signal: calls.append((pid, shutdown_signal)),
    )
    monkeypatch.setattr("pyjs.testing.pytest_plugin.shutil.which", lambda name: None)

    terminate_daemon_process(8765, 123)

    assert calls == [(123, signal.SIGTERM)]


def test_failure_message_includes_managed_browser_artifacts():
    response = {
        "failure_artifacts": {
            "test_app.py::test_fails": {
                "screenshot": "/tmp/failure.png",
                "diagnostics": "/tmp/failure.json",
            }
        }
    }

    message = add_failure_artifacts("AssertionError: boom", response, "test_app.py::test_fails")

    assert "AssertionError: boom" in message
    assert "screenshot: /tmp/failure.png" in message
    assert "diagnostics: /tmp/failure.json" in message


def test_run_failure_names_the_failed_stage():
    response = failed_run("bundle_dispatch", "connection closed")

    assert format_run_failure(response) == (
        "Browser test run failed during bundle dispatch: connection closed"
    )


def test_run_failure_includes_daemon_diagnostics():
    response = failed_run("bundle_build", "cannot compile runner")
    response["daemon_state"] = {"active_browser": False, "pending_runs": 1}
    response["daemon_log_tail"] = "first line\nlast line"

    assert format_run_failure(response) == (
        "Browser test run failed during bundle build: cannot compile runner\n"
        'Daemon state: {"active_browser": false, "pending_runs": 1}\n'
        "Recent daemon log:\n"
        "first line\n"
        "last line"
    )


def test_run_failure_includes_bundle_failure_artifacts():
    response = failed_run("browser_execution", "invalid bundle")
    response["failure_artifacts"] = {
        "<bundle>": {
            "screenshot": "/tmp/bundle.png",
            "diagnostics": "/tmp/bundle.json",
        }
    }

    message = format_run_failure(response)

    assert "Failure artifacts for <bundle>" in message
    assert "screenshot: /tmp/bundle.png" in message
    assert "diagnostics: /tmp/bundle.json" in message


def test_read_log_tail_keeps_only_requested_lines(tmp_path):
    daemon_log = tmp_path / "daemon.log"
    daemon_log.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert read_log_tail(daemon_log, max_lines=2) == "two\nthree"


def test_failed_response_collects_daemon_state_and_log_tail(tmp_path, monkeypatch):
    (tmp_path / "daemon.log").write_text("recent failure\n", encoding="utf-8")
    monkeypatch.setattr(
        "pyjs.testing.pytest_plugin.get_daemon_health",
        lambda port: {
            "pid": 123,
            "active_browser": False,
            "pending_runs": 1,
            "runner_page_error": "excluded duplicate detail",
        },
    )

    response = add_daemon_diagnostics(
        failed_run("bundle_build", "cannot compile runner"),
        8765,
        tmp_path,
    )

    assert response["daemon_state"] == {
        "pid": 123,
        "active_browser": False,
        "pending_runs": 1,
    }
    assert response["daemon_log_tail"] == "recent failure"


def test_control_request_send_has_a_timeout(monkeypatch):
    async def block_send(request):
        await asyncio.Event().wait()

    websocket = SimpleNamespace(send=block_send, recv=AsyncMock())
    monkeypatch.setattr("pyjs.testing.pytest_plugin.CONTROL_SEND_TIMEOUT_SECONDS", 0)

    with pytest.raises(TimeoutError, match="sending test request"):
        asyncio.run(exchange_run_request(websocket, "request"))


def test_run_request_sends_the_suite_once_and_selects_the_current_test(monkeypatch):
    first = SelectedTest("tests/test_app.py::test_one", "tests.test_app", "test_one")
    second = SelectedTest("tests/test_app.py::test_two", "tests.test_app", "test_two")
    websocket = SimpleNamespace(
        send=AsyncMock(),
        recv=AsyncMock(
            return_value='{"type":"run_tests_result","status":"ok","results":[]}'
        ),
    )

    class Connection:
        async def __aenter__(self):
            return websocket

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(
        "pyjs.testing.pytest_plugin.connect",
        lambda *args, **kwargs: Connection(),
    )

    response = asyncio.run(
        send_run_request(8765, second, [first, second], "suite-1")
    )

    assert response == {
        "type": "run_tests_result",
        "status": "ok",
        "results": [],
    }
    request = json.loads(websocket.send.await_args.args[0])
    assert request == {
        "type": "run_tests",
        "suite_id": "suite-1",
        "tests": [first.to_payload(), second.to_payload()],
        "run_nodeids": [second.nodeid],
        "selected_nodeids": [first.nodeid, second.nodeid],
        "current_nodeid": second.nodeid,
    }


def test_control_response_wait_has_a_timeout(monkeypatch):
    async def block_receive():
        await asyncio.Event().wait()

    websocket = SimpleNamespace(send=AsyncMock(), recv=block_receive)
    monkeypatch.setattr("pyjs.testing.pytest_plugin.RUN_RESPONSE_TIMEOUT_SECONDS", 0)

    with pytest.raises(TimeoutError, match="waiting for pyjs daemon response"):
        asyncio.run(exchange_run_request(websocket, "request"))
