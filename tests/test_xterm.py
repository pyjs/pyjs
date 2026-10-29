"""Execute the published xterm packages through the Python bindings."""

import asyncio
import importlib

import pytest

from pyjs.server.dev import create_server
from pyjs.tooling.browser import Browser, free_port
from pyjs.tooling.npm import ManagedNpmProject, collect_npm_packages
from pyjs.web.xterm import __pyjs_npm_imports__

pytestmark = pytest.mark.pyjs_python


def test_xterm_mount_styles_options_input_fit_and_disposal(tmp_path, monkeypatch):
    (tmp_path / 'pyproject.toml').touch()
    (tmp_path / 'xterm_test_app.py').write_text('''
from pyjs import js
from pyjs.web.domx import CustomElement, div, ref, tag
from pyjs.web.xterm import TerminalOptions, Theme, create_terminal, create_fit, write

@js
class Demo(CustomElement):
    def __init__(self):
        super().__init__()
        self.surface = ref(div({'style': 'width:700px;height:250px'}))
        self.status = ref(div({'data-testid': 'received'}))
        tag(self, self.surface, self.status)

    async def initialize(self):
        self.terminal = create_terminal(TerminalOptions(cols=37, rows=8,
            fontSize=15, cursorBlink=False, theme=Theme(background='#123456')))
        self.setAttribute('data-initial-cols', str(self.terminal.cols))
        self.terminal.open(self.surface)
        self.fit = create_fit()
        self.terminal.loadAddon(self.fit)
        self.fit.fit()
        self.subscription = self.terminal.onData(self.receive)
        await write(self.terminal, 'PyJS \\x1b[31mred\\x1b[0m\\r\\nUnicode: 🐍')
        line = self.terminal.buffer.active.getLine(0)
        if line is not None:
            self.setAttribute('data-first-line', line.translateToString(True))
        self.setAttribute('data-ready', 'true')

    def receive(self, text: str):
        self.status.textContent += text

    def disconnected(self):
        self.subscription.dispose()
        self.terminal.dispose()

def main():
    return Demo()
''')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(__import__('sys').modules, 'xterm_test_app', raising=False)
    importlib.invalidate_caches()
    project = ManagedNpmProject.for_project(tmp_path)
    project.sync(collect_npm_packages(['pyjs.web.xterm']), __pyjs_npm_imports__)

    async def run():
        port = free_port()
        server = create_server('xterm_test_app', port=port)
        server.start()
        try:
            async with Browser(headless=True) as browser:
                page = await browser.new_page(f'http://127.0.0.1:{port}/')
                await page.wait_for("document.querySelector('demo-element')?.getAttribute('data-ready') === 'true' || document.querySelector('[data-ready=true]') != null", 'xterm mount', timeout=60)
                await page.evaluate("void (window.demo = document.querySelector('[data-ready=true]'))")
                assert await page.evaluate("demo.getAttribute('data-initial-cols')") == '37'
                assert await page.evaluate("demo.getAttribute('data-first-line')") == 'PyJS red'
                assert await page.evaluate('demo.terminal.options.fontSize') == 15
                assert await page.evaluate('demo.terminal.options.cursorBlink') is False
                assert await page.evaluate('demo.terminal.options.theme.background') == '#123456'
                assert await page.evaluate("getComputedStyle(document.querySelector('.xterm')).position") == 'relative'
                assert await page.evaluate("getComputedStyle(document.querySelector('.xterm-helper-textarea')).opacity") == '0'
                assert await page.evaluate('demo.terminal.buffer.active.getLine(0).translateToString(true)') == 'PyJS red'
                assert await page.evaluate('demo.terminal.buffer.active.getLine(1).translateToString(true)') == 'Unicode: 🐍'
                columns = await page.evaluate('demo.terminal.cols')
                await page.evaluate("demo.surface.style.width='350px';demo.fit.fit()")
                assert await page.evaluate('demo.terminal.cols') < columns
                await page.evaluate('demo.terminal.focus()')
                await page.session.send('Input.insertText', {'text': 'PYJS'})
                await page.wait_for_text('[data-testid=received]', 'PYJS')
                await page.evaluate('demo.subscription.dispose()')
                await page.session.send('Input.insertText', {'text': 'IGNORED'})
                assert await page.text('[data-testid=received]') == 'PYJS'
                await page.evaluate('window.terminal = demo.terminal; demo.remove()')
                assert await page.evaluate("document.querySelector('.xterm') === null")
                assert page.exceptions == []
        finally:
            server.close()

    asyncio.run(run())
