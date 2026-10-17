import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

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


def test_node_uses_platform_archive_name(monkeypatch, tmp_path):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")

    node = Node(version="24.18.1", root=tmp_path)

    assert node.platform_name == "linux-x64"
    assert node.home == tmp_path / "v24.18.1-linux-x64"
    assert node.executable == node.home / "bin/node"
    assert node.npm_executable == node.home / "bin/npm"


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


def test_node_download_mirror_prefers_the_pyjs_override(monkeypatch):
    monkeypatch.setenv("NODEJS_ORG_MIRROR", "https://node.example/dist/")
    node = Node(version="24.18.1")
    assert node.download_base_url() == "https://node.example/dist/v24.18.1"

    monkeypatch.setenv("PYJS_NODE_MIRROR", "https://pyjs.example/node")
    assert node.download_base_url() == "https://pyjs.example/node/v24.18.1"


def test_node_runs_javascript_as_an_ecmascript_module(tmp_path):
    runner = Mock()
    runner.run.return_value.returncode = 0
    sources = []

    def capture_source(command, **options):
        sources.append(Path(command[-1]).read_text(encoding="utf-8"))
        return runner.run.return_value

    runner.run.side_effect = capture_source
    node = Node(root=tmp_path, runner=runner)
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
    node = Node(root=tmp_path / "node")
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
    node = Node(root=tmp_path / "node")
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
    node = Node(root=tmp_path / "node")
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
