"""Host toolchain boundaries; real execution lives in the shared native suite."""

import ctypes
import errno
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.native.platform import binary_suffix, errno_symbol
from pyjs.tooling.llvm import LLVM, _windows_exported_ir


@pytest.fixture
def configured_compiler(tmp_path, monkeypatch):
    compiler = tmp_path / "clang"
    manager = Mock()
    manager.find_clang.return_value.executable.return_value = compiler
    manager.find_clang.return_value.version = "21.1.8"
    monkeypatch.setattr("sdkmgr.Manager", Mock(return_value=manager))
    return compiler


@pytest.mark.parametrize("platform,suffix,shared_suffix,errno", [
    ("linux", "", ".so", "__errno_location"),
    ("darwin", "", ".dylib", "__error"),
    ("win32", ".exe", ".dll", "_errno"),
])
def test_compilation_uses_host_linker_contract(tmp_path, monkeypatch, configured_compiler,
                                             platform, suffix, shared_suffix, errno):
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess([], 0, "", "")
    llvm = LLVM(configured_compiler, runner)
    monkeypatch.setattr(sys, "platform", platform)
    assert binary_suffix() == suffix
    assert binary_suffix(shared=True) == shared_suffix
    assert errno_symbol() == errno
    ir = ("define i32 @entry() { ret i32 0 }\ndefine internal i32 @hidden() { ret i32 1 }\n"
          '@counter = global i64 0\n@secret = private constant i32 1\n'
          '@not_defined_here = external global i64\n'
          'define i32 @"quoted.entry"() { ret i32 2 }\n')
    for shared in (False, True):
        result = llvm.compile(ir, tmp_path, shared=shared)
        assert result.name == "program" + (shared_suffix if shared else suffix)
        command = runner.run.call_args.args[0]
        assert ("-lm" in command) == (platform != "win32")
        assert ("-fPIC" in command) == (shared and platform != "win32")
        assert ("-dynamiclib" in command) == (shared and platform == "darwin")
        if platform == "win32":
            assert "-Wl,/NODEFAULTLIB:libcmt,/DEFAULTLIB:msvcrt" in command
            assert "--rtlib=compiler-rt" in command
            assert "-llegacy_stdio_definitions" in command
            if shared:
                assert (tmp_path / "program.ll").read_text() == _windows_exported_ir(ir)


def test_windows_exports_follow_tokens_not_lines_or_comments():
    source = '''
        ; define i32 @comment() { ret i32 1 }
        @missing = external global i32
        @local = private unnamed_addr constant [2 x i8] c"x\\00"
        @data = ; an initializer may refer to another symbol
            global ptr @missing
        define ; headers and definitions need not occupy a single line
            dso_local i32 @"visible.entry"() { ret i32 1 } define internal i32 @hidden() { ret i32 2 }
        define available_externally i32 @not_emitted() { ret i32 3 }
        define hidden i32 @hidden_function() { ret i32 7 }
        @hidden_data = hidden global i32 8
        @other = dllexport global i32 4
        define dllexport i32 @exported() { ret i32 5 }
        define external i32 @explicit() { ret i32 6 }
    '''
    expected = source.replace('@data =', '@data = dllexport ').replace(
        'dso_local i32 @"visible.entry"', 'dso_local dllexport  i32 @"visible.entry"')
    expected = expected.replace('define external i32', 'define external dllexport  i32')
    assert _windows_exported_ir(source) == expected
    assert _windows_exported_ir(expected) == expected


def test_linker_stdout_is_retained_in_compile_diagnostics(tmp_path, configured_compiler):
    runner = Mock()
    runner.run.side_effect = subprocess.CalledProcessError(
        1, [], output="LINK: missing runtime library", stderr="link failed")
    with pytest.raises(subprocess.CalledProcessError) as caught:
        LLVM(configured_compiler, runner).compile("define i32 @main() { ret i32 0 }", tmp_path)
    assert "LINK: missing runtime library" in caught.value.__notes__[0]
    assert "link failed" in caught.value.__notes__[0]


def test_shared_library_exports_public_functions_and_data(tmp_path):
    import _ctypes

    path = LLVM().compile('''
        @"quoted.counter" = global i64 7
        @hidden_state = hidden global i64 0
        @not_defined_here = external global i64
        define hidden i64 @hidden_helper() {
            %value = load i64, ptr @hidden_state
            ret i64 %value
        }
        define i64 @"quoted\\2Eentry"() {
            %value = load i64, ptr @"quoted.counter"
            %hidden = call i64 @hidden_helper()
            %result = add i64 %value, %hidden
            ret i64 %result
        }
        define internal i64 @hidden() { ret i64 99 }
    ''', tmp_path / "build, directory", shared=True)
    library = ctypes.CDLL(str(path))
    try:
        function = getattr(library, "quoted.entry")
        function.restype = ctypes.c_int64
        counter = ctypes.c_int64.in_dll(library, "quoted.counter")
        assert function() == counter.value == 7
        counter.value = 11
        assert function() == 11
        with pytest.raises(AttributeError):
            _ = library.hidden
        with pytest.raises(AttributeError):
            _ = library.hidden_helper
        with pytest.raises(ValueError):
            ctypes.c_int64.in_dll(library, "hidden_state")
    finally:
        unload = _ctypes.FreeLibrary if sys.platform == "win32" else _ctypes.dlclose
        unload(library._handle)


def test_readme_native_example(tmp_path):
    from pyjs.cli import main

    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    section = readme.split("Save this as `primes.py`", 1)[1]
    source = section.split("```python\n", 1)[1].split("```", 1)[0]
    path = tmp_path / "primes.py"
    path.write_text(source, encoding="utf-8")
    output = tmp_path / ("primes" + binary_suffix())
    assert main(["build", "--target", "native", str(path), "-o", str(output)]) == 0
    python = subprocess.run([sys.executable, path], capture_output=True, timeout=30)
    native = subprocess.run([output], capture_output=True, timeout=30)
    newline = b"\r\n" if sys.platform == "win32" else b"\n"
    assert (python.returncode, python.stdout, python.stderr) == (0, b"148933" + newline, b"")
    assert (native.returncode, native.stdout, native.stderr) == (0, b"148933\n", b"")


def test_python_comparison_preserves_unencodable_exception_diagnostics(tmp_path):
    result = LLVM()._run_python(
        'def main() -> int:\n    raise ValueError("bad \\udc80")\n', tmp_path, timeout=10)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.endswith("ValueError: bad \\udc80\n")
    assert "lost sys.stderr" not in result.stderr


@pytest.mark.parametrize("capacity", [0, 1, 4, 8])
def test_cpython_float_format_leaf_preserves_c99_sizing_and_termination(capacity):
    from pyjs import int32
    from pyjs.native.runtime.float_math import fixed_format, format_buffer
    from pyjs.native.runtime.pointers import Pointer

    buffer = ctypes.create_string_buffer(b"xxxxxxxx", 8)
    assert format_buffer(Pointer(ctypes.addressof(buffer)), capacity, fixed_format(), int32(2), 1.25) == 4
    expected = b"1.25"[:capacity - 1] + b"\0" if capacity else b""
    assert buffer.raw.startswith(expected)
    assert buffer.raw[capacity:] == b"x" * (8 - capacity)


@pytest.mark.parametrize("source,expected", [("def main() -> int: return 0", 0),
                                           ('def main() -> str: return "output"', errno.EBADF)])
def test_executable_startup_tolerates_closed_standard_streams(tmp_path, source, expected):
    ir = transpile_llvm(source).replace("define i32 @main()", "define i32 @pyjs.start()")
    close = "_close" if sys.platform == "win32" else "close"
    ir += f'''
        declare i32 @{close}(i32)
        define i32 @main() {{
            %out = call i32 @{close}(i32 1)
            %err = call i32 @{close}(i32 2)
            %result = call i32 @pyjs.start()
            ret i32 %result
        }}
    '''
    executable = LLVM().compile(ir, tmp_path)
    result = subprocess.run([executable], capture_output=True, timeout=10)
    assert (result.returncode, result.stdout, result.stderr) == (expected, b"", b"")
