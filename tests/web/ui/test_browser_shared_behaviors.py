import pytest

from pyjs import js
from pyjs.testing.web import mount, wait_for_frames
from pyjs.ui.floating import FloatingPosition
from pyjs.web.dom import document, window
from pyjs.web.domx import button
from pyjs.web.events import Event
from pyjs.web.ui.combobox import Combobox
from pyjs.web.ui.dialog import DialogContent
from pyjs.web.ui.floating import FloatingPanel
from tests.web.ui.test_collection import (
    RichChoice,
    test_list_navigation_filters_wraps_and_clears_stale_highlight as collection_scenario,
)

pytestmark = pytest.mark.pyjs_web


@js
def test_independent_collection_behavior_in_the_browser():
    collection_scenario()


@js
async def test_rich_subclassed_choices_work_inside_a_native_modal():
    picker = Combobox(RichChoice("one", "One"), RichChoice("two", "Two"))
    dialog = DialogContent("Choose an environment", picker)
    mount(dialog)
    dialog.show_modal()
    picker.open()
    await wait_for_frames()
    assert picker.is_open
    assert picker.panel.matches(":popover-open")
    item = picker.visible_items()[1]
    bounds = item.getBoundingClientRect()
    hit = document.elementFromPoint(bounds.left + bounds.width / 2,
                                    bounds.top + bounds.height / 2)
    if hit is None:
        raise AssertionError("No pointer target inside the modal popup")
    assert item is hit or item.contains(hit)
    item.click()
    assert picker.selected_value == "two"
    assert not picker.panel.isConnected
    picker.open()
    dialog.close()
    await wait_for_frames()
    assert not picker.is_open
    assert not picker.panel.isConnected
    dialog.show_modal()
    picker.open()
    await wait_for_frames()
    assert picker.panel.matches(":popover-open")
    picker.panel.hidePopover()
    await wait_for_frames()
    assert not picker.is_open
    assert picker.input.getAttribute("aria-expanded") == "false"
    dialog.close()


@js
class MeasuredPanel(FloatingPanel):
    def __init__(self):
        super().__init__(button("Action"))
        self.updates = 0
        self.style.width = "320px"
        self.style.height = "160px"

    def reposition(self) -> FloatingPosition:
        self.updates += 1
        return super().reposition()


@js
async def test_popup_follows_geometry_and_releases_bindings_on_removal():
    anchor = button("Open")
    anchor.style.position = "fixed"
    anchor.style.left = str(window.innerWidth - 40) + "px"
    anchor.style.top = str(window.innerHeight - 40) + "px"
    panel = MeasuredPanel()
    mount(anchor)
    panel.open(anchor)
    await wait_for_frames()
    bounds = panel.getBoundingClientRect()
    assert panel.getAttribute("data-side") == "top"
    assert bounds.right <= window.innerWidth - 7
    assert bounds.bottom < anchor.getBoundingClientRect().top

    anchor.style.left = "200px"
    anchor.style.top = "200px"
    document.dispatchEvent(Event("scroll"))
    await wait_for_frames()
    assert panel.getAttribute("data-side") == "bottom"
    assert panel.getBoundingClientRect().left == 200
    updates = panel.updates
    anchor.style.width = "400px"
    await wait_for_frames(4)
    assert panel.updates > updates

    panel.style.height = str(window.innerHeight * 2) + "px"
    await wait_for_frames(4)
    assert panel.getBoundingClientRect().bottom <= window.innerHeight - 7
    panel.style.height = "60px"
    await wait_for_frames(4)
    assert panel.getBoundingClientRect().height == 60

    panel.remove()
    await wait_for_frames()
    updates = panel.updates
    window.dispatchEvent(Event("resize"))
    document.dispatchEvent(Event("scroll"))
    await wait_for_frames()
    assert panel.updates == updates
    panel.open(anchor, align="end")
    await wait_for_frames()
    assert panel.getBoundingClientRect().right == anchor.getBoundingClientRect().right
    panel.close()


@js
async def test_invalid_popup_placement_cleans_up_and_allows_reopening():
    anchor = button("Open")
    panel = MeasuredPanel()
    mount(anchor)
    failed = False
    try:
        panel.open(anchor, side="invalid")
    except ValueError:
        failed = True
    assert failed
    assert not panel.isConnected
    assert panel.getAttribute("data-state") == "closed"
    panel.open(anchor)
    await wait_for_frames()
    assert panel.matches(":popover-open")
    panel.close()
