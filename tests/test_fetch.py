import asyncio
import importlib
import sys

import pytest

from pyjs.server.dev import create_server
from pyjs.tooling.browser import Browser, free_port

pytestmark = pytest.mark.pyjs_python


def test_fetch_callback_sends_method_headers_and_body(tmp_path, monkeypatch):
    (tmp_path / 'fetch_application.py').write_text('''
from collections.abc import Awaitable, Callable
from pyjs import js
from pyjs.server.dev import Response as ServerResponse
from pyjs.web.domx import CustomElement, tag
from pyjs.web.network import RequestInit, Response, fetch

@js
class Client(CustomElement):
    def __init__(self):
        super().__init__()
        tag(self, {'data-testid': 'client'}, 'Loading')

    async def initialize(self):
        request: Callable[[str, object], Awaitable[Response]] = fetch
        response = await request('/echo', {'method': 'POST', 'body': 'dictionary',
            'headers': {'X-Probe': 'dictionary'}})
        self.textContent = await response.text()
        response = await request('/echo', RequestInit(method='POST', body='native',
            headers={'X-Probe': 'native'}))
        self.textContent += await response.text()
        response = await fetch(url='/echo', options={'method': 'POST', 'body': 'keyword',
            'headers': {'X-Probe': 'keyword'}})
        self.textContent += await response.text()
        self.setAttribute('data-order', '')
        response = await fetch(options={'method': 'POST', 'body': self.record('reversed'),
            'headers': {'X-Probe': 'reversed'}}, url=self.record('/echo'))
        self.textContent += await response.text()
        self.setAttribute('data-ready', 'true')

    def record(self, value: str) -> str:
        self.setAttribute('data-order', (self.getAttribute('data-order') or '') + value)
        return value

def main():
    return Client()

def echo(request):
    return ServerResponse.text(request.method + '/' + request.headers.get('X-Probe', '')
                               + '/' + request.body.decode() + '\\n')
''')
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, 'fetch_application', raising=False)
    importlib.invalidate_caches()

    async def run():
        port = free_port()
        server = create_server('fetch_application', routes={('POST', '/echo'): 'echo'}, port=port)
        server.start()
        try:
            async with Browser(headless=True) as browser:
                page = await browser.new_page(f'http://127.0.0.1:{port}/')
                await page.wait_for_attribute('[data-testid=client]', 'data-ready', 'true')
                assert await page.text('[data-testid=client]') == '\n'.join(
                    'POST/' + name + '/' + name for name in ('dictionary', 'native', 'keyword', 'reversed')) + '\n'
                assert await page.attribute('[data-testid=client]', 'data-order') == 'reversed/echo'
                assert page.exceptions == []
        finally:
            server.close()
            sys.modules.pop('fetch_application', None)

    asyncio.run(run())
