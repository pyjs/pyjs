import pytest

from pyjs import js
from pyjs.testing.client.runtime import BrowserTest, run_selected_tests

pytestmark = pytest.mark.pyjs_web


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
