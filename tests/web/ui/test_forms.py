import pytest

from examples.components.catalog import CatalogForm
from pyjs.web.ui.checkbox import Checkbox
from pyjs.web.ui.field import Field, FieldDescription, FieldLabel, FieldSet, FieldTitle
from pyjs.web.ui.input import Input
from pyjs.web.ui.label import Label
from pyjs.web.ui.switch import Switch
from pyjs.web.ui.textarea import Textarea


@pytest.mark.pyjs_python
def test_form_controls_render_as_native_elements_on_the_server():
    input_element = Input("email", "you@example.com", "email")
    textarea_element = Textarea("About you", "bio")
    checkbox = Checkbox("terms", True)
    switch_control = Switch("updates", True)
    label = Label("Accept terms", checkbox)

    assert input_element.element.tagName == "INPUT"
    assert input_element.element.getAttribute("type") == "email"
    assert input_element.element.getAttribute("name") == "email"
    assert textarea_element.element.tagName == "TEXTAREA"
    assert textarea_element.element.getAttribute("name") == "bio"
    assert checkbox.is_checked()
    assert checkbox.element.getAttribute("checked") == ""
    assert switch_control.is_checked()
    assert switch_control.element.getAttribute("checked") == ""
    assert switch_control.element.getAttribute("role") == "switch"
    assert label.tagName == "LABEL"
    assert label.children[0] is checkbox.element
    assert label.childNodes[1] is checkbox.element


@pytest.mark.pyjs_python
def test_field_primitives_preserve_semantics_and_orientation():
    field = Field(
        FieldLabel(FieldTitle("Email"), Input()),
        FieldDescription("Required"),
    )
    field_set = FieldSet(field)

    assert field_set.tagName == "FIELDSET"
    assert field.getAttribute("role") == "group"
    assert field.getAttribute("data-orientation") == "vertical"
    assert field.children[0].getAttribute("data-slot") == "field-label"


@pytest.mark.pyjs_python
def test_catalog_form_keeps_initial_values_in_native_controls():
    form = CatalogForm()

    assert form.email.get_value() == ""
    assert not form.terms.is_checked()
    assert form.updates.is_checked()
    assert form.error.getAttribute("hidden") == ""
