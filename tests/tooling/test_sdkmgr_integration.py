import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest
from sdkmgr import SDKError
from sdkmgr.providers import Platform

from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_artifacts import AndroidArtifact, AndroidArtifactResolver
from pyjs.tooling.browser import browser_executable
from pyjs.tooling.llvm import LLVM


def test_browser_discovery_never_installs(monkeypatch):
    manager = Mock()
    manager.find_browser.return_value.executable.return_value = Path("/managed/chrome")
    monkeypatch.setattr("sdkmgr.Manager", Mock(return_value=manager))
    assert browser_executable() == str(Path("/managed/chrome"))
    manager.find_browser.assert_called_once_with()
    manager.ensure_browser.assert_not_called()
    manager.find_browser.return_value = None
    with pytest.raises(RuntimeError, match="sdkmgr browser install"):
        browser_executable()


def test_invalid_browser_override_is_diagnostic(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROME_BIN", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="Configured Chrome executable") as caught:
        browser_executable()
    assert isinstance(caught.value.__cause__, SDKError)


def test_clang_missing_or_invalid_never_installs(monkeypatch):
    manager = Mock()
    manager.find_clang.return_value = None
    monkeypatch.setattr("sdkmgr.Manager", Mock(return_value=manager))
    with pytest.raises(RuntimeError, match="sdkmgr clang install"):
        LLVM().ensure()
    manager.find_clang.side_effect = SDKError("configured compiler is broken")
    with pytest.raises(RuntimeError, match="configured compiler is broken"):
        LLVM(executable="custom-compiler").ensure()
    manager.ensure_clang.assert_not_called()


@pytest.mark.parametrize("system,suffix,script", [("linux", "", ""), ("windows", ".exe", ".bat")])
def test_android_exact_lookup_and_host_suffixes(tmp_path, monkeypatch, system, suffix, script):
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: Platform(system, "x64")))
    for version in ("35.0.0", "35.0.1-rc1", "35.0.1", "ignored"):
        directory = tmp_path / "build-tools" / version
        directory.mkdir(parents=True)
        (directory / f"aapt2{suffix}").touch()
        (directory / f"d8{script}").touch()
    sdk = AndroidSDK(tmp_path, tmp_path / "jdk")
    assert sdk.adb == tmp_path / "platform-tools" / f"adb{suffix}"
    assert sdk.emulator == tmp_path / "emulator" / f"emulator{suffix}"
    assert sdk.build_tool("aapt2") == tmp_path / "build-tools/35.0.1" / f"aapt2{suffix}"
    assert sdk.build_tool("d8") == tmp_path / "build-tools/35.0.1" / f"d8{script}"
    assert not (tmp_path / "cmdline-tools").exists()


def test_artifact_download_cache_and_corruption(tmp_path, monkeypatch):
    payload = b"jar content"
    artifact = AndroidArtifact("org.example", "library", "1.0", "jar", "central",
                               hashlib.sha256(payload).hexdigest())
    fetch = Mock(side_effect=lambda url, path: path.write_bytes(payload))
    monkeypatch.setattr("sdkmgr.artifacts.fetch", fetch)
    messages = []
    resolver = AndroidArtifactResolver(tmp_path, messages.append)
    result = resolver.resolve_artifacts([artifact])
    path, = result.jars
    assert path.read_bytes() == payload
    assert resolver.resolve_artifacts([artifact]) == result
    assert fetch.call_count == 1
    assert fetch.call_args.args[0] == artifact.url
    assert messages == ["Downloading org.example:library:1.0"]
    path.write_bytes(b"damaged")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        resolver.resolve_artifacts([artifact])
    assert fetch.call_count == 1


def test_artifact_checksum_failure_does_not_publish(tmp_path, monkeypatch):
    artifact = AndroidArtifact("org.example", "library", "1.0", "jar", "central", "0" * 64)
    monkeypatch.setattr("sdkmgr.artifacts.fetch", lambda url, path: path.write_bytes(b"wrong"))
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        AndroidArtifactResolver(tmp_path).resolve_artifacts([artifact])
    assert not list(tmp_path.rglob("*.jar"))
