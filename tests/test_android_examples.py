import builtins
import importlib
import runpy
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("example", ["calculator", "notes"])
def test_android_flag_launches_without_web_server(monkeypatch, example):
    package = "pyjs_examples." + example
    build = importlib.import_module(package + ".android_build")
    launch = Mock()
    monkeypatch.setattr(build, "run_android", launch)
    monkeypatch.setattr("sys.argv", [package, "--android"])
    original_import = builtins.__import__

    def import_without_web_server(name, *args, **kwargs):
        assert name != "pyjs.server.dev", "Android must not start the web server"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_web_server)
    runpy.run_module(package, run_name="__main__")
    launch.assert_called_once_with()


@pytest.mark.parametrize("example", ["calculator", "notes"])
def test_examples_reject_the_retired_android_flag(monkeypatch, capsys, example):
    package = "pyjs_examples." + example
    monkeypatch.setattr("sys.argv", [package, "--android-jvm"])
    with pytest.raises(SystemExit) as error:
        runpy.run_module(package, run_name="__main__")
    assert error.value.code == 2
    assert "unrecognized arguments: --android-jvm" in capsys.readouterr().err
