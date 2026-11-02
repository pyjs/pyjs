import asyncio
import os
import subprocess
import sys

import pytest
from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, free_port, wait_for_http

pytestmark = pytest.mark.pyjs_python


def test_components_preserves_its_shell_during_partial_navigation():
    async def run():
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        environment = os.environ.copy()
        environment["PYJS_PORT"] = str(port)
        environment["PYTHONUNBUFFERED"] = "1"
        server = subprocess.Popen(
            [sys.executable, "-m", "pyjs_examples.components"],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            await wait_for_http(url, timeout=120)
            async with Browser() as browser:
                page = await browser.new_page(url)
                await page.wait_for_selector("components-app")
                await page.wait_for_selector("catalog-app")
                await page.wait_for(
                    "document.querySelector('components-app')._initialized === true",
                    "the components navigation shell to hydrate",
                )
                assert page.exceptions == []
                await page.evaluate(
                    "window.__componentsShell = document.querySelector('components-app')"
                )

                await page.click('a[href="/workspace"]')
                assert page.exceptions == []
                await page.wait_for_selector("workspace-app")

                assert await page.evaluate(
                    "document.querySelector('components-app') === "
                    "window.__componentsShell"
                ) is True
                assert await page.attribute(
                    'a[href="/workspace"]', "aria-current"
                ) == "page"
                assert await page.evaluate("location.pathname") == "/workspace"
                assert page.exceptions == []

                await page.click('a[href="/diagrams"]')
                await page.wait_for("document.querySelector('diagram-canvas')?._initialized === true",
                                    "the diagram surface to hydrate")
                assert page.exceptions == []
                assert await page.evaluate(
                    "document.querySelector('[aria-label=\"Node label\"]').hidden") is True
                node = '[data-node-id="question"]'
                original = await page.attribute(node, "transform")
                box = await page.selector_clip(node)
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                for phase, dx, dy in [("mousePressed", 0, 0), ("mouseMoved", 20, 15),
                                      ("mouseMoved", 40, 30), ("mouseReleased", 40, 30)]:
                    await page.session.send("Input.dispatchMouseEvent", {
                        "type": phase, "x": x + dx, "y": y + dy,
                        "button": "left", "buttons": 0 if phase == "mouseReleased" else 1,
                        "clickCount": 1,
                    })
                assert await page.attribute(node, "transform") != original
                await page.click('[data-diagram-action="undo"]')
                assert page.exceptions == []
                assert await page.attribute(node, "transform") == original
                assert await page.evaluate(
                    "document.querySelector('components-app') === window.__componentsShell") is True
                assert page.exceptions == []

                await page.session.send("Emulation.setDeviceMetricsOverride", {
                    "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": False,
                })
                await page.click('[data-diagram-action="fit"]')
                await page.wait_for_frames()
                assert await page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth") is True
                assert page.exceptions == []
        finally:
            stop_process(server)

    asyncio.run(run())
