import textwrap

import pytest

from tests.java.test_exceptions import assert_matches_python

SOURCE = '''
from pyjs_examples.notes.android_storage import (
    OrderFile, OrderObserver, OrderSession, OrderWrite, SaveDriver, StorageError,
)
from pyjs.java.errors import SecurityException
class Store(OrderFile):
    def __init__(self):
        super().__init__("memory/order")
        self.saved: list[int] = []
        self.fail = False
    def read(self, expected: list[int]) -> list[int]:
        return list(self.saved)
    def write(self, order: list[int]) -> None:
        if self.fail:
            raise StorageError("write failed")
        self.saved = list(order)
class Driver(SaveDriver):
    def __init__(self):
        self.write: OrderWrite | None = None
        self.count = 0
        self.fail_start = False
    def submit(self, session: OrderSession, write: OrderWrite) -> None:
        if self.fail_start:
            raise SecurityException("start failed")
        assert self.write is None
        self.write = write
        self.count += 1
    def finish(self, session: OrderSession) -> OrderWrite:
        write = self.write
        assert write is not None
        self.write = None
        write.run()
        session.complete(write)
        return write
class Observer(OrderObserver):
    def __init__(self):
        self.count = 0
    def storage_changed(self) -> None:
        self.count += 1
def drop(session: OrderSession, order: list[int]) -> None:
    session.changed(order)
    session.save(order)
def main() -> int:
    store = Store()
    driver = Driver()
    session = OrderSession(store, driver)
    assert len(session.restore([1, 2, 3])) == 3
'''


@pytest.mark.parametrize("body", [
    '''
    drop(session, [2, 1, 3])
    drop(session, [3, 2, 1])
    drop(session, [1, 3, 2])
    assert driver.count == 1
    driver.finish(session)
    assert store.saved[0] == 2 and driver.count == 2
    assert session.dirty and session.message == "Saving…"
    driver.finish(session)
    assert store.saved[1] == 3 and not session.dirty
    ''',
    '''
    drop(session, [2, 1, 3])
    drop(session, [3, 2, 1])
    session.changed([1, 3, 2])
    driver.finish(session)
    driver.finish(session)
    assert store.saved[0] == 3 and session.pending_order[0] == 1
    assert session.dirty and session.in_flight is None
    ''',
    '''
    drop(session, [2, 1, 3])
    store.fail = True
    failed = driver.finish(session)
    assert session.dirty and "write failed" in session.failure_report
    store.fail = False
    session.save(session.pending_order)
    retry = session.in_flight
    assert retry is not None
    assert retry is not failed and retry.revision == failed.revision
    session.complete(failed)
    assert session.in_flight is retry
    driver.finish(session)
    session.complete(failed)
    assert not session.dirty and session.message == ""
    ''',
    '''
    driver.fail_start = True
    drop(session, [2, 1, 3])
    assert session.dirty and session.in_flight is None
    assert "start failed" in session.message
    driver.fail_start = False
    session.save(session.pending_order)
    driver.finish(session)
    assert not session.dirty and store.saved[0] == 2
    ''',
    '''
    old = Observer()
    session.attach(old)
    drop(session, [2, 1, 3])
    session.detach(old)
    current = Observer()
    session.attach(current)
    session.detach(old)
    driver.finish(session)
    assert old.count == 2 and current.count == 2
    session.detach(current)
    assert session.observer is None
    ''',
])
def test_save_queue_matches_python(tmp_path, body):
    source = SOURCE + textwrap.indent(textwrap.dedent(body).strip(), "    ")
    assert_matches_python(source + "\n    return 42\n", tmp_path)
