from typing import cast

import pytest

from pyjs.android import (
    Activity,
    Bundle,
    LayoutParams,
    LinearLayout,
    LinearLayoutParams,
    TextView,
    View,
)
from pyjs.android.controls import HorizontalScrollView
from pyjs.android.testing import NoMatchingViewException, ViewAssertion, by_id, launch
from pyjs.java import i32

pytestmark = pytest.mark.pyjs_android_jvm


class HorizontalActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        for index in range(2):
            scroll = HorizontalScrollView(self)
            scroll.setId(i32(1001 + index))
            scroll.setLayoutParams(LinearLayoutParams(160, 60, 0.0))
            scroll.set_fill_viewport(True)
            child = TextView(self)
            child.setText("X")
            child.setMinimumWidth(i32(600 if index == 0 else 40))
            child.setLayoutParams(LayoutParams(LayoutParams.WRAP_CONTENT, 48))
            scroll.addView(child)
            root.addView(scroll)
        self.setContentView(root)


class HorizontalBounds(ViewAssertion):
    def __init__(self, wide: bool):
        self.wide = wide

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        scroll = cast(HorizontalScrollView, view)
        child = scroll.getChildAt(0)
        assert child is not None
        assert scroll.getWidth() == 160, "viewport width: " + str(scroll.getWidth())
        assert child.getWidth() == (600 if self.wide else 160), "child width: " + str(child.getWidth())
        scroll.scroll_to(i32(1000), i32(1000))
        assert scroll.getScrollX() == (440 if self.wide else 0), "horizontal offset: " + str(scroll.getScrollX())
        assert scroll.getScrollY() == 0, "vertical offset: " + str(scroll.getScrollY())
        scroll.scroll_to(i32(-100), i32(-100))
        assert scroll.getScrollX() == 0 and scroll.getScrollY() == 0


def test_horizontal_overflow_clamps_and_short_content_fills_viewport() -> None:
    launch(HorizontalActivity)
    by_id(1001).check(HorizontalBounds(True))
    by_id(1002).check(HorizontalBounds(False))
