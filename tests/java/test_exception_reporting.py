import re
import subprocess
from textwrap import dedent, indent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import format_exception, transpile_jvm
from tests.java.test_exception_causes import NATIVE_IO
from tests.java.test_exceptions import assert_compiles_to_android_dex, run_jvm
from tests.java.test_jvm import java
from tests.semantics.helpers import run_python


def relationships(report):
    # Frame syntax and generated JVM class names deliberately remain native.
    # Compare managed error headings and relationships. Foreign Java headings
    # and frames are checked separately in the interop cases below.
    lines = []
    for line in report.splitlines():
        line = re.sub(r'^Exception in thread "[^"]+" ', "", line)
        line = re.sub(r"^PyjsProgram\$(?:exception\$)?", "", line)
        if re.match(r"^[A-Za-z_]\w*(?::|$)", line):
            lines.append(line.removesuffix(": "))
        elif line in (
            "The above exception was the direct cause of the following exception:",
            "During handling of the above exception, another exception occurred:",
        ):
            lines.append(line)
    return lines


CASES = {
    "implicit": '''
try:
    raise ValueError("original")
except ValueError:
    raise RuntimeError("wrapper")
''',
    "explicit-precedence": '''
explicit = TypeError("explicit")
try:
    raise ValueError("hidden context")
except ValueError:
    raise RuntimeError("wrapper") from explicit
''',
    "suppression": '''
try:
    raise ValueError("hidden context")
except ValueError:
    raise RuntimeError("wrapper") from None
''',
    "mixed": '''
try:
    raise ValueError("original")
except ValueError:
    try:
        raise TypeError("middle")
    except TypeError as middle:
        raise RuntimeError("last") from middle
''',
    "self-cycle": '''
error = RuntimeError("self")
raise error from error
''',
    "mutual-cycle": '''
first = ValueError("first")
second = RuntimeError("second")
try:
    raise first from second
except ValueError:
    raise second from first
''',
    "base-exception": '''
try:
    raise BaseException("root")
except BaseException:
    raise Failure("child")
''',
    "empty-message": '''
try:
    raise ValueError()
except ValueError:
    raise RuntimeError("résumé 📝")
''',
}


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("caught", [False, True], ids=["uncaught", "format-api"])
def test_reports_match_python_chain_selection_and_order(tmp_path, case, caught):
    body = dedent(CASES[case]).strip()
    if caught:
        body = "try:\n" + indent(body, "    ") + '''
except BaseException as error:
    return format_exception(error)
'''
    source = '''
from pyjs.java import format_exception

class Failure(BaseException):
    pass

''' + f'def main() -> {"str" if caught else "int"}:\n' + indent(body, "    ") + "\n"
    expected = run_python(source + ('\nprint(main(), end="")\n' if caught else "\nmain()\n"))
    actual = run_jvm(source, tmp_path)
    assert actual.returncode == (0 if caught else 1), actual.stderr
    assert expected.returncode == (0 if caught else 1), expected.stderr
    actual_report = actual.stdout if caught else actual.stderr
    expected_report = expected.stdout if caught else expected.stderr
    assert relationships(actual_report) == relationships(expected_report)
    assert relationships(actual_report)
    assert "exceptions.py:" in actual_report


def test_cpython_formatter_uses_standard_traceback_behavior():
    try:
        raise ValueError("original")
    except ValueError:
        try:
            raise RuntimeError("wrapper")
        except RuntimeError as error:
            assert relationships(format_exception(error)) == [
                "ValueError: original",
                "During handling of the above exception, another exception occurred:",
                "RuntimeError: wrapper",
            ]


def test_long_chains_are_iterative_and_reports_do_not_mutate_errors(tmp_path):
    result = run_jvm('''
from pyjs.java import format_exception

def main() -> str:
    previous = RuntimeError("oldest")
    for index in range(1200):
        current = RuntimeError(str(index))
        try:
            raise current from previous
        except RuntimeError:
            pass
        previous = current
    cause = previous.__cause__
    context = previous.__context__
    report = format_exception(previous)
    assert previous.__cause__ is cause
    assert previous.__context__ is context
    assert previous.__suppress_context__
    assert report == format_exception(previous)
    return report
''', tmp_path)
    assert result.returncode == 0, result.stderr
    headings = relationships(result.stdout)
    assert headings[::2] == ["RuntimeError: oldest"] + [f"RuntimeError: {i}" for i in range(1200)]
    assert headings[1::2] == [
        "The above exception was the direct cause of the following exception:"
    ] * 1200
    assert len(result.stdout) < 2_000_000


def test_report_preserves_exact_jvm_source_frames(tmp_path):
    result = run_jvm('''\
from pyjs.java import format_exception
def main() -> str:
    return format_exception(ValueError("first"))
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.replace("\r\n", "\n") == (
        "PyjsProgram$exception$ValueError: first\n"
        "\tat PyjsProgram.pyjs_main(exceptions.py:3)\n"
        "\tat PyjsProgram.main(exceptions.py)\n"
    )


NATIVE_OUTPUTS = '''
from typing import cast
from pyjs import jvm
from pyjs.java import format_exception

@jvm.native("java/io/Writer")
class Writer:
    pass

@jvm.native("java/io/StringWriter")
class StringWriter(Writer):
    def __init__(self) -> None: ...
    def toString(self) -> str: ...

@jvm.native("java/io/PrintWriter")
class PrintWriter:
    def __init__(self, writer: Writer) -> None: ...

@jvm.native("java/io/OutputStream")
class OutputStream:
    pass

@jvm.native("java/io/ByteArrayOutputStream")
class Bytes(OutputStream):
    def __init__(self) -> None: ...
    def toString(self) -> str: ...

@jvm.native("java/io/PrintStream")
class PrintStream:
    def __init__(self, output: OutputStream) -> None: ...

@jvm.native("java/lang/Throwable")
class Throwable:
    @jvm.native("java/lang/Throwable", name="printStackTrace", invocation="virtual")
    def print_default(self) -> None: ...
    @jvm.native("java/lang/Throwable", name="printStackTrace", invocation="virtual")
    def print_writer(self, writer: PrintWriter) -> None: ...
    @jvm.native("java/lang/Throwable", name="printStackTrace", invocation="virtual")
    def print_stream(self, stream: PrintStream) -> None: ...
    def addSuppressed(self, error: BaseException) -> None: ...
    def initCause(self, error: BaseException) -> BaseException: ...
'''


@pytest.mark.parametrize("output", ["default", "writer", "stream"])
def test_print_stack_trace_overloads_use_the_same_report(tmp_path, output):
    render = {
        "default": "view.print_default()\nreturn expected",
        "writer": "sink = StringWriter()\nview.print_writer(PrintWriter(sink))\nassert sink.toString() == expected\nreturn expected",
        "stream": "sink = Bytes()\nview.print_stream(PrintStream(sink))\nassert sink.toString() == expected\nreturn expected",
    }[output]
    result = run_jvm(NATIVE_OUTPUTS + '''
def main() -> str:
    try:
        raise ValueError("original")
    except ValueError:
        try:
            raise RuntimeError("wrapper")
        except RuntimeError as error:
            expected = format_exception(error)
            view = cast(Throwable, error)
''' + indent(render, "            ") + "\n    return \"not caught\"\n", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == (result.stdout if output == "default" else "")
    assert relationships(result.stdout) == [
        "ValueError: original",
        "During handling of the above exception, another exception occurred:",
        "RuntimeError: wrapper",
    ]


def test_native_failures_and_suppressed_details_are_preserved(tmp_path):
    missing = str(tmp_path / "absent" / "order.txt")
    result = run_jvm(NATIVE_OUTPUTS + NATIVE_IO + f'''
def main() -> str:
    try:
        Input({missing!r})
    except IOException as native:
        try:
            raise RuntimeError("save failed")
        except RuntimeError as wrapper:
            cast(Throwable, wrapper).addSuppressed(TypeError("secondary"))
            report = format_exception(wrapper)
            assert wrapper.__context__ is native
            return report
    return "not caught"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    # Native frame details and the filesystem's error wording vary by JVM/OS.
    assert "java.io.FileNotFoundException:" in result.stdout
    assert missing in result.stdout
    assert "java.io.FileInputStream" in result.stdout
    assert "Suppressed: PyjsProgram$exception$TypeError: secondary" in result.stdout
    assert relationships(result.stdout) == [
        "During handling of the above exception, another exception occurred:",
        "RuntimeError: save failed",
    ]


def test_formatter_follows_python_context_below_a_native_root(tmp_path):
    missing = str(tmp_path / "absent" / "order.txt")
    result = run_jvm(NATIVE_OUTPUTS + NATIVE_IO + f'''
def main() -> str:
    try:
        raise ValueError("original")
    except ValueError:
        try:
            raise RuntimeError("managed wrapper")
        except RuntimeError as error:
            try:
                Input({missing!r})
            except IOException as native:
                view = cast(Throwable, native)
                view.initCause(error)
                sink = StringWriter()
                view.print_writer(PrintWriter(sink))
                assert "ValueError: original" not in sink.toString()
                return format_exception(native)
    return "not caught"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert relationships(result.stdout) == [
        "ValueError: original",
        "During handling of the above exception, another exception occurred:",
        "RuntimeError: managed wrapper",
        "The above exception was the direct cause of the following exception:",
    ]
    assert "java.io.FileNotFoundException:" in result.stdout
    assert missing in result.stdout


@pytest.mark.parametrize("output", ["format", "default", "writer", "stream"])
@pytest.mark.parametrize("factory", [False, True], ids=["direct", "base-factory"])
def test_unraised_custom_formatters_are_retained_at_every_report_boundary(tmp_path, output, factory):
    value = 'create()' if factory else 'Failure("raw")'
    render = {
        "format": "return format_exception(error)",
        "default": 'cast(Throwable, error).print_default()\nreturn ""',
        "writer": "sink = StringWriter()\ncast(Throwable, error).print_writer(PrintWriter(sink))\nreturn sink.toString()",
        "stream": "sink = Bytes()\ncast(Throwable, error).print_stream(PrintStream(sink))\nreturn sink.toString()",
    }[output]
    result = run_jvm(NATIVE_OUTPUTS + '''
class Failure(Exception):
    def __str__(self) -> str:
        return "custom:" + super().__str__()

def create() -> Exception:
    return Failure("raw")

def main() -> str:
''' + f'    error = {value}\n'
        + indent(render, "    ") + "\n", tmp_path)
    assert result.returncode == 0, result.stderr
    report = result.stderr if output == "default" else result.stdout
    assert (result.stdout if output == "default" else result.stderr) == ""
    assert report.splitlines()[0] == "PyjsProgram$Failure: custom:raw"
    assert relationships(report) == ["Failure: custom:raw"]


@pytest.mark.parametrize("formatter", [
    'def __str__(self) -> str | None:\n    return None',
    'def __str__(self) -> int:\n    return 42',
    'def __str__(self) -> str:\n    raise TypeError("broken formatter")',
    'def __str__(self) -> str:\n    raise BaseException("broken formatter")',
])
def test_report_formatter_failure_preserves_original_error_and_active_handler(tmp_path, formatter):
    result = run_jvm('''
from pyjs.java import format_exception

class Failure(Exception):
''' + indent(formatter, "    ") + '''

def main() -> str:
    original = ValueError("active")
    try:
        raise original
    except ValueError:
        error = Failure("raw")
        report = format_exception(error)
        assert error.__context__ is None
        assert error.__cause__ is None
        try:
            raise RuntimeError("after formatting")
        except RuntimeError as after:
            assert after.__context__ is original
        return report
    return "not caught"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert relationships(result.stdout) == ["Failure: <exception str() failed>"]


def test_foreign_subclass_reports_keep_java_message_semantics(tmp_path):
    result = run_jvm('''
from pyjs import jvm
from pyjs.java import format_exception

@jvm.native("java/lang/RuntimeException")
class ForeignError(Exception):
    def __init__(self, message: str) -> None: ...

class ForeignChild(ForeignError):
    def __init__(self, message: str):
        super().__init__(message)

    def __str__(self) -> str:
        return "Python-only text"

def main() -> str:
    return format_exception(ForeignChild("native text"))
''', tmp_path)
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.splitlines()[0] == "PyjsProgram$ForeignChild: native text"
    assert "Python-only text" not in result.stdout


@pytest.mark.parametrize(("call", "message", "column", "help_text"), [
    ("format_exception(None)",
     "Argument 'error' to format_exception expects BaseException, got NoneType",
     29, "Pass a value compatible with BaseException."),
    ("format_exception(42)",
     "Argument 'error' to format_exception expects BaseException, got int",
     29, "Pass a value compatible with BaseException."),
    ("format_exception()",
     "format_exception() is missing required argument(s): 'error'",
     12, "Pass every required argument."),
    ("format_exception(error=ValueError())",
     "format_exception() parameter 'error' is positional-only",
     29, "Pass 'error' as a positional argument."),
])
def test_report_argument_diagnostics(call, message, column, help_text):
    with pytest.raises(CompilationError) as caught:
        transpile_jvm("from pyjs.java import format_exception\ndef main() -> str:\n    return " + call + "\n")
    error = caught.value
    assert (error.diagnostic.code, error.diagnostic.message) == ("PYJS1104", message)
    assert (error.lineno, error.offset) == (3, column)
    assert error.diagnostic.help == (help_text,)


def test_report_runtime_and_java_printer_compile_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(NATIVE_OUTPUTS + '''
def main() -> str:
    try:
        raise ValueError("original")
    except ValueError:
        try:
            raise RuntimeError("wrapper")
        except RuntimeError as error:
            sink = StringWriter()
            cast(Throwable, error).print_writer(PrintWriter(sink))
            assert sink.toString() == format_exception(error)
            return sink.toString()
    return "not caught"
''', tmp_path)


@pytest.mark.parametrize("separator", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("output", ["format", "default", "writer", "stream"])
def test_report_bytes_use_one_host_line_separator(tmp_path, separator, output):
    render = {
        "format": "return expected",
        "default": "view.print_default()\nreturn expected",
        "writer": "sink = StringWriter()\nview.print_writer(PrintWriter(sink))\nassert sink.toString() == expected\nreturn expected",
        "stream": "sink = Bytes()\nview.print_stream(PrintStream(sink))\nassert sink.toString() == expected\nreturn expected",
    }[output]
    if output != "format":
        render = "view = cast(Throwable, error)\n" + render
    source = NATIVE_OUTPUTS + '''
def main() -> str:
    try:
        raise ValueError("first")
    except ValueError:
        try:
            raise TypeError("middle")
        except TypeError as middle:
            try:
                raise RuntimeError("last") from middle
            except RuntimeError as error:
                expected = format_exception(error)
''' + indent(render, "                ") + '\n    return "not caught"\n'
    transpile_jvm(source, filename="newlines.py").write(tmp_path)
    # Text-mode subprocess capture would normalize CRLF and hide this defect.
    result = subprocess.run(
        [java(), "-Xmx128m", "-Xverify:all", "-Dline.separator=" + separator,
         "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == (result.stdout if output == "default" else b"")
    remainder = result.stdout.replace(separator.encode(), b"")
    assert b"\r" not in remainder and b"\n" not in remainder
    assert result.stdout.endswith(separator.encode())
    assert relationships(result.stdout.decode()) == [
        "ValueError: first",
        "During handling of the above exception, another exception occurred:",
        "TypeError: middle",
        "The above exception was the direct cause of the following exception:",
        "RuntimeError: last",
    ]


@pytest.mark.parametrize("auto_flush", [False, True])
@pytest.mark.parametrize("kind", ["RuntimeError", "NativeError"])
def test_print_writer_preserves_configured_auto_flush(tmp_path, auto_flush, kind):
    result = run_jvm(NATIVE_OUTPUTS + f'''
@jvm.native("java/io/PrintWriter")
class BufferedWriter:
    def __init__(self, sink: OutputStream, auto_flush: bool) -> None: ...
    def flush(self) -> None: ...

@jvm.native("java/lang/Throwable")
class Printable:
    def printStackTrace(self, sink: BufferedWriter) -> None: ...

@jvm.native("java/lang/RuntimeException")
class NativeError(Exception):
    def __init__(self, message: str) -> None: ...

def main() -> str:
    error = {kind}("original")
    expected = format_exception(error)
    sink = Bytes()
    writer = BufferedWriter(sink, {auto_flush!r})
    cast(Printable, error).printStackTrace(writer)
    assert sink.toString() == {"expected" if auto_flush else '""'}
    writer.flush()
    assert sink.toString() == expected
    return "preserved"
''', tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "preserved", "")


def test_uncaught_host_prefix_precedes_oldest_entry_and_escaping_error_is_last(tmp_path):
    result = run_jvm('''
def main() -> int:
    try:
        raise ValueError("original")
    except ValueError:
        raise RuntimeError("escaping")
''', tmp_path)
    assert result.returncode == 1, result.stderr
    assert result.stderr.splitlines()[0] == (
        'Exception in thread "main" PyjsProgram$exception$ValueError: original'
    )
    assert relationships(result.stderr) == [
        "ValueError: original",
        "During handling of the above exception, another exception occurred:",
        "RuntimeError: escaping",
    ]
