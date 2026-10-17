import asyncio
import json

import pyjs.testing.capture as capture


class Page:
    def __init__(self):
        self.calls = []

    async def set_viewport(self, width, height, *, scale):
        self.calls.append(("viewport", width, height, scale))

    async def set_color_scheme(self, color_scheme):
        self.calls.append(("color_scheme", color_scheme))

    async def navigate(self, url):
        self.calls.append(("navigate", url))

    async def wait_for(self, expression, description):
        self.calls.append(("wait_for", expression, description))

    async def wait_for_frames(self, frames):
        self.calls.append(("frames", frames))

    async def settle(self):
        self.calls.append(("settle",))

    async def screenshot(self, path, *, selector, full_page):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        self.calls.append(("screenshot", path, selector, full_page))
        return path

    async def inspect(self):
        return {"visibleText": "Hello", "exceptions": [], "console": []}


class Browser:
    page = Page()

    def __init__(self, *, headless):
        assert headless

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        pass

    async def new_page(self):
        return self.page


def test_capture_url_writes_screenshot_and_diagnostics(tmp_path, monkeypatch):
    Browser.page = Page()
    monkeypatch.setattr(capture, "Browser", Browser)
    output = tmp_path / "capture.png"

    result = asyncio.run(
        capture.capture_url(
            "http://localhost:8000",
            output,
            width=390,
            height=844,
            color_scheme="dark",
            wait_for_selector="main",
            selector="main",
        )
    )

    assert result.screenshots == [output.resolve()]
    assert output.read_bytes() == b"png"
    diagnostics = json.loads(result.diagnostics.read_text())
    assert diagnostics["visibleText"] == "Hello"
    assert diagnostics["capture"]["width"] == 390
    assert diagnostics["capture"]["screenshots"] == [str(output.resolve())]
    assert ("color_scheme", "dark") in Browser.page.calls
    assert ("settle",) in Browser.page.calls
