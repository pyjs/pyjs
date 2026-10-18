import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("body", ["pass", "return None", "print('hello')"])
def test_none_entry_returns_success(tmp_path, body):
    result = LLVM().run_source(f"def main() -> None:\n    {body}\n", directory=tmp_path)
    assert result.returncode == 0
    assert result.stdout == ("hello\n" if "print" in body else "")
    assert result.stderr == ""


def test_native_source_can_wrap_top_level_statements(tmp_path):
    llvm = LLVM()
    ir = transpile_llvm("print('hello')\n", wrap=None)
    executable = llvm.compile(ir, tmp_path)
    result = llvm.runner.run([executable], capture_output=True)
    assert result.stdout == "hello\n"
