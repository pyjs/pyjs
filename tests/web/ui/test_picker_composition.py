import asyncio

from pyjs import js
from pyjs.javascript.source import compile_source
from pyjs.javascript.transpiler import bundle
from pyjs.tooling.browser import Browser
from pyjs.web.domx import button, ref
from pyjs.web.events import Event
from pyjs.web.ssr import render_html
from pyjs.web.ui import Widget
from pyjs.web.ui.combobox import Combobox
from pyjs.web.ui.dialog import DialogContent, DialogHeader, DialogTitle
from tests.web.ui.test_collection import RichChoice


@js
class PickerFixture(Widget):
    def __init__(self):
        super().__init__()
        self.picker = ref(Combobox(RichChoice("one", "One"), RichChoice("two", "Two")))
        self.dialog = ref(DialogContent("Choose an environment",
            DialogHeader(DialogTitle("Choose an environment")), self.picker))
        self.trigger = ref(button({"data-open-picker": ""}, "Choose"))
        self.add(self.trigger, self.dialog)

    def initialize(self):
        self.trigger.addEventListener("click", self.open)
        self.setAttribute("data-ready", "")

    def open(self, event: Event):
        self.dialog.show_modal()


@js
def picker_page():
    return PickerFixture()


def test_hydrated_modal_picker_accepts_real_pointer_selection(tmp_path):
    source, css = bundle(picker_page, include_main=True, call_main=False)
    path = tmp_path / "picker.html"
    path.write_text('<!doctype html><meta name="viewport" '
        'content="width=device-width,initial-scale=1">'
        '<style>' + css + '</style>' + render_html(picker_page()) +
        '<script>' + source + '</script>')

    async def scenario():
        async with Browser() as browser:
            page = await browser.new_page()
            # Headless windows have no OS activation; emulate it for focus events.
            await page.session.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
            for width in (1280, 360):
                await page.set_viewport(width, 800)
                await page.navigate(path.as_uri())
                await page.wait_for_selector("[data-ready]")
                for selector in ("[data-open-picker]", "[data-slot=combobox-input]",
                                 '[data-slot=combobox-item][data-value=two]'):
                    if selector.endswith("[data-value=two]"):
                        await page.wait_for_selector(":popover-open")
                    bounds = await page._selector_bounds(selector)
                    for kind in ("mousePressed", "mouseReleased"):
                        await page.session.send("Input.dispatchMouseEvent", {
                            "type": kind,
                            "x": bounds["x"] + bounds["width"] / 2,
                            "y": bounds["y"] + bounds["height"] / 2,
                            "button": "left", "clickCount": 1,
                        })
                await page.wait_for_selector('[data-slot=combobox][data-value=two]')
                assert await page.evaluate('document.querySelector("dialog").open')
                assert not await page.evaluate('Boolean(document.querySelector(":popover-open"))')
                assert not page.exceptions, page.exceptions
    asyncio.run(scenario())


def test_geometry_and_collection_helpers_exclude_unused_behavior():
    with compile_source('''
        from pyjs.ui.floating import FloatingRect, place_floating

        def main() -> int:
            return place_floating(FloatingRect(0, 0, 10, 10),
                                  FloatingRect(0, 0, 20, 20)).left
    ''') as built:
        assert "pyjs.ui.floating" in built.module_names
        assert not any(name.startswith("pyjs.web.") for name in built.module_names)
        assert "ResizeObserver" not in built.javascript

    with compile_source('''
        from pyjs.web.domx import div
        from pyjs.web.ui.collection import ListNavigation, filter_items

        def main() -> int:
            return len(ListNavigation([div("Choice")]).available())
    ''') as built:
        collection = built.sources["pyjs.web.ui.collection"]
        assert "available()" in collection
        assert "highlight(" not in collection
        assert "current(" not in collection
        assert "filter_items(" not in collection
        assert "pyjs.web.ui.floating" not in built.module_names
        assert "pyjs.web.ui.dialog" not in built.module_names

    with compile_source('''
        from pyjs.web.dom import document
        from pyjs.web.ui.command import Command, CommandItem

        def main():
            document.body.append(Command(CommandItem("open", "Open")))
    ''') as built:
        assert "pyjs.web.ui.collection" in built.module_names
        assert "pyjs.web.ui.dialog" not in built.module_names
        assert "pyjs.web.ui.floating" not in built.module_names
