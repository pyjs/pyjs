import sys

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import CUSTOM_EXCEPTION_CONTRACT, EXCEPTION_OBJECT_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
    run_jvm,
)


@pytest.mark.parametrize("contract", [CUSTOM_EXCEPTION_CONTRACT, EXCEPTION_OBJECT_CONTRACT],
                         ids=["custom", "owned"])
def test_shared_custom_exception_contract(tmp_path, contract):
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("contract", [CUSTOM_EXCEPTION_CONTRACT, EXCEPTION_OBJECT_CONTRACT],
                         ids=["custom", "owned"])
def test_custom_exception_contract_compiles_to_android_dex(tmp_path, contract):
    assert_compiles_to_android_dex(contract.source, tmp_path)


@pytest.mark.parametrize("base", ["ValueError", "KeyError"])
@pytest.mark.parametrize("payload", ["-42", "True", "False", "int8(255)", "int64(9007199254740993)"])
def test_custom_scalar_messages_keep_python_spelling(tmp_path, base, payload):
    assert_text_matches_python(f'''
from pyjs import int8, int64

class Failure({base}):
    pass

def main() -> str:
    try:
        raise Failure({payload})
    except {base} as error:
        return str(error) + "|" + error.__str__()
    return "unhandled"
''', tmp_path)


@pytest.mark.parametrize("base", ["Exception", "KeyError"])
@pytest.mark.parametrize("multiple", [False, True], ids=["single", "tuple"])
@pytest.mark.parametrize("initialize", [False, True], ids=["original", "replaced"])
def test_nullable_boolean_original_arguments_keep_none_and_bool_text(tmp_path, base, multiple, initialize):
    assert_text_matches_python(f'''
class Failure({base}):
    def __init__(self, value: bool | None, label: str = "default"):
        self.value = value
        self.label = label
        {'super().__init__(value)' if initialize else 'pass'}

def main() -> str:
    values: list[bool | None] = [None, False, True]
    messages: list[str] = []
    for value in values:
        saved = Failure(value{', "label"' if multiple else ''})
        messages.append(str(saved))
    return "|".join(messages)
''', tmp_path)


@pytest.mark.parametrize("base", ["Exception", "ValueError", "KeyError", "BaseException"])
@pytest.mark.parametrize("arguments", ['"record", 42', '"record"', 'record="record", revision=42', ""])
def test_original_positional_arguments_exclude_defaults_and_keywords(tmp_path, base, arguments):
    assert_text_matches_python(f'''
class Failure({base}):
    def __init__(self, record: str = "untitled", revision: int = 0):
        self.record = record
        self.revision = revision

def main() -> str:
    saved = Failure({arguments})
    try:
        raise saved
    except {base} as error:
        assert error is saved
        return str(error)
    return "unhandled"
''', tmp_path)


def test_inherited_initializer_fields_and_owned_reraises(tmp_path):
    assert_text_matches_python('''
class Failure(Exception):
    def __init__(self, record: str):
        self.record = record
        super().__init__("base:" + record)

class Conflict(Failure):
    def __init__(self, record: str, revision: int):
        super().__init__(record)
        self.revision = revision

    def next_revision(self) -> int:
        return self.revision + 1

class RetryConflict(Conflict):
    pass

def make_error() -> RetryConflict:
    return RetryConflict("record", revision=42)

def main() -> str:
    saved = make_error()
    pending: list[Failure] = [saved]
    try:
        raise pending[0]
    except Failure as error:
        assert error is saved
        assert isinstance(error, RetryConflict)
        error.revision = error.next_revision()
        try:
            raise
        except Exception as repeated:
            assert repeated is saved
            return str(error) + ":" + error.record + ":" + str(error.revision)
    return "unhandled"
''', tmp_path)


def test_key_error_reinitialization_and_native_method_name_isolation(tmp_path):
    assert_text_matches_python('''
class MissingRecord(KeyError):
    def __init__(self, record: str):
        self.record = record
        super().__init__(record)

    def getMessage(self) -> int:
        return 42

    def fillInStackTrace(self) -> bool:
        return True

    def set_message(self, record: str) -> None:
        self.record = record

def main() -> str:
    saved = MissingRecord("first's title")
    before = str(saved)
    saved.__init__("second's title")
    assert saved.getMessage() == 42
    assert saved.fillInStackTrace()
    saved.set_message("field only")
    assert saved.record == "field only"
    return before + "|" + str(saved)
''', tmp_path)


def test_initializer_argument_order_and_failure_cleanup(tmp_path):
    assert_text_matches_python('''
def argument(events: list[str], value: str) -> str:
    events.append(value)
    return value

class Failure(Exception):
    def __init__(self, first: str, second: str = "default"):
        self.first = first
        if first == "fail":
            raise ValueError("initialization failed")
        super().__init__(first + ":" + second)

def main() -> str:
    events: list[str] = []
    saved = Failure(second=argument(events, "second"), first=argument(events, "first"))
    events.append(str(saved))
    events.append(str(Failure("implicit")))
    try:
        try:
            raise Failure(argument(events, "fail"))
        finally:
            events.append("cleanup")
    except ValueError as error:
        events.append(str(error))
    except Failure:
        events.append("wrong error")
    return "|".join(events)
''', tmp_path)


def test_rich_original_payload_can_be_replaced_by_initializer(tmp_path):
    assert_text_matches_python('''
class Failure(Exception):
    def __init__(self, revisions: list[int]):
        self.revisions = revisions
        super().__init__("failed")

def main() -> str:
    revisions = [1, 2]
    saved = Failure(revisions)
    revisions.append(3)
    try:
        raise saved
    except Failure as error:
        assert error.revisions is revisions
        assert error.revisions[2] == 3
        return str(error)
    return "unhandled"
''', tmp_path)


@pytest.mark.parametrize("expression", ["str(saved)", "saved.__str__()", "format_error(saved)"])
def test_custom_string_dispatch_and_super_bypass(tmp_path, expression):
    assert_text_matches_python(f'''
class Failure(Exception):
    def __init__(self, code: int):
        self.code = code

    def __str__(self) -> str:
        return "custom:" + super().__str__() + ":" + str(self.code)

class Child(Failure):
    pass

def format_error(error: Exception) -> str:
    return str(error)

def main() -> str:
    saved = Child(42)
    return {expression}
''', tmp_path)


def test_union_exception_formatting_retains_each_reached_override(tmp_path):
    assert_text_matches_python('''
class First(Exception):
    def __str__(self) -> str:
        return "first"

class Second(Exception):
    def __str__(self) -> str:
        return "second"

def message(error: First | Second) -> str:
    return str(error)

def main() -> str:
    return message(First()) + "|" + message(Second())
''', tmp_path)


@pytest.mark.parametrize(("annotation", "result"), [("int", "42"), ("str | None", "None")])
def test_invalid_string_result_raises_type_error_only_for_implicit_call(tmp_path, annotation, result):
    assert_matches_python(f'''
class Failure(Exception):
    def __str__(self) -> {annotation}:
        return {result}

def main() -> int:
    saved = Failure()
    assert saved.__str__() == {result}
    try:
        str(saved)
    except TypeError:
        return 42
    return 1
''', tmp_path)


@pytest.mark.parametrize("default", [True, False], ids=["default", "required"])
def test_formatter_parameters_preserve_explicit_calls_and_implicit_defaults(tmp_path, default):
    assert_text_matches_python(f'''
class Failure(Exception):
    def __str__(self, suffix: str{" = 'default'" if default else ""}) -> str:
        return "custom:" + suffix

def main() -> str:
    saved = Failure()
    explicit = saved.__str__("explicit")
    try:
        return explicit + "|" + str(saved)
    except TypeError:
        return explicit + "|required"
''', tmp_path)


def test_formatter_defaults_use_declared_primitive_widths(tmp_path):
    assert_text_matches_python('''
from pyjs import int8

class Failure(Exception):
    def __str__(self, tag: str = "tag", index: int = 42, flag: bool = True,
                code: int8 = 7, other: int8 = 1) -> str:
        return tag + str(index) + str(flag) + str(code) + str(other)

def main() -> str:
    return str(Failure())
''', tmp_path)


def test_custom_base_exception_is_not_caught_by_exception(tmp_path):
    assert_matches_python('''
class StopTask(BaseException):
    def __init__(self, code: int):
        self.code = code
        super().__init__(code)

def main() -> int:
    try:
        raise StopTask(42)
    except Exception:
        return 1
    except StopTask as error:
        assert str(error) == "42"
        return error.code
    return 2
''', tmp_path)


@pytest.mark.parametrize("base", ["SyntaxError", "OSError"])
@pytest.mark.parametrize("initialize", ["pass", "super().__init__(message)"])
def test_special_builtin_initializers_are_not_implicit_base_initializers(tmp_path, base, initialize):
    assert_text_matches_python(f'''
class Failure({base}):
    def __init__(self, message: str):
        self.saved = message
        {initialize}

def main() -> str:
    saved = Failure("first")
    before = str(saved)
    saved.__init__("second")
    return before + "|" + str(saved) + "|" + saved.saved
''', tmp_path)


def test_failed_reinitialization_keeps_message_and_exception_identity(tmp_path):
    assert_text_matches_python('''
def message(fail: bool) -> str:
    if fail:
        raise ValueError("conversion")
    return "saved"

class Failure(Exception):
    def __init__(self, fail: bool):
        super().__init__(message(fail))

def main() -> str:
    saved = Failure(False)
    try:
        saved.__init__(True)
    except ValueError:
        pass
    try:
        raise saved
    except Failure as error:
        assert error is saved
        return str(error)
    return "unhandled"
''', tmp_path)


def test_unused_invalid_formatter_is_not_retained(tmp_path):
    assert_matches_python('''
class Failure(Exception):
    def __init__(self, code: int):
        self.code = code

    def __str__(self) -> str:
        return not_defined

def main() -> int:
    return Failure(42).code
''', tmp_path)


def test_opaque_original_payload_only_fails_when_default_text_is_consumed(tmp_path):
    # Rich default formatting is not supported yet. Do not invent Java text,
    # reject field-only construction, or fail before an initializer replaces it.
    result = run_jvm('''
class Failure(Exception):
    def __init__(self, items: list[int]):
        self.items = items

def main() -> int:
    saved = Failure([42])
    assert saved.items[0] == 42
    try:
        str(saved)
    except TypeError as error:
        assert str(error) == "JVM default exception text requires scalar positional arguments"
        return 42
    return 1
''', tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (42, "", "")


def test_exception_formatter_reachability_is_receiver_scoped():
    # No explicit __str__ call: it would mask a missing implicit dependency.
    compilation = transpile_jvm('''
class Used(Exception):
    def __str__(self) -> str:
        return "used"

class Unused(Exception):
    def __init__(self, code: int):
        self.code = code

    def __str__(self) -> str:
        return not_defined

def format_error(error: Used) -> str:
    return str(error)

def main() -> str:
    unused = Unused(42)
    return format_error(Used()) + str(unused.code)
''')
    # Exact retained class set guards against accidental global reachability.
    assert set(compilation.classes) == {
        "PyjsProgram", "PyjsProgram$Used", "PyjsProgram$Unused",
        "PyjsProgram$exception$Exception", "PyjsProgram$exception$TypeError",
    }


@pytest.mark.parametrize("result_type, result", [("int", "42"), ("None", "None"),
                                                ("str | None", "None")])
@pytest.mark.parametrize("base", ["Exception", "Parent"])
def test_explicit_base_view_rejects_incompatible_formatter_results(base, result_type, result):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''
class Parent(Exception):
    def __str__(self) -> str:
        return "parent"
class Failure({base}):
    def __str__(self) -> {result_type}:
        return {result}
def message(error: {base}) -> str:
    return str(error.__str__())
def main() -> str:
    return message(Failure())
''')
    expected = (
        "JVM explicit exception __str__ calls require matching override result types; "
        "narrow the receiver to its concrete exception type at line 2 "
        "while compiling _pyjs_java_.message"
    )
    if base == "Parent" and result_type != "str | None":
        # User-defined base methods already enforce their JVM descriptor before
        # emitting any call. Nullable strings share a descriptor, not a type.
        expected = "JVM override Failure.__str__ must preserve the base method signature"
    assert str(caught.value) == expected


def test_explicit_base_view_does_not_apply_the_implicit_string_result_guard(tmp_path):
    assert_matches_python('''
from typing import cast
def nullable_text() -> str | None:
    return None
class Failure(Exception):
    def __str__(self) -> str:
        return cast(str, nullable_text())
def check(error: Exception) -> bool:
    return error.__str__() is None
def main() -> int:
    error = Failure()
    assert check(error)
    try:
        str(error)
    except TypeError:
        return 42
    return 0
''', tmp_path)


@pytest.mark.parametrize("body", [
    'def __init__(self, values: list[int]):\n        self.values = values',
    'def __str__(self) -> None:\n        return None',
    'def __str__(self) -> str:\n        raise ValueError("formatter failed")',
])
def test_uncaught_exceptions_preserve_type_and_trace_when_text_fails(tmp_path, body):
    argument = "[42]" if "__init__" in body else ""
    result = run_jvm(f'''
class Failure(Exception):
    {body}
def fail() -> None:
    raise Failure({argument})
def main() -> int:
    fail()
    return 0
''', tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    # Java class prefixes and line numbers vary; assert the original error and
    # its user frames, not the JVM uncaught-handler failure being fixed here.
    assert "PyjsProgram$Failure: <exception str() failed>" in result.stderr
    assert "at PyjsProgram.fail(" in result.stderr
    assert "at PyjsProgram.pyjs_main(" in result.stderr
    assert "thrown from the UncaughtExceptionHandler" not in result.stderr


def test_uncaught_custom_formatter_is_reachable_without_a_python_string_call(tmp_path):
    result = run_jvm('''
class Failure(Exception):
    def __str__(self) -> str:
        return "custom text"
def main() -> int:
    raise Failure()
''', tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "PyjsProgram$Failure: custom text" in result.stderr
    assert "at PyjsProgram.pyjs_main(" in result.stderr


def test_strict_formatting_and_safe_java_reporting_compile_to_dex(tmp_path):
    assert_compiles_to_android_dex('''
class Opaque(Exception):
    def __init__(self, values: list[int]):
        self.values = values
class Invalid(Exception):
    def __str__(self) -> None:
        return None
def main() -> int:
    errors: list[Exception] = [Opaque([42]), Invalid()]
    for error in errors:
        try:
            str(error)
        except TypeError:
            pass
    raise errors[0]
''', tmp_path)


def test_union_exception_field_access_has_a_located_boundary():
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm('''
class First(Exception):
    def __init__(self, code: int):
        self.code = code
class Second(Exception):
    def __init__(self, code: int):
        self.code = code
def read(error: First | Second) -> int:
    return error.code
def main() -> int:
    return read(First(42))
''')
    assert str(caught.value) == (
        "JVM cannot resolve field code on First|Second at line 2 "
        "while compiling _pyjs_java_.read"
    )


def test_custom_exception_identity_is_module_scoped(tmp_path, monkeypatch):
    modules = ("first_errors", "second_errors")
    for name in modules:
        (tmp_path / f"{name}.py").write_text('''
class InvalidRecord(ValueError):
    pass

def fail() -> None:
    raise InvalidRecord("invalid")
''')
    monkeypatch.syspath_prepend(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    try:
        assert_matches_python('''
from first_errors import InvalidRecord as First, fail as first
from second_errors import InvalidRecord as Second, fail as second

def main() -> int:
    score = 0
    try:
        first()
    except Second:
        return 1
    except First:
        score += 20
    try:
        second()
    except First:
        return 2
    except Second:
        score += 22
    return score
''', tmp_path)
    finally:
        for name in modules:
            sys.modules.pop(name, None)


def test_represented_custom_fields_and_context_manager_details(tmp_path):
    assert_text_matches_python('''
from pyjs import int8, int64

class Conflict(Exception):
    def __init__(self, code: int8, revision: int64):
        super().__init__(revision)
        self.code = code
        self.revision = revision

class Scope:
    def __init__(self, expected: Conflict):
        self.expected = expected

    def __enter__(self) -> None:
        pass

    def __exit__(self, kind: type[BaseException] | None,
                 value: BaseException | None, trace: object) -> bool:
        assert kind is Conflict
        assert value is self.expected
        assert trace is not None
        assert isinstance(value, Conflict)
        assert value.code == int8(-1)
        assert value.revision == int64(9007199254740993)
        return True

def main() -> str:
    saved = Conflict(int8(255), int64(9007199254740993))
    with Scope(saved):
        raise saved
    return str(saved)
''', tmp_path)


@pytest.mark.parametrize(("source", "code", "message", "help_text", "line"), [
    (
        '''class Failure(Exception):
    def __init__(self, value: int = 42):
        self.value = value
def main() -> int:
    raise Failure
''',
        "PYJS1104", "raise requires an exception instance",
        "Raise Exception or an instance of one of its subclasses.", "raise Failure",
    ),
    (
        '''class Failure(Exception):
    def __init__(self, message: str):
        BaseException.__init__(self, message)
def main() -> str:
    return str(Failure("saved"))
''',
        "PYJS1104", "__init__() received too many positional arguments",
        "Pass at most 1 positional arguments.", "BaseException.__init__(self, message)",
    ),
    (
        '''class Failure(ValueError, TypeError):
    pass
def main() -> int:
    raise Failure("failed")
''',
        "PYJS2001", "Multiple inheritance is not supported for 'Failure'",
        "Use one base class and compose the remaining behavior.", "class Failure(ValueError, TypeError):",
    ),
], ids=["type-raise", "unbound-builtin-init", "multiple-bases"])
def test_custom_exception_analysis_boundaries_are_located(source, code, message, help_text, line):
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(source, filename="custom_errors.py")
    diagnostic = caught.value.diagnostic
    assert diagnostic.code.value == code
    assert diagnostic.message == message
    assert diagnostic.help == (help_text,)
    span = diagnostic.primary.span
    assert span.source.filename.endswith("custom_errors.py")
    assert span.source.lines[span.start_position.line].strip() == line
