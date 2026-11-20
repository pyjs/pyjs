import pytest

from pyjs import int8
from pyjs.android.testing import application_context
from pyjs.java import JVMArray, i32
from pyjs.java.io import (
    ByteArrayInputStream,
    ByteArrayOutputStream,
    File,
    FileInputStream,
    FileOutputStream,
    IOException,
    create_temp_file,
)
from pyjs.java.zip import ZipEntry, ZipException, ZipInputStream, ZipOutputStream

pytestmark = pytest.mark.pyjs_android_jvm


def payload() -> JVMArray[int8]:
    value = JVMArray[int8](256)
    for index in range(256):
        value[index] = int8(index)
    return value


def encoded_archive() -> JVMArray[int8]:
    output = ByteArrayOutputStream()
    archive = ZipOutputStream(output)
    data = payload()
    try:
        archive.putNextEntry(ZipEntry("empty/"))
        archive.closeEntry()
        archive.putNextEntry(ZipEntry("empty/file"))
        archive.closeEntry()
        archive.putNextEntry(ZipEntry("資料/😀.bin"))
        for _ in range(300):
            archive.write(data, i32(0), i32(len(data)))
        archive.closeEntry()
        archive.finish()
        return output.toByteArray()
    finally:
        archive.close()


def test_streaming_zip_round_trip_binary_unicode_and_empty_entries() -> None:
    reader = ZipInputStream(ByteArrayInputStream(encoded_archive()))
    buffer = JVMArray[int8](137)
    try:
        entry = reader.getNextEntry()
        assert entry is not None and entry.getName() == "empty/" and entry.isDirectory()
        assert reader.read(buffer) == -1
        reader.closeEntry()
        entry = reader.getNextEntry()
        assert entry is not None and entry.getName() == "empty/file" and not entry.isDirectory()
        assert reader.read(buffer) == -1
        entry = reader.getNextEntry()
        assert entry is not None and entry.getName() == "資料/😀.bin"
        count = 0
        while True:
            size = int(reader.read(buffer))
            if size == -1:
                break
            assert size > 0
            for index in range(size):
                assert buffer[index] == int8((count + index) % 256)
            count += size
        assert count == 300 * 256
        assert reader.getNextEntry() is None
    finally:
        reader.close()


def test_zip_rejects_writes_without_entry_and_duplicate_names() -> None:
    archive = ZipOutputStream(ByteArrayOutputStream())
    data = payload()
    try:
        rejected = False
        try:
            archive.write(data, i32(0), i32(1))
        except ZipException:
            rejected = True
        assert rejected
        archive.putNextEntry(ZipEntry("same"))
        archive.closeEntry()
        rejected = False
        try:
            archive.putNextEntry(ZipEntry("same"))
        except ZipException:
            rejected = True
        assert rejected
    finally:
        archive.close()


def file_stream_round_trip(directory: File) -> None:
    file = create_temp_file("stream-bytes", ".bin", directory)
    data = payload()
    try:
        writer = FileOutputStream(file)
        try:
            writer.write(data, i32(3), i32(200))
        finally:
            writer.close()
        reader = FileInputStream(file)
        buffer = JVMArray[int8](71)
        count = 0
        try:
            while True:
                size = int(reader.read(buffer))
                if size == -1:
                    break
                assert size > 0
                for index in range(size):
                    assert buffer[index] == int8(count + index + 3)
                count += size
            assert count == 200 and file.length() == 200
        finally:
            reader.close()
        rejected = False
        try:
            reader.read(buffer)
        except IOException:
            rejected = True
        assert rejected
    finally:
        assert file.delete()
    rejected = False
    try:
        reader = FileInputStream(file)
        reader.close()
    except IOException:
        rejected = True
    assert rejected


def test_file_stream_round_trip_and_failed_reads() -> None:
    file_stream_round_trip(application_context().getFilesDir())
