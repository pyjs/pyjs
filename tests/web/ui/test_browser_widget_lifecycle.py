from typing import cast

import pytest

from pyjs import js
from pyjs.testing.web import wait_for_frames
from pyjs.web.dom import document
from pyjs.web.domx import button, div
from pyjs.web.events import Event
from pyjs.web.ui.combobox import Combobox, ComboboxItem
from pyjs.web.ui.input_group import InputGroup, InputGroupAddon, InputGroupInput
from pyjs.web.ui.message_scroller import MessageScroller
from pyjs.web.ui.scroll_area import ScrollArea
from pyjs.web.ui.sonner import Toaster
from tests.web.ui.browser import bubbling_click, mount, require_element
from tests.web.ui.scroller import constrain_scroller, dispatch_wheel, tall_item

pytestmark = pytest.mark.pyjs_web


@js
class EventCounter:
    def __init__(self):
        self.count = 0

    def handleEvent(self, event: Event) -> None:
        self.count = self.count + 1


@js
async def test_hydrated_message_scroller_releases_follow_on_wheel():
    scroller = cast(MessageScroller, document.createElement("message-scroller"))
    scroller.setAttribute("data-self-id", "hydrated-scroller")
    scroller.setAttribute("data-auto-scroll", "true")
    scroller.setAttribute("data-bound", "true")
    scroller.setAttribute("data-default-scroll", "end")
    scroller.setAttribute("data-edge-threshold", "8")
    scroller.setAttribute("data-mode", "following-bottom")
    scroller.setAttribute("data-newest-first", "false")
    scroller.setAttribute("data-peek", "64")
    scroller.setAttribute("data-pending-scroll", "true")
    spacer = div(
        {
            "data-slot": "message-scroller-spacer",
            "id": "hydrated-scroller-spacer",
            "style": "height:0px",
        }
    )
    content = div(
        {
            "data-slot": "message-scroller-content",
            "id": "hydrated-scroller-content",
            "role": "log",
        },
        tall_item("First", 80),
        tall_item("Second", 80),
        spacer,
    )
    viewport = div(
        {
            "data-slot": "message-scroller-viewport",
            "id": "hydrated-scroller-viewport",
            "role": "region",
            "tabindex": "0",
        },
        content,
    )
    jump = button(
        {
            "data-slot": "message-scroller-button",
            "id": "hydrated-scroller-scroll_button",
            "type": "button",
        },
        "Latest",
    )
    scroller.replaceChildren(viewport, jump)
    scroller.setAttribute("style", "height:90px")
    viewport.setAttribute("style", "height:90px;max-height:90px")
    content.setAttribute("style", "gap:0;padding:0;min-height:0")
    mount(scroller)
    await wait_for_frames()

    assert scroller.mode == "following-bottom"
    dispatch_wheel(scroller, -40)
    assert scroller.mode == "free-scrolling"


@js
async def test_hydrated_scroll_area_updates_fade_on_scroll():
    area = ScrollArea(div({"style": "height:400px"}, "Long"), height="80px")
    area.setAttribute("data-self-id", "hydrated-scroll-area")
    area.setAttribute("data-bound", "true")
    mount(area)
    await wait_for_frames()

    area.scrollTop = 40
    area.dispatchEvent(Event("scroll"))
    start = area.style.getPropertyValue("--scroll-fade-start")
    assert start.endswith("px")


@js
async def test_hydrated_input_group_addon_focuses_the_control():
    control = InputGroupInput()
    addon = InputGroupAddon("https://")
    group = InputGroup(addon, control)
    group.setAttribute("data-self-id", "hydrated-input-group")
    group.setAttribute("data-bound", "true")
    mount(group)
    await wait_for_frames()

    bubbling_click(addon)
    assert document.activeElement is control


@js
def test_combobox_multi_select_click_toggles_once():
    python_item = ComboboxItem("Python", "Python")
    rust_item = ComboboxItem("Rust", "Rust")
    combobox = Combobox(python_item, rust_item, multiple=True)
    mount(combobox)
    combobox.open()
    bubbling_click(python_item.element)
    assert combobox.selected_values == ["Python"]
    bubbling_click(rust_item.element)
    assert combobox.selected_values == ["Python", "Rust"]


@js
def test_toaster_action_emits_once():
    toaster = Toaster()
    actions = EventCounter()
    toaster.addEventListener("toast-action", actions)
    mount(toaster)
    toast_id = toaster.notify("Saved", "Keep going", duration=0, action_label="Undo")
    bubbling_click(require_element(toaster, "[data-toast-action]"))
    assert actions.count == 1
    assert toaster.last_action_toast_id == toast_id
    assert toaster.querySelector("[data-slot=toast]") is None


@js
def test_combobox_clear_refreshes_filtered_items():
    python_item = ComboboxItem("py", "Python")
    js_item = ComboboxItem("js", "JavaScript")
    combobox = Combobox(python_item, js_item)
    mount(combobox)
    combobox.open()
    combobox.input.value = "xyz"
    combobox.on_input(Event("input"))
    assert combobox.empty.getAttribute("hidden") is None
    bubbling_click(combobox.clear)
    assert combobox.input.value == ""
    assert python_item.element.getAttribute("hidden") is None
    assert combobox.empty.getAttribute("hidden") == ""


@js
def test_combobox_highlight_preserves_selected_aria():
    python_item = ComboboxItem("py", "Python")
    js_item = ComboboxItem("js", "JavaScript")
    combobox = Combobox(python_item, js_item)
    mount(combobox)
    combobox.open()
    bubbling_click(js_item.element)
    assert combobox.selected_value == "js"
    assert js_item.element.getAttribute("aria-selected") == "true"
    combobox.open()
    assert js_item.element.getAttribute("aria-selected") == "true"
    assert python_item.element.getAttribute("data-highlighted") == "true"
    assert python_item.element.getAttribute("aria-selected") == "false"


@js
def test_combobox_removes_portaled_panel_when_disconnected():
    python_item = ComboboxItem("Python", "Python")
    combobox = Combobox(python_item)
    mount(combobox)
    combobox.open()
    assert combobox.panel.parentElement is document.body
    combobox.remove()
    assert not combobox.panel.isConnected
    mount(combobox)
    combobox.open()
    bubbling_click(python_item.element)
    assert combobox.selected_value == "Python"


@js
async def test_message_scroller_clears_autoscrolling_across_remount():
    scroller = MessageScroller(
        tall_item("First", 80, message_id="a"),
        tall_item("Second", 80),
        auto_scroll=True,
    )
    constrain_scroller(scroller, 90)
    mount(scroller)
    scroller.scroll_to_latest()
    dispatch_wheel(scroller, -40)
    scroller.scroll_to_message("a")
    scroller.remove()
    document.body.append(scroller)
    await wait_for_frames()
    assert scroller.autoscrolling is False
    scroller.viewport.scrollTop = scroller.viewport.scrollHeight
    scroller.scrolled(Event("scroll"))
    assert scroller.mode == "following-bottom"


@js
async def test_message_scroller_restores_free_scroll_position_after_remount():
    scroller = MessageScroller(
        tall_item("First", 200),
        tall_item("Second", 200),
        auto_scroll=True,
    )
    constrain_scroller(scroller, 90)
    mount(scroller)
    scroller.scroll_to_latest()
    dispatch_wheel(scroller, -40)
    scroller.viewport.scrollTop = 120
    scroller.scrolled(Event("scroll"))
    await wait_for_frames()
    assert scroller.viewport.scrollTop == 120
    scroller.remove()
    document.body.append(scroller)
    await wait_for_frames()
    assert scroller.viewport.scrollTop == 120


@js
class ResizeCountingScroller(MessageScroller):
    def __init__(self, *children):
        self.resize_count = 0
        super().__init__(*children, auto_scroll=True)

    def content_resized(self, entries: object, observer: object) -> None:
        self.resize_count = self.resize_count + 1
        super().content_resized(entries, observer)


@js
async def test_message_scroller_autoscroll_does_not_loop_on_scrollbar_hide():
    scroller = ResizeCountingScroller(
        tall_item("First", 80),
        tall_item("Second", 80),
        tall_item("Third", 80),
    )
    constrain_scroller(scroller, 90)
    mount(scroller)
    await wait_for_frames(40)
    assert scroller.autoscrolling is False
    first = scroller.resize_count
    await wait_for_frames(40)
    assert scroller.resize_count == first


@js
async def test_message_scroller_reinstalls_observer_after_remount():
    scroller = MessageScroller(
        tall_item("First", 80),
        tall_item("Second", 80),
        auto_scroll=True,
    )
    constrain_scroller(scroller, 90)
    mount(scroller)
    scroller.scroll_to_latest()
    assert scroller.mode == "following-bottom"
    scroller.remove()
    assert scroller.resize_observer is None
    document.body.append(scroller)
    assert scroller.resize_observer is not None
    items = scroller.item_elements()
    last = items[len(items) - 1]
    last.style.setProperty("height", "240px")
    await wait_for_frames()
    assert scroller.is_at_latest()
