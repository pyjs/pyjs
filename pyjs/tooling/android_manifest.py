"""Android's manifest merger, with a checksum-locked host-only classpath."""

import os
import zipfile
from pathlib import Path

from .android_artifacts import AndroidArtifactResolver
from .command import CommandRunner

MANIFEST_MERGER_LOCK = Path(__file__).with_name("android_manifest_runtime.json")


def merge_android_manifests(
    main: Path,
    output: Path,
    *,
    aars: tuple[Path, ...] = (),
    overlays: tuple[Path, ...] = (),
    java_home: Path,
    cache: Path,
    runner: CommandRunner | None = None,
) -> Path:
    """Merge library components, metadata and permissions before resource linking.

    Android's own conflict, placeholder and minimum-SDK checks remain enabled.
    Overlays have higher priority than the generated application manifest; use
    them for explicit ``tools:`` directives rather than silently dropping a
    library's declarations. The tool's JARs never become application dependencies.
    With no library manifests or overlays, no tool is resolved or launched.
    """
    libraries = []
    for index, path in enumerate(dict.fromkeys(aars)):
        with zipfile.ZipFile(path) as archive:
            try:
                data = archive.read("AndroidManifest.xml")
            except KeyError as error:
                raise RuntimeError(f"Android AAR has no manifest: {path}") from error
        directory = output.parent / "library-manifests" / str(index)
        directory.mkdir(parents=True, exist_ok=True)
        manifest = directory / "AndroidManifest.xml"
        manifest.write_bytes(data)
        libraries.append(manifest)
    if not libraries and not overlays:
        return main
    for path in overlays:
        if not path.is_file():
            raise FileNotFoundError(f"Android manifest overlay not found: {path}")
    for path in (*libraries, *overlays):
        if os.pathsep in str(path.resolve()):
            raise ValueError(f"Android manifest path contains the list separator: {path}")
    classpath = AndroidArtifactResolver(cache).resolve(MANIFEST_MERGER_LOCK)
    java = java_home / "bin" / ("java.exe" if os.name == "nt" else "java")
    command = [java, "-Xmx256m", "-cp", os.pathsep.join(map(str, classpath.jars)),
               "com.android.manifmerger.Merger", "--main", main.resolve(),
               "--out", output.resolve(), "--remove-tools-declarations",
               # Non-Gradle applications specify SDK levels in their manifest.
               # This permits that source, not incompatible library SDK levels.
               "--lenientUsesSdkInManifestHandling", "true"]
    if libraries:
        command += ["--libs", os.pathsep.join(str(path.resolve()) for path in libraries)]
    if overlays:
        command += ["--overlays", os.pathsep.join(str(path.resolve()) for path in overlays)]
    result = (runner or CommandRunner()).run(command, capture_output=True, check=False, timeout=60)
    if result.returncode != 0:
        raise RuntimeError("Android manifest merge failed:\n" + result.stdout + result.stderr)
    if not output.is_file():
        raise RuntimeError("Android manifest merger did not produce an output file")
    return output
