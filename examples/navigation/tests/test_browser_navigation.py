import asyncio
import os
import subprocess
import sys

import pytest
from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, free_port, wait_for_http

pytestmark = pytest.mark.pyjs_python


def test_navigation_preserves_the_shell_and_hydrates_replaced_pages():
    async def run():
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        environment = os.environ.copy()
        environment["PYJS_PORT"] = str(port)
        environment["PYTHONUNBUFFERED"] = "1"
        server = subprocess.Popen(
            [sys.executable, "-m", "pyjs_examples.navigation"],
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
                await page.wait_for_selector("atlas-layout")
                await page.wait_for(
                    "document.querySelector('atlas-layout')._initialized === true",
                    "the navigation layout to hydrate",
                )
                await page.evaluate(
                    "window.__initialLayout = document.querySelector('atlas-layout')"
                )

                await page.click('[data-navigation-link="projects"]')
                await page.wait_for_text("h1", "Projects")
                assert await page.evaluate("location.pathname") == "/projects"
                assert await page.evaluate("document.title") == "Projects · Atlas"
                assert await page.evaluate(
                    "window.__initialLayout === document.querySelector('atlas-layout')"
                )
                assert await page.text("[data-navigation-count-label]") == "1"
                assert await page.attribute(
                    '[data-navigation-link="projects"]', "aria-current"
                ) == "page"

                await page.click('[data-navigation-link="settings"]')
                await page.wait_for_selector("preferences-panel")
                assert await page.text("[data-navigation-count-label]") == "2"
                await page.click("[data-preference-toggle]")
                assert await page.text("[data-preference-state]") == "Disabled"

                await page.evaluate("history.back()")
                await page.wait_for_text("h1", "Projects")
                assert await page.evaluate("location.pathname") == "/projects"
                assert await page.text("[data-navigation-count-label]") == "3"

                await page.set_viewport(390, 844, mobile=True)
                assert await page.evaluate(
                    "getComputedStyle(document.querySelector('[data-mobile-navigation]'))"
                    ".display !== 'none'"
                )
                assert await page.evaluate(
                    "getComputedStyle("
                    "document.querySelector('[data-navigation-sidebar]'))"
                    ".display === 'none'"
                )
                assert page.exceptions == []
        finally:
            stop_process(server)

    asyncio.run(run())
