import asyncio
import base64
import subprocess

import pytest
from websockets.exceptions import ConnectionClosedError

import pyjs.tooling.browser as browser
from pyjs.tooling.browser import (
    Browser,
    BrowserLaunchError,
    BrowserPage,
    CDPSession,
)


class BrowserProcess:
    def __init__(self, *, timeout: bool = False):
        self.running = True
        self.timeout = timeout
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("chrome", timeout)
        self.running = False
        return 0

    def kill(self):
        self.killed = True


class Session:
    def __init__(self):
        self.listeners = {}
        self.messages = []

    def listen(self, method, callback):
        self.listeners[method] = callback

    def unlisten(self, method, callback):
        if self.listeners.get(method) is callback:
            del self.listeners[method]

    async def send(self, method, params=None):
        self.messages.append((method, params))
        if method == "Page.captureScreenshot":
            return {"data": base64.b64encode(b"png").decode()}
        return {}


class RuntimeSession(Session):
    def __init__(self, values):
        super().__init__()
        self.values = iter(values)

    async def send(self, method, params=None):
        self.messages.append((method, params))
        if method == "Runtime.evaluate":
            return {"result": {"value": next(self.values)}}
        return {}


def test_browser_page_initialization_waits_for_execution_context():
    class NavigatingSession(Session):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def send(self, method, params=None):
            self.messages.append((method, params))
            if method == "Runtime.evaluate":
                self.attempts += 1
                if self.attempts < 3:
                    raise RuntimeError("Cannot find default execution context")
            return {}

    async def run():
        session = NavigatingSession()
        page = BrowserPage(session)

        await page.initialize()

        assert session.attempts == 3
        assert session.messages[:2] == [
            ("Page.enable", None),
            ("Runtime.enable", None),
        ]

    asyncio.run(run())


def test_browser_page_evaluation_waits_for_execution_context():
    class NavigatingSession(Session):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def send(self, method, params=None):
            self.messages.append((method, params))
            if method == "Runtime.evaluate":
                self.attempts += 1
                if self.attempts < 3:
                    raise RuntimeError("Cannot find default execution context")
                return {"result": {"value": "ready"}}
            return {}

    async def run():
        session = NavigatingSession()
        page = BrowserPage(session)

        assert await page.evaluate("document.readyState") == "ready"
        assert session.attempts == 3

    asyncio.run(run())


def test_browser_page_evaluation_does_not_retry_unrelated_runtime_errors():
    class BrokenSession(Session):
        async def send(self, method, params=None):
            raise RuntimeError("evaluation failed")

    async def run():
        page = BrowserPage(BrokenSession())

        with pytest.raises(RuntimeError, match="^evaluation failed$"):
            await page.evaluate("broken()")

    asyncio.run(run())


def test_browser_page_evaluation_times_out_without_an_execution_context():
    class NavigatingSession(Session):
        async def send(self, method, params=None):
            raise RuntimeError("Cannot find default execution context")

    async def run():
        page = BrowserPage(NavigatingSession())

        with pytest.raises(
            TimeoutError,
            match="^Timed out waiting for the page execution context$",
        ):
            await page._runtime_evaluate({}, timeout=0)

    asyncio.run(run())


def test_cdp_session_treats_connection_closure_as_normal_shutdown():
    class ClosedConnection:
        def __init__(self):
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ConnectionClosedError(None, None, None)

        async def close(self):
            self.closed = True

    async def run():
        connection = ClosedConnection()
        session = CDPSession(connection)
        pending = asyncio.get_running_loop().create_future()
        session.pending[1] = pending

        await session.reader

        assert session.reader.exception() is None
        with pytest.raises(ConnectionError, match="connection closed"):
            await pending
        await session.close()
        assert connection.closed

    asyncio.run(run())


def test_browser_page_captures_png_and_runtime_diagnostics(tmp_path):
    async def run():
        session = Session()
        page = BrowserPage(session)
        session.listeners["Runtime.consoleAPICalled"](
            {"type": "warning", "args": [{"value": "watch out"}]}
        )
        session.listeners["Runtime.exceptionThrown"](
            {"exceptionDetails": {"exception": {"description": "Error: broken"}}}
        )

        screenshot = await page.screenshot(tmp_path / "page.png")

        assert screenshot.read_bytes() == b"png"
        assert page.console == [{"level": "warning", "values": ["watch out"]}]
        assert page.exceptions == ["Error: broken"]
        assert session.messages == [
            (
                "Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": False},
            )
        ]

    asyncio.run(run())


def test_browser_page_captures_an_explicit_clip(tmp_path):
    async def run():
        session = Session()
        page = BrowserPage(session)
        clip = {"x": 1, "y": 2, "width": 30, "height": 40, "scale": 1}

        await page.screenshot(tmp_path / "clip.png", clip=clip)

        assert session.messages[-1] == (
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": clip,
            },
        )

    asyncio.run(run())


def test_browser_page_returns_a_clipped_screenshot_data_url():
    async def run():
        session = Session()
        page = BrowserPage(session)
        clip = {"x": 1, "y": 2, "width": 30, "height": 40, "scale": 1}

        data_url = await page.screenshot_data_url(clip)

        assert data_url == "data:image/png;base64,cG5n"
        assert session.messages[-1] == (
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": clip,
            },
        )

    asyncio.run(run())


def test_headless_webgpu_uses_software_adapter_without_a_system_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    instance = Browser(executable="chrome", webgpu=True)

    arguments = instance._launch_arguments(tmp_path)

    assert "--headless=new" in arguments
    assert "--enable-features=Vulkan" in arguments
    assert "--use-angle=swiftshader" in arguments
    assert "--use-vulkan=swiftshader" in arguments
    assert "--use-webgpu-adapter=swiftshader" in arguments
    assert "--disable-vulkan-surface" in arguments
    assert "--enable-unsafe-webgpu" in arguments


def test_headed_browser_does_not_enable_headless_webgpu_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    instance = Browser(executable="chrome", headless=False, webgpu=True)

    arguments = instance._launch_arguments(tmp_path)

    assert "--headless=new" not in arguments
    assert "--enable-unsafe-webgpu" not in arguments


def test_browser_appends_environment_and_explicit_launch_arguments(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "PYJS_CHROME_ARGS",
        '--disable-features=Translate "--host-resolver-rules=MAP app.test 127.0.0.1"',
    )
    instance = Browser(
        executable="chrome",
        extra_arguments=("--force-device-scale-factor=1",),
    )

    arguments = instance._launch_arguments(tmp_path)

    assert arguments[-4:] == [
        "--disable-features=Translate",
        "--host-resolver-rules=MAP app.test 127.0.0.1",
        "--force-device-scale-factor=1",
        "about:blank",
    ]
    assert "--no-sandbox" not in arguments


def test_browser_rejects_malformed_environment_arguments(monkeypatch):
    monkeypatch.setenv("PYJS_CHROME_ARGS", '"unterminated')

    with pytest.raises(RuntimeError, match="Invalid PYJS_CHROME_ARGS"):
        Browser(executable="chrome")


def test_browser_cleans_up_when_startup_is_cancelled(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    process = BrowserProcess()

    async def cancel_startup(url, timeout):
        raise asyncio.CancelledError

    monkeypatch.setattr(browser.tempfile, "mkdtemp", lambda prefix: str(profile))
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(browser, "wait_for_http", cancel_startup)

    async def run():
        instance = Browser(executable="chrome")
        with pytest.raises(asyncio.CancelledError):
            await instance.__aenter__()

        assert process.terminated
        assert instance.process is None
        assert instance.profile is None
        assert not profile.exists()

    asyncio.run(run())


def test_browser_cleans_up_when_chrome_cannot_start(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()

    def fail_to_start(*args, **kwargs):
        raise OSError("Chrome could not start")

    monkeypatch.setattr(browser.tempfile, "mkdtemp", lambda prefix: str(profile))
    monkeypatch.setattr(browser.subprocess, "Popen", fail_to_start)

    async def run():
        instance = Browser(executable="chrome")
        with pytest.raises(BrowserLaunchError, match="could not start") as caught:
            await instance.__aenter__()

        assert caught.value.executable == "chrome"
        assert caught.value.exit_code is None
        assert caught.value.devtools_url.endswith("/json/version")
        assert instance.process is None
        assert instance.profile is None
        assert not profile.exists()

    asyncio.run(run())


def test_browser_reports_an_early_exit_and_stderr(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    process = BrowserProcess()
    process.running = False

    def start(*args, **kwargs):
        kwargs["stderr"].write(b"first line\nGPU initialization failed\n")
        kwargs["stderr"].flush()
        return process

    async def wait_forever(url, timeout):
        await asyncio.Future()

    monkeypatch.setattr(browser.tempfile, "mkdtemp", lambda prefix: str(profile))
    monkeypatch.setattr(browser.subprocess, "Popen", start)
    monkeypatch.setattr(browser, "wait_for_http", wait_forever)

    async def run():
        instance = Browser(executable="chrome")
        with pytest.raises(BrowserLaunchError) as caught:
            await instance.__aenter__()

        error = caught.value
        assert error.reason == "Chrome exited before opening DevTools"
        assert error.exit_code == 0
        assert error.stderr == "first line\nGPU initialization failed"
        assert "--remote-debugging-port=" in str(error)
        assert "GPU initialization failed" in str(error)
        assert instance.process is None
        assert instance.profile is None
        assert not profile.exists()

    asyncio.run(run())


def test_browser_terminates_when_a_page_session_fails_to_close(tmp_path):
    class BrokenSession:
        def listen(self, method, callback):
            pass

        async def close(self):
            raise ConnectionError("Chrome connection closed")

    async def run():
        profile = tmp_path / "profile"
        profile.mkdir()
        process = BrowserProcess()
        instance = Browser(executable="chrome")
        instance.profile = profile
        instance.process = process
        instance.pages = [BrowserPage(BrokenSession())]

        await instance.close()

        assert process.terminated
        assert instance.pages == []
        assert instance.process is None
        assert instance.profile is None
        assert not profile.exists()

    asyncio.run(run())


def test_browser_kills_a_process_that_does_not_terminate(tmp_path):
    async def run():
        profile = tmp_path / "profile"
        profile.mkdir()
        process = BrowserProcess(timeout=True)
        instance = Browser(executable="chrome")
        instance.profile = profile
        instance.process = process

        await instance.close()

        assert process.terminated
        assert process.killed
        assert not profile.exists()

    asyncio.run(run())


def test_browser_closes_one_page_without_closing_the_other(monkeypatch):
    class ClosableSession:
        def __init__(self):
            self.closed = False

        def listen(self, method, callback):
            pass

        async def close(self):
            self.closed = True

    async def run():
        first = BrowserPage(ClosableSession(), "first")
        second = BrowserPage(ClosableSession(), "second")
        instance = Browser.__new__(Browser)
        instance.debug_port = 1234
        instance.pages = [first, second]
        requests = []
        monkeypatch.setattr(browser, "request", lambda url: requests.append(url))

        await instance.close_page(first)

        assert requests == ["http://127.0.0.1:1234/json/close/first"]
        assert first.session.closed
        assert instance.pages == [second]

    asyncio.run(run())


def test_browser_retries_a_cold_page_connection(monkeypatch):
    class ConnectedSession(Session):
        async def close(self):
            pass

    targets = iter(
        [
            {"id": "first", "webSocketDebuggerUrl": "ws://first"},
            {"id": "second", "webSocketDebuggerUrl": "ws://second"},
        ]
    )
    opened = []
    closed = []

    async def open_session(url):
        opened.append(url)
        if url == "ws://first":
            raise TimeoutError("cold browser")
        return ConnectedSession()

    async def no_delay(_delay):
        pass

    monkeypatch.setattr(browser, "request_json", lambda *args, **kwargs: next(targets))
    monkeypatch.setattr(browser.CDPSession, "open", open_session)
    monkeypatch.setattr(browser, "request", lambda url: closed.append(url))
    monkeypatch.setattr(browser.asyncio, "sleep", no_delay)

    async def run():
        instance = Browser.__new__(Browser)
        instance.debug_port = 1234
        instance.pages = []

        page = await instance.new_page()

        assert page.target_id == "second"
        assert instance.pages == [page]

    asyncio.run(run())

    assert opened == ["ws://first", "ws://second"]
    assert closed == ["http://127.0.0.1:1234/json/close/first"]


def test_browser_reports_the_final_page_connection_failure(monkeypatch):
    attempts = []
    closed = []

    def new_target(*args, **kwargs):
        target_id = str(len(attempts) + 1)
        return {"id": target_id, "webSocketDebuggerUrl": f"ws://{target_id}"}

    async def fail_to_open(url):
        attempts.append(url)
        raise TimeoutError(f"attempt {len(attempts)}")

    async def no_delay(_delay):
        pass

    monkeypatch.setattr(browser, "request_json", new_target)
    monkeypatch.setattr(browser.CDPSession, "open", fail_to_open)
    monkeypatch.setattr(browser, "request", lambda url: closed.append(url))
    monkeypatch.setattr(browser.asyncio, "sleep", no_delay)

    async def run():
        instance = Browser.__new__(Browser)
        instance.debug_port = 1234
        instance.pages = []

        with pytest.raises(TimeoutError, match="attempt 3"):
            await instance.new_page()

        assert instance.pages == []

    asyncio.run(run())

    assert attempts == ["ws://1", "ws://2", "ws://3"]
    assert closed == [
        "http://127.0.0.1:1234/json/close/1",
        "http://127.0.0.1:1234/json/close/2",
        "http://127.0.0.1:1234/json/close/3",
    ]


def test_browser_page_selector_helpers_return_python_values():
    async def run():
        session = RuntimeSession(
            [
                "connected",
                '["general", "product-design"]',
                "2 people",
                '["Alice", "Bob"]',
                None,
                None,
                None,
            ]
        )
        page = BrowserPage(session)

        assert await page.attribute("chat-app", "connection") == "connected"
        assert await page.attributes("[data-room]", "data-room") == [
            "general",
            "product-design",
        ]
        assert await page.text('[data-testid="member-count"]') == "2 people"
        assert await page.texts("[data-user]") == ["Alice", "Bob"]
        await page.click('[data-room="general"]')
        await page.fill('[data-testid="message-input"]', "Hello")
        await page.submit('[data-testid="message-input"]')

        expressions = [
            params["expression"]
            for method, params in session.messages
            if method == "Runtime.evaluate"
        ]
        assert "element.click()" in expressions[4]
        assert 'element.value = "Hello"' in expressions[5]
        assert "form.requestSubmit()" in expressions[6]

    asyncio.run(run())


def test_browser_page_selector_waits_use_readable_conditions():
    async def run():
        session = RuntimeSession([True, True, True, True])
        page = BrowserPage(session)

        await page.wait_for_selector("main")
        await page.wait_for_attribute("chat-app", "connection", "connected")
        await page.wait_for_count("[data-user]", 2)
        await page.wait_for_text('[data-testid="message-list"]', "Hello")

        expressions = [
            params["expression"]
            for method, params in session.messages
            if method == "Runtime.evaluate"
        ]
        assert 'document.querySelector("main") !== null' in expressions[0]
        assert 'getAttribute("connection") === "connected"' in expressions[1]
        assert 'document.querySelectorAll("[data-user]").length === 2' in expressions[2]
        assert 'textContent.includes("Hello")' in expressions[3]

    asyncio.run(run())


def test_browser_page_can_toggle_offline_network_conditions():
    async def run():
        session = Session()
        page = BrowserPage(session)

        await page.set_offline()
        await page.set_offline(False)

        assert session.messages == [
            ("Network.enable", None),
            (
                "Network.emulateNetworkConditions",
                {
                    "offline": True,
                    "latency": 0,
                    "downloadThroughput": -1,
                    "uploadThroughput": -1,
                    "connectionType": "none",
                },
            ),
            ("Network.enable", None),
            (
                "Network.emulateNetworkConditions",
                {
                    "offline": False,
                    "latency": 0,
                    "downloadThroughput": -1,
                    "uploadThroughput": -1,
                    "connectionType": "wifi",
                },
            ),
        ]

    asyncio.run(run())


def test_browser_page_drags_between_selector_positions():
    class DragSession(RuntimeSession):
        async def send(self, method, params=None):
            result = await super().send(method, params)
            if (
                method == "Input.dispatchMouseEvent"
                and params.get("type") == "mouseMoved"
                and params.get("buttons") == 1
                and "Input.dragIntercepted" in self.listeners
            ):
                self.listeners["Input.dragIntercepted"](
                    {"data": {"items": [], "dragOperationsMask": 16}}
                )
            return result

    async def run():
        session = DragSession(
            [
                '{"x":10,"y":20,"width":40,"height":60}',
                '{"x":110,"y":220,"width":80,"height":100}',
            ]
        )
        page = BrowserPage(session)

        await page.drag("[data-card=source]", "[data-card=target]", target_y_ratio=0.25, steps=2)

        mouse_events = [
            params
            for method, params in session.messages
            if method == "Input.dispatchMouseEvent"
        ]
        assert mouse_events == [
            {"type": "mouseMoved", "x": 30.0, "y": 50.0},
            {
                "type": "mousePressed",
                "x": 30.0,
                "y": 50.0,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
            {
                "type": "mouseMoved",
                "x": 90.0,
                "y": 147.5,
                "button": "left",
                "buttons": 1,
            },
            {
                "type": "mouseMoved",
                "x": 150.0,
                "y": 245.0,
                "button": "left",
                "buttons": 1,
            },
            {
                "type": "mouseReleased",
                "x": 150.0,
                "y": 245.0,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        ]
        drag_events = [
            params for method, params in session.messages if method == "Input.dispatchDragEvent"
        ]
        assert [event["type"] for event in drag_events] == ["dragEnter", "dragOver", "drop"]
        assert all(event["data"]["dragOperationsMask"] == 16 for event in drag_events)

    asyncio.run(run())
