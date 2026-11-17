from typing import cast

import pytest

from examples.components.catalog import CatalogForm
from pyjs import js
from pyjs.testing.web import wait_for_frames
from pyjs.web.dom import document
from pyjs.web.domx import div, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement, HTMLTextAreaElement
from pyjs.web.ui.checkbox import Checkbox
from pyjs.web.ui.input import Input
from pyjs.web.ui.switch import Switch
from pyjs.web.ui.textarea import Textarea
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


@js
async def test_auto_sizing_textarea_wraps_reflows_and_shrinks_without_losing_selection():
    control = Textarea("Task", auto_size=True)
    field = cast(HTMLTextAreaElement, control.element)
    host = div(tw("w-80"), control)
    mount(host)
    await wait_for_frames(2)
    initial = field.clientHeight
    assert initial >= 42
    assert field.getBoundingClientRect().width == host.getBoundingClientRect().width
    text = "A long task with emoji 😀 and words to wrap. " * 8
    control.set_value(text)
    field.focus()
    field.setSelectionRange(2, 9)
    await wait_for_frames(2)
    expanded = field.clientHeight
    assert expanded > initial * 2
    assert field.scrollHeight <= field.clientHeight + 1
    assert field.scrollWidth <= field.clientWidth + 1
    host.style.width = "180px"
    await wait_for_frames(2)
    assert field.clientHeight > expanded
    assert field.getBoundingClientRect().width == 180
    assert field.scrollHeight <= field.clientHeight + 1
    assert document.activeElement is field
    assert field.selectionStart == 2 and field.selectionEnd == 9
    field.value = "Short"
    field.dispatchEvent(Event("input", bubbles=True))
    await wait_for_frames(2)
    assert field.clientHeight == initial
    control.set_value("path/" * 100)
    await wait_for_frames(2)
    assert field.scrollWidth <= field.clientWidth + 1
    assert field.scrollHeight <= field.clientHeight + 1
    control.set_value("First\n\nLast\n")
    await wait_for_frames(2)
    assert field.clientHeight > initial
    assert field.scrollHeight <= field.clientHeight + 1
    control.set_value("")
    await wait_for_frames(2)
    assert field.clientHeight == initial


@js
def test_native_form_controls_keep_state_on_the_dom():
    input_element = Input("email", "you@example.com", "email")
    textarea_element = Textarea("About you", "bio")
    checkbox = Checkbox("terms")
    switch_control = Switch("updates", True)
    mount(
        input_element.element,
        textarea_element.element,
        checkbox.element,
        switch_control.element,
    )

    input_element.set_value("ada@example.com")
    textarea_element.set_value("First programmer")
    cast(HTMLElement, checkbox.element).click()
    cast(HTMLElement, switch_control.element).click()

    assert input_element.get_value() == "ada@example.com"
    assert textarea_element.get_value() == "First programmer"
    assert checkbox.is_checked()
    assert not switch_control.is_checked()
    assert switch_control.element.getAttribute("role") == "switch"


@js
def test_catalog_form_reports_errors_and_accepts_valid_values():
    form = CatalogForm()
    mount(form)

    form.form.dispatchEvent(Event("submit", bubbles=True, cancelable=True))

    assert form.error.getAttribute("hidden") is None
    assert form.email.getAttribute("aria-invalid") == "true"
    assert form.terms.getAttribute("aria-invalid") == "true"
    assert form.status.textContent == "Please correct the highlighted fields."

    form.email.set_value("ada@example.com")
    form.terms.set_checked(True)
    form.form.dispatchEvent(Event("submit", bubbles=True, cancelable=True))

    assert form.error.getAttribute("hidden") == ""
    assert form.email.getAttribute("aria-invalid") == "false"
    assert form.terms.getAttribute("aria-invalid") == "false"
    assert form.status.textContent == "Preferences saved for ada@example.com."
