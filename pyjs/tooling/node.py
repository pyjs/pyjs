import os
import platform
import subprocess
import tempfile
from pathlib import Path

from sdkmgr import Manager, SDKError

from .command import CommandRunner

NODE_VERSION = "24.18.1"
MIN_NODE_MAJOR = 20


def cache_root() -> Path:
    root = os.environ.get("XDG_CACHE_HOME")
    if root:
        return Path(root) / "pyjs"
    return Path.home() / ".cache" / "pyjs"


class Node:
    def __init__(
        self,
        version: str = NODE_VERSION,
        root: Path | None = None,
        runner: CommandRunner | None = None,
        executable: str | Path | None = None,
    ):
        self.version = version
        self.root = root
        self.runner = runner or CommandRunner()
        environment_executable = os.environ.get("PYJS_NODE")
        selected_executable = (
            executable if executable is not None else environment_executable
        )
        self._executable = (
            Path(selected_executable).expanduser() if selected_executable else None
        )
        if executable is not None:
            self.selection = "argument"
        elif environment_executable:
            self.selection = "PYJS_NODE"
        else:
            self.selection = "managed"
        self._override_checked = False
        self._installation = None

    def _managed(self, *, install: bool = False):
        if self._installation is not None:
            return self._installation
        if os.environ.get("PYJS_NODE_MIRROR"):
            raise RuntimeError(
                "PYJS_NODE_MIRROR is no longer used. Configure your mise/nvm "
                "provider's mirror, or select an existing runtime with PYJS_NODE."
            )
        manager = Manager(self.root, interactive=False)
        try:
            self._installation = (manager.ensure if install else manager.find)(
                "node", version=self.version,
            )
        except SDKError as error:
            raise RuntimeError(str(error)) from error
        if self._installation is None:
            raise RuntimeError(
                f"Node {self.version} is not installed. Call Node.ensure() or "
                f"run sdkmgr install node@{self.version}."
            )
        return self._installation

    @property
    def home(self) -> Path:
        if self._executable is not None:
            return self._executable.parent
        return self._managed().home

    @property
    def executable(self) -> Path:
        if self._executable is not None:
            return self._executable
        return self._managed().executable()

    @property
    def npm_executable(self) -> Path:
        if self._executable is not None:
            name = "npm.cmd" if platform.system() == "Windows" else "npm"
            return self._executable.with_name(name)
        return self._managed().executable("npm")

    @property
    def bin_directory(self) -> Path:
        return self.executable.parent

    def environment(self) -> dict[str, str]:
        return {"PATH": f"{self.bin_directory}{os.pathsep}{os.environ.get('PATH', '')}"}

    def ensure(self) -> Path:
        if self._executable is not None:
            return self._ensure_override()
        return self._managed(install=True).home

    def _ensure_override(self) -> Path:
        if self._override_checked:
            return self.home
        if not self.executable.is_file():
            raise RuntimeError(
                f"Node executable selected by {self.selection} does not exist: "
                f"{self.executable}"
            )
        result = self.runner.run(
            [self.executable, "--version"],
            capture_output=True,
        )
        output = (result.stdout or "").strip()
        version = output.removeprefix("v")
        try:
            major = int(version.split(".", 1)[0])
        except (TypeError, ValueError):
            raise RuntimeError(
                f"Node executable {self.executable} returned an invalid version: "
                f"{output!r}"
            ) from None
        if major < MIN_NODE_MAJOR:
            raise RuntimeError(
                f"Node {version} is unsupported; PyJS requires Node "
                f"{MIN_NODE_MAJOR} or newer."
            )
        self.version = version
        self._override_checked = True
        return self.home

    def run_javascript(self, source: str) -> subprocess.CompletedProcess[str]:
        return self.run_module(source)

    def run_module(self, source: str) -> subprocess.CompletedProcess[str]:
        return self._run_module(source)

    def check_module(self, source: str) -> subprocess.CompletedProcess[str]:
        return self._run_module(source, "--check")

    def _run_module(
        self,
        source: str,
        *options: str,
    ) -> subprocess.CompletedProcess[str]:
        self.ensure()
        with tempfile.TemporaryDirectory(prefix="pyjs-node-") as temporary:
            module = Path(temporary) / "module.mjs"
            module.write_text(source, encoding="utf-8")
            return self.runner.run(
                [self.executable, *options, module],
                environment=self.environment(),
                capture_output=True,
                check=False,
            )


class Npm:
    def __init__(self, node: Node | None = None, runner: CommandRunner | None = None):
        self.node = node or Node()
        self.runner = runner or self.node.runner

    def install(
        self,
        prefix: Path,
        *packages: str,
        save: bool = False,
        exact: bool = False,
    ) -> None:
        self.node.ensure()
        if not self.node.npm_executable.is_file():
            raise RuntimeError(
                f"npm was not found next to {self.node.executable}: "
                f"{self.node.npm_executable}"
            )
        prefix.mkdir(parents=True, exist_ok=True)
        options = []
        if not save:
            options.append("--no-save")
        if exact:
            options.append("--save-exact")
        self.runner.run(
            [
                self.node.npm_executable,
                "install",
                "--prefix",
                prefix,
                *options,
                *packages,
            ],
            environment=self.node.environment(),
        )

    def sync(self, prefix: Path) -> None:
        """Install a managed package.json while preserving npm's exact lockfile."""
        self.install(prefix, save=True, exact=True)

    def bundle(self, entry: Path, output: Path) -> None:
        """Bundle a managed ESM entry point with the installed esbuild."""
        self.node.ensure()
        if not self.node.npm_executable.is_file():
            raise RuntimeError(
                f"npm was not found next to {self.node.executable}: "
                f"{self.node.npm_executable}"
            )
        self.runner.run(
            [
                self.node.npm_executable,
                "exec",
                "--prefix",
                entry.parent,
                "--",
                "esbuild",
                entry,
                "--bundle",
                "--format=esm",
                f"--outfile={output}",
            ],
            environment=self.node.environment(),
        )
