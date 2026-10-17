from typing import cast

import pytest

from examples.components.catalog import CatalogForm
from pyjs import js
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement
from pyjs.web.ui.checkbox import Checkbox
from pyjs.web.ui.input import Input
from pyjs.web.ui.switch import Switch
from pyjs.web.ui.textarea import Textarea
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


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
