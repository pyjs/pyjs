import pytest

from pyjs.web.ui.accordion import AccordionGroup, AccordionItem
from pyjs.web.ui.tabs import Tab, TabGroup


@pytest.mark.pyjs_python
def test_tabs_and_accordion_store_initial_state_in_the_dom():
    account = Tab("account", "Account", "Account settings")
    password = Tab("password", "Password", "Password settings")
    tabs = TabGroup(account, password, default_value="account")
    first = AccordionItem("first", "First question", "First answer", open=True)
    second = AccordionItem("second", "Second question", "Second answer")
    accordion = AccordionGroup(first, second)

    assert tabs.current_value() == "account"
    assert account.trigger.getAttribute("aria-selected") == "true"
    assert account.trigger.getAttribute("aria-controls") == account.content.getAttribute("id")
    assert account.content.getAttribute("aria-labelledby") == account.trigger.getAttribute("id")
    assert account.content.getAttribute("style") == "display: block"
    assert password.content.getAttribute("style") == "display: none"
    assert accordion.getAttribute("multiple") == "false"
    assert accordion.children[0] is first
    assert accordion.get_items()[1] is second
    assert first.trigger.getAttribute("aria-expanded") == "true"
    assert first.trigger.getAttribute("aria-controls") == first.content.getAttribute("id")
    assert first.content.getAttribute("aria-labelledby") == first.trigger.getAttribute("id")
    assert first.content.getAttribute("role") == "region"
    assert second.content.getAttribute("style") == "display: none"


@pytest.mark.pyjs_python
def test_multiple_accordion_preserves_independent_open_items():
    first = AccordionItem("first", "First", "First answer", open=True)
    second = AccordionItem("second", "Second", "Second answer", open=True)
    accordion = AccordionGroup(first, second, multiple=True)

    accordion.set_open("first", False)

    assert not first.is_open()
    assert second.is_open()


@pytest.mark.pyjs_python
def test_accordion_values_must_be_unique_within_the_group():
    first = AccordionItem("duplicate", "First", "First answer")
    second = AccordionItem("duplicate", "Second", "Second answer")

    with pytest.raises(ValueError, match="must be unique"):
        AccordionGroup(first, second)
