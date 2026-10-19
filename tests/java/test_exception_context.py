from textwrap import indent

import pytest

from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exception_causes import NATIVE_IO
from tests.java.test_exceptions import run_jvm


def test_context_follows_calls_not_construction_and_restores_nested_handlers(tmp_path):
    assert_text_matches_python('''
def fail(error: RuntimeError) -> None:
    raise error

def handled() -> None:
    try:
        raise ValueError("inner")
    except ValueError:
        pass

def main() -> str:
    first = ValueError("first")
    saved = RuntimeError("saved")
    assert saved.__context__ is None
    try:
        raise first
    except ValueError:
        created = RuntimeError("constructed, not raised")
        assert created.__context__ is None
        handled()
        try:
            fail(saved)
        except RuntimeError as second:
            assert second is saved
            assert second.__context__ is first
            assert second.__cause__ is None
            assert not second.__suppress_context__
        try:
            raise RuntimeError("restored")
        except RuntimeError as restored:
            assert restored.__context__ is first
    try:
        raise RuntimeError("outside")
    except RuntimeError as outside:
        assert outside.__context__ is None
    return str(saved)
''', tmp_path)


@pytest.mark.parametrize("from_clause", ["", " from None", " from explicit"])
def test_context_is_retained_independently_of_explicit_cause_and_suppression(tmp_path, from_clause):
    assert_text_matches_python(f'''
def main() -> str:
    original = ValueError("original")
    explicit = ValueError("explicit")
    try:
        raise original
    except ValueError:
        try:
            raise RuntimeError("wrapper"){from_clause}
        except RuntimeError as wrapper:
            assert wrapper.__context__ is original
            assert wrapper.__suppress_context__ == {bool(from_clause)!r}
            assert wrapper.__cause__ is {"explicit" if from_clause == " from explicit" else "None"}
            return str(wrapper)
    return "not caught"
''', tmp_path)


@pytest.mark.parametrize("first_base", ["ValueError", "BaseException"])
def test_bare_reraise_preserves_context_but_explicit_reuse_breaks_cycles(tmp_path, first_base):
    assert_text_matches_python(f'''
def main() -> str:
    first = {first_base}("first")
    second = RuntimeError("second")
    third = TypeError("third")
    try:
        raise first
    except {first_base}:
        try:
            raise second
        except RuntimeError:
            assert second.__context__ is first
            try:
                raise third
            except TypeError:
                assert third.__context__ is second
                try:
                    raise first
                except {first_base} as reused:
                    assert reused.__context__ is third
                    assert third.__context__ is second
                    assert second.__context__ is None
                    try:
                        raise
                    except {first_base} as repeated:
                        assert repeated.__context__ is third
    try:
        raise first
    except {first_base} as outside:
        assert outside.__context__ is third
    return str(first)
''', tmp_path)


@pytest.mark.parametrize("operation", ['int("bad")', '[1][8]', '1 // 0', '{}["missing"]'])
def test_runtime_failures_capture_the_callers_active_context(tmp_path, operation):
    # Give dictionary literals a concrete item type before subscription.
    expression = 'items["missing"]' if operation.startswith("{}") else operation
    assert_text_matches_python(f'''
def fail() -> None:
    items: dict[str, str] = {{}}
    {expression}

def main() -> str:
    original = ValueError("original")
    try:
        raise original
    except ValueError:
        try:
            fail()
        except Exception as error:
            assert error.__context__ is original
            return str(original)
    return "not caught"
''', tmp_path)


def test_exceptional_finally_preserves_pending_failure_as_context(tmp_path):
    assert_text_matches_python('''
def main() -> str:
    original = ValueError("original")
    try:
        try:
            raise original
        finally:
            raise RuntimeError("cleanup")
    except RuntimeError as error:
        assert error.__context__ is original
        return str(error)
    return "not caught"
''', tmp_path)


def test_return_from_handler_restores_context_before_finally_and_caller(tmp_path):
    assert_text_matches_python('''
def finish(saved: list[RuntimeError]) -> int:
    try:
        raise ValueError("handled")
    except ValueError:
        return 42
    finally:
        try:
            raise RuntimeError("finally")
        except RuntimeError as error:
            saved.append(error)

def main() -> str:
    saved: list[RuntimeError] = []
    original = ValueError("caller")
    try:
        raise original
    except ValueError:
        assert finish(saved) == 42
        assert saved[0].__context__ is original
        try:
            raise RuntimeError("after call")
        except RuntimeError as after:
            assert after.__context__ is original
    return str(saved[0])
''', tmp_path)


def test_exceptional_exit_call_and_return_restore_dynamic_context(tmp_path):
    assert_text_matches_python('''
class Scope:
    def __enter__(self) -> None:
        pass

    def __exit__(self, kind: type[BaseException] | None,
                 error: BaseException | None, trace: object) -> bool:
        if error is not None:
            raise RuntimeError("exit failed")
        return False

def main() -> str:
    original = ValueError("body")
    try:
        with Scope():
            raise original
    except RuntimeError as error:
        assert error.__context__ is original
        return str(error)
    return "not caught"
''', tmp_path)


def test_native_failure_can_be_the_context_of_a_python_wrapper(tmp_path):
    absent = str(tmp_path / "missing" / "order.txt")
    result = run_jvm(NATIVE_IO + f'''

def main() -> int:
    try:
        Input({absent!r})
    except IOException as original:
        try:
            raise RuntimeError("read failed")
        except RuntimeError as wrapper:
            assert wrapper.__context__ is original
            assert original.__context__ is None
            return 42
    return 1
''', tmp_path)
    assert result.returncode == 42, result.stderr


@pytest.mark.parametrize("exit_statement", ["break", "continue"])
def test_loop_exit_restores_outer_handler_and_finally_context(tmp_path, exit_statement):
    assert_text_matches_python(f'''
def main() -> str:
    original = ValueError("outer")
    try:
        raise original
    except ValueError:
        for index in range(2):
            try:
                raise TypeError("inner")
            except TypeError:
                {exit_statement}
            finally:
                try:
                    raise RuntimeError("cleanup")
                except RuntimeError as cleaned:
                    assert cleaned.__context__ is original
        try:
            raise RuntimeError("after loop")
        except RuntimeError as after:
            assert after.__context__ is original
            return str(after)
    return "not caught"
''', tmp_path)


def test_unwinding_a_callee_restores_callers_handler_and_preserves_inner_context(tmp_path):
    assert_text_matches_python('''
def fail() -> None:
    try:
        raise ValueError("callee")
    except ValueError as inner:
        raise RuntimeError("failure")

def main() -> str:
    original = TypeError("caller")
    try:
        raise original
    except TypeError:
        try:
            fail()
        except RuntimeError as error:
            context = error.__context__
            assert isinstance(context, ValueError)
            assert str(context) == "callee"
            assert context.__context__ is original
        try:
            raise RuntimeError("after unwind")
        except RuntimeError as restored:
            assert restored.__context__ is original
            return str(restored)
    return "not caught"
''', tmp_path)


def test_context_is_thread_local_and_completed_calls_do_not_retain_handler_state(tmp_path):
    result = run_jvm('''
from pyjs import jvm

@jvm.native("java/lang/Runnable", interface=True)
class Runnable:
    def run(self) -> None: ...

@jvm.native("java/lang/Thread")
class Thread:
    def __init__(self, task: Runnable) -> None: ...
    def start(self) -> None: ...
    def join(self) -> None: ...

class Task(Runnable):
    def __init__(self):
        self.error = ValueError("worker")
        self.success = False

    def run(self) -> None:
        try:
            raise self.error
        except ValueError:
            assert self.error.__context__ is None
            try:
                raise RuntimeError("inside worker")
            except RuntimeError as nested:
                self.success = nested.__context__ is self.error

def main() -> int:
    caller = ValueError("main")
    try:
        raise caller
    except ValueError:
        task = Task()
        worker = Thread(task)
        worker.start()
        worker.join()
        assert task.success
        assert task.error.__context__ is None
        try:
            raise RuntimeError("main after join")
        except RuntimeError as after:
            assert after.__context__ is caller
    standalone = Task()
    standalone.run()
    assert standalone.success
    try:
        raise RuntimeError("after return")
    except RuntimeError as outside:
        assert outside.__context__ is None
    return 42
''', tmp_path)
    assert result.returncode == 42, result.stderr
    assert result.stderr == ""


def test_suppressed_exit_and_normal_finally_leave_no_active_error(tmp_path):
    assert_text_matches_python('''
class Scope:
    def __enter__(self) -> None:
        pass

    def __exit__(self, kind: type[BaseException] | None,
                 error: BaseException | None, trace: object) -> bool:
        return True

def main() -> str:
    with Scope():
        raise ValueError("suppressed")
    try:
        raise ValueError("handled")
    except ValueError:
        pass
    finally:
        try:
            raise RuntimeError("normal finally")
        except RuntimeError as error:
            assert error.__context__ is None
    try:
        raise RuntimeError("after cleanup")
    except RuntimeError as after:
        assert after.__context__ is None
        return str(after)
    return "not caught"
''', tmp_path)


@pytest.mark.parametrize("completion", ["return", 'raise RuntimeError("callback failed")'])
def test_native_callback_completion_restores_context_before_reentry(tmp_path, completion):
    # FutureTask catches callback failures in Java. Reenter before any Python
    # branch can hide stale state by reactivating the caller's handler.
    result = run_jvm(f'''
from pyjs import jvm

@jvm.native("java/lang/Runnable", interface=True)
class Runnable:
    def run(self) -> None: ...

@jvm.native("java/util/concurrent/FutureTask")
class FutureTask:
    def __init__(self, task: Runnable, result: object) -> None: ...
    def run(self) -> None: ...
    def isDone(self) -> bool: ...

class Task(Runnable):
    def run(self) -> None:
        try:
            raise ValueError("callback")
        except ValueError:
            {completion}

def capture() -> RuntimeError:
    try:
        raise RuntimeError("reentered")
    except RuntimeError as error:
        return error

def main() -> int:
    original = ValueError("caller")
    try:
        raise original
    except ValueError:
        task = FutureTask(Task(), None)
        task.run()
        after = capture()
        assert after.__context__ is original
        assert task.isDone()
    return 42
''', tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (42, "", "")


@pytest.mark.parametrize("formatter", [
    'def __str__(self) -> str | None:\n    return None',
    'def __str__(self) -> int:\n    return 42',
    'def __str__(self) -> str:\n    raise TypeError("formatter failed")',
])
def test_formatter_failures_capture_context_and_leave_the_handler_active(tmp_path, formatter):
    assert_text_matches_python(f'''
class Failure(Exception):
{indent(formatter, "    ")}

def render(error: Exception) -> str:
    return str(error)

def main() -> str:
    original = ValueError("original")
    try:
        raise original
    except ValueError:
        try:
            render(Failure())
        except TypeError as invalid:
            assert invalid.__context__ is original
        try:
            raise RuntimeError("after formatting")
        except RuntimeError as after:
            assert after.__context__ is original
    return "preserved"
''', tmp_path)


def test_unsupported_default_text_failure_keeps_context(tmp_path):
    # Opaque default text is a deliberate JVM boundary, not a CPython failure.
    result = run_jvm('''
class Failure(Exception):
    def __init__(self, values: list[int]):
        self.values = values

def main() -> int:
    original = ValueError("original")
    try:
        raise original
    except ValueError:
        try:
            str(Failure([42]))
        except TypeError as invalid:
            assert invalid.__context__ is original
            assert str(invalid) == "JVM default exception text requires scalar positional arguments"
            return 42
    return 1
''', tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (42, "", "")


@pytest.mark.parametrize(("annotation", "value"), [
    ("None", "None"), ("str", '"value"'), ("str | None", "None"),
    ("int", "42"), ("float", "1.5"), ("bool", "True"),
])
def test_every_return_storage_restores_inherited_context(tmp_path, annotation, value):
    assert_text_matches_python(f'''
def handled() -> {annotation}:
    try:
        raise ValueError("callee")
    except ValueError:
        return {value}

def main() -> str:
    caller = ValueError("caller")
    try:
        raise caller
    except ValueError:
        handled()
        try:
            raise RuntimeError("after return")
        except RuntimeError as restored:
            assert restored.__context__ is caller
    return "restored"
''', tmp_path)
