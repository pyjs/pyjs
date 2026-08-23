#!/usr/bin/env python3

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, BrowserPage, free_port, wait_for_http

EXAMPLE_ROOT = Path(__file__).resolve().parent
OUTPUT = Path.cwd() / "screenshots"


async def notes_state(page: BrowserPage) -> dict:
    return {
        "notes": await page.attributes(
            '[data-testid="notes-cards"] > [data-card-id]', "data-card-id"
        ),
        "pinned": await page.attributes(
            '[data-testid="pinned-cards"] > [data-card-id]', "data-card-id"
        ),
        "archive": await page.attributes(
            '[data-testid="archive-cards"] > [data-card-id]', "data-card-id"
        ),
        "counts": await page.texts("[data-column-count]"),
        "status": await page.text("[data-board-status]"),
        "activeDropZones": await page.attributes("[data-drag-over]", "data-testid"),
    }


async def exercise(page: BrowserPage) -> dict:
    await page.wait_for_selector("web-notes-app", "the hydrated notes board")
    await page.drag(
        '[data-card-id="groceries"]',
        '[data-card-id="launch"]',
        target_y_ratio=0.2,
    )
    await page.wait_for(
        "document.querySelector('[data-testid=\"pinned-cards\"]')"
        "?.firstElementChild?.getAttribute('data-card-id') === 'groceries'",
        "the note to move through Chrome's native drag lifecycle",
    )
    await page.drag(
        '[data-card-id="design"]',
        '[data-testid="archive-cards"]',
        target_y_ratio=0.95,
    )
    await page.wait_for(
        "document.querySelector('[data-testid=\"archive-cards\"]')"
        "?.lastElementChild?.getAttribute('data-card-id') === 'design'",
        "a note dropped in the section's empty space",
    )

    result = await notes_state(page)
    expected = {
        "notes": ["reading"],
        "pinned": ["groceries", "launch", "weekend"],
        "archive": ["recipe", "quote", "design"],
        "counts": ["1", "3", "3"],
        "status": "Design notes moved to Archive",
        "activeDropZones": [],
    }
    if result != expected:
        raise RuntimeError(f"Unexpected board state: {json.dumps(result)}")
    if page.exceptions:
        raise RuntimeError(f"Browser errors: {'; '.join(page.exceptions)}")

    await page.settle()
    await page.screenshot(OUTPUT / "notes.png", selector="[data-notes-board]")
    return result


async def main() -> None:
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    environment = os.environ.copy()
    environment["PYJS_PORT"] = str(port)
    with tempfile.TemporaryFile(mode="w+") as server_log:
        server = subprocess.Popen(
            [sys.executable, "-m", "pyjs_examples.notes", "--web"],
            cwd=EXAMPLE_ROOT.parents[1],
            env=environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            await wait_for_http(url, timeout=20)
            async with Browser() as browser:
                page = await browser.new_page(url)
                await page.set_viewport(1440, 1000)
                result = await exercise(page)
                OUTPUT.mkdir(parents=True, exist_ok=True)
                (OUTPUT / "notes.json").write_text(
                    json.dumps(result, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(json.dumps(result, indent=2))
        except BaseException:
            stop_process(server)
            server_log.seek(0)
            sys.stderr.write(server_log.read())
            raise
        finally:
            stop_process(server)


if __name__ == "__main__":
    asyncio.run(main())
