from typing import cast

import pytest

from pyjs.android import View
from pyjs.android.controls import EditText, InputType
from pyjs.android.testing import NoMatchingViewException, ViewAssertion, by_id, launch
from pyjs.java import i32

from .android_robolectric_app import GreetingActivity

pytestmark = pytest.mark.pyjs_android_jvm


class EditBuffer(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        field = cast(EditText, view)
        assert EditText(field.getContext()).getLayout() is None
        field.setSingleLine(False)
        field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE)
        field.setText("A😀B")
        buffer = field.get_text()
        assert buffer.length() == 4
        assert buffer.replace(i32(1), i32(3), "🌍\n雪") is buffer
        assert buffer.to_string() == "A🌍\n雪B"


class SetTextWrapping(ViewAssertion):
    def __init__(self, horizontal: bool):
        self.horizontal = horizontal

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        field = cast(EditText, view)
        layout = field.getLayout()
        assert layout is not None and layout.getWidth() > 0
        original = layout.getWidth()
        layout.increaseWidthTo(i32(original + 100))
        assert layout.getWidth() == original + 100
        field.setHorizontallyScrolling(self.horizontal)


class CheckTextLayout(ViewAssertion):
    def __init__(self, horizontal: bool):
        self.horizontal = horizontal

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        field = cast(EditText, view)
        layout = field.getLayout()
        assert layout is not None
        if self.horizontal:
            assert layout.getWidth() > field.getWidth()
        else:
            assert layout.getWidth() <= field.getWidth()


def test_editable_replacement_uses_utf16_offsets_and_returns_the_same_buffer() -> None:
    launch(GreetingActivity)
    by_id(i32(1004)).check(EditBuffer())
    by_id(i32(1004)).assert_text("A🌍\n雪B")


def test_text_layout_width_and_horizontal_wrapping_preserve_contents() -> None:
    launch(GreetingActivity)
    by_id(i32(1004)).check(EditBuffer())
    by_id(i32(1004)).check(SetTextWrapping(True))
    by_id(i32(1004)).check(CheckTextLayout(True))
    by_id(i32(1004)).assert_text("A🌍\n雪B")
    by_id(i32(1004)).check(SetTextWrapping(False))
    by_id(i32(1004)).check(CheckTextLayout(False))
    by_id(i32(1004)).assert_text("A🌍\n雪B")
