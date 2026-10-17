import pytest

from pyjs import js
from pyjs.server import CursorPageRequest
from pyjs.web.events import Event
from pyjs.web.ui.breadcrumb import (
    Breadcrumb,
    BreadcrumbItem,
    BreadcrumbLink,
    BreadcrumbList,
    BreadcrumbPage,
    BreadcrumbSeparator,
)
from pyjs.web.ui.infinite_scroll import InfiniteScroll
from pyjs.web.ui.progress import ProgressBar
from pyjs.web.ui.table import (
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
)
from tests.web.ui.browser import mount, require_element

pytestmark = pytest.mark.pyjs_web


@js
def test_navigation_and_data_widgets_render_and_update_in_the_browser():
    breadcrumb = Breadcrumb(
        BreadcrumbList(
            BreadcrumbItem(BreadcrumbLink("/", "Home")),
            BreadcrumbSeparator(),
            BreadcrumbItem(BreadcrumbPage("Components")),
        )
    )
    progress = ProgressBar(25, "Upload progress")
    table = Table(
        TableHeader(TableRow(TableHead("Name"))),
        TableBody(TableRow(TableCell("Ada"))),
    )
    mount(breadcrumb, progress, table)

    assert breadcrumb.getAttribute("aria-label") == "Breadcrumb"
    assert require_element(breadcrumb, "[aria-current=page]").textContent == "Components"
    assert require_element(table, "table").tagName == "TABLE"
    assert require_element(table, "th").getAttribute("scope") == "col"

    progress.set_value(65)
    assert progress.current_value() == 65
    assert progress.getAttribute("aria-valuenow") == "65"
    root_bounds = progress.getBoundingClientRect()
    indicator_bounds = progress.indicator.getBoundingClientRect()
    assert round(indicator_bounds.width / root_bounds.width * 100) == 65

    progress.set_value(-1)
    assert progress.current_value() == 0

    progress.set_value(101)
    assert progress.current_value() == 100


@js
class ScrollLoader:
    def __init__(self):
        self.requests: list[CursorPageRequest] = []
        self.scroll = InfiniteScroll("next-page", size=4)

    async def load(self, request: CursorPageRequest) -> None:
        self.requests.append(request)
        self.scroll.set_cursor(None)


@js
async def test_infinite_scroll_keeps_browser_callback_registration():
    loader = ScrollLoader()
    scroll = loader.scroll
    scroll.on_load(loader.load)
    # Keep the observed element detached so intersection timing cannot trigger
    # a second load alongside the explicit call being tested.
    scroll.initialize()
    await scroll.load_more(Event("click"))
    assert len(loader.requests) == 1
    assert loader.requests[0].after == "next-page"
    assert loader.requests[0].size == 4
    assert scroll.next_request() is None
    assert scroll.getAttribute("aria-busy") == "false"
    assert scroll.button.getAttribute("disabled") == ""
    assert scroll.status.textContent == "All results loaded."
    scroll.disconnected()
