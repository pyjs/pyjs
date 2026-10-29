"""Execute the published xterm packages through the Python bindings."""

import asyncio
import importlib
import subprocess
import sys
import textwrap

import pytest

from pyjs.server.dev import create_server
from pyjs.testing.pytest_plugin import get_daemon_health, terminate_daemon_process
from pyjs.tooling.browser import Browser, free_port
from pyjs.tooling.npm import (
    ManagedNpmProject,
    NpmImport,
    NpmPackage,
    collect_npm_packages,
)
from pyjs.web.xterm import __pyjs_npm_imports__

pytestmark = pytest.mark.pyjs_python


def test_compiled_browser_runner_loads_npm_in_each_frame_and_maps_failures(tmp_path):
    (tmp_path / 'pyproject.toml').touch()
    source = textwrap.dedent('''\
        import pytest
        from pyjs import js
        from pyjs.testing.web import mount
        from pyjs.web.dom import document, window
        from pyjs.web.domx import div
        from pyjs.web.xterm import TerminalOptions, create_terminal, write

        pytestmark = pytest.mark.pyjs_web

        @js
        async def mount_terminal():
            assert document.getElementById('mounted-terminal') is None
            surface = div({'id': 'mounted-terminal', 'style': 'width:400px;height:200px'})
            mount(surface)
            terminal = create_terminal(TerminalOptions(cols=20, rows=4))
            terminal.open(surface)
            await write(terminal, 'Managed module')
            line = terminal.buffer.active.getLine(0)
            assert line is not None
            assert line.translateToString(True) == 'Managed module'
            screen = surface.querySelector('.xterm')
            assert screen is not None
            assert window.getComputedStyle(screen).position == 'relative'
            assert document.querySelectorAll('style[id^="pyjs-npm:"]').length == 1
            terminal.dispose()
            assert surface.querySelector('.xterm') is None

        @js
        async def test_first_frame():
            await mount_terminal()

        @js
        async def test_second_frame():
            await mount_terminal()

        @js
        def test_mapped_failure():
            raise ValueError('expected module failure')
    ''')
    test_path = tmp_path / 'test_browser_npm.py'
    test_path.write_text(source)
    failure_line = next(index for index, line in enumerate(source.splitlines(), 1)
                        if "raise ValueError" in line)
    project = ManagedNpmProject.for_project(tmp_path)
    project.sync(collect_npm_packages(['pyjs.web.xterm']), __pyjs_npm_imports__)
    port = free_port()
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '-q', str(test_path),
             '--pyjs-target=web', '--pyjs-browser=managed',
             f'--pyjs-daemon-port={port}'],
            cwd=tmp_path, capture_output=True, text=True, timeout=120,
        )
        output = result.stdout + result.stderr
        assert result.returncode == 1, output
        assert '1 failed, 2 passed' in output, output
        assert f'{test_path}:{failure_line}:' in output, output
        assert 'expected module failure' in output, output
    finally:
        health = get_daemon_health(port)
        if health is not None and health.get('project_root') == str(tmp_path):
            terminate_daemon_process(port, health.get('pid'))


def test_shared_package_aliases_mount_base_before_theme_once(tmp_path):
    package = NpmPackage('example-style', '1.0.0')
    project = ManagedNpmProject(tmp_path)
    assets = tmp_path / 'node_modules' / package.name
    assets.mkdir(parents=True)
    (assets / 'base.css').write_text('.target{color:rgb(10,20,30)}')
    (assets / 'theme.css').write_text('.target{color:rgb(40,50,60)}')
    source = project._styles_source((
        NpmImport(package, '$first', ('theme.css',)),
        NpmImport(package, '$second', ('base.css', 'theme.css')),
    ))
    document = tmp_path / 'index.html'
    document.write_text('<!doctype html><html><head></head><body><div class="target">Text</div>'
                        '<script>' + source + '</script></body></html>')

    async def run():
        async with Browser(headless=True) as browser:
            page = await browser.new_page(document.as_uri())
            assert await page.evaluate("getComputedStyle(document.querySelector('.target')).color") == 'rgb(40, 50, 60)'
            assert await page.evaluate("Array.from(document.querySelectorAll('style'), s => s.id)") == [
                'pyjs-npm:example-style@1.0.0/base.css', 'pyjs-npm:example-style@1.0.0/theme.css']
            await page.evaluate(source)
            assert await page.evaluate("document.querySelectorAll('style').length") == 2
            assert page.exceptions == []

    asyncio.run(run())


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
        server = create_server('xterm_test_app', port=port, css='.xterm .xterm-viewport{cursor:crosshair} .xterm .composition-view{color:rgb(1,2,3)}')
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
                assert await page.evaluate("getComputedStyle(document.querySelector('.xterm-viewport')).cursor") == 'crosshair'
                assert await page.evaluate("getComputedStyle(document.querySelector('.composition-view')).color") == 'rgb(1, 2, 3)'
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
