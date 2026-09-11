import argparse
import hashlib
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from generate_packages import NPM_ROOT, TARGETS, write_runtime_package
from release import validate_versions

PROJECT_ROOT = NPM_ROOT.parent


def download(target) -> Path:
    cache = NPM_ROOT / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / target.asset
    if not archive.exists():
        print(f"Downloading Python {target.python_version} for {target.name}...")
        temporary = archive.with_suffix(f"{archive.suffix}.download")
        try:
            with urllib.request.urlopen(target.url) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != target.sha256:
        raise RuntimeError(f"Unexpected SHA-256 for {archive.name}: {digest}")
    return archive


def run(command: list[str]):
    print("+", " ".join(command))
    subprocess.run(command, check=True)


def build(target_name: str) -> Path:
    version = validate_versions()
    target = TARGETS[target_name]
    archive = download(target)
    destination = NPM_ROOT / "dist" / target.package_name.rpartition("/")[2]
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True)

    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")

    python = destination / target.python_executable
    if not python.exists():
        raise RuntimeError(f"Python executable was not found at {python}")

    try:
        run([str(python), "-m", "pip", "--version"])
    except subprocess.CalledProcessError:
        run([str(python), "-m", "ensurepip"])

    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--no-compile",
            "--upgrade",
            str(PROJECT_ROOT),
        ]
    )
    shutil.copy2(PROJECT_ROOT / "LICENSE", destination / "LICENSE")
    write_runtime_package(target, destination, version)
    print(f"Built {target.package_name} in {destination}")
    return destination


def main():
    parser = argparse.ArgumentParser(description="Build a portable PyJS npm runtime.")
    parser.add_argument("target", choices=TARGETS)
    args = parser.parse_args()
    build(args.target)

if __name__ == "__main__":
    main()
