import hashlib
from pathlib import Path


def verify_sha256(path: Path, manifest: Path, name: str | None = None) -> None:
    name = name or path.name
    expected = None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        published_name = (
            parts[1].lstrip("*").removeprefix("./")
            if len(parts) == 2
            else None
        )
        if published_name == name:
            expected = parts[0]
            break
    if expected is None:
        raise RuntimeError(f"No published checksum was found for {name}.")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f"Checksum verification failed for {name}.")
