import pytest

from pyjs.web.ui.breadcrumb import (
    Breadcrumb,
    BreadcrumbItem,
    BreadcrumbLink,
    BreadcrumbList,
    BreadcrumbPage,
    BreadcrumbSeparator,
)
from pyjs.web.ui.progress import ProgressBar
from pyjs.web.ui.table import (
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
)


@pytest.mark.pyjs_python
def test_navigation_and_data_widgets_render_semantic_server_html():
    breadcrumb = Breadcrumb(
        BreadcrumbList(
            BreadcrumbItem(BreadcrumbLink("/", "Home")),
            BreadcrumbSeparator(),
            BreadcrumbItem(BreadcrumbPage("Components")),
        )
    )
    progress = ProgressBar(120, "Upload progress")
    table = Table(
        TableHeader(TableRow(TableHead("Name"))),
        TableBody(TableRow(TableCell("Ada"))),
    )

    assert breadcrumb.tagName == "NAV"
    assert breadcrumb.getAttribute("aria-label") == "Breadcrumb"
    assert progress.current_value() == 100
    assert progress.getAttribute("aria-valuenow") == "100"
    assert progress.indicator.getAttribute("style") == "width: 100%"
    assert table.getAttribute("data-slot") == "table-container"
    assert table.children[0].tagName == "TABLE"
