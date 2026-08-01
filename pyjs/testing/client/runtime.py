from pyjs import js, js_object
from pyjs.testing.client.state import RenderArtifact, TestResult
from pyjs.web.dom import Window


@js(builtin=True)
class TestingWindow(Window):
    def __init__(self):
        super().__init__()
        self.__pyjsAutoRun__ = True
        self.__pyjsCurrentTest__: object | None = None
        self.__pyjsReportResults__: callable | None = None
        self.__pyjsRunId = ""
        self.__pyjsRunSelectedTests__: callable = object()
        self.__pyjsSelectedTests: list[object] = []
        self.__pyjsTestResults__: object | None = None
        self.__pyjsRenderArtifacts__: list[RenderArtifact] = []


window = TestingWindow()
js_object(window, builtin=True)


@js
class BrowserTest:
    def __init__(
        self,
        nodeid: str,
        module: str,
        function_name: str,
        call: callable,
    ):
        self.nodeid = nodeid
        self.module = module
        self.function = function_name
        self.call = call


@js
class TestRunReport:
    def __init__(self, run_id: str, results: list[TestResult]):
        self.runId = run_id
        self.results = results


@js
def exception_text(error: Exception) -> str:
    stack = error.stack
    if stack is not None:
        return stack
    message = error.message
    if message:
        return message
    return str(error)


@js(builtin=True, inline="{call}()")
async def call_browser_test(call: callable) -> None:
    import inspect

    result = call()
    if inspect.isawaitable(result):
        await result


@js(builtin=True, inline="{call}({selected_tests})")
async def call_selected_tests(
    call: callable, selected_tests: list[BrowserTest]
) -> list[TestResult]:
    return await call(selected_tests)


@js(builtin=True, inline="{call}({run_id}, {selected_tests})")
def launch_automatic_results(
    call: callable, run_id: str, selected_tests: list[BrowserTest]
) -> None:
    import asyncio

    asyncio.run(call(run_id, selected_tests))


@js
async def run_selected_tests(selected_tests: list[BrowserTest]) -> list[TestResult]:
    results: list[TestResult] = []
    for test in selected_tests:
        try:
            window.__pyjsCurrentTest__: object | None = test
            window.__pyjsRenderArtifacts__: list[RenderArtifact] = []
            await call_browser_test(test.call)
            results.append(TestResult(test.nodeid, "passed", window.__pyjsRenderArtifacts__))
        except Exception as error:
            results.append(
                TestResult(
                    test.nodeid,
                    "failed",
                    window.__pyjsRenderArtifacts__,
                    error=exception_text(error),
                )
            )
        finally:
            window.__pyjsCurrentTest__: object | None = None
    return results


@js
async def report_automatic_results(run_id: str, selected_tests: list[BrowserTest]):
    results = await run_selected_tests(selected_tests)
    report = TestRunReport(run_id, results)
    reporter = window.__pyjsReportResults__
    if reporter is not None:
        reporter(report)
    else:
        window.__pyjsTestResults__: object | None = report


@js
def initialize_test_runtime(run_id: str, selected_tests: list[BrowserTest]):
    window.__pyjsRunId = run_id
    window.__pyjsSelectedTests: list[object] = selected_tests
    window.__pyjsRunSelectedTests__: callable = run_selected_tests

    if window.__pyjsAutoRun__ is not False:
        launch_automatic_results(report_automatic_results, run_id, selected_tests)
