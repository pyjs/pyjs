import hashlib
import json
import zipfile

import httpx
import pytest
import sdkmgr.artifacts

from pyjs.tooling.android_artifacts import (
    AndroidArtifact,
    AndroidArtifactResolver,
    locked_android_artifacts,
)


def cached_artifact(cache, filename, digest, content):
    directory = cache / "artifacts" / digest
    directory.mkdir(parents=True)
    path = directory / filename
    path.write_bytes(content)
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
        "plain-1.jar",
        jar_digest,
        jar,
    )
    aar_path = cached_artifact(
        cache,
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


@pytest.mark.parametrize("alternate", ["valid", "missing", "corrupt", "mirror", "mirror-corrupt"])
def test_central_missing_artifact_uses_verified_alternates(tmp_path, monkeypatch, alternate):
    content = b"locked artifact"
    artifact = AndroidArtifact("example", "runtime", "1", "jar", "central",
                               hashlib.sha256(content).hexdigest())
    urls = []

    def download(request):
        urls.append(str(request.url))
        if (len(urls) == 1 or alternate == "missing"
                or len(urls) == 2 and alternate.startswith("mirror")):
            return httpx.Response(404)
        return httpx.Response(200, content=content if alternate in {"valid", "mirror"} else b"wrong content")

    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **options:
                        client(transport=httpx.MockTransport(download), **options))
    resolver = AndroidArtifactResolver(tmp_path)
    if alternate in {"valid", "mirror"}:
        path = resolver.resolve_artifacts([artifact]).jars[0]
        assert path.read_bytes() == content
        assert resolver.resolve_artifacts([artifact]).jars == (path,)
    else:
        with pytest.raises(RuntimeError, match="Could not download|SHA-256 mismatch"):
            resolver.resolve_artifacts([artifact])
        assert sdkmgr.ArtifactCache(tmp_path).find(
            sdkmgr.Artifact(artifact.url, artifact.sha256, artifact.filename)) is None
    expected = [artifact.url, "https://repo1.maven.org/maven2/example/runtime/1/runtime-1.jar"]
    if alternate in {"missing", "mirror", "mirror-corrupt"}:
        expected.append("https://maven-central.storage-download.googleapis.com/maven2/example/runtime/1/runtime-1.jar")
    assert urls == expected


@pytest.mark.parametrize("repository, failure", [
    ("google", 404), ("central", 401), ("central", 403), ("central", 429),
    ("central", "corrupt"), ("central", "disk"), ("central", "opaque"),
])
@pytest.mark.parametrize("missing_primary", [False, True])
def test_alternate_does_not_mask_other_download_or_storage_errors(
    tmp_path, monkeypatch, repository, failure, missing_primary,
):
    artifact = AndroidArtifact("example", "runtime", "1", "jar", repository,
                               hashlib.sha256(b"locked artifact").hexdigest())
    urls = []

    def download(url, destination):
        urls.append(url)
        if missing_primary and repository == "central" and len(urls) == 1:
            response = httpx.Response(404, request=httpx.Request("GET", url))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise sdkmgr.SDKError("Could not download artifact") from error
        if failure == "corrupt":
            destination.write_bytes(b"wrong content")
        elif failure == "disk":
            raise OSError("Disk full")
        elif failure == "opaque":
            raise sdkmgr.SDKError("404 text without an HTTP response")
        else:
            response = httpx.Response(failure, request=httpx.Request("GET", url))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise sdkmgr.SDKError("Could not download artifact") from error

    monkeypatch.setattr(sdkmgr.artifacts, "fetch", download)
    with pytest.raises(RuntimeError):
        AndroidArtifactResolver(tmp_path).resolve_artifacts([artifact])
    expected = [artifact.url]
    if missing_primary and repository == "central":
        expected.append("https://repo1.maven.org/maven2/example/runtime/1/runtime-1.jar")
    assert urls == expected
    assert sdkmgr.ArtifactCache(tmp_path).find(
        sdkmgr.Artifact(artifact.url, artifact.sha256, artifact.filename)) is None
