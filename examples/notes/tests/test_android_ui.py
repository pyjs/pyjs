from typing import cast

import pytest
from pyjs import JS, jvm
from pyjs.android import View
from pyjs.android.recycler_testing import StaggeredGridSnapshot
from pyjs.android.recyclerview import RecyclerView
from pyjs.android.testing import (
    NoMatchingViewException,
    ViewAssertion,
    application_context,
    by_id,
    by_text,
    launch,
    recreate,
    run_on_main,
)
from pyjs.android.uiautomator import find_text
from pyjs.java import format_exception, i32
from pyjs.java.concurrent import Runnable, Thread
from pyjs.java.io import File, RandomAccessFile
from pyjs_examples.notes.android import NotesActivity, NotesAdapter, NotesApplication
from pyjs_examples.notes.android_saves import BackgroundSaveDriver
from pyjs_examples.notes.android_storage import Closing, OrderFile, OrderSession, StorageError

pytestmark = [
    pytest.mark.pyjs_android_jvm,
    pytest.mark.pyjs_android_dependencies("androidx"),
]


@jvm.native("android/util/Log", name="getStackTraceString")
def android_stack_trace(error: BaseException) -> str: ...


@jvm.native("java/util/concurrent/TimeUnit")
class TimeUnit:
    pass


@jvm.native("java/util/concurrent/TimeUnit", name="valueOf")
def time_unit(name: str) -> TimeUnit: ...


@jvm.native("java/util/concurrent/CountDownLatch")
class Latch:
    def __init__(self, count: i32) -> None: ...

    def countDown(self) -> None: ...

    @jvm.native(
        "java/util/concurrent/CountDownLatch", name="await", invocation="virtual",
    )
    def await_timeout(self, timeout: int, unit: TimeUnit) -> bool: ...


@jvm.native("java/lang/Thread", name="currentThread")
def current_thread() -> Thread: ...


def test_android_log_report_preserves_implicit_exception_context() -> None:
    try:
        raise ValueError("invalid saved note")
    except ValueError:
        try:
            raise StorageError("Could not restore notes")
        except StorageError as error:
            assert len(error.args) == 1
            assert cast(str, error.args[0]) == "Could not restore notes"
            report = format_exception(error)
            assert android_stack_trace(error) == report
            assert "ValueError: invalid saved note" in report
            assert "During handling of the above exception" in report
            assert "StorageError: Could not restore notes" in report


LAUNCH_NOTE: JS = (
    "Launch checklist\n\n✓ Review the final build\n"
    "☐ Capture store screenshots\n☐ Publish the release notes"
)
WEEKEND_NOTE: JS = (
    "Weekend ideas\n\nWalk the river trail\nTry the new bakery\nCall Maya"
)


class NoteOrder(ViewAssertion):
    def __init__(self, expected: list[int], phase: str = "board") -> None:
        self.expected = expected
        self.phase = phase

    def check(
        self, view: View | None, error: NoMatchingViewException | None,
    ) -> None:
        assert error is None
        assert view is not None
        adapter = cast(RecyclerView, view).get_adapter()
        assert adapter is not None, "Notes grid has no adapter"
        if adapter is not None:
            assert adapter.get_item_count() == len(self.expected)
            order = ""
            for index in range(adapter.get_item_count()):
                order += str(adapter.get_item_id(index)) + " "
            for index in range(len(self.expected)):
                actual = adapter.get_item_id(index)
                expected = self.expected[index]
                assert actual == expected, (
                    f"{self.phase}: card {index}: expected ID {expected}, "
                    f"got {actual}; order: {order}"
                )
        snapshot = StaggeredGridSnapshot(cast(RecyclerView, view))
        assert snapshot.stable_ids
        assert not snapshot.pending_updates
        assert len(snapshot.children) > 0
        for child in snapshot.children:
            assert child.adapter_position >= 0
            assert child.item_id == self.expected[child.adapter_position]
            assert child.right > child.left and child.bottom > child.top


def order_path() -> str:
    return application_context().getFilesDir().getPath() + "/notes-order.txt"


class NewProcessSession(Runnable):
    def run(self) -> None:
        owner = cast(NotesApplication, application_context())
        owner.session = OrderSession(OrderFile(order_path()))


def reset_order() -> None:
    file = File(order_path())
    if file.exists():
        assert file.delete()
    run_on_main(NewProcessSession())


class FailOnce(OrderFile):
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.fail = True

    def write(self, order: list[int]) -> None:
        if self.fail:
            self.fail = False
            raise StorageError("Injected write failure")
        super().write(order)


class MoveAndSave(ViewAssertion):
    def __init__(self, fail: bool) -> None:
        self.fail = fail

    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        adapter = cast(NotesAdapter, cast(RecyclerView, view).get_adapter())
        session = adapter.session
        if session is None:
            raise AssertionError("Notes adapter has no storage session")
        if self.fail:
            session.store = FailOnce(session.store.path)
        adapter.move(0, 1)
        adapter.save_order()


class UnsavedSession(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        adapter = cast(NotesAdapter, cast(RecyclerView, view).get_adapter())
        owner = cast(NotesApplication, view.getContext().getApplicationContext())
        assert adapter.session is owner.session
        assert owner.session.dirty and owner.session.can_save
        assert "Injected write failure" in owner.session.failure_report


class GatedOrderFile(OrderFile):
    def __init__(self, path: str, fail: bool) -> None:
        super().__init__(path)
        self.fail = fail
        self.started = Latch(1)
        self.release = Latch(1)
        self.worker: Thread | None = None

    def write(self, order: list[int]) -> None:
        self.worker = current_thread()
        self.started.countDown()
        if not self.release.await_timeout(15, time_unit("SECONDS")):
            raise StorageError("Background test gate timed out")
        if self.fail:
            raise StorageError("Injected write failure")
        super().write(order)


class InstallBackgroundSession(Runnable):
    def __init__(self, store: GatedOrderFile) -> None:
        self.store = store

    def run(self) -> None:
        owner = cast(NotesApplication, application_context())
        owner.session = OrderSession(self.store, BackgroundSaveDriver())


class PollBackgroundSession(Runnable):
    def run(self) -> None:
        session = cast(NotesApplication, application_context()).session
        session.driver.poll(session)


def finish_background_write(store: GatedOrderFile) -> None:
    assert store.started.await_timeout(15, time_unit("SECONDS"))
    worker = store.worker
    assert worker is not None
    assert worker is not current_thread()
    store.release.countDown()
    worker.join()
    run_on_main(PollBackgroundSession())


def check_background_recreation(fail: bool) -> None:
    reset_order()
    store = GatedOrderFile(order_path(), fail)
    try:
        run_on_main(InstallBackgroundSession(store))
        launch(NotesActivity)
        by_id(100).check(MoveAndSave(False))
        assert store.started.await_timeout(15, time_unit("SECONDS"))
        by_id(101).assert_text("Saving…")
        recreate()
        by_id(100).check(NoteOrder(
            [1002, 1001, 1003, 1004, 1005, 1006, 1007], "background recreation",
        ))
        by_id(101).assert_text("Saving…")
        finish_background_write(store)
        if fail:
            by_id(100).check(UnsavedSession())
            by_id(101).assert_text("Order not saved. Tap to retry. Injected write failure")
            assert not File(order_path()).exists()
            store.fail = False
            store.started = Latch(1)
            by_id(101).click()
            finish_background_write(store)
        by_id(101).assert_text("")
        run_on_main(NewProcessSession())
        launch(NotesActivity)
        by_id(100).check(NoteOrder(
            [1002, 1001, 1003, 1004, 1005, 1006, 1007], "background saved order",
        ))
    finally:
        store.release.countDown()
        worker = store.worker
        if worker is not None:
            worker.join()
        run_on_main(PollBackgroundSession())
        reset_order()


def test_background_write_completes_after_activity_recreation() -> None:
    check_background_recreation(False)


def test_background_write_failure_retries_after_activity_recreation() -> None:
    check_background_recreation(True)


def test_grid_displays_sample_cards_in_adapter_order() -> None:
    reset_order()
    launch(NotesActivity)
    by_id(100).assert_displayed()
    by_id(100).check(NoteOrder([1001, 1002, 1003, 1004, 1005, 1006, 1007]))
    by_text(LAUNCH_NOTE).assert_displayed()
    by_text(WEEKEND_NOTE).assert_displayed()


@pytest.mark.pyjs_android_device
def test_long_press_drag_reorders_cards_and_can_move_them_back() -> None:
    reset_order()
    launch(NotesActivity)
    # ItemTouchHelper requires crossing the target edge, not just aligning it.
    find_text(LAUNCH_NOTE).drag_to(find_text(WEEKEND_NOTE), 1_000, 32, 0)

    by_id(100).check(NoteOrder([1002, 1001, 1003, 1004, 1005, 1006, 1007], "after drag"))
    by_text(LAUNCH_NOTE).assert_displayed()
    by_text(WEEKEND_NOTE).assert_displayed()
    recreate()
    by_id(100).check(NoteOrder([1002, 1001, 1003, 1004, 1005, 1006, 1007], "after recreation"))

    find_text(LAUNCH_NOTE).drag_to(find_text(WEEKEND_NOTE), 1_000, -32, 0)

    by_id(100).check(NoteOrder([1001, 1002, 1003, 1004, 1005, 1006, 1007], "after reverse drag"))
    by_text(LAUNCH_NOTE).assert_displayed()
    by_text(WEEKEND_NOTE).assert_displayed()
    reset_order()


def test_saved_order_survives_activity_recreation() -> None:
    reset_order()
    try:
        launch(NotesActivity)
        by_id(100).check(MoveAndSave(False))
        recreate()
        by_id(100).check(NoteOrder([1002, 1001, 1003, 1004, 1005, 1006, 1007]))
    finally:
        reset_order()


def test_failed_save_keeps_board_and_retries_from_the_status_message() -> None:
    reset_order()
    try:
        launch(NotesActivity)
        by_id(100).check(MoveAndSave(True))
        by_id(101).assert_text("Order not saved. Tap to retry. Injected write failure")
        by_id(100).check(NoteOrder([1002, 1001, 1003, 1004, 1005, 1006, 1007], "after failed save"))
        by_id(101).click()
        by_id(101).assert_text("")
        recreate()
        by_id(100).check(NoteOrder([1002, 1001, 1003, 1004, 1005, 1006, 1007], "after retry and recreate"))
    finally:
        reset_order()


def test_unsaved_order_and_retry_survive_repeated_activity_recreation() -> None:
    reset_order()
    try:
        launch(NotesActivity)
        by_id(100).check(MoveAndSave(True))
        for attempt in range(2):
            recreate()
            by_id(100).check(NoteOrder(
                [1002, 1001, 1003, 1004, 1005, 1006, 1007],
                f"pending recreation {attempt}",
            ))
            by_id(100).check(UnsavedSession())
            by_id(101).assert_text("Order not saved. Tap to retry. Injected write failure")
        assert not File(order_path()).exists()
        by_id(101).click()
        by_id(101).assert_text("")
        run_on_main(NewProcessSession())
        launch(NotesActivity)
        by_id(100).check(NoteOrder(
            [1002, 1001, 1003, 1004, 1005, 1006, 1007], "fresh owner after retry",
        ))
    finally:
        reset_order()


def test_unsaved_state_is_process_local_and_does_not_replace_saved_snapshot() -> None:
    reset_order()
    try:
        launch(NotesActivity)
        by_id(100).check(MoveAndSave(False))
        by_id(100).check(MoveAndSave(True))
        recreate()
        by_id(100).check(NoteOrder(
            [1001, 1002, 1003, 1004, 1005, 1006, 1007], "pending over saved",
        ))
        by_id(100).check(UnsavedSession())
        run_on_main(NewProcessSession())
        launch(NotesActivity)
        by_id(100).check(NoteOrder(
            [1002, 1001, 1003, 1004, 1005, 1006, 1007], "fresh owner before retry",
        ))
        by_id(101).assert_text("")
    finally:
        reset_order()


def test_invalid_saved_order_shows_warning_and_does_not_overwrite() -> None:
    reset_order()
    try:
        with Closing(RandomAccessFile(order_path(), "rw")) as stream:
            stream.writeBytes("1001\n1001\n")
        launch(NotesActivity)
        by_id(101).assert_text("Could not load saved order: Saved order contains an invalid or duplicate note")
        by_id(101).assert_displayed()
        by_id(100).check(NoteOrder([1001, 1002, 1003, 1004, 1005, 1006, 1007]))
        by_id(100).check(MoveAndSave(False))
        with Closing(RandomAccessFile(order_path(), "r")) as saved:
            assert saved.readLine() == "1001"
            assert saved.readLine() == "1001"
            assert saved.readLine() is None
    finally:
        reset_order()
