from typing import cast

from pyjs import js
from pyjs.testing.client.sidebar import short_test_name, test_file_name
from pyjs.testing.client.state import TestState
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, button, div, ref, span, tag, tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLElement, HTMLIFrameElement


@js
def frame_has_meaningful_content(frame: HTMLIFrameElement) -> bool:
    try:
        doc = frame.contentDocument
        if doc is None:
            return False
        body = doc.body
        if body.childElementCount > 0:
            return True
        text = body.textContent
        if text is None:
            return False
        return len(text.strip()) > 0
    except Exception:
        return True


@js
def panel_button(name: str, label: str, badge: HTMLElement | None = None):
    tab = button(
        tw(
            "relative flex h-11 items-center gap-2 border-b-2 border-transparent px-3 "
            "text-xs font-medium text-slate-500 outline-none transition-colors "
            "hover:text-slate-950 focus-visible:ring-2 focus-visible:ring-inset "
            "focus-visible:ring-sky-500 data-[selected=true]:border-sky-500 "
            "data-[selected=true]:text-slate-950 dark:text-slate-400 "
            "dark:hover:text-slate-100 dark:data-[selected=true]:text-white"
        ),
        {
            "aria-selected": "true" if name == "preview" else "false",
            "data-panel-button": name,
            "data-selected": "true" if name == "preview" else "false",
            "role": "tab",
            "type": "button",
        },
        label,
    )
    if badge is not None:
        tab.append(badge)
    return tab


@js
class RunnerViewer(CustomElement):
    def __init__(self):
        super().__init__()
        self.currentFrame: HTMLIFrameElement | None = None
        self.currentFrameNodeid: str | None = None
        self.selectedPanel = "preview"

        self.testName = ref(
            tag(
                "h2",
                tw("truncate text-sm font-semibold text-slate-950 dark:text-slate-100"),
                "No test selected",
            )
        )
        self.testPath = ref(
            div(
                tw("truncate text-xs text-slate-500 dark:text-slate-400"),
                "Select a test to inspect",
            )
        )
        self.testStatus = ref(
            span(
                tw(
                    "rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] "
                    "font-medium text-slate-500 dark:border-slate-700 dark:bg-slate-900 "
                    "dark:text-slate-400 data-[status=running]:border-sky-500/30 "
                    "data-[status=running]:bg-sky-500/10 data-[status=running]:text-sky-600 "
                    "data-[status=passed]:border-emerald-500/30 "
                    "data-[status=passed]:bg-emerald-500/10 data-[status=passed]:text-emerald-600 "
                    "data-[status=failed]:border-rose-500/30 data-[status=failed]:bg-rose-500/10 "
                    "data-[status=failed]:text-rose-600 dark:data-[status=running]:text-sky-300 "
                    "dark:data-[status=passed]:text-emerald-300 "
                    "dark:data-[status=failed]:text-rose-300"
                ),
                {"data-testid": "selected-status"},
                "Idle",
            )
        )
        selected_header = div(
            tw(
                "flex min-h-16 items-center justify-between gap-4 border-b border-slate-200 "
                "px-4 py-3 dark:border-slate-800"
            ),
            div(tw("min-w-0"), self.testName, self.testPath),
            self.testStatus,
        )

        self.outputCount = ref(
            span(
                tw(
                    "rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 "
                    "dark:bg-slate-800 dark:text-slate-300"
                ),
                "0",
            )
        )
        self.errorCount = ref(
            span(
                tw(
                    "hidden rounded-full bg-rose-100 px-1.5 py-0.5 text-[10px] text-rose-700 "
                    "dark:bg-rose-500/15 dark:text-rose-300"
                ),
                "0",
            )
        )
        tabs = div(
            tw("flex border-b border-slate-200 px-1 dark:border-slate-800"),
            {"aria-label": "Test details", "role": "tablist"},
            panel_button("preview", "Preview"),
            panel_button("output", "Output", self.outputCount),
            panel_button("errors", "Errors", self.errorCount),
        )

        self.currentFrameLabel = ref(
            div(
                tw("min-w-0 flex-1 truncate text-xs text-slate-500 dark:text-slate-400"),
                "No preview available",
            )
        )
        browser_bar = div(
            tw(
                "flex h-10 items-center gap-3 border-b border-slate-200 bg-slate-100 px-3 "
                "dark:border-slate-700 dark:bg-slate-800/80"
            ),
            div(
                tw("flex shrink-0 gap-1.5"),
                span(tw("size-2.5 rounded-full bg-rose-400 dark:bg-rose-500/70")),
                span(tw("size-2.5 rounded-full bg-amber-400 dark:bg-amber-500/70")),
                span(tw("size-2.5 rounded-full bg-emerald-400 dark:bg-emerald-500/70")),
            ),
            div(
                tw(
                    "flex min-w-0 flex-1 items-center rounded-md border border-slate-200 "
                    "bg-white px-2.5 py-1.5 dark:border-slate-700 dark:bg-slate-900"
                ),
                span(tw("mr-2 text-[10px] text-emerald-500"), "●"),
                self.currentFrameLabel,
            ),
            span(tw("shrink-0 text-xs text-slate-400"), "100%"),
        )
        self.frameHost = ref(
            div(
                tw(
                    "frame-host relative min-h-0 flex-1 overflow-hidden bg-slate-100 "
                    "dark:bg-slate-950"
                ),
                {"data-empty": "true", "data-empty-label": "No preview available"},
            )
        )
        preview_surface = div(
            tw(
                "flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border "
                "border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900"
            ),
            browser_bar,
            self.frameHost,
        )
        self.previewPanel = ref(
            div(
                tw("flex min-h-0 flex-1 flex-col p-3"),
                {"data-panel": "preview", "role": "tabpanel"},
                preview_surface,
            )
        )

        self.currentConsoleOutput = ref(
            div(
                tw(
                    "console-output min-h-0 flex-1 overflow-auto rounded-xl border "
                    "border-slate-200 bg-slate-50 font-mono text-xs leading-5 "
                    "dark:border-slate-800 dark:bg-slate-950"
                ),
                "No console output recorded",
            )
        )
        self.outputPanel = ref(
            div(
                tw("hidden min-h-0 flex-1 p-3"),
                {"data-panel": "output", "role": "tabpanel"},
                self.currentConsoleOutput,
            )
        )

        self.errorOutput = ref(
            tag(
                "pre",
                tw(
                    "m-0 min-h-full whitespace-pre-wrap break-words rounded-xl border "
                    "border-slate-200 bg-slate-50 p-4 font-mono text-xs leading-5 "
                    "text-slate-600 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400"
                ),
                "No errors recorded",
            )
        )
        self.errorPanel = ref(
            div(
                tw("hidden min-h-0 flex-1 overflow-auto p-3"),
                {"data-panel": "errors", "role": "tabpanel"},
                self.errorOutput,
            )
        )

        self.viewerRoot = ref(
            div(
                tw(
                    "viewer flex min-h-0 flex-1 flex-col overflow-hidden bg-white dark:bg-slate-950"
                ),
                selected_header,
                tabs,
                self.previewPanel,
                self.outputPanel,
                self.errorPanel,
            )
        )
        self.viewerRoot.addEventListener("click", self.panel_clicked)
        tag(self, tw("flex min-h-0 min-w-0 flex-1"), self.viewerRoot)

    def panel_clicked(self, event: Event):
        target = cast(Element, event.target)
        selected = target.closest("[data-panel-button]")
        if selected is None:
            return
        panel = selected.getAttribute("data-panel-button")
        if panel is not None:
            self.selectPanel(panel)

    def selectPanel(self, panel: str):
        self.selectedPanel = panel
        buttons: list[HTMLElement] = self.viewerRoot.querySelectorAll("[data-panel-button]")
        for candidate in buttons:
            selected = candidate.getAttribute("data-panel-button") == panel
            candidate.setAttribute("aria-selected", "true" if selected else "false")
            candidate.setAttribute("data-selected", "true" if selected else "false")
        panels: list[HTMLElement] = self.viewerRoot.querySelectorAll("[data-panel]")
        for candidate in panels:
            selected = candidate.getAttribute("data-panel") == panel
            candidate.classList.toggle("hidden", not selected)
            candidate.classList.toggle("flex", selected)

    def showEmptyConsole(self):
        self.currentConsoleOutput.replaceChildren()
        self.currentConsoleOutput.textContent = "No console output recorded"
        self.outputCount.textContent = "0"
        self.errorCount.textContent = "0"
        self.errorCount.classList.add("hidden")
        self.errorOutput.textContent = "No errors recorded"
        self.testName.textContent = "No test selected"
        self.testPath.textContent = "Select a test to inspect"
        self.testStatus.textContent = "Idle"
        self.testStatus.setAttribute("data-status", "idle")

    def showConsole(self, nodeid: str, state: TestState):
        self.testName.textContent = short_test_name(nodeid)
        self.testPath.textContent = test_file_name(nodeid)
        status_label = state.status
        if state.status == "pending":
            status_label = "Pending"
        elif state.status == "running":
            status_label = "Running"
        elif state.status == "passed":
            status_label = "Passed"
        elif state.status == "failed":
            status_label = "Failed"
        self.testStatus.textContent = status_label
        self.testStatus.setAttribute("data-status", state.status)
        self.currentConsoleOutput.replaceChildren()
        lines = state.consoleLines
        self.outputCount.textContent = str(len(lines))
        if len(lines) == 0:
            self.currentConsoleOutput.textContent = "No console output recorded"
        else:
            for entry in lines:
                level = entry.level or "log"
                line = div(
                    tw(
                        "console-line grid grid-cols-[4.5rem_minmax(0,1fr)] border-b "
                        "border-slate-200 px-3 py-2 last:border-b-0 dark:border-slate-800"
                    ),
                    {"data-level": level},
                    span(tw("uppercase text-slate-400"), level),
                    span(
                        tw("whitespace-pre-wrap break-words text-slate-700 dark:text-slate-300"),
                        entry.text,
                    ),
                )
                line.classList.add(level)
                self.currentConsoleOutput.append(line)
        has_error = state.error != ""
        self.errorCount.textContent = "1" if has_error else "0"
        self.errorCount.classList.toggle("hidden", not has_error)
        self.errorOutput.textContent = state.error if has_error else "No errors recorded"
        if has_error:
            self.errorOutput.classList.add("text-rose-700", "dark:text-rose-300")
            if not state.hasPreview:
                self.selectPanel("errors")
        else:
            self.errorOutput.classList.remove("text-rose-700", "dark:text-rose-300")

    def setHostEmptyState(self, empty: bool, label: str):
        self.frameHost.setAttribute("data-empty", "true" if empty else "false")
        self.frameHost.setAttribute("data-empty-label", label)

    def setCurrentFrameLabel(self, nodeid: str | None, has_ui: bool):
        if not has_ui or nodeid is None:
            self.currentFrameLabel.textContent = "No preview available"
            return
        self.currentFrameLabel.textContent = str(nodeid)

    def setFrameHostMode(self, frame: HTMLIFrameElement, nodeid: str, state: TestState):
        has_ui = frame_has_meaningful_content(frame) or state.status == "running"
        self.frameHost.classList.toggle("no-ui", not has_ui)
        self.setHostEmptyState(not has_ui, "This test did not render a UI")
        self.setCurrentFrameLabel(nodeid, has_ui)
        if has_ui:
            self.selectPanel("preview")

    def setActiveFrame(self, frame: HTMLIFrameElement, nodeid: str, state: TestState):
        if self.currentFrame is not None:
            if self.currentFrame is not frame:
                self.currentFrame.classList.remove("active")
        frame.classList.add("active")
        self.currentFrame = frame
        self.currentFrameNodeid = nodeid
        self.setFrameHostMode(frame, nodeid, state)

    def appendFrame(self, frame: HTMLIFrameElement, nodeid: str, state: TestState):
        self.frameHost.append(frame)
        self.setActiveFrame(frame, nodeid, state)

    def clearActiveFrame(self):
        if self.currentFrame is not None:
            self.currentFrame.classList.remove("active")
        self.currentFrame = None
        self.currentFrameNodeid = None
        self.setHostEmptyState(True, "No preview available")
        self.frameHost.classList.add("no-ui")
        self.setCurrentFrameLabel(None, False)

    def resetFrameHost(self):
        self.frameHost.replaceChildren()
        self.clearActiveFrame()

    def getCurrentFrame(self) -> HTMLIFrameElement | None:
        return self.currentFrame

    def getCurrentFrameNodeid(self) -> str | None:
        return self.currentFrameNodeid
