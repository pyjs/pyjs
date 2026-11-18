from typing import cast

import pytest

from pyjs.android import Bundle, DragShadowBuilder, KeyEvent, Point, Runnable, View
from pyjs.android.controls import EditText
from pyjs.android.testing import (
    NoMatchingViewException,
    ViewAssertion,
    background,
    by_id,
    by_text,
    launch,
    recreate,
    resume,
)

from .android_robolectric_app import DeferredRestoreActivity, GreetingActivity

pytestmark = pytest.mark.pyjs_android_jvm


class ViewEnabled(ViewAssertion):
    def __init__(self, expected: bool) -> None:
        self.expected = expected

    def check(
        self, view: View | None, error: NoMatchingViewException | None,
    ) -> None:
        assert error is None
        assert view is not None
        if view is not None:
            assert view.isEnabled() == self.expected


class MissingView(ViewAssertion):
    def check(
        self, view: View | None, error: NoMatchingViewException | None,
    ) -> None:
        assert view is None
        assert error is not None


class DisableView(Runnable):
    def __init__(self, view: View) -> None:
        self.view = view

    def run(self) -> None:
        self.view.setEnabled(False)


class ShadowAndCallbacks(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None
        assert view is not None
        if view is not None:
            size = Point(0, 0)
            touch = Point(0, 0)
            DragShadowBuilder(view).onProvideShadowMetrics(size, touch)
            assert size.x == view.getWidth()
            assert size.y == view.getHeight()
            assert touch.x == size.x // 2
            assert touch.y == size.y // 2
            action = DisableView(view)
            assert view.postDelayed(action, 60_000)
            assert view.removeCallbacks(action)
            assert view.isEnabled()
            assert view.postDelayed(action, 0)


def test_native_shadow_metrics_and_view_callback_scheduling() -> None:
    launch(GreetingActivity)
    by_id(1002).check(ShadowAndCallbacks())
    by_id(1002).check(ViewEnabled(False))


def test_compiled_python_uses_espresso_under_robolectric() -> None:
    launch(GreetingActivity)
    by_text("Hello from Python").assert_displayed()
    by_id(1002).click()
    by_id(1001).assert_text("Clicked from Python")


def test_custom_view_assertion_inspects_matched_native_view() -> None:
    launch(GreetingActivity)
    by_id(1002).check(ViewEnabled(True))


def test_activity_lifecycle_controls_restore_saved_instance_state() -> None:
    launch(GreetingActivity)
    by_id(1002).click()
    background()
    resume()
    by_id(1001).assert_text("Clicked from Python")
    recreate()
    by_id(1001).assert_text("Clicked from Python")


class DeferredSelection(ViewAssertion):
    def __init__(self, set_value: bool):
        self.set_value = set_value

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        field = cast(EditText, view)
        if self.set_value:
            field.requestFocus()
            field.set_selection_range(2, 5)
        else:
            assert field.getSelectionStart() == 2
            assert field.getSelectionEnd() == 5


class CompleteDeferredLoad(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        activity = cast(DeferredRestoreActivity, view.getContext())
        assert activity.restore_calls == 1
        activity.complete_load()


def test_native_view_restoration_can_wait_until_controls_exist() -> None:
    launch(DeferredRestoreActivity)
    by_id(1011).replace_text("A 😀 draft 日本語")
    by_id(1011).check(DeferredSelection(True))
    recreate()
    by_id(1010).assert_text("Loading")
    by_id(1010).check(CompleteDeferredLoad())
    by_id(1011).assert_text("A 😀 draft 日本語")
    by_id(1011).check(DeferredSelection(False))


def test_nested_bundles_preserve_state_and_accept_null() -> None:
    outer = Bundle()
    assert outer.get_bundle("pending") is None
    inner = Bundle()
    inner.put_string("draft", "Saved 日本語😀")
    outer.put_bundle("pending", inner)
    restored = outer.get_bundle("pending")
    assert restored is not None
    assert restored.get_string("draft") == "Saved 日本語😀"
    outer.put_bundle("pending", None)
    assert outer.get_bundle("pending") is None


def test_dialog_scoped_confirmation_and_cancellation() -> None:
    launch(GreetingActivity)
    by_text("Show confirmation").click()
    by_text("Cancel").in_dialog().click()
    by_id(1001).assert_text("Waiting")
    by_text("Show confirmation").click()
    by_text("Confirm").in_dialog().click()
    by_id(1001).assert_text("Confirmed")


def test_keyboard_and_ime_actions_reach_native_text_fields() -> None:
    launch(GreetingActivity)
    by_id(1004).replace_text("draft😀")
    by_id(1004).click()
    by_id(1004).press_key(KeyEvent.KEYCODE_DEL)
    by_id(1004).assert_text("draft")
    by_id(1004).ime_action()
    by_id(1001).assert_text("draft")


def test_custom_view_assertion_receives_missing_view_error() -> None:
    launch(GreetingActivity)
    by_id(9999).check(MissingView())


@pytest.mark.xfail(
    strict=True, reason="Negative control: Espresso must report the failed check",
)
def test_custom_view_assertion_does_not_swallow_failure() -> None:
    launch(GreetingActivity)
    by_id(1002).check(ViewEnabled(False))
