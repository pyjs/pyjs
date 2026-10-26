"""Execute generated Node hosts, including imports, async I/O and source maps."""
import importlib
import json
import os
import signal
import subprocess
import sys
import time
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


@pytest.fixture
def callbacks(monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).parent / "fixtures/node")
    module = importlib.import_module("callbacks")
    yield module
    sys.modules.pop("callbacks", None)


def test_node_adapters_capture_callbacks_once_without_shadowing(tmp_path, callbacks, node):
    target = build_node(callbacks.main, tmp_path / "callbacks.cjs")
    result = subprocess.run([*node, target], input="hello\n", text=True,
                            capture_output=True, check=True, timeout=10)
    assert result.stdout.splitlines() == [
        "made first", "made second", "made stderr", "made stdout", "made stdin", "registered",
        "first 1 3", "stderr 1 hello", "stderr 2 hello", "stdout 1 5", "stdout 2 5",
        "stdin 1 hello", "end",
    ]


def test_electron_adapters_capture_callbacks_at_registration(tmp_path, callbacks, node):
    target = build_node(callbacks.electron, tmp_path / "callbacks.cjs", executable=False)
    # Stub only Electron's IPC registration; run the real compiled adapters.
    script = """
const Module = require('node:module'), load = Module._load;
Module._load = function(name, ...args) {
    return name === 'electron'
        ? {ipcMain: {handle: (_channel, callback) => {globalThis.testHandler = callback}}}
        : load.call(this, name, ...args);
};
require(process.argv[1]).main().catch(error => {console.error(error); process.exitCode = 1});
"""
    result = subprocess.run([*node, "-e", script, target], text=True,
                            capture_output=True, check=True, timeout=10)
    assert result.stdout.splitlines() == [
        "made message", "made reassigned", "made detach", "made ipc", "registered",
        "message 1 paused{}", "message 2 paused{}", "detach 1 closed", "detach 2 closed",
        "ipc 1 /example{}", "ipc 2 /example{}",
    ]


def test_node_pytest_rejects_unsettled_entry(tmp_path):
    source = tmp_path / "test_unsettled.py"
    source.write_text('''import pytest
from pyjs import js
pytestmark = pytest.mark.pyjs_node
@js.inline("new Promise(() => {{}})")
async def pending() -> None: ...
@js
async def test_pending():
    await pending()
    assert False, "must not pass before reaching this statement"
''')
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--pyjs-target=node", str(source)],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Node entry did not complete" in result.stdout
    assert "1 failed" in result.stdout


@pytest.mark.parametrize("interrupt", [False, pytest.param(True, marks=pytest.mark.skipif(
    os.name == "nt", reason="SIGINT delivery to a child pytest process is POSIX-specific"))])
def test_node_timeout_or_interrupt_stops_detached_child(tmp_path, interrupt):
    (tmp_path / "conftest.py").write_text('''def pytest_configure():
    import pyjs.testing.pytest_plugin as plugin
    plugin.NODE_TEST_TIMEOUT_SECONDS = 2
''')
    source = tmp_path / "test_child.py"
    source.write_text('''import pytest
from pyjs import js
from pyjs.node import cwd, environment, executable, sleep, spawn, write_text_sync
pytestmark = pytest.mark.pyjs_node
@js
async def test_child():
    child = spawn(executable(), ["-e", "setInterval(() => {}, 1000)"], cwd())
    write_text_sync(environment("TEST_CHILD_PID"), str(child.pid))
    await sleep(30000)
''')
    pid_file = tmp_path / "child.pid"
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                   "TEST_CHILD_PID": str(pid_file)}
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "--pyjs-target=node", str(source)],
            cwd=tmp_path, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            if interrupt:
                deadline = time.monotonic() + 15
                while not pid_file.exists() and time.monotonic() < deadline:
                    assert process.poll() is None, "pytest exited before spawning its child"
                    time.sleep(.02)
                assert pid_file.exists(), "Test child did not start"
                process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == (2 if interrupt else 1), stdout + stderr
            assert ("KeyboardInterrupt" if interrupt else
                    "Node test timed out after 2 seconds") in stdout
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 3
        while process_is_running(pid) and time.monotonic() < deadline:
            time.sleep(.05)
        assert not process_is_running(pid), f"Detached child {pid} survived the test timeout"
    finally:
        if pid_file.exists():
            pid = int(pid_file.read_text())
            if process_is_running(pid):
                os.kill(pid, 9)


def process_is_running(pid):
    if os.name == "nt":
        listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, check=True, timeout=5)
        return f'"{pid}"' in listing.stdout
    listing = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                             capture_output=True, text=True, check=False, timeout=5)
    # A terminated orphan can briefly remain a zombie until its reaper runs.
    return bool(listing.stdout.strip()) and not listing.stdout.strip().startswith("Z")
