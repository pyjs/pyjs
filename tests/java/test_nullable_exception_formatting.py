"""Nullable exception formatting must dispatch on the value, not only its ABI."""

import ast

import pytest

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.source import analyze_source
from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.analysis import JVM_ENVIRONMENT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)

EXCEPTION_TYPES = '''
class Failure(Exception):
    def __str__(self) -> str:
        return "custom:" + super().__str__()

class Child(Failure):
    pass

class StopTask(BaseException):
    def __str__(self) -> str:
        return "stop:" + super().__str__()
'''


@pytest.mark.parametrize("kind", [
    "Exception", "BaseException", "ValueError", "KeyError", "Failure", "Child", "StopTask",
])
@pytest.mark.parametrize("formatting", [
    "str(create(calls, present))",
    'f"{create(calls, present)}"',
    'f"{create(calls, present)!s}"',
    "create(calls, present).__str__()",
], ids=["str", "interpolation", "str-conversion", "explicit"])
def test_nullable_exception_formatting_preserves_value_and_single_evaluation(
    tmp_path, kind, formatting,
):
    assert_text_matches_python(EXCEPTION_TYPES + f'''
def create(calls: list[bool], present: bool) -> {kind} | None:
    calls.append(present)
    return {kind}("message") if present else None

def main() -> str:
    calls: list[bool] = []
    result = ""
    for present in [True, False]:
        result += {formatting} + "|"
    assert len(calls) == 2
    assert calls[0] and not calls[1]
    return result
''', tmp_path)


@pytest.mark.parametrize("formatting", ["str(error)", 'f"{error}"', "error.__str__()"])
@pytest.mark.parametrize("view", [
    "Exception", "Failure | Child", "BaseException", "Failure | StopTask", "ValueError | Failure",
])
def test_nullable_base_and_union_views_retain_custom_dispatch(tmp_path, formatting, view):
    assert_text_matches_python(EXCEPTION_TYPES + f'''
def create(present: bool) -> {view} | None:
    if present:
        return Child("saved")
    return None

def main() -> str:
    result = ""
    for present in [True, False]:
        error = create(present)
        result += {formatting} + "|"
    return result
''', tmp_path)


def test_nullable_interpolation_lowers_to_str_with_scoped_protocols():
    source = EXCEPTION_TYPES + '''
def main(error: None | Child) -> str:
    return f"{error}"
'''
    with analyze_source(source, wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        calls = [
            node for block in analysis.entry_point.ir.blocks for node in ast.walk(block)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert len(calls) == 1
        call = calls[0]
        assert call.func.id == "str" and call.keywords == []
        assert len(call.args) == 1 and call.args[0].id == "error"
        assert analyzed_value_type(call).name == "str"
        assert [(member.name, methods) for member, methods in call.runtime_protocols] == [
            ("Child", ("__str__",)),
        ]


@pytest.mark.parametrize("formatting", ["str(error)", 'f"{error}"', "error.__str__()"])
def test_nullable_exception_fields_and_list_items(tmp_path, formatting):
    assert_text_matches_python(EXCEPTION_TYPES + f'''
class Saved:
    def __init__(self, error: None | Child):
        self.error = error

def main() -> str:
    result = ""
    for saved in [Saved(None), Saved(Child("saved"))]:
        error = saved.error
        result += {formatting} + "|"
    for error in [None, Child("item")]:
        result += {formatting} + "|"
    return result
''', tmp_path)


@pytest.mark.parametrize("formatting", ["str(error)", 'f"{error}"', "error.__str__()"])
def test_nullable_foreign_exception_uses_native_message(tmp_path, formatting):
    assert_text_matches_python(f'''
from pyjs import jvm

@jvm.native("java/lang/RuntimeException")
class NativeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)

def create(present: bool) -> NativeError | None:
    return NativeError("foreign") if present else None

def main() -> str:
    result = ""
    for present in [True, False]:
        error = create(present)
        result += {formatting} + "|"
    return result
''', tmp_path)


@pytest.mark.parametrize("view", ["Failure", "Child"])
def test_nullable_native_subclass_explicit_formatter_keeps_python_dispatch(tmp_path, view):
    assert_text_matches_python(f'''
from pyjs import jvm

@jvm.native("java/lang/RuntimeException")
class NativeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)

class Failure(NativeError):
    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self) -> str:
        return "custom"

class Child(Failure):
    def __str__(self) -> str:
        return "child"

def create(present: bool) -> {view} | None:
    return Child("native message") if present else None

def main() -> str:
    result = ""
    for present in [True, False]:
        result += create(present).__str__() + "|"
    return result
''', tmp_path)


@pytest.mark.parametrize("formatting", ["str(error)", 'f"{error}"'])
def test_nullable_implicit_formatting_preserves_invalid_result_guard(tmp_path, formatting):
    assert_matches_python(f'''
class Failure(Exception):
    def __str__(self) -> int:
        return 42

def create(present: bool) -> Failure | None:
    return Failure() if present else None

def main() -> int:
    for present in [False, True]:
        error = create(present)
        try:
            assert {formatting} == "None"
        except TypeError:
            assert present
            return 42
    return 0
''', tmp_path)


def test_nullable_explicit_call_keeps_null_formatter_result(tmp_path):
    assert_matches_python('''
from typing import cast

def empty_text() -> str | None:
    return None

class Failure(Exception):
    def __str__(self) -> str:
        return cast(str, empty_text())

def create(present: bool) -> Failure | None:
    return Failure() if present else None

def main() -> int:
    assert create(False).__str__() == "None"
    assert create(True).__str__() is None
    return 42
''', tmp_path)


def test_nullable_explicit_nonstring_result_requires_narrowing():
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm('''
class Failure(Exception):
    def __str__(self) -> int:
        return 42
def format_error(error: Failure | None) -> None:
    error.__str__()
def main() -> int:
    format_error(None)
    return 42
''')
    assert str(caught.value) == (
        "JVM nullable exception __str__ calls require a string result; "
        "narrow the receiver to its concrete exception type at line 2 "
        "while compiling _pyjs_java_.format_error"
    )


@pytest.mark.parametrize("formatting", ["str(error)", 'f"{error}"', "error.__str__()"])
def test_unrelated_union_members_keep_a_focused_formatting_boundary(formatting):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''
def format_error(error: Exception | str | None) -> str:
    return {formatting}
def main() -> str:
    return format_error(None)
''')
    assert str(caught.value) == (
        "JVM string conversion requires str, int, or bool at line 2 "
        "while compiling _pyjs_java_.format_error"
    )


@pytest.mark.parametrize("formatting", ["str(error)", 'f"{error}"', "error.__str__()"])
def test_nullable_custom_formatter_defaults_and_raised_errors(tmp_path, formatting):
    assert_text_matches_python(f'''
class Failure(Exception):
    def __init__(self, calls: list[str], fail: bool):
        self.calls = calls
        self.fail = fail

    def __str__(self, suffix: str = "default") -> str:
        self.calls.append(suffix)
        if self.fail:
            raise ValueError("format failed")
        return suffix

def format_error(error: Failure | None) -> str:
    return {formatting}

def main() -> str:
    calls: list[str] = []
    assert format_error(None) == "None"
    assert len(calls) == 0
    result = format_error(Failure(calls, False))
    try:
        format_error(Failure(calls, True))
    except ValueError as caught:
        result += "|" + str(caught)
    assert len(calls) == 2
    assert calls[0] == "default" and calls[1] == "default"
    return result
''', tmp_path)


def test_nullable_formatting_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(EXCEPTION_TYPES + '''
from pyjs import jvm

@jvm.native("java/lang/RuntimeException")
class NativeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)

class NativeChild(NativeError):
    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self) -> str:
        return "native override"

def native(present: bool) -> NativeChild | None:
    return NativeChild("native") if present else None

def create(present: bool) -> Exception | None:
    return Child("saved") if present else None

def concrete(present: bool) -> Child | None:
    return Child("concrete") if present else None

def main() -> str:
    result = ""
    for present in [True, False]:
        error = create(present)
        result += str(error) + f"{error}" + error.__str__()
        child = concrete(present)
        result += str(child) + f"{child}" + child.__str__()
        result += native(present).__str__()
    return result
''', tmp_path)


def test_explicitly_none_exception_local_formats_without_narrowing(tmp_path):
    assert_text_matches_python(EXCEPTION_TYPES + '''
def main() -> str:
    saved: Child | None = None
    return str(saved)
''', tmp_path)
