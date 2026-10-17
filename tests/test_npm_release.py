import io
import json
import shutil
import subprocess
import tarfile

import pytest
import yaml

from npm.scripts import release
from npm.scripts.generate_packages import NPM_ROOT, TARGETS, write_runtime_package
from npm.scripts.release import (
    launcher_version,
    prepare_artifact,
    validate_versions,
    verified_archive,
)


def write_package(path, name, version, **metadata):
    package = {"name": name, "version": version, **metadata}
    content = json.dumps(package).encode()
    member = tarfile.TarInfo("package/package.json")
    member.size = len(content)
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(member, io.BytesIO(content))


def test_release_versions_and_tag_agree():
    assert validate_versions() == "0.4.0"
    assert launcher_version() == "0.4.1"

    with pytest.raises(RuntimeError, match="cannot use a full release tag"):
        validate_versions("v0.4.0")


@pytest.fixture
def launcher_manifest(tmp_path, monkeypatch):
    for directory in ("cli", "runtime"):
        (tmp_path / directory).mkdir()
    shutil.copy2(
        NPM_ROOT / "runtime/package.json.template",
        tmp_path / "runtime/package.json.template",
    )
    manifest = json.loads((NPM_ROOT / "cli/package.json").read_text())
    monkeypatch.setattr(release, "NPM_ROOT", tmp_path)
    return tmp_path / "cli/package.json", manifest


@pytest.mark.parametrize("version", ["0.3.9", "0.5.0", "0.4.1-rc.1", "latest"])
def test_launcher_revision_rejects_non_patch_versions(launcher_manifest, version):
    path, manifest = launcher_manifest
    manifest["version"] = version
    path.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="must increase the patch version"):
        validate_versions()


def test_full_release_still_requires_matching_tag(launcher_manifest):
    path, manifest = launcher_manifest
    manifest["version"] = "0.4.0"
    path.write_text(json.dumps(manifest))
    assert validate_versions("v0.4.0") == "0.4.0"
    with pytest.raises(RuntimeError, match="does not match v0.4.0"):
        validate_versions("v0.5.0")


def test_launcher_patch_cannot_change_runtime_versions(launcher_manifest):
    path, manifest = launcher_manifest
    manifest["optionalDependencies"]["@pyjsdev/cli-linux-arm64"] = "0.4.1"
    path.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="Release versions do not agree"):
        validate_versions()


def test_release_requires_every_runtime_in_launcher(monkeypatch):
    monkeypatch.delitem(TARGETS, "linux-arm64")
    with pytest.raises(
        RuntimeError, match="Launcher optional dependencies must match runtime targets"
    ):
        validate_versions()


@pytest.mark.parametrize("target", TARGETS.values(), ids=lambda target: target.name)
def test_runtime_package_selectors_and_executable(target, tmp_path):
    write_runtime_package(target, tmp_path, validate_versions())
    manifest = json.loads((tmp_path / "package.json").read_text())
    assert manifest == {
        "name": target.package_name,
        "version": "0.4.0",
        "description": f"Portable PyJS runtime for {target.name}",
        "license": "BSD-3-Clause",
        "repository": {
            "type": "git",
            "url": "git+https://github.com/pyjs/pyjs.git",
            "directory": "npm",
        },
        "homepage": "https://github.com/pyjs/pyjs",
        "os": [target.os],
        "cpu": [target.cpu],
        **({"libc": [target.libc]} if target.libc else {}),
        "files": ["python", "LICENSE"],
        "pyjsRuntime": {
            "python": target.python_executable,
            "pythonVersion": target.python_version,
            "pythonBuild": target.python_build,
        },
    }


@pytest.mark.parametrize(
    "platform,arch,glibc,message",
    [
        *[
            (
                target.os, target.cpu, "2.39",
                f"The platform package {target.package_name} is missing. "
                "Reinstall @pyjsdev/cli without omitting optional dependencies.",
            )
            for target in TARGETS.values()
        ],
        *[
            ("linux", arch, None,
             "The PyJS npm prototype does not support Linux musl yet.")
            for arch in ("x64", "arm64")
        ],
        ("linux", "riscv64", "2.39",
         "The PyJS npm prototype does not support linux-riscv64 yet."),
    ],
)
def test_launcher_selects_runtime_or_explains_unsupported_platform(
    platform, arch, glibc, message,
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the npm launcher")
    result = subprocess.run(
        [node, "-e", """
const fs = require("node:fs");
const vm = require("node:vm");
const [filename, platform, arch, glibc] = process.argv.slice(1);
const mockedRequire = name => require(name);
mockedRequire.resolve = () => {
  throw Object.assign(new Error("missing"), { code: "MODULE_NOT_FOUND" });
};
vm.runInNewContext(fs.readFileSync(filename, "utf8"), {
  require: mockedRequire,
  console,
  process: {
    platform, arch,
    report: { getReport: () => ({ header: {
      glibcVersionRuntime: JSON.parse(glibc),
    } }) },
    exit: code => { process.exitCode = code; },
  },
});
""", str(NPM_ROOT / "cli/bin/pyjs.cjs"), platform, arch, json.dumps(glibc)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"pyjs: {message}\n"


def test_public_workflow_builds_and_gates_every_runtime():
    workflows = NPM_ROOT.parent / ".github/workflows"
    jobs = yaml.safe_load((workflows / "publish.yml").read_text())["jobs"]
    builds = {
        job["with"]["target"]: (name, job)
        for name, job in jobs.items()
        if job.get("uses") == "./.github/workflows/build-runtime.yml"
        and name != "build-single"
    }
    assert builds.keys() == TARGETS.keys()
    # Platforms share preflight but never serialize behind another OS build.
    for _, job in builds.values():
        assert job["needs"] == "preflight"
        assert job["if"] == "github.event_name == 'push' || inputs.target == 'all'"
    assert builds["linux-arm64"][1]["with"]["runner"] == "ubuntu-24.04-arm"
    publication = jobs["publish-runtimes"]
    assert {name for name, job in builds.values()} == set(publication["needs"])
    assert publication["strategy"]["matrix"]["include"] == [
        {"artifact": job["with"]["artifact"], "package": TARGETS[target].package_name}
        for target, (name, job) in builds.items()
    ]
    assert "publish-runtimes" in jobs["publish-launcher"]["needs"]
    assert jobs["build-single"]["needs"] == "preflight"
    assert jobs["build-single"]["with"]["include-launcher"] is True
    assert jobs["publish-runtimes"]["if"] == "github.event_name == 'push'"
    assert jobs["publish-launcher"]["if"] == "github.event_name == 'push'"


def test_shared_runtime_build_checks_python_packages_and_can_avoid_pr_archives():
    workflow = yaml.safe_load((NPM_ROOT.parent / ".github/workflows/build-runtime.yml").read_text())
    assert workflow[True]["workflow_call"]["inputs"]["retain-artifact"]["default"] is True
    steps = workflow["jobs"]["build"]["steps"]
    assert any(step.get("run") == "python scripts/check_distributions.py" for step in steps)
    for name in ("Prepare release artifact", "Upload release artifact"):
        assert next(step for step in steps if step.get("name") == name)["if"] == "inputs.retain-artifact"
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False


@pytest.mark.parametrize("include_launcher", [False, True])
def test_arm64_artifact_verifies_checksum(tmp_path, include_launcher):
    packages = tmp_path / "packages"
    packages.mkdir()
    target = TARGETS["linux-arm64"]
    write_runtime_package(target, tmp_path, validate_versions())
    metadata = json.loads((tmp_path / "package.json").read_text())
    write_package(packages / "runtime.tgz", **metadata)
    write_package(packages / "cli.tgz", "@pyjsdev/cli", launcher_version())
    destination = tmp_path / "artifact"

    prepare_artifact(
        "linux-arm64", packages, destination, include_launcher=include_launcher,
    )

    manifest = json.loads((destination / "manifest.json").read_text())
    if include_launcher:
        assert verified_archive(destination, "@pyjsdev/cli") == destination / "cli.tgz"
        launcher = manifest["packages"].pop(0)
        assert launcher["name"] == "@pyjsdev/cli"
        assert launcher["version"] == launcher_version()
    assert manifest == {
        "schema": 1,
        "target": "linux-arm64",
        "version": "0.4.0",
        "packages": [{
            "cpu": ["arm64"],
            "file": "runtime.tgz",
            "libc": ["glibc"],
            "name": target.package_name,
            "os": ["linux"],
            "pyjsRuntime": metadata["pyjsRuntime"],
            "sha256": manifest["packages"][0]["sha256"],
            "version": "0.4.0",
        }],
    }
    assert (destination / "cli.tgz").exists() is include_launcher
    assert verified_archive(destination, target.package_name) == destination / "runtime.tgz"
    (destination / "runtime.tgz").write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="Checksum failed for runtime.tgz"):
        verified_archive(destination, target.package_name)


def test_release_artifact_records_and_verifies_package_metadata(tmp_path):
    packages = tmp_path / "packages"
    packages.mkdir()
    write_package(
        packages / "runtime.tgz",
        "@pyjsdev/cli-linux-x64",
        "0.4.0",
        os=["linux"],
        cpu=["x64"],
        libc=["glibc"],
        pyjsRuntime={"pythonVersion": "3.14.7"},
    )
    write_package(packages / "cli.tgz", "@pyjsdev/cli", launcher_version())
    write_package(packages / "stale-cli.tgz", "@pyjsdev/cli", "0.3.0")
    destination = tmp_path / "artifact"

    prepare_artifact("linux-x64", packages, destination)

    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest == {
        "packages": [
            {
                "cpu": None,
                "file": "cli.tgz",
                "libc": None,
                "name": "@pyjsdev/cli",
                "os": None,
                "pyjsRuntime": None,
                "sha256": manifest["packages"][0]["sha256"],
                "version": launcher_version(),
            },
            {
                "cpu": ["x64"],
                "file": "runtime.tgz",
                "libc": ["glibc"],
                "name": "@pyjsdev/cli-linux-x64",
                "os": ["linux"],
                "pyjsRuntime": {"pythonVersion": "3.14.7"},
                "sha256": manifest["packages"][1]["sha256"],
                "version": "0.4.0",
            },
        ],
        "schema": 1,
        "target": "linux-x64",
        "version": "0.4.0",
    }
    assert verified_archive(destination, "@pyjsdev/cli") == destination / "cli.tgz"
    assert verified_archive(
        destination,
        "@pyjsdev/cli-linux-x64",
    ) == destination / "runtime.tgz"
    assert (destination / "SHA256SUMS").read_text().splitlines() == [
        f'{manifest["packages"][0]["sha256"]}  cli.tgz',
        f'{manifest["packages"][1]["sha256"]}  runtime.tgz',
    ]

    (destination / "runtime.tgz").write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="Checksum failed for runtime.tgz"):
        verified_archive(destination, "@pyjsdev/cli-linux-x64")
