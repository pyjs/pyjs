from pyjs.android import Activity, Bundle, LinearLayout, TextView, dp
from pyjs.android.controls import EditText
from pyjs.android.graphics import Typeface
from pyjs.android.text import (
    SpannableString,
    Spanned,
    StrikethroughSpan,
    StyleSpan,
    TypefaceSpan,
)
from pyjs.java import i32


def sample_text() -> SpannableString:
    text = SpannableString("Bold\nItalic\nStrike\nCode 😀")
    text.set_span(StyleSpan(Typeface.BOLD), i32(0), i32(4), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    text.set_span(StyleSpan(Typeface.ITALIC), i32(5), i32(11), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    text.set_span(StrikethroughSpan(), i32(12), i32(18), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    text.set_span(TypefaceSpan("monospace"), i32(19), i32(26), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    return text


class StyledTextActivity(Activity):
    def onCreate(self, state: Bundle | None) -> None:
        super().onCreate(state)
        root = LinearLayout(self)
        root.setOrientation(LinearLayout.VERTICAL)
        root.setPadding(dp(self, 24), dp(self, 72), dp(self, 24), dp(self, 24))
        root.setFocusableInTouchMode(True)
        root.requestFocus()
        label = TextView(self)
        label.setContentDescription("Styled preview")
        label.setTextSize(24.0)
        label.setText(sample_text())
        root.addView(label)
        editor = EditText(self)
        editor.setId(i32(1004))
        editor.setContentDescription("Styled editor")
        editor.setText(sample_text())
        root.addView(editor)
        self.setContentView(root)


def main() -> int:
    activity = StyledTextActivity()
    activity.onCreate(None)
    return 0
