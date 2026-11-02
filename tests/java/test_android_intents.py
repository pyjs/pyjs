import pytest

from pyjs import jvm
from pyjs.android import CharSequence, Intent, JavaCharSequence

pytestmark = pytest.mark.pyjs_android_jvm


@jvm.native("android/text/SpannableString")
class StyledText(JavaCharSequence):
    def __init__(self, text: CharSequence) -> None: ...


def test_text_share_extras_preserve_plain_and_styled_content() -> None:
    intent = Intent().set_action(Intent.ACTION_SEND).set_type("text/plain")
    assert intent.get_action() == Intent.ACTION_SEND
    assert intent.get_type() == "text/plain"
    intent.add_flags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK)
    assert intent.get_flags() == Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK
    assert intent.get_char_sequence_extra(Intent.EXTRA_TEXT) is None
    assert intent.get_string_extra(Intent.EXTRA_SUBJECT) is None
    intent.put_string_extra(Intent.EXTRA_SUBJECT, "A subject 😀")
    intent.put_string_extra(Intent.EXTRA_TEXT, "Plain 雪\nhttps://example.com/?a=1&b=2")
    plain = intent.get_char_sequence_extra(Intent.EXTRA_TEXT)
    assert plain is not None
    if plain is not None:
        assert plain.to_string() == "Plain 雪\nhttps://example.com/?a=1&b=2"
    intent.put_char_sequence_extra(Intent.EXTRA_TEXT, StyledText("Styled 😀\nsecond line"))
    styled = intent.get_char_sequence_extra(Intent.EXTRA_TEXT)
    assert styled is not None
    if styled is not None:
        assert styled.to_string() == "Styled 😀\nsecond line"
    assert intent.get_string_extra(Intent.EXTRA_SUBJECT) == "A subject 😀"
    intent.remove_extra(Intent.EXTRA_SUBJECT)
    assert intent.get_string_extra(Intent.EXTRA_SUBJECT) is None
    intent.put_char_sequence_extra(Intent.EXTRA_TEXT, None)
    assert intent.get_char_sequence_extra(Intent.EXTRA_TEXT) is None
    intent.set_type(None)
    assert intent.get_type() is None
