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


async def board_state(page: BrowserPage) -> dict:
    return {
        "todo": await page.attributes('[data-testid="todo-cards"] > [data-card-id]', "data-card-id"),
        "inProgress": await page.attributes(
            '[data-testid="in-progress-cards"] > [data-card-id]', "data-card-id"
        ),
        "done": await page.attributes('[data-testid="done-cards"] > [data-card-id]', "data-card-id"),
        "counts": await page.texts("[data-column-count]"),
        "status": await page.text("[data-board-status]"),
        "activeDropZones": await page.attributes("[data-drag-over]", "data-testid"),
    }


async def exercise(page: BrowserPage) -> dict:
    await page.wait_for_selector("kanban-board", "the hydrated Kanban board")
    await page.drag(
        '[data-card-id="onboarding-audit"]',
        '[data-card-id="drag-drop"]',
        target_y_ratio=0.2,
    )
    await page.wait_for(
        "document.querySelector('[data-testid=\"in-progress-cards\"]')"
        "?.firstElementChild?.getAttribute('data-card-id') === 'onboarding-audit'",
        "the card to move through Chrome's native drag lifecycle",
    )
    await page.drag(
        '[data-card-id="launch-checklist"]',
        '[data-testid="done-cards"]',
        target_y_ratio=0.95,
    )
    await page.wait_for(
        "document.querySelector('[data-testid=\"done-cards\"]')"
        "?.lastElementChild?.getAttribute('data-card-id') === 'launch-checklist'",
        "a card dropped in the column's empty space",
    )

    result = await board_state(page)
    expected = {
        "todo": ["customer-interview"],
        "inProgress": ["onboarding-audit", "drag-drop", "empty-states"],
        "done": ["scope-release", "browser-runner", "launch-checklist"],
        "counts": ["1", "3", "3"],
        "status": "Write launch checklist moved to Done",
        "activeDropZones": [],
    }
    if result != expected:
        raise RuntimeError(f"Unexpected board state: {json.dumps(result)}")
    if page.exceptions:
        raise RuntimeError(f"Browser errors: {'; '.join(page.exceptions)}")

    await page.settle()
    await page.screenshot(OUTPUT / "kanban.png", selector="[data-kanban-board]")
    return result


async def main() -> None:
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    environment = os.environ.copy()
    environment["PYJS_PORT"] = str(port)
    with tempfile.TemporaryFile(mode="w+") as server_log:
        server = subprocess.Popen(
            [sys.executable, "kanban.py"],
            cwd=EXAMPLE_ROOT,
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
                (OUTPUT / "kanban.json").write_text(
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
