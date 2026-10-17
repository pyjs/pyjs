import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from pyjs.android.dependencies import (
    ANDROIDX_RUNTIME_LOCK,
    resolve_android_dependency_locks,
)
from pyjs.java import JVMCompilation, JVMCompiledTest
from pyjs.testing import android_runtime
from pyjs.testing.android_runtime import (
    AndroidArtifact,
    AndroidRuntimeClasspath,
    AndroidRuntimeResolver,
    AndroidTestResult,
    RobolectricRunner,
    locked_android_artifacts,
)
from pyjs.tooling.android_artifacts import (
    AndroidArtifactClasspath,
)
from pyjs.tooling.android_artifacts import (
    locked_android_artifacts as locked_product_artifacts,
)


def _cached_artifact(cache, artifact, content):
    directory = cache / "artifacts" / artifact.group / artifact.name / artifact.version
    directory.mkdir(parents=True)
    path = directory / artifact.filename
    path.write_bytes(content)
    (directory / f"{artifact.filename}.sha256").write_text(artifact.sha256 + "\n")
    return path


def test_android_runtime_lock_contains_robolectric_and_espresso():
    artifacts = locked_android_artifacts()

    assert any(value.name == "robolectric" for value in artifacts)
    assert any(value.name == "espresso-core" for value in artifacts)
    assert any(value.robolectric_sdk == 35 for value in artifacts)


@pytest.mark.parametrize("mode", ["native", "legacy"])
def test_robolectric_sets_explicit_graphics_mode(tmp_path, monkeypatch, mode):
    runtime = AndroidRuntimeClasspath((), tmp_path / "sdk.jar")
    runner = RobolectricRunner(
        Path("java"), Path("aapt2"), Path("android.jar"), runtime, 35,
        graphics_mode=mode,
    )
    compilation = Mock()
    compilation.tests = []
    compilation.resources = []
    monkeypatch.setattr(runner, "_prepare_resources", lambda *_: ())
    monkeypatch.setattr(runner, "_results", lambda *_: {})
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(android_runtime.subprocess, "run", run)
    runner.run(compilation, tmp_path)
    assert f"-Drobolectric.graphicsMode={mode.upper()}" in run.call_args.args[0]


def test_robolectric_rejects_unknown_graphics_mode(tmp_path):
    with pytest.raises(ValueError, match="graphics_mode"):
        RobolectricRunner(
            Path("java"), Path("aapt2"), Path("android.jar"),
            AndroidRuntimeClasspath((), tmp_path / "sdk.jar"), 35,
            graphics_mode="typo",
        )


def test_android_device_runtime_contains_device_libraries_only():
    artifacts = locked_android_artifacts(android_runtime.DEVICE_LOCK)

    assert any(value.name == "runner" for value in artifacts)
    assert any(value.name == "espresso-core" for value in artifacts)
    assert any(value.name == "uiautomator" for value in artifacts)
    assert not any(value.group == "org.robolectric" for value in artifacts)


def test_androidx_runtime_lock_pins_recycler_view_and_transitive_graph():
    artifacts = locked_product_artifacts(ANDROIDX_RUNTIME_LOCK)

    coordinates = {
        (value.group, value.name, value.version, value.extension) for value in artifacts
    }
    assert len(coordinates) == 24
    assert (
        "androidx.recyclerview",
        "recyclerview",
        "1.4.0",
        "aar",
    ) in coordinates
    assert ("androidx.core", "core", "1.13.0", "aar") in coordinates
    assert (
        "androidx.customview",
        "customview",
        "1.0.0",
        "aar",
    ) in coordinates


def test_android_artifact_classpaths_merge_without_duplicate_packaging(tmp_path):
    shared = tmp_path / "shared.jar"
    first = AndroidArtifactClasspath(
        (shared, tmp_path / "first.jar"),
        (tmp_path / "first.aar",),
    )
    second = AndroidArtifactClasspath(
        (shared, tmp_path / "second.jar"),
        (tmp_path / "first.aar", tmp_path / "second.aar"),
    )

    assert AndroidArtifactClasspath.merge(first, second) == AndroidArtifactClasspath(
        (shared, tmp_path / "first.jar", tmp_path / "second.jar"),
        (tmp_path / "first.aar", tmp_path / "second.aar"),
    )


def test_named_android_dependency_locks_resolve_as_one_classpath(tmp_path):
    locks = []
    for name in ("first", "second"):
        lock = tmp_path / f"{name}.json"
        lock.write_text('{"version": 1, "artifacts": []}')
        locks.append((name, lock))
    progress = Mock()

    result = resolve_android_dependency_locks(
        tmp_path / "cache",
        tuple(locks),
        progress,
    )

    assert result == AndroidArtifactClasspath((), ())
    assert [call.args[0] for call in progress.call_args_list] == [
        "Resolving Android dependency set first",
        "Resolving Android dependency set second",
    ]


def test_named_android_dependency_locks_reject_version_conflicts(tmp_path):
    locks = []
    for name, version in (("first", "1"), ("second", "2")):
        lock = tmp_path / f"{name}.json"
        lock.write_text(
            json.dumps(
                {
                    "version": 1,
                    "artifacts": [
                        {
                            "group": "example",
                            "name": "shared",
                            "version": version,
                            "extension": "jar",
                            "repository": "central",
                            "sha256": version * 64,
                        }
                    ],
                }
            )
        )
        locks.append((name, lock))

    with pytest.raises(RuntimeError, match="conflicting example:shared"):
        resolve_android_dependency_locks(tmp_path / "cache", tuple(locks))


@pytest.mark.parametrize("device", [False, True])
def test_android_runtime_resolver_extracts_locked_aars(tmp_path, monkeypatch, device):
    jar_content = b"plain jar"
    aar_path = tmp_path / "fixture.aar"
    with zipfile.ZipFile(aar_path, "w") as archive:
        archive.writestr("classes.jar", b"aar classes")
    aar_content = aar_path.read_bytes()
    sdk_content = b"android all"
    artifacts = (
        AndroidArtifact(
            "example",
            "plain",
            "1",
            "jar",
            "central",
            hashlib.sha256(jar_content).hexdigest(),
        ),
        AndroidArtifact(
            "example",
            "views",
            "1",
            "aar",
            "central",
            hashlib.sha256(aar_content).hexdigest(),
        ),
        AndroidArtifact(
            "example",
            "android-all",
            "1",
            "jar",
            "central",
            hashlib.sha256(sdk_content).hexdigest(),
            robolectric_sdk=35,
        ),
    )
    def locked_artifacts(lock=android_runtime.LOCK):
        assert lock == (android_runtime.DEVICE_LOCK if device else android_runtime.LOCK)
        return artifacts[:2] if device else artifacts

    monkeypatch.setattr(android_runtime, "locked_android_artifacts", locked_artifacts)
    cache = tmp_path / "cache"
    for artifact, content in zip(
        artifacts,
        (jar_content, aar_content, sdk_content),
        strict=True,
    ):
        _cached_artifact(cache, artifact, content)

    resolver = AndroidRuntimeResolver(cache)
    runtime = resolver.resolve_device() if device else resolver.resolve(35)

    assert [path.read_bytes() for path in runtime.jars] == [
        jar_content,
        b"aar classes",
    ]
    if not device:
        assert runtime.robolectric_sdk.read_bytes() == sdk_content


def test_android_runtime_resolves_only_the_selected_locked_sdk(
    tmp_path,
    monkeypatch,
):
    artifacts = (
        AndroidArtifact("example", "runtime", "1", "jar", "central", "runtime"),
        AndroidArtifact(
            "example",
            "android-34",
            "1",
            "jar",
            "central",
            "sdk-34",
            robolectric_sdk=34,
        ),
        AndroidArtifact(
            "example",
            "android-35",
            "1",
            "jar",
            "central",
            "sdk-35",
            robolectric_sdk=35,
        ),
    )
    monkeypatch.setattr(android_runtime, "locked_android_artifacts", lambda: artifacts)
    resolver = AndroidRuntimeResolver(tmp_path)
    resolver._artifact = Mock(side_effect=lambda artifact: tmp_path / artifact.filename)

    runtime = resolver.resolve(35)

    assert runtime.jars == (tmp_path / "runtime-1.jar",)
    assert runtime.robolectric_sdk == tmp_path / "android-35-1.jar"
    assert [call.args[0] for call in resolver._artifact.call_args_list] == [
        artifacts[0],
        artifacts[2],
    ]


def test_android_runtime_rejects_an_unlocked_sdk_before_resolving_artifacts(
    tmp_path,
    monkeypatch,
):
    artifacts = (
        AndroidArtifact(
            "example",
            "android-35",
            "1",
            "jar",
            "central",
            "sdk-35",
            robolectric_sdk=35,
        ),
    )
    monkeypatch.setattr(android_runtime, "locked_android_artifacts", lambda: artifacts)
    resolver = AndroidRuntimeResolver(tmp_path)
    resolver._artifact = Mock()

    with pytest.raises(RuntimeError, match="Android API 34 is not locked"):
        resolver.resolve(34)

    resolver._artifact.assert_not_called()


def test_robolectric_results_map_junit_methods_to_pytest_nodeids():
    compilation = JVMCompilation(
        "Tests",
        {},
        (
            JVMCompiledTest("test_notes.py::test_pass", "Tests$Suite", "test_0_pass"),
            JVMCompiledTest("test_notes.py::test_fail", "Tests$Suite", "test_1_fail"),
        ),
    )
    completed = subprocess.CompletedProcess(
        [],
        1,
        stdout="""JUnit version 4.13.2
.E
There was 1 failure:
1) test_1_fail(Tests$Suite)
java.lang.AssertionError: broken
    at Tests.test_fail(test_notes.py:7)

FAILURES!!!
Tests run: 2, Failures: 1
""",
        stderr="",
    )

    assert RobolectricRunner._results(compilation, completed) == {
        "test_notes.py::test_pass": AndroidTestResult("passed"),
        "test_notes.py::test_fail": AndroidTestResult(
            "failed",
            "1) test_1_fail(Tests$Suite)\n"
            "java.lang.AssertionError: broken\n"
            "    at Tests.test_fail(test_notes.py:7)\n\n"
            "FAILURES!!!\nTests run: 2, Failures: 1",
        ),
    }


def test_robolectric_prepares_binary_resources_for_generated_activities(
    tmp_path,
    monkeypatch,
):
    manifest = tmp_path / "resources" / "AndroidManifest.xml"
    manifest.parent.mkdir()
    manifest.write_text("<manifest />")
    compilation = JVMCompilation(
        "Tests",
        {},
        resources=(manifest.parent,),
    )
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        Path(command[3]).write_bytes(b"resource apk")

    monkeypatch.setattr(subprocess, "run", run)
    runner = RobolectricRunner(
        tmp_path / "java",
        tmp_path / "aapt2",
        tmp_path / "android.jar",
        AndroidRuntimeClasspath((), tmp_path / "android-all.jar"),
        35,
    )

    classes = tmp_path / "classes"
    classes.mkdir()
    runner._prepare_resources(compilation, classes)

    assert commands[0][0][:4] == [
        tmp_path / "aapt2",
        "link",
        "-o",
        classes / "pyjs-test-resources.ap_",
    ]
    configuration = (classes / "com/android/tools/test_config.properties").read_text()
    assert f"android_merged_manifest={manifest.as_uri()}" in configuration
    assert "android_custom_package=org.pyjs.testing" in configuration


def test_robolectric_links_dependency_resources_and_returns_their_classes(
    tmp_path,
):
    manifest = tmp_path / "resources" / "AndroidManifest.xml"
    manifest.parent.mkdir()
    manifest.write_text("<manifest />")
    compilation = JVMCompilation("Tests", {}, resources=(manifest.parent,))
    dependencies = AndroidArtifactClasspath((), (tmp_path / "widgets.aar",))
    generated = tmp_path / "generated-classes"
    linker = Mock()
    linker.link.return_value = generated
    runner = RobolectricRunner(
        tmp_path / "java",
        tmp_path / "aapt2",
        tmp_path / "android.jar",
        AndroidRuntimeClasspath((), tmp_path / "android-all.jar"),
        35,
        resource_linker=linker,
        dependencies=dependencies,
    )

    classes = tmp_path / "classes"
    classes.mkdir()

    assert runner._prepare_resources(compilation, classes) == (generated,)
    linker.link.assert_called_once_with(
        tmp_path / "android.jar",
        manifest,
        classes / "pyjs-test-resources.ap_",
        classes / "android-resource-build",
        min_sdk=21,
        target_sdk=35,
        dependencies=dependencies,
    )
