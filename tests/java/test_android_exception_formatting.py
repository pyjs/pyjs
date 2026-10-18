"""Execute exception text dispatch on both Robolectric and Android ART."""

from typing import cast

import pytest

from pyjs import jvm

pytestmark = pytest.mark.pyjs_android_jvm


@jvm.native("java/lang/RuntimeException")
class NativeError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class ForeignFailure(NativeError):
    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self, suffix: str = "parent") -> str:
        return suffix


class ForeignChild(ForeignFailure):
    def __str__(self, suffix: str = "child") -> str:
        return suffix


class ManagedFailure(Exception):
    def __str__(self) -> str:
        return "managed"


def mixed_text(error: ManagedFailure | ForeignFailure | None) -> str:
    return str(error) + f"|{error}|{error!s}|" + error.__str__()


def reversed_text(error: None | ForeignFailure | ManagedFailure) -> str:
    return str(error) + f"|{error}|{error!s}|" + error.__str__()


def test_nullable_mixed_exception_text_preserves_runtime_dispatch() -> None:
    assert mixed_text(None) == "None|None|None|None"
    assert reversed_text(None) == "None|None|None|None"
    assert mixed_text(ManagedFailure("raw")) == "managed|managed|managed|managed"
    assert reversed_text(ManagedFailure("raw")) == "managed|managed|managed|managed"
    assert mixed_text(ForeignChild("raw")) == "child|child|child|child"
    assert reversed_text(ForeignChild("raw")) == "child|child|child|child"


class TrackedFailure(ForeignFailure):
    def __init__(self, message: str, events: list[str], fail: bool):
        super().__init__(message)
        self.events = events
        self.fail = fail

    def __str__(self, suffix: str = "tracked") -> str:
        self.events.append("format")
        if self.fail:
            raise ValueError("formatter failed")
        return suffix


def optional_text(error: ForeignFailure | None) -> str:
    return f"{error}"


def create_tracked(events: list[str], fail: bool) -> ForeignFailure | None:
    events.append("create")
    return TrackedFailure("raw", events, fail)


def test_foreign_formatter_effects_and_exceptions_survive_android_lowering() -> None:
    events: list[str] = []
    assert optional_text(None) == "None"
    assert len(events) == 0
    assert optional_text(create_tracked(events, False)) == "tracked"
    assert len(events) == 2
    assert events[0] == "create" and events[1] == "format"
    try:
        optional_text(create_tracked(events, True))
        raise AssertionError("Expected formatter failure")
    except ValueError as error:
        assert str(error) == "formatter failed"
    assert len(events) == 4
    assert events[2] == "create" and events[3] == "format"


def absent() -> str | None:
    return None


class InvalidFailure(ForeignFailure):
    def __str__(self, suffix: str = "unused") -> str:
        return cast(str, absent())


class DetailedFailure(NativeError):
    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self) -> str:
        parent = super()
        return "detail:" + parent.__str__()


def base_text(error: Exception | None) -> str:
    return str(error)


def test_foreign_formatter_null_guard_and_lexical_super() -> None:
    invalid = InvalidFailure("raw")
    assert invalid.__str__() is None
    try:
        optional_text(invalid)
        raise AssertionError("Expected invalid formatter result")
    except TypeError:
        pass
    assert base_text(DetailedFailure("native")) == "detail:native"
    assert base_text(None) == "None"
