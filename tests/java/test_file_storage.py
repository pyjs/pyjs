import os

import pytest

from tests.java.test_exceptions import run_jvm


def test_notes_file_order_round_trip_uses_real_jvm_io(tmp_path):
    destination = tmp_path / "order.txt"
    result = run_jvm(f'''
        from pyjs_examples.notes.android_storage import OrderFile, OrderSession
        def main() -> int:
            session = OrderSession(OrderFile({str(destination)!r}))
            order = session.load([1, 2])
            assert session.can_save and len(order) == 0
            session.dirty = True
            session.save([2, 1])
            assert not session.dirty and session.message == ""
            restored = session.load([1, 2])
            assert restored[0] == 2 and restored[1] == 1
            return 42
    ''', tmp_path / "classes")
    assert result.returncode == 42, result.stderr
    assert destination.read_text() == "2\n1\n"
    assert list(tmp_path.glob("notes-order-*.tmp")) == []


def test_notes_existing_snapshot_replacement_obeys_the_host_file_api(tmp_path):
    destination = tmp_path / "order.txt"
    destination.write_text("1\n2\n")
    # OpenJDK's Windows File.renameTo refuses an existing destination.
    # The Android example must report that failure, never delete the old file.
    replaces = os.name != "nt"
    result = run_jvm(f'''
        from pyjs_examples.notes.android_storage import OrderFile, OrderSession
        def main() -> int:
            session = OrderSession(OrderFile({str(destination)!r}))
            order = session.load([1, 2])
            assert order[0] == 1 and order[1] == 2
            session.dirty = True
            session.save([2, 1])
            assert session.dirty == {not replaces}
            assert (session.message == "") == {replaces}
            assert (session.failure_report == "") == {replaces}
            return 42
    ''', tmp_path / "classes")
    assert result.returncode == 42, result.stderr
    assert destination.read_text() == ("2\n1\n" if replaces else "1\n2\n")
    assert list(tmp_path.glob("notes-order-*.tmp")) == []


@pytest.mark.parametrize("contents", ["1\n1\n", "1\n", "not an id\n", "9999999999999999999999999\n"])
def test_notes_rejects_invalid_snapshots_on_the_jvm(tmp_path, contents):
    destination = tmp_path / "order.txt"
    destination.write_text(contents)
    result = run_jvm(f'''
        from pyjs_examples.notes.android_storage import OrderFile, OrderSession
        def main() -> int:
            session = OrderSession(OrderFile({str(destination)!r}))
            order = session.load([1, 2])
            assert not session.can_save and len(order) == 0
            assert session.message.startswith("Could not load saved order:")
            assert session.failure_report != ""
            session.dirty = True
            session.save([2, 1])
            return 42
    ''', tmp_path / "classes")
    assert result.returncode == 42, result.stderr
    assert destination.read_text() == contents


def test_notes_failed_replace_preserves_destination_and_removes_attempt(tmp_path):
    destination = tmp_path / "directory"
    destination.mkdir()
    sentinel = destination / "keep"
    sentinel.write_text("original")
    result = run_jvm(f'''
        from pyjs_examples.notes.android_storage import OrderFile, OrderSession, StorageError
        def main() -> int:
            session = OrderSession(OrderFile({str(destination)!r}))
            try:
                session.store.write([2, 1])
            except StorageError as failed:
                assert failed.path == {str(destination)!r}
                assert failed.operation == "replace"
                assert str(failed) == "Could not replace the saved order"
            else:
                return 1
            session.can_save = True
            session.dirty = True
            session.save([2, 1])
            assert session.dirty
            assert session.message == "Order not saved. Tap to retry. Could not replace the saved order"
            assert not session.store.cleanup_failed
            assert "StorageError: Could not replace the saved order" in session.failure_report
            return 42
    ''', tmp_path / "classes")
    assert result.returncode == 42, result.stderr
    assert sentinel.read_text() == "original"
    assert list(tmp_path.glob("notes-order-*.tmp")) == []


def test_notes_create_failure_wraps_native_cause_with_destination(tmp_path):
    destination = str(tmp_path / "missing" / "order.txt")
    result = run_jvm(f'''
        from typing import cast
        from pyjs.java.io import IOException
        from pyjs_examples.notes.android_storage import OrderFile, StorageError
        def main() -> int:
            store = OrderFile({destination!r})
            try:
                store.write([1, 2])
            except StorageError as failed:
                assert failed.path == {destination!r}
                assert failed.operation == "create"
                assert isinstance(failed.__cause__, IOException)
                assert failed.__context__ is failed.__cause__
                assert len(failed.args) == 1
                assert cast(str, failed.args[0]) == str(failed)
                assert failed.__suppress_context__
                assert not store.cleanup_failed
                return 42
            return 1
    ''', tmp_path / "classes")
    assert result.returncode == 42, result.stderr
    assert not (tmp_path / "missing").exists()


def test_real_jvm_stream_closes_after_body_failure(tmp_path):
    destination = tmp_path / "order.txt"
    destination.write_text("1\n2\n")
    result = run_jvm(f'''
        from pyjs.java.io import IOException, RandomAccessFile
        from pyjs_examples.notes.android_storage import Closing
        def main() -> int:
            stream = RandomAccessFile({str(destination)!r}, "r")
            try:
                with Closing(stream):
                    raise ValueError("body")
            except ValueError as error:
                assert str(error) == "body"
            try:
                stream.readLine()
            except IOException:
                return 42
            return 1
    ''', tmp_path / "classes")
    assert result.returncode == 42, result.stderr
