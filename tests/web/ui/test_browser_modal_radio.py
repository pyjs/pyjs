from typing import cast

import pytest

from pyjs import js
from pyjs.web.dom import document
from pyjs.web.domx import tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement
from pyjs.web.ui.alert_dialog import (
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
)
from pyjs.web.ui.radio_group import RadioGroup, RadioGroupItem
from pyjs.web.ui.sheet import (
    Sheet,
    SheetClose,
    SheetContent,
    SheetDescription,
    SheetFooter,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
)
from pyjs.web.ui.sidebar import MobileSidebar, SidebarContent
from tests.web.ui.browser import bubbling_click, mount, require_element

pytestmark = pytest.mark.pyjs_web


@js
def mounted_alert_dialog() -> AlertDialog:
    alert = AlertDialog(
        AlertDialogTrigger("Delete project"),
        AlertDialogContent(
            "Delete project",
            AlertDialogHeader(
                AlertDialogTitle("Are you absolutely sure?"),
                AlertDialogDescription("This action cannot be undone."),
            ),
            AlertDialogFooter(AlertDialogCancel("Cancel"), AlertDialogAction("Continue")),
        ),
    )
    mount(alert)
    return alert


@js
def test_alert_dialog_requires_an_explicit_decision():
    alert = mounted_alert_dialog()
    alert.open()

    assert alert.is_open
    assert alert.content.dialog_element.getAttribute("role") == "alertdialog"
    assert alert.content.dialog_element.querySelector("[aria-label=Close]") is None

    alert.content.dialog_element.dispatchEvent(Event("click"))
    assert alert.is_open

    cancel = require_element(alert.content.dialog_element, "[data-slot=alert-dialog-cancel]")
    bubbling_click(cancel)
    assert not alert.is_open
    assert document.activeElement is alert.trigger.element

    alert.open()
    action = require_element(alert.content.dialog_element, "[data-slot=alert-dialog-action]")
    bubbling_click(action)
    assert not alert.is_open


@js
def test_sheet_opens_on_the_selected_edge_and_closes_from_its_controls():
    sheet = Sheet(
        SheetTrigger("Edit profile"),
        SheetContent(
            "Edit profile",
            SheetHeader(
                SheetTitle("Edit profile"),
                SheetDescription("Make changes to your profile."),
            ),
            SheetFooter(SheetClose("Done")),
            side="right",
        ),
    )
    mount(sheet)
    sheet.open()

    bounds = sheet.content.dialog_element.getBoundingClientRect()
    body_bounds = document.body.getBoundingClientRect()
    assert sheet.is_open
    assert sheet.content.dialog_element.getAttribute("data-side") == "right"
    assert round(bounds.right) == round(body_bounds.right)
    assert round(bounds.top) == round(body_bounds.top)
    assert round(bounds.bottom) == round(body_bounds.bottom)

    done = require_element(sheet.content.dialog_element, "[data-slot=sheet-close]")
    bubbling_click(done)
    assert not sheet.is_open


@js
def test_mobile_sidebar_restores_page_state_when_navigation_replaces_it():
    previous_overflow = document.body.style.overflow
    sidebar = MobileSidebar(
        "Primary navigation",
        SidebarContent("Links"),
        trigger_style=tw("size-10 md:hidden"),
        content_style=tw("fixed left-0"),
        surface_style=tw("flex h-full"),
    )
    mount(sidebar)
    document.body.style.overflow = "clip"

    assert sidebar.trigger.getAttribute("class") == "size-10 md:hidden"
    assert sidebar.content.dialog_element.getAttribute("class") == "fixed left-0"
    assert sidebar.content.surface.getAttribute("class") == "flex h-full"
    cast(HTMLElement, sidebar.trigger.element).click()
    assert sidebar.is_open
    assert sidebar.trigger.getAttribute("aria-expanded") == "true"
    assert document.body.style.overflow == "hidden"

    sidebar.remove()
    assert document.body.style.overflow == "clip"
    document.body.style.overflow = previous_overflow


@js
def test_radio_group_keeps_selection_on_native_dom_controls():
    comfortable = RadioGroupItem("comfortable", "Comfortable")
    compact = RadioGroupItem("compact", "Compact", checked=True)
    group = RadioGroup(comfortable, compact, name="density", orientation="horizontal")
    mount(group)

    assert group.current_value() == "compact"
    assert compact.is_checked()
    assert group.getAttribute("aria-orientation") == "horizontal"
    assert comfortable.control.getAttribute("name") == compact.control.getAttribute("name")

    comfortable.control.click()
    assert group.current_value() == "comfortable"
    assert comfortable.is_checked()
    assert not compact.is_checked()

    group.select("compact", focus=True)
    assert group.current_value() == "compact"
    assert document.activeElement is compact.control

    compact.control.click()
    assert group.current_value() == "compact"
    assert compact.is_checked()


@js
def test_radio_group_can_start_empty_and_uses_one_generated_name():
    comfortable = RadioGroupItem("comfortable", "Comfortable")
    compact = RadioGroupItem("compact", "Compact")
    group = RadioGroup(comfortable, compact)
    mount(group)

    assert group.current_value() == ""
    assert not comfortable.is_checked()
    assert not compact.is_checked()
    assert comfortable.control.getAttribute("name") != ""
    assert comfortable.control.getAttribute("name") == compact.control.getAttribute("name")

    compact.control.click()
    assert group.current_value() == "compact"
    assert compact.is_checked()


@js
def test_generated_radio_names_isolate_multiple_groups():
    first = RadioGroupItem("first", "First")
    second = RadioGroupItem("second", "Second")
    first_group = RadioGroup(first)
    second_group = RadioGroup(second)
    mount(first_group, second_group)

    assert first.control.getAttribute("name") != second.control.getAttribute("name")

    first.control.click()
    second.control.click()
    assert first.is_checked()
    assert second.is_checked()
