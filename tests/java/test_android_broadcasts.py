from typing import cast

import pytest

from pyjs import jvm
from pyjs.android import TextView, View
from pyjs.android.testing import (
    NoMatchingViewException,
    ViewAssertion,
    by_id,
    by_text,
    launch,
)

from .android_broadcast_app import BroadcastActivity

pytestmark = pytest.mark.pyjs_android_jvm


@jvm.native("android/os/SystemClock", name="elapsedRealtime")
def elapsed_time() -> int: ...


@jvm.native("android/os/SystemClock", name="sleep")
def sleep(milliseconds: int) -> None: ...


class ReadText(ViewAssertion):
    def __init__(self):
        self.text = ""

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        self.text = cast(TextView, view).getText().to_string()


def wait_for_text(expected: str) -> None:
    state = ReadText()
    deadline = elapsed_time() + 5000
    while elapsed_time() < deadline:
        by_id(1001).check(state)
        if state.text == expected:
            return
        sleep(10)
    by_id(1001).assert_text(expected)


def test_async_broadcast_completion_waits_for_worker_and_finishes_after_failure() -> None:
    launch(BroadcastActivity)
    for action, expected in [("save", "Saved 日本語 😀"), ("fail", "Save failed"),
                             ("save", "Saved 日本語 😀")]:
        by_text("begin").click()
        wait_for_text("Waiting for background save")
        by_text(action).click()
        wait_for_text(expected)
