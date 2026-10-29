import gzip
import hashlib
import json

import pytest

from perf.app import mount
from perf.artifacts import (
    algorithm_ranges,
    code_size,
    fold_header,
    javascript_ranges,
    recorded_code_size,
)
from perf.harness.build import ROOT, build
from pyjs.javascript.source import compile_source
from pyjs.server.dev import Application, Server
from tests.test_dev_server import request

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


@pytest.mark.parametrize("case, method", [
    ("bounce", "step()"), ("objects", "score()"),
    ("binarytrees", "count()"), ("nbody", "constructor("),
])
def test_fresh_js_manifests_include_algorithm_class_methods(tmp_path, case, method):
    output = tmp_path / case
    build(case, "pyjs-js", output, {"node": {"path": "node"}})
    text = (output / "generated.js").read_text()
    metadata = json.loads((output / "source-ranges.json").read_text())
    visible = "\n".join("\n".join(text.split("\n")[a:b]) for a, b in metadata["ranges"])
    assert "constructor(" in visible
    assert method in visible
    assert "function kernel" in visible
    assert "function batch" not in visible and "function main" not in visible
    source = (ROOT / "cases" / case / "workload.py").read_text()
    assert fold_header(source, "pyjs-js", text, metadata) == ";".join(
        f"{a}:{b}" for a, b in metadata["ranges"])


def test_js_method_scope_ownership_excludes_same_named_adapter_methods():
    source = '''class Box:
    def __init__(self, value: int):
        self.value = value
    def score(self) -> int:
        return self.value + 1
def kernel(value: int) -> int:
    return Box(value).score()
'''
    entry = ("from pyjs import js\n" + source.replace("class Box:", "@js\nclass Box:")
             .replace("def kernel", "@js\ndef kernel") + '''
@js
class Adapter:
    def score(self) -> int:
        return 777
@js
def main() -> int:
    return kernel(2) + Adapter().score()
''')
    with compile_source(entry, filename="workload.py", module_name="perf_workload") as result:
        ranges = javascript_ranges(result.source_map, source)
        visible = "\n".join("\n".join(result.javascript.split("\n")[a:b]) for a, b in ranges)
        assert "constructor(value)" in visible
        assert "return this.value + 1;" in visible
        assert "function kernel" in visible
        assert "return 777;" in result.javascript and "return 777;" not in visible
        assert "function main" not in visible


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


@pytest.mark.parametrize("ranges", [None, "0:1", [[0]], [[-1, 1]], [[0, 100]],
                                    [[1, 2], [0, 1]], [[0, True]]])
def test_invalid_fold_metadata_leaves_source_unfolded(ranges):
    text = "first\nsecond\n"
    metadata = {"schema": 1, "sha256": hashlib.sha256(text.encode()).hexdigest(), "ranges": ranges}
    assert fold_header(SOURCE, "pyjs-js", text, metadata) == ""


def test_unversioned_class_manifest_uses_complete_declaration_fallback():
    text = """define('perf_workload', function (__export_js__, __import_js__) {
class Box {
    constructor(value) {
        this.value = value;
    }
}
__export_js__.Box = Box;
function kernel(value) {
    return value;
}
__export_js__.kernel = kernel;
});
"""
    old = {"sha256": hashlib.sha256(text.encode()).hexdigest(), "ranges": [[7, 10]]}
    assert fold_header(SOURCE, "pyjs-js", text, old) == "1:6;7:10"


def test_built_js_folding_and_shipped_sizes_reach_live_ui(tmp_path):
    run = tmp_path / "saved"
    output = run / "build" / "sieve" / "pyjs-js"
    result = build("sieve", "pyjs-js", output, {"node": {"path": "node"}})
    generated = (output / "generated.js").read_bytes()
    shipped = (output / "program.cjs").read_bytes()
    assert shipped.startswith(generated) and len(shipped) > len(generated)
    assert result["code_size"] == {"bytes": len(shipped), "files": ["program.cjs"],
                                   "gzip_bytes": len(gzip.compress(shipped, mtime=0))}
    manifest = output / "source-ranges.json"
    metadata = json.loads(manifest.read_text())
    assert metadata["schema"] == 1
    assert metadata["sha256"] == hashlib.sha256(generated).hexdigest()
    assert metadata["ranges"]
    source = (ROOT / "cases" / "sieve" / "workload.py").read_text()
    visible = "\n".join("\n".join(generated.decode().split("\n")[a:b]) for a, b in metadata["ranges"])
    assert "function kernel" in visible
    assert "function batch" not in visible and "function main" not in visible
    path = "build/sieve/pyjs-js/generated.js"
    data = {"created": "2026-10-29", "sources": {"cases/sieve/workload.py": source},
            "rows": [{"case": "sieve", "target": "pyjs-js", "artifacts": {
                path: len(generated), "build/sieve/pyjs-js/program.cjs": len(shipped)}}]}
    snapshot = run / "results.json"
    snapshot.write_text(json.dumps(data))
    original = snapshot.read_bytes()
    app = Application()
    mount(app, root=tmp_path)
    with Server(app, port=0, quiet=True) as server:
        status, headers, body = request(server, "GET", "/perf/artifact/saved/" + path)
        assert status == 200 and body == generated
        assert headers["X-PyJS-Algorithm-Ranges"] == ";".join(f"{a}:{b}" for a, b in metadata["ranges"])
        enriched = json.loads(request(server, "GET", "/perf/results/saved.json")[2])
        assert enriched["rows"][0]["code_size"] == result["code_size"]
        assert snapshot.read_bytes() == original
        manifest.write_text("broken JSON")
        status, headers, body = request(server, "GET", "/perf/artifact/saved/" + path)
        assert status == 200 and body == generated
        assert headers["X-PyJS-Algorithm-Ranges"] == fold_header(source, "pyjs-js", generated.decode())
