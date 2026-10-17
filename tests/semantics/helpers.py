import difflib
import subprocess
import sys
import textwrap
from dataclasses import dataclass

from pyjs.javascript.source import compile_source
from pyjs.tooling.node import Node


@dataclass(frozen=True)
class RuntimeResult:
    returncode: int
    stdout: str
    stderr: str


def format_semantics_failure(
    expected: RuntimeResult,
    actual: RuntimeResult,
    javascript: str,
) -> str:
    expected_lines = [
        f"returncode: {expected.returncode}\n",
        f"stdout: {expected.stdout!r}\n",
        f"stderr: {expected.stderr!r}\n",
    ]
    actual_lines = [
        f"returncode: {actual.returncode}\n",
        f"stdout: {actual.stdout!r}\n",
        f"stderr: {actual.stderr!r}\n",
    ]
    difference = "".join(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="CPython",
            tofile="JavaScript",
        )
    )
    return f"Runtime results differ:\n{difference}\nGenerated JavaScript:\n{javascript}"


def run_python(source: str) -> RuntimeResult:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        capture_output=True,
        check=False,
        text=True,
    )
    return RuntimeResult(result.returncode, result.stdout, result.stderr)


def run_javascript(source: str) -> tuple[RuntimeResult, str]:
    with compile_source(
        textwrap.dedent(source),
        filename="<semantics>",
        module_name="_pyjs_semantics",
    ) as compilation:
        javascript = compilation.javascript + """\
Promise.resolve(__pyjsEntry__.main()).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    result = Node().run_javascript(javascript)
    return RuntimeResult(result.returncode, result.stdout, result.stderr), javascript


def assert_semantics(source: str) -> None:
    __tracebackhide__ = True
    expected = run_python(source)
    actual, javascript = run_javascript(source)
    if expected != actual:
        raise AssertionError(
            format_semantics_failure(expected, actual, javascript)
        ) from None
