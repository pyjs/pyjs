"""Resolve and execute the locked Robolectric Android test runtime."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pyjs.java import JVMCompilation
from pyjs.tooling.android_artifacts import (
    AndroidArtifact,
    AndroidArtifactClasspath,
    AndroidArtifactResolver,
)
from pyjs.tooling.android_artifacts import (
    locked_android_artifacts as _locked_android_artifacts,
)
from pyjs.tooling.android_jvm import AndroidResourceLinker

LOCK = Path(__file__).with_name("android_runtime.json")
DEVICE_LOCK = Path(__file__).with_name("android_device_runtime.json")


@dataclass(frozen=True)
class AndroidRuntimeClasspath:
    jars: tuple[Path, ...]
    robolectric_sdk: Path


@dataclass(frozen=True)
class AndroidDeviceClasspath:
    jars: tuple[Path, ...]


def locked_android_artifacts(
    lock: Path = LOCK,
) -> tuple[AndroidArtifact, ...]:
    return _locked_android_artifacts(lock)


class AndroidRuntimeResolver(AndroidArtifactResolver):
    def resolve(self, api: int) -> AndroidRuntimeClasspath:
        artifacts = locked_android_artifacts()
        sdk_artifact = next(
            (
                artifact
                for artifact in artifacts
                if artifact.robolectric_sdk == api
            ),
            None,
        )
        if sdk_artifact is None:
            raise RuntimeError(f"Robolectric Android API {api} is not locked")
        classpath = self.resolve_artifacts(
            artifact for artifact in artifacts if artifact.robolectric_sdk is None
        )
        return AndroidRuntimeClasspath(classpath.jars, self._artifact(sdk_artifact))

    def resolve_device(self) -> AndroidDeviceClasspath:
        classpath = self.resolve_artifacts(locked_android_artifacts(DEVICE_LOCK))
        return AndroidDeviceClasspath(classpath.jars)


@dataclass(frozen=True)
class AndroidTestResult:
    outcome: str
    error: str | None = None


class RobolectricRunner:
    JVM_ARGUMENTS = (
        "--add-opens=java.base/java.lang=ALL-UNNAMED",
        "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED",
        "--add-opens=java.base/java.io=ALL-UNNAMED",
        "--add-opens=java.base/java.util=ALL-UNNAMED",
        "--add-opens=java.base/java.util.concurrent=ALL-UNNAMED",
    )

    def __init__(
        self,
        java: Path,
        aapt2: Path,
        android_jar: Path,
        runtime: AndroidRuntimeClasspath,
        api: int,
        resource_linker: AndroidResourceLinker | None = None,
        dependencies: AndroidArtifactClasspath | None = None,
        graphics_mode: str = "native",
    ) -> None:
        if graphics_mode not in {"native", "legacy"}:
            raise ValueError("graphics_mode must be native or legacy")
        self.graphics_mode = graphics_mode
        self.java = Path(java)
        self.aapt2 = Path(aapt2)
        self.android_jar = Path(android_jar)
        self.runtime = runtime
        self.api = api
        self.resource_linker = resource_linker
        self.dependencies = dependencies

    def run(
        self,
        compilation: JVMCompilation,
        classes: Path,
        *,
        timeout: float = 120,
    ) -> dict[str, AndroidTestResult]:
        compilation.write(classes)
        resource_classes = self._prepare_resources(compilation, classes)
        test_classes = tuple(dict.fromkeys(test.class_name for test in compilation.tests))
        classpath = [
            classes,
            *resource_classes,
            *compilation.resources,
            self.android_jar,
            *self.runtime.jars,
        ]
        command = [
            self.java,
            *self.JVM_ARGUMENTS,
            f"-Drobolectric.dependency.dir={self.runtime.robolectric_sdk.parent}",
            "-Drobolectric.offline=true",
            f"-Drobolectric.graphicsMode={self.graphics_mode.upper()}",
            "-cp",
            os.pathsep.join(str(path) for path in classpath),
            "org.junit.runner.JUnitCore",
            *(name.replace("/", ".") for name in test_classes),
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return self._results(compilation, completed)

    def _prepare_resources(
        self,
        compilation: JVMCompilation,
        classes: Path,
    ) -> tuple[Path, ...]:
        manifest = next(
            (
                directory / "AndroidManifest.xml"
                for directory in compilation.resources
                if (directory / "AndroidManifest.xml").is_file()
            ),
            None,
        )
        if manifest is None:
            return ()
        resources = classes / "pyjs-test-resources.ap_"
        generated = ()
        if self.dependencies is not None:
            if self.resource_linker is None:
                raise RuntimeError(
                    "Android dependencies require a Robolectric resource linker"
                )
            generated = (
                self.resource_linker.link(
                    self.android_jar,
                    manifest,
                    resources,
                    classes / "android-resource-build",
                    min_sdk=21,
                    target_sdk=self.api,
                    dependencies=self.dependencies,
                ),
            )
        else:
            subprocess.run(
                [
                    self.aapt2,
                    "link",
                    "-o",
                    resources,
                    "-I",
                    self.android_jar,
                    "--manifest",
                    manifest,
                    "--min-sdk-version",
                    "21",
                    "--target-sdk-version",
                    str(self.api),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        configuration = classes / "com/android/tools/test_config.properties"
        configuration.parent.mkdir(parents=True, exist_ok=True)
        configuration.write_text(
            f"android_merged_manifest={manifest.as_uri()}\n"
            f"android_resource_apk={resources.as_uri()}\n"
            "android_custom_package=org.pyjs.testing\n"
        )
        return generated

    @staticmethod
    def _results(
        compilation: JVMCompilation,
        completed: subprocess.CompletedProcess[str],
    ) -> dict[str, AndroidTestResult]:
        if completed.returncode == 0:
            return {
                test.nodeid: AndroidTestResult("passed")
                for test in compilation.tests
            }
        output = completed.stdout + completed.stderr
        results = {
            test.nodeid: AndroidTestResult("passed") for test in compilation.tests
        }
        methods = {test.method_name: test.nodeid for test in compilation.tests}
        failures = output.split("There was", 1)[-1] if "There was" in output else output
        located = False
        matches = tuple(re.finditer(r"(?m)^\d+\) ([^(]+)\(", failures))
        for index, match in enumerate(matches):
            method = match.group(1)
            nodeid = methods.get(method)
            if nodeid is None:
                continue
            located = True
            end = matches[index + 1].start() if index + 1 < len(matches) else None
            error = failures[match.start():end].strip()
            results[nodeid] = AndroidTestResult("failed", error)
        if not located:
            error = output.strip() or f"JUnit exited with status {completed.returncode}"
            return {
                test.nodeid: AndroidTestResult("failed", error)
                for test in compilation.tests
            }
        return results


__all__ = [
    "AndroidArtifact",
    "AndroidDeviceClasspath",
    "AndroidRuntimeClasspath",
    "AndroidRuntimeResolver",
    "AndroidTestResult",
    "RobolectricRunner",
    "locked_android_artifacts",
]
