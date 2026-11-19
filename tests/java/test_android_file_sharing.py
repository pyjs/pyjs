import pytest

from pyjs.android import Intent, parse_uri, uri_clip_data
from pyjs.android.testing import application_context
from pyjs.java import i32
from pyjs.java.io import File, FileOutputStream, OutputStreamWriter, create_temp_file

pytestmark = pytest.mark.pyjs_android_jvm


def test_no_backup_directory_is_private_persistent_storage_not_cache() -> None:
    context = application_context()
    directory = context.get_no_backup_files_dir()
    assert directory.getPath() != context.getFilesDir().getPath()
    assert directory.getPath() != context.get_cache_dir().getPath()
    file = create_temp_file("no-backup-test-", ".txt", directory)
    try:
        writer = OutputStreamWriter(FileOutputStream(file), "UTF-8")
        try:
            writer.write("private")
        finally:
            writer.close()
        reopened = File(context.get_no_backup_files_dir().getPath() + "/" + file.getName())
        assert reopened.length() == 7
    finally:
        assert file.delete()


def test_cache_file_writer_and_directory_metadata() -> None:
    context = application_context()
    directory = create_temp_file("share-test-", ".dir", context.get_cache_dir())
    assert directory.delete()
    assert directory.mkdirs()
    file = File(directory.getPath() + "/note.txt")
    try:
        writer = OutputStreamWriter(FileOutputStream(file), "UTF-8")
        try:
            writer.write("Note 雪😀\n")
        finally:
            writer.close()
        assert file.getName() == "note.txt" and file.length() == 13
        assert file.lastModified() > 0
        files = directory.listFiles()
        assert files is not None and len(files) == 1
        assert files[0].getPath() == file.getPath()
    finally:
        assert file.delete()
        assert directory.delete()
    assert directory.listFiles() is None


def test_uri_clip_is_preserved_in_intent_and_can_be_removed() -> None:
    context = application_context()
    uri = parse_uri("https://example.test/note.txt")
    clip = uri_clip_data(context.get_content_resolver(), "Note copy", uri)
    assert clip.get_item_count() == 1
    actual = clip.get_item_at(i32(0)).get_uri()
    assert actual is not None and actual.to_string() == uri.to_string()
    intent = Intent().add_flags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    intent.set_clip_data(clip)
    restored = intent.get_clip_data()
    assert restored is not None and restored.get_item_count() == 1
    actual = restored.get_item_at(i32(0)).get_uri()
    assert actual is not None and actual.to_string() == uri.to_string()
    assert intent.get_flags() == Intent.FLAG_GRANT_READ_URI_PERMISSION
    intent.set_clip_data(None)
    assert intent.get_clip_data() is None
