from typing import cast

import pytest

from pyjs import js
from pyjs.testing.web import wait_for_frames
from pyjs.web.dom import document
from pyjs.web.domx import (
    button,
    div,
    input,
    tag,  # noqa: F401 - used by inline DOM helpers
    tw,
)
from pyjs.web.events import Event
from pyjs.web.html import HTMLButtonElement, HTMLDivElement, HTMLInputElement
from pyjs.web.ui.dialog import (
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogPanel,
    DialogTitle,
    DialogTrigger,
)
from tests.web.ui.browser import bubbling_click, mount, require_element

pytestmark = pytest.mark.pyjs_web


@js
class DialogDemo(Dialog):
    def __init__(self):
        background_button: HTMLButtonElement = button("Background action")
        name_input: HTMLInputElement = input(
            tw("h-9 w-full rounded-md border border-slate-300 px-3 text-sm"),
            {"autofocus": "", "placeholder": "Name"},
        )
        cancel_button = DialogClose("Cancel")
        content = DialogContent(
            "Edit profile",
            DialogHeader(
                DialogTitle("Edit profile"),
                DialogDescription("Make changes to your profile, then save when you are done."),
            ),
            name_input,
            DialogFooter(cancel_button),
        )
        super().__init__(DialogTrigger("Edit profile"), content)
        self.background_button = background_button
        self.name_input = name_input
        self.cancel_button = cancel_button


@js
def mounted_dialog() -> DialogDemo:
    demo = DialogDemo()
    background = div({"data-testid": "dialog-background"}, demo.background_button)
    mount(background, demo)
    return demo


@js
def test_dialog_opens_as_an_accessible_native_modal():
    demo = mounted_dialog()

    demo.trigger.element.dispatchEvent(Event("click"))

    assert demo.is_open
    assert demo.content.dialog_element.open
    assert demo.getAttribute("data-state") == "open"
    assert demo.trigger.element.getAttribute("aria-expanded") == "true"
    assert demo.content.dialog_element.getAttribute("aria-label") == "Edit profile"
    assert document.body.style.overflow == "hidden"
    assert document.activeElement is demo.name_input

    demo.background_button.focus()
    assert document.activeElement is demo.name_input


@js
def test_dialog_close_controls_cancel_and_restore_focus():
    demo = mounted_dialog()
    demo.open()

    bubbling_click(demo.cancel_button.element)

    assert not demo.is_open
    assert not demo.content.dialog_element.open
    assert demo.trigger.element.getAttribute("aria-expanded") == "false"
    assert document.body.style.overflow == "visible"
    assert document.activeElement is demo.trigger.element

    demo.open()
    demo.content.dialog_element.dispatchEvent(Event("cancel", cancelable=True))
    assert not demo.is_open


@js
def test_dialog_closes_from_the_backdrop_and_default_close_button():
    demo = mounted_dialog()
    demo.open()

    demo.content.dialog_element.dispatchEvent(Event("click"))
    assert not demo.is_open

    demo.open()
    close_button = require_element(demo.content.dialog_element, "[aria-label=Close]")
    bubbling_click(close_button)
    assert not demo.is_open


@js
def test_dialog_reopens_after_native_close_and_cleans_up_when_removed():
    demo = mounted_dialog()
    document.body.style.overflow = "scroll"

    demo.open()
    demo.open()
    assert document.body.style.overflow == "hidden"

    demo.content.dialog_element.close()
    demo.content.dialog_element.dispatchEvent(Event("close"))
    assert not demo.is_open
    assert document.body.style.overflow == "scroll"
    assert document.activeElement is demo.trigger.element

    demo.open()
    demo.remove()
    assert not demo.is_open
    assert document.body.style.overflow == "scroll"


@js
def test_dialog_visual_showcase():
    demo = mounted_dialog()
    demo.open()
    bounds = demo.content.dialog_element.getBoundingClientRect()
    body_bounds = document.body.getBoundingClientRect()

    assert demo.content.dialog_element.getAttribute("data-state") == "open"
    assert bounds.width > 300
    assert bounds.height > 150
    assert round(bounds.left + bounds.width / 2) == round(body_bounds.left + body_bounds.width / 2)


@js
async def test_scrollable_dialog_keeps_growing_content_and_actions_reachable():
    root = document.documentElement
    if root is None:
        raise ValueError("The browser document must have a root element")
    for placement in ["center", "top", "bottom", "left", "right"]:
        first: HTMLInputElement = input({"autofocus": "", "aria-label": "First field"})
        last = DialogClose("Done")
        last_button = cast(HTMLButtonElement, last.element)
        tall: HTMLDivElement = div(tw("min-h-[1500px]"), "Long content")
        content = DialogContent("Long form", first, tall, DialogFooter(last),
                                placement=placement, scrollable=True)
        demo = Dialog(DialogTrigger("Open long form"), content)
        mount(demo)
        demo.open()
        await wait_for_frames()
        assert content.surface.scrollHeight > content.surface.clientHeight
        assert document.activeElement is first
        last_button.focus()
        await wait_for_frames()
        bounds = last.element.getBoundingClientRect()
        assert bounds.top >= 0 and bounds.bottom <= root.clientHeight, (
            placement + ": " + str(bounds.top) + ".." + str(bounds.bottom) + " / " + str(root.clientHeight))
        assert content.surface.scrollTop > 0
        first.focus()
        await wait_for_frames()
        assert first.getBoundingClientRect().top >= 0
        tall.style.setProperty("min-height", "2200px")
        last_button.focus()
        await wait_for_frames()
        assert last.element.getBoundingClientRect().bottom <= root.clientHeight
        bubbling_click(last.element)
        assert not content.dialog_element.open
        assert document.activeElement is demo.trigger.element


@js
async def test_dialog_panel_keeps_header_and_footer_visible_while_editing_long_content():
    first: HTMLInputElement = input({"aria-label": "First line"})
    last: HTMLInputElement = input({"aria-label": "Last line"})
    tall: HTMLDivElement = div(tw("min-h-[1500px]"), "Document")
    panel = DialogPanel("Edit document", first, tall, last)
    back = button("Back")
    save = DialogClose("Save")
    panel.header.append(back)
    panel.footer.append(save.element)
    demo = Dialog(DialogTrigger("Edit document"), panel)
    background = button("Background")
    mount(background, demo)
    demo.open()
    await wait_for_frames()
    bounds = panel.dialog_element.getBoundingClientRect()
    header = panel.header.getBoundingClientRect()
    footer = panel.footer.getBoundingClientRect()
    viewport = document.documentElement
    if viewport is None:
        raise ValueError("Expected a browser document")
    assert bounds.top >= 0 and bounds.bottom <= viewport.clientHeight
    assert bounds.left >= 0 and bounds.right <= viewport.clientWidth
    assert panel.body.scrollHeight > panel.body.clientHeight
    assert panel.body.clientHeight > 0
    last.focus()
    await wait_for_frames()
    assert panel.body.scrollTop > 0
    assert panel.header.getBoundingClientRect().top == header.top
    assert panel.footer.getBoundingClientRect().top == footer.top
    assert last.getBoundingClientRect().bottom <= footer.top
    background.focus()
    assert document.activeElement is last
    tall.style.setProperty("min-height", "2200px")
    last.focus()
    await last.scrollIntoView(block="nearest")
    await wait_for_frames()
    assert panel.footer.getBoundingClientRect().bottom <= viewport.clientHeight
    bubbling_click(save.element)
    assert not panel.dialog_element.open
    assert document.activeElement is demo.trigger.element
