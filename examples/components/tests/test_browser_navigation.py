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
                await page.evaluate("document.querySelector('[data-node-activate=no]').focus()")
                await page.session.send("Input.dispatchKeyEvent", {
                    "type": "keyDown", "key": "Delete", "code": "Delete",
                    "windowsVirtualKeyCode": 46,
                })
                await page.session.send("Input.dispatchKeyEvent", {
                    "type": "keyUp", "key": "Delete", "code": "Delete",
                    "windowsVirtualKeyCode": 46,
                })
                assert await page.evaluate(
                    "document.querySelector('[data-node-id=no]') === null") is True
                assert await page.evaluate("document.activeElement.localName") == "diagram-canvas"
                await page.session.send("Input.dispatchKeyEvent", {
                    "type": "keyDown", "key": "z", "code": "KeyZ", "modifiers": 2,
                    "windowsVirtualKeyCode": 90,
                })
                await page.session.send("Input.dispatchKeyEvent", {
                    "type": "keyUp", "key": "z", "code": "KeyZ", "modifiers": 2,
                    "windowsVirtualKeyCode": 90,
                })
                assert await page.evaluate(
                    "document.querySelector('[data-node-id=no]') !== null") is True
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

                await page.click('a[href="/diagram-view"]')
                await page.wait_for("document.querySelector('review-diagram')?._initialized === true",
                                    "the read-only diagram to hydrate")
                assert await page.evaluate("document.querySelector('review-diagram').owner") == "Publishing team"
                assert page.exceptions == []
                box = await page.selector_clip('[data-node-activate="draft"]')
                for phase in ("mousePressed", "mouseReleased"):
                    await page.session.send("Input.dispatchMouseEvent", {
                        "type": phase, "x": box["x"] + 8, "y": box["y"] + 8,
                        "button": "left", "buttons": 0 if phase == "mouseReleased" else 1,
                        "clickCount": 1,
                    })
                await page.wait_for_text('[role="status"]', "Activated: draft")
                await page.evaluate("document.querySelector('[data-node-activate=publish]').focus()")
                await page.session.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter"})
                await page.session.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter"})
                await page.wait_for_text('[role="status"]', "Activated: publish")
                await page.fill('[aria-label="Comment for draft"]', "Persistent local draft")
                await page.evaluate("document.querySelector('review-diagram').draw()")
                assert await page.evaluate(
                    "document.querySelector('[aria-label=\"Comment for draft\"]').value") == "Persistent local draft"
                for atomic_moves in (True, False):
                    result = await page.evaluate("""(atomic => {
                        const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'moveBefore');
                        if (!atomic) delete Element.prototype.moveBefore;
                        const viewer = document.querySelector('review-diagram');
                        const graph = viewer.get_graph();
                        const field = viewer.querySelector('[aria-label="Comment for publish"]');
                        const card = field.closest('review-card');
                        let disconnected = 0;
                        const previousDisconnect = card.disconnected;
                        card.disconnected = () => { disconnected++; };
                        try {
                            field.focus();
                            field.value = 'Unfinished local comment';
                            field.setSelectionRange(2, 8, 'backward');
                            for (const [nodes, edges] of [
                                [graph.nodes, []],
                                [[...graph.nodes].reverse(), []],
                                [graph.nodes, graph.edges],
                            ]) {
                                const snapshot = Object.assign(
                                    Object.create(Object.getPrototypeOf(graph)), graph, {nodes, edges});
                                viewer.configure(snapshot);
                                if (document.activeElement !== field) throw Error('Lost focus');
                                if (field.selectionStart !== 2 || field.selectionEnd !== 8 ||
                                    field.selectionDirection !== 'backward') throw Error('Lost selection');
                                if (field.value !== 'Unfinished local comment') throw Error('Lost value');
                                const ids = [...viewer.querySelectorAll('[data-node-id]')]
                                    .map(node => node.getAttribute('data-node-id'));
                                if (JSON.stringify(ids) !== JSON.stringify(nodes.map(node => node.id)))
                                    throw Error('Wrong stacking order');
                            }
                            return {disconnected};
                        } finally {
                            card.disconnected = previousDisconnect;
                            if (descriptor) Object.defineProperty(Element.prototype, 'moveBefore', descriptor);
                        }
                    })(""" + ("true" if atomic_moves else "false") + ")")
                    assert result == {"disconnected": 0}
                assert page.exceptions == []
                await page.navigate(url + "diagram-view")
                await page.wait_for("document.querySelector('review-diagram')?._initialized === true",
                                    "the directly loaded custom diagram to hydrate")
                assert await page.evaluate("document.querySelector('review-diagram').owner") == "Publishing team"
                owners = await page.evaluate("""(() => {
                    const viewer = document.querySelector('review-diagram');
                    const graph = viewer.get_graph();
                    const data = JSON.parse(viewer.getAttribute('data-diagram'));
                    data.nodes.push({...data.nodes[0], id: 'extra', label: 'New task', y: 260});
                    viewer.configure(graph.constructor.model_validate_json(JSON.stringify(data)));
                    return [...viewer.querySelectorAll('review-card p')].map(node => node.textContent);
                })()""")
                assert owners == ["Owner: Publishing team"] * 3
                assert page.exceptions == []
        finally:
            stop_process(server)

    asyncio.run(run())
