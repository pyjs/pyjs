"""Package and run compiled Python tests with AndroidJUnitRunner."""

import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pyjs.java import JVMCompilation
from pyjs.java.classfile import ClassFile
from pyjs.tooling.android import AndroidDevice, AndroidSDK
from pyjs.tooling.android_artifacts import AndroidArtifactClasspath
from pyjs.tooling.android_jvm import AndroidResourceLinker

from .android_runtime import AndroidDeviceClasspath, AndroidTestResult

TARGET_PACKAGE = "org.pyjs.testing.target"
TEST_PACKAGE = "org.pyjs.testing"
RUNNER = "androidx.test.runner.AndroidJUnitRunner"


@dataclass(frozen=True)
class AndroidTestPackages:
    target: Path
    tests: Path


class AndroidDeviceTestBuilder:
    def __init__(
        self,
        sdk: AndroidSDK,
        android_jar: Path,
        runtime: AndroidDeviceClasspath,
        api: int,
        *,
        dependencies: AndroidArtifactClasspath | None = None,
    ) -> None:
        self.sdk = sdk
        self.android_jar = Path(android_jar)
        self.runtime = runtime
        self.api = api
        self.dependencies = dependencies

    def build(
        self,
        compilation: JVMCompilation,
        output: Path,
        *,
        keystore: Path | None = None,
    ) -> AndroidTestPackages:
        output.mkdir(parents=True, exist_ok=True)
        signing_key = keystore or Path.home() / ".android" / "debug.keystore"
        if not signing_key.is_file():
            raise RuntimeError(
                f"Android debug keystore not found at {signing_key}. "
                "Create it with Android Studio or keytool."
            )
        with tempfile.TemporaryDirectory(prefix="pyjs-android-tests-") as temporary:
            build = Path(temporary)
            target_classes = build / "target-classes"
            test_classes = build / "test-classes"
            self._write_split_classes(compilation, target_classes, test_classes)
            dex = build / "dex"
            dex.mkdir()
            environment = self.sdk.environment()
            environment.setdefault(
                "JAVA_OPTS",
                os.environ.get("JAVA_OPTS", "-Xmx1024m"),
            )
            self.sdk.runner.run(
                [
                    self.sdk.build_tool("d8"),
                    "--lib",
                    self.android_jar,
                    "--min-api",
                    "21",
                    "--output",
                    dex,
                    "--classpath",
                    target_classes,
                    *(
                        argument
                        for path in (
                            self.dependencies.jars
                            if self.dependencies is not None
                            else ()
                        )
                        for argument in ("--classpath", path)
                    ),
                    *sorted(test_classes.rglob("*.class")),
                    *self.runtime.jars,
                ],
                environment=environment,
                capture_output=True,
            )

            source_manifest = next(
                directory / "AndroidManifest.xml"
                for directory in compilation.resources
                if (directory / "AndroidManifest.xml").is_file()
            )
            self._validate_target_activities(
                source_manifest.read_text(),
                target_classes,
            )
            target_manifest = build / "target-AndroidManifest.xml"
            target_manifest.write_text(
                self._target_manifest(source_manifest.read_text())
            )
            target_unaligned = build / "target-unaligned.apk"
            resource_classes = AndroidResourceLinker(self.sdk).link(
                self.android_jar,
                target_manifest,
                target_unaligned,
                build / "target-resources",
                min_sdk=21,
                target_sdk=self.api,
                dependencies=self.dependencies,
            )
            target_dex = build / "target-dex"
            target_dex.mkdir()
            self.sdk.runner.run(
                [
                    self.sdk.build_tool("d8"),
                    "--lib",
                    self.android_jar,
                    "--min-api",
                    "21",
                    "--output",
                    target_dex,
                    *sorted(target_classes.rglob("*.class")),
                    *sorted(resource_classes.rglob("*.class")),
                    *(
                        self.dependencies.jars
                        if self.dependencies is not None
                        else ()
                    ),
                ],
                environment=environment,
                capture_output=True,
            )
            target = output / f"{TARGET_PACKAGE}-debug.apk"
            self._finish_package(
                target_unaligned,
                target,
                build / "target",
                signing_key,
                target_dex,
            )

            test_manifest = build / "test-AndroidManifest.xml"
            test_manifest.write_text(self._test_manifest())
            tests = output / f"{TEST_PACKAGE}-debug-androidTest.apk"
            self._package(test_manifest, tests, build / "tests", signing_key, dex)
        return AndroidTestPackages(target, tests)

    @staticmethod
    def _write_split_classes(
        compilation: JVMCompilation,
        target: Path,
        tests: Path,
    ) -> None:
        test_owners = tuple(
            f"{compilation.main_class}$module${module.replace('.', '$')}"
            for module in compilation.test_modules
        )
        wrappers = {test.class_name for test in compilation.tests}
        bridges = {
            "org/pyjs/testing/PyjsAndroid",
            "org/pyjs/testing/PyjsDevice",
            "org/pyjs/testing/PyjsDeviceElement",
            "org/pyjs/testing/PyjsView",
        }
        marker = target / "org/pyjs/testing/target/PyjsTarget.class"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(ClassFile("org/pyjs/testing/target/PyjsTarget").render())
        for name, content in compilation.classes.items():
            is_test = (
                name == compilation.main_class
                or name in wrappers
                or name in bridges
                or any(
                    name == owner or name.startswith(owner + "$")
                    for owner in test_owners
                )
            )
            destination = (tests if is_test else target) / f"{name}.class"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    @staticmethod
    def _validate_target_activities(manifest: str, classes: Path) -> None:
        for kind, activity in re.findall(
            r'<(activity|application)\b[^>]*\bandroid:name="([^"]+)"',
            manifest,
        ):
            class_file = classes / f"{activity.replace('.', '/')}.class"
            if not class_file.is_file():
                raise RuntimeError(
                    f"Android {kind} {activity} is defined in a selected test "
                    "module. Move it to an application module imported by the test."
                )

    def _package(
        self,
        manifest: Path,
        output: Path,
        build: Path,
        keystore: Path,
        dex: Path | None = None,
    ) -> None:
        build.mkdir()
        unaligned = build / "unaligned.apk"
        self.sdk.runner.run(
            [
                self.sdk.build_tool("aapt2"),
                "link",
                "-o",
                unaligned,
                "-I",
                self.android_jar,
                "--manifest",
                manifest,
                "--min-sdk-version",
                "21",
                "--target-sdk-version",
                str(self.api),
                "--version-code",
                "1",
                "--version-name",
                "0.1",
            ],
            environment=self.sdk.environment(),
        )
        if dex is not None:
            self._append_dex(unaligned, dex)
        self._finish_package(unaligned, output, build, keystore)

    def _finish_package(
        self,
        unaligned: Path,
        output: Path,
        build: Path,
        keystore: Path,
        dex: Path | None = None,
    ) -> None:
        build.mkdir(exist_ok=True)
        if dex is not None:
            self._append_dex(unaligned, dex)
        aligned = build / "aligned.apk"
        self.sdk.runner.run(
            [self.sdk.build_tool("zipalign"), "-f", "4", unaligned, aligned],
            environment=self.sdk.environment(),
        )
        self.sdk.runner.run(
            [
                self.sdk.build_tool("apksigner"),
                "sign",
                "--ks",
                keystore,
                "--ks-key-alias",
                "androiddebugkey",
                "--ks-pass",
                "pass:android",
                "--key-pass",
                "pass:android",
                "--out",
                output,
                aligned,
            ],
            environment=self.sdk.environment(),
        )

    @staticmethod
    def _append_dex(package: Path, directory: Path) -> None:
        dex_files = sorted(directory.glob("classes*.dex"))
        if not dex_files:
            raise RuntimeError("D8 did not produce any DEX files")
        with zipfile.ZipFile(package, "a") as archive:
            for dex in dex_files:
                archive.write(dex, dex.name, compress_type=zipfile.ZIP_STORED)

    def _target_manifest(self, manifest: str) -> str:
        return manifest.replace(
            'package="org.pyjs.testing"',
            f'package="{TARGET_PACKAGE}"',
        ).replace(
            "  <application",
            "  <application android:debuggable=\"true\"",
        )

    def _test_manifest(self) -> str:
        return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{TEST_PACKAGE}">
  <application android:allowBackup="false" android:debuggable="true">
    <activity
        android:name="androidx.test.core.app.InstrumentationActivityInvoker$BootstrapActivity"
        android:exported="true"
        android:theme="@android:style/Theme.Material.Light.NoActionBar" />
    <activity
        android:name="androidx.test.core.app.InstrumentationActivityInvoker$EmptyActivity"
        android:exported="true"
        android:theme="@android:style/Theme.Material.Light.NoActionBar" />
    <activity
        android:name="androidx.test.core.app.InstrumentationActivityInvoker$EmptyFloatingActivity"
        android:exported="true"
        android:theme="@android:style/Theme.Material.Light.Dialog" />
  </application>
  <instrumentation
      android:name="{RUNNER}"
      android:targetPackage="{TARGET_PACKAGE}"
      android:functionalTest="false" />
</manifest>
"""


class AndroidDeviceTestRunner:
    def __init__(self, sdk: AndroidSDK, device: AndroidDevice) -> None:
        self.sdk = sdk
        self.device = device

    def run(
        self,
        compilation: JVMCompilation,
        packages: AndroidTestPackages,
        *,
        timeout: float = 120,
    ) -> dict[str, AndroidTestResult]:
        self.sdk.install(self.device, packages.target)
        self.sdk.install(self.device, packages.tests)
        self.sdk.prepare_for_tests(self.device)
        completed = self.sdk.runner.run(
            [
                self.sdk.adb,
                "-s",
                self.device.identifier,
                "shell",
                "am",
                "instrument",
                "-w",
                "-r",
                "-e",
                "class",
                ",".join(
                    dict.fromkeys(
                        test.class_name.replace("/", ".").replace("$", r"\$")
                        for test in compilation.tests
                    )
                ),
                f"{TEST_PACKAGE}/{RUNNER}",
            ],
            environment=self.sdk.environment(),
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        return self._results(compilation, completed.stdout + completed.stderr)

    @staticmethod
    def _results(
        compilation: JVMCompilation,
        output: str,
    ) -> dict[str, AndroidTestResult]:
        methods = {test.method_name: test.nodeid for test in compilation.tests}
        results = {}
        status = {}
        for line in output.splitlines():
            if line.startswith("INSTRUMENTATION_STATUS: "):
                key, separator, value = line.removeprefix(
                    "INSTRUMENTATION_STATUS: "
                ).partition("=")
                if separator:
                    status[key] = value
            elif line.startswith("INSTRUMENTATION_STATUS_CODE:"):
                code = int(line.partition(":")[2].strip())
                nodeid = methods.get(status.get("test"))
                if nodeid is not None and code in {0, -1, -2}:
                    outcome = "passed" if code == 0 else "failed"
                    error = status.get("stack", "").strip() or None
                    results[nodeid] = AndroidTestResult(outcome, error)
                status = {}
            elif "stack" in status:
                status["stack"] += "\n" + line
        missing = [test for test in compilation.tests if test.nodeid not in results]
        for test in missing:
            summary = re.search(r"INSTRUMENTATION_FAILED:.*", output)
            error = summary.group(0) if summary else output.strip()
            results[test.nodeid] = AndroidTestResult(
                "failed",
                error or "AndroidJUnitRunner did not report a result",
            )
        return results


__all__ = [
    "AndroidDeviceTestBuilder",
    "AndroidDeviceTestRunner",
    "AndroidTestPackages",
]
