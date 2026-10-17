import argparse
import asyncio
import contextlib
import hashlib
import html
import importlib
import json
import os
import re
import signal
import threading
import time
import traceback
import uuid
import webbrowser
from pathlib import Path
from typing import Any

from pyjs.javascript.sourcemap import (
    SourceMap,
    TranspiledJavaScript,
    map_stack_trace,
)
from pyjs.javascript.transpiler import bundle
from pyjs.server.dev import Application, Request, Response, Server, WebSocket
from pyjs.testing.builder import (
    BrowserBundle,
    BrowserBundleBuilder,
    SelectedTest,
    compute_testing_signature,
)
from pyjs.testing.protocol import failed_run
from pyjs.tooling.browser import Browser, BrowserPage
from pyjs.tooling.npm import ManagedNpmProject

BROWSER_CONNECT_TIMEOUT_SECONDS = 30
BROWSER_DISPATCH_TIMEOUT_SECONDS = 10
BROWSER_STALE_AFTER_SECONDS = 15


def map_result_exception(result: dict[str, Any], source_map: SourceMap) -> None:
    exception = result.get("exception")
    if isinstance(exception, dict):
        stack = exception.get("stack")
        mapped_stack = (
            map_stack_trace(stack, source_map) if isinstance(stack, str) else ""
        )
        exception["mapped_stack"] = mapped_stack
        message = exception.get("message")
        result["error"] = mapped_stack
        if not mapped_stack and isinstance(message, str):
            result["error"] = message
        return
    if isinstance(error := result.get("error"), str) and error:
        mapped_error = map_stack_trace(error, source_map)
        if mapped_error != error:
            result["raw_error"] = error
        result["error"] = mapped_error


def build_runner_components() -> tuple[str, str]:
    module = importlib.import_module("pyjs.testing.client.app")
    module = importlib.reload(module)
    return bundle(module.main, include_main=True)


def runner_build_failure_html(error: str) -> str:
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>pyjs Browser Runner Build Failed</title>
    <style>
      body {{ margin: 2rem; font-family: ui-monospace, monospace; color: #7f1d1d; }}
      pre {{ overflow: auto; padding: 1rem; background: #fef2f2; white-space: pre-wrap; }}
    </style>
  </head>
  <body>
    <h1>Browser runner build failed</h1>
    <p>Fix the Python compilation error below, then reload this page.</p>
    <pre>{html.escape(error)}</pre>
  </body>
</html>
"""


class PrototypeDaemon:
    def __init__(
        self,
        host: str,
        port: int,
        idle_seconds: int,
        project_root: Path,
        cache_dir: Path,
        browser_mode: str = "system",
        headed: bool = False,
        browser_width: int = 1440,
        browser_height: int = 1000,
        color_scheme: str = "system",
        artifacts_dir: Path | None = None,
        test_timeout: float = 30,
        retained_iframes: int = 10,
    ):
        self.host = host
        self.port = port
        self.idle_seconds = idle_seconds
        self.project_root = project_root.resolve()
        self.cache_dir = cache_dir.resolve()
        self.browser_mode = browser_mode
        self.headed = headed
        self.browser_width = browser_width
        self.browser_height = browser_height
        self.color_scheme = color_scheme
        self.artifacts_dir = (artifacts_dir or self.cache_dir / "artifacts").resolve()
        self.test_timeout = test_timeout
        self.retained_iframes = retained_iframes
        self.managed_page: BrowserPage | None = None
        self.bundle_builder = BrowserBundleBuilder(self.project_root, self.cache_dir)
        # Both builders change imported modules. Serialize their worker threads,
        # including when a cancelled request leaves a compilation finishing.
        self.build_lock = threading.Lock()
        self.signature = compute_testing_signature()
        self.current_bundle = ""
        self.current_css = ""
        self.current_source_map = SourceMap()
        self.current_vendor = b""
        self.current_run_id: str | None = None
        self.cached_suite_id: str | None = None
        self.cached_bundle: BrowserBundle | None = None
        self.reusable = True
        self.runner_page_error: str | None = None
        self.active_browser: WebSocket | None = None
        self.last_browser_seen: float | None = None
        self.pending_results: dict[str, asyncio.Future[list[dict[str, Any]]]] = {}
        self.run_lock = asyncio.Lock()
        self.browser_ready = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self.last_activity = time.monotonic()

    @property
    def runner_url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def touch_activity(self) -> None:
        self.last_activity = time.monotonic()

    def status_payload(self) -> dict[str, Any]:
        self.discard_stale_browser()
        status = {
            "status": "ok",
            "signature": self.signature,
            "pid": os.getpid(),
            "project_root": str(self.project_root),
            "cache_dir": str(self.cache_dir),
            "active_browser": self.active_browser is not None,
            "current_run_id": self.current_run_id,
            "reusable": self.reusable,
            "pending_runs": len(self.pending_results),
            "runner_page_error": self.runner_page_error,
            "browser_mode": self.browser_mode,
            "headed": self.headed,
            "browser_width": self.browser_width,
            "browser_height": self.browser_height,
            "color_scheme": self.color_scheme,
            "artifacts_dir": str(self.artifacts_dir),
            "test_timeout": self.test_timeout,
            "retained_iframes": self.retained_iframes,
            "last_activity_seconds_ago": round(time.monotonic() - self.last_activity, 3),
        }
        if self.last_browser_seen is not None:
            status["browser_last_seen_seconds_ago"] = round(
                time.monotonic() - self.last_browser_seen, 3
            )
        if self.managed_page is not None:
            status["browser_exceptions"] = self.managed_page.exceptions
            status["browser_console"] = self.managed_page.console[-10:]
        return status

    def activate_browser(self, connection: WebSocket) -> None:
        self.active_browser = connection
        self.last_browser_seen = time.monotonic()
        self.browser_ready.set()

    def note_browser_activity(self, connection: WebSocket) -> None:
        if self.active_browser is connection:
            self.last_browser_seen = time.monotonic()

    def discard_stale_browser(self) -> None:
        if (
            self.active_browser is not None
            and self.last_browser_seen is not None
            and time.monotonic() - self.last_browser_seen > BROWSER_STALE_AFTER_SECONDS
        ):
            self.deactivate_browser(self.active_browser)

    def deactivate_browser(self, connection: WebSocket) -> None:
        if self.active_browser is connection:
            self.active_browser = None
            self.browser_ready.clear()

    def discard_bundle(self) -> None:
        self.current_bundle = ""
        self.current_css = ""
        self.current_source_map = SourceMap()
        self.current_vendor = b""
        self.current_run_id = None
        self.cached_suite_id = None
        self.cached_bundle = None
        self.reusable = False

    async def runner_page(self, request: Request) -> Response:
        self.touch_activity()
        try:
            runner_page = await asyncio.to_thread(self.runner_html)
        except Exception:
            self.runner_page_error = traceback.format_exc()
            self.reusable = False
            self.browser_ready.set()
            return Response.html(
                runner_build_failure_html(self.runner_page_error),
                status=500,
                headers={"Cache-Control": "no-store"},
            )
        self.runner_page_error = None
        if self.active_browser is None:
            self.browser_ready.clear()
        return Response.html(runner_page, headers={"Cache-Control": "no-store"})

    def bundle_javascript(self, request: Request) -> Response:
        self.touch_activity()
        requested_run_id = request.query_value("run_id")
        if not self.current_bundle or requested_run_id != self.current_run_id:
            return Response.text("bundle not available", status=404)
        return Response(
            self.current_bundle,
            content_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    def bundle_css(self, request: Request) -> Response:
        self.touch_activity()
        requested_run_id = request.query_value("run_id")
        if requested_run_id != self.current_run_id:
            return Response.text("bundle not available", status=404)
        return Response(
            self.current_css,
            content_type="text/css; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    def vendor_javascript(self, request: Request) -> Response:
        self.touch_activity()
        if not self.current_vendor:
            return Response.text("vendor not available", status=404)
        return Response(
            self.current_vendor,
            content_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    def bundle_source_map(self, request: Request) -> Response:
        self.touch_activity()
        requested_run_id = request.query_value("run_id")
        if (
            not self.current_source_map.mappings
            or requested_run_id != self.current_run_id
        ):
            return Response.text("source map not available", status=404)
        return Response(
            self.current_source_map.to_json(),
            content_type="application/json; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    def health(self, request: Request) -> Response:
        return Response.json(
            self.status_payload(), headers={"Cache-Control": "no-store"}
        )

    def request_shutdown(self, request: Request) -> Response:
        self.shutdown_event.set()
        return Response.text("shutting down")

    async def handler(self, connection: WebSocket) -> None:
        try:
            async with asyncio.TaskGroup() as tasks:
                pending_run = None
                try:
                    async for raw_message in connection:
                        message = json.loads(raw_message)
                        message_type = message.get("type")
                        self.note_browser_activity(connection)

                        if message_type == "browser_heartbeat":
                            continue

                        self.touch_activity()
                        if message_type == "register_browser":
                            self.activate_browser(connection)
                            await connection.send(json.dumps({"type": "browser_registered"}))
                        elif message_type == "run_tests":
                            if pending_run is not None and not pending_run.done():
                                await connection.send(json.dumps(failed_run("busy", "A test request is already running")))
                            else:
                                # Keep reading control frames, including pings,
                                # while compilation and browser execution wait.
                                pending_run = tasks.create_task(self.respond_to_run(connection, message))
                        elif message_type == "test_results":
                            future = self.pending_results.get(message["run_id"])
                            if future is not None and not future.done():
                                future.set_result(message["results"])
                finally:
                    if pending_run is not None:
                        pending_run.cancel()
        finally:
            was_active = self.active_browser is connection
            self.deactivate_browser(connection)
            if was_active:
                for future in self.pending_results.values():
                    if not future.done():
                        future.set_exception(
                            ConnectionError("Browser runner disconnected")
                        )

    async def respond_to_run(self, connection: WebSocket, message: dict[str, Any]) -> None:
        response = await self.handle_run_tests(message)
        await connection.send(json.dumps(response))

    def build_bundle(self, selected_tests: list[SelectedTest], run_id: str) -> BrowserBundle:
        with self.build_lock:
            return self.bundle_builder.build(selected_tests, run_id)

    async def handle_run_tests(self, message: dict[str, Any]) -> dict[str, Any]:
        async with self.run_lock:
            try:
                return await self._handle_run_tests(message)
            except asyncio.CancelledError:
                future = self.pending_results.pop(self.current_run_id, None)
                if future is not None:
                    future.cancel()
                self.discard_bundle()
                raise

    async def _handle_run_tests(self, message: dict[str, Any]) -> dict[str, Any]:
        self.touch_activity()
        selected_tests = [SelectedTest.from_payload(payload) for payload in message["tests"]]
        nodeids = [test.nodeid for test in selected_tests]
        run_nodeids = message.get("run_nodeids", nodeids)
        selected_nodeids = message.get("selected_nodeids", nodeids)
        current_nodeid = message.get("current_nodeid")
        suite_id = message.get("suite_id")
        run_id = uuid.uuid4().hex
        self.current_bundle = ""
        self.current_css = ""
        self.current_source_map = SourceMap()
        self.current_vendor = b""
        self.current_run_id = None
        bundle_result = self.cached_bundle if suite_id == self.cached_suite_id else None
        if bundle_result is None:
            try:
                bundle_result = await asyncio.to_thread(self.build_bundle, selected_tests, suite_id or run_id)
            except Exception as exc:
                self.discard_bundle()
                return failed_run("bundle_build", str(exc))
            if suite_id is not None:
                self.cached_suite_id = suite_id
                self.cached_bundle = bundle_result

        vendor = ManagedNpmProject.for_project(self.project_root).vendor_for(
            bundle_result.npm_imports
        )
        if bundle_result.npm_imports and vendor is None:
            self.discard_bundle()
            return failed_run(
                "bundle_build",
                "JavaScript dependencies are not synchronized; run "
                "'pyjs npm sync' from the project directory",
            )

        self.reusable = True
        generated = TranspiledJavaScript(
            bundle_result.javascript,
            bundle_result.source_map,
        )
        self.current_bundle = generated.with_source_mapping_url(
            f"/bundle.js.map?run_id={run_id}",
            source_url=f"/bundle.js?run_id={run_id}",
        )
        self.current_css = bundle_result.css
        self.current_source_map = bundle_result.source_map
        self.current_vendor = vendor.read_bytes() if vendor is not None else b""
        self.current_run_id = run_id
        result_future: asyncio.Future[list[dict[str, Any]]] = (
            asyncio.get_running_loop().create_future()
        )
        self.pending_results[run_id] = result_future

        browser = await self.ensure_browser_connection()
        if browser is None:
            self.pending_results.pop(run_id, None)
            if self.runner_page_error is not None:
                return failed_run(
                    "bundle_build",
                    "Failed to build browser runner page:\n" + self.runner_page_error,
                )
            return failed_run(
                "browser_connection",
                "No browser runner connected. "
                f"Open {self.runner_url}, or rerun with --pyjs-browser=managed.",
            )

        try:
            await asyncio.wait_for(
                browser.send(
                    json.dumps(
                        {
                            "type": "run_bundle",
                            "run_id": run_id,
                            "nodeids": run_nodeids,
                            "selected_nodeids": selected_nodeids,
                            "current_nodeid": current_nodeid,
                            "max_preserved_iframes": self.retained_iframes,
                        }
                    )
                ),
                timeout=BROWSER_DISPATCH_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            self.pending_results.pop(run_id, None)
            self.deactivate_browser(browser)
            self.discard_bundle()
            return failed_run("bundle_dispatch", "Timed out dispatching bundle to browser")
        except Exception as exc:
            self.pending_results.pop(run_id, None)
            self.deactivate_browser(browser)
            self.discard_bundle()
            return failed_run("bundle_dispatch", str(exc))

        try:
            results = await asyncio.wait_for(
                result_future,
                timeout=self.test_timeout,
            )
        except TimeoutError:
            self.pending_results.pop(run_id, None)
            self.discard_bundle()
            return failed_run(
                "result_transport",
                f"Timed out after {self.test_timeout:g} seconds waiting for browser test results",
            )
        except Exception as exc:
            self.pending_results.pop(run_id, None)
            self.discard_bundle()
            return failed_run("result_transport", str(exc))

        self.pending_results.pop(run_id, None)
        for result in results:
            map_result_exception(result, self.current_source_map)
        await self.capture_render_artifacts(results)
        failure_artifacts = await self.capture_failure_artifacts(results)
        bundle_result = next(
            (result for result in results if result.get("nodeid") == "<bundle>"),
            None,
        )
        if bundle_result is not None and bundle_result.get("outcome") != "passed":
            response = failed_run(
                "browser_execution",
                bundle_result.get(
                    "error",
                    "Browser bundle failed before individual test results were reported",
                ),
            )
            if isinstance(bundle_result.get("exception"), dict):
                response["exception"] = bundle_result["exception"]
            if isinstance(bundle_result.get("raw_error"), str):
                response["raw_error"] = bundle_result["raw_error"]
            if failure_artifacts:
                response["failure_artifacts"] = failure_artifacts
            return response
        response = {
            "type": "run_tests_result",
            "status": "ok",
            "results": results,
        }
        if failure_artifacts:
            response["failure_artifacts"] = failure_artifacts
        return response

    async def capture_render_artifacts(self, results: list[dict[str, Any]]) -> None:
        for result in results:
            nodeid = result.get("nodeid")
            artifacts = result.get("artifacts", [])
            requested = [artifact for artifact in artifacts if artifact.get("elementId")]
            if not requested or not isinstance(nodeid, str):
                continue
            page = self.managed_page
            if page is None:
                for artifact in requested:
                    artifact["error"] = "DOM render assertions require --pyjs-browser=managed"
                continue

            try:
                await page.evaluate(
                    "document.querySelector('browser-runner-app')"
                    f"?.selectTest({json.dumps(nodeid)})"
                )
                await page.wait_for_frames()
                for artifact in requested:
                    element_id = artifact["elementId"]
                    selector = f'[data-pyjs-render~="{element_id}"]'
                    animation_time = artifact.get("animationTimeMs")
                    clip = await page.evaluate_json(
                        f"""(() => {{
                            const app = document.querySelector('browser-runner-app');
                            const frame = app?.getFrameForNodeid({json.dumps(nodeid)});
                            if (!frame) return {{error: 'The test iframe was not retained'}};
                            const element = frame.contentDocument?.querySelector(
                                {json.dumps(selector)}
                            );
                            if (!element) return {{error: 'The rendered element was not found'}};
                            const animationTime = {json.dumps(animation_time)};
                            if (animationTime !== null) {{
                                const animations = element.getAnimations({{subtree: true}});
                                if (animations.length === 0) {{
                                    return {{error: 'The rendered element has no animations'}};
                                }}
                                for (const animation of animations) {{
                                    animation.pause();
                                    animation.currentTime = animationTime;
                                }}
                            }}
                            const frameBounds = frame.getBoundingClientRect();
                            const bounds = element.getBoundingClientRect();
                            if (
                                bounds.left < 0 || bounds.top < 0 ||
                                bounds.right > frame.clientWidth ||
                                bounds.bottom > frame.clientHeight
                            ) {{
                                return {{error: 'The rendered element does not fit in the test iframe'}};
                            }}
                            return {{
                                x: window.scrollX + frameBounds.left + bounds.left,
                                y: window.scrollY + frameBounds.top + bounds.top,
                                width: bounds.width,
                                height: bounds.height,
                                scale: 1,
                            }};
                        }})()"""
                    )
                    if animation_time is not None:
                        await page.wait_for_frames()
                    if not clip or clip.get("error"):
                        artifact["error"] = (clip or {}).get(
                            "error", "The rendered element has no visible geometry"
                        )
                    elif clip["width"] <= 0 or clip["height"] <= 0:
                        artifact["error"] = "The rendered element has no visible geometry"
                    else:
                        artifact["dataUrl"] = await page.screenshot_data_url(clip)
            except Exception as exc:
                for artifact in requested:
                    if not artifact.get("dataUrl"):
                        artifact["error"] = str(exc)

    async def capture_failure_artifacts(
        self,
        results: list[dict[str, Any]],
    ) -> dict[str, dict[str, str]]:
        page = self.managed_page
        if page is None:
            return {}
        artifacts: dict[str, dict[str, str]] = {}
        output_dir = self.artifacts_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        for result in results:
            nodeid = result.get("nodeid")
            if result.get("outcome") == "passed" or not isinstance(nodeid, str):
                continue
            readable = re.sub(r"[^A-Za-z0-9_-]+", "-", nodeid).strip("-")[-80:]
            digest = hashlib.sha256(nodeid.encode()).hexdigest()[:8]
            stem = f"{readable or 'browser'}-{digest}"
            screenshot = output_dir / f"{stem}.png"
            diagnostics = output_dir / f"{stem}.json"
            try:
                if nodeid != "<bundle>":
                    await page.evaluate(
                        "document.querySelector('browser-runner-app')"
                        f"?.selectTest({json.dumps(nodeid)})"
                    )
                await page.wait_for_frames()
                await page.screenshot(screenshot)
                state = await page.inspect()
                state["nodeid"] = nodeid
                diagnostics.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
                artifacts[nodeid] = {
                    "screenshot": str(screenshot),
                    "diagnostics": str(diagnostics),
                }
            except Exception as exc:
                artifacts[nodeid] = {"error": str(exc)}
        return artifacts

    async def monitor_idle(self) -> None:
        if self.idle_seconds <= 0:
            return

        while not self.shutdown_event.is_set():
            await asyncio.sleep(1)
            if self.run_lock.locked() or self.pending_results:
                continue
            if time.monotonic() - self.last_activity < self.idle_seconds:
                continue
            self.shutdown_event.set()
            return

    async def ensure_browser_connection(self) -> WebSocket | None:
        self.discard_stale_browser()
        if self.active_browser is not None:
            return self.active_browser

        self.runner_page_error = None
        self.browser_ready.clear()
        if self.browser_mode == "system":
            webbrowser.open_new_tab(self.runner_url)
        try:
            await asyncio.wait_for(
                self.browser_ready.wait(), timeout=BROWSER_CONNECT_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return None
        return self.active_browser

    def runner_html(self) -> str:
        with self.build_lock:
            runner_components_js, runner_components_css = build_runner_components()
        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="color-scheme" content="dark light" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PyJS Browser Tests</title>
    <style>
      {runner_components_css}
      :root {{
        color-scheme: light dark;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      html, body, #app-root {{ height: 100%; }}
      body {{ margin: 0; overflow: hidden; }}
      browser-runner-app {{ display: flex; }}
      runner-sidebar, runner-viewer {{ min-height: 0; }}
      iframe.runner-frame {{
        display: none;
        width: 100%;
        height: 100%;
        border: 0;
        background: white;
      }}
      iframe.runner-frame.active {{ display: block; }}
      .frame-host[data-empty="true"]::before {{
        content: attr(data-empty-label);
        position: absolute;
        inset: 0;
        display: grid;
        place-items: center;
        padding: 2rem;
        color: #64748b;
        font-size: 0.8125rem;
        text-align: center;
      }}
      .console-line[data-level="warn"] {{ background: rgb(245 158 11 / 0.08); }}
      .console-line[data-level="error"] {{ background: rgb(244 63 94 / 0.08); }}
      @media (max-width: 39.999rem) {{
        body {{ overflow: auto; }}
        runner-sidebar {{ height: 22rem; border-right: 0; }}
        runner-viewer {{ min-height: 40rem; }}
      }}
    </style>
  </head>
  <body>
    <script>
      {runner_components_js}
    </script>
  </body>
</html>
"""


async def async_main(
    host: str,
    port: int,
    idle_seconds: int,
    project_root: Path,
    cache_dir: Path,
    browser_mode: str,
    headed: bool,
    browser_width: int,
    browser_height: int,
    color_scheme: str,
    artifacts_dir: Path,
    test_timeout: float,
    retained_iframes: int,
) -> None:
    daemon = PrototypeDaemon(
        host,
        port,
        idle_seconds,
        project_root,
        cache_dir,
        browser_mode,
        headed,
        browser_width,
        browser_height,
        color_scheme,
        artifacts_dir,
        test_timeout,
        retained_iframes,
    )
    loop = asyncio.get_running_loop()
    handled_signals: list[signal.Signals] = []
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, daemon.shutdown_event.set)
        except NotImplementedError:
            break
        handled_signals.append(shutdown_signal)
    application = Application(name="PyJS browser tests")
    application.get("/", daemon.runner_page)
    application.get("/bundle.js", daemon.bundle_javascript)
    application.get("/bundle.js.map", daemon.bundle_source_map)
    application.get("/bundle.css", daemon.bundle_css)
    application.get("/pyjs-vendor.js", daemon.vendor_javascript)
    application.get("/healthz", daemon.health)
    application.get("/shutdown", daemon.request_shutdown)
    application.websocket("/ws", daemon.handler)
    application.websocket("/control", daemon.handler)
    server = Server(application, host=host, port=port)
    daemon.port = server.server_port
    try:
        async with server:

            async def run_until_shutdown() -> None:
                monitor_task = asyncio.create_task(daemon.monitor_idle())
                try:
                    await daemon.shutdown_event.wait()
                finally:
                    monitor_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await monitor_task

            if browser_mode == "managed":
                async with Browser(headless=not headed, webgpu=True) as browser:
                    page = await browser.new_page()
                    daemon.managed_page = page
                    await page.set_viewport(browser_width, browser_height)
                    if color_scheme != "system":
                        await page.set_color_scheme(color_scheme)
                    await page.navigate(daemon.runner_url, timeout=120)
                    await run_until_shutdown()
            else:
                await run_until_shutdown()
    finally:
        for shutdown_signal in handled_signals:
            loop.remove_signal_handler(shutdown_signal)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--idle-seconds", type=int, default=120)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--cache-dir", type=Path, default=Path.cwd() / ".pytest_cache" / "pyjs")
    parser.add_argument("--browser-mode", choices=("system", "managed"), default="system")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--browser-width", type=int, default=1440)
    parser.add_argument("--browser-height", type=int, default=1000)
    parser.add_argument("--color-scheme", choices=("system", "light", "dark"), default="system")
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--test-timeout", type=float, default=30)
    parser.add_argument("--retained-iframes", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(
        async_main(
            args.host,
            args.port,
            args.idle_seconds,
            args.project_root,
            args.cache_dir,
            args.browser_mode,
            args.headed,
            args.browser_width,
            args.browser_height,
            args.color_scheme,
            args.artifacts_dir or args.cache_dir / "artifacts",
            args.test_timeout,
            args.retained_iframes,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
