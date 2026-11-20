import zipfile

import pytest

from tests.java.test_exceptions import run_jvm


@pytest.mark.parametrize("case", [
    "streaming_zip_round_trip_binary_unicode_and_empty_entries",
    "zip_rejects_writes_without_entry_and_duplicate_names",
])
def test_native_zip_on_jvm(case, tmp_path):
    result = run_jvm(f'''
from tests.java.test_android_zip import test_{case}
def main() -> str:
    test_{case}()
    return "ok"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"


def test_native_file_stream_on_jvm(tmp_path):
    result = run_jvm(f'''
from pyjs.java.io import File
from tests.java.test_android_zip import file_stream_round_trip
def main() -> str:
    file_stream_round_trip(File({str(tmp_path)!r}))
    return "ok"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"


def test_native_archive_is_readable_by_python_zipfile(tmp_path):
    path = tmp_path / "interop.zip"
    result = run_jvm(f'''
from pyjs.java import i32
from pyjs.java.io import File, FileOutputStream
from tests.java.test_android_zip import encoded_archive
def main() -> str:
    value = encoded_archive()
    stream = FileOutputStream(File({str(path)!r}))
    try:
        stream.write(value, i32(0), i32(len(value)))
    finally:
        stream.close()
    return "ok"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["empty/", "empty/file", "資料/😀.bin"]
        assert archive.read("empty/file") == b""
        assert archive.read("資料/😀.bin") == bytes(range(256)) * 300
        assert archive.testzip() is None
