import pytest

from pyjs import js
from pyjs.javascript import encodeURIComponent
from pyjs.testing.client.app import load_test_module
from pyjs.testing.client.runtime import BrowserTest, run_selected_tests
from pyjs.testing.web import mount
from pyjs.web.domx import iframe

pytestmark = pytest.mark.pyjs_web


@js
async def test_module_loader_reports_syntax_runtime_and_import_failures():
    for source in ["let = ;", "throw new Error('module startup failure')",
                   "import '/missing-test-module.js'"]:
        frame = iframe()
        mount(frame)
        failed = False
        try:
            await load_test_module(frame, 'data:text/javascript,' + encodeURIComponent(source))
        except Exception:
            failed = True
        finally:
            frame.remove()
        assert failed


@js
def raise_structured_failure() -> None:
    raise ValueError("structured failure")


@js
async def test_browser_failures_capture_structured_exception_details():
    results = await run_selected_tests(
        [
            BrowserTest(
                "tests/testing/test_browser_runtime.py::raise_structured_failure",
                "tests.testing.test_browser_runtime",
                "raise_structured_failure",
                raise_structured_failure,
            )
        ]
    )

    assert len(results) == 1
    exception = results[0].exception
    if exception is None:
        raise AssertionError("Missing structured exception details")
    assert exception.name == "RangeError"
    assert exception.message == "structured failure"
    assert "structured failure" in exception.stack
