"""Native text output boundaries, query encoding and partial failure semantics."""

import os
import signal
import subprocess
import sys

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_urlencode_preserves_order_utf8_and_owned_output(optimize):
    LLVM().assert_matches_python('''
        from urllib.parse import urlencode
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            query = {"café": "雪/🙂", "a\\0b": "+ =&%", "~safe": "-._~"}
            query["empty"] = ""
            del query["a\\0b"]
            query["a\\0b"] = "last entry"
            result = urlencode(query)
            query.clear()
            gc_collect()
            empty: dict[str, str] = {}
            print(0.1, 1.0, -0.0, 1e16, sep="|")
            return result + "|" + urlencode(empty) + "|" + urlencode({}) + "|" + urlencode({"": ""})
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_print_evaluation_partial_output_and_collecting_callbacks(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Label:
            def __init__(self, events: list[int], value: int):
                self.events = events
                self.value = value

            def __str__(self) -> str:
                self.events.append(self.value + 10)
                gc_collect()
                if self.value == 2:
                    raise ValueError("conversion failed")
                return "label=" + str(self.value)

        def label(events: list[int], value: int) -> Label:
            events.append(value)
            gc_collect()
            return Label(events, value)

        def option(events: list[int], value: int) -> str:
            events.append(value)
            gc_collect()
            return "[" + str(value) + "]"

        def main() -> int:
            gc_set_threshold(1)
            events: list[int] = []
            try:
                print(label(events, 1), label(events, 2), label(events, 3),
                      end=option(events, 4), sep=option(events, 5), flush=True)
            except ValueError:
                print("caught", events)
            print(label(events, 3), label(events, 4))
            print("é😀", 42, True, None, b"bytes", sep=None, end=None, file=None)
            print()
            print([], {}, ())
            return 0
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_print_optional_options_mutation_and_numeric_representations(optimize):
    LLVM().assert_matches_python('''
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect, gc_set_threshold

        class Mutator:
            def __init__(self, values: list[int]):
                self.values = values

            def __str__(self) -> str:
                self.values.append(3)
                gc_collect()
                return "mutated"

        def mutate(values: list[int]) -> int:
            values.append(2)
            gc_collect()
            return len(values)

        def emit(separator: str | None, ending: str | None) -> None:
            print(int8(-3), int64(9223372036854775807), float32(1.5), sep=separator, end=ending)

        def main() -> int:
            gc_set_threshold(1)
            values = [1]
            print(values, mutate(values), Mutator(values), values)
            emit(None, None)
            emit("--", "END")
            print()
            return 0
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_print_failed_options_and_reentrant_output(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Label:
            def __str__(self) -> str:
                print("inside", end=":")
                gc_collect()
                return "outside"

        def ending(fail: bool) -> str:
            gc_collect()
            if fail:
                raise ValueError("before output")
            return "!"

        def main() -> int:
            gc_set_threshold(1)
            try:
                print("not written", Label(), end=ending(True))
            except ValueError:
                print("caught")
            print(Label(), "done", end=ending(False))
            return 0
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_output_allocation_recovery(tmp_path, optimize):
    source = transpile_llvm('''
        from urllib.parse import urlencode
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        def main() -> int:
            gc_set_threshold(1)
            query = {"café": "雪/🙂", "a\\0b": "+ =&%"}
            expected = urlencode(query)
            caught = 0
            for attempt in range(1, 80):
                arm(attempt)
                complete = False
                try:
                    result = urlencode(query)
                    print(result, [1, 2, 3], end="")
                    arm(0)
                    complete = True
                except MemoryError:
                    arm(0)
                    caught += 1
                finally:
                    arm(0)
                gc_collect()
                assert urlencode(query) == expected
                if complete:
                    assert result == expected and caught > 0
                    return 0
            return 1
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_print_write_failure_is_catchable_and_recovers(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> int:
            gc_set_threshold(1)
            try:
                print([1, 2], "never written")
            except OSError:
                gc_collect()
                print("recovered")
                return 0
            return 1
    ''')
    # A zero-byte write cannot make progress. Inject it once without closing
    # the host's stdout or relying on pipe/terminal error behavior.
    source = source.replace("call i64 @write(", "call i64 @test.write(")
    source += '''
        @test.fail.write = private global i1 true
        define private i64 @test.write(i32 %fd, ptr %data, i64 %size) {
          %fail = load i1, ptr @test.fail.write
          store i1 false, ptr @test.fail.write
          br i1 %fail, label %failed, label %write
        failed:
          ret i64 0
        write:
          %written = call i64 @write(i32 %fd, ptr %data, i64 %size)
          ret i64 %written
        }
    '''
    executable = LLVM().compile(source, tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
    assert (result.returncode, result.stdout, result.stderr) == (0, "recovered\n", "")


@pytest.mark.parametrize("optimize", [0, 2])
def test_print_shared_failure_uses_each_write_status(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect

        def main() -> int:
            result = 0
            for position in range(6):
                try:
                    print("a", "b", "c", sep="|", end="!")
                except BrokenPipeError:
                    result += 10
                except OSError:
                    result += 1
                gc_collect()
            return result
    ''')
    # Fail successive calls at each of the six argument/separator/ending sites.
    # Alternate EPIPE and zero-write EIO, leaving stale EPIPE in libc errno on
    # EIO: dispatch must use this write's captured status, not the previous one.
    source = source.replace("call i64 @write(", "call i64 @test.write(")
    source += '''
        @test.remaining = private global i64 0
        @test.failure = private global i64 0
        define private i64 @test.write(i32 %fd, ptr %data, i64 %size) {
          %remaining = load i64, ptr @test.remaining
          %fail = icmp eq i64 %remaining, 0
          br i1 %fail, label %failed, label %written
        written:
          %left = sub i64 %remaining, 1
          store i64 %left, ptr @test.remaining
          ret i64 %size
        failed:
          %failure = load i64, ptr @test.failure
          %next = add i64 %failure, 1
          store i64 %next, ptr @test.failure
          store i64 %next, ptr @test.remaining
          %odd = and i64 %failure, 1
          %pipe = icmp eq i64 %odd, 0
          br i1 %pipe, label %epipe, label %eio
        epipe:
          %errno = call ptr @__errno_location()
          store i32 32, ptr %errno
          ret i64 -1
        eio:
          ret i64 0
        }
    '''
    executable = LLVM().compile(source, tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
    assert (result.returncode, result.stdout, result.stderr) == (33, "", "")


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("handler", ["BrokenPipeError", "ConnectionError", "OSError"])
def test_print_closed_pipe_is_catchable(tmp_path, optimize, handler):
    source = f'''
def main() -> int:
    try:
        print("message", flush=True)
    except {handler}:
        return 42
    except OSError:
        return 43
    return 1
'''
    executable = LLVM().compile(transpile_llvm(source), tmp_path, optimize=optimize,
                                sanitizers=("address", "undefined"))
    for command in ([sys.executable, "-u", "-c", source + "\nraise SystemExit(main())"], [executable]):
        read, write = os.pipe()
        os.close(read)
        try:
            result = subprocess.run(command, stdout=write, stderr=subprocess.PIPE, timeout=10)
            assert (result.returncode, result.stderr) == (42, b"")
        finally:
            os.close(write)
    # No sys.stdout object is modeled: a descriptor absent at process startup
    # still produces OSError, rather than CPython's stdout=None no-op.
    result = subprocess.run(["/bin/sh", "-c", 'exec "$1" >&-', "closed-output", str(executable)],
                            capture_output=True, timeout=10)
    assert (result.returncode, result.stdout, result.stderr) == (
        42 if handler == "OSError" else 43, b"", b"",
    )


def test_renderer_library_preserves_host_sigpipe_policy(tmp_path):
    # Run in a child: changing SIGPIPE in the pytest process would interfere
    # with unrelated output. Killing this child proves libc still has SIG_DFL;
    # Python's getsignal() alone could report stale interpreter-side state.
    script = '''
import os, signal, sys
from pathlib import Path
from pyjs.tooling.llvm import LLVM
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
library = LLVM().compile_library('def main() -> str: return "rendered"', Path(sys.argv[1]))
try:
    assert library.render() == "rendered"
finally:
    library.close()
os.kill(os.getpid(), signal.SIGPIPE)
raise SystemExit(99)
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=30)
    assert (result.returncode, result.stdout, result.stderr) == (-signal.SIGPIPE, b"", b"")


@pytest.mark.parametrize("optimize", [0, 2])
def test_urlencode_host_input_and_dom_escaping(tmp_path, optimize):
    comparison = LLVM().assert_library_matches_python('''
        import urllib.parse
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import tag
        from pyjs.web.ssr import render_html

        def render(query: list[tuple[str, str]]) -> str:
            gc_set_threshold(1)
            local = dict(query)
            encoded = urllib.parse.urlencode(local)
            local.clear()
            gc_collect()
            return render_html(tag("a", {"href": "/logs?" + encoded}, "View logs"))
    ''', [("q", "雪 & status=error"), ("page", "1")], directory=tmp_path,
        entry_point="render", optimize=optimize)
    comparison.library.close()


@pytest.mark.parametrize("source, message", [
    ('print("x", file=1)', "standard output"),
    ('print(*[1, 2])', "expansion"),
    ('print("x", flush=1)', "bool"),
    ('urlencode({"a": 1})', "str"),
    ('urlencode({"a": "b"}, doseq=True)', "doseq"),
])
def test_text_output_unsupported_boundaries(source, message):
    with pytest.raises((LLVMUnsupported, CompilationError), match=message):
        transpile_llvm("from urllib.parse import urlencode\ndef main() -> int:\n    " + source + "\n    return 0")


@pytest.mark.parametrize("import_statement, expression", [
    ("import urllib.parse", "urllib.parse.quote('a b')"),
    ("import urllib.parse as query", "query.quote_plus('a b')"),
    ("from urllib import parse", "parse.quote('a b')"),
])
def test_missing_url_module_members_have_located_diagnostics(import_statement, expression):
    with pytest.raises(CompilationError) as caught:
        transpile_llvm(f"{import_statement}\ndef main() -> str:\n    return {expression}", filename="query.py")
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "PYJS1003"
    primary = diagnostic.to_dict()["primary"]
    assert primary["file"] == "query.py"
    assert primary["start"]["line"] == 2
    assert "has no attribute" in diagnostic.message


@pytest.mark.parametrize("arguments", ["int", "Item", "[int]", "{'kind': str}", "(Item,)", "file=Item"])
def test_print_class_values_fail_before_runtime_type_queries(arguments):
    with pytest.raises(LLVMUnsupported, match=r"LLVM print does not support class objects at line 2") as caught:
        transpile_llvm(f"class Item: pass\ndef main() -> int:\n    print({arguments})\n    return 0",
                       filename="class_print.py")
    assert caught.value.__notes__ == [
        "Source location: class_print.py:3:5 (main; reported line above is function-relative)",
    ]
