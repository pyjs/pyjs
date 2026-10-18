"""File-based native execution; compiler imports stay out of the JavaScript CLI."""

import io
import json
import shutil
import subprocess
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from pyjs.native.llvm import transpile_llvm
from pyjs.native.platform import binary_suffix
from pyjs.tooling.llvm import LLVM
from pyjs.tooling.perf import Benchmark

# Windows CPython text streams otherwise translate LF to CRLF and can use a
# legacy encoding; native streams are UTF-8/binary. Configure the reference
# process, rather than normalizing captured bytes and hiding real differences.
# This small launcher runs only on Windows; its startup is included in timing.
_PYTHON_BINARY_STDIO = """\
import sys
sys.stdout.reconfigure(encoding="utf-8", newline="")
sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace", newline="")
arguments = sys.argv[1:]
mode = arguments[0]
if mode == "-m":
    import runpy
    sys.argv = arguments[1:]
    runpy.run_module(sys.argv[0], run_name="__main__", alter_sys=True)
elif mode in ("-c", "-"):
    source = arguments[1] if mode == "-c" else sys.stdin.buffer.read().decode("utf-8")
    filename = "<string>" if mode == "-c" else "<stdin>"
    sys.argv = [mode]
    namespace = {"__name__": "__main__", "__package__": None, "__spec__": None}
    if mode == "-":
        namespace["__file__"] = filename
    exec(compile(source, filename, "exec"), namespace)
else:
    import os
    import runpy
    sys.argv = arguments
    sys.path[0] = os.path.dirname(os.path.abspath(mode))
    runpy.run_path(mode, run_name="__main__")
"""


@contextmanager
def _source_path(program, *, is_file):
    # Match Python's script-directory import lookup without leaving it on the
    # host interpreter's path when the CLI is called programmatically.
    previous = sys.path[:]
    if is_file:
        sys.path.insert(0, str(Path(program.filename).resolve().parent))
    try:
        yield
    finally:
        sys.path[:] = previous


@contextmanager
def _analysis_output():
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        # Module discovery can import parent packages before analysis begins.
        # Capture both stages, keeping initialization out of JSON/LLVM artifacts.
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield stdout, stderr
    except BaseException as error:
        for name, stream in (("stdout", stdout), ("stderr", stderr)):
            if stream.getvalue():
                if isinstance(error, Exception):
                    error.add_note(f"Analysis {name}:\n{stream.getvalue()}")
                else:
                    # argparse's SystemExit does not display exception notes.
                    print(stream.getvalue(), file=sys.stderr, end="")
        raise


def _emit(program, *, is_file, entry="main", wrap=None):
    with _source_path(program, is_file=is_file):
        return transpile_llvm(
            program.source,
            filename=program.filename,
            # A file called __main__.py must not execute its guarded entry
            # during analysis. Package module names remain intact.
            module_name=("__pyjs_main__" if program.module_name == "__main__"
                         else program.module_name),
            entry_point=entry,
            wrap=wrap,
        )


def build(args, load_program, command_parser, *, is_file, entry="main", wrap=None):
    if args.only_js or args.include_main or args.args is not None:
        command_parser.error("--only-js, --include-main and --args are browser build options")
    with _analysis_output() as (stdout, stderr):
        program = load_program()
        output = args.output or Path(Path(program.filename).stem + binary_suffix())
        if output.resolve() == Path(program.filename).resolve():
            command_parser.error("the executable must not overwrite the Python source")
        if sys.platform == "win32" and output.suffix.lower() != ".exe":
            output = output.with_name(output.name + ".exe")
        if output.is_dir():
            command_parser.error("the executable output must be a file, not a directory")
        if (output.resolve() == Path(program.filename).resolve()
                or (output.exists() and Path(program.filename).exists() and output.samefile(program.filename))):
            command_parser.error("the executable must not overwrite the Python source")
        ir = _emit(program, is_file=is_file, entry=entry, wrap=wrap)
    print(stdout.getvalue() + stderr.getvalue(), file=sys.stderr, end="")
    # Compile away from user files: neither the intermediate IR nor the linker
    # may overwrite a nearby source, and a failed build leaves the old binary.
    with TemporaryDirectory(prefix="pyjs-native-") as directory:
        executable = LLVM().compile(ir, Path(directory))
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, output)
    print(f"Wrote {output}")
    return 0


def run(args, load_program, command_parser):
    if args.loops is not None:
        command_parser.error("native --perf measures whole processes; use --samples, not --loops")
    started = perf_counter()
    with _analysis_output() as (stdout, stderr):
        program = load_program()
        ir = _emit(program, is_file=args.source not in (None, "-"))
    stdout, stderr = stdout.getvalue(), stderr.getvalue()
    if not args.json:
        print(stdout + stderr, file=sys.stderr, end="")
    if args.src or args.src_all:
        # LLVM emits one linked module, including its reachable dependencies.
        print(ir, end="" if ir.endswith("\n") else "\n")
        return 0
    llvm = LLVM()
    with TemporaryDirectory(prefix="pyjs-native-") as directory:
        executable = llvm.compile(ir, Path(directory))
        compilation = {
            "seconds": perf_counter() - started,
            "compiler": llvm.version,
            "optimization": "O2",
            "stdout": stdout,
            "stderr": stderr,
        }
        if args.perf:
            return _perf(args, program, executable, compilation)
        if args.v and not args.json:
            print(ir, file=sys.stderr)
        # Normal execution inherits stdin/stdout/stderr and has no test timeout.
        result = subprocess.run([executable], capture_output=args.json)
        if args.json:
            payload = {"input": program.filename, "compilation": compilation, **_output(result)}
            if args.v:
                payload["llvm_ir"] = ir
            print(json.dumps(payload, indent=2))
        return result.returncode if result.returncode >= 0 else 128 - result.returncode


def _output(result):
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout.decode("utf-8", errors="backslashreplace"),
        "stderr": result.stderr.decode("utf-8", errors="backslashreplace"),
    }


def _perf(args, program, executable, compilation):
    if args.module is not None:
        python_command = [sys.executable, "-m", args.module]
    elif args.code is not None:
        python_command = [sys.executable, "-c", program.source]
    else:
        python_command = [sys.executable, args.source]
    if sys.platform == "win32":
        python_command = [sys.executable, "-c", _PYTHON_BINARY_STDIO, *python_command[1:]]
    commands = {"python": python_command, "native": [executable]}
    samples = {"python": [], "native": []}
    outputs = {}
    reference = None
    expected = None
    mismatch = None
    matches = True
    # Compare every run, including warmups, to the same byte-exact reference.
    # Alternating order limits systematic cache/load bias. Both measurements
    # include process startup, shutdown and captured output, not compilation.
    for index in range(args.warmups + args.samples):
        for name in (("python", "native") if index % 2 == 0 else ("native", "python")):
            started = perf_counter()
            stdin = program.source.encode("utf-8") if name == "python" and args.source == "-" else b""
            result = subprocess.run(commands[name], input=stdin, capture_output=True)
            elapsed = perf_counter() - started
            actual = (result.returncode, result.stdout, result.stderr)
            if reference is None:
                reference = actual
                expected = _output(result)
            if mismatch is None and (actual != reference or result.returncode != 0):
                mismatch = {"run": index + 1, "target": name,
                            "expected": expected, "actual": _output(result)}
            matches &= actual == reference and result.returncode == 0
            outputs[name] = _output(result)
            if index >= args.warmups:
                samples[name].append(elapsed)
    statistics = {name: Benchmark(1, tuple(values)).json() for name, values in samples.items()}
    ratio = statistics["python"]["median"] / statistics["native"]["median"] if matches else None
    payload = {
        "input": program.filename,
        "compilation": compilation,
        "correctness": {"matches": matches, "first_mismatch": mismatch, **outputs},
        "performance": {
            **statistics,
            "python_to_native_ratio": ratio,
            "scope": "whole process, including startup and output; compilation excluded",
            "python_version": sys.version.split()[0],
            "python_stdio": "UTF-8 without newline translation" if sys.platform == "win32" else "default",
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Compilation: {compilation['seconds']:.3f} s ({compilation['compiler']}, O2)")
        print(f"Output matches: {'yes' if matches else 'NO'}")
        if matches:
            print(outputs["python"]["stdout"], end="")
            if sys.platform == "win32":
                print("CPython launcher configures UTF-8/binary newlines; launcher startup included.")
            print(f"Median of {args.samples} runs after {args.warmups} warmups (process startup included):")
            print(f"  CPython {sys.version.split()[0]}: {statistics['python']['median'] * 1000:.3f} ms")
            print(f"  Native: {statistics['native']['median'] * 1000:.3f} ms")
            print(f"  Speedup: {ratio:.2f}x (compilation excluded)")
        else:
            print(json.dumps(mismatch, indent=2))
    return 0 if matches else 1
