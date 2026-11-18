from typing import cast

import pytest

from pyjs.android import Activity, View
from pyjs.android.controls import EditText
from pyjs.android.insets import get_insets_controller, ime, root_window_insets
from pyjs.android.testing import NoMatchingViewException, ViewAssertion, by_id, launch

from .android_keyboard_app import KeyboardActivity

pytestmark = [pytest.mark.pyjs_android_jvm, pytest.mark.pyjs_android_dependencies("androidx")]


class InsetsBoundary(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        activity = cast(Activity, view.getContext())
        assert root_window_insets(EditText(activity)) is None
        window = activity.get_window()
        decor = window.get_decor_view()
        assert decor.getWidth() > 0
        assert ime() == 8
        controller = get_insets_controller(window, view)
        controller.hide(ime())
        controller.hide(ime())
        assert cast(EditText, view).get_text().to_string() == "Typed text"


def test_detached_insets_and_repeated_hide_preserve_editor_content() -> None:
    launch(KeyboardActivity)
    by_id(1001).check(InsetsBoundary())
