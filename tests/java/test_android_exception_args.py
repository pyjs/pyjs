from typing import cast

import pytest

pytestmark = pytest.mark.pyjs_android_jvm


class Message(Exception):
    def __init__(self, value: str):
        super().__init__("message:" + value)


class NumericPayload(Exception):
    def __init__(self, value: float):
        pass


def test_original_arguments_and_saved_tuple_survive_reinitialization() -> None:
    assert len(BaseException().args) == 0
    assert cast(int, ValueError(42).args[0]) == 42
    assert cast(bool, ValueError(False).args[0]) is False
    error = Message("first")
    saved = error.args
    error.__init__("second")
    assert error.args is not saved
    assert cast(str, saved[0]) == "message:first"
    assert cast(str, error.args[-1]) == "message:second"
    assert str(error) == "message:second"


def test_runtime_arguments_and_context_preserve_original_payloads() -> None:
    original = ValueError("outer")
    try:
        raise original
    except ValueError:
        values: dict[str | None, str] = {}
        try:
            values[None]
        except KeyError as missing:
            assert len(missing.args) == 1
            assert missing.args[0] is None
            assert missing.__context__ is original
        else:
            raise AssertionError("missing dictionary key did not raise")
        try:
            ValueError().args[0]
        except IndexError as bounds:
            assert cast(str, bounds.args[0]) == "tuple index out of range"
            assert bounds.__context__ is original
        else:
            raise AssertionError("empty argument lookup did not raise")


def test_boxed_numeric_arguments_preserve_exact_mixed_comparisons() -> None:
    original = NumericPayload(9007199254740992.0)
    floating = original.args[0]
    integer = ValueError(9007199254740993).args[0]
    assert floating != integer
    assert integer != floating
    assert cast(float, floating) == 9007199254740992.0
    assert NumericPayload(-0.0).args[0] == ValueError(False).args[0]
    assert ValueError(True).args[0] == ValueError(1).args[0]


def test_erased_numeric_dictionary_keys_have_an_explicit_boundary() -> None:
    mapping: dict[object, str] = {}
    try:
        mapping[ValueError(True).args[0]] = "value"
    except TypeError as error:
        assert str(error) == "JVM erased numeric and reference-array dictionary keys are not implemented"
        assert len(mapping) == 0
    else:
        raise AssertionError("numeric object key unexpectedly accepted")
