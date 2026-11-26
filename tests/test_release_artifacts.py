import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest
import yaml

from npm.scripts import release
from scripts import check_distributions


@pytest.fixture
def python_packages(tmp_path):
    packages = tmp_path / "packages"
    packages.mkdir()
    version = release.validate_versions()
    for name in release.PYTHON_PACKAGES:
        stem = f"{name.replace('-', '_')}-{version}"
        metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\n".encode()
        with zipfile.ZipFile(packages / f"{stem}-py3-none-any.whl", "w") as archive:
            archive.writestr(f"{stem}.dist-info/METADATA", metadata)
        with tarfile.open(packages / f"{stem}.tar.gz", "w:gz") as archive:
            member = tarfile.TarInfo(f"{stem}/PKG-INFO")
            member.size = len(metadata)
            archive.addfile(member, io.BytesIO(metadata))
    return packages


def test_retained_python_archives_are_identical_and_grouped(python_packages, tmp_path):
    artifact = tmp_path / "artifact"
    release.prepare_python_artifact(python_packages, artifact)
    paths = release.verified_python_archives(artifact)
    assert len(paths) == 6
    assert {path.parent.name for path in paths} == set(release.PYTHON_PACKAGES)
    for path in paths:
        assert path.read_bytes() == (python_packages / path.name).read_bytes()
    assert len((artifact / "SHA256SUMS").read_text().splitlines()) == 6
    with pytest.raises(FileExistsError):
        release.prepare_python_artifact(python_packages, artifact)


@pytest.mark.parametrize("damage", ["missing", "extra", "wrong-metadata"])
def test_python_preparation_rejects_bad_distribution_sets(python_packages, tmp_path, damage):
    path = next(python_packages.glob("*.whl"))
    if damage == "missing":
        path.unlink()
    elif damage == "extra":
        shutil.copy2(path, python_packages / "pyjs-0.4.0-py3-none-any.whl")
    else:
        with zipfile.ZipFile(path) as archive:
            member = archive.namelist()[0]
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(member, "Name: unrelated\nVersion: 0.5.0\n")
    with pytest.raises(RuntimeError, match="six current|metadata mismatch"):
        release.prepare_python_artifact(python_packages, tmp_path / "artifact")
    assert not (tmp_path / "artifact").exists()


@pytest.mark.parametrize("damage", ["corrupt", "missing", "extra", "version", "traversal"])
def test_python_verification_rejects_artifact_changes(python_packages, tmp_path, damage):
    artifact = tmp_path / "artifact"
    release.prepare_python_artifact(python_packages, artifact)
    manifest = json.loads((artifact / "manifest.json").read_text())
    path = artifact / next(iter(manifest["files"]))
    if damage == "corrupt":
        path.write_bytes(b"corrupted")
    elif damage == "missing":
        path.unlink()
    elif damage == "extra":
        (artifact / "pyjs" / "unexpected.whl").touch()
    else:
        if damage == "version":
            manifest["version"] = "0.4.0"
        else:
            manifest["files"]["../escape.whl"] = "0" * 64
        (artifact / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="Checksum|Unexpected files|metadata do not agree"):
        release.verified_python_archives(artifact)


def test_failed_installation_never_retains_publishable_archives(tmp_path, monkeypatch):
    output = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["check_distributions", "--out-dir", str(output)])
    monkeypatch.setattr(check_distributions, "distributions", lambda path: [path / "a.whl"])
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["uv", "pip", "install"]:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(check_distributions.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        check_distributions.main()
    assert not output.exists()
    assert not any("python" in command and "release.py" in " ".join(command) for command in calls)


def test_workspace_dependency_pins_are_checked(tmp_path, monkeypatch):
    for relative in ("pyjs/__init__.py", "pyproject.toml", "examples/pyproject.toml",
                     "extras/pyproject.toml"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(release.PROJECT_ROOT / relative, path)
    monkeypatch.setattr(release, "PROJECT_ROOT", tmp_path)
    path = tmp_path / "examples/pyproject.toml"
    path.write_text(path.read_text().replace('"pyjs==0.5.0"', '"pyjs>=0.4.0"'))
    with pytest.raises(RuntimeError, match="Workspace dependency must pin"):
        release.validate_versions()


@pytest.fixture
def complete_artifacts(python_packages, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    release.prepare_python_artifact(python_packages, artifacts / "python-dist")
    version = release.validate_versions()
    for target in release.TARGETS.values():
        packages = tmp_path / target.name
        packages.mkdir()
        names = [target.package_name]
        if target.name == "linux-x64":
            names.append("@pyjsdev/cli")
        for name in names:
            content = json.dumps({"name": name, "version": version}).encode()
            filename = name.replace("@", "").replace("/", "-") + f"-{version}.tgz"
            with tarfile.open(packages / filename, "w:gz") as archive:
                member = tarfile.TarInfo("package/package.json")
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        release.prepare_artifact(target.name, packages, artifacts / f"npm-{target.name}")
    return artifacts


def test_github_bundle_contains_all_tested_bytes_and_source_identity(complete_artifacts, tmp_path):
    destination = tmp_path / "bundle"
    release.github_artifact(complete_artifacts, destination, "a" * 40)
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["version"] == "0.5.0"
    assert manifest["revision"] == "a" * 40
    assert len(manifest["files"]) == 13  # Twelve archives plus release notes.
    for filename, digest in manifest["files"].items():
        assert release.sha256(destination / filename) == digest
        if filename != "RELEASE_NOTES.md":
            original, = complete_artifacts.rglob(filename)
            assert (destination / filename).read_bytes() == original.read_bytes()


def test_github_bundle_requires_every_target(complete_artifacts, tmp_path):
    shutil.rmtree(complete_artifacts / "npm-win32-x64")
    with pytest.raises(FileNotFoundError):
        release.github_artifact(complete_artifacts, tmp_path / "bundle", "a" * 40)
    assert not (tmp_path / "bundle").exists()


def test_publication_uses_gated_artifacts_and_scoped_permissions():
    workflow = yaml.safe_load((release.PROJECT_ROOT / ".github/workflows/publish.yml").read_text())
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert jobs["assemble"]["needs"] == ["preflight", "validate", "validate-native"]
    for name in ("publish-python", "publish-runtimes", "publish-launcher", "github-release"):
        assert jobs[name]["if"] == "github.event_name == 'push'"
        assert jobs[name]["environment"] in ("pypi", "npm", "release")
    python = jobs["publish-python"]
    assert python["needs"] == ["preflight", "assemble"]
    assert python["permissions"] == {"contents": "read", "id-token": "write"}
    uploads = [step for step in python["steps"] if step.get("uses", "").startswith("pypa/")]
    assert [step["with"]["packages-dir"] for step in uploads] == [
        "python-dist/pyjs", "python-dist/pyjs-examples", "python-dist/pyjs-extras",
    ]
    assert all("password" not in step["with"] and "skip-existing" not in step["with"]
               for step in uploads)
    assert set(jobs["github-release"]["needs"]) == {
        "preflight", "assemble", "publish-python", "publish-launcher",
    }
    assert jobs["github-release"]["permissions"] == {"contents": "write"}
    for name in ("assemble", "publish-python", "github-release"):
        commands = "\n".join(step.get("run", "") for step in jobs[name]["steps"])
        assert "uv build" not in commands and "build_runtime.py" not in commands
