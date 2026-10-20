import pytest
from pyjs.java.errors import SecurityException
from pyjs_examples.notes import android_saves as saves
from pyjs_examples.notes.android_storage import OrderSession
from pyjs_examples.notes.tests.test_android_save_queue import MemoryFile


@pytest.fixture
def runtime(monkeypatch):
    class Runtime:
        tasks = []
        callbacks = []
        accept_post = True
        fail_start = False

    runtime = Runtime()

    class Flag:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class Handler:
        def __init__(self, looper):
            pass

        def post(self, callback):
            if runtime.accept_post:
                runtime.callbacks.append(callback)
            return runtime.accept_post

    class Thread:
        def __init__(self, task):
            self.task = task

        def start(self):
            if runtime.fail_start:
                raise SecurityException("start failed")
            runtime.tasks.append(self.task)

    monkeypatch.setattr(saves, "AtomicBoolean", Flag)
    monkeypatch.setattr(saves, "Handler", Handler)
    monkeypatch.setattr(saves, "Thread", Thread)
    store = MemoryFile()
    session = OrderSession(store, saves.BackgroundSaveDriver())
    session.restore([1, 2])
    return runtime, session, store


def test_background_result_is_not_applied_until_main_thread_acknowledgement(runtime):
    host, session, store = runtime
    session.changed([2, 1])
    session.save([2, 1])
    task = host.tasks.pop()
    session.driver.poll(session)
    assert session.dirty and store.saved == []
    task.run()
    assert store.saved == [2, 1]
    assert session.dirty and session.message == "Saving…"
    host.callbacks.pop().run()
    assert not session.dirty and session.driver.task is None


@pytest.mark.parametrize("recover", ["restore", "retry"])
def test_rejected_post_is_recovered_without_repeating_the_write(runtime, recover):
    host, session, store = runtime
    host.accept_post = False
    session.changed([2, 1])
    session.save([2, 1])
    host.tasks.pop().run()
    assert session.dirty and host.callbacks == []
    if recover == "restore":
        assert session.restore([1, 2]) == [2, 1]
    else:
        session.save([2, 1])
    assert not session.dirty and store.saved == [2, 1]
    assert session.driver.task is None and host.tasks == []


def test_start_failure_clears_native_driver_and_can_retry(runtime):
    host, session, store = runtime
    host.fail_start = True
    session.changed([2, 1])
    session.save([2, 1])
    assert session.driver.task is None and session.in_flight is None
    assert session.dirty and "start failed" in session.message
    host.fail_start = False
    session.save([2, 1])
    host.tasks.pop().run()
    host.callbacks.pop().run()
    assert not session.dirty and store.saved == [2, 1]


def test_delayed_callback_after_poll_does_not_complete_the_next_write(runtime):
    host, session, store = runtime
    session.changed([2, 1])
    session.save([2, 1])
    host.tasks.pop().run()
    delayed = host.callbacks.pop()
    session.changed([1, 2])
    session.save([1, 2])
    current = session.in_flight
    delayed.run()
    assert session.in_flight is current and session.dirty
    assert store.saved == [2, 1]
    host.tasks.pop().run()
    host.callbacks.pop().run()
    assert store.saved == [1, 2] and not session.dirty
