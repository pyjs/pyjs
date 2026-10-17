import hashlib
import subprocess
from unittest.mock import Mock

import pytest

from pyjs.javascript.utils import TailwindBuildError, TailwindCSS


def test_tailwind_css_uses_only_the_compiler_candidates(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=b"compiled css"))
    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", run)

    css = TailwindCSS().get_css({'before:content-["menu"]', "rounded-md"})

    assert css == "compiled css"
    assert run.call_args.args[0] == ["tailwindcss", "-i", "-"]
    assert run.call_args.kwargs["input"].decode() == (
        '@import "tailwindcss" source(none);\n'
        '@source inline("before:content-[\\"menu\\"] rounded-md");\n'
    )


def test_tailwind_css_builds_a_stylesheet(tmp_path, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", run)
    source = tmp_path / "input.css"
    output = tmp_path / "assets" / "output.css"

    result = TailwindCSS().build(source, output, minify=True, cwd=tmp_path)

    assert result == output
    assert output.parent.is_dir()
    assert run.call_args.args[0] == [
        "tailwindcss",
        "-i",
        str(source),
        "-o",
        str(output),
        "--minify",
    ]
    assert run.call_args.kwargs["cwd"] == tmp_path


def test_tailwind_css_downloads_standalone_cli_when_command_is_missing(tmp_path, monkeypatch):
    completed = subprocess.CompletedProcess([], 0, stdout=b"compiled css")
    run = Mock(side_effect=(FileNotFoundError, completed))

    def download(url, destination):
        if url.endswith("sha256sums.txt"):
            checksum = hashlib.sha256(b"tailwind").hexdigest()
            destination.write_text(
                f"{checksum}  ./tailwindcss-test\n",
                encoding="utf-8",
            )
        else:
            destination.write_bytes(b"tailwind")

    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", run)
    monkeypatch.setattr("pyjs.javascript.utils.urllib.request.urlretrieve", download)
    monkeypatch.setattr(TailwindCSS, "platform_asset", staticmethod(lambda: "tailwindcss-test"))

    css = TailwindCSS(cache_directory=tmp_path).get_css({"rounded-md"})

    executable = tmp_path / TailwindCSS.VERSION / "tailwindcss-test"
    assert css == "compiled css"
    assert executable.read_bytes() == b"tailwind"
    assert (executable.parent / "sha256sums.txt").is_file()
    assert run.call_args_list[1].args[0][0] == str(executable)


def test_tailwind_css_rejects_a_checksum_mismatch(tmp_path, monkeypatch):
    def download(url, destination):
        if url.endswith("sha256sums.txt"):
            destination.write_text(
                f"{'0' * 64}  tailwindcss-test\n",
                encoding="utf-8",
            )
        else:
            destination.write_bytes(b"tailwind")

    monkeypatch.setattr("pyjs.javascript.utils.urllib.request.urlretrieve", download)
    monkeypatch.setattr(
        TailwindCSS,
        "platform_asset",
        staticmethod(lambda: "tailwindcss-test"),
    )

    with pytest.raises(
        RuntimeError,
        match="Checksum verification failed for tailwindcss-test",
    ):
        TailwindCSS(cache_directory=tmp_path).install()

    version_directory = tmp_path / TailwindCSS.VERSION
    assert not (version_directory / "tailwindcss-test").exists()
    assert not (version_directory / "tailwindcss-test.download").exists()
    assert not (version_directory / "sha256sums.download").exists()


def test_tailwind_css_reuses_a_verified_cached_executable(tmp_path, monkeypatch):
    version_directory = tmp_path / TailwindCSS.VERSION
    version_directory.mkdir()
    executable = version_directory / "tailwindcss-test"
    executable.write_bytes(b"tailwind")
    checksum = hashlib.sha256(b"tailwind").hexdigest()
    (version_directory / "sha256sums.txt").write_text(
        f"{checksum}  tailwindcss-test\n",
        encoding="utf-8",
    )
    download = Mock(side_effect=AssertionError("cache should not download"))
    monkeypatch.setattr("pyjs.javascript.utils.urllib.request.urlretrieve", download)
    monkeypatch.setattr(
        TailwindCSS,
        "platform_asset",
        staticmethod(lambda: "tailwindcss-test"),
    )

    assert TailwindCSS(cache_directory=tmp_path).install() == executable
    download.assert_not_called()


def test_tailwind_css_interrupted_download_keeps_an_existing_binary(
    tmp_path,
    monkeypatch,
):
    version_directory = tmp_path / TailwindCSS.VERSION
    version_directory.mkdir()
    executable = version_directory / "tailwindcss-test"
    executable.write_bytes(b"existing")

    def interrupt(url, destination):
        destination.write_bytes(b"partial checksum")
        raise OSError("interrupted")

    monkeypatch.setattr(
        "pyjs.javascript.utils.urllib.request.urlretrieve",
        interrupt,
    )
    monkeypatch.setattr(
        TailwindCSS,
        "platform_asset",
        staticmethod(lambda: "tailwindcss-test"),
    )

    with pytest.raises(OSError, match="interrupted"):
        TailwindCSS(cache_directory=tmp_path).install()

    assert executable.read_bytes() == b"existing"
    assert not (version_directory / "sha256sums.download").exists()


def test_tailwind_css_failure_stops_the_build(monkeypatch):
    failure = subprocess.CalledProcessError(
        2,
        ["tailwindcss", "-i", "-"],
        stderr=b"Invalid utility class",
    )
    monkeypatch.setattr(
        "pyjs.javascript.utils.subprocess.run",
        Mock(side_effect=failure),
    )

    with pytest.raises(
        TailwindBuildError,
        match="Tailwind CSS compilation failed with exit code 2: "
        "Invalid utility class",
    ) as caught:
        TailwindCSS().get_css({"invalid"})

    assert caught.value.command == ("tailwindcss", "-i", "-")
    assert caught.value.exit_code == 2
    assert caught.value.stderr == "Invalid utility class"
    assert caught.value.__cause__ is failure


def test_tailwind_css_selects_the_current_platform_asset(monkeypatch):
    monkeypatch.setattr("pyjs.javascript.utils.platform.system", lambda: "Linux")
    monkeypatch.setattr("pyjs.javascript.utils.platform.machine", lambda: "aarch64")
    monkeypatch.setattr("pyjs.javascript.utils.platform.libc_ver", lambda: ("musl", "1.2"))
    assert TailwindCSS.platform_asset() == "tailwindcss-linux-arm64-musl"

    monkeypatch.setattr("pyjs.javascript.utils.platform.system", lambda: "Darwin")
    monkeypatch.setattr("pyjs.javascript.utils.platform.machine", lambda: "arm64")
    assert TailwindCSS.platform_asset() == "tailwindcss-macos-arm64"

    monkeypatch.setattr("pyjs.javascript.utils.platform.system", lambda: "Windows")
    assert TailwindCSS.platform_asset() == "tailwindcss-windows-x64.exe"
