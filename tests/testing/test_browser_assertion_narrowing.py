from typing import Literal

import pytest

from pyjs import js

pytestmark = pytest.mark.pyjs_web


@js
class Value:
    def __init__(self):
        self.text = "present"


@js
def optional_value(present: bool) -> Value | None:
    return Value() if present else None


@js
def text(value: Value) -> str:
    return value.text


@js
async def checkpoint():
    return None


@js
async def test_none_assertion_preserves_narrowing_across_await():
    value = optional_value(True)
    assert value is not None
    await checkpoint()
    assert text(value) == "present"


@js
def test_compound_truth_assertion_preserves_narrowing():
    left = optional_value(True)
    right = optional_value(True)
    assert left and right is not None
    assert text(left) == text(right)


@js
def selected(value: Literal["yes", "no"]) -> Literal["yes", "no"]:
    return value


@js
def require_yes(value: Literal["yes"]) -> str:
    return value


@js
def test_literal_assertion_preserves_narrowing():
    value = selected("yes")
    assert value == "yes"
    assert require_yes(value) == "yes"


@js
def read(events: list[str]) -> Value | None:
    events.append("read")
    return Value()


@js
def detail(events: list[str]) -> str:
    events.append("message")
    return "missing value"


@js
def test_assertion_reporting_evaluates_once_and_keeps_messages_lazy():
    events: list[str] = []
    assert isinstance(read(events), Value), detail(events)
    assert events == ["read"]
    value = optional_value(False)
    with pytest.raises(AssertionError, match="missing value"):
        assert value is not None, detail(events)
    assert events == ["read", "message"]
