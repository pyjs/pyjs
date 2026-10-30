import asyncio
import os
import subprocess
import sys
import textwrap
from urllib.request import urlopen

import pytest

from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, free_port, wait_for_http

pytestmark = pytest.mark.pyjs_python


@pytest.mark.parametrize("proxy_factory", [False, True, "local", "dynamic"])
def test_server_effect_output_hydrates_without_repeating_initial_work(tmp_path, proxy_factory):
    application = tmp_path / "effect_application.py"
    application.write_text(
        textwrap.dedent(
            """\
            import os

            from pyjs import effect, js, state
            from pyjs.server.dev import serve
            from pyjs.web.domx import CustomElement, button, ref, tag
            from pyjs.web.events import Event


            @js
            class EffectProbe(CustomElement):
                value = state(7)

                def __init__(self):
                    super().__init__()
                    self.result = ref(tag("output", "7"))
                    self.increment_button = ref(button("+"))
                    self.increment_button.addEventListener("click", self.increment)
                    tag(self, self.result, self.increment_button)

                @effect(value)
                def render_value(self):
                    self.result.textContent = str(self.value)
                    previous = self.get_data("effect-runs")
                    runs = 0 if previous is None else int(previous)
                    self.set_data("effect-runs", str(runs + 1))

                def increment(self, event: Event):
                    self.value += 1


            def main():
                return EffectProbe()


            if __name__ == "__main__":
                serve(__file__, port=int(os.environ["PYJS_PORT"]))
            """
        ),
        encoding="utf-8",
    )

    if proxy_factory:
        (tmp_path / "controls.py").write_text(
            "from pyjs import js\nfrom pyjs.web.ui.button import Button\n"
            "@js\ndef make_button(label: str) -> Button:\n    return Button(label)\n"
        )
        application.write_text(application.read_text().replace(
            "from pyjs.web.events import Event", "from controls import make_button\nfrom pyjs.web.events import Event"
        ).replace('ref(button("+"))', 'ref(make_button("+"))').replace(
            'self.increment_button.addEventListener("click", self.increment)',
            'self.increment_button.on_click(self.increment)',
        ))

    if proxy_factory == "local":
        application.write_text(application.read_text().replace(
            "from controls import make_button",
            "from pyjs.web.ui.button import Button\n"
            "@js\nclass LocalButton(Button):\n    pass\n"
            "@js\ndef make_button(label: str) -> LocalButton:\n    return LocalButton(label)\n",
        ))

    if proxy_factory == "dynamic":
        application.write_text(application.read_text().replace(
            'self.value += 1', 'self.value += 1\n        tag(self, make_button("Created"))'
        ))

    async def run():
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        environment = os.environ.copy()
        environment["PYJS_PORT"] = str(port)
        server = subprocess.Popen(
            [sys.executable, str(application)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            await wait_for_http(url, timeout=120)
            with urlopen(url, timeout=10) as response:
                server_html = response.read().decode("utf-8")

            assert 'data-effect-runs="1"' in server_html
            assert ">7</output>" in server_html

            async with Browser() as browser:
                page = await browser.new_page(url)
                await page.wait_for(
                    "document.querySelector('effect-probe')?._initialized === true",
                    "the effect probe to hydrate",
                )
                assert await page.attribute(
                    "effect-probe", "data-effect-runs"
                ) == "1"
                assert await page.text("effect-probe output") == "7"

                await page.click("effect-probe button")
                await page.wait_for_attribute(
                    "effect-probe", "data-effect-runs", "2"
                )
                assert await page.text("effect-probe output") == "8"
                if proxy_factory == "dynamic":
                    await page.wait_for_count('effect-probe button', 2)
                    assert await page.text('effect-probe button:last-child') == 'Created'
                assert page.exceptions == []
        finally:
            stop_process(server)

    asyncio.run(run())
