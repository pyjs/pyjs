"""Exercise the installed-command boundary with a real compiler on every host."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pyjs.native.platform import binary_suffix
from tests.native.runtime_support import TRAP_RETURN_CODES


def cli(*arguments, cwd, stdin=None):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2]))
    return subprocess.run(
        [sys.executable, "-m", "pyjs", *arguments], cwd=cwd, env=env,
        input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


@pytest.mark.parametrize("mode", ["file", "module", "package", "command", "stdin"])
def test_native_input_modes(tmp_path, mode):
    source = "print('hello')\n"
    if mode in ("file", "module"):
        (tmp_path / "hello.py").write_text(source, encoding="utf-8")
        arguments = ["hello.py"] if mode == "file" else ["-m", "hello"]
    elif mode == "package":
        package = tmp_path / "hello"
        package.mkdir()
        (package / "__init__.py").touch()
        (package / "greeting.py").write_text("def message() -> str: return 'hello'\n", encoding="utf-8")
        (package / "__main__.py").write_text("from .greeting import message\nprint(message())\n", encoding="utf-8")
        arguments = ["-m", "hello"]
    else:
        arguments = ["-c", source] if mode == "command" else ["-"]
    result = cli("--target", "native", *arguments, cwd=tmp_path,
                 stdin=source if mode == "stdin" else None)
    assert (result.returncode, result.stdout, result.stderr) == (0, "hello\n", "")


def test_file_imports_guarded_main_and_retained_build(tmp_path):
    project = tmp_path / "project with spaces"
    project.mkdir()
    (project / "helper.py").write_text("def value() -> int: return 23\n", encoding="utf-8")
    source = project / "__main__.py"
    source.write_text(
        "from helper import value\n"
        "def main() -> None:\n    print(value())\n"
        "if __name__ == '__main__':\n    main()\n", encoding="utf-8")
    binary = tmp_path / ("retained program" + binary_suffix())
    result = cli("build", "--target", "native", str(source), "-o", str(binary), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"Wrote {binary}\n"  # Compilation did not execute main.
    assert sorted(path.name for path in project.glob("*.ll")) == []
    native = subprocess.run([binary], capture_output=True, timeout=10)
    assert (native.returncode, native.stdout, native.stderr) == (0, b"23\n", b"")


def test_module_build_with_non_main_entry(tmp_path):
    (tmp_path / "a.py").write_text("def start() -> str: return 'built'\n", encoding="utf-8")
    result = cli("build", "--target", "native", "a:start", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    native = subprocess.run([tmp_path / ("a" + binary_suffix())], capture_output=True, timeout=10)
    assert (native.returncode, native.stdout, native.stderr) == (0, b"built", b"")


@pytest.mark.parametrize("entry", ["main", "typo"])
def test_explicit_missing_entry_is_not_replaced_with_an_empty_program(tmp_path, entry):
    (tmp_path / "sample.py").write_text("def start() -> str: return 'built'\n", encoding="utf-8")
    result = cli("build", "--target", "native", f"sample:{entry}", cwd=tmp_path)
    assert result.returncode == 2
    assert entry in result.stderr
    assert not (tmp_path / ("sample" + binary_suffix())).exists()


@pytest.mark.parametrize("body,code,stdout,stderr", [
    ("print('hello')", 0, "hello\n", ""),
    ("return 7", 7, "", ""),
    ("raise ValueError('bad value')", None, "", "ValueError: bad value"),
])
def test_native_process_streams_and_exit(tmp_path, body, code, stdout, stderr):
    annotation = "int" if body.startswith("return") else "None"
    result = cli("--target", "native", "-c", f"def main() -> {annotation}:\n    {body}\n",
                 cwd=tmp_path, stdin="from stdin\n")
    assert result.stdout == stdout
    if code is None:
        # Native uncaught exceptions currently print a traceback and trap. The
        # command normalizes POSIX signals to their conventional shell status.
        assert result.returncode in {128 - value if value < 0 else value for value in TRAP_RETURN_CODES}
    else:
        assert result.returncode == code, result.stderr
    if stderr:
        assert stderr in result.stderr
    else:
        assert result.stderr == ""


def test_native_json_and_ir(tmp_path):
    source = "print('héllo')\n"
    result = cli("--target", "native", "--json", "-c", source, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert (payload["exit_code"], payload["stdout"], payload["stderr"]) == (0, "héllo\n", "")
    assert payload["compilation"]["seconds"] > 0
    ir = cli("--target", "native", "--src", "-c", source, cwd=tmp_path)
    assert ir.returncode == 0, ir.stderr
    assert "define i32 @main()" in ir.stdout
    assert "héllo\n" not in ir.stdout  # Printed IR, not an executed program.


def test_initialization_output_does_not_corrupt_json_or_ir(tmp_path):
    source = "def main() -> None:\n    print('runtime')\nprint('initialization')\n"
    result = cli("--target", "native", "--json", "-c", source, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["stdout"] == "runtime\n"
    assert payload["compilation"]["stdout"] == "initialization\n"
    assert result.stderr == ""

    result = cli("--target", "native", "--src", "-c", source, cwd=tmp_path)
    assert result.returncode == 0
    assert result.stderr == "initialization\n"
    assert "initialization" not in result.stdout
    assert "define i32 @main()" in result.stdout

    result = cli("--target", "native", "--json", "-c",
                 source.replace("print('runtime')", "missing_name()"), cwd=tmp_path)
    assert result.returncode == 2
    error = json.loads(result.stdout)["error"]
    assert "missing_name" in error["message"]
    assert error["notes"] == ["Analysis stdout:\ninitialization\n"]


def test_package_discovery_output_is_compilation_output(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "__init__.py").write_text("print('package initialization')\n", encoding="utf-8")
    (package / "app.py").write_text("def main() -> None: print('runtime')\n", encoding="utf-8")
    result = cli("--target", "native", "--json", "-m", "package.app", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["stdout"] == "runtime\n"
    assert payload["compilation"]["stdout"] == "package initialization\n"
    assert result.stderr == ""
    result = cli("build", "--target", "native", "package.app", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"Wrote app{binary_suffix()}\n"
    assert result.stderr == "package initialization\n"


@pytest.mark.parametrize("source,matches", [
    ("print(sum([1, 2, 3]))\n", True),
    ("print('héllo\\r\\nworld')\n", True),
    ("def main() -> str: return 'native return value'\n", False),
])
def test_native_performance_compares_real_processes(tmp_path, source, matches):
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    result = cli("--target", "native", "--perf", "--json", "--samples", "2", "--warmups", "1",
                 str(path), cwd=tmp_path)
    assert result.returncode == (0 if matches else 1), result.stderr
    payload = json.loads(result.stdout)
    assert payload["correctness"]["matches"] is matches
    assert (payload["correctness"]["first_mismatch"] is None) is matches
    assert (payload["performance"]["python_to_native_ratio"] is not None) is matches
    assert payload["compilation"]["seconds"] > 0
    for target in ("python", "native"):
        measurements = payload["performance"][target]
        assert len(measurements["samples"]) == 2
        assert measurements["median"] > 0


def test_build_does_not_overwrite_source_or_old_executable_on_failure(tmp_path):
    source = tmp_path / "broken.py"
    text = "def main() -> None:\n    missing_name()\n"
    source.write_text(text, encoding="utf-8")
    result = cli("build", "--target", "native", str(source), "-o", str(source), cwd=tmp_path)
    assert result.returncode == 2
    assert "must not overwrite" in result.stderr
    assert source.read_text(encoding="utf-8") == text
    binary = tmp_path / ("previous" + binary_suffix())
    binary.write_bytes(b"old build")
    result = cli("build", "--target", "native", str(source), "-o", str(binary), cwd=tmp_path)
    assert result.returncode == 2
    assert "missing_name" in result.stderr
    assert binary.read_bytes() == b"old build"


@pytest.mark.parametrize("arguments,message", [
    (["--loops", "1", "-c", "pass"], "use --samples, not --loops"),
    (["--samples", "0", "-c", "pass"], "--samples must be positive"),
    (["--json", "--src", "-c", "pass"], "cannot be combined"),
    (["--json", "-c", "def broken(:"], "SyntaxError"),
    (["--json", "missing.py"], "cannot open"),
])
def test_native_cli_diagnostics(tmp_path, arguments, message):
    result = cli("--target", "native", *arguments, cwd=tmp_path)
    assert result.returncode == 2
    assert message in result.stdout + result.stderr


def test_performance_retains_an_earlier_mismatch(monkeypatch, capsys):
    from types import SimpleNamespace

    from pyjs.native.cli import _PYTHON_BINARY_STDIO, _perf

    results = iter((b"good\n", b"bad\n", b"good\n", b"good\n"))
    commands = []

    def execute(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, next(results), b"")

    monkeypatch.setattr(subprocess, "run", execute)
    args = SimpleNamespace(module=None, code="pass", source=None, warmups=1, samples=1, json=True)
    program = SimpleNamespace(source="pass", filename="<string>")
    assert _perf(args, program, Path("program"), {"seconds": 1}) == 1
    report = json.loads(capsys.readouterr().out)
    mismatch = report["correctness"]["first_mismatch"]
    assert (mismatch["run"], mismatch["target"], mismatch["actual"]["stdout"]) == (1, "native", "bad\n")
    assert mismatch["expected"]["stdout"] == "good\n"
    assert report["performance"]["python_to_native_ratio"] is None
    python_command = [sys.executable, "-c", "pass"]
    if sys.platform == "win32":
        python_command = [sys.executable, "-c", _PYTHON_BINARY_STDIO, "-c", "pass"]
    assert commands[0] == commands[3] == python_command
    assert commands[1] == commands[2] == [Path("program")]


@pytest.mark.parametrize("mode", ["file", "module", "command", "stdin"])
def test_binary_stdio_launcher_preserves_source_modes_and_bytes(tmp_path, mode):
    from pyjs.native.cli import _PYTHON_BINARY_STDIO

    # Exercise the Windows launcher on every host, including imports from a
    # different script directory. Raw CR/LF must survive, not be normalized.
    text = "print('héllo\\r\\nworld')\n"
    if mode == "file":
        project = tmp_path / "sub directory"
        project.mkdir()
        (project / "helper.py").write_text(text, encoding="utf-8")
        source = project / "program.py"
        source.write_text("import helper\n", encoding="utf-8")
        arguments = [str(source)]
    elif mode == "module":
        (tmp_path / "sample.py").write_text(text, encoding="utf-8")
        arguments = ["-m", "sample"]
    else:
        arguments = ["-c", text] if mode == "command" else ["-"]
    result = subprocess.run([sys.executable, "-c", _PYTHON_BINARY_STDIO, *arguments],
                            cwd=tmp_path, capture_output=True, timeout=10,
                            input=text.encode("utf-8") if mode == "stdin" else None)
    assert (result.returncode, result.stdout, result.stderr) == (0, "héllo\r\nworld\n".encode(), b"")
