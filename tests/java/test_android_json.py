import pytest

from pyjs import jvm
from pyjs.android import Intent
from pyjs.android.json import JsonWriter
from pyjs.java.io import OutputStream, OutputStreamWriter, StringWriter

pytestmark = pytest.mark.pyjs_android_jvm


@jvm.native("java/io/ByteArrayOutputStream")
class BytesOutput(OutputStream):
    def __init__(self): ...
    def toString(self, charset: str) -> str: ...


def write_document(writer: JsonWriter) -> None:
    writer.begin_object()
    writer.name("text").string('😀雪"\\\r\n\t\x00')
    writer.name("items").begin_array()
    writer.integer(9223372036854775807).integer(-9223372036854775808)
    writer.boolean(False).boolean(True).string(None).null()
    writer.end_array().end_object()


def expected_document() -> str:
    return ('{"text":"😀雪\\"\\\\\\r\\n\\t\\u0000",'
            '"items":[9223372036854775807,-9223372036854775808,false,true,null,null]}')


def test_streaming_json_uses_exact_native_overloads_and_escaping() -> None:
    destination = StringWriter()
    writer = JsonWriter(destination)
    write_document(writer)
    writer.flush()
    assert destination.toString() == expected_document()
    writer.close()
    assert destination.toString() == expected_document()


def test_utf8_stream_writer_flushes_and_closes_complete_document() -> None:
    stream = BytesOutput()
    writer = JsonWriter(OutputStreamWriter(stream, "UTF-8"))
    write_document(writer)
    writer.close()
    assert stream.toString("UTF-8") == expected_document()


def test_document_picker_title_uses_standard_extra() -> None:
    intent = Intent()
    intent.set_action(Intent.ACTION_CREATE_DOCUMENT)
    intent.add_category(Intent.CATEGORY_OPENABLE)
    intent.set_type("application/json")
    intent.put_string_extra(Intent.EXTRA_TITLE, "backup.json")
    assert intent.get_string_extra(Intent.EXTRA_TITLE) == "backup.json"
