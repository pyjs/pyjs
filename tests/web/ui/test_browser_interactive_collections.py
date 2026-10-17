import pytest

from pyjs import js
from pyjs.web.dom import document
from pyjs.web.ui.accordion import AccordionGroup, AccordionItem
from pyjs.web.ui.tabs import Tab, TabGroup
from tests.web.ui.browser import bubbling_click, mount, press_key

pytestmark = pytest.mark.pyjs_web


@js
def test_tabs_select_with_pointer_and_keyboard():
    account = Tab("account", "Account", "Account settings")
    password = Tab("password", "Password", "Password settings")
    tabs = TabGroup(account, password, default_value="account")
    mount(tabs)

    assert account.trigger.getAttribute("aria-controls") == account.content.getAttribute("id")
    assert account.content.getAttribute("aria-labelledby") == account.trigger.getAttribute("id")

    bubbling_click(password.trigger)
    assert tabs.current_value() == "password"
    assert password.trigger.getAttribute("aria-selected") == "true"
    assert password.content.getAttribute("style") == "display: block"
    assert account.content.getAttribute("style") == "display: none"

    press_key(password.trigger, "ArrowRight")
    assert tabs.current_value() == "account"
    assert document.activeElement is account.trigger

    press_key(account.trigger, "ArrowLeft")
    assert document.activeElement is password.trigger

    press_key(password.trigger, "Home")
    assert document.activeElement is account.trigger

    press_key(account.trigger, "End")
    assert document.activeElement is password.trigger


@js
def test_tab_relationship_ids_are_unique_across_groups():
    first_tab = Tab("first", "First", "First content")
    second_tab = Tab("second", "Second", "Second content")
    first_group = TabGroup(first_tab, default_value="first")
    second_group = TabGroup(second_tab, default_value="second")
    mount(first_group, second_group)

    assert first_tab.trigger.getAttribute("id") != second_tab.trigger.getAttribute("id")
    assert first_tab.content.getAttribute("id") != second_tab.content.getAttribute("id")
    assert first_tab.trigger.getAttribute("aria-controls") == first_tab.content.getAttribute("id")
    assert second_tab.trigger.getAttribute("aria-controls") == second_tab.content.getAttribute("id")


@js
def test_single_accordion_toggles_and_moves_keyboard_focus():
    first = AccordionItem("first", "First question", "First answer", open=True)
    second = AccordionItem("second", "Second question", "Second answer")
    accordion = AccordionGroup(first, second)
    mount(accordion)
    second.append(second.trigger)

    assert first.trigger.getAttribute("aria-controls") == first.content.getAttribute("id")
    assert first.content.getAttribute("aria-labelledby") == first.trigger.getAttribute("id")
    assert first.content.getAttribute("role") == "region"

    bubbling_click(second.icon)
    assert first.trigger.getAttribute("aria-expanded") == "false"
    assert first.content.getAttribute("style") == "display: none"
    assert second.trigger.getAttribute("aria-expanded") == "true"
    assert second.content.getAttribute("style") == "display: block"

    press_key(second.trigger, "ArrowDown")
    assert document.activeElement is first.trigger

    press_key(first.trigger, "ArrowUp")
    assert document.activeElement is second.trigger

    press_key(second.trigger, "Home")
    assert document.activeElement is first.trigger

    press_key(first.trigger, "End")
    assert document.activeElement is second.trigger


@js
def test_multiple_accordion_keeps_other_items_open():
    first = AccordionItem("first", "First", "First answer", open=True)
    second = AccordionItem("second", "Second", "Second answer")
    accordion = AccordionGroup(first, second, multiple=True)
    mount(accordion)

    bubbling_click(second.trigger)
    assert first.is_open()
    assert second.is_open()

    bubbling_click(first.trigger)
    assert not first.is_open()
    assert second.is_open()


@js
def test_accordion_rejects_duplicate_values():
    message = ""
    try:
        AccordionGroup(
            AccordionItem("duplicate", "First", "First answer"),
            AccordionItem("duplicate", "Second", "Second answer"),
        )
    except Exception as error:
        message = error.message

    assert message == "AccordionItem values must be unique within an AccordionGroup"
