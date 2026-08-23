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
        finally:
            stop_process(server)

    asyncio.run(run())
