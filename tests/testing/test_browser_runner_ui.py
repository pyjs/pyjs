import pytest

from pyjs import js
from pyjs.testing.client.app import BrowserRunnerApp
from pyjs.testing.client.state import ConsoleLine
from pyjs.testing.web import bubbling_click, mount, selector_count
from pyjs.web.domx import require_element
from pyjs.web.events import Event

pytestmark = pytest.mark.pyjs_web


@js
def populated_runner() -> BrowserRunnerApp:
    app = BrowserRunnerApp()
    mount(app)
    nodeids = [
        "tests/web/ui/test_dialog.py::test_dialog_opens",
        "tests/web/ui/test_dialog.py::test_dialog_closes",
        "tests/testing/test_runtime.py::TestConsole::test_captures_output",
        "tests/testing/test_runtime.py::test_reports_long_failure",
    ]
    app.prepareRunSession(nodeids, nodeids[0])
    app.markTestPassed(nodeids[0])
    app.markTestPassed(nodeids[1])
    app.markTestRunning(nodeids[2])
    app.setTestConsoleLines(
        nodeids[2],
        [
            ConsoleLine("info", "Opening browser"),
            ConsoleLine("warn", "Waiting for a delayed element"),
        ],
    )
    app.markTestFailed(nodeids[3], "AssertionError: expected 'ready', received 'loading'")
    app.setTestConsoleLines(nodeids[3], [ConsoleLine("error", "Element remained loading")])
    app.renderTestListSelf()
    app.setStatus(app.summarizeResults())
    return app


@js
def test_runner_groups_searches_and_filters_mixed_results():
    app = populated_runner()

    assert selector_count(app, "[data-test-file]") == 2
    assert selector_count(app, "[data-test-nodeid]:not([hidden])") == 4
    assert app.sidebar.visibleCount.textContent == "4 tests"
    assert app.sidebar.failedCount.textContent == "1"
    assert app.sidebar.passedCount.textContent == "2"
    assert app.sidebar.runningCount.textContent == "1"
    assert app.progressBar.style.width == "75%"
    assert app.sidebar.visibleSummary.classList.contains("hidden")

    app.sidebar.search.set_value("dialog")
    app.sidebar.search.element.dispatchEvent(Event("input"))
    assert selector_count(app, "[data-test-nodeid]:not([hidden])") == 2
    assert selector_count(app, "[data-test-file]:not([hidden])") == 1
    assert not app.sidebar.visibleSummary.classList.contains("hidden")
    assert app.sidebar.visibleSummary.textContent == "2 tests visible"

    app.sidebar.search.set_value("")
    app.sidebar.search.element.dispatchEvent(Event("input"))
    bubbling_click(require_element(app, "[data-filter=failed]"))
    assert selector_count(app, "[data-test-nodeid]:not([hidden])") == 1
    assert app.sidebar.visibleCount.textContent == "1 tests"
    assert app.sidebar.visibleSummary.classList.contains("hidden")


@js
def test_runner_selects_failure_details_and_switches_output_panels():
    app = populated_runner()
    failed_nodeid = "tests/testing/test_runtime.py::test_reports_long_failure"

    app.selectTest(failed_nodeid)

    assert app.viewer.testName.textContent == "test_reports_long_failure"
    assert app.viewer.testStatus.textContent == "Failed"
    assert "AssertionError" in app.viewer.errorOutput.textContent
    assert app.viewer.selectedPanel == "errors"
    assert require_element(app, "[data-panel=errors]").classList.contains("flex")

    bubbling_click(require_element(app, "[data-panel-button=output]"))
    assert app.viewer.selectedPanel == "output"
    assert selector_count(app.viewer.currentConsoleOutput, "[data-level=error]") == 1
    assert app.viewer.outputCount.textContent == "1"


@js
def test_runner_empty_and_no_match_states_are_explicit():
    app = BrowserRunnerApp()
    mount(app)
    app.renderTestListSelf()

    assert selector_count(app, "[data-test-nodeid]") == 0
    assert app.sidebar.empty.classList.contains("grid")
    assert app.sidebar.emptyTitle.textContent == "Waiting for a test run"
    assert app.sidebar.visibleCount.textContent == "0 tests"
    assert app.viewer.testName.textContent == "No test selected"

    app = populated_runner()
    app.sidebar.search.set_value("does-not-exist")
    app.sidebar.search.element.dispatchEvent(Event("input"))
    assert app.sidebar.empty.classList.contains("grid")
    assert app.sidebar.emptyTitle.textContent == "No matching tests"
    assert app.sidebar.test_list.classList.contains("hidden")


@js
def test_runner_long_test_names_do_not_expand_the_sidebar():
    app = BrowserRunnerApp()
    mount(app)
    long_name = (
        "tests/web/ui/test_a_very_long_module_name_for_layout_regressions.py::"
        "TestADeeplyNestedScope::test_a_long_parameterized_case[value-with-a-long-description]"
    )
    app.prepareRunSession([long_name], long_name)
    app.markTestFailed(long_name, "failure")
    app.renderTestListSelf()

    sidebar_bounds = app.sidebar.getBoundingClientRect()
    row = require_element(app, "[data-test-nodeid]")
    row_bounds = row.getBoundingClientRect()
    assert row_bounds.right <= sidebar_bounds.right
    assert row_bounds.width <= sidebar_bounds.width


@js
def test_runner_only_retains_iframes_that_render_meaningful_content():
    app = BrowserRunnerApp()
    mount(app)
    logic_nodeid = "tests/test_logic.py::test_calculates_value"
    visual_nodeid = "tests/test_visual.py::test_renders_card"
    app.prepareRunSession([logic_nodeid, visual_nodeid], logic_nodeid)
    logic_state = app._testStates[0]
    visual_state = app._testStates[1]

    logic_frame = app.createFrameForTest(logic_nodeid)
    app.setTestConsoleLines(logic_nodeid, [ConsoleLine("info", "calculation completed")])
    app.markTestPassed(logic_nodeid)
    retained_logic = app.retainRenderedFrame(logic_nodeid, logic_frame, "passed", 10)

    assert not retained_logic
    assert not logic_state.hasPreview
    assert logic_frame.parentElement is None
    assert len(logic_state.consoleLines) == 1

    visual_frame = app.createFrameForTest(visual_nodeid)
    visual_document = visual_frame.contentDocument
    if visual_document is None:
        raise Exception("visual test iframe did not expose a document")
    visual_document.body.textContent = "Rendered card"
    app.markTestPassed(visual_nodeid)
    retained_visual = app.retainRenderedFrame(visual_nodeid, visual_frame, "passed", 10)
    app.renderTestListSelf()

    assert retained_visual
    assert visual_state.hasPreview
    assert visual_frame.parentElement is app.viewer.frameHost
    assert selector_count(app, "[aria-label='Rendered preview retained']") == 1

    app.selectTest(logic_nodeid)
    assert app.viewer.selectedPanel == "output"
    app.selectTest(visual_nodeid)
    assert app.viewer.selectedPanel == "preview"


@js
def test_runner_metadata_columns_stay_aligned_for_two_digit_output_counts():
    app = BrowserRunnerApp()
    mount(app)
    nodeids = [
        "tests/test_output.py::test_nine_lines",
        "tests/test_output.py::test_ten_lines",
    ]
    app.prepareRunSession(nodeids, nodeids[0])
    nine_lines: list[ConsoleLine] = []
    ten_lines: list[ConsoleLine] = []
    for index in range(9):
        nine_lines.append(ConsoleLine("info", str(index)))
    for index in range(10):
        ten_lines.append(ConsoleLine("info", str(index)))
    app.setTestConsoleLines(nodeids[0], nine_lines)
    app.setTestConsoleLines(nodeids[1], ten_lines)
    app._testStates[0].hasPreview = True
    app._testStates[1].hasPreview = True
    app.renderTestListSelf()

    indicators = app.querySelectorAll("[data-preview-indicator=true]")
    output_indicators = app.querySelectorAll("[data-output-indicator=true]")
    first_icon = indicators[0].getBoundingClientRect()
    second_icon = indicators[1].getBoundingClientRect()
    first_output = output_indicators[0].getBoundingClientRect()
    second_output = output_indicators[1].getBoundingClientRect()

    assert round(first_icon.left) == round(second_icon.left)
    assert round(first_output.left) == round(second_output.left)
