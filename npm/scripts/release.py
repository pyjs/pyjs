"""Validate release metadata and prepare inspectable npm build artifacts."""

import argparse
import ast
import hashlib
import json
import shutil
import tarfile
import tomllib
from pathlib import Path

try:
    from .generate_packages import NPM_ROOT, TARGETS
except ImportError:
    from generate_packages import NPM_ROOT, TARGETS

PROJECT_ROOT = NPM_ROOT.parent
PUBLIC_REPOSITORY = "git+https://github.com/pyjs/pyjs.git"


def pyjs_version() -> str:
    module = ast.parse((PROJECT_ROOT / "pyjs" / "__init__.py").read_text())
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            continue
        version = ast.literal_eval(statement.value)
        return ".".join(str(part) for part in version)
    raise RuntimeError("pyjs.__version__ was not found")


def project_version(path: Path) -> str:
    project = tomllib.loads(path.read_text())["project"]
    return project["version"]


def validate_versions(tag: str | None = None) -> str:
    version = pyjs_version()
    cli = json.loads((NPM_ROOT / "cli" / "package.json").read_text())
    versions = {
        "pyjs": version,
        "pyjs-examples": project_version(PROJECT_ROOT / "examples" / "pyproject.toml"),
        "pyjs-extras": project_version(PROJECT_ROOT / "extras" / "pyproject.toml"),
        "@pyjsdev/cli": cli["version"],
    }
    versions.update(
        {
            package: dependency
            for package, dependency in cli["optionalDependencies"].items()
        }
    )
    mismatches = {
        package: candidate
        for package, candidate in versions.items()
        if candidate != version
    }
    if mismatches:
        details = ", ".join(
            f"{package}={candidate}" for package, candidate in mismatches.items()
        )
        raise RuntimeError(f"Release versions do not agree with {version}: {details}")
    repository = cli.get("repository", {}).get("url")
    if repository != PUBLIC_REPOSITORY:
        raise RuntimeError(f"Unexpected npm repository URL: {repository!r}")
    runtime_template = (NPM_ROOT / "runtime" / "package.json.template").read_text()
    if f'"url": "{PUBLIC_REPOSITORY}"' not in runtime_template:
        raise RuntimeError("The runtime package template has the wrong repository URL")
    if tag is not None and tag != f"v{version}":
        raise RuntimeError(f"Release tag {tag!r} does not match v{version}")
    return version


def package_manifest(archive: Path) -> dict:
    with tarfile.open(archive, "r:gz") as package:
        member = package.getmember("package/package.json")
        source = package.extractfile(member)
        if source is None:
            raise RuntimeError(f"package.json is missing from {archive}")
        return json.load(source)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_artifact(target_name: str, packages: Path, destination: Path) -> None:
    version = validate_versions()
    expected = {TARGETS[target_name].package_name}
    if target_name == "linux-x64":
        expected.add("@pyjsdev/cli")
    archives = {}
    for archive in packages.glob("*.tgz"):
        package = package_manifest(archive)
        if package["name"] in expected and package["version"] == version:
            archives[package["name"]] = (archive, package)
    missing = expected - archives.keys()
    if missing:
        raise RuntimeError(f"Missing npm archives: {', '.join(sorted(missing))}")

    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True)
    manifest = {"schema": 1, "target": target_name, "version": version, "packages": []}
    checksums = []
    for name in sorted(expected):
        archive, package = archives[name]
        copied = destination / archive.name
        shutil.copy2(archive, copied)
        digest = sha256(copied)
        manifest["packages"].append(
            {
                "cpu": package.get("cpu"),
                "file": copied.name,
                "libc": package.get("libc"),
                "name": name,
                "os": package.get("os"),
                "pyjsRuntime": package.get("pyjsRuntime"),
                "sha256": digest,
                "version": version,
            }
        )
        checksums.append(f"{digest}  {copied.name}")
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (destination / "SHA256SUMS").write_text("\n".join(checksums) + "\n")


def verified_archive(directory: Path, package_name: str) -> Path:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["version"] != validate_versions():
        raise RuntimeError("Artifact and source versions do not agree")
    selected = None
    for package in manifest["packages"]:
        archive = directory / package["file"]
        if sha256(archive) != package["sha256"]:
            raise RuntimeError(f"Checksum failed for {archive.name}")
        archived = package_manifest(archive)
        if archived["name"] != package["name"] or archived["version"] != package["version"]:
            raise RuntimeError(f"Manifest metadata failed for {archive.name}")
        if package["name"] == package_name:
            selected = archive
    if selected is None:
        raise RuntimeError(f"Package {package_name} is missing from {directory}")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    version = commands.add_parser("version", help="validate and print the release version")
    version.add_argument("--tag")
    prepare = commands.add_parser("prepare", help="prepare one platform artifact")
    prepare.add_argument("target", choices=TARGETS)
    prepare.add_argument("packages", type=Path)
    prepare.add_argument("destination", type=Path)
    archive = commands.add_parser("archive", help="verify and locate one npm archive")
    archive.add_argument("directory", type=Path)
    archive.add_argument("package")
    arguments = parser.parse_args()

    if arguments.command == "version":
        print(validate_versions(arguments.tag))
    elif arguments.command == "prepare":
        prepare_artifact(arguments.target, arguments.packages, arguments.destination)
    else:
        print(verified_archive(arguments.directory, arguments.package))


if __name__ == "__main__":
    main()
