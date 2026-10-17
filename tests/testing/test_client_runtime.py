import asyncio

import pytest

from pyjs.testing.client.assertions import assert_compare, assert_condition
from pyjs.testing.client.runtime import (
    BrowserTest,
    initialize_test_runtime,
    run_selected_tests,
    window,
)


class BrowserFailure(Exception):
    def __init__(self, stack: str):
        super().__init__(stack)
        self.stack = stack
        self.message = stack


def test_run_selected_tests_calls_bound_functions_and_records_results():
    calls: list[str] = []

    def pass_test():
        calls.append("passed")

    def fail_test():
        calls.append("failed")
        raise BrowserFailure("failure stack")

    selected_tests = [
        BrowserTest(
            "tests/test_example.py::test_pass", "tests.test_example", "test_pass", pass_test
        ),
        BrowserTest(
            "tests/test_example.py::test_fail", "tests.test_example", "test_fail", fail_test
        ),
    ]

    results = asyncio.run(run_selected_tests(selected_tests))

    assert calls == ["passed", "failed"]
    assert [(result.nodeid, result.outcome) for result in results] == [
        ("tests/test_example.py::test_pass", "passed"),
        ("tests/test_example.py::test_fail", "failed"),
    ]
    assert results[0].exception is None
    assert results[1].exception.name == "BrowserFailure"
    assert results[1].exception.message == "failure stack"
    assert results[1].exception.stack == "failure stack"
    assert window.__pyjsCurrentTest__ is None


def test_initialize_test_runtime_publishes_direct_callable_manifest(monkeypatch):
    reports = []
    selected_tests = [
        BrowserTest(
            "tests/test_example.py::test_pass",
            "tests.test_example",
            "test_pass",
            lambda: None,
        )
    ]
    monkeypatch.setattr(window, "__pyjsAutoRun__", True)
    monkeypatch.setattr(window, "__pyjsReportResults__", reports.append)

    initialize_test_runtime("run-1", selected_tests)

    assert window.__pyjsRunId == "run-1"
    assert window.__pyjsSelectedTests == selected_tests
    assert window.__pyjsRunSelectedTests__ is run_selected_tests
    assert len(reports) == 1
    assert reports[0].runId == "run-1"
    assert reports[0].results[0].outcome == "passed"


def test_testing_assertions_report_expression_values_and_lazy_messages():
    messages = []

    assert_condition(True, "value", lambda: messages.append("not evaluated"))
    assert_condition("truthy", "value", lambda: messages.append("not evaluated"))
    assert messages == []

    with pytest.raises(AssertionError, match=r"left == right.*left=1.*right=2.*wrong value"):
        assert_compare(False, 1, "left", "==", 2, "right", lambda: "wrong value")
