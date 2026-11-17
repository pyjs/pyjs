from typing import cast

import pytest

from examples.components.catalog import CatalogForm, growing_field_example
from pyjs import js
from pyjs.testing.web import assert_render, wait_for_frames
from pyjs.web.dom import document
from pyjs.web.domx import button, div, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement, HTMLTextAreaElement
from pyjs.web.ui.checkbox import Checkbox
from pyjs.web.ui.field import Field, FieldAccessory, FieldContent
from pyjs.web.ui.input import Input
from pyjs.web.ui.switch import Switch
from pyjs.web.ui.textarea import Textarea
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


@js
async def test_horizontal_field_accessories_stay_at_first_line_during_reflow():
    checkbox = Checkbox("complete")
    checkbox.element.setAttribute("aria-label", "Complete")
    control = Textarea("Task", auto_size=True)
    field = cast(HTMLTextAreaElement, control.element)
    action = button(tw("h-9 px-2"), {"type": "button"}, "Remove")
    leading = FieldAccessory(checkbox)
    trailing = FieldAccessory(action)
    row = Field(leading, FieldContent(control), trailing, orientation="horizontal")
    host = div(tw("w-80 bg-white p-2"), row)
    mount(host)
    control.set_value("A task with words that wrap. " * 8)
    field.focus()
    field.setSelectionRange(2, 9)
    for direction in ("ltr", "rtl"):
        row.setAttribute("dir", direction)
        for width in (320, 200):
            host.style.width = str(width) + "px"
            await wait_for_frames(2)
            bounds = field.getBoundingClientRect()
            check_bounds = checkbox.element.getBoundingClientRect()
            action_bounds = action.getBoundingClientRect()
            assert bounds.height > 60
            # Native text uses 8px padding, a 1px border and a 20px line box.
            assert abs(check_bounds.top + check_bounds.height / 2 - bounds.top - 19) <= 1
            assert abs(action_bounds.top + action_bounds.height / 2 - bounds.top - 19) <= 1
            assert leading.getBoundingClientRect().height == 36
            assert trailing.getBoundingClientRect().height == 36
            assert row.scrollWidth <= row.clientWidth
            assert field.scrollWidth <= field.clientWidth + 1
            assert field.scrollHeight <= field.clientHeight + 1
            if direction == "ltr":
                assert check_bounds.right < bounds.left and bounds.right < action_bounds.left
            else:
                assert action_bounds.right < bounds.left and bounds.right < check_bounds.left
            assert document.activeElement is field
            assert field.selectionStart == 2 and field.selectionEnd == 9
    row.setAttribute("dir", "ltr")
    host.style.width = "320px"
    control.set_value("path/" * 100)
    await wait_for_frames(2)
    assert row.scrollWidth <= row.clientWidth
    assert field.scrollWidth <= field.clientWidth + 1
    control.set_value("Short")
    await wait_for_frames(2)
    assert field.getBoundingClientRect().height == 44
    cast(HTMLElement, checkbox.element).click()
    assert checkbox.is_checked()
    action.focus()
    action.click()
    assert document.activeElement is action
    assert control.get_value() == "Short" and checkbox.is_checked()
    action.style.height = "48px"
    await wait_for_frames(2)
    assert trailing.getBoundingClientRect().height == 48
    action.style.removeProperty("height")
    control.set_value("A task with words that wrap. " * 8)
    await wait_for_frames(2)
    assert_render(host, "field-growing-textarea-accessories")


@js
def test_catalog_growing_field_clear_action_keeps_checkbox_state():
    row = growing_field_example()
    mount(row)
    field = cast(HTMLTextAreaElement, row.querySelector("textarea"))
    checkbox = cast(HTMLElement, row.querySelector("input"))
    action = cast(HTMLElement, row.querySelector("button"))
    checkbox.click()
    assert field.value != ""
    action.click()
    assert field.value == ""
    assert checkbox.matches(":checked")


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
