import pytest

from pyjs import uint16
from pyjs.java import JVMArray, StringBuilder, string_from_chars
from pyjs.java.base64 import base64_decoder
from pyjs.java.charset import charset_for_name
from pyjs.java.errors import IndexOutOfBoundsException
from pyjs.java.io import (
    ByteArrayInputStream,
    InputStreamReader,
    IOException,
    Reader,
    StringReader,
)

pytestmark = pytest.mark.pyjs_android_jvm


def read_chunks(reader: Reader) -> str:
    buffer = JVMArray[uint16](3)
    output = StringBuilder()
    count = reader.read(buffer, 1, 1)
    while count != -1:
        assert count == 1
        assert buffer[0] == 0 and buffer[2] == 0
        output.append(string_from_chars(buffer, 1, count))
        count = reader.read(buffer, 1, 1)
    assert reader.read(buffer, 0, 3) == -1
    return output.to_string()


def test_strict_utf8_reads_small_chunks_without_losing_unicode() -> None:
    # UTF-8 for A, NUL, e-acute, a supplementary emoji, CRLF, and z.
    data = base64_decoder().decode("QQDDqfCfmIANCno=")
    stream = ByteArrayInputStream(data)
    reader = InputStreamReader(stream, charset_for_name("UTF-8").newDecoder())
    try:
        assert read_chunks(reader) == "A\x00é😀\r\nz"
    finally:
        reader.close()
    closed = False
    try:
        reader.read(JVMArray[uint16](1), 0, 1)
    except IOException:
        closed = True
    assert closed


def test_strict_utf8_rejects_malformed_and_truncated_input() -> None:
    # Invalid leading byte, overlong form, encoded surrogate, truncated scalar,
    # and valid text followed by an invalid byte.
    for encoded in ["/w==", "wK8=", "7aCA", "8J+Y", "b2v/"]:
        reader = InputStreamReader(ByteArrayInputStream(base64_decoder().decode(encoded)),
                                   charset_for_name("UTF-8").newDecoder())
        rejected = False
        try:
            read_chunks(reader)
        except IOException:
            rejected = True
        finally:
            reader.close()
        assert rejected, encoded


def test_reader_ranges_and_string_copy() -> None:
    reader = StringReader("A😀z")
    buffer = JVMArray[uint16](6)
    assert reader.read(buffer, 1, 4) == 4
    assert buffer[0] == 0 and buffer[5] == 0
    assert buffer[1] == 65 and buffer[2] == 0xD83D and buffer[3] == 0xDE00
    copied = string_from_chars(buffer, 1, 4)
    buffer[1] = uint16(66)
    assert copied == "A😀z"
    assert string_from_chars(buffer, 2, 2) == "😀"
    assert string_from_chars(buffer, 6, 0) == ""
    invalid_read = False
    try:
        reader.read(buffer, 5, 2)
    except IndexOutOfBoundsException:
        invalid_read = True
    assert invalid_read
    invalid_copy = False
    try:
        string_from_chars(buffer, -1, 1)
    except IndexOutOfBoundsException:
        invalid_copy = True
    assert invalid_copy
    reader.close()


def test_empty_utf8_input_is_eof() -> None:
    reader = InputStreamReader(ByteArrayInputStream(base64_decoder().decode("")),
                               charset_for_name("UTF-8").newDecoder())
    try:
        assert read_chunks(reader) == ""
    finally:
        reader.close()
