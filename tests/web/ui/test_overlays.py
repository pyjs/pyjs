import pytest

from pyjs.web.ui.hover_card import HoverCard, HoverCardContent, HoverCardTrigger
from pyjs.web.ui.popover import Popover, PopoverClose, PopoverContent, PopoverTrigger
from pyjs.web.ui.tooltip import Tooltip, TooltipContent, TooltipTrigger


@pytest.mark.pyjs_python
def test_floating_overlays_render_accessible_closed_state_on_the_server():
    popover = Popover(
        PopoverTrigger("Open"),
        PopoverContent(PopoverClose("Done"), label="Preferences"),
    )
    tooltip = Tooltip(TooltipTrigger("?"), TooltipContent("More information"))
    hover_card = HoverCard(
        HoverCardTrigger("@ada", href="/ada"),
        HoverCardContent("Ada Lovelace"),
    )

    assert popover.getAttribute("data-state") == "closed"
    assert popover.trigger.getAttribute("aria-haspopup") == "dialog"
    assert popover.content.getAttribute("aria-label") == "Preferences"
    assert popover.content.getAttribute("role") == "dialog"
    assert tooltip.getAttribute("data-state") == "closed"
    assert tooltip.content.getAttribute("role") == "tooltip"
    assert tooltip.trigger.getAttribute("aria-describedby") is not None
    assert hover_card.getAttribute("data-state") == "closed"
    assert hover_card.trigger.getAttribute("href") == "/ada"
