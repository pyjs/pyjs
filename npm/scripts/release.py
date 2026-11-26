"""Validate release metadata and assemble tested distribution artifacts."""

import argparse
import ast
import hashlib
import json
import re
import shutil
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

try:
    from .generate_packages import NPM_ROOT, TARGETS
except ImportError:
    from generate_packages import NPM_ROOT, TARGETS

PROJECT_ROOT = NPM_ROOT.parent
PUBLIC_REPOSITORY = "git+https://github.com/pyjs/pyjs.git"
PYTHON_PACKAGES = ("pyjs", "pyjs-examples", "pyjs-extras")


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


def launcher_version() -> str:
    return json.loads((NPM_ROOT / "cli" / "package.json").read_text())["version"]


def validate_versions(tag: str | None = None) -> str:
    version = pyjs_version()
    cli = json.loads((NPM_ROOT / "cli" / "package.json").read_text())
    expected_packages = {target.package_name for target in TARGETS.values()}
    if set(cli["optionalDependencies"]) != expected_packages:
        raise RuntimeError("Launcher optional dependencies must match runtime targets")
    versions = {
        "pyjs": version,
        "pyjs-examples": project_version(PROJECT_ROOT / "examples" / "pyproject.toml"),
        "pyjs-extras": project_version(PROJECT_ROOT / "extras" / "pyproject.toml"),
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
    for path in (PROJECT_ROOT / "pyproject.toml",
                 PROJECT_ROOT / "examples/pyproject.toml",
                 PROJECT_ROOT / "extras/pyproject.toml"):
        metadata = tomllib.loads(path.read_text())
        project = metadata["project"]
        dependencies = [*project.get("dependencies", [])]
        for group in (*project.get("optional-dependencies", {}).values(),
                      *metadata.get("dependency-groups", {}).values()):
            dependencies.extend(item for item in group if isinstance(item, str))
        for dependency in dependencies:
            match = re.match(r"(pyjs(?:-examples|-extras)?)(?:\[[^]]+\])?(.*)$",
                             dependency)
            if match and match[2] != f"=={version}":
                raise RuntimeError(f"Workspace dependency must pin {version}: {dependency}")
    if cli["version"] != version:
        runtime_parts = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
        launcher_parts = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", cli["version"])
        if (
            tag is not None
            or runtime_parts is None
            or launcher_parts is None
            or runtime_parts.group(1, 2) != launcher_parts.group(1, 2)
            or int(launcher_parts[3]) <= int(runtime_parts[3])
        ):
            raise RuntimeError(
                "A launcher-only revision must increase the patch version of "
                f"{version} and cannot use a full release tag"
            )
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


def prepare_artifact(
    target_name: str, packages: Path, destination: Path, *, include_launcher=False,
) -> None:
    version = validate_versions()
    expected = {TARGETS[target_name].package_name: version}
    if target_name == "linux-x64" or include_launcher:
        expected["@pyjsdev/cli"] = launcher_version()
    archives = {}
    for archive in packages.glob("*.tgz"):
        package = package_manifest(archive)
        if expected.get(package["name"]) == package["version"]:
            archives[package["name"]] = (archive, package)
    missing = expected.keys() - archives.keys()
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
                "version": package["version"],
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
        expected_version = (
            launcher_version() if package["name"] == "@pyjsdev/cli"
            else manifest["version"]
        )
        if package["version"] != expected_version:
            raise RuntimeError("Artifact package and source versions do not agree")
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


def python_files(version):
    return {
        f"{name}/{name.replace('-', '_')}-{version}{suffix}": name
        for name in PYTHON_PACKAGES
        for suffix in ("-py3-none-any.whl", ".tar.gz")
    }


def check_python_metadata(path, name, version):
    stem = f"{name.replace('-', '_')}-{version}"
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            content = archive.read(f"{stem}.dist-info/METADATA")
    else:
        with tarfile.open(path, "r:gz") as archive:
            member = archive.extractfile(f"{stem}/PKG-INFO")
            if member is None:
                raise RuntimeError(f"Missing metadata in {path.name}")
            content = member.read()
    metadata = BytesParser().parsebytes(content)
    if metadata["Name"] != name or metadata["Version"] != version:
        raise RuntimeError(f"Python archive metadata mismatch: {path.name}")


def prepare_python_artifact(packages, destination):
    version = validate_versions()
    expected = python_files(version)
    archives = {path.name for path in packages.iterdir()
                if path.name.endswith((".whl", ".tar.gz"))}
    if archives != {Path(path).name for path in expected}:
        raise RuntimeError("Expected exactly six current Python distribution archives")
    for relative, name in expected.items():
        check_python_metadata(packages / Path(relative).name, name, version)
    destination.mkdir(parents=True, exist_ok=False)
    files = {}
    for relative in expected:
        path = destination / relative
        path.parent.mkdir(exist_ok=True)
        shutil.copy2(packages / path.name, path)
        files[relative] = sha256(path)
    (destination / "manifest.json").write_text(json.dumps(
        {"schema": 1, "version": version, "files": files}, indent=2,
    ) + "\n")
    (destination / "SHA256SUMS").write_text("".join(
        f"{digest}  {name}\n" for name, digest in sorted(files.items())
    ))


def verified_python_archives(directory):
    version = validate_versions()
    manifest = json.loads((directory / "manifest.json").read_text())
    expected = python_files(version)
    if (manifest.get("schema") != 1 or manifest.get("version") != version
            or set(manifest.get("files", {})) != expected.keys()):
        raise RuntimeError("Python artifact and source metadata do not agree")
    actual = {str(path.relative_to(directory)).replace("\\", "/")
              for path in directory.rglob("*") if path.is_file()}
    if actual != expected.keys() | {"manifest.json", "SHA256SUMS"}:
        raise RuntimeError("Unexpected files in Python artifact")
    paths = []
    for relative, name in expected.items():
        path = directory / relative
        if path.is_symlink() or sha256(path) != manifest["files"][relative]:
            raise RuntimeError(f"Checksum failed for {relative}")
        check_python_metadata(path, name, version)
        paths.append(path)
    return paths


def github_artifact(artifacts, destination, revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("Expected a full release commit SHA")
    version = validate_versions(f"v{pyjs_version()}")
    archives = verified_python_archives(artifacts / "python-dist")
    for target in TARGETS.values():
        directory = artifacts / f"npm-{target.name}"
        archives.append(verified_archive(directory, target.package_name))
        if target.name == "linux-x64":
            archives.append(verified_archive(directory, "@pyjsdev/cli"))
    if len({path.name for path in archives}) != 12:
        raise RuntimeError("Expected twelve distinct release archives")
    notes = PROJECT_ROOT / "releases" / f"{version}.md"
    if not notes.is_file():
        raise RuntimeError(f"Missing release notes for {version}")
    destination.mkdir(parents=True, exist_ok=False)
    files = {}
    for archive in archives:
        shutil.copy2(archive, destination / archive.name)
        files[archive.name] = sha256(archive)
    shutil.copy2(notes, destination / "RELEASE_NOTES.md")
    files["RELEASE_NOTES.md"] = sha256(destination / "RELEASE_NOTES.md")
    (destination / "SHA256SUMS").write_text("".join(
        f"{digest}  {name}\n" for name, digest in sorted(files.items())
    ))
    (destination / "manifest.json").write_text(json.dumps(
        {"schema": 1, "version": version, "revision": revision, "files": files}, indent=2,
    ) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    version = commands.add_parser("version", help="validate and print the release version")
    version.add_argument("--tag")
    version.add_argument("--launcher", action="store_true")
    prepare = commands.add_parser("prepare", help="prepare one platform artifact")
    prepare.add_argument("target", choices=TARGETS)
    prepare.add_argument("packages", type=Path)
    prepare.add_argument("destination", type=Path)
    prepare.add_argument("--include-launcher", action="store_true")
    archive = commands.add_parser("archive", help="verify and locate one npm archive")
    archive.add_argument("directory", type=Path)
    archive.add_argument("package")
    python = commands.add_parser("python", help="retain tested Python distributions")
    python.add_argument("packages", type=Path)
    python.add_argument("destination", type=Path)
    verify_python = commands.add_parser("verify-python", help="verify Python artifacts")
    verify_python.add_argument("directory", type=Path)
    github = commands.add_parser("github", help="assemble checked GitHub release assets")
    github.add_argument("artifacts", type=Path)
    github.add_argument("destination", type=Path)
    github.add_argument("--revision", required=True)
    arguments = parser.parse_args()

    if arguments.command == "version":
        runtime_version = validate_versions(arguments.tag)
        print(launcher_version() if arguments.launcher else runtime_version)
    elif arguments.command == "prepare":
        prepare_artifact(
            arguments.target, arguments.packages, arguments.destination,
            include_launcher=arguments.include_launcher,
        )
    elif arguments.command == "archive":
        print(verified_archive(arguments.directory, arguments.package))
    elif arguments.command == "python":
        prepare_python_artifact(arguments.packages, arguments.destination)
    elif arguments.command == "verify-python":
        for path in verified_python_archives(arguments.directory):
            print(path)
    else:
        github_artifact(arguments.artifacts, arguments.destination, arguments.revision)


if __name__ == "__main__":
    main()
