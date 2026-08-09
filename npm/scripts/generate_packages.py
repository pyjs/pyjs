from dataclasses import dataclass
from pathlib import Path
from string import Template

NPM_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimeTarget:
    name: str
    package_name: str
    os: str
    cpu: str
    libc: str | None
    python_version: str
    python_build: str
    asset: str
    sha256: str
    python_executable: str

    @property
    def url(self) -> str:
        asset = self.asset.replace("+", "%2B")
        return (
            "https://github.com/astral-sh/python-build-standalone/releases/download/"
            f"{self.python_build}/{asset}"
        )


TARGETS = {
    "linux-x64": RuntimeTarget(
        name="linux-x64",
        package_name="@pyjsdev/cli-linux-x64",
        os="linux",
        cpu="x64",
        libc="glibc",
        python_version="3.14.7",
        python_build="20260805",
        asset=(
            "cpython-3.14.7+20260805-x86_64-unknown-linux-gnu-"
            "install_only_stripped.tar.gz"
        ),
        sha256="a3a4e4b81b138960c7c546694df8a77578c0b6aa46d47e96f49b9e10e8f860c9",
        # npm does not preserve the python3 symlink when packing the runtime.
        python_executable="python/bin/python3.14",
    ),
    "darwin-x64": RuntimeTarget(
        name="darwin-x64",
        package_name="@pyjsdev/cli-darwin-x64",
        os="darwin",
        cpu="x64",
        libc=None,
        python_version="3.14.7",
        python_build="20260805",
        asset=(
            "cpython-3.14.7+20260805-x86_64-apple-darwin-"
            "install_only_stripped.tar.gz"
        ),
        sha256="e0e8e70dc98a7b9ddcc434ff6c46ff19d7386160e0308ba0e637d5f2f971380d",
        python_executable="python/bin/python3.14",
    ),
    "darwin-arm64": RuntimeTarget(
        name="darwin-arm64",
        package_name="@pyjsdev/cli-darwin-arm64",
        os="darwin",
        cpu="arm64",
        libc=None,
        python_version="3.14.7",
        python_build="20260805",
        asset=(
            "cpython-3.14.7+20260805-aarch64-apple-darwin-"
            "install_only_stripped.tar.gz"
        ),
        sha256="abbf6e8530a283ed795fa91fd6bcf4501e2b1fa287b2cb1c15b70d3028f3a7c9",
        python_executable="python/bin/python3.14",
    ),
    "win32-x64": RuntimeTarget(
        name="win32-x64",
        package_name="@pyjsdev/cli-win32-x64",
        os="win32",
        cpu="x64",
        libc=None,
        python_version="3.14.7",
        python_build="20260805",
        asset=(
            "cpython-3.14.7+20260805-x86_64-pc-windows-msvc-"
            "install_only_stripped.tar.gz"
        ),
        sha256="d4582ec0f8c80524d341bee5b92b1612104123845cdfc835c64cb0153214be5f",
        python_executable="python/python.exe",
    ),
}


def write_runtime_package(target: RuntimeTarget, destination: Path, version: str):
    template = Template((NPM_ROOT / "runtime" / "package.json.template").read_text())
    package = template.substitute(
        package_name=target.package_name,
        version=version,
        target=target.name,
        os=target.os,
        cpu=target.cpu,
        libc=f',\n  "libc": ["{target.libc}"]' if target.libc else "",
        python_executable=target.python_executable,
        python_version=target.python_version,
        python_build=target.python_build,
    )
    (destination / "package.json").write_text(package)
