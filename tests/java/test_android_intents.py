import pytest

from pyjs import jvm
from pyjs.android import CharSequence, Intent, JavaCharSequence, Uri, parse_uri

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


def test_stream_share_extras_preserve_uri_and_native_type_checks() -> None:
    intent = Intent().set_action(Intent.ACTION_SEND).set_type("image/png")
    assert intent.get_parcelable_extra(Intent.EXTRA_STREAM) is None
    intent.put_string_extra(Intent.EXTRA_STREAM, "content://example.images/not-a-uri-object")
    assert intent.get_parcelable_extra(Intent.EXTRA_STREAM) is None
    uri = parse_uri("content://example.images/photos/42?name=Garden%20photo")
    intent.put_parcelable_extra(Intent.EXTRA_STREAM, uri)
    intent.add_flags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    stream = intent.get_parcelable_extra(Intent.EXTRA_STREAM)
    assert isinstance(stream, Uri)
    assert stream.get_scheme() == "content"
    assert stream.to_string() == uri.to_string()
    assert intent.get_flags() == Intent.FLAG_GRANT_READ_URI_PERMISSION
    intent.put_parcelable_extra(Intent.EXTRA_STREAM, Intent().set_action("example.other"))
    other = intent.get_parcelable_extra(Intent.EXTRA_STREAM)
    assert isinstance(other, Intent) and not isinstance(other, Uri)
    assert other.get_action() == "example.other"
    intent.put_parcelable_extra(Intent.EXTRA_STREAM, None)
    assert intent.get_parcelable_extra(Intent.EXTRA_STREAM) is None
    intent.put_parcelable_extra(Intent.EXTRA_STREAM, uri)
    intent.remove_extra(Intent.EXTRA_STREAM)
    assert intent.get_parcelable_extra(Intent.EXTRA_STREAM) is None


def test_uri_scheme_distinguishes_content_files_and_relative_paths() -> None:
    assert parse_uri("content://example.images/1").get_scheme() == "content"
    assert parse_uri("file:///private/image.png").get_scheme() == "file"
    assert parse_uri("https://example.org/image.png").get_scheme() == "https"
    assert parse_uri("image.png").get_scheme() is None
