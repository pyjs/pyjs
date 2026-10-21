"""Foreign declarations and missing APIs are not executable native source."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("module, name, expression", [
    ("pathlib", "PureWindowsPath", 'str(value("C:/a", "b"))'),
    ("pathlib", "Path", 'value("a").name'),
    ("datetime", "timezone", "str(value.utc)"),
    ("datetime", "time", "str(value(1, 2))"),
    ("datetime", "UTC", "str(value)"),
    ("uuid", "uuid4", "str(value())"),
])
@pytest.mark.parametrize("qualified", [False, True])
def test_used_missing_library_names_fail_at_source(module, name, expression, qualified):
    if qualified:
        statement = f"import {module} as library"
        expression = expression.replace("value", f"library.{name}")
        message = f"has no attribute '{name}'"
    else:
        statement = f"from {module} import {name} as value"
        message = f"{module}.{name} is not supported by pyjs.native.{module}"
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm(f"{statement}\ndef main() -> str:\n    return {expression}\n")
    assert caught.value.lineno in (1, 3)
    assert name in caught.value.text


@pytest.mark.parametrize("source, message", [
    ('''from pyjs.java.concurrent import Runnable, Thread
class Task(Runnable):
    def __init__(self, log: list[str]):
        self.log = log
    def run(self) -> None:
        self.log.append("ran")
def main() -> str:
    log: list[str] = []
    worker = Thread(Task(log))
    worker.start()
    worker.join()
    return str(len(log))
''', "cannot inherit JVM-only declarations"),
    ('''from pyjs.java.concurrent import AtomicBoolean
def main() -> str:
    return str(AtomicBoolean(True).get())
''', "cannot allocate class AtomicBoolean"),
    ('''from pyjs.java.concurrent import AtomicBoolean
class Flag(AtomicBoolean):
    pass
def main() -> str:
    return str(Flag(True).get())
''', "cannot inherit JVM-only declarations"),
])
def test_jvm_declarations_do_not_supply_native_implementations(source, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(source)


def test_rebound_missing_import_is_not_an_unsupported_dependency():
    result = LLVM().assert_matches_python('''
from datetime import UTC
UTC = "application value"
def main() -> str:
    return UTC
''')
    assert result.native.stdout == "application value"


def test_shader_native_class_keeps_its_python_cpu_fallback():
    result = LLVM().assert_matches_python('''
from pyjs import wgsl
@wgsl.native
class Scalar:
    def __init__(self, value: int):
        self.value = value
    def read(self) -> int:
        return self.value
def main() -> str:
    return str(Scalar(42).read())
''')
    assert result.native.stdout == "42"


@pytest.mark.parametrize("qualified", [False, True])
def test_missing_import_cannot_escape_through_reexport(tmp_path, monkeypatch, qualified):
    (tmp_path / "host_paths.py").write_text("from pathlib import PureWindowsPath as WindowsPath\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    if qualified:
        statement, expression = "import host_paths", "host_paths.WindowsPath"
    else:
        statement, expression = "from host_paths import WindowsPath", "WindowsPath"
    with pytest.raises(CompilationError, match="PureWindowsPath is not supported") as caught:
        transpile_llvm(f'{statement}\ndef main() -> str:\n    return str({expression}("a", "b"))\n')
    assert caught.value.lineno is not None


def test_reached_class_missing_library_alias_has_location():
    with pytest.raises(CompilationError, match="PureWindowsPath is not supported") as caught:
        transpile_llvm('''from pathlib import PureWindowsPath
class Record:
    kind = PureWindowsPath
    def __init__(self, value: int):
        self.value = value
def main() -> str:
    return str(Record(3).value)
''')
    assert caught.value.lineno == 3
    assert "kind = PureWindowsPath" in caught.value.text


@pytest.mark.parametrize("module", ["datetime", "pathlib", "uuid", "math", "itertools"])
def test_mapped_library_star_import_has_location(module):
    with pytest.raises(CompilationError, match="Star imports from mapped libraries") as caught:
        transpile_llvm(f'\nfrom {module} import *\ndef main() -> str:\n    return "ok"\n')
    assert caught.value.lineno == 2
    assert f"from {module} import *" in caught.value.text
