import subprocess
from unittest.mock import Mock

import pytest
from sdkmgr import SDKError

from pyjs.javascript.utils import TailwindBuildError, TailwindCSS


@pytest.fixture
def manager(monkeypatch):
    manager = Mock()
    manager.ensure.return_value.executable.return_value = "/managed/tailwindcss"
    monkeypatch.setattr("sdkmgr.Manager", Mock(return_value=manager))
    return manager


def test_tailwind_css_uses_only_the_compiler_candidates(monkeypatch, manager):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=b"compiled css"))
    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", run)

    css = TailwindCSS().get_css({'before:content-["menu"]', "rounded-md"})

    assert css == "compiled css"
    assert run.call_args.args[0] == ["/managed/tailwindcss", "-i", "-"]
    assert run.call_args.kwargs["input"].decode() == (
        '@import "tailwindcss" source(none);\n'
        '@source inline("before:content-[\\"menu\\"] rounded-md");\n'
    )


def test_tailwind_css_builds_a_stylesheet(tmp_path, monkeypatch, manager):
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", run)
    source = tmp_path / "input.css"
    output = tmp_path / "assets" / "output.css"

    result = TailwindCSS().build(source, output, minify=True, cwd=tmp_path)

    assert result == output
    assert output.parent.is_dir()
    assert run.call_args.args[0] == [
        "/managed/tailwindcss", "-i", str(source), "-o", str(output), "--minify",
    ]
    assert run.call_args.kwargs["cwd"] == tmp_path


def test_tailwind_resolves_exact_sdk_version_once(tmp_path, monkeypatch, manager):
    factory = Mock(return_value=manager)
    monkeypatch.setattr("sdkmgr.Manager", factory)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=b"css"))
    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", run)
    tool = TailwindCSS(cache_directory=tmp_path)
    assert tool.get_css({"rounded-md"}) == "css"
    assert tool.get_css({"underline"}) == "css"
    factory.assert_called_once_with(tmp_path, interactive=False)
    manager.ensure.assert_called_once_with("tailwindcss", version=TailwindCSS.VERSION)


def test_tailwind_provisioning_errors_stop_build(monkeypatch, manager):
    manager.ensure.side_effect = SDKError("bad checksum")
    run = Mock()
    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", run)
    with pytest.raises(RuntimeError, match="bad checksum") as caught:
        TailwindCSS().get_css({"rounded-md"})
    assert isinstance(caught.value.__cause__, SDKError)
    run.assert_not_called()


def test_explicit_tailwind_command_is_not_replaced(monkeypatch, manager):
    run = Mock(side_effect=FileNotFoundError)
    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", run)
    with pytest.raises(FileNotFoundError):
        TailwindCSS("custom-tailwind").get_css({"rounded-md"})
    assert run.call_args.args[0][0] == "custom-tailwind"
    manager.ensure.assert_not_called()


def test_tailwind_css_failure_stops_the_build(monkeypatch, manager):
    failure = subprocess.CalledProcessError(
        2, ["/managed/tailwindcss", "-i", "-"], stderr=b"Invalid utility class",
    )
    monkeypatch.setattr("pyjs.javascript.utils.subprocess.run", Mock(side_effect=failure))

    with pytest.raises(
        TailwindBuildError,
        match="Tailwind CSS compilation failed with exit code 2: Invalid utility class",
    ) as caught:
        TailwindCSS().get_css({"invalid"})

    assert caught.value.command == ("/managed/tailwindcss", "-i", "-")
    assert caught.value.exit_code == 2
    assert caught.value.stderr == "Invalid utility class"
    assert caught.value.__cause__ is failure
