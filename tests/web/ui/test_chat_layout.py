"""The same hydrated conversation exercises desktop layout and actual Android IME."""

import asyncio
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pyjs import js
from pyjs.javascript.transpiler import bundle
from pyjs.server.rendering import page
from pyjs.testing.android_browser import AndroidBrowser
from pyjs.tooling.browser import Browser
from pyjs.web.domx import div, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.ssr import render_html
from pyjs.web.ui import Widget
from pyjs.web.ui.chat import (
    ChatBody,
    ChatFooter,
    ChatHeading,
    ChatHistory,
    ChatPanel,
    ChatView,
)
from pyjs.web.ui.input_group import InputGroupButton, InputGroupTextarea
from pyjs.web.ui.prompt_input import PromptInput
from pyjs.web.ui.styles import Stylesheet


@js
class ComposerFixture(Widget):
    def __init__(self):
        super().__init__()
        self.add(tw('contents'))
        self.field = ref(InputGroupTextarea('Write a message'))
        self.field.setAttribute('rows', '1')
        self.send = ref(InputGroupButton('Send'))
        self.send.setAttribute('type', 'submit')
        self.remove_button = ref(InputGroupButton('Remove image'))
        self.prompt = ref(PromptInput(self.field, self.send, compact=True))
        self.prompt.set_attachments(div('preview.png', self.remove_button))
        self.form = ref(tag('form', self.prompt))
        self.add(self.form)

    def initialize(self):
        # The parent initializes before its SSR child's references are restored.
        self.prompt.set_attachments(div('preview.png', self.remove_button))
        self.prompt.show_attachments(True)
        self.remove_button.addEventListener('click', self.remove_image)
        self.form.addEventListener('submit', self.submit)
        self.setAttribute('data-ready', '')

    def remove_image(self, event: Event):
        self.prompt.show_attachments(False)
        self.setAttribute('data-removed', '')

    def submit(self, event: Event):
        event.preventDefault()
        self.setAttribute('data-sent', self.field.value)


@js
def fixture_page():
    history = ChatHistory(*[tag('p', 'A message with a long path: /' + 'segment/' * 30) for _ in range(20)])
    return div(tw('flex'),
        ChatView(ChatHeading('A long conversation title', 'Conversation details'),
                 ChatBody(history, ChatFooter(ComposerFixture()))),
        ChatPanel(div('Assistant'), ChatBody(ChatHistory(tag('p', 'Hello')), ChatFooter(ComposerFixture()))))


@js
def styled_marker():
    css = '[data-marker="</STYLE>"] { color: rgb(7, 8, 9); }'
    return div(Stylesheet(css), tag('p', {'data-marker': '</STYLE>'}, 'Case-sensitive selector'))


@js
class PanelStateFixture(Widget):
    def __init__(self):
        super().__init__()
        for state in (True, False):
            panel = ChatPanel(div('Heading'), div('Content'))
            panel.setAttribute('id', 'saved-closed' if state else 'saved-open')
            panel.set_collapsed(state)
            self.add(panel)
        self.add(div({'id': 'server-marker'}, styled_marker()))

    def initialize(self):
        panel = ChatPanel(div('Heading'), div('Content'))
        panel.setAttribute('id', 'client-closed')
        panel.set_collapsed(True)
        self.add(panel, div({'id': 'client-marker'}, styled_marker()))
        self.setAttribute('data-ready', '')


@js
def state_page():
    return PanelStateFixture()


@pytest.fixture(scope='module')
def chat_origin(tmp_path_factory):
    path = tmp_path_factory.mktemp('chat-layout')
    source, css = bundle(fixture_page, include_main=True, call_main=False)
    (path / 'app.js').write_text(source)
    (path / 'app.css').write_text(css)
    (path / 'index.html').write_text(page(fixture_page(), 'app.js', 'app.css'))
    (path / 'ssr.html').write_text((path / 'index.html').read_text().split('<script')[0])
    state_source, state_css = bundle(state_page, include_main=True, call_main=False)
    (path / 'state.js').write_text(state_source)
    (path / 'state.css').write_text(state_css)
    (path / 'state.html').write_text('<!doctype html><link rel="stylesheet" href="state.css">' +
        render_html(PanelStateFixture()) + '<script type="module" src="state.js"></script>')
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(path))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


async def pointer_click(page, selector):
    bounds = await page._selector_bounds(selector)
    x, y = bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2
    for kind in ('mousePressed', 'mouseReleased'):
        await page.session.send('Input.dispatchMouseEvent', {
            'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})


async def assert_field_visible(page, root):
    await page.wait_for('''(() => {
      const r = document.querySelector(ROOT + ' textarea').getBoundingClientRect();
      const v = visualViewport;
      return r.height > 16 && r.top >= v.offsetTop &&
        r.bottom <= v.offsetTop + v.height && v.offsetTop + v.height - r.bottom < 40 &&
        document.documentElement.scrollWidth <= innerWidth;
    })()'''.replace('ROOT', json.dumps(root)), 'composer remains inside viewport')


def test_hydrated_chat_layout_focus_and_actions(chat_origin):
    async def scenario():
        async with Browser() as browser:
            page = await browser.new_page(chat_origin)
            for width, height in ((1280, 800), (360, 640), (360, 320), (640, 160), (640, 41)):
                await page.set_viewport(width, height)
                await page.navigate(chat_origin)
                try:
                    await page.wait_for_selector('[data-ready]')
                except TimeoutError:
                    raise AssertionError(page.exceptions) from None
                for root in ('[data-slot=chat-view]', '[data-slot=chat-panel]'):
                    if root.endswith('panel]'):
                        if await page.evaluate("document.querySelector('[data-slot=chat-panel-toggle]').getAttribute('aria-expanded') === 'false'"):
                            await page.click('[data-slot=chat-panel-toggle]')
                    await page.evaluate(f'document.querySelector({json.dumps(root + " textarea")}).focus()')
                    await page.fill(root + ' textarea', 'Line of a long draft\n' * 20)
                    await assert_field_visible(page, root)
                    if height >= 240:
                        await pointer_click(page, root + ' [data-slot=prompt-attachments] button')
                        await page.wait_for_selector(root + ' [data-removed]')
                    await pointer_click(page, root + ' button[type=submit]')
                    await page.wait_for_selector(root + ' [data-sent]')
                    assert await page.evaluate(f'document.querySelector({json.dumps(root + " [data-sent]")}).getAttribute("data-sent")') == 'Line of a long draft\n' * 20
                    if root.endswith('panel]') and height >= 240:
                        await page.click('[data-slot=chat-panel-toggle]')
                assert not page.exceptions, page.exceptions
    asyncio.run(scenario())


def test_chat_styles_and_panel_state_before_and_after_hydration(chat_origin):
    async def scenario():
        async with Browser() as browser:
            page = await browser.new_page(chat_origin + '/ssr.html')
            for width, padding, collapsed in ((360, 4, True), (1280, 12, False)):
                await page.set_viewport(width, 640)
                await page.navigate(chat_origin + '/ssr.html')
                assert await page.evaluate("""(() => {
                    const panel = document.querySelector('[data-slot=chat-panel]');
                    const content = document.querySelector('[data-slot=message-scroller-content]');
                    return [panel.getBoundingClientRect().height < 100,
                            parseFloat(getComputedStyle(content).paddingLeft)];
                })()""") == [collapsed, padding]
                await page.navigate(chat_origin + '/state.html')
                await page.wait_for_selector('[data-ready]')
                await page.wait_for_selector('#client-closed [aria-expanded=false]')
                assert await page.evaluate("""['saved-closed', 'saved-open', 'client-closed'].map(id => {
                    const panel = document.getElementById(id);
                    return [panel.dataset.collapsed,
                            panel.querySelector('[data-slot=chat-panel-content]').hidden];
                })""") == [['true', True], ['false', False], ['true', True]]
                assert await page.evaluate("""['server-marker', 'client-marker'].map(id =>
                    getComputedStyle(document.querySelector('#' + id + ' p')).color)
                """) == ['rgb(7, 8, 9)', 'rgb(7, 8, 9)']
                assert not page.exceptions, page.exceptions
    asyncio.run(scenario())


def test_chat_with_android_keyboard(pyjs_android_browser_avd, chat_origin, tmp_path):
    async def scenario():
        async with AndroidBrowser(pyjs_android_browser_avd, artifacts=tmp_path) as browser:
            origin = await browser.reverse(int(chat_origin.rsplit(':', 1)[1]))
            page = await browser.new_page(origin)
            await page.wait_for_selector('[data-ready]')
            for root in ('[data-slot=chat-view]', '[data-slot=chat-panel]'):
                if root.endswith('panel]'):
                    await browser.tap(page, '[data-slot=chat-panel-toggle]')
                    await page.wait_for_attribute('[data-slot=chat-panel-toggle]', 'aria-expanded', 'true')
                await browser.tap(page, root + ' textarea')
                await browser.wait_for_keyboard()
                await page.session.send('Input.insertText', {'text': 'Long draft\n' * 20})
                await assert_field_visible(page, root)
                await browser.tap(page, root + ' [data-slot=prompt-attachments] button')
                await page.wait_for_selector(root + ' [data-removed]')
                await browser.rotate(page, landscape=True)
                await browser.tap(page, root + ' textarea')
                await browser.wait_for_keyboard()
                await assert_field_visible(page, root)
                await browser.tap(page, root + ' button[type=submit]')
                await page.wait_for_selector(root + ' [data-sent]')
                await browser.screenshot(tmp_path / ('panel.png' if root.endswith('panel]') else 'page.png'))
                await browser.dismiss_keyboard(page)
                await browser.rotate(page)
            assert not page.exceptions, page.exceptions
    asyncio.run(scenario())
