"""Python-aware reports and Java printer dispatch on Android runtimes."""

from typing import cast

import pytest

from pyjs import jvm
from pyjs.java import format_exception

pytestmark = pytest.mark.pyjs_android_jvm


class Failure(Exception):
    def __str__(self) -> str:
        return "custom:" + super().__str__()


class InvalidText(Exception):
    def __str__(self) -> str | None:
        return None


@jvm.native("java/io/Writer")
class Writer:
    pass


@jvm.native("java/io/StringWriter")
class StringWriter(Writer):
    def __init__(self) -> None: ...

    def toString(self) -> str: ...


@jvm.native("java/io/PrintWriter")
class PrintWriter:
    def __init__(self, sink: Writer) -> None: ...


@jvm.native("java/lang/Throwable")
class Throwable:
    def printStackTrace(self, sink: PrintWriter) -> None: ...


def test_report_selects_context_and_keeps_original_state() -> None:
    original = ValueError("original")
    try:
        raise original
    except ValueError:
        try:
            raise Failure("wrapper")
        except Failure as error:
            report = format_exception(error)
            assert "ValueError: original" in report
            assert "During handling of the above exception" in report
            assert "custom:wrapper" in report
            assert error.__context__ is original
            assert error.__cause__ is None
            assert report == format_exception(error)
        try:
            raise Failure("hidden") from None
        except Failure as suppressed:
            report = format_exception(suppressed)
            assert "ValueError: original" not in report
            assert "custom:hidden" in report
            assert suppressed.__context__ is original


def test_unraised_formatter_survives_java_printer_dispatch() -> None:
    error = Failure("unraised")
    sink = StringWriter()
    cast(Throwable, error).printStackTrace(PrintWriter(sink))
    assert "custom:unraised" in sink.toString()
    assert sink.toString() == format_exception(error)
    assert error.__context__ is None


def test_report_breaks_cause_cycles_and_contains_formatter_failure() -> None:
    first = ValueError("first")
    second = RuntimeError("second")
    try:
        raise first from second
    except ValueError:
        try:
            raise second from first
        except RuntimeError:
            report = format_exception(second)
            assert "ValueError: first" in report
            assert "RuntimeError: second" in report
            assert "The above exception was the direct cause" in report
            assert first.__cause__ is second
            assert second.__cause__ is first
            assert "<exception str() failed>" in format_exception(InvalidText())
            try:
                raise Failure("after formatting")
            except Failure as after:
                assert after.__context__ is second
