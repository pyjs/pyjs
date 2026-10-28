import asyncio
import json
import threading
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, Mock

import pytest

from pyjs.analysis.diagnostics import SourceFile
from pyjs.javascript.sourcemap import SourceMap, SourceMapping
from pyjs.testing.builder import BrowserBundle
from pyjs.testing.daemon import PrototypeDaemon
from pyjs.testing.protocol import RunFailureStage
from pyjs.tooling.node import Node
from pyjs.tooling.npm import NpmImport, NpmPackage

BUNDLE = BrowserBundle("bundle", "")


def make_daemon(tmp_path):
    return PrototypeDaemon("127.0.0.1", 8765, 0, tmp_path, tmp_path / "cache")


def run_tests(daemon):
    return asyncio.run(daemon._handle_run_tests({"tests": []}))


@pytest.mark.parametrize("disconnect", [False, True])
def test_compilation_keeps_control_pings_and_runner_builds_responsive(tmp_path, monkeypatch, disconnect):
    from websockets.asyncio.client import connect

    from pyjs.server.dev import Application, Server

    daemon = make_daemon(tmp_path)
    building = threading.Event()
    release = threading.Event()
    runner_built = threading.Event()

    def build(*args):
        building.set()
        assert release.wait(5), "compilation blocked the control connection"
        return BUNDLE

    def runner_components():
        assert release.is_set(), "runner compilation overlapped test imports"
        runner_built.set()
        return "", ""

    async def send_result(raw):
        daemon.pending_results[json.loads(raw)["run_id"]].set_result([])

    daemon.bundle_builder.build = build
    daemon.ensure_browser_connection = AsyncMock(return_value=SimpleNamespace(send=send_result))
    monkeypatch.setattr("pyjs.testing.daemon.build_runner_components", runner_components)

    async def scenario():
        app = Application()
        app.websocket("/control")(daemon.handler)
        server = Server(app, port=0, quiet=True)
        await server.start_async()
        try:
            async with connect(app.websocket_url.rstrip("/") + "/control") as client:
                await client.send(json.dumps({"type": "run_tests", "tests": []}))
                assert await asyncio.to_thread(building.wait, 2)
                runner = asyncio.create_task(daemon.runner_page(request()))
                pong = await client.ping()
                await asyncio.wait_for(pong, 2)
                assert not runner_built.is_set()
                await client.send(json.dumps({"type": "run_tests", "tests": []}))
                busy = json.loads(await asyncio.wait_for(client.recv(), 2))
                assert busy["stage"] == "busy"
                assert busy["stage"] in get_args(RunFailureStage.__value__)
                if disconnect:
                    await client.close()
                    await asyncio.wait_for(daemon.run_lock.acquire(), 2)
                    daemon.run_lock.release()
                    assert daemon.pending_results == {}
                    assert daemon.reusable is False
                release.set()
                if not disconnect:
                    result = json.loads(await asyncio.wait_for(client.recv(), 2))
                    assert result["status"] == "ok", result
                assert (await runner).status == 200
                assert runner_built.is_set()
        finally:
            release.set()
            await server.close_async()

    asyncio.run(scenario())


def request(path="/", query=None):
    from pyjs.server.dev import Request

    return Request("GET", path, path, query or {}, {}, b"")


@pytest.mark.parametrize("build_failure", [False, True])
def test_startup_prepares_runner_before_listening_and_reuses_page(tmp_path, monkeypatch, build_failure):
    from urllib.request import urlopen

    from pyjs.server.dev import Server
    from pyjs.testing.daemon import async_main

    building, release = threading.Event(), threading.Event()
    servers, builds = [], []

    def components():
        builds.append(1)
        building.set()
        assert release.wait(5)
        if build_failure:
            raise ValueError("invalid runner code")
        return "// prepared runner", ""

    def read(url):
        with urlopen(url, timeout=2) as response:
            return response.status, response.read().decode()

    async def scenario():
        started = asyncio.Event()

        class RecordingServer(Server):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs, request_timeout=0.1, quiet=True)
                servers.append(self)

            async def start_async(self):
                await super().start_async()
                started.set()
                return self

        monkeypatch.setattr("pyjs.testing.daemon.Server", RecordingServer)
        monkeypatch.setattr("pyjs.testing.daemon.build_runner_components", components)
        task = asyncio.create_task(async_main(
            "127.0.0.1", 0, 0, tmp_path, tmp_path / "cache", "system", False,
            1440, 1000, "system", tmp_path / "artifacts", 30, 10,
        ))
        try:
            assert await asyncio.to_thread(building.wait, 2)
            assert not servers, "daemon advertised readiness before runner compilation"
            release.set()
            if build_failure:
                with pytest.raises(RuntimeError, match="invalid runner code"):
                    await asyncio.wait_for(task, 2)
                assert not servers
                return
            await asyncio.wait_for(started.wait(), 2)
            for _ in range(2):
                status, body = await asyncio.to_thread(read, servers[0].url + "/")
                assert status == 200
                assert "// prepared runner" in body
            assert builds == [1], "page requests recompiled the runner"
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_cancelled_request_drops_pending_browser_results(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)

    async def scenario():
        dispatched = asyncio.Event()

        async def send(raw):
            dispatched.set()

        daemon.ensure_browser_connection = AsyncMock(return_value=SimpleNamespace(send=send))
        task = asyncio.create_task(daemon.handle_run_tests({"tests": []}))
        await asyncio.wait_for(dispatched.wait(), 2)
        future, = daemon.pending_results.values()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert future.cancelled()
        assert daemon.pending_results == {}
        assert not daemon.run_lock.locked()
        assert daemon.reusable is False

    asyncio.run(scenario())


def test_newest_registered_browser_remains_active_when_older_browser_disconnects(tmp_path):
    daemon = make_daemon(tmp_path)
    older_browser = object()
    newer_browser = object()

    daemon.activate_browser(older_browser)
    daemon.activate_browser(newer_browser)
    daemon.deactivate_browser(older_browser)

    assert daemon.active_browser is newer_browser
    assert daemon.browser_ready.is_set()


def test_active_browser_disconnect_clears_browser_readiness(tmp_path):
    daemon = make_daemon(tmp_path)
    browser = object()

    daemon.activate_browser(browser)
    daemon.deactivate_browser(browser)

    assert daemon.active_browser is None
    assert not daemon.browser_ready.is_set()


def test_browser_activity_refreshes_its_last_seen_time(tmp_path, monkeypatch):
    daemon = make_daemon(tmp_path)
    browser = object()
    monotonic = Mock(side_effect=[10, 15])
    monkeypatch.setattr("pyjs.testing.daemon.time.monotonic", monotonic)

    daemon.activate_browser(browser)
    daemon.note_browser_activity(browser)

    assert daemon.last_browser_seen == 15


def test_stale_browser_is_not_reused(tmp_path, monkeypatch):
    daemon = make_daemon(tmp_path)
    browser = object()
    daemon.activate_browser(browser)
    daemon.last_browser_seen = 10
    monkeypatch.setattr("pyjs.testing.daemon.time.monotonic", Mock(return_value=30))
    monkeypatch.setattr("pyjs.testing.daemon.BROWSER_CONNECT_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr("pyjs.testing.daemon.webbrowser.open_new_tab", Mock())

    connected = asyncio.run(daemon.ensure_browser_connection())

    assert connected is None
    assert daemon.active_browser is None
    assert not daemon.browser_ready.is_set()


def test_browser_heartbeat_does_not_prevent_idle_shutdown(tmp_path, monkeypatch):
    daemon = make_daemon(tmp_path)

    class HeartbeatConnection:
        def __init__(self):
            self.messages = iter([json.dumps({"type": "browser_heartbeat"})])

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.messages)
            except StopIteration:
                raise StopAsyncIteration from None

    browser = HeartbeatConnection()
    daemon.active_browser = browser
    daemon.last_browser_seen = 5
    original_activity = daemon.last_activity
    monkeypatch.setattr("pyjs.testing.daemon.time.monotonic", Mock(return_value=10))

    asyncio.run(daemon.handler(browser))

    assert daemon.last_browser_seen == 10
    assert daemon.last_activity == original_activity


@pytest.mark.parametrize(
    "failure",
    [
        SyntaxError("invalid test syntax"),
        TypeError("cannot analyze test"),
        RuntimeError("cannot generate bundle"),
    ],
)
def test_bundle_build_failure_reports_its_stage(tmp_path, failure):
    daemon = make_daemon(tmp_path)
    daemon.current_bundle = "old bundle"
    daemon.current_css = "old css"
    daemon.current_run_id = "old-run"
    daemon.bundle_builder.build = Mock(side_effect=failure)

    response = run_tests(daemon)

    assert response["stage"] == "bundle_build"
    assert response["error"] == str(failure)
    assert daemon.current_bundle == ""
    assert daemon.current_css == ""
    assert daemon.current_run_id is None
    assert daemon.cached_suite_id is None
    assert daemon.cached_bundle is None
    assert daemon.reusable is False


def test_vendor_javascript_serves_the_current_managed_module(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.current_vendor = b"export const ready = true;\n"

    response = daemon.vendor_javascript(request("/pyjs-vendor.js"))

    assert response.status == 200
    assert response.body == b"export const ready = true;\n"
    assert response.content_type == "application/javascript; charset=utf-8"
    assert response.headers == {"Cache-Control": "no-store"}


def test_missing_managed_vendor_reports_bundle_build_failure(
    tmp_path,
    monkeypatch,
):
    daemon = make_daemon(tmp_path)
    imports = (
        NpmImport(NpmPackage("example-package", "1.2.3"), "$example"),
    )
    daemon.bundle_builder.build = Mock(
        return_value=BrowserBundle("bundle", "", npm_imports=imports)
    )
    managed_project = Mock()
    managed_project.vendor_for.return_value = None
    monkeypatch.setattr(
        "pyjs.testing.daemon.ManagedNpmProject.for_project",
        Mock(return_value=managed_project),
    )

    response = run_tests(daemon)

    assert response == {
        "type": "run_tests_result",
        "status": "failed",
        "stage": "bundle_build",
        "error": (
            "JavaScript dependencies are not synchronized; run "
            "'pyjs npm sync' from the project directory"
        ),
    }
    assert daemon.current_vendor == b""
    assert daemon.reusable is False


def test_daemon_accepts_a_valid_bundle_after_a_failed_build(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(
        side_effect=[ValueError("cannot compile test"), BUNDLE]
    )

    failed = run_tests(daemon)

    async def send_result(raw_message):
        run_id = json.loads(raw_message)["run_id"]
        daemon.pending_results[run_id].set_result([])

    daemon.ensure_browser_connection = AsyncMock(
        return_value=SimpleNamespace(send=send_result)
    )
    recovered = run_tests(daemon)

    assert failed == {
        "type": "run_tests_result",
        "status": "failed",
        "stage": "bundle_build",
        "error": "cannot compile test",
    }
    assert recovered == {
        "type": "run_tests_result",
        "status": "ok",
        "results": [],
    }
    assert daemon.reusable is True


def test_daemon_caches_one_compiled_suite_while_running_one_test_at_a_time(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    sent_messages = []

    async def send_result(raw_message):
        message = json.loads(raw_message)
        sent_messages.append(message)
        daemon.pending_results[message["run_id"]].set_result([])

    daemon.ensure_browser_connection = AsyncMock(
        return_value=SimpleNamespace(send=send_result)
    )
    tests = [
        {
            "nodeid": "tests/test_app.py::test_one",
            "module_name": "tests.test_app",
            "function_name": "test_one",
        },
        {
            "nodeid": "tests/test_app.py::test_two",
            "module_name": "tests.test_app",
            "function_name": "test_two",
        },
    ]

    for nodeid in (tests[0]["nodeid"], tests[1]["nodeid"]):
        response = asyncio.run(
            daemon._handle_run_tests(
                {
                    "type": "run_tests",
                    "suite_id": "suite-1",
                    "tests": tests,
                    "run_nodeids": [nodeid],
                    "selected_nodeids": [test["nodeid"] for test in tests],
                    "current_nodeid": nodeid,
                }
            )
        )
        assert response == {
            "type": "run_tests_result",
            "status": "ok",
            "results": [],
        }

    asyncio.run(
        daemon._handle_run_tests(
            {
                "type": "run_tests",
                "suite_id": "suite-2",
                "tests": tests,
                "run_nodeids": [tests[0]["nodeid"]],
                "selected_nodeids": [test["nodeid"] for test in tests],
                "current_nodeid": tests[0]["nodeid"],
            }
        )
    )

    assert daemon.bundle_builder.build.call_count == 2
    assert [call.args[1] for call in daemon.bundle_builder.build.call_args_list] == [
        "suite-1",
        "suite-2",
    ]
    assert [message["nodeids"] for message in sent_messages] == [
        [tests[0]["nodeid"]],
        [tests[1]["nodeid"]],
        [tests[0]["nodeid"]],
    ]


def test_browser_connection_failure_reports_its_stage(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    daemon.ensure_browser_connection = AsyncMock(return_value=None)

    response = run_tests(daemon)

    assert response == {
        "type": "run_tests_result",
        "status": "failed",
        "stage": "browser_connection",
        "error": (
            "No browser runner connected. Open http://127.0.0.1:8765/, "
            "or rerun with --pyjs-browser=managed."
        ),
    }


def test_runner_page_build_failure_renders_diagnostics(tmp_path, monkeypatch):
    daemon = make_daemon(tmp_path)
    request = SimpleNamespace(path="/")
    monkeypatch.setattr(
        "pyjs.testing.daemon.build_runner_components",
        Mock(side_effect=ValueError("unsupported runner code <here>")),
    )

    response = asyncio.run(daemon.runner_page(request))

    assert response.status == 500
    assert "Browser runner build failed" in response.body
    assert "unsupported runner code &lt;here&gt;" in response.body
    assert "unsupported runner code <here>" in daemon.runner_page_error
    assert daemon.browser_ready.is_set()


def test_runner_page_build_failure_wakes_browser_connection_wait(tmp_path, monkeypatch):
    daemon = make_daemon(tmp_path)
    request = SimpleNamespace(path="/")
    monkeypatch.setattr("pyjs.testing.daemon.webbrowser.open_new_tab", Mock())
    monkeypatch.setattr(
        "pyjs.testing.daemon.build_runner_components",
        Mock(side_effect=ValueError("unsupported runner code")),
    )

    async def request_failed_page_while_waiting():
        browser_task = asyncio.create_task(daemon.ensure_browser_connection())
        await asyncio.sleep(0)
        await daemon.runner_page(request)
        return await browser_task

    browser = asyncio.run(request_failed_page_while_waiting())

    assert browser is None
    assert "unsupported runner code" in daemon.runner_page_error


def test_managed_browser_connection_waits_for_browser_startup(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.browser_mode = "managed"
    browser = object()

    async def connect_after_daemon_health_is_available():
        browser_task = asyncio.create_task(daemon.ensure_browser_connection())
        await asyncio.sleep(0)
        daemon.activate_browser(browser)
        return await browser_task

    assert asyncio.run(connect_after_daemon_health_is_available()) is browser


def test_runner_page_build_failure_returns_without_browser_connection_timeout(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    daemon.runner_page_error = "runner compilation failed"
    daemon.ensure_browser_connection = AsyncMock(return_value=None)

    response = run_tests(daemon)

    assert response["stage"] == "bundle_build"
    assert response["error"] == "Failed to build browser runner page:\nrunner compilation failed"


def test_daemon_status_exposes_runner_state(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.current_run_id = "run-1"
    daemon.runner_page_error = "runner compilation failed"

    status = daemon.status_payload()

    assert status["active_browser"] is False
    assert status["current_run_id"] == "run-1"
    assert status["reusable"] is True
    assert status["pending_runs"] == 0
    assert status["runner_page_error"] == "runner compilation failed"
    assert status["browser_mode"] == "system"
    assert status["headed"] is False
    assert status["browser_width"] == 1440
    assert status["browser_height"] == 1000
    assert status["color_scheme"] == "system"
    assert status["artifacts_dir"] == str((tmp_path / "cache" / "artifacts").resolve())
    assert status["test_timeout"] == 30
    assert status["retained_iframes"] == 10
    assert status["last_activity_seconds_ago"] >= 0


def test_runner_page_uses_generated_component_styles_and_system_theme(tmp_path):
    page = make_daemon(tmp_path).runner_html()
    javascript = page.split("<script>", 1)[1].split("</script>", 1)[0]

    assert "tailwindcss" in page
    assert 'content="dark light"' in page
    assert "prefers-color-scheme: dark" in page
    assert "#f3f0e8" not in page
    assert "iframe.runner-frame.active" in page
    assert "browser_heartbeat" in page
    assert "setInterval" in page
    syntax = Node().check_module(javascript)
    assert syntax.returncode == 0, syntax.stderr


def test_bundle_source_map_serves_embedded_python_source(tmp_path):
    daemon = make_daemon(tmp_path)
    source = SourceFile.from_text("tests/test_example.py", "assert False\n")
    daemon.current_source_map = SourceMap(
        (SourceMapping(2, 4, source, 0, 0),),
        "bundle.js",
    )
    daemon.current_run_id = "run-1"

    response = daemon.bundle_source_map(
        SimpleNamespace(query_value=Mock(return_value="run-1"))
    )

    assert response.status == 200
    assert response.content_type == "application/json; charset=utf-8"
    assert json.loads(response.body) == {
        "version": 3,
        "sources": ["tests/test_example.py"],
        "sourcesContent": ["assert False\n"],
        "names": [],
        "mappings": ";;IAAA",
        "file": "bundle.js",
    }


def test_bundle_css_is_served_for_the_current_run(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.current_run_id = "run-1"
    daemon.current_css = ".menu { display: block; }"
    request = SimpleNamespace(query_value=Mock(return_value="run-1"))

    response = daemon.bundle_css(request)

    assert response.status == 200
    assert response.content_type == "text/css; charset=utf-8"
    assert response.body == ".menu { display: block; }"


def test_bundle_dispatch_failure_reports_its_stage_and_deactivates_browser(tmp_path):
    daemon = make_daemon(tmp_path)
    browser = SimpleNamespace(send=AsyncMock(side_effect=ConnectionError("connection closed")))
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    daemon.ensure_browser_connection = AsyncMock(return_value=browser)
    daemon.activate_browser(browser)

    response = run_tests(daemon)

    assert response["stage"] == "bundle_dispatch"
    assert response["error"] == "connection closed"
    assert daemon.active_browser is None
    assert daemon.current_bundle == ""
    assert daemon.current_run_id is None
    assert daemon.reusable is False


def test_bundle_dispatch_timeout_reports_its_stage(tmp_path, monkeypatch):
    daemon = make_daemon(tmp_path)

    async def block_dispatch(raw_message):
        await asyncio.Event().wait()

    browser = SimpleNamespace(send=block_dispatch)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    daemon.ensure_browser_connection = AsyncMock(return_value=browser)
    daemon.activate_browser(browser)
    monkeypatch.setattr("pyjs.testing.daemon.BROWSER_DISPATCH_TIMEOUT_SECONDS", 0)

    response = run_tests(daemon)

    assert response["stage"] == "bundle_dispatch"
    assert response["error"] == "Timed out dispatching bundle to browser"
    assert daemon.active_browser is None
    assert daemon.current_bundle == ""
    assert daemon.current_run_id is None
    assert daemon.reusable is False


def test_browser_bundle_failure_reports_execution_stage(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)

    async def send_failure(raw_message):
        run_id = json.loads(raw_message)["run_id"]
        daemon.pending_results[run_id].set_result(
            [{"nodeid": "<bundle>", "outcome": "failed", "error": "invalid bundle"}]
        )

    browser = SimpleNamespace(send=send_failure)
    daemon.ensure_browser_connection = AsyncMock(return_value=browser)

    response = run_tests(daemon)

    assert response["stage"] == "browser_execution"
    assert response["error"] == "invalid bundle"


def test_browser_bundle_failure_adds_python_source_locations(tmp_path):
    daemon = make_daemon(tmp_path)
    source = SourceFile.from_text("tests/test_example.py", "raise ValueError()\n")
    source_map = SourceMap((SourceMapping(3, 4, source, 0, 0),), "bundle.js")
    daemon.bundle_builder.build = Mock(
        return_value=BrowserBundle("bundle", "", source_map)
    )

    async def send_failure(raw_message):
        run_id = json.loads(raw_message)["run_id"]
        daemon.pending_results[run_id].set_result(
            [
                {
                    "nodeid": "<bundle>",
                    "outcome": "failed",
                    "error": (
                        "RangeError: failure\n"
                        "    at main (http://127.0.0.1:8765/bundle.js:4:9)"
                    ),
                }
            ]
        )

    daemon.ensure_browser_connection = AsyncMock(
        return_value=SimpleNamespace(send=send_failure)
    )

    response = run_tests(daemon)

    assert response["stage"] == "browser_execution"
    assert response["error"] == (
        "RangeError: failure\n"
        "    at main (tests/test_example.py:1:1)"
    )
    assert response["raw_error"] == (
        "RangeError: failure\n"
        "    at main (http://127.0.0.1:8765/bundle.js:4:9)"
    )


def test_browser_bundle_failure_preserves_structured_exception_details(tmp_path):
    daemon = make_daemon(tmp_path)
    source = SourceFile.from_text("tests/test_example.py", "raise ValueError()\n")
    source_map = SourceMap((SourceMapping(3, 4, source, 0, 0),), "bundle.js")
    daemon.bundle_builder.build = Mock(
        return_value=BrowserBundle("bundle", "", source_map)
    )
    raw_stack = (
        "RangeError: failure\n"
        "    at main (http://127.0.0.1:8765/bundle.js:4:9)"
    )

    async def send_failure(raw_message):
        run_id = json.loads(raw_message)["run_id"]
        daemon.pending_results[run_id].set_result(
            [
                {
                    "nodeid": "<bundle>",
                    "outcome": "failed",
                    "exception": {
                        "name": "RangeError",
                        "message": "failure",
                        "stack": raw_stack,
                    },
                }
            ]
        )

    daemon.ensure_browser_connection = AsyncMock(
        return_value=SimpleNamespace(send=send_failure)
    )

    response = run_tests(daemon)

    assert response == {
        "type": "run_tests_result",
        "status": "failed",
        "stage": "browser_execution",
        "error": "RangeError: failure\n    at main (tests/test_example.py:1:1)",
        "exception": {
            "name": "RangeError",
            "message": "failure",
            "stack": raw_stack,
            "mapped_stack": (
                "RangeError: failure\n"
                "    at main (tests/test_example.py:1:1)"
            ),
        },
    }


def test_daemon_recovers_after_a_browser_bundle_failure(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    outcomes = iter(
        [
            [
                {
                    "nodeid": "<bundle>",
                    "outcome": "failed",
                    "error": "invalid bundle",
                }
            ],
            [],
        ]
    )

    async def send_result(raw_message):
        run_id = json.loads(raw_message)["run_id"]
        daemon.pending_results[run_id].set_result(next(outcomes))

    daemon.ensure_browser_connection = AsyncMock(
        return_value=SimpleNamespace(send=send_result)
    )

    failed = run_tests(daemon)
    recovered = run_tests(daemon)

    assert failed["stage"] == "browser_execution"
    assert recovered == {
        "type": "run_tests_result",
        "status": "ok",
        "results": [],
    }
    assert daemon.reusable is True


def test_daemon_recovers_after_an_individual_runtime_failure(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    outcomes = iter(
        [
            [
                {
                    "nodeid": "tests/test_app.py::test_value",
                    "outcome": "failed",
                    "error": "runtime failed",
                }
            ],
            [
                {
                    "nodeid": "tests/test_app.py::test_value",
                    "outcome": "passed",
                }
            ],
        ]
    )

    async def send_result(raw_message):
        run_id = json.loads(raw_message)["run_id"]
        daemon.pending_results[run_id].set_result(next(outcomes))

    daemon.ensure_browser_connection = AsyncMock(
        return_value=SimpleNamespace(send=send_result)
    )

    failed = run_tests(daemon)
    recovered = run_tests(daemon)

    assert failed == {
        "type": "run_tests_result",
        "status": "ok",
        "results": [
            {
                "nodeid": "tests/test_app.py::test_value",
                "outcome": "failed",
                "error": "runtime failed",
            }
        ],
    }
    assert recovered == {
        "type": "run_tests_result",
        "status": "ok",
        "results": [
            {
                "nodeid": "tests/test_app.py::test_value",
                "outcome": "passed",
            }
        ],
    }
    assert daemon.reusable is True


def test_run_message_includes_configured_retained_iframe_limit(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.retained_iframes = 3
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    sent_message = None

    async def send_result(raw_message):
        nonlocal sent_message
        sent_message = json.loads(raw_message)
        daemon.pending_results[sent_message["run_id"]].set_result([])

    daemon.ensure_browser_connection = AsyncMock(return_value=SimpleNamespace(send=send_result))

    run_tests(daemon)

    assert sent_message["max_preserved_iframes"] == 3
    run_id = sent_message["run_id"]
    assert daemon.current_bundle == (
        "bundle\n"
        f"//# sourceURL=/bundle.js?run_id={run_id}\n"
        f"//# sourceMappingURL=/bundle.js.map?run_id={run_id}\n"
    )


def test_managed_browser_captures_failure_artifacts(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.artifacts_dir = tmp_path / "configured-artifacts"
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)

    async def screenshot(path):
        path.write_bytes(b"png")

    daemon.managed_page = SimpleNamespace(
        evaluate=AsyncMock(),
        wait_for_frames=AsyncMock(),
        screenshot=screenshot,
        inspect=AsyncMock(return_value={"visibleText": "failed test"}),
    )

    async def send_failure(raw_message):
        run_id = json.loads(raw_message)["run_id"]
        daemon.pending_results[run_id].set_result(
            [{"nodeid": "tests/test_app.py::test_fails", "outcome": "failed", "error": "boom"}]
        )

    daemon.ensure_browser_connection = AsyncMock(return_value=SimpleNamespace(send=send_failure))

    response = run_tests(daemon)

    artifact = response["failure_artifacts"]["tests/test_app.py::test_fails"]
    assert artifact["screenshot"].endswith(".png")
    assert artifact["diagnostics"].endswith(".json")
    assert (tmp_path / "configured-artifacts").is_dir()


@pytest.mark.parametrize(
    "width,height,expected_width,expected_height",
    [(160, 96, 160, 96), (1062.75, 732.5, 1062, 732), (0.5, 0.25, 1, 1)],
)
def test_managed_browser_captures_requested_element_render(
    tmp_path, width, height, expected_width, expected_height,
):
    daemon = make_daemon(tmp_path)
    page = SimpleNamespace(
        evaluate=AsyncMock(),
        wait_for_frames=AsyncMock(),
        evaluate_json=AsyncMock(
            return_value={"x": 12.25, "y": 24.5, "width": width, "height": height, "scale": 1}
        ),
        screenshot_data_url=AsyncMock(return_value="data:image/png;base64,cG5n"),
    )
    daemon.managed_page = page
    results = [
        {
            "nodeid": "tests/test_app.py::test_card",
            "outcome": "passed",
            "artifacts": [{"name": "card", "dataUrl": "", "elementId": "render-0"}],
        }
    ]

    asyncio.run(daemon.capture_render_artifacts(results))

    artifact = results[0]["artifacts"][0]
    assert artifact["dataUrl"] == "data:image/png;base64,cG5n"
    page.screenshot_data_url.assert_awaited_once_with(
        {"x": 12.25, "y": 24.5, "width": expected_width,
         "height": expected_height, "scale": 1}
    )


def test_managed_browser_seeks_animation_before_element_render(tmp_path):
    daemon = make_daemon(tmp_path)
    page = SimpleNamespace(
        evaluate=AsyncMock(),
        wait_for_frames=AsyncMock(),
        evaluate_json=AsyncMock(
            return_value={"x": 12, "y": 24, "width": 160, "height": 96, "scale": 1}
        ),
        screenshot_data_url=AsyncMock(return_value="data:image/png;base64,cG5n"),
    )
    daemon.managed_page = page
    results = [
        {
            "nodeid": "tests/test_app.py::test_card",
            "outcome": "passed",
            "artifacts": [
                {
                    "name": "card",
                    "dataUrl": "",
                    "elementId": "render-0",
                    "animationTimeMs": 250,
                }
            ],
        }
    ]

    asyncio.run(daemon.capture_render_artifacts(results))

    expression = page.evaluate_json.await_args.args[0]
    assert "element.getAnimations({subtree: true})" in expression
    assert "const animationTime = 250" in expression
    assert page.wait_for_frames.await_count == 2


def test_dom_render_request_explains_that_managed_browser_is_required(tmp_path):
    daemon = make_daemon(tmp_path)
    results = [
        {
            "nodeid": "tests/test_app.py::test_card",
            "outcome": "passed",
            "artifacts": [{"name": "card", "dataUrl": "", "elementId": "render-0"}],
        }
    ]

    asyncio.run(daemon.capture_render_artifacts(results))

    assert results[0]["artifacts"][0]["error"] == (
        "DOM render assertions require --pyjs-browser=managed"
    )


def test_result_timeout_reports_transport_stage(tmp_path):
    daemon = make_daemon(tmp_path)
    browser = SimpleNamespace(send=AsyncMock())
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)
    daemon.ensure_browser_connection = AsyncMock(return_value=browser)

    daemon.test_timeout = 0

    response = run_tests(daemon)

    assert response["stage"] == "result_transport"
    assert response["error"] == "Timed out after 0 seconds waiting for browser test results"
    assert daemon.current_bundle == ""
    assert daemon.current_run_id is None
    assert daemon.cached_bundle is None
    assert daemon.reusable is False


def test_active_browser_disconnect_fails_run_without_waiting(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon.bundle_builder.build = Mock(return_value=BUNDLE)

    class DisconnectedBrowser:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def send(self, raw_message):
            await daemon.handler(self)

    browser = DisconnectedBrowser()
    daemon.activate_browser(browser)
    daemon.ensure_browser_connection = AsyncMock(return_value=browser)

    response = run_tests(daemon)

    assert response == {
        "type": "run_tests_result",
        "status": "failed",
        "stage": "result_transport",
        "error": "Browser runner disconnected",
    }
    assert daemon.active_browser is None
    assert daemon.pending_results == {}
    assert daemon.reusable is False
