import asyncio
import base64
import binascii
import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest
from PIL import Image
from websockets.asyncio.client import ClientConnection, connect

from pyjs.testing.builder import SelectedTest, compute_testing_signature
from pyjs.testing.protocol import failed_run, format_failure_artifact, format_run_failure

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_IDLE_SECONDS = 120
NO_BROWSER_RETRY_SECONDS = 2
CONTROL_CONNECT_TIMEOUT_SECONDS = 10
CONTROL_SEND_TIMEOUT_SECONDS = 10
DAEMON_START_TIMEOUT_SECONDS = 120
RUN_RESPONSE_TIMEOUT_SECONDS = 75
RESPONSE_TIMEOUT_GRACE_SECONDS = 15
DAEMON_LOG_TAIL_LINES = 20
RENDER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_BROWSER_MODE = "system"
DEFAULT_BROWSER_WIDTH = 1440
DEFAULT_BROWSER_HEIGHT = 1000
DEFAULT_COLOR_SCHEME = "system"
DEFAULT_TEST_TIMEOUT_SECONDS = 30.0
DEFAULT_RETAINED_IFRAMES = 10
ANDROID_DEPENDENCY_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class BrowserTestConfig:
    mode: str
    headed: bool
    width: int
    height: int
    color_scheme: str
    artifacts_dir: Path
    timeout: float
    retained_iframes: int

    @classmethod
    def from_pytest(cls, config: pytest.Config) -> BrowserTestConfig:
        mode = str(configured_setting(config, "pyjs_browser", DEFAULT_BROWSER_MODE))
        color_scheme = str(configured_setting(config, "pyjs_color_scheme", DEFAULT_COLOR_SCHEME))
        if mode not in {"system", "managed"}:
            raise pytest.UsageError("pyjs_browser must be 'system' or 'managed'")
        if color_scheme not in {"system", "light", "dark"}:
            raise pytest.UsageError("pyjs_color_scheme must be 'system', 'light', or 'dark'")

        headed = bool(configured_setting(config, "pyjs_headed", False, "pyjs_headed"))
        if mode == "system" and headed:
            raise pytest.UsageError("pyjs_headed requires pyjs_browser = 'managed'")
        if mode == "system" and color_scheme != "system":
            raise pytest.UsageError("pyjs_color_scheme requires pyjs_browser = 'managed'")

        width = positive_int(
            "pyjs_browser_width",
            configured_setting(config, "pyjs_browser_width", DEFAULT_BROWSER_WIDTH),
        )
        height = positive_int(
            "pyjs_browser_height",
            configured_setting(config, "pyjs_browser_height", DEFAULT_BROWSER_HEIGHT),
        )
        timeout = positive_float(
            "pyjs_timeout",
            configured_setting(config, "pyjs_timeout", DEFAULT_TEST_TIMEOUT_SECONDS),
        )
        retained_iframes = nonnegative_int(
            "pyjs_retained_iframes",
            configured_setting(config, "pyjs_retained_iframes", DEFAULT_RETAINED_IFRAMES),
        )
        return cls(
            mode,
            headed,
            width,
            height,
            color_scheme,
            artifact_directory(config),
            timeout,
            retained_iframes,
        )


def configured_setting(
    config: pytest.Config,
    name: str,
    default: object,
    option_name: str | None = None,
) -> object:
    option_name = option_name or "--" + name.replace("_", "-")
    option_value = config.getoption(option_name)
    if option_value is not None:
        return option_value
    ini_value = config.getini(name)
    if ini_value not in {None, ""}:
        return ini_value
    return default


def artifact_directory(config: pytest.Config) -> Path:
    project_root = Path(str(config.rootpath)).resolve()
    default = Path(str(config.cache.mkdir("pyjs"))).resolve() / "artifacts"
    configured = configured_setting(config, "pyjs_artifacts_dir", default)
    directory = Path(str(configured)).expanduser()
    if not directory.is_absolute():
        directory = project_root / directory
    return directory.resolve()


def positive_int(name: str, value: object) -> int:
    try:
        parsed = int(value)
    except TypeError, ValueError:
        raise pytest.UsageError(f"{name} must be a positive integer") from None
    if parsed <= 0:
        raise pytest.UsageError(f"{name} must be a positive integer")
    return parsed


def nonnegative_int(name: str, value: object) -> int:
    try:
        parsed = int(value)
    except TypeError, ValueError:
        raise pytest.UsageError(f"{name} must be a non-negative integer") from None
    if parsed < 0:
        raise pytest.UsageError(f"{name} must be a non-negative integer")
    return parsed


def positive_float(name: str, value: object) -> float:
    try:
        parsed = float(value)
    except TypeError, ValueError:
        raise pytest.UsageError(f"{name} must be a positive number") from None
    if parsed <= 0:
        raise pytest.UsageError(f"{name} must be a positive number")
    return parsed


def browser_test_config(config: pytest.Config) -> BrowserTestConfig:
    settings = getattr(config, "_pyjs_browser_test_config", None)
    if settings is None:
        settings = BrowserTestConfig.from_pytest(config)
        config._pyjs_browser_test_config = settings
    return settings


class BrowserResults:
    def __init__(self) -> None:
        self.suite_id = uuid.uuid4().hex
        self.eligible_tests: list[SelectedTest] | None = None


class AndroidJVMResults:
    def __init__(self) -> None:
        self.suite_id = uuid.uuid4().hex
        self.eligible_tests: list[SelectedTest] | None = None
        self.results = None


def add_failure_artifacts(error: str, response: dict[str, Any], nodeid: str) -> str:
    failure_artifacts = response.get("failure_artifacts")
    artifact = failure_artifacts.get(nodeid) if isinstance(failure_artifacts, dict) else None
    details = format_failure_artifact(artifact)
    if details is None:
        return error
    return error + "\nFailure artifacts: " + details


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("pyjs")
    group.addoption(
        "--pyjs-target",
        choices=["python", "web", "android"],
        default=None,
        help="Run ordinary Python tests, web tests, or opt-in Android device tests.",
    )
    group.addoption(
        "--pyjs-android-avd",
        default=None,
        help="Android virtual device to start when no emulator is already running.",
    )
    group.addoption(
        "--pyjs-android-headless",
        action="store_true",
        help="Start a managed Android emulator without a window or audio.",
    )
    group.addoption(
        "--pyjs-android-runtime",
        choices=["host", "robolectric", "device"],
        default=None,
        help="Run host-driven, Robolectric, or compiled device Android tests.",
    )
    group.addoption(
        "--pyjs-android-graphics",
        choices=["native", "legacy"],
        default="native",
        help="Robolectric graphics: native Android metrics or legacy fakes.",
    )
    group.addoption(
        "--pyjs-android-api",
        type=int,
        default=35,
        help="Android API used to compile and execute JVM Android tests.",
    )
    group.addoption(
        "--pyjs-android-timeout",
        type=float,
        default=120,
        help="Seconds allowed for one compiled Android test suite.",
    )
    group.addoption(
        "--pyjs-daemon-port",
        type=int,
        default=DEFAULT_PORT,
        help="Port for the PyJS test daemon.",
    )
    group.addoption(
        "--pyjs-daemon-idle-seconds",
        type=int,
        default=DEFAULT_IDLE_SECONDS,
        help="How long an idle PyJS test daemon stays alive. Use 0 to disable auto-shutdown.",
    )
    group.addoption(
        "--pyjs-update-renders",
        action="store_true",
        help="Create or replace expected web-render images.",
    )
    group.addoption(
        "--pyjs-browser",
        choices=["system", "managed"],
        default=None,
        help="Use the system browser runner or a PyJS-managed Chrome instance.",
    )
    group.addoption(
        "--pyjs-headed",
        dest="pyjs_headed",
        action="store_true",
        default=None,
        help="Show the managed Chrome window instead of running it headlessly.",
    )
    group.addoption(
        "--pyjs-headless",
        dest="pyjs_headed",
        action="store_false",
        default=None,
        help="Run managed Chrome headlessly, overriding pyjs_headed.",
    )
    group.addoption(
        "--pyjs-browser-width",
        type=int,
        default=None,
        help="Managed-browser viewport width.",
    )
    group.addoption(
        "--pyjs-browser-height",
        type=int,
        default=None,
        help="Managed-browser viewport height.",
    )
    group.addoption(
        "--pyjs-color-scheme",
        choices=["system", "light", "dark"],
        default=None,
        help="Emulate a color scheme in managed Chrome.",
    )
    group.addoption(
        "--pyjs-artifacts-dir",
        type=Path,
        default=None,
        help="Directory for failure screenshots, diagnostics, and render diffs.",
    )
    group.addoption(
        "--pyjs-timeout",
        type=float,
        default=None,
        help="Seconds to wait for one browser test result.",
    )
    group.addoption(
        "--pyjs-retained-iframes",
        type=int,
        default=None,
        help="Maximum number of rendered previews retained by the runner.",
    )

    parser.addini("pyjs_browser", "Browser runner mode: system or managed.", default="")
    parser.addini("pyjs_headed", "Show managed Chrome instead of running headlessly.", type="bool")
    parser.addini("pyjs_browser_width", "Managed-browser viewport width.", default="")
    parser.addini("pyjs_browser_height", "Managed-browser viewport height.", default="")
    parser.addini("pyjs_color_scheme", "Managed-browser color scheme.", default="")
    parser.addini("pyjs_artifacts_dir", "Directory for generated test artifacts.", default="")
    parser.addini("pyjs_timeout", "Browser test execution timeout in seconds.", default="")
    parser.addini(
        "pyjs_android_dependency_sets",
        "Named checksum-locked Android application dependencies (NAME=PATH).",
        type="linelist",
        default=[],
    )
    parser.addini(
        "pyjs_retained_iframes",
        "Maximum number of rendered test previews retained by the runner.",
        default="",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "pyjs_web: run a test only with --pyjs-target=web",
    )
    config.addinivalue_line(
        "markers",
        "pyjs_python: exclude a test from the pyjs web target",
    )
    config.addinivalue_line(
        "markers",
        "pyjs_android: run a test only with --pyjs-target=android",
    )
    config.addinivalue_line(
        "markers",
        "pyjs_android_jvm: compile a test for Robolectric or AndroidJUnitRunner",
    )
    config.addinivalue_line(
        "markers",
        "pyjs_android_device: require AndroidJUnitRunner instead of Robolectric",
    )
    config.addinivalue_line(
        "markers",
        "pyjs_android_dependencies(*sets): package application dependency sets",
    )
    config._pyjs_web_results = BrowserResults()
    config._pyjs_android_jvm_results = AndroidJVMResults()
    if config.getoption("--pyjs-target") == "web":
        config._pyjs_browser_test_config = BrowserTestConfig.from_pytest(config)


def selected_test_from_item(item: pytest.Function) -> SelectedTest:
    if item.cls is not None:
        raise ValueError(
            f"Compiled targets support module-level test functions, not {item.nodeid}"
        )
    function_name = getattr(item, "originalname", None) or item.name
    dependencies = []
    iter_markers = getattr(item, "iter_markers", lambda _name: ())
    for marker in iter_markers("pyjs_android_dependencies"):
        if marker.kwargs or any(not isinstance(value, str) for value in marker.args):
            raise pytest.UsageError(
                "pyjs_android_dependencies accepts dependency-set names as "
                "positional strings"
            )
        dependencies.extend(marker.args)
    return SelectedTest(
        nodeid=item.nodeid,
        module_name=item.module.__name__,
        function_name=function_name,
        android_dependencies=tuple(dict.fromkeys(dependencies)),
    )


def is_web_test(item: pytest.Item) -> bool:
    return (
        item.get_closest_marker("pyjs_web") is not None
        and item.get_closest_marker("pyjs_python") is None
        and item.get_closest_marker("pyjs_android") is None
        and item.get_closest_marker("pyjs_android_jvm") is None
    )


def is_android_jvm_test(item: pytest.Item) -> bool:
    return item.get_closest_marker("pyjs_android_jvm") is not None


def is_android_jvm_test_for_runtime(item: pytest.Item, runtime: str) -> bool:
    return is_android_jvm_test(item) and (
        runtime == "device"
        or item.get_closest_marker("pyjs_android_device") is None
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    target = item.config.getoption("--pyjs-target")
    android_test = item.get_closest_marker("pyjs_android") is not None
    android_jvm_test = is_android_jvm_test(item)
    android_runtime = item.config.getoption("--pyjs-android-runtime") or "host"
    if (
        target == "android"
        and android_runtime == "robolectric"
        and item.get_closest_marker("pyjs_android_device") is not None
    ):
        pytest.skip("device-only Android test")
    if target == "android" and android_runtime == "host" and not android_test:
        pytest.skip("not a host-driven Android test")
    if target == "android" and android_runtime != "host" and not android_jvm_test:
        pytest.skip("not a compiled Android test")
    if target != "android" and (android_test or android_jvm_test):
        pytest.skip("Android-only test")
    if target != "web" and item.get_closest_marker("pyjs_web") is not None:
        pytest.skip("web-only test")
    if target == "web" and not is_web_test(item):
        pytest.skip("not a web test")


@pytest.fixture
def pyjs_artifacts_dir(request: pytest.FixtureRequest) -> Path:
    return artifact_directory(request.config)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> object | None:
    target = pyfuncitem.config.getoption("--pyjs-target")
    if target == "android" and is_android_jvm_test(pyfuncitem):
        return run_android_jvm_item(pyfuncitem)
    if target != "web":
        return None

    state: BrowserResults = pyfuncitem.config._pyjs_web_results
    try:
        if state.eligible_tests is None:
            state.eligible_tests = [
                selected_test_from_item(item)
                for item in pyfuncitem.session.items
                if isinstance(item, pytest.Function) and is_web_test(item)
            ]
        response = run_browser_target(
            pyfuncitem.config,
            selected_test_from_item(pyfuncitem),
            state.eligible_tests,
            state.suite_id,
        )
    except pytest.UsageError:
        raise
    except Exception as exc:
        pytest.fail(str(exc), pytrace=False)
    if response["status"] != "ok":
        pytest.fail(format_run_failure(response), pytrace=False)
    response_error = validate_browser_response(response["results"], [pyfuncitem.nodeid])
    if response_error is not None:
        error = format_run_failure(failed_run("result_transport", response_error))
        pytest.fail(error, pytrace=False)
    result = response["results"][0]
    if result["outcome"] == "passed":
        render_error = verify_render_artifacts(pyfuncitem, result.get("artifacts", []))
        if render_error is not None:
            pytest.fail(render_error, pytrace=False)
        return True
    error = result.get("error", f"Browser test failed: {pyfuncitem.nodeid}")
    error = add_failure_artifacts(error, response, pyfuncitem.nodeid)
    pytest.fail(error, pytrace=False)


def run_android_jvm_item(pyfuncitem: pytest.Function) -> bool | None:
    config = pyfuncitem.config
    runtime = config.getoption("--pyjs-android-runtime") or "host"
    if runtime not in {"robolectric", "device"}:
        return None
    state: AndroidJVMResults = config._pyjs_android_jvm_results
    try:
        if state.eligible_tests is None:
            state.eligible_tests = [
                selected_test_from_item(item)
                for item in pyfuncitem.session.items
                if isinstance(item, pytest.Function)
                and is_android_jvm_test_for_runtime(item, runtime)
            ]
        if state.results is None:
            run = (
                run_robolectric_target
                if runtime == "robolectric"
                else run_android_device_target
            )
            state.results = run(config, state.eligible_tests, state.suite_id)
        result = state.results[pyfuncitem.nodeid]
    except pytest.UsageError:
        raise
    except Exception as exc:
        if state.eligible_tests is not None:
            from pyjs.testing.android_runtime import AndroidTestResult

            state.results = {
                test.nodeid: AndroidTestResult("failed", str(exc))
                for test in state.eligible_tests
            }
        pytest.fail(str(exc), pytrace=False)
    if result.outcome == "passed":
        return True
    pytest.fail(result.error or f"Android test failed: {pyfuncitem.nodeid}", pytrace=False)


def run_robolectric_target(
    config: pytest.Config,
    selected_tests: list[SelectedTest],
    suite_id: str,
):
    from pyjs.android.api import AndroidAPI
    from pyjs.android.dependencies import resolve_android_dependency_locks
    from pyjs.testing.android_jvm import AndroidJVMSuiteBuilder
    from pyjs.testing.android_runtime import AndroidRuntimeResolver, RobolectricRunner
    from pyjs.tooling.android import AndroidSDK
    from pyjs.tooling.android_jvm import AndroidResourceLinker

    api = positive_int("pyjs_android_api", config.getoption("--pyjs-android-api"))
    timeout = positive_float(
        "pyjs_android_timeout",
        config.getoption("--pyjs-android-timeout"),
    )
    project_root = Path(str(config.rootpath)).resolve()
    cache = Path(str(config.cache.mkdir("pyjs"))).resolve()
    shared_cache = Path(
        os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
    ) / "pyjs" / "android-test"
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    progress = reporter.write_line if reporter is not None else None
    sdk = AndroidSDK()
    android = AndroidAPI.from_sdk(api, sdk)
    runtime = AndroidRuntimeResolver(shared_cache, progress).resolve(api)
    dependency_locks = android_dependency_locks(config)
    dependency_sets = android_dependency_sets(
        selected_tests,
        frozenset(dependency_locks),
    )
    dependencies = None
    if dependency_sets:
        selected_locks = tuple(
            (name, dependency_locks[name]) for name in sorted(dependency_sets)
        )
        dependencies = resolve_android_dependency_locks(
            shared_cache / "application",
            selected_locks,
            progress,
        )
    compilation = AndroidJVMSuiteBuilder(project_root, cache).build(
        selected_tests,
        suite_id,
        api=api,
    )
    if dependencies is not None:
        compilation = replace(
            compilation,
            resources=(*compilation.resources, *dependencies.jars),
        )
    runner = RobolectricRunner(
        sdk.java_home / "bin" / "java",
        sdk.build_tool("aapt2"),
        android.android_jar,
        runtime,
        api,
        resource_linker=AndroidResourceLinker(sdk),
        dependencies=dependencies,
        graphics_mode=config.getoption("--pyjs-android-graphics"),
    )
    return runner.run(
        compilation,
        cache / "android-jvm" / suite_id / "classes",
        timeout=timeout,
    )


def android_dependency_sets(
    selected_tests: list[SelectedTest],
    available: frozenset[str] = frozenset({"androidx"}),
) -> frozenset[str]:
    values = frozenset(
        dependency
        for selected in selected_tests
        for dependency in selected.android_dependencies
    )
    unknown = values - available
    if unknown:
        names = ", ".join(repr(name) for name in sorted(unknown))
        raise pytest.UsageError(f"unknown Android dependency set: {names}")
    return values


def android_dependency_locks(config: pytest.Config) -> dict[str, Path]:
    from pyjs.android.dependencies import ANDROIDX_RUNTIME_LOCK

    result = {"androidx": ANDROIDX_RUNTIME_LOCK}
    for entry in config.getini("pyjs_android_dependency_sets"):
        name, separator, path = entry.partition("=")
        name = name.strip()
        path = path.strip()
        if not separator or ANDROID_DEPENDENCY_NAME.fullmatch(name) is None or not path:
            raise pytest.UsageError(
                "pyjs_android_dependency_sets entries must use NAME=PATH with "
                "a lowercase dependency-set name"
            )
        if name in result:
            raise pytest.UsageError(f"duplicate Android dependency set: {name!r}")
        lock = Path(path)
        if not lock.is_absolute():
            lock = Path(str(config.rootpath)) / lock
        lock = lock.resolve()
        if not lock.is_file():
            raise pytest.UsageError(
                f"Android dependency lock for {name!r} was not found at {lock}"
            )
        result[name] = lock
    return result


def run_android_device_target(
    config: pytest.Config,
    selected_tests: list[SelectedTest],
    suite_id: str,
):
    from pyjs.android.api import AndroidAPI
    from pyjs.android.dependencies import resolve_android_dependency_locks
    from pyjs.testing.android_device import (
        AndroidDeviceTestBuilder,
        AndroidDeviceTestRunner,
    )
    from pyjs.testing.android_jvm import AndroidJVMSuiteBuilder
    from pyjs.testing.android_runtime import AndroidRuntimeResolver
    from pyjs.tooling.android import AndroidSDK

    api = positive_int("pyjs_android_api", config.getoption("--pyjs-android-api"))
    timeout = positive_float(
        "pyjs_android_timeout",
        config.getoption("--pyjs-android-timeout"),
    )
    project_root = Path(str(config.rootpath)).resolve()
    cache = Path(str(config.cache.mkdir("pyjs"))).resolve()
    shared_cache = Path(
        os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
    ) / "pyjs" / "android-test"
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    progress = reporter.write_line if reporter is not None else None
    sdk = AndroidSDK()
    android = AndroidAPI.from_sdk(api, sdk)
    dependency_locks = android_dependency_locks(config)
    dependency_sets = android_dependency_sets(
        selected_tests,
        frozenset(dependency_locks),
    )
    runtime = AndroidRuntimeResolver(shared_cache, progress).resolve_device()
    dependencies = None
    if dependency_sets:
        selected_locks = tuple(
            (name, dependency_locks[name]) for name in sorted(dependency_sets)
        )
        dependencies = resolve_android_dependency_locks(
            shared_cache / "application",
            selected_locks,
            progress,
        )
    compilation = AndroidJVMSuiteBuilder(project_root, cache).build(
        selected_tests,
        suite_id,
        api=api,
        robolectric=False,
    )
    output = cache / "android-device" / suite_id
    packages = AndroidDeviceTestBuilder(
        sdk,
        android.android_jar,
        runtime,
        api,
        dependencies=dependencies,
    ).build(compilation, output)
    device = sdk.ensure_emulator(
        config.getoption("--pyjs-android-avd"),
        headless=config.getoption("--pyjs-android-headless"),
    )
    return AndroidDeviceTestRunner(sdk, device).run(
        compilation,
        packages,
        timeout=timeout,
    )


def verify_render_artifacts(item: pytest.Function, artifacts: list[dict[str, Any]]) -> str | None:
    for artifact in artifacts:
        error = verify_render_artifact(item, artifact)
        if error is not None:
            return error
    return None


def verify_render_artifact(item: pytest.Function, artifact: dict[str, Any]) -> str | None:
    name = artifact.get("name")
    if not isinstance(name, str) or RENDER_NAME_PATTERN.fullmatch(name) is None:
        return "Render artifact names may contain only letters, numbers, underscores, and hyphens."
    if error := artifact.get("error"):
        return f"Could not capture render artifact {name!r}: {error}"

    try:
        actual = decode_render_image(artifact.get("dataUrl"))
    except ValueError as exc:
        return f"Invalid render artifact {name!r}: {exc}"

    expected_path = Path(str(item.path)).parent / "renders" / f"{name}.png"
    if item.config.getoption("--pyjs-update-renders"):
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        actual.save(expected_path)
        return None
    if not expected_path.exists():
        return (
            f"Missing expected render {expected_path}. "
            "Run pytest with --pyjs-update-renders to create it."
        )

    with Image.open(expected_path) as image:
        expected = image.convert("RGBA")
    if actual.size != expected.size:
        return render_failure(
            item,
            name,
            actual,
            None,
            f"size {actual.size}, expected {expected.size}",
            artifact.get("diagnostics"),
        )

    threshold = artifact.get("pixelThreshold", 8)
    allowed_ratio = artifact.get("maxDifferentPixelRatio", 0.01)
    if not isinstance(threshold, (int, float)) or not isinstance(allowed_ratio, (int, float)):
        return f"Invalid comparison settings for render artifact {name!r}."

    different = 0
    diff = Image.new("RGBA", actual.size, (0, 0, 0, 255))
    diff_pixels = []
    for actual_pixel, expected_pixel in zip(
        actual.get_flattened_data(), expected.get_flattened_data(), strict=True
    ):
        channel_difference = max(
            abs(actual_channel - expected_channel)
            for actual_channel, expected_channel in zip(actual_pixel, expected_pixel, strict=True)
        )
        if channel_difference > threshold:
            different += 1
            diff_pixels.append((255, 0, 255, 255))
        else:
            diff_pixels.append((0, 0, 0, 255))
    diff.putdata(diff_pixels)

    total = actual.width * actual.height
    ratio = different / total
    if ratio <= allowed_ratio:
        return None
    detail = f"{different}/{total} pixels differ ({ratio:.2%}); allowed {allowed_ratio:.2%}"
    return render_failure(
        item,
        name,
        actual,
        diff,
        detail,
        artifact.get("diagnostics"),
    )


def decode_render_image(data_url: object) -> Image.Image:
    prefix = "data:image/png;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ValueError("expected a base64-encoded PNG data URL")
    try:
        raw_image = base64.b64decode(data_url[len(prefix) :], validate=True)
        with Image.open(io.BytesIO(raw_image)) as image:
            return image.convert("RGBA")
    except (binascii.Error, OSError) as exc:
        raise ValueError("could not decode PNG data") from exc


def render_failure(
    item: pytest.Function,
    name: str,
    actual: Image.Image,
    diff: Image.Image | None,
    detail: str,
    diagnostics: object = None,
) -> str:
    output_dir = browser_test_config(item.config).artifacts_dir / "renders"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", item.nodeid).strip("-")
    actual_path = output_dir / f"{stem}-{name}-actual.png"
    actual.save(actual_path)
    paths = f"actual: {actual_path}"
    if diff is not None:
        diff_path = output_dir / f"{stem}-{name}-diff.png"
        diff.save(diff_path)
        paths += f", diff: {diff_path}"
    if isinstance(diagnostics, str) and diagnostics:
        diagnostics_path = output_dir / f"{stem}-{name}-diagnostics.txt"
        diagnostics_path.write_text(diagnostics + "\n")
        paths += f", diagnostics: {diagnostics_path}"
        detail += f"; WebGPU diagnostics: {diagnostics}"
    return f"Render artifact {name!r} does not match: {detail} ({paths})"


def validate_browser_response(
    results: list[dict[str, Any]], expected_nodeids: list[str]
) -> str | None:
    bundle_result = next((result for result in results if result.get("nodeid") == "<bundle>"), None)
    if bundle_result is not None and bundle_result.get("outcome") != "passed":
        return bundle_result.get(
            "error", "Browser bundle failed before individual test results were reported"
        )

    returned_nodeids = [
        result.get("nodeid") for result in results if isinstance(result.get("nodeid"), str)
    ]
    missing = [nodeid for nodeid in expected_nodeids if nodeid not in returned_nodeids]
    unexpected = [nodeid for nodeid in returned_nodeids if nodeid not in expected_nodeids]
    if not missing and not unexpected:
        return None

    details: list[str] = ["Browser returned a mismatched test result set."]
    if missing:
        details.append(f"Missing: {', '.join(missing)}")
    if unexpected:
        details.append(f"Unexpected: {', '.join(unexpected)}")
    details.append(
        "If this happened after changing the testing prototype, restart the browser runner page and let pytest start a fresh daemon."
    )
    return "\n".join(details)


def run_browser_target(
    config: pytest.Config,
    current_test: SelectedTest,
    selected_tests: list[SelectedTest],
    suite_id: str,
) -> dict[str, Any]:
    port = config.getoption("--pyjs-daemon-port")
    idle_seconds = config.getoption("--pyjs-daemon-idle-seconds")
    project_root = Path(str(config.rootpath)).resolve()
    cache_dir = Path(str(config.cache.mkdir("pyjs"))).resolve()
    settings = browser_test_config(config)
    testing_signature = getattr(config, "_pyjs_testing_signature", None)
    if testing_signature is None:
        testing_signature = compute_testing_signature()
        config._pyjs_testing_signature = testing_signature
    try:
        ensure_daemon_running(
            port,
            idle_seconds,
            project_root,
            cache_dir,
            settings,
            testing_signature,
        )
        response = asyncio.run(
            send_run_request(
                port,
                current_test,
                selected_tests,
                suite_id,
                settings.timeout,
            )
        )
    except Exception as exc:
        response = failed_run("result_transport", str(exc))
    if response.get("stage") == "browser_connection":
        time.sleep(NO_BROWSER_RETRY_SECONDS)
        try:
            response = asyncio.run(
                send_run_request(
                    port,
                    current_test,
                    selected_tests,
                    suite_id,
                    settings.timeout,
                )
            )
        except Exception as exc:
            response = failed_run("result_transport", str(exc))
    return add_daemon_diagnostics(response, port, cache_dir)


def read_log_tail(path: Path, max_lines: int = DAEMON_LOG_TAIL_LINES) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as logfile:
            return "".join(deque(logfile, maxlen=max_lines)).rstrip()
    except OSError:
        return ""


def add_daemon_diagnostics(
    response: dict[str, Any],
    port: int,
    cache_dir: Path,
) -> dict[str, Any]:
    if response.get("status") != "failed":
        return response

    health = get_daemon_health(port)
    if health is not None:
        state_keys = (
            "pid",
            "active_browser",
            "browser_mode",
            "browser_width",
            "browser_height",
            "color_scheme",
            "artifacts_dir",
            "test_timeout",
            "retained_iframes",
            "current_run_id",
            "reusable",
            "pending_runs",
            "last_activity_seconds_ago",
            "browser_exceptions",
            "browser_console",
        )
        response["daemon_state"] = {key: health[key] for key in state_keys if key in health}
    log_tail = read_log_tail(cache_dir / "daemon.log")
    if log_tail:
        response["daemon_log_tail"] = log_tail
    return response


def daemon_matches_project(
    health: dict[str, Any] | None,
    signature: str,
    project_root: Path,
    cache_dir: Path,
    settings: BrowserTestConfig,
) -> bool:
    return (
        health is not None
        and health.get("reusable", True) is True
        and health.get("signature") == signature
        and health.get("project_root") == str(project_root)
        and health.get("cache_dir") == str(cache_dir)
        and health.get("browser_mode", DEFAULT_BROWSER_MODE) == settings.mode
        and health.get("headed", False) == settings.headed
        and health.get("browser_width", DEFAULT_BROWSER_WIDTH) == settings.width
        and health.get("browser_height", DEFAULT_BROWSER_HEIGHT) == settings.height
        and health.get("color_scheme", DEFAULT_COLOR_SCHEME) == settings.color_scheme
        and health.get("artifacts_dir") == str(settings.artifacts_dir)
        and health.get("test_timeout", DEFAULT_TEST_TIMEOUT_SECONDS) == settings.timeout
        and health.get("retained_iframes", DEFAULT_RETAINED_IFRAMES) == settings.retained_iframes
    )


def ensure_daemon_running(
    port: int,
    idle_seconds: int,
    project_root: Path,
    cache_dir: Path,
    settings: BrowserTestConfig,
    expected_signature: str,
) -> None:
    health = get_daemon_health(port)
    if daemon_matches_project(
        health,
        expected_signature,
        project_root,
        cache_dir,
        settings,
    ):
        return
    if health is not None:
        restart_daemon(port, health)

    cache_dir.mkdir(parents=True, exist_ok=True)
    daemon_log = cache_dir / "daemon.log"
    environment = os.environ.copy()
    python_paths = [str(project_root), *(path for path in sys.path if path)]
    environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(python_paths))
    with daemon_log.open("a", encoding="utf-8") as logfile:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pyjs.testing.daemon",
                "--host",
                HOST,
                "--port",
                str(port),
                "--idle-seconds",
                str(idle_seconds),
                "--project-root",
                str(project_root),
                "--cache-dir",
                str(cache_dir),
                "--browser-mode",
                settings.mode,
                "--browser-width",
                str(settings.width),
                "--browser-height",
                str(settings.height),
                "--color-scheme",
                settings.color_scheme,
                "--artifacts-dir",
                str(settings.artifacts_dir),
                "--test-timeout",
                str(settings.timeout),
                "--retained-iframes",
                str(settings.retained_iframes),
                *(["--headed"] if settings.headed else []),
            ],
            cwd=project_root,
            env=environment,
            stdout=logfile,
            stderr=logfile,
            start_new_session=True,
        )

    # Readiness includes cold runner compilation, not just binding the socket.
    deadline = time.monotonic() + DAEMON_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"PyJS daemon exited during startup:\n{read_log_tail(daemon_log)}")
        health = get_daemon_health(port)
        if daemon_matches_project(
            health,
            expected_signature,
            project_root,
            cache_dir,
            settings,
        ):
            return
        time.sleep(0.1)
    raise RuntimeError(f"Timed out starting pyjs daemon on port {port}")


def daemon_is_running(port: int) -> bool:
    return get_daemon_health(port) is not None


def get_daemon_health(port: int) -> dict[str, Any] | None:
    try:
        with urlopen(f"http://{HOST}:{port}/healthz", timeout=0.5) as response:
            if response.status != 200:
                return None
            payload = response.read().decode("utf-8")
    except OSError, URLError:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"status": "ok", "legacy": True}


def restart_daemon(port: int, health: dict[str, Any]) -> None:
    request_daemon_shutdown(port)
    if wait_for_daemon_stop(port, timeout_seconds=3):
        return
    terminate_daemon_process(port, health.get("pid"))
    if wait_for_daemon_stop(port, timeout_seconds=3):
        return
    raise RuntimeError(f"Timed out stopping stale pyjs daemon on port {port}")


def request_daemon_shutdown(port: int) -> None:
    try:
        request = Request(f"http://{HOST}:{port}/shutdown")
        with urlopen(request, timeout=0.5):
            return
    except URLError:
        return


def wait_for_daemon_stop(port: int, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if get_daemon_health(port) is None:
            return True
        time.sleep(0.1)
    return get_daemon_health(port) is None


def terminate_daemon_process(port: int, pid: Any) -> None:
    if isinstance(pid, int):
        with contextlib.suppress(ProcessLookupError):
            if os.name == "posix":
                process_group = os.getpgid(pid)
                if process_group == pid:
                    os.killpg(process_group, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
    lsof = shutil.which("lsof")
    if not lsof:
        return
    completed = subprocess.run(
        [lsof, "-ti", f"tcp:{port}"],
        capture_output=True,
        text=True,
        check=False,
    )
    for raw_pid in completed.stdout.splitlines():
        raw_pid = raw_pid.strip()
        if not raw_pid:
            continue
        with contextlib.suppress(ProcessLookupError, ValueError):
            os.kill(int(raw_pid), signal.SIGTERM)


async def send_run_request(
    port: int,
    current_test: SelectedTest,
    selected_tests: list[SelectedTest],
    suite_id: str,
    test_timeout: float = DEFAULT_TEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = f"ws://{HOST}:{port}/control"
    request = json.dumps(
        {
            "type": "run_tests",
            "suite_id": suite_id,
            "tests": [test.to_payload() for test in selected_tests],
            "run_nodeids": [current_test.nodeid],
            "selected_nodeids": [test.nodeid for test in selected_tests],
            "current_nodeid": current_test.nodeid,
        }
    )
    async with connect(url, open_timeout=CONTROL_CONNECT_TIMEOUT_SECONDS) as websocket:
        response_timeout = max(
            RUN_RESPONSE_TIMEOUT_SECONDS,
            test_timeout + RESPONSE_TIMEOUT_GRACE_SECONDS,
        )
        raw_response = await exchange_run_request(websocket, request, response_timeout)
    return json.loads(raw_response)


async def exchange_run_request(
    websocket: ClientConnection,
    request: str,
    response_timeout: float | None = None,
) -> str | bytes:
    try:
        await asyncio.wait_for(
            websocket.send(request),
            timeout=CONTROL_SEND_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise TimeoutError("Timed out sending test request to pyjs daemon") from exc
    try:
        return await asyncio.wait_for(
            websocket.recv(),
            timeout=RUN_RESPONSE_TIMEOUT_SECONDS if response_timeout is None else response_timeout,
        )
    except TimeoutError as exc:
        raise TimeoutError("Timed out waiting for pyjs daemon response") from exc
