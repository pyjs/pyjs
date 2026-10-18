"""Python text dispatch on authored subclasses of foreign Java throwables."""

import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_matches_python

FORMATTING = pytest.mark.parametrize("formatting", [
    "str(error)", 'f"{error}"', 'f"{error!s}"', "error.__str__()",
], ids=["str", "interpolation", "str-conversion", "explicit"])

NATIVE_ERROR = '''
from pyjs import jvm

@jvm.native("java/lang/RuntimeException")
class NativeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)

class Failure(NativeError):
    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self, suffix: str = "parent") -> str:
        return suffix

class Child(Failure):
    def __str__(self, suffix: str = "child") -> str:
        return suffix
'''


@FORMATTING
@pytest.mark.parametrize("view", ["Failure", "Failure | None", "Inherited | None"])
def test_native_subclass_formatting_uses_runtime_override_and_defaults(
    tmp_path, formatting, view,
):
    assert_text_matches_python(NATIVE_ERROR + f'''
class Inherited(Child):
    pass

def create(events: list[str]) -> {view}:
    events.append("create")
    return Inherited("native message")

def format_error(error: {view}) -> str:
    return {formatting}

def main() -> str:
    events: list[str] = []
    result = format_error(create(events))
    assert len(events) == 1
    return result
''', tmp_path)


@FORMATTING
@pytest.mark.parametrize("view", [
    "Managed | Failure", "Failure | Managed",
    "Managed | Failure | None", "None | Failure | Managed",
])
def test_mixed_exception_union_dispatch_is_independent_of_member_order(
    tmp_path, formatting, view,
):
    absent = 'result += format_error(None) + "|"' if "None" in view else ""
    assert_text_matches_python(NATIVE_ERROR + f'''
class Managed(Exception):
    def __str__(self) -> str:
        return "managed"

def format_error(error: {view}) -> str:
    return {formatting}

def main() -> str:
    result = format_error(Managed("raw")) + "|"
    result += format_error(Child("native message")) + "|"
    {absent}
    return result
''', tmp_path)


@FORMATTING
def test_nullable_native_formatter_preserves_effects_and_failures(tmp_path, formatting):
    assert_text_matches_python(NATIVE_ERROR + f'''
class Tracked(Failure):
    def __init__(self, message: str, events: list[str], fail: bool):
        super().__init__(message)
        self.events = events
        self.fail = fail

    def __str__(self, suffix: str = "tracked") -> str:
        self.events.append(suffix)
        if self.fail:
            raise ValueError("formatter failed")
        return suffix

def format_error(error: Failure | None) -> str:
    return {formatting}

def main() -> str:
    events: list[str] = []
    result = format_error(None)
    assert len(events) == 0
    result += "|" + format_error(Tracked("raw", events, False))
    try:
        format_error(Tracked("raw", events, True))
    except ValueError as caught:
        result += "|" + str(caught)
    assert len(events) == 2
    assert events[0] == "tracked" and events[1] == "tracked"
    return result
''', tmp_path)


@FORMATTING
def test_native_nullable_factory_interpolation_keeps_authored_text(tmp_path, formatting):
    expression = formatting.replace("error", "create(present)")
    assert_text_matches_python(NATIVE_ERROR + f'''
def create(present: bool) -> Child | None:
    return Child("raw") if present else None

def main() -> str:
    result = ""
    for present in [True, False]:
        result += {expression} + "|"
    return result
''', tmp_path)


@pytest.mark.parametrize("view", ["NativeError", "Exception", "BaseException | None"])
def test_widened_foreign_subclass_keeps_formatter_and_native_super(tmp_path, view):
    assert_text_matches_python(NATIVE_ERROR + f'''
class Detailed(NativeError):
    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self) -> str:
        parent = super()
        return "detail:" + parent.__str__()

def format_error(error: {view}) -> str:
    return str(error)

def main() -> str:
    return format_error(Detailed("raw"))
''', tmp_path)


@pytest.mark.parametrize("formatting", ["str(error)", 'f"{error}"', 'f"{error!s}"'])
def test_foreign_implicit_text_rejects_null_but_explicit_returns_it(tmp_path, formatting):
    assert_matches_python(NATIVE_ERROR + f'''
from typing import cast

def absent() -> str | None:
    return None

class Invalid(Failure):
    def __str__(self, suffix: str = "unused") -> str:
        return cast(str, absent())

def format_error(error: Failure | None) -> str:
    return {formatting}

def main() -> int:
    error = Invalid("raw")
    assert error.__str__() is None
    assert format_error(None) == "None"
    try:
        format_error(error)
    except TypeError:
        return 42
    return 0
''', tmp_path)


def test_foreign_explicit_base_view_rejects_conflicting_result_type():
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(NATIVE_ERROR + '''
class Invalid(NativeError):
    def __init__(self, message: str):
        super().__init__(message)
    def __str__(self) -> int:
        return 42
def message(error: NativeError | None) -> str:
    return error.__str__()
def main() -> str:
    return message(Invalid("raw"))
''')
    assert str(caught.value) == (
        "JVM explicit exception __str__ calls require matching override result types; "
        "narrow the receiver to its concrete exception type at line 2 "
        "while compiling _pyjs_java_.message"
    )
