import asyncio

import pytest

from pyjs.server import CursorPageRequest, Page
from pyjs.web.events import Event
from pyjs.web.ssr import render_html
from pyjs.web.ui.attachment import (
    Attachment,
    AttachmentContent,
    AttachmentDescription,
    AttachmentGroup,
    AttachmentTitle,
)
from pyjs.web.ui.bubble import Bubble, BubbleContent
from pyjs.web.ui.calendar import Calendar
from pyjs.web.ui.carousel import Carousel, CarouselItem
from pyjs.web.ui.chart import BarChart, LineChart, MultiLineChart
from pyjs.web.ui.combobox import Combobox, ComboboxItem
from pyjs.web.ui.command import Command, CommandItem
from pyjs.web.ui.context_menu import (
    ContextMenu,
    ContextMenuContent,
    ContextMenuItem,
    ContextMenuTrigger,
)
from pyjs.web.ui.date_picker import DatePicker
from pyjs.web.ui.direction import Direction
from pyjs.web.ui.drawer import Drawer, DrawerContent, DrawerTitle, DrawerTrigger
from pyjs.web.ui.infinite_scroll import InfiniteScroll
from pyjs.web.ui.input_group import InputGroup, InputGroupAddon, InputGroupInput
from pyjs.web.ui.input_otp import InputOTP
from pyjs.web.ui.item import Item, ItemContent, ItemDescription, ItemTitle
from pyjs.web.ui.marker import Marker, MarkerContent
from pyjs.web.ui.menubar import Menubar, MenubarItem, MenubarMenu
from pyjs.web.ui.message import Message, MessageContent, MessageGroup
from pyjs.web.ui.message_scroller import MessageScroller
from pyjs.web.ui.native_select import NativeSelect, NativeSelectOption
from pyjs.web.ui.navigation_menu import (
    NavigationMenu,
    NavigationMenuLink,
    NavigationMenuList,
)
from pyjs.web.ui.pagination import (
    CursorPagination,
    Pagination,
    PaginationContent,
    PaginationItem,
    PaginationLink,
)
from pyjs.web.ui.resizable import ResizableHandle, ResizablePanel, ResizablePanelGroup
from pyjs.web.ui.scroll_area import ScrollArea
from pyjs.web.ui.select import Select, SelectContent, SelectItem, SelectTrigger
from pyjs.web.ui.sidebar import (
    MobileSidebar,
    Sidebar,
    SidebarContent,
    SidebarInset,
    SidebarLayout,
    SidebarMenu,
    SidebarMenuButton,
    SidebarMenuItem,
    SidebarTrigger,
)
from pyjs.web.ui.slider import Slider
from pyjs.web.ui.sonner import Toaster
from pyjs.web.ui.typography import TypographyH1, TypographyP


@pytest.mark.pyjs_python
def test_remaining_content_primitives_render_stable_semantics():
    title = AttachmentTitle("report.pdf")
    attachment = AttachmentGroup(
        Attachment(AttachmentContent(title, AttachmentDescription("240 KB")))
    )
    bubble = Bubble(BubbleContent("Hello"), align="end", variant="tinted")
    item = Item(ItemContent(ItemTitle("Account"), ItemDescription("Profile settings")))
    messages = MessageGroup(Message(MessageContent("Welcome")))
    marker = Marker(MarkerContent("New"))
    direction = Direction(TypographyH1("Heading"), TypographyP("Copy"), direction="rtl")

    assert attachment.getAttribute("role") == "list"
    assert title.getAttribute("data-slot") == "attachment-title"
    assert bubble.getAttribute("data-align") == "end"
    assert bubble.getAttribute("data-variant") == "tinted"
    assert item.getAttribute("role") == "listitem"
    assert messages.getAttribute("role") == "log"
    assert marker.getAttribute("data-slot") == "marker"
    assert direction.getAttribute("dir") == "rtl"


@pytest.mark.pyjs_python
def test_remaining_form_and_navigation_primitives_use_native_semantics():
    input_control = InputGroupInput(name="site")
    input_group = InputGroup(InputGroupAddon("https://"), input_control)
    native_select = NativeSelect(
        NativeSelectOption("one", "One", selected=True),
        NativeSelectOption("two", "Two"),
        name="number",
        label="Number",
    )
    current_page = PaginationLink("?page=1", "1", current=True)
    pagination = Pagination(
        PaginationContent(
            PaginationItem(current_page),
            PaginationItem(PaginationLink("?page=2", "2")),
        )
    )
    navigation_link = NavigationMenuLink("/docs", "Docs", current=True)
    navigation = NavigationMenu(NavigationMenuList(navigation_link))
    slider = Slider(25, label="Volume", name="volume")

    assert input_group.getAttribute("data-slot") == "input-group"
    assert input_group.getAttribute("role") == "group"
    assert input_control.getAttribute("name") == "site"
    assert 'data-bound="' not in render_html(input_group)
    assert 'data-bound="' not in render_html(MessageScroller("One", "Two"))
    assert 'data-bound="' not in render_html(ScrollArea("Long content", height="10rem"))
    assert native_select.children[0].getAttribute("aria-label") == "Number"
    assert pagination.getAttribute("aria-label") == "Pagination"
    assert current_page.getAttribute("aria-current") == "page"
    assert navigation.tagName == "NAV"
    assert navigation_link.getAttribute("data-pyjs-navigation-link") == ""
    assert slider.getAttribute("type") == "range"
    assert slider.getAttribute("value") == "25"
    assert slider.getAttribute("class") == (
        "h-5 w-full cursor-pointer accent-slate-950 "
        "disabled:cursor-not-allowed disabled:opacity-50"
    )


@pytest.mark.pyjs_python
def test_cursor_pagination_owns_cursor_button_state_and_requests():
    pagination = CursorPagination(size=20)
    pagination.set_page(
        Page[str](
            items=["one"],
            next="next-cursor",
            previous="previous-cursor",
        )
    )

    assert pagination.previous_request() == CursorPageRequest(
        size=20,
        before="previous-cursor",
    )
    assert pagination.next_request() == CursorPageRequest(
        size=20,
        after="next-cursor",
    )

    requests: list[CursorPageRequest] = []

    async def load_page(request: CursorPageRequest):
        requests.append(request)

    pagination.on_page(load_page)
    asyncio.run(pagination._load_previous(Event("click")))
    asyncio.run(pagination._load_next(Event("click")))

    assert requests == [
        CursorPageRequest(size=20, before="previous-cursor"),
        CursorPageRequest(size=20, after="next-cursor"),
    ]

    pagination.set_size(10)

    assert pagination.getAttribute("data-page-size") == "10"
    assert pagination.next_request() == CursorPageRequest(
        size=10,
        after="next-cursor",
    )

    pagination.set_page(Page[str](items=[]))

    assert pagination.previous_request() is None
    assert pagination.next_request() is None
    assert pagination.previous.getAttribute("disabled") == ""
    assert pagination.next.getAttribute("disabled") == ""


@pytest.mark.pyjs_python
def test_remaining_interactive_components_store_initial_state_on_the_dom():
    calendar = Calendar("July", 2026, days=31, starts_on=3, selected_day=21)
    carousel = Carousel(CarouselItem("First"), CarouselItem("Second"))
    command = Command(CommandItem("Open file", "Open file"), CommandItem("Save", "Save"))
    otp = InputOTP(6, name="code")
    scroller = MessageScroller("One", "Two")
    select = Select(
        SelectTrigger("Choose a fruit"),
        SelectContent(SelectItem("apple", "Apple"), SelectItem("pear", "Pear")),
        value="pear",
    )
    toaster = Toaster()

    assert calendar.selected_day() == "21"
    assert len(calendar.children[2].children) == 34
    assert carousel.getAttribute("data-index") == "0"
    assert carousel.items[0].getAttribute("aria-hidden") == "false"
    assert command.input.getAttribute("role") == "combobox"
    assert command.getAttribute("data-enter-selects") == "true"
    search = Command(CommandItem("Hit", "Hit"), enter_selects=False)
    assert search.getAttribute("data-enter-selects") == "false"
    assert len(otp.children[1].children) == 6
    assert scroller.viewport.getAttribute("role") == "region"
    assert scroller.content.getAttribute("role") == "log"
    assert select.selected_value == "pear"
    assert select.item_elements()[1].getAttribute("aria-selected") == "true"
    assert toaster.getAttribute("aria-live") == "polite"


@pytest.mark.pyjs_python
def test_remaining_visual_and_modal_components_have_accessible_structure():
    chart = BarChart([10, 20, 15], ["One", "Two", "Three"], label="Quarterly sales")
    drawer = Drawer(DrawerTrigger("Open"), DrawerContent("Settings", DrawerTitle("Settings")))
    panels = ResizablePanelGroup(
        ResizablePanel("One", initial_size=40),
        ResizableHandle(with_handle=True),
        ResizablePanel("Two", initial_size=60),
    )
    scroll_area = ScrollArea("Long content", height="10rem")

    assert chart.children[0].getAttribute("aria-label") == "Quarterly sales"
    assert len(chart.children[0].children) == 3
    assert chart.children[0].children[0].getAttribute("height") == "75"
    assert drawer.content.dialog_element.getAttribute("data-side") == "bottom"
    assert panels.children[1].getAttribute("aria-label") == "Resize panels"
    assert panels.current_size(panels.panel_elements()[0]) == 40
    assert panels.handle_elements()[0].getAttribute("aria-valuenow") == "40"
    assert panels.getAttribute("data-min-size") == "10"
    chrome_free = ResizablePanelGroup(
        ResizablePanel("One", initial_size=30),
        ResizableHandle(),
        ResizablePanel("Two", initial_size=70),
        framed=False,
        min_size=15,
    )
    assert chrome_free.getAttribute("data-min-size") == "15"
    assert "border-slate-200" not in (chrome_free.getAttribute("class") or "")
    assert scroll_area.getAttribute("tabindex") == "0"
    assert "scrollbar-width:thin" in render_html(scroll_area)


@pytest.mark.pyjs_python
def test_line_chart_updates_a_real_svg_data_series():
    chart = LineChart(
        [3, 5, 4],
        ["Mon", "Tue", "Wed"],
        label="Visits",
        value_labels=["3 visits", "5 visits", "4 visits"],
        annotation_labels=["", "deployed v2", ""],
    )

    assert chart.chart().namespaceURI == "http://www.w3.org/2000/svg"
    assert chart.chart().getAttribute("aria-label") == "Visits"
    assert chart.chart().children[3].getAttribute("d") == (
        "M40 360 L500 40 L960 200"
    )
    assert len(chart.chart().children) == 8
    annotations = [
        child
        for child in chart.chart().children
        if child.getAttribute("data-slot") == "chart-annotation"
    ]
    assert len(annotations) == 1
    assert annotations[0].getAttribute("aria-label") == "Tue: deployed v2"

    chart.append_point(
        8,
        "Thu",
        max_points=3,
        value_label="8 visits",
        annotation_label="deployed v3",
    )

    points = [
        child
        for child in chart.chart().children
        if child.getAttribute("data-slot") == "chart-point"
    ]
    assert [point.getAttribute("data-label") for point in points] == [
        "Tue",
        "Wed",
        "Thu",
    ]
    assert [point.getAttribute("data-value") for point in points] == ["5", "4", "8"]
    assert [point.getAttribute("aria-label") for point in points] == [
        "Tue: 5 visits",
        "Wed: 4 visits",
        "Thu: 8 visits",
    ]
    annotations = [
        child
        for child in chart.chart().children
        if child.getAttribute("data-slot") == "chart-annotation"
    ]
    assert [item.getAttribute("data-annotation-label") for item in annotations] == [
        "deployed v2",
        "deployed v3",
    ]


@pytest.mark.pyjs_python
def test_multi_line_chart_renders_aligned_series_and_legend():
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

    paths = [
        child
        for child in chart.chart().children
        if child.getAttribute("data-slot") == "chart-line"
    ]
    points = [
        child
        for child in chart.chart().children
        if child.getAttribute("data-slot") == "chart-point"
    ]
    annotations = [
        child
        for child in chart.chart().children
        if child.getAttribute("data-slot") == "chart-annotation"
    ]

    assert chart.chart().getAttribute("aria-label") == "Request outcomes"
    assert [path.getAttribute("data-series") for path in paths] == [
        "Requests",
        "Errors",
    ]
    assert len(points) == 6
    assert annotations[0].getAttribute("aria-label") == "Tue: deployed v2"
    assert points[-1].getAttribute("aria-label") == "Errors · Wed: 1 error"
    assert chart.children[1].getAttribute("aria-label") == "Chart series"
    assert [
        item.getAttribute("data-series-label")
        for item in chart.children[1].children
    ] == [
        "Requests",
        "Errors",
    ]

    with pytest.raises(ValueError, match="must be aligned"):
        MultiLineChart([[1], [1, 2]], ["One", "Two"])
    with pytest.raises(ValueError, match="series labels must have equal lengths"):
        MultiLineChart([[1]], [])
    with pytest.raises(
        ValueError,
        match="formatted value labels must have equal lengths",
    ):
        MultiLineChart([[1]], ["One"], value_labels=[])
    with pytest.raises(ValueError, match="formatted value labels must be aligned"):
        MultiLineChart([[1, 2]], ["One"], value_labels=[["1"]])
    with pytest.raises(ValueError, match="requires at least one color"):
        MultiLineChart([[1]], ["One"], colors=[])


@pytest.mark.pyjs_python
def test_infinite_scroll_owns_cursor_loading_and_terminal_state():
    requests = []
    scroll = InfiniteScroll("next-page", label="Older visits", size=4)

    async def load(request: CursorPageRequest):
        requests.append(request)
        scroll.set_cursor(None)

    scroll.on_load(load)
    scroll.initialize()
    asyncio.run(scroll.load_more(Event("click")))

    assert requests == [CursorPageRequest(size=4, after="next-page")]
    assert scroll.next_request() is None
    assert scroll.getAttribute("aria-busy") == "false"
    assert scroll.button.getAttribute("disabled") == ""
    assert scroll.status.textContent == "All results loaded."


@pytest.mark.pyjs_python
def test_remaining_composite_components_have_coherent_server_state():
    context_menu = ContextMenu(
        ContextMenuTrigger("Right click"),
        ContextMenuContent(ContextMenuItem("copy", "Copy")),
    )
    menubar = Menubar(MenubarMenu("File", MenubarItem("new", "New")))
    combobox = Combobox(ComboboxItem("Python", "Python"), name="language")
    date_picker = DatePicker(Calendar("July", 2026, selected_day=21))
    sidebar = Sidebar("Navigation")
    inset = SidebarInset(SidebarTrigger("☰"), "Content")
    sidebar_layout = SidebarLayout(sidebar, inset)
    mobile_sidebar = MobileSidebar("Navigation", SidebarContent("Links"))

    assert context_menu.trigger.getAttribute("aria-haspopup") == "menu"
    assert menubar.getAttribute("role") == "menubar"
    assert combobox.input.getAttribute("aria-autocomplete") == "list"
    assert date_picker.selected_day() == "21"
    assert sidebar_layout.is_open()
    assert sidebar.getAttribute("data-slot") == "sidebar"
    assert mobile_sidebar.getAttribute("data-slot") == "mobile-sidebar"
    assert mobile_sidebar.trigger.getAttribute("aria-label") == "Open navigation"
    assert mobile_sidebar.content.dialog_element.getAttribute("data-side") == "left"
    assert mobile_sidebar.content.dialog_element.getAttribute("data-mobile") == "true"


@pytest.mark.pyjs_python
def test_sidebar_menu_uses_navigation_semantics():
    menu = SidebarMenu(
        SidebarMenuItem(SidebarMenuButton("/", "Home", current=True)),
        SidebarMenuItem(SidebarMenuButton("/settings", "Settings")),
    )
    content = SidebarContent(menu)

    assert menu.tagName == "UL"
    assert menu.children[0].tagName == "LI"
    assert menu.children[0].children[0].getAttribute("aria-current") == "page"
    assert content.getAttribute("data-slot") == "sidebar-content"


@pytest.mark.pyjs_python
def test_new_components_reject_invalid_configuration():
    with pytest.raises(ValueError, match="Direction"):
        Direction("copy", direction="sideways")
    with pytest.raises(ValueError, match="between 28 and 31"):
        Calendar("February", 2026, days=27)
    with pytest.raises(ValueError, match="greater than minimum"):
        Slider(minimum=10, maximum=10)
    with pytest.raises(ValueError, match="positive"):
        InputOTP(0)
