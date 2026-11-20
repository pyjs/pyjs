import asyncio
from urllib.parse import quote

import pytest

from examples.components.catalog import CatalogForm
from pyjs import js
from pyjs.javascript.transpiler import bundle
from pyjs.tooling.browser import Browser
from pyjs.web.domx import tag
from pyjs.web.ssr import render_html
from pyjs.web.ui.checkbox import Checkbox, CheckboxTarget
from pyjs.web.ui.field import (
    Field,
    FieldAccessory,
    FieldContent,
    FieldDescription,
    FieldLabel,
    FieldSet,
    FieldTitle,
)
from pyjs.web.ui.input import Input
from pyjs.web.ui.label import Label
from pyjs.web.ui.switch import Switch
from pyjs.web.ui.textarea import Textarea


@pytest.mark.pyjs_python
def test_server_set_values_survive_html_parsing_and_native_form_reset():
    values = ["", "\n\nA journal 日本語 😀", "\r\nFirst\rLast\n",
              '</textarea><input name="injected"> & < > "']
    controls = []
    for index, value in enumerate(values):
        field = Textarea(name=str(index))
        field.set_value("Replaced initial value")
        field.set_value(value)
        assert field.get_value() == value
        controls.append(field)
    title = Input(name="title")
    title.set_value('Title < > & " 日本語')
    markup = render_html(tag("form", title, *controls))

    async def run():
        async with Browser() as browser:
            page = await browser.new_page("data:text/html;charset=utf-8," + quote(markup))
            expected = [value.replace("\r\n", "\n").replace("\r", "\n") for value in values]
            assert await page.evaluate("Array.from(document.querySelectorAll('textarea'), e => e.value)") == expected
            assert await page.evaluate("document.querySelector('input').value") == title.get_value()
            assert await page.evaluate("document.querySelectorAll('input').length") == 1
            await page.evaluate("""(() => {
                for (const field of document.querySelectorAll('input,textarea')) field.value = 'Edited';
                document.querySelector('form').reset();
            })()""")
            assert await page.evaluate("Array.from(document.querySelectorAll('textarea'), e => e.value)") == expected
            assert await page.evaluate("document.querySelector('input').value") == title.get_value()

    asyncio.run(run())


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
def test_horizontal_field_accessory_preserves_native_controls():
    checkbox = Checkbox("complete")
    control = Textarea("Task", auto_size=True)
    accessory = FieldAccessory(checkbox)
    content = FieldContent(control)
    field = Field(accessory, content, orientation="horizontal")

    assert field.getAttribute("data-orientation") == "horizontal"
    assert accessory.getAttribute("data-slot") == "field-accessory"
    assert accessory.children[0] is checkbox.element
    assert content.children[0] is control.element
    assert "min-w-0" in content.getAttribute("class").split()
    assert accessory.getAttribute("tabindex") is None


@js
def checkbox_target_form():
    checkbox = Checkbox("complete", True)
    checkbox.element.setAttribute("aria-label", "Complete task")
    return tag("form", Field(
        FieldAccessory(CheckboxTarget(checkbox)), FieldContent(Textarea("Task")),
        orientation="horizontal",
    ), tag("button", {"type": "reset"}, "Reset"))


@pytest.mark.pyjs_python
def test_checkbox_target_retains_native_pointer_keyboard_and_form_behavior():
    _source, css = bundle(checkbox_target_form, include_main=True, call_main=False)
    markup = "<style>" + css + "</style>" + render_html(checkbox_target_form())

    async def run():
        async with Browser() as browser:
            page = await browser.new_page("data:text/html;charset=utf-8," + quote(markup))
            await page.set_viewport(320, 640, mobile=True)
            await page.evaluate("""(() => {
                window.changes = [];
                document.querySelector('input').addEventListener('change', event => {
                    window.changes.push([event.target.checked, event.isTrusted]);
                });
            })()""")
            area = await page.selector_clip('[data-slot="checkbox-target"]')
            box = await page.selector_clip('input')
            assert area["width"] == area["height"] == 36
            assert box["width"] == box["height"] == 16
            accessibility = await page.session.send("Accessibility.getFullAXTree")
            controls = [node for node in accessibility["nodes"]
                        if node.get("role", {}).get("value") == "checkbox"]
            assert len(controls) == 1
            assert controls[0]["name"]["value"] == "Complete task"
            point = {"x": area["x"] + 2, "y": area["y"] + 18}
            assert point["x"] < box["x"]
            assert await page.evaluate(
                "document.querySelector('[data-slot=checkbox-target]').tabIndex") == -1
            for kind in ("mousePressed", "mouseReleased"):
                await page.session.send("Input.dispatchMouseEvent", {
                    "type": kind, **point, "button": "left", "clickCount": 1,
                })
            assert await page.evaluate("window.changes") == [[False, True]]
            assert await page.evaluate("document.activeElement === document.querySelector('input')")
            await page.session.send("Input.dispatchTouchEvent", {
                "type": "touchStart", "touchPoints": [point],
            })
            await page.session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            await page.wait_for("window.changes.length === 2", "native touch toggles once")
            assert await page.evaluate("window.changes") == [[False, True], [True, True]]
            for key, code, number in [(" ", "Space", 32), ("Tab", "Tab", 9)]:
                for kind in ("keyDown", "keyUp"):
                    await page.session.send("Input.dispatchKeyEvent", {
                        "type": kind, "key": key, "code": code, "windowsVirtualKeyCode": number,
                    })
            assert await page.evaluate("window.changes") == [[False, True], [True, True], [False, True]]
            assert await page.evaluate("document.activeElement.tagName") == "TEXTAREA"
            await page.click('button[type="reset"]')
            assert await page.evaluate("document.querySelector('input').checked")
            assert await page.evaluate("new FormData(document.querySelector('form')).get('complete')") == "on"
            await page.evaluate("document.querySelector('input').disabled = true")
            for kind in ("mousePressed", "mouseReleased"):
                await page.session.send("Input.dispatchMouseEvent", {
                    "type": kind, **point, "button": "left", "clickCount": 1,
                })
            assert await page.evaluate("window.changes.length") == 3
            assert await page.evaluate("document.querySelector('input').checked")
            assert await page.evaluate("new FormData(document.querySelector('form')).has('complete')") is False
            assert not page.exceptions, page.exceptions

    asyncio.run(run())


@pytest.mark.pyjs_python
def test_catalog_form_keeps_initial_values_in_native_controls():
    form = CatalogForm()

    assert form.email.get_value() == ""
    assert not form.terms.is_checked()
    assert form.updates.is_checked()
    assert form.error.getAttribute("hidden") == ""


@pytest.mark.pyjs_python
def test_auto_sizing_textarea_retains_native_form_contract():
    control = Textarea("Write a task", "task", auto_size=True)
    control.set_value("A long task\nWith another line")
    assert control.element.tagName == "TEXTAREA"
    assert control.element.getAttribute("name") == "task"
    assert control.element.getAttribute("rows") == "1"
    assert control.get_value() == "A long task\nWith another line"
    assert "field-sizing-content" in control.element.getAttribute("class").split()
    assert "w-full" in control.element.getAttribute("class").split()
    assert "px-3" in control.element.getAttribute("class").split()
    assert "min-h-24" not in control.element.getAttribute("class").split()
    assert Textarea().element.getAttribute("rows") is None
