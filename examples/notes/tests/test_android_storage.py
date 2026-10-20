from pathlib import Path

import pytest
from pyjs.java.io import IOException
from pyjs_examples.notes import android_storage as storage
from pyjs_examples.notes.android import NotesAdapter


@pytest.fixture
def file_io(tmp_path, monkeypatch):
    class Faults:
        stage = ""
        fail_cleanup = False
        fail_close = False
        streams = []
        created = 0

        def check(self, stage):
            if stage == self.stage or stage == "close" and self.fail_close:
                raise IOException(stage)

    faults = Faults()

    class File:
        def __init__(self, path):
            self.path = Path(path)

        def getPath(self):
            return str(self.path)

        def getParentFile(self):
            return File(self.path.parent)

        def exists(self):
            return self.path.exists()

        def length(self):
            return self.path.stat().st_size

        def delete(self):
            if faults.fail_cleanup:
                return False
            self.path.unlink()
            return True

        def renameTo(self, destination):
            if faults.stage == "replace":
                return False
            self.path.replace(destination.path)
            return True

    class Stream:
        def __init__(self, path, mode):
            faults.check("open-read" if mode == "r" else "open-write")
            self.file = open(path, "r" if mode == "r" else "w", encoding="ascii")
            faults.streams.append(self.file)

        def readLine(self):
            faults.check("read")
            line = self.file.readline()
            return None if line == "" else line.rstrip("\r\n")

        def writeBytes(self, text):
            self.file.write(text)
            faults.check("write")

        def getFD(self):
            return self

        def sync(self):
            faults.check("sync")

        def close(self):
            self.file.close()
            faults.check("close")

    def temporary(prefix, suffix, directory):
        faults.check("create")
        faults.created += 1
        file = File(directory.path / (prefix + str(faults.created) + suffix))
        file.path.touch()
        return file

    monkeypatch.setattr(storage, "File", File)
    monkeypatch.setattr(storage, "RandomAccessFile", Stream)
    monkeypatch.setattr(storage, "create_temp_file", temporary)
    return faults


def session_at(tmp_path):
    return storage.OrderSession(storage.OrderFile(str(tmp_path / "order.txt")))


def test_first_launch_then_save_restore_and_adapter_alignment(tmp_path, file_io):
    session = session_at(tmp_path)
    adapter = NotesAdapter(["one", "two"], ["red", "blue"], [1, 2], session)
    adapter.restore_order()
    assert session.can_save and not session.dirty and session.message == ""
    adapter.move(0, 1)
    assert session.dirty
    assert not (tmp_path / "order.txt").exists()
    adapter.save_order()
    assert not session.dirty and session.message == ""
    assert (tmp_path / "order.txt").read_text() == "2\n1\n"

    restored = NotesAdapter(["one", "two"], ["red", "blue"], [1, 2], session_at(tmp_path))
    restored.restore_order()
    assert restored.note_ids == [2, 1]
    assert restored.notes == ["two", "one"]
    assert restored.colors == ["blue", "red"]
    assert not restored.session.dirty
    assert all(stream.closed for stream in file_io.streams)


def test_replace_failure_carries_operation_and_destination(tmp_path, file_io):
    destination = tmp_path / "order.txt"
    file_io.stage = "replace"
    with pytest.raises(storage.StorageError) as failed:
        storage.OrderFile(str(destination)).write([1, 2])
    assert failed.value.operation == "replace"
    assert failed.value.path == str(destination)
    assert str(failed.value) == "Could not replace the saved order"
    assert not destination.exists()
    assert list(tmp_path.glob("notes-order-*.tmp")) == []


@pytest.mark.parametrize("stage", ["create", "open-write", "write", "sync", "close"])
def test_write_failure_preserves_native_cause_and_adds_operation(tmp_path, file_io, stage):
    destination = tmp_path / "order.txt"
    file_io.stage = stage
    with pytest.raises(storage.StorageError) as failed:
        storage.OrderFile(str(destination)).write([1, 2])
    assert failed.value.operation == ("create" if stage == "create" else "write")
    assert failed.value.path == str(destination)
    assert isinstance(failed.value.__cause__, IOException)
    assert failed.value.__context__ is failed.value.__cause__
    assert failed.value.args == (str(failed.value),)
    assert str(failed.value.__cause__) == stage
    assert failed.value.__suppress_context__
    assert not destination.exists()
    assert list(tmp_path.glob("notes-order-*.tmp")) == []
    assert all(stream.closed for stream in file_io.streams)


@pytest.mark.parametrize("stage", ["create", "open-write", "write", "sync", "close", "replace"])
def test_failed_save_keeps_previous_snapshot_and_can_retry(tmp_path, file_io, stage):
    path = tmp_path / "order.txt"
    path.write_text("1\n2\n")
    session = session_at(tmp_path)
    assert session.load([1, 2]) == [1, 2]
    session.dirty = True
    file_io.stage = stage
    session.save([2, 1])

    assert session.dirty
    assert session.message.startswith("Order not saved. Tap to retry.")
    assert "StorageError:" in session.failure_report
    if stage != "replace":
        assert "IOException:" in session.failure_report
        assert "The above exception was the direct cause" in session.failure_report
    assert path.read_text() == "1\n2\n"
    assert list(tmp_path.glob("*.tmp")) == []
    assert all(stream.closed for stream in file_io.streams)

    file_io.stage = ""
    session.save([2, 1])
    assert not session.dirty and session.message == ""
    assert session.failure_report == ""
    assert path.read_text() == "2\n1\n"


@pytest.mark.parametrize("contents", [
    "", "1\n", "1\n1\n", "1\n3\n", "2\n1\n2\n", "x\n2\n", "01\n2\n",
    "1\n 2\n", "x" * 1025,
])
def test_invalid_snapshot_is_preserved_and_never_automatically_overwritten(tmp_path, file_io, contents):
    path = tmp_path / "order.txt"
    path.write_text(contents)
    session = session_at(tmp_path)
    assert session.load([1, 2]) == []
    assert not session.can_save
    assert session.message.startswith("Could not load saved order:")
    session.dirty = True
    session.save([2, 1])
    assert path.read_text() == contents
    assert all(stream.closed for stream in file_io.streams)


@pytest.mark.parametrize("stage", ["open-read", "read", "close"])
def test_read_failures_block_saving_without_discarding_the_file(tmp_path, file_io, stage):
    path = tmp_path / "order.txt"
    path.write_text("1\n2\n")
    file_io.stage = stage
    session = session_at(tmp_path)
    assert session.load([1, 2]) == []
    assert not session.can_save
    assert stage in session.message
    assert "IOException:" in session.failure_report
    assert path.read_text() == "1\n2\n"
    assert all(stream.closed for stream in file_io.streams)


def test_primary_failure_survives_secondary_close_and_cleanup_failures(tmp_path, file_io):
    path = tmp_path / "order.txt"
    path.write_text("1\n2\n")
    session = session_at(tmp_path)
    session.load([1, 2])
    session.dirty = True
    file_io.stage = "write"
    file_io.fail_close = True
    file_io.fail_cleanup = True
    session.save([2, 1])
    assert session.message == (
        "Order not saved. Tap to retry. Could not write the saved order: write "
        "Temporary file cleanup also failed."
    )
    assert session.dirty and path.read_text() == "1\n2\n"
    assert all(stream.closed for stream in file_io.streams)


@pytest.mark.parametrize("contents, stage, expected", [
    ("1\n2\n", "read", "Could not load saved order: read"),
    ("1\n1\n", "", "Could not load saved order: Saved order contains an invalid or duplicate note"),
])
def test_failed_read_or_validation_survives_close_failure(
    tmp_path, file_io, contents, stage, expected,
):
    path = tmp_path / "order.txt"
    path.write_text(contents)
    file_io.stage = stage
    file_io.fail_close = True
    session = session_at(tmp_path)
    assert session.load([1, 2]) == []
    assert not session.can_save
    assert session.message == expected
    assert path.read_text() == contents
    assert all(stream.closed for stream in file_io.streams)


def test_retry_clears_prior_cleanup_failure_without_deleting_unowned_files(tmp_path, file_io):
    path = tmp_path / "order.txt"
    path.write_text("1\n2\n")
    unrelated = tmp_path / "unrelated.tmp"
    unrelated.write_text("keep")
    session = session_at(tmp_path)
    session.load([1, 2])
    session.dirty = True
    file_io.stage = "write"
    file_io.fail_cleanup = True
    session.save([2, 1])
    assert session.store.cleanup_failed
    abandoned = list(tmp_path.glob("notes-order-*.tmp"))
    assert len(abandoned) == 1
    partial = abandoned[0].read_text()
    file_io.stage = ""
    file_io.fail_cleanup = False
    session.save([2, 1])
    assert not session.store.cleanup_failed
    assert not session.dirty
    assert session.failure_report == ""
    assert path.read_text() == "2\n1\n"
    assert unrelated.read_text() == "keep"
    assert abandoned[0].read_text() == partial


def test_no_movement_does_not_write_and_unexpected_errors_propagate(tmp_path, file_io):
    session = session_at(tmp_path)
    session.load([1, 2])
    session.save([1, 2])
    assert not (tmp_path / "order.txt").exists()
    with pytest.raises(TypeError):
        with storage.Closing(storage.RandomAccessFile(str(tmp_path / "body.txt"), "rw")):
            raise TypeError("bug")
    assert all(stream.closed for stream in file_io.streams)
