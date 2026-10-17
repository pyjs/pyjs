from typing import cast

import pytest

from pyjs import js
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement
from pyjs.web.ui.avatar import Avatar
from pyjs.web.ui.collapsible import Collapsible, CollapsibleContent, CollapsibleTrigger
from pyjs.web.ui.toggle import Toggle, ToggleGroup
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


@js
def test_collapsible_toggles_native_button_state():
    collapsible = Collapsible(
        CollapsibleTrigger("Files"),
        CollapsibleContent("app.py"),
    )
    mount(collapsible)

    cast(HTMLElement, collapsible.trigger.element).click()

    assert collapsible.is_open()
    assert collapsible.getAttribute("data-state") == "open"
    assert collapsible.trigger.getAttribute("aria-controls") == collapsible.content.getAttribute(
        "id"
    )
    assert collapsible.content.getAttribute("style") == "display: block"

    cast(HTMLElement, collapsible.trigger.element).click()
    assert not collapsible.is_open()
    assert collapsible.content.getAttribute("style") == "display: none"


@js
def test_toggle_and_single_toggle_group_keep_pressed_state_on_the_dom():
    standalone = Toggle("Bold", pressed=True)
    left = Toggle("Left", value="left")
    center = Toggle("Center", value="center", pressed=True)
    right = Toggle("Right", value="right")
    group = ToggleGroup(left, center, right)
    mount(standalone.element, group)

    cast(HTMLElement, standalone.element).click()
    cast(HTMLElement, right.element).click()

    assert not standalone.is_pressed()
    assert not center.is_pressed()
    assert right.is_pressed()
    assert group.current_value() == "right"

    cast(HTMLElement, right.element).click()
    assert group.current_value() == ""


@js
def test_multiple_toggle_group_preserves_independent_pressed_states():
    bold = Toggle("Bold", value="bold")
    italic = Toggle("Italic", value="italic")
    group = ToggleGroup(bold, italic, multiple=True)
    mount(group)

    cast(HTMLElement, bold.element).click()
    cast(HTMLElement, italic.element).click()
    assert bold.is_pressed()
    assert italic.is_pressed()

    cast(HTMLElement, bold.element).click()
    assert not bold.is_pressed()
    assert italic.is_pressed()


@js
def test_avatar_switches_between_fallback_and_loaded_image():
    avatar = Avatar(fallback="AL", src="profile.png", alt="Ada Lovelace")
    mount(avatar)

    avatar.image.dispatchEvent(Event("load"))
    assert avatar.image.getAttribute("style") == "display: block"
    assert avatar.fallback.getAttribute("style") == "display: none"

    avatar.image.dispatchEvent(Event("error"))
    assert avatar.image.getAttribute("style") == "display: none"
    assert avatar.fallback.getAttribute("style") == "display: flex"
