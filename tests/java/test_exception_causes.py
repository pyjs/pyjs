import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import run_jvm

NATIVE_IO = '''
from pyjs import jvm

@jvm.native("java/io/IOException")
class IOException(Exception):
    pass

@jvm.native("java/io/FileInputStream")
class Input:
    def __init__(self, path: str):
        try:
            with open(path, "rb"):
                pass
        except OSError as error:
            raise IOException(str(error))
'''

NATIVE_CAUSES = '''
from pyjs import jvm
from pyjs.java import i32

@jvm.native("java/lang/NumberFormatException")
class NativeFailure(Exception):
    pass

@jvm.native("java/lang/Integer", name="parseInt")
def parse(value: str) -> i32:
    raise NativeFailure("invalid")

@jvm.native("java/lang/RuntimeException")
class NativeWrapper(Exception):
    def __init__(self, cause: BaseException):
        super().__init__("native wrapper")
        # Model Java construction without Python's implicit suppression bit.
        # setattr avoids declaring fake Java fields in the native fixture.
        setattr(self, "__cause__", cause)
        setattr(self, "__suppress_context__", False)

    def getCause(self) -> BaseException | None:
        return self.__cause__

class ChildWrapper(NativeWrapper):
    def __init__(self, cause: BaseException):
        super().__init__(cause)

class GrandchildWrapper(ChildWrapper):
    pass
'''


@pytest.mark.parametrize("base", ["Exception", "BaseException", "ValueError"])
def test_explicit_cause_identity_replacement_suppression_and_reraise(tmp_path, base):
    assert_text_matches_python(f'''
class StorageError({base}):
    pass

def main() -> str:
    error = StorageError("save failed")
    first = ValueError("original")
    second = RuntimeError("replacement")
    assert error.__cause__ is None
    assert not error.__suppress_context__
    try:
        raise error from first
    except {base} as caught:
        assert caught is error
        assert caught.__cause__ is first
        assert caught.__suppress_context__
        try:
            raise
        except {base} as repeated:
            assert repeated is error
            assert repeated.__cause__ is first
        try:
            raise caught from second
        except {base} as replaced:
            assert replaced.__cause__ is second
    try:
        raise error from error
    except {base} as cycle:
        assert cycle.__cause__ is cycle
    try:
        raise error from None
    except {base} as suppressed:
        assert suppressed.__cause__ is None
        assert suppressed.__suppress_context__
    return str(error)
''', tmp_path)


@pytest.mark.parametrize("cause", ["42", "ValueError"])
def test_invalid_cause_has_a_focused_diagnostic(cause):
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(f'def main() -> int:\n    raise RuntimeError("bad") from {cause}\n')
    error = caught.value
    assert error.diagnostic.code == "PYJS1104"
    assert error.diagnostic.message == "exception cause requires an exception instance or None"
    assert (error.lineno, error.offset) == (2, 36)
    assert error.diagnostic.help == ("Construct the cause exception or use 'from None'.",)


@pytest.mark.parametrize(("attribute", "value"), [
    ("__context__", 'ValueError("context")'),
    ("__cause__", "None"), ("__suppress_context__", "True"),
])
def test_chaining_attributes_reject_assignment_until_writable_support(attribute, value):
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(f'''
def main() -> int:
    error = RuntimeError("saved")
    error.{attribute} = {value}
    return 0
''')
    assert caught.value.diagnostic.code == "PYJS1103"
    assert caught.value.diagnostic.message == f"Property '{attribute}' is read-only"
    assert caught.value.lineno == 4


def test_cause_evaluation_order_and_failed_expressions_leave_old_cause_intact(tmp_path):
    assert_text_matches_python('''
def target(events: list[str], error: RuntimeError) -> RuntimeError:
    events.append("target")
    return error

def cause(events: list[str], fail: bool) -> ValueError | None:
    events.append("cause")
    if fail:
        raise ValueError("cause failed")
    return None

def bad_target(events: list[str]) -> RuntimeError:
    events.append("bad target")
    raise ValueError("target failed")

def main() -> str:
    events: list[str] = []
    error = RuntimeError("saved")
    original = ValueError("original")
    try:
        raise error from original
    except RuntimeError:
        pass
    try:
        raise target(events, error) from cause(events, True)
    except ValueError as failed:
        events.append(str(failed))
    assert error.__cause__ is original
    try:
        raise bad_target(events) from cause(events, False)
    except ValueError as failed_target:
        events.append(str(failed_target))
    try:
        raise target(events, error) from cause(events, False)
    except RuntimeError as suppressed:
        assert suppressed is error
        assert suppressed.__cause__ is None
        assert suppressed.__suppress_context__
    return "|".join(events)
''', tmp_path)


def test_cause_factory_is_reachable_and_nullable_cause_can_hold_an_exception(tmp_path):
    assert_text_matches_python('''
def cause(present: bool) -> BaseException | None:
    return ValueError("original") if present else None

def main() -> str:
    try:
        raise RuntimeError("wrapper") from cause(True)
    except RuntimeError as error:
        original = error.__cause__
        assert isinstance(original, ValueError)
        return str(original)
    return "not caught"
''', tmp_path)


def test_union_causes_and_inherited_property_access(tmp_path):
    assert_text_matches_python('''
def original(first: bool) -> ValueError | RuntimeError:
    return ValueError("value") if first else RuntimeError("runtime")

def has_no_chain(error: ValueError | RuntimeError) -> bool:
    return error.__cause__ is None and not error.__suppress_context__

def main() -> str:
    cause = original(False)
    assert has_no_chain(cause)
    try:
        raise RuntimeError("wrapper") from cause
    except RuntimeError as wrapper:
        assert wrapper.__cause__ is cause
        assert not has_no_chain(wrapper)
        return str(cause)
    return "not caught"
''', tmp_path)


def test_context_exit_observes_cause_and_can_suppress_the_wrapper(tmp_path):
    assert_text_matches_python('''
class Scope:
    def __init__(self, cause: ValueError):
        self.cause = cause
        self.exited = False

    def __enter__(self) -> None:
        pass

    def __exit__(self, kind: type[BaseException] | None,
                 error: BaseException | None, trace: object) -> bool:
        assert isinstance(error, BaseException)
        assert error.__cause__ is self.cause
        assert error.__suppress_context__
        self.exited = True
        return True

def main() -> str:
    original = ValueError("disk")
    scope = Scope(original)
    with scope:
        raise RuntimeError("save") from original
    assert scope.exited
    return "suppressed"
''', tmp_path)


def test_reinitialization_and_plain_raise_keep_cause_and_native_method_names_separate(tmp_path):
    assert_text_matches_python('''
class Failure(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message)

    def getCause(self) -> str:
        return "user method"

    def set_cause(self) -> str:
        return "user setter"

def main() -> str:
    error = Failure("first")
    original = ValueError("original")
    try:
        raise error from original
    except Failure:
        pass
    error.__init__("second")
    try:
        raise error
    except Failure as again:
        assert again.__cause__ is original
        assert again.__suppress_context__
        return str(again) + ":" + again.getCause() + ":" + again.set_cause()
    return "not caught"
''', tmp_path)


def test_uncaught_cause_is_visible_in_java_stack_trace(tmp_path):
    result = run_jvm('''
def original() -> ValueError:
    return ValueError("underlying failure")

def main() -> int:
    raise RuntimeError("save failed") from original()
''', tmp_path)
    assert result.returncode != 0
    # Java stack trace paths and generated class names vary with the source.
    assert "RuntimeError: save failed" in result.stderr
    assert "The above exception was the direct cause of the following exception:" in result.stderr
    assert "ValueError: underlying failure" in result.stderr


def test_native_io_failure_remains_the_original_cause(tmp_path):
    absent = str(tmp_path / "missing" / "order.txt")
    result = run_jvm(NATIVE_IO + f'''
def main() -> int:
    try:
        Input({absent!r})
    except IOException as original:
        try:
            raise RuntimeError("read failed") from original
        except RuntimeError as wrapper:
            cause = wrapper.__cause__
            assert cause is original
            assert isinstance(cause, IOException)
            assert str(cause) == str(original)
            assert not cause.__suppress_context__
            return 42
    return 1
''', tmp_path)
    assert result.returncode == 42, result.stderr


@pytest.mark.parametrize("kind", ["NativeWrapper", "ChildWrapper", "GrandchildWrapper"])
def test_native_exception_cannot_be_an_explicit_cause_target(kind):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(NATIVE_CAUSES + f'''
def main() -> None:
    error = {kind}(ValueError("leaf"))
    raise error from None
''')
    assert str(caught.value) == (
        "JVM explicit causes require a Python exception; wrap the native failure"
        " at line 3 while compiling _pyjs_java_.main"
    )


def test_widened_native_cause_target_has_a_python_failure_not_a_java_cast_error(tmp_path):
    absent = str(tmp_path / "missing" / "order.txt")
    result = run_jvm(NATIVE_IO + f'''
def main() -> int:
    try:
        Input({absent!r})
    except Exception as error:
        try:
            raise error from None
        except TypeError as invalid:
            assert str(invalid) == "explicit causes require a Python exception; wrap the native failure"
            return 42
    return 1
''', tmp_path)
    assert result.returncode == 42, result.stderr


@pytest.mark.parametrize("kind", ["NativeWrapper", "ChildWrapper", "GrandchildWrapper"])
@pytest.mark.parametrize("chained", [False, True], ids=["plain-raise", "cause"])
def test_foreign_causes_retain_their_own_native_chain(tmp_path, kind, chained):
    statement = 'raise RuntimeError("outer") from original' if chained else 'raise original'
    checks = '''
        assert caught.__cause__ is original
        assert caught.__suppress_context__
''' if chained else '''
        assert caught is original
'''
    assert_text_matches_python(NATIVE_CAUSES + f'''
def main() -> str:
    leaf = ValueError("leaf")
    original = {kind}(leaf)
    try:
        {statement}
    except Exception as caught:
        assert original.__cause__ is leaf
        assert original.getCause() is leaf
        assert not original.__suppress_context__
{checks}
    return "preserved"
''', tmp_path)


def test_native_thrown_cause_preserves_identity_and_category(tmp_path):
    assert_text_matches_python(NATIVE_CAUSES + '''
def main() -> str:
    try:
        parse("invalid")
    except NativeFailure as original:
        try:
            raise RuntimeError("outer") from original
        except RuntimeError as caught:
            assert caught.__cause__ is original
            assert isinstance(caught.__cause__, NativeFailure)
            assert not original.__suppress_context__
            return "preserved"
    return "unreachable"
''', tmp_path)


def test_cause_only_factory_retains_custom_java_reporting(tmp_path):
    result = run_jvm('''
class Original(ValueError):
    def __str__(self) -> str:
        return "custom underlying text"

class Wrapper(RuntimeError):
    def __str__(self) -> str:
        return "custom outer text"

def cause() -> Exception:
    return Original("raw cause")

def main() -> int:
    raise Wrapper("raw wrapper") from cause()
''', tmp_path)
    assert result.returncode != 0
    # Java stack trace paths/class names vary; only the text is contractual.
    assert ": custom outer text" in result.stderr
    assert "The above exception was the direct cause of the following exception:" in result.stderr
    assert ": custom underlying text" in result.stderr
    assert "raw cause" not in result.stderr


@pytest.mark.parametrize("kind", ["NativeWrapper", "ChildWrapper", "GrandchildWrapper"])
def test_widened_foreign_target_evaluates_cause_before_rejecting(tmp_path, kind):
    result = run_jvm(NATIVE_CAUSES + f'''
def cause(events: list[str]) -> ValueError:
    events.append("evaluated")
    return ValueError("new")

def attach(error: Exception, events: list[str]) -> None:
    raise error from cause(events)

def main() -> int:
    leaf = ValueError("old")
    error = {kind}(leaf)
    events: list[str] = []
    try:
        attach(error, events)
    except TypeError as rejected:
        assert str(rejected) == "explicit causes require a Python exception; wrap the native failure"
        assert len(events) == 1
        assert error.__cause__ is leaf
        assert not error.__suppress_context__
        return 42
    return 1
''', tmp_path)
    # Deliberate foreign-layout boundary, not a CPython semantic claim.
    assert result.returncode == 42, result.stderr


def test_two_object_cause_cycle_terminates_java_reporting(tmp_path):
    result = run_jvm('''
def main() -> int:
    first = RuntimeError("first")
    second = ValueError("second")
    try:
        raise first from second
    except RuntimeError:
        pass
    raise second from first
''', tmp_path)
    assert result.returncode != 0
    # Python-style cycle truncation emits each error once, oldest first.
    assert result.stderr.count("RuntimeError: first") == 1
    assert result.stderr.count("ValueError: second") == 1
    assert result.stderr.index("RuntimeError: first") < result.stderr.index("ValueError: second")
    assert result.stderr.count("The above exception was the direct cause") == 1


@pytest.mark.parametrize("fail_target", [False, True])
@pytest.mark.parametrize("condition", [False, True])
@pytest.mark.parametrize("conditional_target", [False, True])
def test_conditional_cause_is_evaluated_after_the_target(
        tmp_path, fail_target, condition, conditional_target):
    target = f'target(events, {fail_target})'
    if conditional_target:
        target = f'({target} if choose(events, "target condition") else {target})'
    assert_text_matches_python(f'''
def target(events: list[str], fail: bool) -> ValueError:
    events.append("target")
    if fail:
        raise TypeError("target failed")
    return ValueError("wrapper")

def choose(events: list[str], label: str) -> bool:
    events.append(label)
    return {condition}

def cause(events: list[str], label: str) -> RuntimeError:
    events.append(label)
    return RuntimeError(label)

def main() -> str:
    events: list[str] = []
    try:
        raise {target} from (
            cause(events, "yes") if choose(events, "cause condition")
            else cause(events, "no")
        )
    except (ValueError, TypeError):
        pass
    return "|".join(events)
''', tmp_path)


@pytest.mark.parametrize("annotation", ["NoneType", "NoneType | None", "ValueError | NoneType"])
def test_application_nonetype_name_is_not_a_valid_cause(annotation):
    source = f'''
class NoneType:
    pass

def invalid() -> {annotation}:
    return NoneType()

def main() -> None:
    raise RuntimeError("wrapper") from invalid()
'''
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(source)
    error = caught.value
    assert error.diagnostic.code == "PYJS1104"
    assert error.diagnostic.message == "exception cause requires an exception instance or None"
    assert error.diagnostic.help == ("Construct the cause exception or use 'from None'.",)
    assert (error.lineno, error.offset) == (9, 40)


def test_application_nonetype_instance_cannot_reach_bytecode_emission():
    with pytest.raises(CompilationError) as caught:
        transpile_jvm('''
class NoneType:
    pass
def main() -> None:
    raise RuntimeError("wrapper") from NoneType()
''')
    error = caught.value
    assert error.diagnostic.code == "PYJS1104"
    assert error.diagnostic.message == "exception cause requires an exception instance or None"
    assert error.diagnostic.help == ("Construct the cause exception or use 'from None'.",)
    assert (error.lineno, error.offset) == (5, 40)


JAVA_CAUSE_ACCESS = '''
from typing import cast
from pyjs import jvm

@jvm.native("java/lang/Throwable")
class Throwable(BaseException):
    def initCause(self, cause: BaseException) -> BaseException: ...
    def getCause(self) -> BaseException | None: ...

class CustomFailure(RuntimeError):
    pass
'''


@pytest.mark.parametrize("kind", ["BaseException", "RuntimeError", "CustomFailure"])
def test_java_cause_is_visible_until_python_explicitly_replaces_or_clears_it(tmp_path, kind):
    result = run_jvm(JAVA_CAUSE_ACCESS + f'''
def main() -> int:
    original = ValueError("java")
    error = {kind}("wrapper")
    native = cast(Throwable, error)
    assert native.initCause(original) is error
    assert native.getCause() is original
    assert error.__cause__ is original
    assert not error.__suppress_context__
    replacement = ValueError("python")
    try:
        raise error from replacement
    except {kind}:
        assert native.getCause() is replacement
        assert error.__cause__ is replacement
        assert error.__suppress_context__
    try:
        raise error from None
    except {kind}:
        assert native.getCause() is None
        assert error.__cause__ is None
        assert error.__suppress_context__
    return 42
''', tmp_path)
    assert result.returncode == 42, result.stderr


@pytest.mark.parametrize("kind", ["BaseException", "RuntimeError"])
def test_java_cause_checks_and_uncaught_reporting_preserve_cause(tmp_path, kind):
    result = run_jvm(JAVA_CAUSE_ACCESS + f'''
def main() -> int:
    error = {kind}("wrapper")
    native = cast(Throwable, error)
    try:
        native.initCause(error)
        return 1
    except Exception:
        assert native.getCause() is None
    original = ValueError("java cause")
    native.initCause(original)
    try:
        native.initCause(ValueError("second"))
        return 2
    except Exception:
        assert native.getCause() is original
    raise error
''', tmp_path)
    assert result.returncode != 0
    # Java owns frame formatting, self-cycle and one-shot initCause checks.
    assert "The above exception was the direct cause of the following exception:" in result.stderr
    assert "ValueError: java cause" in result.stderr
