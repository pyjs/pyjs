from typing import cast

import pytest

from pyjs.android import TextView, TruncateAt, View
from pyjs.android.testing import (
    NoMatchingViewException,
    ViewAssertion,
    by_description,
    by_id,
    by_text,
    launch,
)

from .android_cards_app import CardsActivity, TextPreviewActivity

pytestmark = [pytest.mark.pyjs_android_jvm, pytest.mark.pyjs_android_dependencies("androidx")]


class CardLifecycle(ViewAssertion):
    def __init__(self, phase: str):
        self.phase = phase

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        cards = cast(CardsActivity, view.getContext()).cards
        assert cards.bound > 0 and cards.attached > 0
        if self.phase == "initial":
            assert cards.attached > cards.detached
        elif self.phase == "scrolled":
            assert cards.attached > cards.detached and cards.detached > 0
            assert cards.recycled > 0
        else:
            assert cards.attached == cards.detached
            assert cards.recycled > 0


def test_recycled_cards_receive_native_attach_detach_and_recycle_callbacks() -> None:
    launch(CardsActivity)
    by_text("Row 0").assert_displayed()
    by_id(100).check(CardLifecycle("initial"))
    by_description("Cards far").click()
    by_text("Row 40").assert_displayed()
    by_id(100).check(CardLifecycle("scrolled"))
    by_description("Cards start").click()
    by_text("Row 0").assert_displayed()
    by_id(100).check(CardLifecycle("scrolled"))
    by_description("Cards replace").click()
    by_id(100).check(CardLifecycle("replaced"))
    by_description("Cards unknown").assert_absent()


class TextEllipsis(ViewAssertion):
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        label = cast(TextView, view)
        activity = cast(TextPreviewActivity, view.getContext())
        assert label.getText().to_string() == activity.original
        layout = label.getLayout()
        assert layout is not None
        if self.enabled:
            assert label.getEllipsize() is TruncateAt.END
            assert layout.getLineCount() == 2
            assert layout.getEllipsisCount(1) > 0
            assert layout.getEllipsisStart(1) > 0
        else:
            assert label.getEllipsize() is None
            assert layout.getLineCount() > 2
            assert layout.getEllipsisCount(1) == 0


def test_multiline_ellipsis_preserves_source_text_and_can_be_disabled() -> None:
    launch(TextPreviewActivity)
    by_id(200).check(TextEllipsis(True))
    by_id(201).check(TextEllipsis(False))
