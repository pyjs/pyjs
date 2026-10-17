import json

from pyjs.testing.artifacts import Artifact, ArtifactManifest


def test_artifact_manifest_writes_portable_artifact_metadata(tmp_path):
    screenshot = tmp_path / "screen.png"
    manifest = ArtifactManifest(
        target="android",
        metadata={"device": "emulator-5554"},
        artifacts=[Artifact("screenshot", "image", screenshot, "image/png")],
    )

    path = manifest.write(tmp_path / "manifest.json")

    assert json.loads(path.read_text()) == {
        "version": 1,
        "target": "android",
        "metadata": {"device": "emulator-5554"},
        "artifacts": [
            {
                "name": "screenshot",
                "kind": "image",
                "path": str(screenshot),
                "media_type": "image/png",
            }
        ],
    }
