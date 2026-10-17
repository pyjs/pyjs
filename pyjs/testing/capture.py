"""Repeatable browser screenshots with retained diagnostic state."""

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pyjs.tooling.browser import Browser


@dataclass
class CaptureResult:
    screenshots: list[Path]
    diagnostics: Path

    def json(self) -> dict[str, object]:
        return {
            "screenshots": [str(path) for path in self.screenshots],
            "diagnostics": str(self.diagnostics),
        }


def _sequence_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.stem}-{index:03d}{path.suffix}")


async def capture_url(
    url: str,
    output: Path,
    *,
    width: int = 1280,
    height: int = 800,
    scale: float = 1,
    color_scheme: str | None = None,
    wait_for_selector: str | None = None,
    selector: str | None = None,
    delay: float = 0,
    frames: int = 2,
    full_page: bool = False,
    settle: bool = True,
    interval: float | None = None,
    duration: float | None = None,
    headed: bool = False,
) -> CaptureResult:
    if (interval is None) != (duration is None):
        raise ValueError("interval and duration must be used together")
    if interval is not None and (interval <= 0 or duration <= 0):
        raise ValueError("interval and duration must be positive")

    output = output.resolve()
    screenshots: list[Path] = []
    async with Browser(headless=not headed) as browser:
        page = await browser.new_page()
        await page.set_viewport(width, height, scale=scale)
        if color_scheme:
            await page.set_color_scheme(color_scheme)
        await page.navigate(url)
        if wait_for_selector:
            selector_source = json.dumps(wait_for_selector)
            await page.wait_for(
                f"document.querySelector({selector_source}) !== null",
                f"selector {wait_for_selector!r}",
            )
        await page.wait_for_frames(frames)
        if delay:
            await asyncio.sleep(delay)

        if interval is None:
            if settle:
                await page.settle()
            screenshots.append(
                await page.screenshot(output, selector=selector, full_page=full_page)
            )
        else:
            if duration is None:
                raise ValueError("duration is required for repeated captures")
            started = asyncio.get_running_loop().time()
            index = 0
            while True:
                screenshots.append(
                    await page.screenshot(
                        _sequence_path(output, index),
                        selector=selector,
                        full_page=full_page,
                    )
                )
                elapsed = asyncio.get_running_loop().time() - started
                if elapsed >= duration:
                    break
                await asyncio.sleep(min(interval, duration - elapsed))
                index += 1

        diagnostics = output.with_suffix(".json")
        state = await page.inspect()
        state["capture"] = {
            **asdict(
                _CaptureSettings(
                    url,
                    width,
                    height,
                    scale,
                    color_scheme,
                    wait_for_selector,
                    selector,
                    delay,
                    frames,
                    full_page,
                    settle,
                    interval,
                    duration,
                )
            ),
            "screenshots": [str(path) for path in screenshots],
        }
        diagnostics.parent.mkdir(parents=True, exist_ok=True)
        diagnostics.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    return CaptureResult(screenshots, diagnostics)


@dataclass
class _CaptureSettings:
    url: str
    width: int
    height: int
    scale: float
    color_scheme: str | None
    wait_for_selector: str | None
    selector: str | None
    delay: float
    frames: int
    full_page: bool
    settle: bool
    interval: float | None
    duration: float | None
