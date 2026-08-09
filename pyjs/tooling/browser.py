import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from websockets.asyncio.client import ClientConnection, connect


def browser_executable() -> str:
    candidates = [
        os.environ.get("CHROME_BIN"),
        "google-chrome",
        "chromium",
        "chromium-browser",
        "/snap/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if executable := shutil.which(candidate):
            return executable
    raise RuntimeError("Chrome or Chromium was not found. Set CHROME_BIN to its executable.")


def free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def request(url: str, method: str = "GET") -> bytes:
    with urlopen(Request(url, method=method), timeout=2) as response:
        return response.read()


def request_json(url: str, method: str = "GET") -> dict[str, Any]:
    return json.loads(request(url, method))


async def wait_for_http(url: str, timeout: float = 15) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            with urlopen(url, timeout=remaining) as response:
                if response.status < 400:
                    return
        except OSError, URLError:
            pass
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {url}")


class CDPSession:
    def __init__(self, connection: ClientConnection):
        self.connection = connection
        self.next_id = 1
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.listeners: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self.reader = asyncio.create_task(self._read_messages())

    @classmethod
    async def open(cls, url: str) -> CDPSession:
        return cls(await connect(url, max_size=None))

    async def _read_messages(self) -> None:
        try:
            async for raw_message in self.connection:
                message = json.loads(raw_message)
                message_id = message.get("id")
                if isinstance(message_id, int):
                    future = self.pending.pop(message_id, None)
                    if future is None:
                        continue
                    if error := message.get("error"):
                        future.set_exception(RuntimeError(error.get("message", str(error))))
                    else:
                        future.set_result(message.get("result", {}))
                    continue
                for listener in self.listeners.get(message.get("method", ""), ()):
                    listener(message.get("params", {}))
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Chrome DevTools connection closed"))
            self.pending.clear()

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = self.next_id
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[message_id] = future
        await self.connection.send(
            json.dumps({"id": message_id, "method": method, "params": params or {}})
        )
        return await future

    def listen(self, method: str, callback: Callable[[dict[str, Any]], None]) -> None:
        self.listeners.setdefault(method, []).append(callback)

    def unlisten(self, method: str, callback: Callable[[dict[str, Any]], None]) -> None:
        callbacks = self.listeners.get(method)
        if callbacks is not None and callback in callbacks:
            callbacks.remove(callback)

    async def close(self) -> None:
        await self.connection.close()
        await self.reader


class BrowserPage:
    def __init__(self, session: CDPSession, target_id: str = ""):
        self.session = session
        self.target_id = target_id
        self.exceptions: list[str] = []
        self.console: list[dict[str, Any]] = []
        session.listen("Runtime.exceptionThrown", self._record_exception)
        session.listen("Runtime.consoleAPICalled", self._record_console)

    async def initialize(self) -> None:
        await self.session.send("Page.enable")
        await self.session.send("Runtime.enable")

    def _record_exception(self, params: dict[str, Any]) -> None:
        detail = params.get("exceptionDetails", {})
        exception = detail.get("exception", {})
        self.exceptions.append(
            exception.get("description") or detail.get("text") or "Unknown error"
        )

    def _record_console(self, params: dict[str, Any]) -> None:
        values = []
        for argument in params.get("args", []):
            values.append(argument.get("value", argument.get("description", "")))
        self.console.append({"level": params.get("type", "log"), "values": values})

    async def evaluate(self, expression: str, *, user_gesture: bool = False) -> Any:
        result = await self.session.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": user_gesture,
            },
        )
        if detail := result.get("exceptionDetails"):
            exception = detail.get("exception", {})
            raise RuntimeError(exception.get("description") or detail.get("text") or expression)
        return result.get("result", {}).get("value")

    async def evaluate_json(self, expression: str) -> Any:
        value = await self.evaluate(f"JSON.stringify({expression})")
        return json.loads(value) if value is not None else None

    async def wait_for(
        self,
        expression: str,
        description: str,
        *,
        timeout: float = 15,
        interval: float = 0.1,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if await self.evaluate(expression):
                return
            await asyncio.sleep(interval)
        raise TimeoutError(f"Timed out waiting for {description}")

    async def wait_for_selector(
        self,
        selector: str,
        description: str | None = None,
        *,
        timeout: float = 15,
    ) -> None:
        await self.wait_for(
            f"document.querySelector({json.dumps(selector)}) !== null",
            description or f"selector {selector!r}",
            timeout=timeout,
        )

    async def wait_for_attribute(
        self,
        selector: str,
        name: str,
        value: str,
        description: str | None = None,
        *,
        timeout: float = 15,
    ) -> None:
        await self.wait_for(
            f"document.querySelector({json.dumps(selector)})"
            f"?.getAttribute({json.dumps(name)}) === {json.dumps(value)}",
            description or f"{selector!r} attribute {name!r} to equal {value!r}",
            timeout=timeout,
        )

    async def wait_for_count(
        self,
        selector: str,
        count: int,
        description: str | None = None,
        *,
        timeout: float = 15,
    ) -> None:
        await self.wait_for(
            f"document.querySelectorAll({json.dumps(selector)}).length === {count}",
            description or f"{count} matches for selector {selector!r}",
            timeout=timeout,
        )

    async def wait_for_text(
        self,
        selector: str,
        text: str,
        description: str | None = None,
        *,
        timeout: float = 15,
    ) -> None:
        await self.wait_for(
            f"document.querySelector({json.dumps(selector)})"
            f"?.textContent.includes({json.dumps(text)})",
            description or f"{selector!r} to contain {text!r}",
            timeout=timeout,
        )

    async def click(self, selector: str) -> None:
        selector_source = json.dumps(selector)
        await self.evaluate(
            f"""(() => {{
                const element = document.querySelector({selector_source});
                if (!element) throw new Error('Could not find selector: ' + {selector_source});
                element.click();
            }})()""",
            user_gesture=True,
        )

    async def drag(
        self,
        source: str,
        target: str,
        *,
        target_x_ratio: float = 0.5,
        target_y_ratio: float = 0.5,
        steps: int = 12,
    ) -> None:
        if steps < 1:
            raise ValueError("steps must be at least 1")
        if not 0 <= target_x_ratio <= 1 or not 0 <= target_y_ratio <= 1:
            raise ValueError("target ratios must be between 0 and 1")

        source_bounds = await self._selector_bounds(source)
        target_bounds = await self._selector_bounds(target)
        source_x = source_bounds["x"] + source_bounds["width"] / 2
        source_y = source_bounds["y"] + source_bounds["height"] / 2
        target_x = target_bounds["x"] + target_bounds["width"] * target_x_ratio
        target_y = target_bounds["y"] + target_bounds["height"] * target_y_ratio

        drag_intercepted = asyncio.get_running_loop().create_future()

        def capture_drag(params: dict[str, Any]) -> None:
            if not drag_intercepted.done():
                drag_intercepted.set_result(params["data"])

        self.session.listen("Input.dragIntercepted", capture_drag)
        await self.session.send("Input.setInterceptDrags", {"enabled": True})
        try:
            try:
                await self.session.send(
                    "Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": source_x, "y": source_y},
                )
                await self.session.send(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mousePressed",
                        "x": source_x,
                        "y": source_y,
                        "button": "left",
                        "buttons": 1,
                        "clickCount": 1,
                    },
                )
                for step in range(1, steps + 1):
                    progress = step / steps
                    await self.session.send(
                        "Input.dispatchMouseEvent",
                        {
                            "type": "mouseMoved",
                            "x": source_x + (target_x - source_x) * progress,
                            "y": source_y + (target_y - source_y) * progress,
                            "button": "left",
                            "buttons": 1,
                        },
                    )
                drag_data = await asyncio.wait_for(drag_intercepted, 2)
            finally:
                await self.session.send("Input.setInterceptDrags", {"enabled": False})
                self.session.unlisten("Input.dragIntercepted", capture_drag)

            for event_type in ("dragEnter", "dragOver", "drop"):
                await self.session.send(
                    "Input.dispatchDragEvent",
                    {"type": event_type, "x": target_x, "y": target_y, "data": drag_data},
                )
        finally:
            await self.session.send(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    "x": target_x,
                    "y": target_y,
                    "button": "left",
                    "buttons": 0,
                    "clickCount": 1,
                },
            )

    async def _selector_bounds(self, selector: str) -> dict[str, float]:
        bounds = await self.evaluate_json(
            f"""(() => {{
                const element = document.querySelector({json.dumps(selector)});
                if (!element) throw new Error('Could not find selector: ' + {json.dumps(selector)});
                const bounds = element.getBoundingClientRect();
                return {{x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height}};
            }})()"""
        )
        if not bounds or bounds["width"] <= 0 or bounds["height"] <= 0:
            raise RuntimeError(f"Selector {selector!r} has no visible geometry")
        return bounds

    async def fill(self, selector: str, value: str) -> None:
        selector_source = json.dumps(selector)
        await self.evaluate(
            f"""(() => {{
                const element = document.querySelector({selector_source});
                if (!element) throw new Error('Could not find selector: ' + {selector_source});
                element.value = {json.dumps(value)};
                element.dispatchEvent(new Event('input', {{bubbles: true}}));
                element.dispatchEvent(new Event('change', {{bubbles: true}}));
            }})()"""
        )

    async def submit(self, selector: str) -> None:
        selector_source = json.dumps(selector)
        await self.evaluate(
            f"""(() => {{
                const element = document.querySelector({selector_source});
                if (!element) throw new Error('Could not find selector: ' + {selector_source});
                const form = element.closest('form');
                if (!form) throw new Error('Selector is not inside a form: ' + {selector_source});
                form.requestSubmit();
            }})()"""
        )

    async def attribute(self, selector: str, name: str) -> str | None:
        selector_source = json.dumps(selector)
        return await self.evaluate(
            f"""(() => {{
                const element = document.querySelector({selector_source});
                if (!element) throw new Error('Could not find selector: ' + {selector_source});
                return element.getAttribute({json.dumps(name)});
            }})()"""
        )

    async def attributes(self, selector: str, name: str) -> list[str | None]:
        return await self.evaluate_json(
            f"Array.from(document.querySelectorAll({json.dumps(selector)}))"
            f".map((element) => element.getAttribute({json.dumps(name)}))"
        )

    async def text(self, selector: str) -> str:
        selector_source = json.dumps(selector)
        return await self.evaluate(
            f"""(() => {{
                const element = document.querySelector({selector_source});
                if (!element) throw new Error('Could not find selector: ' + {selector_source});
                return element.textContent || '';
            }})()"""
        )

    async def texts(self, selector: str) -> list[str]:
        return await self.evaluate_json(
            f"Array.from(document.querySelectorAll({json.dumps(selector)}))"
            ".map((element) => element.textContent || '')"
        )

    async def navigate(self, url: str, *, timeout: float = 15) -> None:
        await self.session.send("Page.navigate", {"url": url})
        await self.wait_for("document.readyState === 'complete'", url, timeout=timeout)

    async def bring_to_front(self) -> None:
        await self.session.send("Page.bringToFront")

    async def set_viewport(
        self,
        width: int,
        height: int,
        *,
        scale: float = 1,
        mobile: bool = False,
    ) -> None:
        await self.session.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": scale,
                "mobile": mobile,
            },
        )

    async def set_color_scheme(self, color_scheme: str) -> None:
        await self.session.send(
            "Emulation.setEmulatedMedia",
            {
                "features": [
                    {"name": "prefers-color-scheme", "value": color_scheme},
                ]
            },
        )

    async def set_offline(self, offline: bool = True) -> None:
        await self.session.send("Network.enable")
        await self.session.send(
            "Network.emulateNetworkConditions",
            {
                "offline": offline,
                "latency": 0,
                "downloadThroughput": -1,
                "uploadThroughput": -1,
                "connectionType": "none" if offline else "wifi",
            },
        )

    async def clear_viewport(self) -> None:
        await self.session.send("Emulation.clearDeviceMetricsOverride")

    async def grant_permissions(self, origin: str, permissions: list[str]) -> None:
        await self.session.send(
            "Browser.grantPermissions",
            {"origin": origin, "permissions": permissions},
        )

    async def wait_for_frames(self, count: int = 2) -> None:
        if count <= 0:
            return
        await self.evaluate(
            f"""new Promise((resolve) => {{
                let remaining = {count};
                const next = () => {{
                    remaining -= 1;
                    if (remaining <= 0) resolve(true);
                    else requestAnimationFrame(next);
                }};
                requestAnimationFrame(next);
            }})"""
        )

    async def settle(self, timeout: float = 2) -> None:
        milliseconds = round(timeout * 1000)
        await self.evaluate(
            f"""(async () => {{
                if (document.fonts) await document.fonts.ready;
                const images = Array.from(document.images).filter((image) => !image.complete);
                await Promise.all(images.map((image) => new Promise((resolve) => {{
                    image.addEventListener('load', resolve, {{once: true}});
                    image.addEventListener('error', resolve, {{once: true}});
                }})));
                const animations = document.getAnimations().filter((animation) => {{
                    const timing = animation.effect?.getTiming();
                    return timing && timing.iterations !== Infinity;
                }});
                await Promise.race([
                    Promise.all(animations.map((animation) => animation.finished.catch(() => null))),
                    new Promise((resolve) => setTimeout(resolve, {milliseconds})),
                ]);
                await new Promise((resolve) =>
                    requestAnimationFrame(() => requestAnimationFrame(resolve)));
                return true;
            }})()"""
        )

    async def selector_clip(self, selector: str) -> dict[str, float]:
        clip = await self.evaluate_json(
            f"""(() => {{
                const element = document.querySelector({json.dumps(selector)});
                if (!element) throw new Error('Could not find selector: ' + {json.dumps(selector)});
                const bounds = element.getBoundingClientRect();
                return {{
                    x: window.scrollX + bounds.left,
                    y: window.scrollY + bounds.top,
                    width: bounds.width,
                    height: bounds.height,
                    scale: 1,
                }};
            }})()"""
        )
        if not clip or clip["width"] <= 0 or clip["height"] <= 0:
            raise RuntimeError(f"Selector {selector!r} has no visible geometry")
        return clip

    async def screenshot(
        self,
        path: Path,
        *,
        selector: str | None = None,
        clip: dict[str, float] | None = None,
        full_page: bool = False,
    ) -> Path:
        if selector is not None and clip is not None:
            raise ValueError("selector and clip cannot be used together")
        params: dict[str, Any] = {
            "format": "png",
            "captureBeyondViewport": full_page or selector is not None or clip is not None,
        }
        if selector is not None:
            params["clip"] = await self.selector_clip(selector)
        elif clip is not None:
            params["clip"] = clip
        result = await self.session.send("Page.captureScreenshot", params)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(result["data"]))
        return path

    async def screenshot_data_url(self, clip: dict[str, float]) -> str:
        result = await self.session.send(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": clip,
            },
        )
        return "data:image/png;base64," + result["data"]

    async def inspect(self) -> dict[str, Any]:
        state = await self.evaluate_json(
            """(() => {
                const describe = (element) => {
                    const bounds = element.getBoundingClientRect();
                    return {
                        tag: element.tagName.toLowerCase(),
                        id: element.id || '',
                        testId: element.getAttribute('data-testid') || '',
                        role: element.getAttribute('role') || '',
                        label: element.getAttribute('aria-label') || '',
                        text: (element.innerText || element.value || '').trim().slice(0, 500),
                        disabled: Boolean(element.disabled),
                        bounds: {
                            x: bounds.x,
                            y: bounds.y,
                            width: bounds.width,
                            height: bounds.height,
                        },
                    };
                };
                return {
                    url: location.href,
                    title: document.title,
                    viewport: {width: innerWidth, height: innerHeight},
                    document: {
                        width: document.documentElement.scrollWidth,
                        height: document.documentElement.scrollHeight,
                    },
                    colorScheme: matchMedia('(prefers-color-scheme: dark)').matches
                        ? 'dark'
                        : 'light',
                    visibleText: (document.body?.innerText || '').trim().slice(0, 20000),
                    elements: Array.from(document.querySelectorAll(
                        'a, button, input, select, textarea, [role], [data-testid]'
                    )).slice(0, 500).map(describe),
                };
            })()"""
        )
        state["exceptions"] = self.exceptions
        state["console"] = self.console
        return state


class Browser:
    def __init__(
        self,
        *,
        executable: str | None = None,
        headless: bool = True,
        webgpu: bool = False,
    ):
        self.executable = executable or browser_executable()
        self.headless = headless
        self.webgpu = webgpu
        self.debug_port = free_port()
        self.profile: Path | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.pages: list[BrowserPage] = []

    def _launch_arguments(self, profile: Path) -> list[str]:
        arguments = [self.executable]
        if self.headless:
            arguments.append("--headless=new")
            if self.webgpu and sys.platform.startswith("linux"):
                arguments.extend(
                    [
                        "--enable-features=Vulkan",
                        "--use-angle=swiftshader",
                        "--use-vulkan=swiftshader",
                        "--use-webgpu-adapter=swiftshader",
                        "--disable-vulkan-surface",
                        "--enable-unsafe-webgpu",
                    ]
                )
        arguments.extend(
            [
                f"--remote-debugging-port={self.debug_port}",
                f"--user-data-dir={profile}",
                "--hide-scrollbars",
                "about:blank",
            ]
        )
        return arguments

    async def __aenter__(self) -> Browser:
        self.profile = Path(tempfile.mkdtemp(prefix="pyjs-browser-"))
        self.process = subprocess.Popen(
            self._launch_arguments(self.profile),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            await wait_for_http(
                f"http://127.0.0.1:{self.debug_port}/json/version",
                timeout=30,
            )
        except Exception:
            await self.close()
            raise
        return self

    async def new_page(self, url: str = "about:blank") -> BrowserPage:
        target = request_json(
            f"http://127.0.0.1:{self.debug_port}/json/new?{quote(url, safe='')}",
            method="PUT",
        )
        page = BrowserPage(
            await CDPSession.open(target["webSocketDebuggerUrl"]),
            target["id"],
        )
        await page.initialize()
        self.pages.append(page)
        return page

    async def close_page(self, page: BrowserPage) -> None:
        if page not in self.pages:
            return
        await asyncio.to_thread(
            request,
            f"http://127.0.0.1:{self.debug_port}/json/close/{page.target_id}",
        )
        await page.session.close()
        self.pages.remove(page)

    async def close(self) -> None:
        for page in self.pages:
            await page.session.close()
        self.pages.clear()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait)
        self.process = None
        if self.profile is not None:
            shutil.rmtree(self.profile, ignore_errors=True)
        self.profile = None

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()
