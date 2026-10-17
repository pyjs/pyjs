"""Pinned external API artifacts used by direct-JVM Android applications."""

from collections.abc import Callable
from pathlib import Path

from pyjs.tooling.android_artifacts import (
    AndroidArtifactClasspath,
    AndroidArtifactResolver,
    locked_android_artifacts,
)

ANDROIDX_RUNTIME_LOCK = Path(__file__).with_name("androidx_runtime.json")


def resolve_androidx_runtime(
    cache: Path,
    progress: Callable[[str], None] | None = None,
) -> AndroidArtifactClasspath:
    """Resolve the pinned AndroidX application runtime and API classpath."""
    return AndroidArtifactResolver(cache, progress).resolve(
        ANDROIDX_RUNTIME_LOCK
    )


def resolve_android_dependency_locks(
    cache: Path,
    locks: tuple[tuple[str, Path], ...],
    progress: Callable[[str], None] | None = None,
) -> AndroidArtifactClasspath:
    """Resolve and merge named, checksum-locked application dependencies."""
    coordinates = {}
    for set_name, lock in locks:
        for artifact in locked_android_artifacts(lock):
            key = (artifact.group, artifact.name)
            identity = (
                artifact.version,
                artifact.extension,
                artifact.repository,
                artifact.sha256,
            )
            previous = coordinates.get(key)
            if previous is not None and previous[1] != identity:
                group, name = key
                raise RuntimeError(
                    f"Android dependency sets {previous[0]!r} and {set_name!r} "
                    f"select conflicting {group}:{name} artifacts"
                )
            coordinates[key] = (set_name, identity)
    resolver = AndroidArtifactResolver(cache, progress)
    resolved = []
    for name, lock in locks:
        if progress is not None:
            progress(f"Resolving Android dependency set {name}")
        resolved.append(resolver.resolve(lock))
    return AndroidArtifactClasspath.merge(*resolved)


__all__ = [
    "ANDROIDX_RUNTIME_LOCK",
    "resolve_android_dependency_locks",
    "resolve_androidx_runtime",
]
