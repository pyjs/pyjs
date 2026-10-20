import pytest

from tests.java.test_exceptions import assert_matches_python, run_jvm


def test_native_thread_publishes_task_state_after_join(tmp_path):
    result = run_jvm('''
        from pyjs.java.concurrent import Runnable, Thread
        class Task(Runnable):
            def __init__(self):
                self.result = 0
            def run(self) -> None:
                try:
                    raise ValueError("worker")
                except ValueError as error:
                    assert str(error) == "worker"
                    self.result = 42
        def main() -> int:
            task = Task()
            thread = Thread(task)
            thread.start()
            thread.join()
            return task.result
    ''', tmp_path)
    assert result.returncode == 42, result.stderr


def test_native_threads_do_not_share_active_python_exception_context(tmp_path):
    result = run_jvm('''
        from pyjs.java.concurrent import Runnable, Thread
        class Task(Runnable):
            def __init__(self):
                self.clean = False
            def run(self) -> None:
                try:
                    raise ValueError("worker")
                except ValueError as error:
                    self.clean = error.__context__ is None
        def main() -> int:
            try:
                raise RuntimeError("main")
            except RuntimeError as outer:
                first = Task()
                second = Task()
                left = Thread(first)
                right = Thread(second)
                left.start()
                right.start()
                left.join()
                right.join()
                assert first.clean and second.clean
                try:
                    raise ValueError("after join")
                except ValueError as error:
                    assert error.__context__ is outer
            return 42
    ''', tmp_path)
    assert result.returncode == 42, result.stderr


@pytest.mark.parametrize("name", ["notify", "notifyAll", "wait", "getClass"])
def test_python_methods_do_not_override_final_object_methods(tmp_path, name):
    assert_matches_python(f'''
        class Observer:
            def __init__(self):
                self.value = 0
            def {name}(self) -> None:
                self.value = 1
        class Updated(Observer):
            def {name}(self) -> None:
                super().{name}()
                self.value += 41
        def call(observer: Observer) -> int:
            observer.{name}()
            return observer.value
        def main() -> int:
            return call(Updated())
    ''', tmp_path)


def test_python_wait_with_timeout_does_not_call_native_monitor(tmp_path):
    assert_matches_python('''
        class Pending:
            def __init__(self):
                self.value = 0
            def wait(self, milliseconds: int) -> None:
                self.value = milliseconds
        def main() -> int:
            pending = Pending()
            pending.wait(42)
            return pending.value
    ''', tmp_path)


def test_native_callback_alias_keeps_its_declared_java_name(tmp_path):
    result = run_jvm('''
        from pyjs import jvm
        from pyjs.java.concurrent import Runnable, Thread
        from typing import cast
        @jvm.native("java/lang/Runnable", interface=True)
        class Callback:
            @jvm.native("java/lang/Runnable", name="run")
            def notify(self) -> None: ...
        class Task(Callback):
            def __init__(self):
                self.value = 0
            def notify(self) -> None:
                self.value = 42
        def main() -> int:
            task = Task()
            thread = Thread(cast(Runnable, task))
            thread.start()
            thread.join()
            return task.value
    ''', tmp_path)
    assert result.returncode == 42, result.stderr


@pytest.mark.parametrize("kind", ["ClassCastException", "SecurityException"])
def test_native_java_failure_bindings_preserve_catches_and_messages(tmp_path, kind):
    result = run_jvm(f'''
        from pyjs.java.errors import {kind}
        def main() -> int:
            try:
                raise {kind}("blocked")
            except {kind} as error:
                assert str(error) == "blocked"
                return 42
            return 1
    ''', tmp_path)
    assert result.returncode == 42, result.stderr
