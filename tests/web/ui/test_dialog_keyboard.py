import asyncio
import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest

from pyjs import js
from pyjs.javascript.transpiler import bundle
from pyjs.server.rendering import page
from pyjs.testing.android_browser import AndroidBrowser
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.browser import Browser
from pyjs.web.ui.dialog import Dialog, DialogClose, DialogPanel, DialogTrigger
from pyjs.web.ui.textarea import Textarea


@js
def editor_page():
    panel = DialogPanel("Document editor", Textarea("Document", auto_size=True))
    panel.header.append(DialogClose("Close").element)
    panel.footer.append(DialogClose("Done").element)
    return Dialog(DialogTrigger("Edit"), panel)


@pytest.fixture
def editor_origin(tmp_path):
    source, css = bundle(editor_page, include_main=True, call_main=False)
    (tmp_path / "app.js").write_text(source)
    (tmp_path / "app.css").write_text(css)
    (tmp_path / "index.html").write_text(page(editor_page(), "app.js", "app.css"))
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_touch_targets_hydrated_modal_and_oversized_textarea(editor_origin, tmp_path):
    driver = AndroidBrowser("geometry-only", sdk=Mock(spec=AndroidSDK))

    async def scenario():
        async with Browser() as browser:
            document = await browser.new_page(editor_origin)
            await document.set_viewport(400, 600, mobile=True)
            await document.wait_for_selector("[data-slot=dialog-trigger]")
            await driver.tap(document, "[data-slot=dialog-trigger]")
            await document.wait_for_selector("dialog[open]")
            text = "Long document line 日本語 😀\n" * 60
            await document.fill("textarea", text)
            await document.wait_for("""(() => {
                const body = document.querySelector('[data-slot=dialog-panel-body]');
                return body.scrollHeight > body.clientHeight;
            })()""", "auto-growing editor overflows its scrolling body")
            await document.evaluate("""document.addEventListener('touchstart', event => {
                window.touched = event.target.tagName;
            })""")
            await driver.tap(document, "textarea")
            assert await document.evaluate("window.touched") == "TEXTAREA"
            assert await document.evaluate("document.activeElement.tagName") == "TEXTAREA"
            await document.screenshot(tmp_path / "editor-touch.png")
            await driver.tap(document, "[data-slot=dialog-panel-footer] button")
            await document.wait_for("!document.querySelector('dialog').open", "editor closed")
            assert await document.evaluate("document.querySelector('textarea').value") == text
            assert not document.exceptions, document.exceptions

    asyncio.run(asyncio.wait_for(scenario(), timeout=60))


def test_generated_document_keeps_editor_actions_above_android_keyboard(
    pyjs_android_browser_avd, editor_origin, tmp_path,
):
    async def scenario():
        async with AndroidBrowser(pyjs_android_browser_avd, artifacts=tmp_path) as browser:
            origin = await browser.reverse(urlsplit(editor_origin).port)
            document = await browser.new_page(origin)
            await document.wait_for_selector("[data-slot=dialog-trigger]")
            await browser.tap(document, "[data-slot=dialog-trigger]")
            await document.wait_for_selector("dialog[open]")
            await browser.dismiss_keyboard(document)
            height = await document.evaluate("innerHeight")
            await browser.tap(document, "textarea")
            await browser.wait_for_keyboard()
            await document.wait_for(f"innerHeight < {height - 100}", "layout resized by IME")
            text = "A long document line 日本語 😀\n" * 60
            await document.session.send("Input.insertText", {"text": text})
            await document.wait_for("""(() => {
                const viewport = visualViewport;
                const controls = document.querySelectorAll('[data-dialog-close]');
                return controls.length === 2 && [...controls].every(control => {
                    const box = control.getBoundingClientRect();
                    return box.height > 0 && box.top >= viewport.offsetTop &&
                        box.bottom <= viewport.offsetTop + viewport.height;
                });
            })()""", "fixed editor actions above keyboard")
            assert await document.evaluate("""(() => {
                const body = document.querySelector('[data-slot=dialog-panel-body]');
                return body.scrollHeight > body.clientHeight;
            })()""")
            await browser.screenshot(tmp_path / "editor-keyboard.png")
            await browser.tap(document, "[data-slot=dialog-panel-footer] button")
            await document.wait_for("!document.querySelector('dialog').open", "editor closed")
            assert await document.evaluate("document.querySelector('textarea').value") == text
            await browser.wait_for_keyboard(False)
            assert not document.exceptions, document.exceptions

    asyncio.run(asyncio.wait_for(scenario(), timeout=90))
