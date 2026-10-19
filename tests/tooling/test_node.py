import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from sdkmgr import Installation, SDKError
from sdkmgr.providers import Platform

from pyjs.tooling import node as node_module
from pyjs.tooling.download import verify_sha256
from pyjs.tooling.node import Node, Npm


@pytest.fixture(autouse=True)
def isolated_node_discovery():
    node_module._managed_installations.clear()
    yield
    node_module._managed_installations.clear()


def test_tooling_import_does_not_load_llvm_or_sdkmgr():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pyjs.tooling.node import Node; "
            "from pyjs.tooling.android import AndroidSDK; "
            "print('pyjs.native.llvm' in sys.modules, 'sdkmgr' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "False False\n"


@pytest.mark.parametrize("system", ["linux", "macos", "windows"])
def test_node_delegates_provisioning_to_sdkmgr(monkeypatch, tmp_path, system):
    installation = Installation("node", "24.18.1", tmp_path / "provider", Platform(system, "x64"))
    manager = Mock()
    manager.ensure.return_value = installation
    factory = Mock(return_value=manager)
    monkeypatch.setattr("sdkmgr.Manager", factory)
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
    monkeypatch.setattr("sdkmgr.Manager", Mock(return_value=manager))
    monkeypatch.delenv("PYJS_NODE", raising=False)
    with pytest.raises(RuntimeError, match="Call Node.ensure"):
        _ = Node().executable
    manager.ensure.assert_not_called()


def test_sdkmgr_failure_keeps_cli_runtime_error_contract(monkeypatch):
    manager = Mock()
    manager.ensure.side_effect = SDKError("provider failed")
    monkeypatch.setattr("sdkmgr.Manager", Mock(return_value=manager))
    monkeypatch.delenv("PYJS_NODE", raising=False)
    with pytest.raises(RuntimeError, match="provider failed"):
        Node().ensure()


@pytest.mark.parametrize("install", [False, True])
def test_manager_constructor_failure_keeps_cli_error_contract(monkeypatch, install):
    monkeypatch.delenv("PYJS_NODE", raising=False)
    monkeypatch.setattr(platform, "machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match="Unsupported platform: .* riscv64"):
        node = Node()
        node.ensure() if install else node.executable


@pytest.fixture
def managed_installation(monkeypatch, tmp_path):
    installation = Installation("node", "24.18.1", tmp_path / "provider", Platform("linux", "x64"))
    for tool in ("node", "npm", "npx"):
        executable = installation.executable(tool)
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.touch()
    manager = Mock()
    manager.ensure.return_value = manager.find.return_value = installation
    monkeypatch.setattr("sdkmgr.Manager", Mock(return_value=manager))
    monkeypatch.delenv("PYJS_NODE", raising=False)
    return installation, manager


def test_managed_node_discovery_is_shared_across_instances(managed_installation):
    installation, manager = managed_installation
    assert Node().executable == installation.executable()
    for _ in range(20):
        assert Node().ensure() == installation.home
    manager.find.assert_called_once()
    manager.ensure.assert_not_called()


@pytest.mark.parametrize("variable", ["PATH", "HOME", "MISE_DATA_DIR", "NVM_DIR", "XDG_DATA_HOME"])
def test_managed_node_cache_respects_environment(monkeypatch, managed_installation, tmp_path, variable):
    Node().ensure()
    monkeypatch.setenv(variable, str(tmp_path / "changed"))
    Node().ensure()
    assert managed_installation[1].ensure.call_count == 2


def test_managed_node_cache_respects_root_and_version(managed_installation, tmp_path):
    Node(root=tmp_path).ensure()
    Node(root=tmp_path / "other").ensure()
    Node(root=tmp_path, version="22.14.0").ensure()
    assert managed_installation[1].ensure.call_count == 3


@pytest.mark.parametrize("install", [False, True])
def test_removed_working_directory_disables_shared_cache(monkeypatch, managed_installation, install):
    def missing_cwd():
        raise FileNotFoundError("working directory was removed")

    monkeypatch.setattr(Path, "cwd", missing_cwd)
    installation, manager = managed_installation
    for _ in range(2):
        node = Node()
        assert (node.ensure() if install else node.home) == installation.home
    operation = manager.ensure if install else manager.find
    assert operation.call_count == 2
    assert not node_module._managed_installations


def test_relative_root_cache_remains_isolated_by_directory(monkeypatch, managed_installation, tmp_path):
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.chdir(directory)
        Node(root=Path("tools")).ensure()
        Node(root=Path("tools")).ensure()
    assert managed_installation[1].ensure.call_count == 2


def test_managed_node_cache_rediscovers_removed_tools(managed_installation):
    installation, manager = managed_installation
    Node().ensure()
    installation.executable("npm").unlink()
    Node().ensure()
    assert manager.ensure.call_count == 2


def test_missing_discovery_is_not_cached(managed_installation):
    installation, manager = managed_installation
    manager.find.return_value = None
    with pytest.raises(RuntimeError, match="Call Node.ensure"):
        _ = Node().executable
    assert Node().ensure() == installation.home
    manager.find.assert_called_once()
    manager.ensure.assert_called_once()


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
    monkeypatch.setattr("sdkmgr.Manager", lambda *a, **kw: pytest.fail("Explicit runtime"))
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
