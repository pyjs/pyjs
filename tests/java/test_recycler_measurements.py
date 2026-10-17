from typing import cast

import pytest

from pyjs.android import View
from pyjs.android.recycler_testing import StaggeredGridSnapshot
from pyjs.android.recyclerview import RecyclerView
from pyjs.android.testing import NoMatchingViewException, ViewAssertion, by_id, launch
from tests.staggered_calibration_cases import heights, outer_tops, spans

from .recycler_measurements_app import (
    CalibrationActivity,
    FourColumnActivity,
    ThreeColumnActivity,
)

pytestmark = [pytest.mark.pyjs_android_jvm,
              pytest.mark.pyjs_android_dependencies("androidx")]


class Measure(ViewAssertion):
    def __init__(self, columns: int, translated: bool) -> None:
        self.columns = columns
        self.translated = translated

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None
        assert view is not None
        recycler = cast(RecyclerView, view)
        snapshot = StaggeredGridSnapshot(recycler)
        assert snapshot.stable_ids
        assert len(snapshot.order) == 8
        # The complete eight-child payload would obscure the geometry contract.
        assert snapshot.to_json().startswith(
            '{"version":1,"coordinates":"recycler-local-pixels","width":601,"height":400,'
        )
        assert not snapshot.pending_updates
        assert len(snapshot.children) == 8
        width = snapshot.width // self.columns
        tops = outer_tops(self.columns)
        lanes = spans(self.columns)
        sizes = heights()
        for child in snapshot.children:
            index = child.adapter_position
            assert child.item_id == 100 + index
            assert child.layout_position == index
            assert child.decorated_top == tops[index], "Top at " + str(index)
            assert child.full_span == (index == 0 or index == 4)
            if child.full_span:
                assert child.left == 0
                assert child.right == snapshot.width
                assert child.bottom - child.top == sizes[index]
            else:
                assert child.span == lanes[index]
                assert child.decorated_left == lanes[index] * width
                assert child.decorated_right == (lanes[index] + 1) * width
                assert child.left == child.decorated_left + 3
                assert child.right == child.decorated_right - 7
                assert child.top == child.decorated_top + 5
                assert child.bottom == child.top + sizes[index], (
                    "Height at " + str(index) + ": " + str(child.bottom - child.top)
                    + " expected " + str(sizes[index])
                )
                assert child.decorated_bottom == child.bottom + 9
            if index == 5:
                assert child.bottom > snapshot.height
                assert child.bottom - child.top == 1100
        first = recycler.getChildAt(1)
        if self.translated:
            assert snapshot.children[1].translation_x == 13.0
            assert snapshot.children[1].translation_y == -17.0
            first.setTranslationX(0.0)
            first.setTranslationY(0.0)
        else:
            first.setTranslationX(13.0)
            first.setTranslationY(-17.0)


def test_two_column_measurements_preserve_full_bounds_and_translation() -> None:
    launch(CalibrationActivity)
    by_id(100).check(Measure(2, False))
    by_id(100).check(Measure(2, True))


def test_three_column_full_span_measurements() -> None:
    launch(ThreeColumnActivity)
    by_id(100).check(Measure(3, False))


def test_four_column_full_span_measurements() -> None:
    launch(FourColumnActivity)
    by_id(100).check(Measure(4, False))
