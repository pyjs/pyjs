import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, free_port, wait_for_http

pytestmark = pytest.mark.pyjs_python


def test_calculator_registers_python_service_worker_and_runs_offline():
    async def run():
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        environment = os.environ.copy()
        environment["PYJS_PORT"] = str(port)
        environment["PYTHONUNBUFFERED"] = "1"
        application = Path(__file__).parents[1] / "calculator.py"
        server = subprocess.Popen(
            [sys.executable, str(application)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            try:
                await wait_for_http(url, timeout=120)
            except TimeoutError as error:
                stop_process(server)
                output = server.stdout.read() if server.stdout is not None else ""
                raise TimeoutError(f"{error}\nServer output:\n{output}") from error
            async with Browser() as browser:
                page = await browser.new_page(url)
                await page.wait_for_selector("calculator-app")
                await page.wait_for(
                    "navigator.serviceWorker.controller !== null",
                    "the calculator service worker to control the page",
                )

                scope = await page.attribute("calculator-app", "data-service-worker")
                assert scope == url

                await page.navigate(url)
                await page.wait_for_selector('[data-testid="calculator-display"]')
                cached_urls = await page.evaluate(
                    "(async () => {"
                    " const cache = await caches.open('pyjs-calculator-v1');"
                    " return (await cache.keys()).map((request) => request.url);"
                    "})()"
                )
                assert url in cached_urls
                assert any(cached_url.endswith(".js") for cached_url in cached_urls)

                await page.set_offline()
                await page.navigate(url)
                await page.wait_for_selector('[data-testid="calculator-display"]')
                await page.click('[data-key="7"]')
                assert await page.text('[data-testid="calculator-display"]') == "7"
                assert page.exceptions == []
        finally:
            stop_process(server)

    asyncio.run(run())
