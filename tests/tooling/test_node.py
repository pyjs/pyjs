import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from sdkmgr import Installation, SDKError
from sdkmgr.providers import Platform

from pyjs.tooling.download import verify_sha256
from pyjs.tooling.node import Node, Npm


def test_node_import_does_not_load_the_llvm_backend():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pyjs.tooling.node import Node; "
            "print('pyjs.native.llvm' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "False\n"


@pytest.mark.parametrize("system", ["linux", "macos", "windows"])
def test_node_delegates_provisioning_to_sdkmgr(monkeypatch, tmp_path, system):
    installation = Installation("node", "24.18.1", tmp_path / "provider", Platform(system, "x64"))
    manager = Mock()
    manager.ensure.return_value = installation
    factory = Mock(return_value=manager)
    monkeypatch.setattr("pyjs.tooling.node.Manager", factory)
    monkeypatch.delenv("PYJS_NODE", raising=False)
    node = Node(version="24.18.1", root=tmp_path)
    factory.assert_not_called()
    assert node.ensure() == installation.home
    assert node.ensure() == installation.home
    factory.assert_called_once_with(tmp_path, interactive=False)
    manager.ensure.assert_called_once_with("node", version="24.18.1")
    assert node.home == installation.home
    assert node.executable == node.home / ("node.exe" if system == "windows" else "bin/node")
    assert node.npm_executable == node.home / ("npm.cmd" if system == "windows" else "bin/npm")


def test_node_path_discovery_never_installs(monkeypatch):
    manager = Mock()
    manager.find.return_value = None
    monkeypatch.setattr("pyjs.tooling.node.Manager", Mock(return_value=manager))
    monkeypatch.delenv("PYJS_NODE", raising=False)
    with pytest.raises(RuntimeError, match="Call Node.ensure"):
        Node().executable
    manager.ensure.assert_not_called()


def test_sdkmgr_failure_keeps_cli_runtime_error_contract(monkeypatch):
    manager = Mock()
    manager.ensure.side_effect = SDKError("provider failed")
    monkeypatch.setattr("pyjs.tooling.node.Manager", Mock(return_value=manager))
    monkeypatch.delenv("PYJS_NODE", raising=False)
    with pytest.raises(RuntimeError, match="provider failed"):
        Node().ensure()


def test_download_verifies_published_checksum(tmp_path):
    archive = tmp_path / "node.tar.xz"
    archive.write_bytes(b"node")
    checksum = hashlib.sha256(b"node").hexdigest()
    checksums = tmp_path / "SHASUMS256.txt"
    checksums.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")

    verify_sha256(archive, checksums)

    archive.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="Checksum verification failed"):
        verify_sha256(archive, checksums)


def test_node_uses_an_explicit_environment_executable(monkeypatch, tmp_path):
    monkeypatch.setattr("pyjs.tooling.node.Manager", lambda *a, **kw: pytest.fail("Explicit runtime"))
    executable = tmp_path / "bin/node"
    executable.parent.mkdir()
    executable.write_text("node", encoding="utf-8")
    monkeypatch.setenv("PYJS_NODE", str(executable))
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [executable, "--version"],
        0,
        stdout="v22.14.0\n",
        stderr="",
    )
    node = Node(runner=runner)

    assert node.ensure() == executable.parent
    assert node.executable == executable
    npm_name = "npm.cmd" if platform.system() == "Windows" else "npm"
    assert node.npm_executable == executable.with_name(npm_name)
    assert node.version == "22.14.0"
    assert node.selection == "PYJS_NODE"
    runner.run.assert_called_once_with(
        [executable, "--version"],
        capture_output=True,
    )


def test_node_rejects_an_old_explicit_version(tmp_path):
    executable = tmp_path / "node"
    executable.write_text("node", encoding="utf-8")
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [executable, "--version"],
        0,
        stdout="v18.20.8\n",
        stderr="",
    )

    with pytest.raises(
        RuntimeError,
        match="Node 18.20.8 is unsupported; PyJS requires Node 20 or newer",
    ):
        Node(executable=executable, runner=runner).ensure()


def test_obsolete_pyjs_mirror_is_not_silently_ignored(monkeypatch):
    monkeypatch.delenv("PYJS_NODE", raising=False)
    monkeypatch.setenv("PYJS_NODE_MIRROR", "https://pyjs.example/node")
    with pytest.raises(RuntimeError, match="provider's mirror"):
        Node().ensure()


def test_node_runs_javascript_as_an_ecmascript_module(tmp_path):
    runner = Mock()
    runner.run.return_value.returncode = 0
    sources = []

    def capture_source(command, **options):
        sources.append(Path(command[-1]).read_text(encoding="utf-8"))
        return runner.run.return_value

    runner.run.side_effect = capture_source
    node = Node(executable=tmp_path / "node", runner=runner)
    node.ensure = Mock(return_value=node.home)

    result = node.run_javascript("console.log('hello');")

    assert result.returncode == 0
    command = runner.run.call_args.args[0]
    assert command[0] == node.executable
    assert command[-1].suffix == ".mjs"
    assert sources == ["console.log('hello');"]
    assert runner.run.call_args.kwargs == {
        "environment": node.environment(),
        "capture_output": True,
        "check": False,
    }


def test_node_checks_ecmascript_module_syntax():
    node = Node()

    valid = node.check_module("export const answer = 42;\n")
    invalid = node.check_module("export const = 42;\n")

    assert valid.returncode == 0
    assert valid.stderr == ""
    assert invalid.returncode != 0
    assert "SyntaxError" in invalid.stderr


def test_npm_can_save_exact_project_dependencies(tmp_path):
    node = Node(executable=tmp_path / "node" / "node")
    node.ensure = Mock(return_value=node.home)
    node.npm_executable.parent.mkdir(parents=True)
    node.npm_executable.touch()
    runner = Mock()
    npm = Npm(node, runner)

    npm.install(tmp_path / "project", "tailwindcss@4.3.3", save=True, exact=True)

    command = runner.run.call_args.args[0]
    assert "--no-save" not in command
    assert "--save-exact" in command
    assert "tailwindcss@4.3.3" in command


def test_npm_syncs_an_existing_managed_project(tmp_path):
    node = Node(executable=tmp_path / "node" / "node")
    node.ensure = Mock(return_value=node.home)
    node.npm_executable.parent.mkdir(parents=True)
    node.npm_executable.touch()
    runner = Mock()
    npm = Npm(node, runner)

    npm.sync(tmp_path / "project")

    assert runner.run.call_args.args[0] == [
        node.npm_executable,
        "install",
        "--prefix",
        tmp_path / "project",
        "--save-exact",
    ]


def test_npm_bundles_with_the_managed_esbuild(tmp_path):
    node = Node(executable=tmp_path / "node" / "node")
    node.ensure = Mock(return_value=node.home)
    node.npm_executable.parent.mkdir(parents=True)
    node.npm_executable.touch()
    runner = Mock()
    npm = Npm(node, runner)
    project = tmp_path / "project"
    entry = project / "pyjs-vendor-entry.js"
    output = project / "pyjs-vendor.js"

    npm.bundle(entry, output)

    runner.run.assert_called_once_with(
        [
            node.npm_executable,
            "exec",
            "--prefix",
            project,
            "--",
            "esbuild",
            entry,
            "--bundle",
            "--format=esm",
            f"--outfile={output}",
        ],
        environment=node.environment(),
    )
