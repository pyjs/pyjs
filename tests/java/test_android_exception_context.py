"""Dynamic handled state on Robolectric and the device's ART runtime."""

import pytest

from pyjs import jvm
from pyjs.java import i32

pytestmark = pytest.mark.pyjs_android_jvm


def fail() -> None:
    raise RuntimeError("helper")


def finish(saved: list[RuntimeError]) -> int:
    try:
        raise ValueError("callee")
    except ValueError:
        return 42
    finally:
        try:
            fail()
        except RuntimeError as error:
            saved.append(error)


def test_calls_and_abrupt_cleanup_restore_the_enclosing_handler() -> None:
    saved: list[RuntimeError] = []
    original = ValueError("caller")
    try:
        raise original
    except ValueError:
        assert finish(saved) == 42
        assert saved[0].__context__ is original
        try:
            fail()
        except RuntimeError as restored:
            assert restored.__context__ is original
    try:
        fail()
    except RuntimeError as outside:
        assert outside.__context__ is None


def test_reuse_breaks_implicit_cycles_without_changing_explicit_cause() -> None:
    first = BaseException("first")
    second = RuntimeError("second")
    try:
        raise first
    except BaseException:
        try:
            raise second from None
        except RuntimeError:
            assert second.__context__ is first
            assert second.__cause__ is None
            assert second.__suppress_context__
            try:
                raise first from first
            except BaseException as reused:
                assert reused.__context__ is second
                assert reused.__cause__ is first
                assert second.__context__ is None
                try:
                    raise
                except BaseException as repeated:
                    assert repeated.__context__ is second


@jvm.native("java/lang/Integer", name="parseInt")
def parse(value: str) -> i32: ...


class InvalidText(Exception):
    def __str__(self) -> str | None:
        return None


def test_native_and_runtime_failures_retain_the_original_context() -> None:
    try:
        parse("invalid")
    except Exception as native:
        assert native.__context__ is None
        try:
            str(InvalidText())
        except TypeError as formatting:
            assert formatting.__context__ is native
        try:
            int("invalid")
        except ValueError as conversion:
            assert conversion.__context__ is native
        try:
            raise RuntimeError("wrapped") from native
        except RuntimeError as wrapped:
            assert wrapped.__context__ is native
            assert wrapped.__cause__ is native


@jvm.native("java/lang/Runnable", interface=True)
class Runnable:
    def run(self) -> None: ...


@jvm.native("java/lang/Thread")
class Thread:
    def __init__(self, task: Runnable) -> None: ...

    def start(self) -> None: ...

    def join(self) -> None: ...


class Worker(Runnable):
    def __init__(self):
        self.isolated = False
        self.restored = False

    def run(self) -> None:
        try:
            fail()
        except RuntimeError as error:
            self.isolated = error.__context__ is None
        try:
            fail()
        except RuntimeError as error:
            self.restored = error.__context__ is None


def test_worker_thread_does_not_inherit_a_callers_exception() -> None:
    original = ValueError("caller")
    try:
        raise original
    except ValueError:
        task = Worker()
        thread = Thread(task)
        thread.start()
        thread.join()
        assert task.isolated and task.restored
        try:
            fail()
        except RuntimeError as restored:
            assert restored.__context__ is original
