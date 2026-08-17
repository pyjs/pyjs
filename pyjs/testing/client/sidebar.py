from typing import cast

from pyjs import js
from pyjs.testing.client.state import TestState
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, button, div, ref, span, tag, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement
from pyjs.web.ui.input import Input


@js
def short_test_name(nodeid: str) -> str:
    parts = nodeid.split("::")
    return parts[len(parts) - 1] or nodeid


@js
def test_file_name(nodeid: str) -> str:
    parts = nodeid.split("::")
    return parts[0] or nodeid


@js
def test_scope_name(nodeid: str) -> str:
    parts = nodeid.split("::")
    if len(parts) <= 2:
        return ""
    scope = ""
    for index in range(1, len(parts) - 1):
        if scope != "":
            scope += " › "
        scope += parts[index]
    return scope


# Each listener needs its own nodeid binding. Defining the closure here avoids
# late-binding the render-loop variable to the final test row.
@js
def bind_select(row: HTMLElement, on_select: callable, nodeid: str) -> None:
    row.addEventListener("click", lambda event: on_select(nodeid))


@js
def status_icon(status: str):
    symbol = "·"
    if status == "passed":
        symbol = "✓"
    elif status == "failed":
        symbol = "×"
    elif status == "running":
        symbol = "↻"
    return span(
        tw(
            "grid size-5 shrink-0 place-items-center rounded-full border text-[11px] font-bold "
            "data-[status=pending]:border-slate-700 data-[status=pending]:text-slate-500 "
            "data-[status=running]:animate-pulse data-[status=running]:border-sky-500/50 "
            "data-[status=running]:bg-sky-500/10 data-[status=running]:text-sky-400 "
            "data-[status=passed]:border-emerald-500/40 data-[status=passed]:bg-emerald-500/10 "
            "data-[status=passed]:text-emerald-400 data-[status=failed]:border-rose-500/50 "
            "data-[status=failed]:bg-rose-500/10 data-[status=failed]:text-rose-400"
        ),
        {"aria-hidden": "true", "data-status": status},
        symbol,
    )


@js
class RunnerSidebar(CustomElement):
    def __init__(self):
        super().__init__()
        self.selectedFilter = "all"
        self.search = ref(Input(input_type="search", placeholder="Filter tests...", name="filter"))
        self.search.setAttribute("aria-label", "Filter tests")
        self.search.setAttribute("data-testid", "test-filter")
        self.search.on_input(self.filters_changed)

        self.totalCount = ref(span("0"))
        self.passedCount = ref(span("0"))
        self.failedCount = ref(span("0"))
        self.runningCount = ref(span("0"))
        self.keptCount = ref(span("0"))
        self.visibleCount = ref(span("0 tests"))
        self.visibleSummary = ref(
            div(
                tw("mt-0.5 hidden text-xs text-slate-500 dark:text-slate-400"),
                {"data-testid": "visible-test-count"},
                self.visibleCount,
                " visible",
            )
        )
        self.test_list = ref(
            div(
                tw(
                    "grid min-h-0 flex-1 grid-cols-[auto_minmax(0,1fr)_auto_auto] "
                    "content-start gap-x-2 overflow-y-auto px-2 pb-3"
                ),
                {"data-testid": "test-list", "id": "test-list"},
            )
        )
        filters = div(
            tw("grid grid-cols-4 gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-900"),
            {
                "aria-label": "Filter tests by status",
                "data-testid": "status-filters",
                "role": "group",
            },
            self.filter_button("all", "All", self.totalCount),
            self.filter_button("failed", "Failed", self.failedCount),
            self.filter_button("passed", "Passed", self.passedCount),
            self.filter_button("running", "Running", self.runningCount),
        )
        header = div(
            tw("grid gap-3 border-b border-slate-200 p-3 dark:border-slate-800"),
            div(
                tw("flex items-center justify-between gap-3"),
                div(
                    tag(
                        "h2",
                        tw("text-sm font-semibold text-slate-950 dark:text-slate-100"),
                        "Tests",
                    ),
                    self.visibleSummary,
                ),
                div(
                    tw("flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400"),
                    span(tw("text-violet-500 dark:text-violet-400"), "◫"),
                    self.keptCount,
                    span("previews"),
                ),
            ),
            self.search,
            filters,
        )
        self.emptyTitle = ref(
            tag(
                "h3",
                tw("mt-3 text-sm font-medium text-slate-900 dark:text-slate-200"),
                "Waiting for a test run",
            )
        )
        self.emptyDescription = ref(
            tag(
                "p",
                tw("mt-1 text-xs leading-5 text-slate-500"),
                "Start pytest with the web target to populate this workspace.",
            )
        )
        self.empty = ref(
            div(
                tw("hidden place-items-center px-6 py-16 text-center"),
                {"data-testid": "filtered-empty"},
                div(
                    span(
                        tw(
                            "mx-auto grid size-10 place-items-center rounded-full bg-slate-100 "
                            "text-slate-400 dark:bg-slate-900 dark:text-slate-500"
                        ),
                        "⌕",
                    ),
                    self.emptyTitle,
                    self.emptyDescription,
                ),
            )
        )
        self.addEventListener("click", self.filter_clicked)
        tag(
            self,
            tw(
                "flex min-h-0 flex-col border-r border-slate-200 bg-white/90 "
                "dark:border-slate-800 dark:bg-slate-950/80"
            ),
            header,
            self.test_list,
            self.empty,
        )

    def filter_button(self, value: str, label: str, count: HTMLElement):
        return button(
            tw(
                "flex min-w-0 items-center justify-center gap-1 rounded-md px-2 py-1.5 "
                "text-xs font-medium text-slate-500 outline-none transition-colors "
                "hover:text-slate-950 focus-visible:ring-2 focus-visible:ring-sky-500 "
                "data-[selected=true]:bg-white data-[selected=true]:text-slate-950 "
                "data-[selected=true]:shadow-sm dark:text-slate-400 dark:hover:text-slate-100 "
                "dark:data-[selected=true]:bg-slate-800 dark:data-[selected=true]:text-white"
            ),
            {
                "aria-pressed": "true" if value == "all" else "false",
                "data-filter": value,
                "data-selected": "true" if value == "all" else "false",
                "type": "button",
            },
            span(tw("truncate"), label),
            count,
        )

    def filter_clicked(self, event: Event):
        target = cast(Element, event.target)
        filter_button = target.closest("[data-filter]")
        if filter_button is None:
            return
        value = filter_button.getAttribute("data-filter")
        if value is None:
            return
        self.selectedFilter = value
        buttons: list[HTMLElement] = self.querySelectorAll("[data-filter]")
        for candidate in buttons:
            selected = candidate.getAttribute("data-filter") == value
            candidate.setAttribute("aria-pressed", "true" if selected else "false")
            candidate.setAttribute("data-selected", "true" if selected else "false")
        self.applyFilters()

    def filters_changed(self, event: Event):
        self.applyFilters()

    def applyFilters(self):
        query = self.search.get_value().lower()
        visible_files: list[str] = []
        visible_count = 0
        rows: list[HTMLElement] = self.test_list.querySelectorAll("[data-test-nodeid]")
        for row in rows:
            status = row.getAttribute("data-status")
            search_text = row.getAttribute("data-search")
            file_name = row.getAttribute("data-file")
            status_matches = self.selectedFilter == "all" or status == self.selectedFilter
            search_matches = query == ""
            if search_text is not None and query in search_text:
                search_matches = True
            visible = status_matches and search_matches
            if visible:
                row.removeAttribute("hidden")
                visible_count += 1
                if file_name is not None and file_name not in visible_files:
                    visible_files.append(file_name)
            else:
                row.setAttribute("hidden", "")
        groups: list[HTMLElement] = self.test_list.querySelectorAll("[data-test-file]")
        for group in groups:
            file_name = group.getAttribute("data-test-file")
            if file_name is not None and file_name in visible_files:
                group.removeAttribute("hidden")
            else:
                group.setAttribute("hidden", "")
        self.visibleCount.textContent = str(visible_count) + " tests"
        self.visibleSummary.classList.toggle("hidden", query == "")
        if len(rows) == 0:
            self.emptyTitle.textContent = "Waiting for a test run"
            self.emptyDescription.textContent = (
                "Start pytest with the web target to populate this workspace."
            )
        else:
            self.emptyTitle.textContent = "No matching tests"
            self.emptyDescription.textContent = "Try another search or status filter."
        self.empty.classList.toggle("hidden", visible_count != 0)
        self.empty.classList.toggle("grid", visible_count == 0)
        self.test_list.classList.toggle("hidden", visible_count == 0)

    def updateCounts(self, states: list[TestState]):
        passed = 0
        failed = 0
        running = 0
        kept = 0
        for state in states:
            if state.status == "passed":
                passed += 1
            elif state.status == "failed":
                failed += 1
            elif state.status == "running":
                running += 1
            if state.hasPreview:
                kept += 1
        self.totalCount.textContent = str(len(states))
        self.passedCount.textContent = str(passed)
        self.failedCount.textContent = str(failed)
        self.runningCount.textContent = str(running)
        self.keptCount.textContent = str(kept)

    def renderTests(
        self,
        states: list[TestState],
        selected_nodeid: str | None,
        on_select: callable,
    ):
        self.test_list.replaceChildren()
        self.updateCounts(states)
        current_file = ""
        for state in states:
            nodeid = state.nodeid
            file_name = test_file_name(nodeid)
            if file_name != current_file:
                current_file = file_name
                file_header = div(
                    tw(
                        "sticky top-0 z-10 col-span-4 mt-2 flex items-center gap-2 border-y "
                        "border-slate-200 bg-white/95 px-2 py-2 text-[11px] font-medium "
                        "text-slate-500 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 "
                        "dark:text-slate-400"
                    ),
                    {"data-test-file": file_name},
                    span(tw("text-slate-400 dark:text-slate-600"), "▾"),
                    span(tw("truncate"), file_name),
                )
                self.test_list.append(file_header)

            row = button(
                tw(
                    "test-row group col-span-4 grid w-full grid-cols-subgrid items-center "
                    "rounded-lg border border-transparent px-2 py-2.5 text-left outline-none "
                    "transition-colors hover:bg-slate-100 focus-visible:ring-2 "
                    "focus-visible:ring-sky-500 data-[selected=true]:border-slate-200 "
                    "data-[selected=true]:bg-slate-100 dark:hover:bg-slate-900 "
                    "dark:data-[selected=true]:border-slate-700 dark:data-[selected=true]:bg-slate-900"
                ),
                {
                    "data-file": file_name,
                    "data-search": nodeid.lower(),
                    "data-selected": "true" if nodeid == selected_nodeid else "false",
                    "data-status": state.status,
                    "data-test-nodeid": nodeid,
                    "type": "button",
                },
                status_icon(state.status),
            )
            row.classList.add("has-preview" if state.hasPreview else "no-preview")
            if nodeid == selected_nodeid:
                row.classList.add("active")
            scope = test_scope_name(nodeid)
            name_column = div(
                tw("min-w-0"),
                div(
                    tw(
                        "test-row-name truncate text-[13px] font-medium text-slate-800 "
                        "dark:text-slate-200"
                    ),
                    short_test_name(nodeid),
                ),
            )
            if scope != "":
                name_column.append(
                    div(
                        tw("mt-0.5 truncate text-[11px] text-slate-500"),
                        scope,
                    )
                )
            full_nodeid = div(tw("test-row-nodeid sr-only"), nodeid)
            name_column.append(full_nodeid)
            preview_slot = span(tw("grid place-items-center text-[10px] text-slate-500"))
            if state.hasPreview:
                preview_slot.append(
                    span(
                        tw("text-violet-500 dark:text-violet-400"),
                        {
                            "aria-label": "Rendered preview retained",
                            "data-preview-indicator": "true",
                            "title": "Rendered preview retained",
                        },
                        "◫",
                    )
                )
            output_slot = span(
                tw("flex items-center gap-0.5 text-[10px] text-slate-500 tabular-nums"),
            )
            if len(state.consoleLines) > 0:
                output_slot.append(
                    span(
                        {
                            "aria-label": "Captured console output",
                            "data-output-indicator": "true",
                            "title": "Captured console output",
                        },
                        "≡",
                    ),
                    span(str(len(state.consoleLines))),
                )
            row.append(name_column, preview_slot, output_slot)
            bind_select(row, on_select, nodeid)
            self.test_list.append(row)
        self.applyFilters()
