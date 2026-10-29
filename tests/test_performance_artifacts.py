import gzip

import pytest

from perf.artifacts import (
    algorithm_ranges,
    code_size,
    fold_header,
    javascript_ranges,
    recorded_code_size,
)
from pyjs.javascript.source import compile_source

SOURCE = '''class Box:
    def __init__(self, value: int):
        self.value = value
def helper(value: int) -> int:
    return value + 1
def kernel(value: int) -> int:
    return helper(value)
'''


@pytest.mark.parametrize("target, text, expected", [
    ("pyjs-js", """const modules = new Map();
define('perf_workload', function (__export_js__, __import_js__) {
function kernel(value) {
    return helper(value);
}
__export_js__.kernel = kernel;
function batch(value) { return kernel(value); }
__export_js__.batch = batch;
});
define('runtime', function () {
function kernel(value) { return 0; }
__export_js__.kernel = kernel;
});
""", [(2, 5)]),
    ("pyjs-llvm", """define i64 @runtime(i64 %value) {
  ret i64 0
}
define i64 @fn.kernel(i64 %value) {
  ret i64 %value
}
define i64 @fn.pyjs_main(i64 %value) {
  ret i64 %value
}
""", [(3, 6)]),
    ("pyjs-jvm", """Classfile /tmp/PyjsProgram.class
Constant pool:
{
  public static long kernel(long);
    Code:
      0: lload_0
      1: lreturn
  public static void main(java.lang.String[]);
    Code:
      0: return
}
Classfile /tmp/Driver.class
{
  public static long kernel(long);
}
""", [(3, 7)]),
])
def test_only_algorithm_declarations_are_open_by_default(target, text, expected):
    assert algorithm_ranges(SOURCE, target, text) == expected
    assert fold_header(SOURCE, target, text) == ";".join(f"{a}:{b}" for a, b in expected)
    assert algorithm_ranges(SOURCE, target, "unrecognized output") == []


def test_js_scope_metadata_keeps_algorithm_and_not_entry_or_runtime():
    source = '''from pyjs import js
@js
def kernel(value: int) -> int:
    return value + 1
@js
def main(value: int) -> int:
    return kernel(value)
'''
    with compile_source(source, filename="workload.py", module_name="perf_workload") as result:
        ranges = javascript_ranges(result.source_map, SOURCE)
        visible = "\n".join("\n".join(result.javascript.split("\n")[a:b]) for a, b in ranges)
        assert "function kernel" in visible
        assert "return value + 1" in visible
        assert "function main" not in visible and "moduleCache" not in visible


@pytest.mark.parametrize("target, names", [
    ("cpython", ["program.py", "driver.py"]),
    ("javascript", ["program.cjs"]), ("pyjs-js", ["program.cjs"]),
    ("java", ["Driver.class", "Kernel.class"]),
    ("pyjs-jvm", ["Driver.class", "PyjsProgram.class", "PyjsProgram$runtime.class"]),
    ("rust", ["program"]), ("pyjs-llvm", ["program"]),
])
def test_code_size_counts_all_runnable_bytes_not_disassembly_or_logs(tmp_path, target, names):
    for name in names:
        (tmp_path / name).write_bytes(b"runtime and algorithm\n" * 100)
    (tmp_path / "generated.ll").write_text("not the shipped binary" * 1000)
    (tmp_path / "bytecode.txt").write_text("not shipped disassembly" * 1000)
    (tmp_path / "jit.log").write_text("not shipped diagnostics" * 1000)
    result = code_size(target, tmp_path)
    assert result["bytes"] == sum((tmp_path / name).stat().st_size for name in names)
    assert set(result["files"]) == set(names)
    if target in {"javascript", "pyjs-js"}:
        assert result["gzip_bytes"] == len(gzip.compress((tmp_path / "program.cjs").read_bytes(), mtime=0))
    else:
        assert "gzip_bytes" not in result


def test_old_snapshot_sizes_require_matching_retained_artifacts(tmp_path):
    directory = tmp_path / "build" / "sample" / "pyjs-js"
    directory.mkdir(parents=True)
    program = directory / "program.cjs"
    program.write_text("runtime(); kernel(); driver();")
    row = {"case": "sample", "target": "pyjs-js", "artifacts": {"build/sample/pyjs-js/program.cjs": program.stat().st_size}}
    assert recorded_code_size(row, tmp_path)["bytes"] == program.stat().st_size
    program.write_text("changed")
    assert recorded_code_size(row, tmp_path) is None
