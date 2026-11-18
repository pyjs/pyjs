from typing import cast

import pytest

from pyjs.android import View
from pyjs.android.testing import (
    NoMatchingViewException,
    ViewAssertion,
    by_id,
    by_text,
    launch,
    press_back,
)
from pyjs.java import i32

from .android_menu_app import MenuActivity

pytestmark = pytest.mark.pyjs_android_jvm


class MenuState(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        popup = cast(MenuActivity, view.getContext()).popup
        menu = popup.get_menu()
        item = menu.find_item(i32(20))
        assert item is not None and not item.is_enabled() and item.is_visible()
        hidden = menu.find_item(i32(30))
        assert hidden is not None and not hidden.is_visible()
        assert menu.find_item(i32(99)) is None
        menu.remove_item(i32(20))
        assert menu.find_item(i32(20)) is None
        menu.clear()
        assert menu.find_item(i32(10)) is None and menu.find_item(i32(30)) is None
        menu.add(i32(0), i32(40), i32(0), "Replacement")
        popup.set_on_menu_item_click_listener(None)
        popup.set_on_dismiss_listener(None)
        popup.dismiss()


def test_popup_selection_and_back_dismissal_have_separate_callbacks() -> None:
    launch(MenuActivity)
    by_id(1001).click()
    by_text("Hidden").assert_absent()
    by_text("Unavailable").assert_displayed()
    by_text("Bold 雪").click()
    by_id(1002).assert_text("Selected 10")
    by_id(1003).assert_text("Dismissed")
    by_id(1001).click()
    press_back()
    by_text("Bold 雪").assert_absent()
    by_id(1002).assert_text("Selected 10")


def test_popup_menu_mutation_and_listener_removal() -> None:
    launch(MenuActivity)
    by_id(1001).check(MenuState())
    by_id(1001).click()
    by_text("Replacement").click()
    by_id(1002).assert_text("Unchanged")
    by_id(1003).assert_text("")
