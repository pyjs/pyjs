import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Artifact:
    name: str
    kind: str
    path: Path
    media_type: str

    def json(self) -> dict[str, str]:
        value = asdict(self)
        value["path"] = str(self.path)
        return value


@dataclass
class ArtifactManifest:
    target: str
    artifacts: list[Artifact]
    metadata: dict[str, object] = field(default_factory=dict)
    version: int = 1

    def json(self) -> dict[str, object]:
        return {
            "version": self.version,
            "target": self.target,
            "metadata": self.metadata,
            "artifacts": [artifact.json() for artifact in self.artifacts],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.json(), indent=2) + "\n", encoding="utf-8")
        return path
