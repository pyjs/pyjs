from typing import cast

import pytest

from pyjs import js
from pyjs.web.dom import document
from pyjs.web.events import Event, MouseEvent
from pyjs.web.html import HTMLElement
from pyjs.web.ui.hover_card import HoverCard, HoverCardContent, HoverCardTrigger
from pyjs.web.ui.popover import Popover, PopoverClose, PopoverContent, PopoverTrigger
from pyjs.web.ui.tooltip import Tooltip, TooltipContent, TooltipTrigger
from tests.web.ui.browser import (
    floating_alignment_gap,
    floating_side_gap,
    mount,
    place_element,
    press_key,
    require_element,
)

pytestmark = pytest.mark.pyjs_web


@js
def mounted_popover() -> Popover:
    popover = Popover(
        PopoverTrigger("Open preferences"),
        PopoverContent(PopoverClose("Done"), label="Preferences"),
    )
    mount(popover)
    return popover


@js
def test_popover_toggles_and_dismisses_from_close_outside_and_escape():
    popover = mounted_popover()

    cast(HTMLElement, popover.trigger.element).click()
    assert popover.is_open
    assert popover.trigger.getAttribute("aria-expanded") == "true"
    assert popover.content.getAttribute("data-state") == "open"

    cast(HTMLElement, popover.trigger.element).click()
    assert not popover.is_open

    cast(HTMLElement, popover.trigger.element).click()
    assert popover.is_open

    popover.content.dispatchEvent(Event("click", bubbles=True))
    assert popover.is_open

    close_button = require_element(popover.content, "[data-slot=popover-close]")
    close_button.dispatchEvent(Event("click", bubbles=True))
    assert not popover.is_open
    assert document.activeElement is popover.trigger.element

    popover.open()
    document.body.dispatchEvent(Event("click", bubbles=True))
    assert not popover.is_open

    popover.open()
    press_key(document, "Escape")
    assert not popover.is_open
    assert document.activeElement is popover.trigger.element


@js
def test_tooltip_opens_for_hover_and_focus_and_closes_on_escape():
    tooltip = Tooltip(TooltipTrigger("?"), TooltipContent("More information"))
    mount(tooltip)

    assert tooltip.trigger.getAttribute("aria-describedby") == tooltip.content.getAttribute("id")

    tooltip.trigger.element.dispatchEvent(Event("mouseenter"))
    assert tooltip.is_open
    assert tooltip.content.getAttribute("data-state") == "open"

    tooltip.trigger.element.dispatchEvent(Event("mouseleave"))
    assert not tooltip.is_open

    tooltip.trigger.element.dispatchEvent(Event("focus"))
    assert tooltip.is_open
    tooltip.trigger.element.dispatchEvent(Event("mouseleave"))
    assert tooltip.is_open
    tooltip.trigger.element.dispatchEvent(Event("blur"))
    assert not tooltip.is_open

    tooltip.trigger.element.dispatchEvent(Event("focus"))
    press_key(document, "Escape")
    assert not tooltip.is_open


@js
def test_tooltip_preserves_descriptions_and_dismisses_on_trigger_click():
    trigger = TooltipTrigger("?")
    trigger.setAttribute("aria-describedby", "existing existing")
    tooltip = Tooltip(trigger, TooltipContent("More information"))
    mount(tooltip)

    expected_description = "existing " + tooltip.content.get_component_id() + "-content"
    assert tooltip.trigger.getAttribute("aria-describedby") == expected_description

    tooltip.trigger.element.dispatchEvent(Event("mouseenter"))
    assert tooltip.is_open

    cast(HTMLElement, tooltip.trigger.element).click()
    assert not tooltip.is_open


@js
def test_hover_card_stays_available_from_trigger_or_content():
    card = HoverCard(
        HoverCardTrigger("@ada"),
        HoverCardContent("Ada Lovelace, computing pioneer."),
    )
    mount(card)

    card.trigger.element.dispatchEvent(Event("mouseenter"))
    assert card.is_open

    trigger_leave = MouseEvent("mouseleave", relatedTarget=card.content)
    card.trigger.element.dispatchEvent(trigger_leave)
    assert card.is_open

    content_leave = MouseEvent("mouseleave", relatedTarget=card.trigger.element)
    card.content.dispatchEvent(content_leave)
    assert card.is_open

    card.content.dispatchEvent(Event("mouseleave"))
    assert not card.is_open

    card.trigger.element.dispatchEvent(Event("focus"))
    assert card.is_open

    press_key(document, "Escape")
    assert not card.is_open


@js
def test_floating_overlay_positions_match_the_selected_side():
    popover = Popover(
        PopoverTrigger("Open"),
        PopoverContent("Content"),
        side="right",
        align="start",
        side_offset=8,
        align_offset=6,
    )
    mount(popover)
    trigger = popover.trigger.element
    place_element(trigger, 80, 64)
    popover.open()

    assert floating_side_gap(trigger, popover.content, "right") == 8
    assert floating_alignment_gap(trigger, popover.content, "right", "start") == 6
