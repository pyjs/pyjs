import pytest

from pyjs.web.ui.aspect_ratio import AspectRatio
from pyjs.web.ui.avatar import Avatar, AvatarGroup, AvatarGroupCount
from pyjs.web.ui.button import Button, ButtonGroup
from pyjs.web.ui.card import Card, CardDescription, CardHeader, CardTitle
from pyjs.web.ui.collapsible import Collapsible, CollapsibleContent, CollapsibleTrigger
from pyjs.web.ui.empty import Empty, EmptyDescription, EmptyHeader, EmptyTitle
from pyjs.web.ui.kbd import Kbd, KbdGroup
from pyjs.web.ui.spinner import Spinner
from pyjs.web.ui.toggle import Toggle, ToggleGroup


@pytest.mark.pyjs_python
def test_foundational_widgets_render_stable_semantics_on_the_server():
    ratio = AspectRatio("Preview", ratio="16 / 9")
    avatar = Avatar(fallback="AL", alt="Ada Lovelace")
    avatars = AvatarGroup(avatar, AvatarGroupCount("+2"))
    button = Button("Save", variant="outline", size="sm")
    buttons = ButtonGroup(button)
    card = Card(CardHeader(CardTitle("Plan"), CardDescription("Details")))
    empty = Empty(EmptyHeader(EmptyTitle("Nothing here"), EmptyDescription("Create one.")))
    keys = KbdGroup(Kbd("Ctrl"), Kbd("K"))
    spinner = Spinner("Saving")

    assert ratio.getAttribute("style") == "aspect-ratio: 16 / 9"
    assert avatar.getAttribute("data-slot") == "avatar"
    assert avatars.getAttribute("data-slot") == "avatar-group"
    assert button.element.tagName == "BUTTON"
    assert button.getAttribute("data-variant") == "outline"
    assert button.getAttribute("data-size") == "sm"
    assert buttons.getAttribute("role") == "group"
    assert card.getAttribute("data-slot") == "card"
    assert empty.getAttribute("data-slot") == "empty"
    assert keys.getAttribute("data-slot") == "kbd-group"
    assert spinner.getAttribute("role") == "status"
    assert spinner.getAttribute("aria-label") == "Saving"


@pytest.mark.pyjs_python
def test_collapsible_and_toggles_store_initial_state_on_the_dom():
    collapsible = Collapsible(
        CollapsibleTrigger("Files"),
        CollapsibleContent("app.py"),
    )
    standalone = Toggle("Bold", pressed=True)
    group = ToggleGroup(
        Toggle("Left", value="left"),
        Toggle("Center", value="center", pressed=True),
    )

    assert not collapsible.is_open()
    assert collapsible.getAttribute("data-state") == "closed"
    assert collapsible.trigger.getAttribute("aria-controls") == collapsible.content.getAttribute(
        "id"
    )
    assert collapsible.content.getAttribute("style") == "display: none"
    assert standalone.is_pressed()
    assert standalone.getAttribute("data-state") == "on"
    assert group.current_value() == "center"
    assert group.getAttribute("data-multiple") == "false"


@pytest.mark.pyjs_python
def test_toggle_group_requires_values_for_its_items():
    with pytest.raises(ValueError, match="must define a value"):
        ToggleGroup(Toggle("Missing value"))
