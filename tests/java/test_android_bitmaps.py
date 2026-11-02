import pytest

from pyjs import int8
from pyjs.android import parse_uri
from pyjs.android.controls import ImageView
from pyjs.android.graphics import BitmapOptions, decode_bitmap
from pyjs.android.testing import application_context, run_on_main
from pyjs.java import JVMArray, i32
from pyjs.java.concurrent import Runnable
from pyjs.java.io import (
    ByteArrayOutputStream,
    IOException,
    OutputStream,
    OutputStreamWriter,
    create_temp_file,
)

pytestmark = pytest.mark.pyjs_android_jvm


def write_range(stream: OutputStream, data: JVMArray[int8], offset: i32, length: i32) -> None:
    stream.write(data, offset, length)


def test_output_stream_byte_ranges_dispatch_to_the_concrete_stream() -> None:
    stream = ByteArrayOutputStream()
    data = JVMArray[int8](4)
    data[0] = int8(127)
    data[1] = int8(-128)
    data[2] = int8(-1)
    write_range(stream, data, 1, 2)
    write_range(stream, data, 3, 1)
    write_range(stream, data, 4, 0)
    for offset in [-1, 4]:
        rejected = False
        try:
            write_range(stream, data, i32(offset), 1)
        except Exception:
            rejected = True
        assert rejected
    rejected = False
    try:
        write_range(stream, data, 0, -1)
    except Exception:
        rejected = True
    assert rejected
    result = stream.toByteArray()
    assert len(result) == 3
    assert result[0] == -128 and result[1] == -1 and result[2] == 0
    stream.close()


def test_uri_output_stream_writes_raw_bytes_and_propagates_closed_errors() -> None:
    context = application_context()
    resolver = context.get_content_resolver()
    file = create_temp_file("binary-output", ".bin", context.getFilesDir())
    uri = parse_uri("file://" + file.getPath())
    data = JVMArray[int8](3)
    data[0] = int8(-128)
    data[1] = int8(-1)
    try:
        output = resolver.open_output_stream(uri, "wt")
        assert output is not None
        try:
            write_range(output, data, 0, 3)
        finally:
            output.close()
        rejected = False
        try:
            write_range(output, data, 0, 3)
        except IOException:
            rejected = True
        assert rejected
        source = resolver.open_input_stream(uri)
        assert source is not None
        try:
            destination = ByteArrayOutputStream()
            buffer = JVMArray[int8](2)
            count = source.read(buffer)
            while count != -1:
                destination.write(buffer, 0, count)
                count = source.read(buffer)
            result = destination.toByteArray()
            assert len(result) == 3
            for index in range(3):
                assert result[index] == data[index]
        finally:
            source.close()
    finally:
        assert file.delete()


def png_bytes() -> JVMArray[int8]:
    # Independently generated solid RGB PNG, 32 by 16 pixels, with a prefix/suffix.
    values = [
        1, 2, 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
        0, 0, 0, 32, 0, 0, 0, 16, 8, 2, 0, 0, 0, 248, 98, 234, 14, 0, 0, 0,
        29, 73, 68, 65, 84, 120, 156, 99, 80, 104, 112, 160, 41, 98, 24, 181,
        96, 212, 130, 81, 11, 70, 45, 24, 181, 96, 40, 88, 0, 0, 21, 162,
        192, 16, 5, 111, 87, 180, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96,
        130, 3,
    ]
    data = JVMArray[int8](len(values))
    for index in range(len(data)):
        data[index] = int8(values[index])
    return data


def test_bitmap_bounds_then_sampled_decode_preserve_original_bytes() -> None:
    data = png_bytes()
    options = BitmapOptions()
    options.inJustDecodeBounds = True
    length = i32(len(data) - 3)
    assert decode_bitmap(data, 2, length, options) is None
    assert options.outWidth == 32 and options.outHeight == 16
    assert options.outMimeType == "image/png"
    options.inJustDecodeBounds = False
    options.inSampleSize = 4
    bitmap = decode_bitmap(data, 2, length, options)
    assert bitmap is not None
    try:
        assert bitmap.getWidth() == 8 and bitmap.getHeight() == 4
        assert 0 < bitmap.getByteCount() <= 8 * 4 * 8
        assert not bitmap.isRecycled()
        assert data[0] == 1 and data[1] == 2 and data[len(data) - 1] == 3
        original = png_bytes()
        for index in range(len(data)):
            assert data[index] == original[index]
    finally:
        bitmap.recycle()
    assert bitmap.isRecycled()


def test_invalid_bitmap_and_bounds_inspection_return_no_pixels() -> None:
    data = JVMArray[int8](4)
    options = BitmapOptions()
    options.inJustDecodeBounds = True
    assert decode_bitmap(data, 0, 4, options) is None
    assert options.outWidth == -1 and options.outHeight == -1
    assert options.outMimeType is None
    options.inJustDecodeBounds = False
    assert decode_bitmap(data, 0, 4, options) is None
    assert decode_bitmap(data, 0, 0, None) is None


class DisplayBitmap(Runnable):
    def run(self) -> None:
        data = png_bytes()
        bitmap = decode_bitmap(data, 2, i32(len(data) - 3), None)
        assert bitmap is not None
        view = ImageView(application_context())
        try:
            assert view.get_drawable() is None
            view.set_image_bitmap(bitmap)
            assert view.get_drawable() is not None
            view.set_image_bitmap(None)
            # Android may retain an empty BitmapDrawable for a null bitmap.
            view.set_image_drawable(None)
            assert view.get_drawable() is None
            assert not bitmap.isRecycled()
        finally:
            view.set_image_drawable(None)
            bitmap.recycle()


def test_image_view_accepts_and_clears_a_native_bitmap() -> None:
    run_on_main(DisplayBitmap())


def test_byte_buffer_extraction_returns_an_independent_binary_copy() -> None:
    stream = ByteArrayOutputStream()
    assert len(stream.toByteArray()) == 0
    data = JVMArray[int8](4)
    data[0] = int8(127)
    data[1] = int8(128)
    data[2] = int8(255)
    data[3] = int8(0)
    stream.write(data, 1, 3)
    first = stream.toByteArray()
    assert len(first) == 3
    assert first[0] == -128 and first[1] == -1 and first[2] == 0
    first[0] = int8(1)
    data[1] = int8(2)
    stream.write(data, 0, 1)
    stream.close()
    second = stream.toByteArray()
    assert len(second) == 4 and len(first) == 3
    assert second[0] == -128 and second[3] == 127


def test_uri_input_stream_reads_binary_bytes_and_reports_missing_files() -> None:
    context = application_context()
    resolver = context.get_content_resolver()
    file = create_temp_file("binary-input", ".bin", context.getFilesDir())
    uri = parse_uri("file://" + file.getPath())
    assert uri.to_string() == "file://" + file.getPath()
    try:
        output = resolver.open_output_stream(uri, "wt")
        assert output is not None
        writer = OutputStreamWriter(output, "UTF-8")
        try:
            writer.write("A\x00é")
        finally:
            writer.close()
        stream = resolver.open_input_stream(uri)
        assert stream is not None
        try:
            buffer = JVMArray[int8](2)
            destination = ByteArrayOutputStream()
            count = stream.read(buffer)
            while count != -1:
                destination.write(buffer, 0, count)
                count = stream.read(buffer)
            data = destination.toByteArray()
            assert len(data) == 4
            assert data[0] == 65 and data[1] == 0
            assert data[2] == -61 and data[3] == -87
            assert stream.read(buffer) == -1
        finally:
            stream.close()
    finally:
        assert file.delete()
    missing = False
    try:
        resolver.open_input_stream(uri)
    except IOException:
        missing = True
    assert missing
