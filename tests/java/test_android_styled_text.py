from typing import cast

import pytest

from pyjs.android import TextView, View
from pyjs.android.controls import EditText
from pyjs.android.graphics import Typeface
from pyjs.android.testing import NoMatchingViewException, ViewAssertion, by_id, launch
from pyjs.android.text import (
    Spannable,
    SpannableString,
    SpannableStringBuilder,
    Spanned,
    StrikethroughSpan,
    StyleSpan,
    TypefaceSpan,
)
from pyjs.java import i32
from pyjs.java.errors import IndexOutOfBoundsException

from .android_styled_text_app import StyledTextActivity

pytestmark = pytest.mark.pyjs_android_jvm


def test_span_ranges_use_utf16_and_relocate_the_same_span_object() -> None:
    text = SpannableString("A😀 bold italic code")
    bold = StyleSpan(Typeface.BOLD)
    italic = StyleSpan(Typeface.ITALIC)
    strike = StrikethroughSpan()
    code = TypefaceSpan("monospace")
    text.set_span(bold, i32(4), i32(8), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    text.set_span(italic, i32(9), i32(15), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    text.set_span(strike, i32(4), i32(15), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    text.set_span(code, i32(16), i32(20), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    assert text.to_string() == "A😀 bold italic code" and text.length() == 20
    assert bold.get_style() == Typeface.BOLD and italic.get_style() == Typeface.ITALIC
    assert code.get_family() == "monospace" and TypefaceSpan(None).get_family() is None
    assert text.get_span_start(bold) == 4 and text.get_span_end(bold) == 8
    assert text.get_span_flags(bold) == Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
    assert text.get_span_start(code) == 16 and text.get_span_end(code) == 20
    styles = text.get_spans(i32(0), text.length(), StyleSpan)
    assert len(styles) == 2 and styles[0] is bold and styles[1] is italic
    assert len(text.get_spans(i32(0), i32(1), TypefaceSpan)) == 0
    text.set_span(bold, i32(1), i32(3), Spanned.SPAN_INCLUSIVE_EXCLUSIVE)
    assert text.get_span_start(bold) == 1 and text.get_span_end(bold) == 3
    text.remove_span(bold)
    text.remove_span(bold)
    assert text.get_span_start(bold) == -1 and text.get_span_end(bold) == -1
    assert text.get_span_flags(bold) == 0 and text.get_span_start(strike) == 4
    assert text.to_string() == "A😀 bold italic code"


def test_invalid_ranges_and_empty_exclusive_spans_follow_android_rules() -> None:
    text = SpannableStringBuilder("ab")
    span = StyleSpan(Typeface.BOLD)
    for start in [-1, 3]:
        rejected = False
        try:
            text.set_span(span, i32(start), i32(2), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        except IndexOutOfBoundsException:
            rejected = True
        assert rejected
        assert text.to_string() == "ab" and text.get_span_start(span) == -1
    text.set_span(span, i32(1), i32(1), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    assert text.get_span_start(span) == -1
    text.set_span(span, i32(0), i32(2), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    text.replace(i32(0), i32(2), "")
    assert text.to_string() == "" and text.get_span_start(span) == -1


def test_builder_endpoint_flags_and_copies_preserve_native_span_semantics() -> None:
    for flags in [Spanned.SPAN_EXCLUSIVE_EXCLUSIVE, Spanned.SPAN_INCLUSIVE_EXCLUSIVE,
                  Spanned.SPAN_EXCLUSIVE_INCLUSIVE, Spanned.SPAN_INCLUSIVE_INCLUSIVE]:
        text = SpannableStringBuilder("ab")
        span = StyleSpan(Typeface.BOLD_ITALIC)
        text.set_span(span, i32(0), i32(2), flags)
        assert text.replace(i32(0), i32(0), "x") is text
        assert text.append("y") is text
        assert text.to_string() == "xaby"
        expected_start = 1 if flags == 33 or flags == 34 else 0
        expected_end = 4 if flags == 18 or flags == 34 else 3
        assert text.get_span_start(span) == expected_start
        assert text.get_span_end(span) == expected_end
        copied = SpannableString(text)
        text.remove_span(span)
        assert copied.get_span_start(span) == expected_start
        assert copied.get_span_end(span) == expected_end
        assert copied.to_string() == "xaby" and text.get_span_start(span) == -1


class StyledEditor(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert view is not None and error is None
        source = SpannableString("A😀 bold")
        span = StyleSpan(Typeface.BOLD)
        source.set_span(span, i32(4), i32(8), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        label = TextView(view.getContext())
        label.setText(source)
        shown = label.getText()
        assert isinstance(shown, Spanned)
        assert shown.get_span_start(span) == 4 and shown.get_span_end(span) == 8
        field = cast(EditText, view)
        field.setText(source)
        buffer = field.get_text()
        assert isinstance(buffer, Spannable)
        buffer.replace(i32(1), i32(3), "Q")
        assert buffer.to_string() == "AQ bold"
        assert buffer.get_span_start(span) == 3 and buffer.get_span_end(span) == 7
        buffer.remove_span(span)
        assert buffer.get_span_start(span) == -1
        assert source.get_span_start(span) == 4 and source.to_string() == "A😀 bold"


def test_styled_text_transfers_into_native_labels_and_editable_buffers() -> None:
    launch(StyledTextActivity)
    by_id(i32(1004)).check(StyledEditor())
    by_id(i32(1004)).assert_text("AQ bold")
