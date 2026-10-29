from typing import cast

from pyjs import js
from pyjs.javascript import JSON, _stringify_unchecked, encodeURIComponent
from pyjs.testing.client.runtime import (
    BrowserTest,
    TestingWindow,
    call_selected_tests,
    exception_details,
    exception_text,
    runtime_exception_text,
)
from pyjs.testing.client.sidebar import RunnerSidebar
from pyjs.testing.client.state import (
    BrowserHeartbeatMessage,
    ConsoleLine,
    FetchOptions,
    PreservedEntry,
    RegisterBrowserMessage,
    RunBundleMessage,
    RuntimeException,
    SingleTestRun,
    TestResult,
    TestResultsMessage,
    TestState,
)
from pyjs.testing.client.viewer import RunnerViewer, frame_has_meaningful_content
from pyjs.web.console import Console
from pyjs.web.dom import document, location
from pyjs.web.domx import CustomElement, div, iframe, ref, span, tag, tw
from pyjs.web.events import ErrorEvent, Event, MessageEvent, PromiseRejectionEvent
from pyjs.web.html import HTMLIFrameElement
from pyjs.web.network import WebSocket, fetch
from pyjs.web.timers import clearInterval, setInterval


@js
def format_console_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Exception):
        return exception_text(value)
    try:
        return str(_stringify_unchecked(value))
    except Exception:
        return str(value)


@js
class CapturingConsole:
    def __init__(self, original: Console, logs: list[ConsoleLine]):
        self.original = original
        self.logs = logs

    def capture(self, level: str, args: tuple[object, ...]):
        values: list[str] = []
        for value in args:
            values.append(format_console_value(value))
        self.logs.append(ConsoleLine(level, " ".join(values)))

    @js.keep
    def log(self, *args: object):
        self.capture("log", args)
        self.original.log(*args)

    @js.keep
    def info(self, *args: object):
        self.capture("info", args)
        self.original.info(*args)

    @js.keep
    def warn(self, *args: object):
        self.capture("warn", args)
        self.original.warn(*args)

    @js.keep
    def error(self, *args: object):
        self.capture("error", args)
        self.original.error(*args)

    @js.keep
    def debug(self, *args: object):
        self.capture("debug", args)
        self.original.debug(*args)

    @js.keep
    def trace(self, *args: object):
        self.capture("trace", args)
        self.original.trace(*args)


@js
class WindowErrorListener:
    def __init__(self, logs: list[ConsoleLine]):
        self.logs = logs

    def handleEvent(self, event: ErrorEvent):
        detail = event.message
        error = event.error
        if isinstance(error, Exception):
            detail = exception_text(error)
        elif error is not None:
            detail = format_console_value(error)
        elif not detail:
            detail = str(event)
        self.logs.append(ConsoleLine("error", detail))


@js
class RejectionErrorListener:
    def __init__(self, logs: list[ConsoleLine]):
        self.logs = logs

    def handleEvent(self, event: PromiseRejectionEvent):
        reason = event.reason
        if isinstance(reason, Exception):
            detail = exception_text(reason)
        else:
            detail = format_console_value(reason)
        self.logs.append(ConsoleLine("error", "Unhandled rejection: " + detail))


@js
def failed_test_run(nodeid: str, error: str, logs: list[ConsoleLine]) -> SingleTestRun:
    exception = RuntimeException("Error", error, "")
    return SingleTestRun(TestResult(nodeid, "failed", [], exception), logs)


@js
class BrowserRunnerApp(CustomElement):
    def __init__(self):
        super().__init__()
        self.runCounter = 0
        self.currentSuiteKey = ""
        self._selectedTestNodeid: str | None = None
        self._testStates: list[TestState] = []
        self._preservedEntries: list[PreservedEntry] = []
        self._ws: WebSocket | None = None
        self._heartbeatTimer: int | None = None
        self.connectionDot = ref(
            span(
                tw("size-2 rounded-full bg-amber-400"),
                {"aria-hidden": "true", "data-testid": "connection-dot"},
            )
        )
        self.connectionLabel = ref(span("Connecting"))
        self.status = ref(
            span(
                tw("sr-only"),
                {"aria-live": "polite", "id": "status"},
                "Browser runner connecting",
            )
        )
        connection = div(
            tw(
                "flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 "
                "py-1.5 text-xs font-medium text-slate-600 shadow-sm dark:border-slate-700 "
                "dark:bg-slate-900 dark:text-slate-300"
            ),
            self.connectionDot,
            self.connectionLabel,
        )
        self.passedSummary = ref(span("0"))
        self.failedSummary = ref(span("0"))
        self.runningSummary = ref(span("0"))
        self.totalSummary = ref(span("0"))
        metrics = div(
            tw("hidden items-center gap-4 text-xs sm:flex"),
            div(
                tw("flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400"),
                span("✓"),
                self.passedSummary,
                span(tw("text-slate-500"), "passed"),
            ),
            div(
                tw("flex items-center gap-1.5 text-rose-600 dark:text-rose-400"),
                span("×"),
                self.failedSummary,
                span(tw("text-slate-500"), "failed"),
            ),
            div(
                tw("flex items-center gap-1.5 text-sky-600 dark:text-sky-400"),
                span("↻"),
                self.runningSummary,
                span(tw("text-slate-500"), "running"),
            ),
            div(
                tw("flex items-center gap-1.5 text-slate-600 dark:text-slate-300"),
                self.totalSummary,
                span(tw("text-slate-500"), "total"),
            ),
        )
        brand = div(
            tw("flex items-center gap-3"),
            span(
                tw(
                    "grid size-8 place-items-center rounded-lg bg-gradient-to-br from-sky-400 "
                    "to-violet-600 font-mono text-sm font-black text-white shadow-lg "
                    "shadow-sky-500/15"
                ),
                "py",
            ),
            div(
                tag(
                    "h1",
                    tw("text-sm font-semibold tracking-tight text-slate-950 dark:text-white"),
                    "Browser tests",
                ),
                div(tw("text-[11px] text-slate-500"), "PyJS interactive runner"),
            ),
        )
        header = tag(
            "header",
            tw(
                "flex h-16 shrink-0 items-center justify-between gap-4 border-b "
                "border-slate-200 bg-white/90 px-4 backdrop-blur dark:border-slate-800 "
                "dark:bg-slate-950/90"
            ),
            brand,
            div(tw("flex items-center gap-5"), metrics, connection, self.status),
        )
        self.progressBar = ref(
            div(
                tw(
                    "h-0.5 w-0 bg-gradient-to-r from-sky-400 to-violet-500 "
                    "transition-[width] duration-300"
                ),
                {"data-testid": "run-progress"},
            )
        )
        header_area = div(
            tw("shrink-0 bg-slate-200 dark:bg-slate-800"),
            header,
            self.progressBar,
        )
        self.sidebar = ref(RunnerSidebar())
        self.viewer = ref(RunnerViewer())
        layout = div(
            tw(
                "layout grid min-h-0 flex-1 grid-cols-[minmax(17rem,22rem)_minmax(0,1fr)] "
                "max-lg:grid-cols-[minmax(15rem,19rem)_minmax(0,1fr)] max-sm:block "
                "max-sm:overflow-auto"
            ),
            self.sidebar,
            self.viewer,
        )
        tag(
            self,
            tw(
                "flex h-dvh min-h-[36rem] flex-col overflow-hidden bg-slate-50 text-slate-950 "
                "antialiased dark:bg-slate-950 dark:text-slate-100"
            ),
            header_area,
            layout,
        )

    def setStatus(self, message: str):
        self.status.textContent = message
        lowered = message.lower()
        if "disconnected" in lowered:
            self.connectionLabel.textContent = "Disconnected"
            tag(self.connectionDot, tw("size-2 rounded-full bg-rose-500"))
        elif "connected" in lowered or "run #" in lowered:
            self.connectionLabel.textContent = "Connected"
            tag(self.connectionDot, tw("size-2 rounded-full bg-emerald-500"))
        else:
            self.connectionLabel.textContent = "Working"
            tag(
                self.connectionDot,
                tw("size-2 animate-pulse rounded-full bg-amber-400"),
            )
        self.updateRunSummary()

    def updateRunSummary(self):
        passed = 0
        failed = 0
        running = 0
        for state in self._testStates:
            if state.status == "passed":
                passed += 1
            elif state.status == "failed":
                failed += 1
            elif state.status == "running":
                running += 1
        self.passedSummary.textContent = str(passed)
        self.failedSummary.textContent = str(failed)
        self.runningSummary.textContent = str(running)
        self.totalSummary.textContent = str(len(self._testStates))
        completed = passed + failed
        percentage = 0
        if len(self._testStates) > 0:
            percentage = round(completed / len(self._testStates) * 100)
        self.progressBar.style.width = str(percentage) + "%"

    def getState(self, nodeid: str) -> TestState | None:
        for state in self._testStates:
            if state.nodeid == nodeid:
                return state

    def renderTestList(self, on_select: callable):
        self.updateRunSummary()
        self.sidebar.renderTests(
            self._testStates,
            self._selectedTestNodeid,
            on_select,
        )

    def renderTestListSelf(self):
        self.renderTestList(self.selectTest)

    def showConsoleForNodeid(self, nodeid: str | None):
        self._selectedTestNodeid = nodeid
        if nodeid is None:
            self.viewer.showEmptyConsole()
            return
        state = self.getState(nodeid)
        if state is None:
            self.viewer.showEmptyConsole()
            return
        self.viewer.showConsole(nodeid, state)

    def prepareRunSession(self, selected_nodeids: list[str], current_nodeid: str | None) -> bool:
        suite_key = _stringify_unchecked(selected_nodeids)
        first_selected_nodeid = ""
        if len(selected_nodeids) > 0:
            first_selected_nodeid = selected_nodeids[0]
        should_reset = self.currentSuiteKey != suite_key
        if current_nodeid == first_selected_nodeid:
            should_reset = True

        if should_reset:
            self.runCounter = self.runCounter + 1
            self.currentSuiteKey = suite_key
            states: list[TestState] = []
            for nodeid in selected_nodeids:
                states.append(TestState(nodeid))
            self._testStates = states
            self.resetFrameHost()
        self._selectedTestNodeid = current_nodeid
        self.showConsoleForNodeid(current_nodeid)

        if current_nodeid is not None:
            current_state = self.getState(current_nodeid)
            if current_state is not None:
                if current_state.status == "pending":
                    current_state.status = "running"
        self.renderTestListSelf()
        return should_reset

    def markTestRunning(self, nodeid: str):
        state = self.getState(nodeid)
        if state is not None:
            state.status = "running"
            state.error = ""

    def setTestConsoleLines(self, nodeid: str, console_lines: list[ConsoleLine]):
        state = self.getState(nodeid)
        if state is not None:
            state.consoleLines = console_lines

    def markTestPassed(self, nodeid: str):
        state = self.getState(nodeid)
        if state is not None:
            state.status = "passed"
            state.error = ""

    def markTestFailed(self, nodeid: str, error: str):
        state = self.getState(nodeid)
        if state is not None:
            state.status = "failed"
            state.error = error

    def setTestHasPreview(self, nodeid: str, has_preview: bool):
        state = self.getState(nodeid)
        if state is not None:
            state.hasPreview = has_preview

    def selectTest(self, nodeid: str):
        state = self.getState(nodeid)
        if state is not None:
            self.showConsoleForNodeid(nodeid)
            if state.hasPreview:
                self.showFrameForNodeid(nodeid)
            else:
                self.clearActiveFrame()
                self.renderTestListSelf()
            if state.status == "failed":
                self.viewer.selectPanel("errors")
            elif not state.hasPreview:
                self.viewer.selectPanel("output")
        else:
            return

    def setActiveFrame(self, frame: HTMLIFrameElement, nodeid: str, state: TestState):
        self.viewer.setActiveFrame(frame, nodeid, state)

    def appendFrame(self, frame: HTMLIFrameElement, nodeid: str, state: TestState):
        self.viewer.appendFrame(frame, nodeid, state)

    def clearActiveFrame(self):
        self.viewer.clearActiveFrame()

    def resetFrameHost(self):
        self.viewer.resetFrameHost()

    def getCurrentFrame(self) -> HTMLIFrameElement | None:
        return self.viewer.getCurrentFrame()

    def getCurrentFrameNodeid(self) -> str | None:
        return self.viewer.getCurrentFrameNodeid()

    def summarizeResults(self) -> str:
        passed = 0
        failed = 0
        running = 0
        kept = 0
        states = self._testStates
        for state in states:
            status = state.status
            if status == "passed":
                passed += 1
            elif status == "failed":
                failed += 1
            elif status == "running":
                running += 1

            if state.hasPreview:
                kept += 1
        return (
            "Run #"
            + str(self.runCounter)
            + "\n"
            + str(len(states))
            + " test(s) tracked\n"
            + str(passed)
            + " passed\n"
            + str(failed)
            + " failed\n"
            + str(running)
            + " running\n"
            + str(kept)
            + " rendered preview(s) retained"
        )

    def selectBestResult(self):
        for state in self._testStates:
            if state.status == "failed":
                self.selectTest(state.nodeid)
                return
        if len(self._testStates) > 0:
            self.selectTest(self._testStates[len(self._testStates) - 1].nodeid)

    def resetPreservedFrames(self):
        for entry in self._preservedEntries:
            entry.frame.remove()
        self._preservedEntries = []

    def getPreservedFrame(self, nodeid: str) -> HTMLIFrameElement | None:
        for entry in self._preservedEntries:
            if entry.nodeid == nodeid:
                return entry.frame

    def getFrameForNodeid(self, nodeid: str) -> HTMLIFrameElement | None:
        current_frame_nodeid = self.getCurrentFrameNodeid()
        if current_frame_nodeid == nodeid:
            return self.getCurrentFrame()
        return self.getPreservedFrame(nodeid)

    def showFrameForNodeid(self, nodeid: str):
        frame = self.getFrameForNodeid(nodeid)
        if frame is not None:
            state = self.getState(nodeid)
            if state is not None:
                self.setActiveFrame(frame, nodeid, state)
                self.renderTestListSelf()

    def removePreservedFrame(self, nodeid: str):
        removed_frame: HTMLIFrameElement | None = None
        remaining_entries: list[PreservedEntry] = []
        for entry in self._preservedEntries:
            if entry.nodeid == nodeid:
                removed_frame = entry.frame
            else:
                remaining_entries.append(entry)
        if removed_frame is not None:
            if self.getCurrentFrameNodeid() == nodeid:
                self.clearActiveFrame()
            removed_frame.remove()
            self._preservedEntries = remaining_entries
            self.setTestHasPreview(nodeid, False)
        else:
            return

    def evictPreservedFramesIfNeeded(self, max_preserved_iframes: int):
        entries = self._preservedEntries
        while len(entries) > max_preserved_iframes:
            nodeid_to_remove = entries[0].nodeid
            for entry in entries:
                if entry.outcome == "passed":
                    nodeid_to_remove = entry.nodeid
                    break
            self.removePreservedFrame(nodeid_to_remove)
            entries = self._preservedEntries

    def preserveFrame(
        self, nodeid: str, frame: HTMLIFrameElement, outcome: str, max_preserved_iframes: int
    ):
        existing_frame = self.getPreservedFrame(nodeid)
        if existing_frame is not None:
            self.removePreservedFrame(nodeid)
        entries = self._preservedEntries
        entries.append(PreservedEntry(nodeid, frame, outcome))
        self.setTestHasPreview(nodeid, True)
        self.evictPreservedFramesIfNeeded(max_preserved_iframes)

    def discardFrame(self, nodeid: str, frame: HTMLIFrameElement):
        if self.getCurrentFrame() is frame:
            self.clearActiveFrame()
        frame.remove()
        self.setTestHasPreview(nodeid, False)

    def retainRenderedFrame(
        self,
        nodeid: str,
        frame: HTMLIFrameElement,
        outcome: str,
        max_preserved_iframes: int,
    ) -> bool:
        if frame_has_meaningful_content(frame):
            self.preserveFrame(nodeid, frame, outcome, max_preserved_iframes)
            return True
        self.discardFrame(nodeid, frame)
        return False

    def createFrameForTest(self, nodeid: str) -> HTMLIFrameElement:
        frame = iframe(tw("runner-frame"), {"title": "pyjs-runner-frame:" + nodeid})
        state = self.getState(nodeid)
        if state is not None:
            self.appendFrame(frame, nodeid, state)
        self.renderTestListSelf()
        return frame

    async def runSingleTest(
        self,
        frame: HTMLIFrameElement,
        module_url: str,
        css: str,
        nodeid: str,
    ) -> SingleTestRun:
        return await execute_single_test(frame, module_url, css, nodeid)

    def resetRunnerState(self, selected_nodeids: list[str], current_nodeid: str | None):
        should_reset = self.prepareRunSession(selected_nodeids, current_nodeid)
        if should_reset:
            self.resetPreservedFrames()

    def startTransport(self):
        start_runner_transport(self)


@js
async def load_test_module(frame: HTMLIFrameElement, module_url: str) -> None: ...


load_test_module.source("""
return new Promise((resolve, reject) => {
    const target = frame.contentWindow;
    const script = frame.contentDocument.createElement('script');
    script.type = 'module';
    script.src = module_url;
    const cleanup = () => {
        target.removeEventListener('error', failed);
        script.remove();
    };
    const failed = event => {
        cleanup();
        reject(event.error ?? new Error(event.message || 'Test module failed to load'));
    };
    script.addEventListener('error', failed, {once: true});
    script.addEventListener('load', () => {cleanup(); resolve();}, {once: true});
    target.addEventListener('error', failed);
    frame.contentDocument.head.append(script);
});
""")


@js
async def execute_single_test(
    frame: HTMLIFrameElement, module_url: str, css: str, nodeid: str
) -> SingleTestRun:
    logs: list[ConsoleLine] = []
    # Test bundles extend their iframe window with the runner protocol fields.
    frame_window = cast(TestingWindow | None, frame.contentWindow)
    if frame_window is None:
        return failed_test_run(
            nodeid,
            "Browser runner iframe did not expose a contentWindow for " + nodeid,
            logs,
        )
    frame_document = frame.contentDocument
    if frame_document is None:
        return failed_test_run(
            nodeid,
            "Browser runner iframe did not expose a contentDocument for " + nodeid,
            logs,
        )

    style = frame_document.createElement("style")
    style.textContent = css
    frame_document.head.append(style)

    original_console = frame_window.console
    capturing_console = CapturingConsole(original_console, logs)
    error_listener = WindowErrorListener(logs)
    rejection_listener = RejectionErrorListener(logs)
    frame_window.console = cast(Console, capturing_console)
    frame_window.addEventListener("error", error_listener)
    frame_window.addEventListener("unhandledrejection", rejection_listener)
    frame_window.__pyjsAutoRun__ = False

    try:
        await load_test_module(frame, module_url)
        manifest: list[BrowserTest] = frame_window.__pyjsSelectedTests
        selected_test: BrowserTest | None = None
        for test in manifest:
            if test.nodeid == nodeid:
                selected_test = test
                break
        if selected_test is None:
            return failed_test_run(
                nodeid,
                "Generated bundle did not expose metadata for " + nodeid,
                logs,
            )

        selected_tests = [selected_test]
        results = await call_selected_tests(frame_window.__pyjsRunSelectedTests__, selected_tests)
        if not isinstance(results, list) or len(results) != 1:
            return failed_test_run(
                nodeid,
                "Generated bundle returned an unexpected result payload for " + nodeid,
                logs,
            )
        return SingleTestRun(results[0], logs)
    except Exception as error:
        return failed_test_run(nodeid, exception_text(error), logs)
    finally:
        frame_window.console = original_console
        frame_window.removeEventListener("error", error_listener)
        frame_window.removeEventListener("unhandledrejection", rejection_listener)


@js
class TransportOpenListener:
    def __init__(self, app: BrowserRunnerApp, socket: WebSocket):
        self.app = app
        self.socket = socket

    def handleEvent(self, event: Event):
        self.socket.send(_stringify_unchecked(RegisterBrowserMessage()))
        self.app._heartbeatTimer = setInterval(self.sendHeartbeat, 5_000)
        self.app.setStatus("Browser runner connected")

    def sendHeartbeat(self):
        if self.socket.readyState == WebSocket.OPEN:
            self.socket.send(_stringify_unchecked(BrowserHeartbeatMessage()))


@js
class TransportMessageListener:
    def __init__(self, app: BrowserRunnerApp, socket: WebSocket):
        self.app = app
        self.socket = socket

    async def handleEvent(self, event: MessageEvent):
        message: RunBundleMessage = JSON.parse(cast(str, event.data))
        if message["type"] != "run_bundle":
            return

        selected_nodeids = message["selected_nodeids"]
        if selected_nodeids is None:
            selected_nodeids = message["nodeids"]
        current_nodeid = message["current_nodeid"]
        if current_nodeid is None and len(message["nodeids"]) > 0:
            current_nodeid = message["nodeids"][0]

        app = self.app
        app.resetRunnerState(selected_nodeids, current_nodeid)
        app.setStatus(app.summarizeResults())
        module_url = "/bundle.js?run_id=" + encodeURIComponent(message["run_id"])
        css_response = await fetch(
            "/bundle.css?run_id=" + encodeURIComponent(message["run_id"]),
            FetchOptions("no-store"),
        )
        css = await css_response.text()
        results: list[TestResult] = []
        try:
            for nodeid in message["nodeids"]:
                app.markTestRunning(nodeid)
                app.renderTestListSelf()

                frame = app.createFrameForTest(nodeid)
                run = await app.runSingleTest(frame, module_url, css, nodeid)
                result = run.result
                results.append(result)
                app.setTestConsoleLines(nodeid, run.consoleLines)
                if result.outcome == "passed":
                    app.markTestPassed(nodeid)
                else:
                    exception = result.exception
                    app.markTestFailed(
                        nodeid,
                        runtime_exception_text(exception)
                        if exception is not None
                        else "Test failed",
                    )
                app.retainRenderedFrame(
                    nodeid,
                    frame,
                    result.outcome,
                    message["max_preserved_iframes"],
                )
                app.selectTest(nodeid)
            app.selectBestResult()
            app.setStatus(app.summarizeResults())
            self.socket.send(
                _stringify_unchecked(TestResultsMessage(message["run_id"], results))
            )
        except Exception as error:
            exception = exception_details(error)
            error_text = runtime_exception_text(exception)
            failed_result = TestResult("<bundle>", "failed", [], exception)
            self.socket.send(
                _stringify_unchecked(
                    TestResultsMessage(message["run_id"], [failed_result])
                )
            )
            app.setStatus(error_text)


@js
class TransportCloseListener:
    def __init__(self, app: BrowserRunnerApp):
        self.app = app

    def handleEvent(self, event: Event):
        clearInterval(self.app._heartbeatTimer)
        self.app._heartbeatTimer = None
        self.app.setStatus("Browser runner disconnected")


@js
def start_runner_transport(app: BrowserRunnerApp) -> None:
    socket = WebSocket("ws://" + location.host + "/ws")
    app._ws = socket
    socket.addEventListener("open", TransportOpenListener(app, socket))
    socket.addEventListener(
        "message",
        TransportMessageListener(app, socket),
    )
    socket.addEventListener("close", TransportCloseListener(app))


def main():
    app_root = document.createElement("div")
    app_root.setAttribute("id", "app-root")
    document.body.append(app_root)
    app = BrowserRunnerApp()
    app_root.append(app)
    app.startTransport()
