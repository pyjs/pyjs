import importlib.util
import json
import subprocess
import sys
import tomllib
from html.parser import HTMLParser

import pytest

from perf.app import mount
from perf.harness.build import ROOT, build
from perf.harness.jit import summarize_jit
from perf.harness.process import execute
from perf.run import (
    CASES,
    calibrate,
    expected,
    oracle,
    parse_samples,
    summarize,
    tool,
    warmup_drift,
)
from perf.view import LABELS, view
from pyjs.server.dev import Application, Server
from pyjs.web.ssr import render_html
from tests.test_dev_server import request

EXPANDED_CASES = ("queens", "permute", "towers", "bounce", "spectralnorm", "nbody")
SMALL_INPUTS = {
    "fibonacci": (0, 1, 2, 3, 10, 20), "binarytrees": (0, 1, 2, 3, 8, 12),
    "queens": (0, 1, 2, 3, 4, 8), "permute": (0, 1, 2, 3, 5, 7),
    "towers": (0, 1, 2, 3, 8, 10),
}


def bounded_input(case):
    return SMALL_INPUTS.get(case, (24,))[-1]


@pytest.mark.parametrize("case", CASES)
def test_kernel_matches_independent_oracle(case):
    path = ROOT / "cases" / case / "workload.py"
    spec = importlib.util.spec_from_file_location("workload", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for size in SMALL_INPUTS.get(case, (0, 1, 2, 3, 10, 24, 101)):
        assert module.kernel(size) == oracle(case, size)
    batch_size = bounded_input(case)
    assert expected(case, batch_size, 3) == 2 * module.kernel(batch_size) + module.kernel(batch_size + 1)


@pytest.mark.parametrize("case", ("binarytrees", "mandelbrot") + EXPANDED_CASES)
def test_new_workloads_match_oracles_at_every_configured_input(case):
    directory = ROOT / "cases" / case
    spec = importlib.util.spec_from_file_location("workload", directory / "workload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for size in tomllib.loads((directory / "case.toml").read_text())["sizes"]:
        for n in (size, size + 1):
            assert module.kernel(n) == oracle(case, n)


def test_new_oracle_known_small_results():
    assert [oracle("binarytrees", n) for n in (0, 1, 2)] == [5, 15, 35]
    # The single point (-1.5, -1) escapes after two iterations.
    assert oracle("mandelbrot", 0) == 0
    assert oracle("mandelbrot", 1) == 2
    assert [oracle("queens", n) for n in (0, 1, 2, 4, 8)] == [1, 1, 0, 2, 92]
    assert [oracle("permute", n) for n in (0, 1, 2, 3)] == [0, 1, 9, 72]
    assert [oracle("towers", n) for n in (0, 1, 2, 3)] == [0, 2, 7, 17]
    assert oracle("spectralnorm", 1) == 1000000000
    assert oracle("nbody", 0) == 1228000000


def test_samples_validate_warmups_as_well_as_measurements():
    assert parse_samples("warmup 42 10\nsample 42 20\n", 42, 1, 1) == [
        {"phase": "warmup", "checksum": 42, "ns": 10},
        {"phase": "sample", "checksum": 42, "ns": 20},
    ]
    for output in ("warmup 41 10\nsample 42 20\n", "sample 42 20\n",
                   "sample 42 10\nsample 42 20\n", "warmup 42 0\nsample 42 20\n",
                   "warmup 42 10\nsample 42 -1\n", "warmup 42 10\nsample 42 nan\n",
                   "warmup 42 10\nsample 42 20\nextra"):
        with pytest.raises(ValueError):
            parse_samples(output, 42, 1, 1)


def test_summary_does_not_choose_fastest_sample():
    assert summarize([1, 2, 9]) == {"median": 2, "min": 1, "max": 9, "mad": 1}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX benchmark runner")
def test_process_timeout_is_bounded():
    with pytest.raises(subprocess.TimeoutExpired):
        execute([sys.executable, "-c", "import time; time.sleep(20)"], timeout=0.1)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX benchmark runner")
def test_python_adapter_checks_real_output_and_preserves_existing_destination(tmp_path):
    directory = tmp_path / "build"
    result = build("matrix", "cpython", directory, {"python": tool(sys.executable)})
    measured = execute(result["command"] + ["24", "3", "1", "2"])
    assert measured.returncode == 0, measured.stderr
    assert len(parse_samples(measured.stdout, expected("matrix", 24, 3), 1, 2)) == 3
    original = (directory / "program.py").read_bytes()
    with pytest.raises(FileExistsError):
        build("matrix", "cpython", directory, {"python": tool(sys.executable)})
    assert (directory / "program.py").read_bytes() == original


@pytest.mark.parametrize("case", CASES)
def test_javascript_reference_matches_oracle(tmp_path, case):
    node = tool("node")
    if not node["path"]:
        pytest.skip("Node is required for the handwritten JavaScript control")
    result = build(case, "javascript", tmp_path / case, {"node": node})
    for size in (1, 2, bounded_input(case)):
        measured = execute(result["command"] + [str(size), "3", "1", "2"])
        assert measured.returncode == 0, measured.stderr
        parse_samples(measured.stdout, expected(case, size, 3), 1, 2)


@pytest.mark.parametrize("case", ("binarytrees", "mandelbrot") + EXPANDED_CASES)
def test_new_python_workloads_execute_as_javascript(tmp_path, case):
    node = tool("node")
    if not node["path"]:
        pytest.skip("Node is required to execute generated JavaScript")
    result = build(case, "pyjs-js", tmp_path / case, {"node": node})
    for size in (0, 1, 2, 8):
        measured = execute(result["command"] + [str(size), "3", "1", "2"])
        assert measured.returncode == 0, measured.stderr
        parse_samples(measured.stdout, expected(case, size, 3), 1, 2)


@pytest.mark.parametrize("case", EXPANDED_CASES)
@pytest.mark.parametrize("target", ("rust", "java", "pyjs-llvm", "pyjs-jvm"))
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Native benchmark adapters target Linux")
def test_expanded_native_adapters_match_oracles(tmp_path, case, target):
    if target == "pyjs-jvm" and case in ("towers", "spectralnorm", "nbody"):
        pytest.skip("JVM lacks list.pop / stdlib math imports; runner retains failed cells")
    requirements = {"rust": ("rustc",), "java": ("java", "javac"),
                    "pyjs-jvm": ("java", "javac"), "pyjs-llvm": ("clang",)}
    tools = {name: tool(name) for name in requirements[target]}
    if any(not entry["path"] for entry in tools.values()):
        pytest.skip(f"{target} toolchain is required for this adapter")
    tools["javap"] = {"path": None}
    result = build(case, target, tmp_path / case, tools)
    # Small edge cases and both configured sizes (plus their alternating N+1)
    # exercise real emitted/compiled programs, not just source construction.
    metadata = tomllib.loads((ROOT / "cases" / case / "case.toml").read_text())
    for size in (0, 1, 2, *metadata["sizes"]):
        measured = execute(result["command"] + [str(size), "2", "0", "1"])
        assert measured.returncode == 0, measured.stderr
        parse_samples(measured.stdout, expected(case, size, 2), 0, 1)


def test_towers_jvm_pop_boundary_is_explicit():
    from pyjs.java import transpile_jvm
    from pyjs.java.diagnostics import JVMUnsupported

    source = (ROOT / "cases/towers/workload.py").read_text()
    with pytest.raises(JVMUnsupported, match="unsupported JVM scalar operation pop"):
        transpile_jvm(source + "\ndef main() -> int:\n    return kernel(3)\n")


def snapshot():
    metadata = {"name": "Sieve", "category": "Integers", "description": "Prime count", "notes": "No bitset"}
    return {
        "schema": 1, "created": "2026-01-01", "complete": True, "dirty": False,
        "label": "<script>bad()</script>", "revision": "abcd", "cpu": "test CPU",
        "platform": "test host", "source_sha256": "123", "policy": {}, "warnings": [],
        "tools": {"python": {"version": "test version"}},
        "sources": {"cases/sieve/workload.py": "# <script>bad()</script>"},
        "rows": [
            {"case": "sieve", "target": "cpython", "size": 24, "metadata": metadata,
             "status": "ok", "warm_seconds": {"median": 0.1}, "startup": {"median": 0.2}},
            {"case": "sieve", "target": "pyjs-js", "size": 24, "metadata": metadata,
             "status": "incorrect", "error": "wrong result <unsafe>",
             "warm_seconds": {"median": 0.000001}},
        ],
    }


def test_matrix_groups_inputs_and_keeps_missing_and_failed_cells():
    class Matrix(HTMLParser):
        def __init__(self):
            super().__init__()
            self.headers = []
            self.rows = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "th" and attrs.get("scope") == "col":
                self.headers.append(attrs.get("data-target"))
            if tag == "tr" and "data-case" in attrs:
                self.rows.append((attrs, []))
            if tag == "td" and "data-target" in attrs:
                self.rows[-1][1].append(attrs)

    data = snapshot()
    data["rows"].append({**data["rows"][0], "size": 48})
    # HTML includes all raw evidence; inspect table structure rather than that scaffolding.
    matrix = Matrix()
    matrix.feed(render_html(view(data, ["example"], "example", "/perf/")))
    assert matrix.headers == [None, *LABELS]
    assert [row[0]["data-size"] for row in matrix.rows] == ["24", "48"]
    for _, cells in matrix.rows:
        assert [cell["data-target"] for cell in cells] == list(LABELS)
        assert cells[0]["data-warm"] == "0.1"
        assert all(cell["data-warm"] == "" for cell in cells[1:])


def test_target_pairs_have_fixed_order_and_explicit_comparison_references():
    class Columns(HTMLParser):
        def __init__(self):
            super().__init__()
            self.targets = []
            self.groups = []
            self.references = {}
            self.current = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "th" and attrs.get("scope") == "colgroup":
                self.groups.append((attrs["data-group"], attrs["colspan"]))
            if tag == "td" and "data-target" in attrs:
                self.current = attrs["data-target"]
                self.targets.append(self.current)
                self.references[self.current] = []
            if tag == "span" and "data-reference" in attrs:
                self.references[self.current].append(attrs["data-reference"])

    parsed = Columns()
    html = render_html(view(snapshot(), ["example"], "example", "/perf/"))
    parsed.feed(html)
    assert parsed.targets == ["cpython", "javascript", "pyjs-js", "rust", "pyjs-llvm", "java", "pyjs-jvm"]
    assert parsed.groups == [("js", "2"), ("native", "2"), ("jvm", "2")]
    assert parsed.references == {
        "cpython": [], "javascript": ["cpython"], "pyjs-js": ["cpython"],
        "rust": ["cpython"], "pyjs-llvm": ["cpython"],
        "java": ["cpython"], "pyjs-jvm": ["cpython"],
    }
    assert 'id="group"' in html and 'id="baseline"' not in html


def test_source_expansions_follow_each_input_and_only_link_recorded_artifacts():
    class Sources(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []
            self.buttons = []
            self.artifacts = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "tr" and ("data-case" in attrs or attrs.get("class") == "source-row"):
                self.rows.append(attrs)
            if tag == "button" and "data-source-button" in attrs:
                self.buttons.append(attrs)
            if tag == "pre" and "data-url" in attrs:
                self.artifacts[attrs["id"]] = attrs["data-url"]

    data = snapshot()
    data["rows"][1]["artifacts"] = {"build/sieve/pyjs-js/generated.js": 42}
    data["rows"].append({**data["rows"][0], "size": 48})
    parsed = Sources()
    parsed.feed(render_html(view(data, ["example"], "example", "/perf/")))
    assert [row.get("data-size", row.get("id")) for row in parsed.rows] == [
        "24", "source-panel-sieve-24", "48", "source-panel-sieve-48"]
    assert all("hidden" in row for row in parsed.rows[1::2])
    assert len(parsed.buttons) == 16  # Workload name plus all seven runtime cells.
    assert [b["aria-controls"] for b in parsed.buttons] == ["source-panel-sieve-24"] * 8 + ["source-panel-sieve-48"] * 8
    assert all(b["aria-expanded"] == "false" for b in parsed.buttons)
    assert parsed.artifacts == {
        "source-sieve-pyjs-js": "/perf/artifact/example/build/sieve/pyjs-js/generated.js",
        "source-sieve-pyjs-llvm": "", "source-sieve-pyjs-jvm": "",
    }


def test_live_ui_escapes_sources_and_keeps_failure_without_timing(tmp_path):
    run = tmp_path / "first"
    run.mkdir()
    path = run / "results.json"
    path.write_text(json.dumps(snapshot()))
    app = Application()
    mount(app, root=tmp_path)
    with Server(app, port=0, quiet=True) as server:
        status, _, body = request(server, "GET", "/perf/")
        assert status == 200
        source = body.decode()
        assert "<script>bad()" not in source
        assert "&lt;script&gt;bad()" in source
        assert "wrong result &lt;unsafe&gt;" in source
        assert 'data-warm=""' in source
        assert 'data-warm="0.1"' in source
        assert 'data-latest="true"' in source
        assert '>Latest run</strong>' in source
        assert '<div hidden=""><label>Saved runs' in source
        assert b"Controls" in request(server, "GET", "/perf/page.js")[2]
        assert request(server, "GET", "/perf/?run=missing")[0] == 404
        # New JSON becomes visible without restarting or generating a site.
        newer = tmp_path / "second"
        newer.mkdir()
        data = snapshot()
        data.update(created="2026-02-01", label="New measurement", complete=False)
        (newer / "results.json").write_text(json.dumps(data))
        assert b"New measurement" in request(server, "GET", "/perf/")[2]
        assert b"coverage is incomplete" in request(server, "GET", "/perf/")[2]
        historical = request(server, "GET", "/perf/?run=first")[2]
        assert b"New measurement" not in historical
        assert b'data-latest="false"' in historical
        assert b'Older saved run' in historical and b'View latest run' in historical
        assert b'View latest run' in request(server, "GET", "/perf/?run=deleted")[2]
        assert json.loads(request(server, "GET", "/perf/results/second.json")[2]) == data
        assert request(server, "GET", "/perf/artifact/first/results.json")[0] == 404
    assert not list(tmp_path.rglob("*.html"))


def test_evidence_explains_forks_and_jit_failures_before_raw_json():
    data = snapshot()
    data["rows"][0].update(loops=2, forks=[[
        {"phase": "warmup", "ns": 8_000_000}, {"phase": "warmup", "ns": 4_000_000},
        {"phase": "sample", "ns": 2_000_000}, {"phase": "sample", "ns": 6_000_000}]],
        jvm_diagnostics={"status": "ok", "compiled": [], "failures": [
            {"method": "PyjsProgram kernel (J)J", "reasons": ["too many local variables"]}]},
        artifacts={"build/sieve/pyjs-jvm/24-jit.xml": 123})
    html = render_html(view(data, ["example"], "example", "/perf/"))
    assert '<td>1</td><td>4.000</td><td>2.000</td><td>2.000</td><td>1.000–3.000</td>' in html
    assert "PyjsProgram kernel (J)J: too many local variables" in html
    assert 'href="/perf/artifact/example/build/sieve/pyjs-jvm/24-jit.xml"' in html
    assert html.index("First warmup") < html.index("Raw samples, commands and metadata")


def test_missing_tool_is_explicit():
    assert tool("no-such-performance-tool-123456") == {"path": None, "version": None}


def test_jit_diagnostics_keep_failed_leaf_elements_and_successful_helpers(tmp_path):
    log = tmp_path / "jit.xml"
    log.write_text('''<hotspot_log>
      <nmethod method="PyjsProgram$list$J get (J)J" compiler="c2"/>
      <nmethod method="Kernel kernel (J)J" compiler="c2"/>
      <task method="PyjsProgram kernel (J)J" level="3" compile_kind="osr">
        <failure reason="illegal oopMap register name"/>
      </task>
      <task method="PyjsProgram kernel (J)J"><failure reason="too many local variables"/></task>
      <task method="unrelated method ()V"><failure reason="not benchmark evidence"/></task>
    </hotspot_log>''')
    result = summarize_jit(log)
    assert result["status"] == "ok"
    assert [item["reasons"] for item in result["failures"]] == [
        ["illegal oopMap register name"], ["too many local variables"]]
    assert result["compiled"] == [{"method": "Kernel kernel (J)J", "compiler": "c2"},
                                  {"method": "PyjsProgram$list$J get (J)J", "compiler": "c2"}]


@pytest.mark.skipif(sys.platform == "win32", reason="requires unprivileged POSIX symlinks")
def test_live_ui_empty_state_and_artifact_containment(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    app = Application()
    mount(app, root=root)
    with Server(app, port=0, quiet=True) as server:
        assert b"No snapshots yet" in request(server, "GET", "/perf/")[2]
        run = root / "first"
        run.mkdir()
        artifact = run / "generated.js"
        artifact.write_text("generated source")
        (run / "24-jit.xml").write_text("<hotspot_log/>")
        (run / "unlisted.log").write_text("private")
        (tmp_path / "outside.txt").write_text("private")
        (run / "escape.txt").symlink_to(tmp_path / "outside.txt")
        data = snapshot()
        data["rows"][0]["artifacts"] = {"generated.js": 16, "escape.txt": 7, "24-jit.xml": 14}
        (run / "results.json").write_text(json.dumps(data))
        status, headers, body = request(server, "GET", "/perf/artifact/first/generated.js")
        assert status == 200 and body == b"generated source"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Content-Type"] == "text/plain; charset=utf-8"
        assert request(server, "GET", "/perf/artifact/first/24-jit.xml")[2] == b"<hotspot_log/>"
        assert request(server, "GET", "/perf/artifact/first/unlisted.log")[0] == 404
        assert request(server, "GET", "/perf/artifact/first/escape.txt")[0] == 404
        assert request(server, "GET", "/perf/artifact/first/../../outside.txt")[0] == 404


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux measurement host")
def test_runner_retains_unavailable_target_and_never_overwrites_snapshot(tmp_path):
    output = tmp_path / "snapshot"
    command = [sys.executable, "-m", "perf.run", "--output", str(output),
               "--cases", "sieve", "--targets", "rust", "--small", "--forks", "1",
               "--rustc", "no-such-performance-tool-123456"]
    result = execute(command, timeout=60, cwd=ROOT.parent)
    assert result.returncode == 1, result.stderr
    original = (output / "results.json").read_bytes()
    snapshot = json.loads(original)
    assert snapshot["complete"]
    assert len(snapshot["rows"]) == 1
    assert snapshot["rows"][0]["status"] == "unavailable"
    assert "warm_seconds" not in snapshot["rows"][0]
    assert not (output / "site").exists()
    repeated = execute(command, timeout=60, cwd=ROOT.parent)
    assert repeated.returncode != 0
    assert (output / "results.json").read_bytes() == original


def test_calibration_is_bounded_and_validates_pilots(monkeypatch):
    counts = []

    def pilot(command, **kwargs):
        size, loops, warmups, samples = map(int, command[-4:])
        counts.append(loops)
        checksum = expected("sieve", size, loops)
        output = "".join(f"{phase} {checksum} {loops * 1_000_000}\n"
                         for phase in ["warmup"] * warmups + ["sample"] * samples)
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr("perf.run.execute", pilot)
    loops, traces = calibrate([], "sieve", 10, loops=1, target_ms=50,
                              max_loops=30, warmups=20, timeout=1)
    assert counts == [1, 10, 30]
    assert loops == 30 == traces[-1]["loops"]
    assert len(traces[-1]["samples"]) == 13
    assert calibrate([], "sieve", 10, loops=5, target_ms=0,
                     max_loops=30, warmups=20, timeout=1) == (5, [])
    monkeypatch.setattr("perf.run.expected", lambda *args: -1)
    with pytest.raises(ValueError, match="incorrect checksum"):
        calibrate([], "sieve", 10, loops=1, target_ms=50,
                  max_loops=30, warmups=20, timeout=1)


def test_warmup_drift_is_a_warning_not_a_convergence_claim():
    def fork(warm, measured):
        return [{"phase": phase, "ns": n} for phase, values in
                (("warmup", warm), ("sample", measured)) for n in values]
    assert warmup_drift([fork([100, 100, 100], [100, 100, 100])]) is None
    assert "20%" in warmup_drift([fork([100, 100, 100], [50, 50, 50])])
    assert "unassessed" in warmup_drift([fork([100], [100])])
