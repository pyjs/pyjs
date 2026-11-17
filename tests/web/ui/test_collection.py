import pytest

from pyjs import js
from pyjs.web.domx import div, span
from pyjs.web.ui.collection import ListNavigation, filter_items
from pyjs.web.ui.combobox import Combobox, ComboboxItem
from pyjs.web.ui.command import Command, CommandItem


@js
def test_list_navigation_filters_wraps_and_clears_stale_highlight():
    first = div({"data-value": "alpha", "data-label": "Alpha"})
    disabled = div({"data-value": "beta", "aria-disabled": "true"})
    last = div({"data-value": "gamma", "data-label": "Gamma"})
    rows = [first, disabled, last]
    navigation = ListNavigation(rows)

    assert navigation.highlight(-1) is last
    assert navigation.highlight(2) is first
    assert filter_items(rows, "GAM", ["data-value", "data-label"]) == 1
    assert navigation.highlight(0) is last
    assert not first.hasAttribute("data-highlighted")

    assert filter_items(rows, "missing", ["data-value"]) == 0
    assert navigation.highlight(0) is None
    assert navigation.current() is None
    assert not last.hasAttribute("data-highlighted")

    assert filter_items(rows, "beta", ["data-value"]) == 1
    assert not disabled.hasAttribute("hidden")
    assert navigation.current() is None
    assert filter_items(rows, "", ["data-value"]) == 3
    assert navigation.highlight(0) is first


@js
class RichChoice(ComboboxItem):
    def __init__(self, value: str, label: str):
        super().__init__(value, label, span(label), span("Available"))


@pytest.mark.pyjs_python
def test_search_controls_share_navigation_without_sharing_selection_semantics():
    first = RichChoice("one", "One")
    second = RichChoice("two", "Two")
    picker = Combobox(first, second)
    picker.select("two")
    picker.highlight(0)
    assert first.getAttribute("data-highlighted") == "true"
    assert first.getAttribute("aria-selected") == "false"
    assert second.getAttribute("aria-selected") == "true"

    command = Command(CommandItem("open", "Open"))
    command.navigation.highlight(0)
    assert command.highlighted_item().getAttribute("aria-selected") == "true"
    assert not command.highlighted_item().hasAttribute("data-highlighted")
