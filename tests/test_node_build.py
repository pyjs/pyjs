"""Execute generated Node hosts, including imports, async I/O and source maps."""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pyjs.cli import main
from pyjs.tooling.node import Node
from pyjs.tooling.node_build import build_node


@pytest.fixture
def node():
    runtime = Node()
    return [str(runtime.executable), "--enable-source-maps"]


@pytest.fixture
def program(monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).parent / "fixtures/node")
    module = importlib.import_module("program")
    yield module
    sys.modules.pop("program", None)


def test_real_async_filesystem_bundle_and_map(tmp_path, program, node):
    target = build_node(program.main, tmp_path / "program.cjs")
    result = subprocess.run([*node, target], text=True, capture_output=True, check=True)
    assert result.stdout == "node filesystem works True\n"
    source_map = json.loads(target.with_suffix(".cjs.map").read_text())
    assert any(source.endswith("program.py") for source in source_map["sources"])
    assert target.read_text().startswith("#!/usr/bin/env node\n")
    assert source_map["mappings"].startswith(";")


def test_requiring_bundle_does_not_execute_entry(tmp_path, program, node):
    target = build_node(program.main, tmp_path / "program.cjs", export_name="start", executable=False)
    result = subprocess.run([*node, "-e", "console.log(typeof require(process.argv[1]).start)", target],
                            text=True, capture_output=True, check=True)
    assert result.stdout == "function\n"
    assert not target.read_text().startswith("#!")


def test_cli_compiles_node_module(tmp_path, program, node):
    target = tmp_path / "program.cjs"
    assert main(["build", "program", "--target", "node", "-o", str(target)]) == 0
    result = subprocess.run([*node, target], text=True, capture_output=True, check=True)
    assert result.stdout == "node filesystem works True\n"


def test_native_errors_map_to_python_lines(tmp_path, monkeypatch, node):
    source = tmp_path / "node_error_sample.py"
    source.write_text('from pyjs import js\n@js\ndef main():\n    raise ValueError("mapped failure")\n')
    monkeypatch.syspath_prepend(tmp_path)
    try:
        module = importlib.import_module("node_error_sample")
        target = build_node(module.main, tmp_path / "failure.cjs")
        result = subprocess.run([*node, target], text=True, capture_output=True)
        assert result.returncode == 1
        assert "mapped failure" in result.stderr
        assert f"{source}:4:" in result.stderr
    finally:
        sys.modules.pop("node_error_sample", None)


def test_node_pytest_marker_runs_async_and_reports_python_failure(tmp_path):
    source = tmp_path / "test_sample.py"
    source.write_text('''import pytest
from pyjs import js
from pyjs.node import sleep
pytestmark = pytest.mark.pyjs_node
@js
async def test_async():
    await sleep(1)
    assert 2 + 2 == 4
@js
def test_failure():
    raise ValueError("node test failure")
''')
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--pyjs-target=node", str(source)],
        cwd=tmp_path, env=environment, text=True, capture_output=True, timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed, 1 passed" in result.stdout
    assert f"{source}:11:" in result.stdout
    ordinary = subprocess.run([sys.executable, "-m", "pytest", "-q", str(source)],
                              cwd=tmp_path, env=environment, text=True, capture_output=True, timeout=60)
    assert ordinary.returncode == 0, ordinary.stdout + ordinary.stderr
    assert "2 skipped" in ordinary.stdout


@pytest.mark.parametrize("option", ["--only-js", "--include-main", "--args=[]"])
def test_node_cli_rejects_browser_options(tmp_path, option):
    with pytest.raises(SystemExit) as error:
        main(["build", "program", "--target", "node", "-o", str(tmp_path / "out.cjs"), option])
    assert error.value.code == 2


def test_node_output_cannot_overwrite_python_source(tmp_path, program):
    source = tmp_path / "source.py"
    source.write_text("original")
    with pytest.raises(ValueError, match=".cjs"):
        build_node(program.main, source)
    assert source.read_text() == "original"
