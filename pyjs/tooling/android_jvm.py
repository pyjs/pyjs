"""Build direct-JVM PyJS applications into installable Android packages."""

import ast
import re
import tempfile
import zipfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from xml.etree import ElementTree

from pyjs.java import transpile_jvm

from .android import AndroidSDK
from .android_artifacts import AndroidArtifactClasspath


@dataclass(frozen=True)
class AndroidManifestComponent:
    """One generated receiver or service declared in the application manifest."""

    kind: str
    class_name: str
    exported: bool = False
    permission: str | None = None
    actions: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        identifier = r"[A-Za-z_][A-Za-z0-9_]*"
        if self.kind not in {"receiver", "service"}:
            raise ValueError("Android manifest components must be receivers or services")
        if re.fullmatch(identifier, self.class_name) is None:
            raise ValueError(f"invalid Android component class name: {self.class_name!r}")
        if any(
            not action or any(character.isspace() for character in action)
            for action in self.actions
        ):
            raise ValueError(
                "Android component actions cannot be empty or contain whitespace"
            )
        if any(
            not name or not resource.startswith("@") for name, resource in self.metadata
        ):
            raise ValueError("Android component metadata requires names and @resources")


@dataclass(frozen=True)
class AndroidJVMApplication:
    """The source and Android identity of one direct-JVM application."""

    source: Path
    module_name: str
    app_id: str
    activity: str
    title: str
    compile_sdk: int
    min_sdk: int = 21
    target_sdk: int | None = None
    debuggable: bool = True
    resources: tuple[Path, ...] = ()
    components: tuple[AndroidManifestComponent, ...] = ()

    def __post_init__(self) -> None:
        identifier = r"[A-Za-z_][A-Za-z0-9_]*"
        if re.fullmatch(rf"{identifier}(?:\.{identifier})+", self.app_id) is None:
            raise ValueError(f"invalid Android application ID: {self.app_id!r}")
        if re.fullmatch(identifier, self.activity) is None:
            raise ValueError(f"invalid Android activity name: {self.activity!r}")
        if self.min_sdk <= 0:
            raise ValueError("Android minimum SDK must be positive")
        if self.compile_sdk < self.min_sdk:
            raise ValueError("Android compile SDK cannot be older than the minimum SDK")
        if self.target_sdk is not None and self.target_sdk < self.min_sdk:
            raise ValueError("Android target SDK cannot be older than the minimum SDK")
        if self.target_sdk is not None and self.target_sdk > self.compile_sdk:
            raise ValueError("Android target SDK cannot be newer than the compile SDK")

    @property
    def jvm_class(self) -> str:
        return f"{self.app_id.replace('.', '/')}/PyjsAndroid"

    @property
    def android_activity(self) -> str:
        return f"{self.app_id}.PyjsAndroid${self.activity}"

    def android_component(self, class_name: str) -> str:
        return f"{self.app_id}.PyjsAndroid${class_name}"


class AndroidResourceLinker:
    """Link Android resources and compile their generated ``R`` classes."""

    def __init__(self, sdk: AndroidSDK) -> None:
        self.sdk = sdk

    def link(
        self,
        platform: Path,
        manifest: Path,
        package: Path,
        build: Path,
        *,
        min_sdk: int,
        target_sdk: int,
        dependencies: AndroidArtifactClasspath | None = None,
        resources: tuple[Path, ...] = (),
    ) -> Path:
        application_resources = self._compile_application_resources(
            resources,
            build / "application-resources",
        )
        dependency_resources, packages = self._compile_aar_resources(
            dependencies.aars if dependencies is not None else (),
            build / "aar-resources",
        )
        compiled_resources = (*dependency_resources, *application_resources)
        generated = build / "generated-resources"
        arguments: list[str | Path] = [
            self.sdk.build_tool("aapt2"),
            "link",
            "-o",
            package,
            "-I",
            platform,
            "--manifest",
            manifest,
            "--min-sdk-version",
            str(min_sdk),
            "--target-sdk-version",
            str(target_sdk),
            "--version-code",
            "1",
            "--version-name",
            "0.1",
        ]
        if compiled_resources:
            arguments.extend(
                ["--auto-add-overlay", "--non-final-ids", "--java", generated]
            )
            if packages:
                arguments.extend(("--extra-packages", ":".join(packages)))
            for resource_archive in compiled_resources:
                arguments.extend(("-R", resource_archive))
        self._run(*arguments)

        classes = build / "resource-classes"
        sources = sorted(generated.rglob("*.java"))
        if sources:
            classes.mkdir()
            self._run(
                self.sdk.java_home / "bin" / "javac",
                "--release",
                "8",
                "-d",
                classes,
                *sources,
            )
        return classes

    def _compile_application_resources(
        self,
        resources: tuple[Path, ...],
        output: Path,
    ) -> tuple[Path, ...]:
        compiled = []
        for index, directory in enumerate(resources):
            directory = Path(directory)
            if not directory.is_dir():
                raise RuntimeError(
                    f"Android application resource directory not found: {directory}"
                )
            output.mkdir(parents=True, exist_ok=True)
            result = output / f"{index}.zip"
            self._run(
                self.sdk.build_tool("aapt2"),
                "compile",
                "--dir",
                directory,
                "-o",
                result,
            )
            compiled.append(result)
        return tuple(compiled)

    def _compile_aar_resources(
        self,
        archives: tuple[Path, ...],
        output: Path,
    ) -> tuple[tuple[Path, ...], tuple[str, ...]]:
        compiled = []
        packages = []
        for index, archive_path in enumerate(archives):
            with zipfile.ZipFile(archive_path) as archive:
                packages.append(self._aar_package(archive_path, archive))
                members = [
                    name
                    for name in archive.namelist()
                    if name.startswith("res/") and not name.endswith("/")
                ]
                if not members:
                    continue
                resources = output / str(index) / "res"
                for name in members:
                    relative = Path(name).relative_to("res")
                    if ".." in relative.parts or relative.is_absolute():
                        raise RuntimeError(
                            f"unsafe Android AAR resource path {name!r}"
                        )
                    destination = resources / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(name))
            result = output / f"{index}.zip"
            self._run(
                self.sdk.build_tool("aapt2"),
                "compile",
                "--dir",
                resources,
                "-o",
                result,
            )
            compiled.append(result)
        return tuple(compiled), tuple(dict.fromkeys(packages))

    @staticmethod
    def _aar_package(path: Path, archive: zipfile.ZipFile) -> str:
        try:
            manifest = archive.read("AndroidManifest.xml")
            package = ElementTree.fromstring(manifest).get("package")
        except (KeyError, ElementTree.ParseError) as error:
            raise RuntimeError(f"invalid Android manifest in {path}") from error
        if package is None or re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+",
            package,
        ) is None:
            raise RuntimeError(f"invalid Android package in {path}: {package!r}")
        return package

    def _run(self, *command: str | Path) -> None:
        self.sdk.runner.run(command, environment=self.sdk.environment())


class AndroidJVMBuilder:
    """Run the Android SDK's small, deterministic APK packaging pipeline."""

    def __init__(self, sdk: AndroidSDK | None = None) -> None:
        self.sdk = sdk or AndroidSDK()

    def build(
        self,
        application: AndroidJVMApplication,
        output: Path,
        *,
        keystore: Path | None = None,
        dependencies: AndroidArtifactClasspath | None = None,
    ) -> Path:
        source = application.source.read_text()
        self._validate_activity_source(application, source)
        compilation = transpile_jvm(
            source,
            filename=str(application.source),
            module_name=application.module_name,
            class_name=application.jvm_class,
        )
        activity_class = f"{application.jvm_class}${application.activity}"
        if activity_class not in compilation.classes:
            raise RuntimeError(
                f"Android activity {application.android_activity} is not reachable "
                "from main()"
            )
        for component in application.components:
            component_class = f"{application.jvm_class}${component.class_name}"
            if component_class not in compilation.classes:
                raise RuntimeError(
                    f"Android {component.kind} {component.class_name} is not "
                    "reachable from main()"
                )

        platform = self._platform(application.compile_sdk)
        target_sdk = application.target_sdk or application.compile_sdk
        signing_key = keystore or Path.home() / ".android" / "debug.keystore"
        if not signing_key.is_file():
            raise RuntimeError(
                f"Android debug keystore not found at {signing_key}. "
                "Create it with Android Studio or keytool."
            )

        output.mkdir(parents=True, exist_ok=True)
        package = output / f"{application.app_id}-debug.apk"
        with tempfile.TemporaryDirectory(prefix="pyjs-android-") as temporary:
            build = Path(temporary)
            classes = build / "classes"
            compilation.write(classes)

            manifest = build / "AndroidManifest.xml"
            manifest.write_text(self._manifest(application, target_sdk))
            unaligned = build / "unaligned.apk"
            dependency_classes = self._link_resources(
                application,
                platform,
                manifest,
                unaligned,
                build,
                dependencies,
            )

            dex = build / "dex"
            dex.mkdir()
            self._run(
                self.sdk.build_tool("d8"),
                "--lib",
                platform,
                "--min-api",
                str(application.min_sdk),
                "--output",
                dex,
                *sorted(classes.rglob("*.class")),
                *sorted(dependency_classes.rglob("*.class")),
                *(dependencies.jars if dependencies is not None else ()),
            )
            self._append_dex_files(unaligned, dex)

            aligned = build / "aligned.apk"
            self._run(self.sdk.build_tool("zipalign"), "-f", "4", unaligned, aligned)
            self._run(
                self.sdk.build_tool("apksigner"),
                "sign",
                "--ks",
                signing_key,
                "--ks-key-alias",
                "androiddebugkey",
                "--ks-pass",
                "pass:android",
                "--key-pass",
                "pass:android",
                "--out",
                package,
                aligned,
            )
            self._run(
                self.sdk.build_tool("apksigner"),
                "verify",
                "--verbose",
                package,
            )
        return package

    def _link_resources(
        self,
        application: AndroidJVMApplication,
        platform: Path,
        manifest: Path,
        package: Path,
        build: Path,
        dependencies: AndroidArtifactClasspath | None,
    ) -> Path:
        return AndroidResourceLinker(self.sdk).link(
            platform,
            manifest,
            package,
            build,
            min_sdk=application.min_sdk,
            target_sdk=application.target_sdk or application.compile_sdk,
            dependencies=dependencies,
            resources=application.resources,
        )

    def _run(self, *command: str | Path) -> None:
        self.sdk.runner.run(command, environment=self.sdk.environment())

    def _platform(self, api: int) -> Path:
        return self.sdk.platform_jar(api)

    @staticmethod
    def _validate_activity_source(
        application: AndroidJVMApplication,
        source: str,
    ) -> None:
        activity = next(
            (
                node
                for node in ast.parse(source, str(application.source)).body
                if isinstance(node, ast.ClassDef) and node.name == application.activity
            ),
            None,
        )
        if activity is None:
            raise ValueError(
                f"Android activity class {application.activity!r} is not defined"
            )
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__init__"
            for node in activity.body
        ):
            raise ValueError(
                "Android constructs the manifest activity without calling its "
                "Python __init__; initialize activity state in onCreate()"
            )

    @staticmethod
    def _append_dex_files(package: Path, dex_directory: Path) -> None:
        dex_files = sorted(dex_directory.glob("classes*.dex"))
        if not dex_files:
            raise RuntimeError("D8 did not produce any DEX files")
        with zipfile.ZipFile(package, "a") as archive:
            for dex in dex_files:
                archive.write(dex, dex.name, compress_type=zipfile.ZIP_STORED)

    @staticmethod
    def _manifest(application: AndroidJVMApplication, target_sdk: int) -> str:
        app_id = escape(application.app_id, quote=True)
        activity = escape(application.android_activity, quote=True)
        title = escape(application.title, quote=True)
        debuggable = str(application.debuggable).lower()
        components = "\n".join(
            AndroidJVMBuilder._manifest_component(application, component)
            for component in application.components
        )
        if components:
            components = "\n" + components
        return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{app_id}">
    <uses-sdk android:minSdkVersion="{application.min_sdk}"
        android:targetSdkVersion="{target_sdk}" />
    <application android:allowBackup="false" android:debuggable="{debuggable}"
        android:label="{title}"
        android:theme="@android:style/Theme.Material.Light.NoActionBar"
        android:usesCleartextTraffic="false">
        <activity android:name="{activity}" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>{components}
    </application>
</manifest>
"""

    @staticmethod
    def _manifest_component(
        application: AndroidJVMApplication,
        component: AndroidManifestComponent,
    ) -> str:
        name = escape(application.android_component(component.class_name), quote=True)
        exported = str(component.exported).lower()
        permission = (
            f' android:permission="{escape(component.permission, quote=True)}"'
            if component.permission is not None
            else ""
        )
        children = []
        if component.actions:
            actions = "\n".join(
                f'                <action android:name="{escape(action, quote=True)}" />'
                for action in component.actions
            )
            children.append(
                "            <intent-filter>\n"
                + actions
                + "\n            </intent-filter>"
            )
        children.extend(
            "            <meta-data "
            f'android:name="{escape(metadata_name, quote=True)}" '
            f'android:resource="{escape(resource, quote=True)}" />'
            for metadata_name, resource in component.metadata
        )
        if not children:
            return (
                f'        <{component.kind} android:name="{name}" '
                f'android:exported="{exported}"{permission} />'
            )
        return (
            f'        <{component.kind} android:name="{name}" '
            f'android:exported="{exported}"{permission}>\n'
            + "\n".join(children)
            + f"\n        </{component.kind}>"
        )


__all__ = [
    "AndroidJVMApplication",
    "AndroidJVMBuilder",
    "AndroidManifestComponent",
    "AndroidResourceLinker",
]
