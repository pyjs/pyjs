from typing import cast

import pytest

from pyjs import js
from pyjs.testing.web import wait_for_frames
from pyjs.web.dom import document, window
from pyjs.web.domx import div
from pyjs.web.events import Event, KeyboardEvent, PointerEvent
from pyjs.web.ui.calendar import Calendar
from pyjs.web.ui.carousel import Carousel, CarouselItem
from pyjs.web.ui.chart import MultiLineChart
from pyjs.web.ui.combobox import Combobox, ComboboxItem
from pyjs.web.ui.command import Command, CommandItem
from pyjs.web.ui.context_menu import (
    ContextMenu,
    ContextMenuContent,
    ContextMenuItem,
    ContextMenuTrigger,
)
from pyjs.web.ui.date_picker import DatePicker
from pyjs.web.ui.input_otp import InputOTP
from pyjs.web.ui.message_scroller import MessageScroller
from pyjs.web.ui.navigation_menu import (
    NavigationMenuContent,
    NavigationMenuItem,
    NavigationMenuTrigger,
)
from pyjs.web.ui.pagination import (
    Pagination,
    PaginationContent,
    PaginationItem,
    PaginationLink,
    PaginationNext,
    PaginationPrevious,
)
from pyjs.web.ui.resizable import ResizableHandle, ResizablePanel, ResizablePanelGroup
from pyjs.web.ui.select import Select, SelectContent, SelectItem, SelectTrigger
from pyjs.web.ui.sidebar import Sidebar, SidebarInset, SidebarLayout, SidebarTrigger
from pyjs.web.ui.slider import Slider
from pyjs.web.ui.sonner import Toaster
from tests.web.ui.browser import bubbling_click, mount, press_key, require_element

pytestmark = pytest.mark.pyjs_web


@js
class EventCounter:
    def __init__(self):
        self.count = 0

    def handleEvent(self, event: Event) -> None:
        self.count = self.count + 1


@js
def test_multi_line_chart_renders_native_svg_and_accessible_legend():
    chart = MultiLineChart(
        [[3, 5, 4], [1, 2, 1]],
        ["Requests", "Errors"],
        ["Mon", "Tue", "Wed"],
        label="Request outcomes",
        value_labels=[
            ["3 requests", "5 requests", "4 requests"],
            ["1 error", "2 errors", "1 error"],
        ],
        annotation_labels=["", "deployed v2", ""],
    )
    mount(chart)

    lines = chart.querySelectorAll("[data-slot=chart-line]")
    points = chart.querySelectorAll("[data-slot=chart-point]")
    legend = require_element(chart, "[data-slot=chart-legend]")

    assert len(lines) == 2
    assert lines[0].getAttribute("data-series") == "Requests"
    assert lines[1].getAttribute("data-series") == "Errors"
    assert len(points) == 6
    assert points[4].getAttribute("aria-label") == "Errors · Tue: 2 errors"
    assert require_element(chart, "svg").getAttribute("aria-label") == "Request outcomes"
    assert legend.getAttribute("aria-label") == "Chart series"
    assert legend.textContent == "RequestsErrors"
    assert (
        require_element(chart, "[data-slot=chart-annotation]").getAttribute("aria-label")
        == "Tue: deployed v2"
    )


@js
def test_pagination_navigation_labels_do_not_overlap_page_links():
    previous = PaginationPrevious("?page=1")
    current = PaginationLink("?page=2", "2", current=True)
    following = PaginationNext("?page=3")
    pagination = Pagination(
        PaginationContent(
            PaginationItem(previous),
            PaginationItem(current),
            PaginationItem(following),
        )
    )
    mount(pagination)

    previous_bounds = previous.getBoundingClientRect()
    current_bounds = current.getBoundingClientRect()
    following_bounds = following.getBoundingClientRect()

    assert previous_bounds.width > current_bounds.width
    assert following_bounds.width > current_bounds.width
    assert previous_bounds.right < current_bounds.left
    assert current_bounds.right < following_bounds.left


@js
def test_calendar_carousel_and_slider_update_native_dom_state():
    calendar = Calendar("July", 2026, starts_on=3, selected_day=21)
    carousel = Carousel(CarouselItem("First"), CarouselItem("Second"))
    slider = Slider(25, label="Volume")
    mount(calendar, carousel, slider.element)

    bubbling_click(require_element(calendar, "[data-day='24']"))
    assert calendar.selected_day() == "24"
    assert require_element(calendar, "[data-day='24']").getAttribute("aria-pressed") == "true"
    assert require_element(calendar, "[data-day='21']").getAttribute("aria-pressed") == "false"

    carousel.next_button.click()
    assert carousel.index == 1
    assert carousel.items[1].getAttribute("aria-hidden") == "false"
    carousel.previous_button.click()
    assert carousel.index == 0

    slider.set_value(80)
    assert slider.get_value() == "80"


@js
def test_command_filters_items_and_keeps_input_focus():
    open_item = CommandItem("Open file", "Open file")
    save_item = CommandItem("Save all", "Save all")
    command = Command(open_item, save_item)
    selected = EventCounter()
    cancelled = EventCounter()
    command.addEventListener("command-select", selected)
    command.addEventListener("command-cancel", cancelled)
    mount(command)

    command.input.value = "save"
    command.input.dispatchEvent(Event("input"))

    assert open_item.getAttribute("hidden") == ""
    assert save_item.getAttribute("hidden") is None
    assert command.empty.getAttribute("hidden") == ""
    assert command.highlighted_item() is save_item.element

    command.input.dispatchEvent(KeyboardEvent("keydown", key="ArrowDown", cancelable=True))
    assert command.highlighted_item() is save_item.element

    command.input.value = "missing"
    command.input.dispatchEvent(Event("input"))
    assert command.empty.getAttribute("hidden") is None

    command.input.value = "open"
    command.input.dispatchEvent(Event("input"))
    assert command.highlighted_item() is open_item.element
    command.input.dispatchEvent(KeyboardEvent("keydown", key="Enter", cancelable=True))
    assert selected.count == 1
    command.input.dispatchEvent(KeyboardEvent("keydown", key="Escape", cancelable=True))
    assert cancelled.count == 1


@js
def test_command_enter_can_submit_instead_of_selecting():
    hit = CommandItem("src/hello.py:1", "src/hello.py:1")
    command = Command(hit, placeholder="Search files", enter_selects=False)
    submitted = EventCounter()
    selected = EventCounter()
    command.addEventListener("command-submit", submitted)
    command.addEventListener("command-select", selected)
    mount(command)

    command.input.dispatchEvent(KeyboardEvent("keydown", key="Enter", cancelable=True))
    assert submitted.count == 1
    assert selected.count == 0
    bubbling_click(hit.element)
    assert selected.count == 1


@js
def test_otp_select_scroller_and_toaster_support_their_core_interactions():
    otp = InputOTP(4)
    select = Select(
        SelectTrigger("Choose"),
        SelectContent(SelectItem("apple", "Apple"), SelectItem("pear", "Pear")),
    )
    scroller = MessageScroller("One", "Two")
    toaster = Toaster()
    mount(otp, select, scroller, toaster)

    otp.set_value("12345")
    assert otp.get_value() == "1234"
    assert require_element(otp, "[data-index='3']").textContent == "4"

    select.open()
    select.select("apple")
    assert select.selected_value == "apple"
    assert (
        require_element(select.trigger.element, "[data-slot=select-value]").textContent
        == "Apple"
    )
    assert select.trigger.getAttribute("aria-expanded") == "false"

    scroller.viewport.scrollTop = 0
    scroller.viewport.style.height = "20px"
    scroller.content.style.height = "500px"
    scroller.scroll_to_latest()
    assert scroller.viewport.scrollTop > 0

    toast_id = toaster.notify("Saved", "Your changes are live.")
    assert toaster.querySelector("[data-toast-id='" + toast_id + "']") is not None
    bubbling_click(require_element(toaster, "[data-toast-close]"))
    assert toaster.querySelector("[data-toast-id='" + toast_id + "']") is None


@js
def test_context_menu_combobox_date_picker_and_sidebar_support_core_interactions():
    context_menu = ContextMenu(
        ContextMenuTrigger("Right click"),
        ContextMenuContent(ContextMenuItem("copy", "Copy")),
    )
    python_item = ComboboxItem("Python", "Python")
    combobox = Combobox(python_item)
    calendar = Calendar("July", 2026, selected_day=21)
    date_picker = DatePicker(calendar)
    sidebar_trigger = SidebarTrigger("☰")
    sidebar_layout = SidebarLayout(Sidebar("Navigation"), SidebarInset(sidebar_trigger, "Main"))
    mount(context_menu, combobox, date_picker, sidebar_layout)

    context_menu.trigger.element.dispatchEvent(Event("contextmenu", bubbles=True, cancelable=True))
    assert context_menu.is_open
    assert context_menu.trigger.getAttribute("aria-expanded") == "true"
    context_menu.close()

    combobox.open()
    bubbling_click(python_item.element)
    assert combobox.selected_value == "Python"
    assert combobox.input.value == "Python"
    assert python_item.getAttribute("aria-selected") == "true"

    date_picker.open()
    bubbling_click(require_element(calendar, "[data-day='24']"))
    assert date_picker.selected_day() == "24"
    assert date_picker.trigger.element.textContent == "24"
    assert not date_picker.is_open

    bubbling_click(sidebar_trigger)
    assert not sidebar_layout.is_open()
    assert sidebar_layout.getAttribute("data-state") == "collapsed"


@js
def test_resizable_and_navigation_menu_support_direct_interaction():
    first_panel = ResizablePanel("Navigation", initial_size=40)
    handle = ResizableHandle(with_handle=True)
    second_panel = ResizablePanel("Content", initial_size=60)
    panels = ResizablePanelGroup(first_panel, handle, second_panel)
    navigation_trigger = NavigationMenuTrigger("Products")
    navigation_content = NavigationMenuContent("Catalog")
    navigation_item = NavigationMenuItem(navigation_trigger, navigation_content)
    mount(panels, navigation_item)

    press_key(handle.element, "ArrowRight")
    assert first_panel.current_size() == 42
    assert second_panel.current_size() == 58
    assert handle.getAttribute("aria-valuenow") == "42"

    navigation_trigger.click()
    assert navigation_item.is_open()
    assert navigation_trigger.getAttribute("aria-expanded") == "true"
    assert navigation_content.getAttribute("hidden") is None

    navigation_trigger.click()
    assert not navigation_item.is_open()
    assert navigation_content.getAttribute("hidden") == ""

    first = ResizablePanel("One", initial_size=30)
    first_handle = ResizableHandle()
    second = ResizablePanel("Two", initial_size=30)
    second_handle = ResizableHandle()
    third = ResizablePanel("Three", initial_size=40)
    group = ResizablePanelGroup(first, first_handle, second, second_handle, third, min_size=10)
    mount(group)
    for _ in range(15):
        press_key(first_handle.element, "ArrowLeft")
    assert first.current_size() == 10.0
    assert second.current_size() == 50.0
    assert third.current_size() == 40.0


@js
async def test_resizable_rebuilds_drag_state_after_server_hydration():
    panels = cast(
        ResizablePanelGroup,
        document.createElement("resizable-panel-group"),
    )
    assert isinstance(panels, ResizablePanelGroup)
    panels.setAttribute("data-direction", "horizontal")
    panels.setAttribute("data-self-id", "hydrated-resizable")
    panels.setAttribute("style", "width: 400px")
    first = div(
        {
            "data-size": "40",
            "data-slot": "resizable-panel",
            "style": "flex-basis: 40%",
        },
        "Navigation",
    )
    handle = div(
        {
            "aria-valuenow": "40",
            "data-direction": "horizontal",
            "data-slot": "resizable-handle",
            "role": "separator",
            "tabindex": "0",
        }
    )
    second = div(
        {
            "data-size": "60",
            "data-slot": "resizable-panel",
            "style": "flex-basis: 60%",
        },
        "Content",
    )
    panels.replaceChildren(first, handle, second)
    mount(panels)
    await wait_for_frames()

    press_key(handle, "ArrowRight")
    assert first.getAttribute("data-size") == "42.0"
    assert second.getAttribute("data-size") == "58.0"

    handle.dispatchEvent(
        PointerEvent(
            "pointerdown",
            bubbles=True,
            cancelable=True,
            clientX=100,
            pointerId=1,
        )
    )
    window.dispatchEvent(PointerEvent("pointermove", clientX=140, pointerId=1))
    window.dispatchEvent(PointerEvent("pointerup", clientX=140, pointerId=1))

    first_size = float(first.getAttribute("data-size"))
    second_size = float(second.getAttribute("data-size"))
    assert first_size > 42
    assert second_size < 58
    assert round(first_size + second_size) == 100
    assert panels.drag_index == -1
