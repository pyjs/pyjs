import pytest

from pyjs import js
from pyjs.web.dom import document
from pyjs.web.domx import (
    button,
    div,
    input,
    tag,  # noqa: F401 - used by inline DOM helpers
    tw,
)
from pyjs.web.events import Event
from pyjs.web.html import HTMLButtonElement, HTMLInputElement
from pyjs.web.ui.dialog import (
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
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
