import hashlib
import json
import zipfile

import pytest

from pyjs.tooling.android_artifacts import (
    AndroidArtifactResolver,
    locked_android_artifacts,
)


def cached_artifact(cache, group, name, version, filename, digest, content):
    directory = cache / "artifacts" / group / name / version
    directory.mkdir(parents=True)
    path = directory / filename
    path.write_bytes(content)
    (directory / f"{filename}.sha256").write_text(digest + "\n")
    return path


@pytest.mark.parametrize("explicit_artifacts", [False, True])
def test_resolves_locked_jar_and_aar_classpath(tmp_path, explicit_artifacts):
    jar = b"plain classes"
    archive = tmp_path / "library.aar"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("classes.jar", b"aar classes")
        output.writestr("libs/embedded.jar", b"embedded classes")
        output.writestr("res/values/values.xml", b"<resources/>")
    aar = archive.read_bytes()
    jar_digest = hashlib.sha256(jar).hexdigest()
    aar_digest = hashlib.sha256(aar).hexdigest()
    lock = tmp_path / "artifacts.json"
    lock.write_text(
        json.dumps(
            {
                "version": 1,
                "artifacts": [
                    {
                        "group": "sample",
                        "name": "plain",
                        "version": "1",
                        "extension": "jar",
                        "repository": "central",
                        "sha256": jar_digest,
                    },
                    {
                        "group": "sample",
                        "name": "views",
                        "version": "2",
                        "extension": "aar",
                        "repository": "google",
                        "sha256": aar_digest,
                    },
                ],
            }
        )
    )
    cache = tmp_path / "cache"
    cached_artifact(
        cache,
        "sample",
        "plain",
        "1",
        "plain-1.jar",
        jar_digest,
        jar,
    )
    aar_path = cached_artifact(
        cache,
        "sample",
        "views",
        "2",
        "views-2.aar",
        aar_digest,
        aar,
    )

    resolver = AndroidArtifactResolver(cache)
    if explicit_artifacts:
        result = resolver.resolve_artifacts(iter(locked_android_artifacts(lock)))
    else:
        result = resolver.resolve(lock)

    assert [path.read_bytes() for path in result.jars] == [
        jar, b"aar classes", b"embedded classes",
    ]
    assert result.aars == (aar_path,)
