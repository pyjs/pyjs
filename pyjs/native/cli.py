"""File-based native execution; compiler imports stay out of the JavaScript CLI."""

import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
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
    output = {"stdout": "", "stderr": ""}
    try:
        # Module discovery can import parent packages before analysis begins.
        # Real streams preserve .buffer/.fileno(); descriptor redirection also
        # catches os.write and inherited subprocess output, not just print().
        # This is process-wide, like the CLI's existing sys.path manipulation.
        with ExitStack() as stack:
            captures = {}
            for name, descriptor, redirect in (("stdout", 1, redirect_stdout), ("stderr", 2, redirect_stderr)):
                previous = getattr(sys, name)
                previous.flush()
                inheritable = os.get_inheritable(descriptor)
                saved = os.dup(descriptor)
                stack.callback(os.close, saved)
                stack.callback(os.dup2, saved, descriptor, inheritable=inheritable)
                capture = stack.enter_context(TemporaryFile(mode="w+b", buffering=0))
                stream = stack.enter_context(io.TextIOWrapper(
                    capture, encoding="utf-8", errors="backslashreplace", newline="", write_through=True,
                ))
                os.dup2(capture.fileno(), descriptor, inheritable=inheritable)
                stack.enter_context(redirect(stream))
                captures[name] = capture, previous
            try:
                yield output
            finally:
                for name, (capture, previous) in captures.items():
                    # Cached Python streams may have buffered descriptor writes.
                    previous.flush()
                    original = getattr(sys, f"__{name}__")
                    if original is not None and original is not previous:
                        original.flush()
                    capture.seek(0)
                    output[name] = capture.read().decode("utf-8", errors="backslashreplace")
    except BaseException as error:
        for name, value in output.items():
            if value:
                if isinstance(error, Exception):
                    error.add_note(f"Analysis {name}:\n{value}")
                else:
                    # argparse's SystemExit does not display exception notes.
                    print(value, file=sys.stderr, end="")
        raise


def _emit(program, *, is_file, entry="main", wrap=None):
    with _source_path(program, is_file=is_file):
        return transpile_llvm(
            program.source,
            filename=program.filename,
            # File inputs are scripts, not importable module names: a math.py
            # script must not replace stdlib math in the compiler's sys.modules.
            # Keep main guards inactive; preserve explicit package module names.
            module_name=("__pyjs_main__" if is_file or program.module_name == "__main__"
                         else program.module_name),
            entry_point=entry,
            wrap=wrap,
        )


def build(args, load_program, command_parser, *, is_file, entry="main", wrap=None):
    if args.only_js or args.include_main or args.args is not None:
        command_parser.error("--only-js, --include-main and --args are browser build options")
    with _analysis_output() as output_text:
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
    print(output_text["stdout"] + output_text["stderr"], file=sys.stderr, end="")
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
    with _analysis_output() as output_text:
        program = load_program()
        ir = _emit(program, is_file=args.source not in (None, "-"))
    stdout, stderr = output_text["stdout"], output_text["stderr"]
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
                            "reason": "nonzero_exit" if result.returncode else "output_mismatch",
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
        if matches:
            print("Output matches: yes")
            print(outputs["python"]["stdout"], end="")
            if sys.platform == "win32":
                print("CPython launcher configures UTF-8/binary newlines; launcher startup included.")
            print(f"Median of {args.samples} runs after {args.warmups} warmups (process startup included):")
            print(f"  CPython {sys.version.split()[0]}: {statistics['python']['median'] * 1000:.3f} ms")
            print(f"  Native: {statistics['native']['median'] * 1000:.3f} ms")
            print(f"  Speedup: {ratio:.2f}x (compilation excluded)")
        else:
            if mismatch["reason"] == "nonzero_exit":
                print(f"Validation failed: {mismatch['target']} exited with status {mismatch['actual']['exit_code']}")
            else:
                print("Output matches: NO")
            print(json.dumps(payload["correctness"], indent=2))
    return 0 if matches else 1
