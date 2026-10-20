import pytest
from pyjs.java.errors import SecurityException
from pyjs_examples.notes.android_storage import (
    OrderFile,
    OrderObserver,
    OrderSession,
    SaveDriver,
    StorageError,
)


class MemoryFile(OrderFile):
    def __init__(self):
        super().__init__("memory/order")
        self.saved = []
        self.fail = False
        self.reads = 0

    def read(self, expected):
        self.reads += 1
        return list(self.saved)

    def write(self, order):
        if self.fail:
            raise StorageError("write failed", self.path, "write")
        self.saved = list(order)


class ManualDriver(SaveDriver):
    def __init__(self):
        self.pending = []
        self.submitted = []
        self.fail_start = False

    def submit(self, session, write):
        if self.fail_start:
            raise SecurityException("start failed")
        assert not self.pending, "overlapping writer"
        self.pending.append((session, write))
        self.submitted.append(write)

    def finish(self):
        session, write = self.pending.pop()
        write.run()
        session.complete(write)
        return write


class Observer(OrderObserver):
    def __init__(self, session):
        self.session = session
        self.messages = []

    def storage_changed(self):
        self.messages.append(self.session.message)


@pytest.fixture
def queue():
    store, driver = MemoryFile(), ManualDriver()
    session = OrderSession(store, driver)
    assert session.restore([1, 2, 3]) == [1, 2, 3]
    return session, store, driver


def edit_and_drop(session, order):
    session.changed(order)
    session.save(order)


def test_write_snapshots_are_detached_and_only_one_writer_runs(queue):
    session, store, driver = queue
    order = [2, 1, 3]
    edit_and_drop(session, order)
    first = session.in_flight
    order[0] = 99
    assert first.order == [2, 1, 3]
    edit_and_drop(session, [3, 2, 1])
    edit_and_drop(session, [1, 3, 2])
    assert len(driver.submitted) == 1
    driver.finish()
    assert store.saved == [2, 1, 3]
    assert session.dirty and session.message == "Saving…"
    assert session.in_flight.order == [1, 3, 2]
    assert len(driver.submitted) == 2
    driver.finish()
    assert store.saved == [1, 3, 2]
    assert not session.dirty and session.message == ""


def test_acknowledgement_does_not_save_an_unfinished_drag(queue):
    session, store, driver = queue
    edit_and_drop(session, [2, 1, 3])
    session.changed([3, 2, 1])
    driver.finish()
    assert store.saved == [2, 1, 3]
    assert session.dirty and session.in_flight is None
    assert session.restore([1, 2, 3]) == [3, 2, 1]
    session.save([3, 2, 1])
    driver.finish()
    assert not session.dirty and store.saved == [3, 2, 1]


def test_queued_drop_keeps_its_snapshot_when_a_new_drag_begins(queue):
    session, store, driver = queue
    edit_and_drop(session, [2, 1, 3])
    edit_and_drop(session, [3, 2, 1])
    session.changed([1, 3, 2])
    driver.finish()
    assert session.in_flight.order == [3, 2, 1]
    driver.finish()
    assert store.saved == [3, 2, 1]
    assert session.dirty
    assert session.pending_order == [1, 3, 2]
    assert session.in_flight is None


def test_failed_write_stops_and_retry_uses_the_latest_order(queue):
    session, store, driver = queue
    edit_and_drop(session, [2, 1, 3])
    edit_and_drop(session, [3, 2, 1])
    store.fail = True
    driver.finish()
    assert session.in_flight is None and session.dirty
    assert len(driver.submitted) == 1
    assert store.saved == []
    assert "write failed" in session.message
    assert "StorageError:" in session.failure_report
    store.fail = False
    session.save(session.pending_order)
    driver.finish()
    assert store.saved == [3, 2, 1]
    assert not session.dirty and session.failure_report == ""


def test_failed_start_and_stale_acknowledgement_cannot_complete_retry(queue):
    session, store, driver = queue
    driver.fail_start = True
    edit_and_drop(session, [2, 1, 3])
    assert session.dirty and session.in_flight is None
    assert "start failed" in session.message
    driver.fail_start = False
    session.save(session.pending_order)
    store.fail = True
    failed = driver.finish()
    store.fail = False
    session.save(session.pending_order)
    retry = session.in_flight
    assert retry is not failed and retry.revision == failed.revision
    session.complete(failed)
    assert session.in_flight is retry
    completed = driver.finish()
    session.complete(completed)
    session.complete(failed)
    assert not session.dirty and session.message == ""
    assert store.saved == [2, 1, 3]


def test_recreation_reuses_queue_and_detaching_old_observer_keeps_new_one(queue):
    session, store, driver = queue
    old = Observer(session)
    session.attach(old)
    edit_and_drop(session, [2, 1, 3])
    session.detach(old)
    old_count = len(old.messages)
    current = Observer(session)
    session.attach(current)
    session.detach(old)
    assert session.restore([1, 2, 3]) == [2, 1, 3]
    assert store.reads == 1
    driver.finish()
    assert len(old.messages) == old_count
    assert current.messages == ["Saving…", ""]
    session.detach(current)
    assert session.observer is None


def test_clean_and_blocked_sessions_never_start_a_worker(queue):
    session, store, driver = queue
    session.save([1, 2, 3])
    assert driver.submitted == []
    session.can_save = False
    edit_and_drop(session, [3, 2, 1])
    assert session.dirty
    assert driver.submitted == [] and store.saved == []
