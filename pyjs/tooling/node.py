import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .command import CommandRunner
from .download import verify_sha256

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
        self.root = root or cache_root() / "tooling" / "node"
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

    @property
    def platform_name(self) -> str:
        system = platform.system()
        machine = platform.machine().lower()
        architectures = {
            "x86_64": "x64",
            "amd64": "x64",
            "aarch64": "arm64",
            "arm64": "arm64",
        }
        try:
            architecture = architectures[machine]
        except KeyError:
            raise RuntimeError(f"Node is not available for architecture {machine!r}.") from None
        systems = {"Linux": "linux", "Darwin": "darwin", "Windows": "win"}
        try:
            return f"{systems[system]}-{architecture}"
        except KeyError:
            raise RuntimeError(f"Node is not available for {system!r}.") from None

    @property
    def home(self) -> Path:
        if self._executable is not None:
            return self._executable.parent
        return self.root / f"v{self.version}-{self.platform_name}"

    @property
    def executable(self) -> Path:
        if self._executable is not None:
            return self._executable
        name = "node.exe" if platform.system() == "Windows" else "node"
        return self.home / ("node.exe" if platform.system() == "Windows" else f"bin/{name}")

    @property
    def npm_executable(self) -> Path:
        if self._executable is not None:
            name = "npm.cmd" if platform.system() == "Windows" else "npm"
            return self._executable.with_name(name)
        if platform.system() == "Windows":
            return self.home / "npm.cmd"
        return self.home / "bin/npm"

    @property
    def bin_directory(self) -> Path:
        if self._executable is not None:
            return self._executable.parent
        if platform.system() == "Windows":
            return self.home
        return self.home / "bin"

    def environment(self) -> dict[str, str]:
        return {"PATH": f"{self.bin_directory}{os.pathsep}{os.environ.get('PATH', '')}"}

    def ensure(self) -> Path:
        if self._executable is not None:
            return self._ensure_override()
        if self.executable.exists() and self.npm_executable.exists():
            return self.home

        self.root.mkdir(parents=True, exist_ok=True)
        suffixes = {"Windows": "zip", "Darwin": "tar.gz", "Linux": "tar.xz"}
        try:
            suffix = suffixes[platform.system()]
        except KeyError:
            raise RuntimeError(f"Node is not available for {platform.system()!r}.") from None
        archive_name = f"node-v{self.version}-{self.platform_name}.{suffix}"
        base_url = self.download_base_url()

        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / archive_name
            checksums = temporary_path / "SHASUMS256.txt"
            urllib.request.urlretrieve(f"{base_url}/{archive_name}", archive)
            urllib.request.urlretrieve(f"{base_url}/SHASUMS256.txt", checksums)
            verify_sha256(archive, checksums)
            extracted = self._extract(archive, temporary_path)
            if self.home.exists():
                shutil.rmtree(self.home)
            extracted.replace(self.home)
        return self.home

    def download_base_url(self) -> str:
        mirror = (
            os.environ.get("PYJS_NODE_MIRROR")
            or os.environ.get("NODEJS_ORG_MIRROR")
            or "https://nodejs.org/dist"
        )
        return f"{mirror.rstrip('/')}/v{self.version}"

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

    def _extract(self, archive: Path, destination: Path) -> Path:
        directory_name = (
            archive.name.removesuffix(".zip").removesuffix(".tar.xz").removesuffix(".tar.gz")
        )
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as source:
                source.extractall(destination)
        else:
            with tarfile.open(archive) as source:
                source.extractall(destination, filter="data")
        return destination / directory_name


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
