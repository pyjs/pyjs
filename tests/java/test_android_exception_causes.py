"""Exercise chaining on Robolectric and the device's actual ART runtime."""

import pytest

from pyjs import jvm
from pyjs.java import i32

pytestmark = pytest.mark.pyjs_android_jvm


class SaveFailure(RuntimeError):
    pass


def test_cause_identity_replacement_and_suppression() -> None:
    error = SaveFailure("save failed")
    original = ValueError("original")
    assert error.__cause__ is None
    assert not error.__suppress_context__
    cleaned = False
    try:
        try:
            raise error from original
        finally:
            cleaned = True
    except RuntimeError as caught:
        assert cleaned and caught is error
        assert caught.__cause__ is original
        assert caught.__suppress_context__
        try:
            raise
        except Exception as repeated:
            assert repeated is error and repeated.__cause__ is original
    try:
        raise error from error
    except RuntimeError as cycle:
        assert cycle.__cause__ is error
    try:
        raise error from None
    except RuntimeError as cleared:
        assert cleared.__cause__ is None
        assert cleared.__suppress_context__


def fail_cause(events: list[str]) -> BaseException:
    events.append("cause")
    raise ValueError("cause failed")


def get_target(events: list[str], error: SaveFailure) -> SaveFailure:
    events.append("target")
    return error


def test_failing_cause_preserves_original_state_and_evaluation_order() -> None:
    events: list[str] = []
    error = SaveFailure("save")
    original = ValueError("first")
    try:
        raise error from original
    except SaveFailure:
        pass
    try:
        raise get_target(events, error) from fail_cause(events)
    except ValueError as failed:
        assert str(failed) == "cause failed"
    assert error.__cause__ is original
    assert len(events) == 2
    assert events[0] == "target" and events[1] == "cause"


@jvm.native("java/lang/NumberFormatException")
class NativeFailure(Exception):
    pass


@jvm.native("java/lang/Integer", name="parseInt")
def parse(value: str) -> i32:
    raise NativeFailure("invalid")


def test_native_failure_is_preserved_but_cannot_receive_python_state() -> None:
    try:
        parse("invalid")
    except Exception as original:
        try:
            raise SaveFailure("read failed") from original
        except SaveFailure as wrapper:
            assert wrapper.__cause__ is original
            assert isinstance(wrapper.__cause__, NativeFailure)
            assert not original.__suppress_context__
        try:
            raise original from None
        except TypeError as invalid:
            assert str(invalid) == (
                "explicit causes require a Python exception; wrap the native failure"
            )
            return
    raise AssertionError("Expected native-target rejection")
