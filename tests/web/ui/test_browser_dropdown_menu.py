from typing import cast

import pytest

from pyjs import js
from pyjs.testing.web import wait_for_frames
from pyjs.web.dom import document
from pyjs.web.domx import button
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement
from pyjs.web.ui.dropdown_menu import (
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
)
from tests.web.ui.browser import (
    bubbling_click,
    floating_alignment_gap,
    floating_side_gap,
    mount,
    place_element,
    press_key,
)

pytestmark = pytest.mark.pyjs_web


@js
class DropdownMenuDemo(DropdownMenu):
    def __init__(self, side: str = "bottom", align: str = "start"):
        trigger = DropdownMenuTrigger("Open menu")
        trigger.setAttribute("data-testid", "dropdown-trigger")
        self.profile_item = DropdownMenuItem("Profile", "Profile")
        self.billing_item = DropdownMenuItem("Billing", "Billing")
        self.settings_item = DropdownMenuItem("Settings", "Settings")
        content = DropdownMenuContent(
            DropdownMenuLabel("My Account"),
            DropdownMenuSeparator(),
            self.profile_item,
            self.billing_item,
            self.settings_item,
        )
        content.setAttribute("data-testid", "dropdown-content")
        super().__init__(trigger, content, side=side, align=align)
        place_element(self.trigger.element, 48, 36)

    def move_trigger(self, left: int, top: int):
        place_element(self.trigger.element, left, top)


@js
def mounted_dropdown(
    side: str = "bottom",
    align: str = "start",
    left: int = 48,
    top: int = 36,
) -> DropdownMenuDemo:
    demo = DropdownMenuDemo(side=side, align=align)
    demo.move_trigger(left, top)
    mount(demo)
    demo.open()
    return demo


@js
def test_dropdown_uses_shadcn_default_placement():
    demo = mounted_dropdown()

    assert demo.content.getAttribute("data-side") == "bottom"
    assert demo.content.getAttribute("data-align") == "start"
    assert demo.trigger.getAttribute("aria-controls") == demo.content.getAttribute("id")
    assert floating_side_gap(demo.trigger.element, demo.content, "bottom") == 4
    assert floating_alignment_gap(demo.trigger.element, demo.content, "bottom", "start") == 0


@js
def test_floating_panel_supports_explicit_sides_and_alignment():
    top_demo = mounted_dropdown("top", "end", 360, 220)
    assert floating_side_gap(top_demo.trigger.element, top_demo.content, "top") == 4
    assert floating_alignment_gap(top_demo.trigger.element, top_demo.content, "top", "end") == 0

    left_demo = mounted_dropdown("left", "center", 360, 220)
    assert floating_side_gap(left_demo.trigger.element, left_demo.content, "left") == 4
    assert (
        floating_alignment_gap(left_demo.trigger.element, left_demo.content, "left", "center") == 0
    )

    right_demo = mounted_dropdown("right", "start", 360, 220)
    assert floating_side_gap(right_demo.trigger.element, right_demo.content, "right") == 4
    assert (
        floating_alignment_gap(right_demo.trigger.element, right_demo.content, "right", "start")
        == 0
    )


@js
def test_dropdown_closes_after_selection_and_outside_click():
    demo = DropdownMenuDemo()
    mount(demo)

    demo.trigger.element.dispatchEvent(Event("click"))
    assert demo.is_open
    assert demo.trigger.element.getAttribute("aria-expanded") == "true"

    cast(HTMLElement, demo.billing_item.element).click()
    assert demo.selected_value == "Billing"
    assert not demo.is_open

    demo.trigger.element.dispatchEvent(Event("click"))
    demo.content.dispatchEvent(Event("click", bubbles=True))
    assert demo.is_open

    document.body.dispatchEvent(Event("click", bubbles=True))
    assert not demo.is_open
    assert demo.content.getAttribute("data-state") == "closed"


@js
def test_dropdown_keyboard_navigation_and_escape():
    demo = DropdownMenuDemo()
    mount(demo)

    press_key(demo.trigger.element, "ArrowDown")
    assert demo.is_open
    assert document.activeElement is demo.profile_item.element

    press_key(demo.profile_item.element, "ArrowUp")
    assert document.activeElement is demo.settings_item.element

    press_key(demo.settings_item.element, "ArrowDown")
    assert document.activeElement is demo.profile_item.element

    press_key(demo.profile_item.element, "ArrowDown")
    assert document.activeElement is demo.billing_item.element

    press_key(demo.billing_item.element, "Escape")
    assert not demo.is_open
    assert document.activeElement is demo.trigger.element

    press_key(demo.trigger.element, "ArrowUp")
    assert demo.is_open
    assert document.activeElement is demo.settings_item.element

    press_key(demo.settings_item.element, "Home")
    assert document.activeElement is demo.profile_item.element

    press_key(demo.profile_item.element, "End")
    assert document.activeElement is demo.settings_item.element

    press_key(demo.settings_item.element, "PageDown")
    assert document.activeElement is demo.settings_item.element


@js
class CheckedMenuDemo(DropdownMenu):
    def __init__(self):
        trigger = DropdownMenuTrigger("Open checks")
        self.notify_item = DropdownMenuCheckboxItem("notify", "Notifications")
        self.list_item = DropdownMenuRadioItem("list", "List")
        self.grid_item = DropdownMenuRadioItem("grid", "Grid")
        content = DropdownMenuContent(
            self.notify_item,
            self.list_item,
            self.grid_item,
        )
        super().__init__(trigger, content)
        place_element(self.trigger.element, 48, 36)


@js
def test_dropdown_checkbox_and_radio_activate_from_mouse_and_keyboard():
    demo = CheckedMenuDemo()
    mount(demo)
    demo.open()

    bubbling_click(demo.notify_item.element)
    assert demo.notify_item.getAttribute("aria-checked") == "true"
    assert demo.is_open

    bubbling_click(demo.notify_item.element)
    assert demo.notify_item.getAttribute("aria-checked") == "false"

    press_key(demo.trigger.element, "ArrowDown")
    press_key(demo.notify_item.element, "Enter")
    assert demo.notify_item.getAttribute("aria-checked") == "true"
    assert demo.is_open

    bubbling_click(demo.grid_item.element)
    assert demo.grid_item.getAttribute("aria-checked") == "true"
    assert demo.list_item.getAttribute("aria-checked") == "false"
    assert not demo.is_open

    demo.open()
    press_key(demo.trigger.element, "ArrowDown")
    press_key(demo.notify_item.element, "ArrowDown")
    press_key(demo.list_item.element, " ")
    assert demo.list_item.getAttribute("aria-checked") == "true"
    assert demo.grid_item.getAttribute("aria-checked") == "false"
    assert not demo.is_open


@js
class SubmenuDemo(DropdownMenu):
    def __init__(self):
        trigger = DropdownMenuTrigger("Open nested")
        self.profile_item = DropdownMenuItem("profile", "Profile")
        self.sub_trigger = DropdownMenuSubTrigger("more", "More")
        self.nested_item = DropdownMenuItem("nested", "Nested")
        self.submenu = DropdownMenuSub(
            self.sub_trigger,
            DropdownMenuSubContent(self.nested_item),
        )
        content = DropdownMenuContent(self.profile_item, self.submenu)
        super().__init__(trigger, content)
        place_element(self.trigger.element, 48, 36)


@js
def test_dropdown_submenu_closes_with_parent_escape_and_arrow_left():
    demo = SubmenuDemo()
    mount(demo)
    demo.open()
    demo.submenu.open_sub(Event("mouseenter"))
    assert demo.submenu.panel.isConnected
    assert demo.submenu.panel.parentElement is document.body

    demo.submenu.panel.dispatchEvent(Event("click", bubbles=True))
    assert demo.is_open
    assert demo.submenu.is_sub_open()

    press_key(document, "Escape")
    assert not demo.submenu.is_sub_open()
    assert not demo.submenu.panel.isConnected
    assert demo.is_open

    demo.submenu.open_sub(Event("mouseenter"))
    press_key(document, "ArrowLeft")
    assert not demo.submenu.is_sub_open()
    assert demo.is_open

    demo.submenu.open_sub(Event("mouseenter"))
    demo.close()
    assert not demo.submenu.panel.isConnected
    assert not demo.submenu.is_sub_open()


@js
def test_dropdown_submenu_keyboard_stays_in_the_active_panel():
    demo = SubmenuDemo()
    mount(demo)

    press_key(demo.trigger.element, "ArrowDown")
    assert document.activeElement is demo.profile_item.element
    press_key(demo.profile_item.element, "ArrowDown")
    assert document.activeElement is demo.sub_trigger.element
    press_key(demo.sub_trigger.element, "ArrowRight")
    assert demo.submenu.is_sub_open()
    assert document.activeElement is demo.nested_item.element
    press_key(demo.nested_item.element, "ArrowDown")
    assert document.activeElement is demo.nested_item.element
    press_key(demo.nested_item.element, "ArrowLeft")
    assert not demo.submenu.is_sub_open()
    assert document.activeElement is demo.sub_trigger.element
    press_key(demo.sub_trigger.element, "Enter")
    assert demo.selected_value == ""
    assert demo.is_open
    press_key(demo.sub_trigger.element, "ArrowDown")
    assert document.activeElement is demo.profile_item.element


@js
class SiblingSubmenuDemo(DropdownMenu):
    def __init__(self):
        trigger = DropdownMenuTrigger("Open nested")
        self.a_trigger = DropdownMenuSubTrigger("a", "A")
        self.first_item = DropdownMenuItem("first", "First")
        self.submenu_a = DropdownMenuSub(
            self.a_trigger,
            DropdownMenuSubContent(self.first_item),
        )
        self.b_trigger = DropdownMenuSubTrigger("b", "B")
        self.second_item = DropdownMenuItem("second", "Second")
        self.submenu_b = DropdownMenuSub(
            self.b_trigger,
            DropdownMenuSubContent(self.second_item),
        )
        content = DropdownMenuContent(self.submenu_a, self.submenu_b)
        super().__init__(trigger, content)
        place_element(self.trigger.element, 48, 36)


@js
def test_sibling_submenu_hover_then_keyboard_selects_active_panel():
    demo = SiblingSubmenuDemo()
    mount(demo)
    demo.open()
    demo.submenu_a.open_sub(Event("mouseenter"))
    demo.submenu_b.open_sub(Event("mouseenter"))
    assert not demo.submenu_a.is_sub_open()
    assert demo.submenu_b.is_sub_open()
    cast(HTMLElement, demo.second_item.element).focus()
    press_key(demo.second_item.element, "ArrowDown")
    press_key(demo.second_item.element, "Enter")
    assert demo.selected_value == "second"


@js
class NestedSubmenuDemo(DropdownMenu):
    def __init__(self):
        trigger = DropdownMenuTrigger("Open nested")
        self.child_trigger = DropdownMenuSubTrigger("child", "Child")
        self.nested_item = DropdownMenuItem("nested", "Nested")
        self.child = DropdownMenuSub(
            self.child_trigger,
            DropdownMenuSubContent(self.nested_item),
        )
        self.parent_trigger = DropdownMenuSubTrigger("parent", "Parent")
        self.parent = DropdownMenuSub(
            self.parent_trigger,
            DropdownMenuSubContent(self.child),
        )
        content = DropdownMenuContent(self.parent)
        super().__init__(trigger, content)
        place_element(self.trigger.element, 48, 36)


@js
def test_opening_child_submenu_does_not_close_its_parent():
    demo = NestedSubmenuDemo()
    mount(demo)
    demo.open()
    press_key(demo.parent_trigger.element, "ArrowRight")
    assert demo.parent.is_sub_open()
    press_key(demo.child_trigger.element, "ArrowRight")
    assert demo.parent.is_sub_open()
    assert demo.child.is_sub_open()
    assert demo.parent.panel.isConnected
    assert demo.child.panel.parentElement is document.body
    press_key(demo.nested_item.element, "ArrowLeft")
    assert not demo.child.is_sub_open()
    assert demo.parent.is_sub_open()
    assert document.activeElement is demo.child_trigger.element
    demo.remove()
    assert not demo.parent.panel.isConnected
    assert not demo.child.panel.isConnected


@js
def test_dropdown_remove_closes_a_portaled_submenu():
    demo = SubmenuDemo()
    mount(demo)
    demo.open()
    demo.submenu.open_sub(Event("mouseenter"))
    assert demo.submenu.panel.parentElement is document.body
    demo.remove()
    assert not demo.submenu.panel.isConnected
    assert not demo.submenu.is_sub_open()


@js
async def test_hydrated_submenu_nested_click_selects():
    menu = cast(DropdownMenu, document.createElement("dropdown-menu"))
    menu.setAttribute("data-self-id", "hydrated-dropdown")
    menu.setAttribute("data-align", "start")
    menu.setAttribute("data-align-offset", "0")
    menu.setAttribute("data-side", "bottom")
    menu.setAttribute("data-side-offset", "4")
    menu.setAttribute("data-slot", "dropdown-menu")
    trigger = button(
        {
            "aria-controls": "hydrated-dropdown-content",
            "aria-expanded": "false",
            "aria-haspopup": "menu",
            "data-slot": "dropdown-menu-trigger",
            "id": "hydrated-dropdown-trigger",
            "type": "button",
        },
        "Open nested",
    )
    profile = button(
        {
            "data-slot": "dropdown-menu-item",
            "data-value": "profile",
            "role": "menuitem",
            "tabindex": "-1",
            "type": "button",
        },
        "Profile",
    )
    nested = button(
        {
            "data-slot": "dropdown-menu-item",
            "data-value": "nested",
            "role": "menuitem",
            "tabindex": "-1",
            "type": "button",
        },
        "Nested",
    )
    sub_trigger = button(
        {
            "aria-haspopup": "menu",
            "data-slot": "dropdown-menu-sub-trigger",
            "data-value": "more",
            "id": "hydrated-sub-trigger",
            "role": "menuitem",
            "tabindex": "-1",
            "type": "button",
        },
        "More",
    )
    panel = cast(
        DropdownMenuSubContent, document.createElement("dropdown-menu-sub-content")
    )
    panel.setAttribute("data-slot", "dropdown-menu-sub-content")
    panel.setAttribute("id", "hydrated-sub-panel")
    panel.setAttribute("role", "menu")
    panel.append(nested)
    sub = cast(DropdownMenuSub, document.createElement("dropdown-menu-sub"))
    sub.setAttribute("data-self-id", "hydrated-sub")
    sub.setAttribute("data-slot", "dropdown-menu-sub")
    sub.setAttribute("data-state", "closed")
    sub.append(sub_trigger, panel)
    content = cast(DropdownMenuContent, document.createElement("dropdown-menu-content"))
    content.setAttribute("data-slot", "dropdown-menu-content")
    content.setAttribute("id", "hydrated-dropdown-content")
    content.setAttribute("role", "menu")
    content.append(profile, sub)
    menu.append(trigger, content)
    mount(menu)
    await wait_for_frames()
    menu.open()
    sub.open_sub(Event("mouseenter"))
    bubbling_click(nested)
    assert menu.selected_value == "nested"
    assert not menu.is_open


@js
def test_empty_dropdown_ignores_navigation_keys():
    menu = DropdownMenu(
        DropdownMenuTrigger("Empty menu"),
        DropdownMenuContent(DropdownMenuLabel("No actions")),
    )
    mount(menu)

    press_key(menu.trigger.element, "ArrowDown")

    assert not menu.is_open
    assert menu.trigger.getAttribute("aria-expanded") == "false"


@js
def test_floating_dropdown_visual_showcase():
    demo = mounted_dropdown("bottom", "start", 80, 64)

    assert floating_side_gap(demo.trigger.element, demo.content, "bottom") == 4
    assert floating_alignment_gap(demo.trigger.element, demo.content, "bottom", "start") == 0
    assert demo.content.getAttribute("data-state") == "open"
