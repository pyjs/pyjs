import pytest

from pyjs import js
from pyjs.javascript import encodeURIComponent
from pyjs.testing.client.app import load_test_module
from pyjs.testing.client.runtime import BrowserTest, run_selected_tests
from pyjs.testing.web import mount
from pyjs.web.dom import window
from pyjs.web.domx import iframe

pytestmark = pytest.mark.pyjs_web


@js
async def test_module_loader_reports_syntax_runtime_and_import_failures():
    sources = ["let = ;", "throw new Error('module startup failure')",
               "await new Promise(resolve => setTimeout(resolve, 80)); throw new Error('async module failure')"]
    messages = ['Unexpected', 'module startup failure', 'async module failure']
    for index, source in enumerate(sources):
        frame = iframe()
        mount(frame)
        message = ''
        try:
            await load_test_module(frame, 'data:text/javascript,' + encodeURIComponent(source))
        except Exception as error:
            message = str(error)
        finally:
            frame.remove()
        assert messages[index] in message


@js
async def test_module_loader_waits_for_async_evaluation():
    frame = iframe()
    mount(frame)
    try:
        source = "await new Promise(resolve => setTimeout(resolve, 80)); document.body.setAttribute('data-ready', 'yes')"
        await load_test_module(frame, 'data:text/javascript,' + encodeURIComponent(source))
        target = frame.contentDocument
        if target is not None:
            assert target.body.getAttribute('data-ready') == 'yes'
        else:
            raise AssertionError('Missing iframe document')
    finally:
        frame.remove()


@js
async def test_module_loader_reports_real_missing_module_fetches():
    parent = window.parent
    if parent is None:
        raise AssertionError('Missing runner window')
    missing = parent.location.origin + '/missing-browser-test-module.js'
    assert missing.startswith('http://')
    for url in [missing, 'data:text/javascript,' + encodeURIComponent("import '" + missing + "'")]:
        frame = iframe()
        mount(frame)
        message = ''
        try:
            await load_test_module(frame, url)
        except Exception as error:
            message = str(error)
        finally:
            frame.remove()
        assert 'Failed to fetch dynamically imported module' in message


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
