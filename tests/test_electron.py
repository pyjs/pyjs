"""Desktop packaging contracts, without downloading an Electron runtime."""
import json

import pytest

from pyjs.cli import main
from pyjs.tooling import electron


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(electron, "runtime_layout", lambda system: ("electron", "resources/app"))
    directory = tmp_path / "runtime"
    directory.mkdir()
    (directory / "electron").write_text("runtime")
    (directory / "resources").mkdir()
    (directory / "resources/default_app.asar").write_text("default")
    return directory


def page(directory):
    destination = directory / "sample.main.html"
    destination.write_text("<p>Example</p>")
    return destination


def test_real_cli_preserves_python_source_maps_and_host(tmp_path, runtime, monkeypatch):
    module = tmp_path / "desktop_sample.py"
    module.write_text('''from pyjs import js
from pyjs.web.domx import CustomElement, tag
@js
class DesktopSample(CustomElement):
    def __init__(self):
        super().__init__()
        tag(self, "Hello")
    def connectedCallback(self):
        self.setAttribute("data-ready", "yes")
def main():
    return DesktopSample()
''')
    monkeypatch.syspath_prepend(tmp_path)
    monkeypatch.chdir(tmp_path)
    host = tmp_path / "host"
    host.mkdir()
    (host / "main.cjs").write_text("exports.start = async context => {};\n")
    (host / "preload.cjs").write_text("// preload\n")
    output = tmp_path / "built"
    assert main(["build", "desktop_sample", "--target", "electron", "-o", str(output),
                 "--electron-runtime", str(runtime), "--electron-host", str(host)]) == 0
    app = output / "resources/app"
    assert 'require(\'./host/main.cjs\')' in (app / "main.cjs").read_text()
    assert (app / "host/preload.cjs").read_text() == "// preload\n"
    renderer = app / "renderer"
    source_map = json.loads((renderer / "desktop_sample.main.js.map").read_text())
    assert any("desktop_sample.py" in source for source in source_map["sources"])
    assert any('return DesktopSample()' in source for source in source_map["sourcesContent"])
    assert "sourceMappingURL=desktop_sample.main.js.map" in (renderer / "desktop_sample.main.js").read_text()
    assert "Hello" in (renderer / "desktop_sample.main.html").read_text()
    assert not list(tmp_path.glob("*.main.*"))
    (output / "electron").write_text("changed")
    assert (runtime / "electron").read_text() == "runtime"


def test_failure_does_not_publish_partial_output(tmp_path, runtime):
    def fail(directory):
        (directory / "partial").write_text("partial")
        raise RuntimeError("compiler failed")
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="compiler failed"):
        electron.build_application(output, fail, runtime=runtime)
    assert not output.exists()
    assert not list(tmp_path.glob("pyjs-electron-*"))


def test_existing_output_and_recursive_host_rejected(tmp_path, runtime):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "user-data").write_text("keep")
    with pytest.raises(FileExistsError):
        electron.build_application(output, page, runtime=runtime)
    assert (output / "user-data").read_text() == "keep"
    (output / "main.cjs").write_text("")
    with pytest.raises(ValueError, match="inside the host"):
        electron.build_application(output / "child", page, runtime=runtime, host=output)


def test_default_host_keeps_renderer_sandboxed(tmp_path, runtime):
    output = tmp_path / "app"
    electron.build_application(output, page, runtime=runtime)
    host = (output / "resources/app/main.cjs").read_text()
    assert "sandbox: true, contextIsolation: true, nodeIntegration: false" in host
    assert "await window.loadFile(renderer)" in host
    assert "action: 'deny'" in host


@pytest.mark.parametrize("system,executable,app", [
    ("Linux", "electron", "resources/app"),
    ("Windows", "electron.exe", "resources/app"),
    ("Darwin", "Electron.app/Contents/MacOS/Electron", "Electron.app/Contents/Resources/app"),
])
def test_platform_layout(system, executable, app):
    assert electron.runtime_layout(system) == (executable, app)


@pytest.mark.parametrize("arguments", [
    ["--target", "js", "--electron-host", "host"],
    ["--target", "electron"],
    ["--target", "electron", "-o", "app", "--only-js"],
    ["--target", "electron", "-o", "app", "--include-main"],
])
def test_invalid_cli_combinations_rejected(arguments):
    with pytest.raises(SystemExit) as error:
        main(["build", "missing_module", *arguments])
    assert error.value.code == 2


def test_managed_runtime_uses_exact_package_and_reuses_install(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(electron.platform, "system", lambda: "Linux")
    monkeypatch.setattr(electron.platform, "machine", lambda: "test-architecture")
    installed = []
    class Installer:
        def __init__(self):
            self.node = self
            self.runner = self
            self.executable = "node"
        def environment(self):
            return {}
        def run(self, command, environment):
            assert str(command[1]).endswith("node_modules/electron/install.js")
            runtime = command[1].parent / "dist"
            runtime.mkdir(parents=True)
            (runtime / "electron").write_text("binary")
        def sync(self, directory):
            installed.append(json.loads((directory / "package.json").read_text()))
    monkeypatch.setattr(electron, "Npm", Installer)
    runtime = electron.managed_runtime()
    assert (runtime / "electron").read_text() == "binary"
    assert electron.managed_runtime() == runtime
    assert installed == [{"private": True, "dependencies": {"electron": electron.ELECTRON_VERSION}}]


def test_missing_npm_runtime_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(electron.platform, "system", lambda: "Linux")
    class Installer:
        def __init__(self):
            self.node = self
            self.runner = self
            self.executable = "node"
        def environment(self):
            return {}
        def run(self, command, environment):
            pass
        def sync(self, directory):
            pass
    monkeypatch.setattr(electron, "Npm", Installer)
    with pytest.raises(RuntimeError, match="host runtime"):
        electron.managed_runtime()
    assert list((tmp_path / "pyjs/electron").iterdir()) == []
