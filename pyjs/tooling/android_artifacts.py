"""Resolve checksum-locked Android JAR and AAR artifacts."""

import json
import re
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

CENTRAL = "https://repo.maven.apache.org/maven2"
GOOGLE = "https://dl.google.com/dl/android/maven2"


@dataclass(frozen=True)
class AndroidArtifact:
    group: str
    name: str
    version: str
    extension: str
    repository: str
    sha256: str
    robolectric_sdk: int | None = None

    def __post_init__(self) -> None:
        if self.repository not in {"central", "google"}:
            raise ValueError(
                f"unsupported Android artifact repository {self.repository!r}"
            )
        if self.extension not in {"aar", "jar"}:
            raise ValueError(
                f"unsupported Android artifact extension {self.extension!r}"
            )

    @property
    def filename(self) -> str:
        return f"{self.name}-{self.version}.{self.extension}"

    @property
    def url(self) -> str:
        repository = GOOGLE if self.repository == "google" else CENTRAL
        group = self.group.replace(".", "/")
        return f"{repository}/{group}/{self.name}/{self.version}/{self.filename}"


@dataclass(frozen=True)
class AndroidArtifactClasspath:
    jars: tuple[Path, ...]
    aars: tuple[Path, ...]

    @classmethod
    def merge(
        cls,
        *values: AndroidArtifactClasspath,
    ) -> AndroidArtifactClasspath:
        return cls(
            tuple(dict.fromkeys(path for value in values for path in value.jars)),
            tuple(dict.fromkeys(path for value in values for path in value.aars)),
        )


def locked_android_artifacts(lock: Path) -> tuple[AndroidArtifact, ...]:
    payload = json.loads(Path(lock).read_text())
    if payload.get("version") != 1:
        raise RuntimeError("unsupported Android artifact lock version")
    artifacts = tuple(AndroidArtifact(**value) for value in payload["artifacts"])
    if any(re.fullmatch(r"[0-9a-f]{64}", value.sha256) is None for value in artifacts):
        raise ValueError("Android artifact SHA-256 must be lowercase hexadecimal")
    return artifacts


class AndroidArtifactResolver:
    """Download and extract an explicit checksum-locked artifact set."""

    def __init__(
        self,
        cache: Path,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.cache = Path(cache)
        self.progress = progress or (lambda _message: None)

    def resolve(self, lock: Path) -> AndroidArtifactClasspath:
        return self.resolve_artifacts(locked_android_artifacts(lock))

    def resolve_artifacts(
        self,
        artifacts: Iterable[AndroidArtifact],
    ) -> AndroidArtifactClasspath:
        jars = []
        aars = []
        for artifact in artifacts:
            path = self._artifact(artifact)
            if artifact.extension == "aar":
                aars.append(path)
                jars.extend(self._extract_aar(artifact, path))
            elif artifact.extension == "jar":
                jars.append(path)
        return AndroidArtifactClasspath(tuple(jars), tuple(aars))

    def _artifact(self, artifact: AndroidArtifact) -> Path:
        from sdkmgr import Artifact, ArtifactCache, SDKError

        try:
            cache = ArtifactCache(self.cache)
            selected = Artifact(artifact.url, artifact.sha256, artifact.filename)
            if existing := cache.find(selected):
                return existing
            self.progress(f"Downloading {artifact.group}:{artifact.name}:{artifact.version}")
            return cache.ensure(selected)
        except SDKError as error:
            raise RuntimeError(str(error)) from error

    def _extract_aar(
        self,
        artifact: AndroidArtifact,
        path: Path,
    ) -> tuple[Path, ...]:
        output = self.cache / "aars" / artifact.sha256
        marker = output / ".complete"
        if not marker.is_file():
            output.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path) as archive:
                names = [
                    name
                    for name in archive.namelist()
                    if name == "classes.jar"
                    or name.startswith("libs/") and name.endswith(".jar")
                ]
                for name in names:
                    if ".." in Path(name).parts or Path(name).is_absolute():
                        raise RuntimeError(
                            f"unsafe Android AAR member path {name!r}"
                        )
                    destination = output / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(name))
            marker.write_text(artifact.sha256 + "\n")
        return tuple(sorted(output.rglob("*.jar")))


__all__ = [
    "AndroidArtifact",
    "AndroidArtifactClasspath",
    "AndroidArtifactResolver",
    "locked_android_artifacts",
]
