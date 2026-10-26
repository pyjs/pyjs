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


@pytest.mark.parametrize("internal", [False, True])
def test_runtime_resources_links_stay_inside_copy(tmp_path, runtime, internal):
    resources = runtime / "resources"
    resources.rename(runtime / "resource-data")
    shared = tmp_path / "shared"
    shared.mkdir()
    try:
        resources.symlink_to("resource-data" if internal else shared, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    output = tmp_path / "app"
    if internal:
        electron.build_application(output, page, runtime=runtime)
        assert (output / "resources/app/renderer/sample.main.html").is_file()
        assert (output / "resource-data/app/main.cjs").is_file()
    else:
        with pytest.raises(ValueError, match="escapes the copied distribution"):
            electron.build_application(output, page, runtime=runtime)
        assert not output.exists()
    assert not (runtime / "resource-data/app").exists()
    assert list(shared.iterdir()) == []
    assert not list(tmp_path.glob("pyjs-electron-*"))


def test_managed_runtime_alias_cannot_contain_output(tmp_path, runtime, monkeypatch):
    alias = tmp_path / "cache-alias"
    try:
        alias.symlink_to(runtime, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    monkeypatch.setattr(electron, "managed_runtime", lambda: alias)
    def render(directory):
        pytest.fail("Unsafe output must be rejected before rendering")
    with pytest.raises(ValueError, match="inside the runtime directory"):
        electron.build_application(runtime / "app", render)
    assert not list(runtime.glob("pyjs-electron-*"))


def test_destination_created_during_render_is_preserved(tmp_path, runtime):
    output = tmp_path / "app"
    inode = []
    def render(directory):
        output.mkdir()
        inode.append(output.stat().st_ino)
        return page(directory)
    with pytest.raises(FileExistsError):
        electron.build_application(output, render, runtime=runtime)
    assert output.stat().st_ino == inode[0]
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("name", ["app", "app.asar"])
def test_existing_runtime_application_is_preserved(tmp_path, runtime, name):
    existing = runtime / "resources" / name
    existing.write_text("original")
    output = tmp_path / "app"
    with pytest.raises(ValueError, match="already contains"):
        electron.build_application(output, page, runtime=runtime)
    assert existing.read_text() == "original"
    assert not output.exists()


@pytest.mark.parametrize("target", ["js", "electron"])
def test_npm_page_loads_as_a_module(tmp_path, runtime, monkeypatch, target):
    from pyjs.tooling.npm import ManagedNpmProject

    module_name = f"npm_sample_{target}"
    (tmp_path / f"{module_name}.py").write_text('''from pyjs import js
from pyjs.tooling.npm import NpmImport, NpmPackage
from pyjs.web.domx import CustomElement, tag
__pyjs_npm_imports__ = (NpmImport(NpmPackage("example", "1.2.3"), "$example"),)
@js
def answer() -> str: ...
answer.source("return $example.answer;")
@js
class NpmSample(CustomElement):
    def __init__(self):
        super().__init__()
        tag(self, "waiting")
    def connectedCallback(self):
        self.setAttribute("data-answer", answer())
def main():
    return NpmSample()
''')
    def copy_vendor(self, imports, destination):
        destination.write_text("export const $example = {answer: 'loaded'};\n")
        return destination
    monkeypatch.setattr(ManagedNpmProject, "copy_vendor", copy_vendor)
    monkeypatch.syspath_prepend(tmp_path)
    monkeypatch.chdir(tmp_path)
    arguments = ["build", module_name, "--target", target]
    renderer = tmp_path
    if target == "electron":
        output = tmp_path / "built"
        arguments += ["-o", str(output), "--electron-runtime", str(runtime)]
        renderer = output / "resources/app/renderer"
    assert main(arguments) == 0
    html = (renderer / f"{module_name}.main.html").read_text()
    assert 'type="module"' in html
    assert "import " in (renderer / f"{module_name}.main.js").read_text()
    assert (renderer / "pyjs-vendor.js").is_file()


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


@pytest.mark.parametrize("source", ["host", "runtime"])
def test_output_cannot_alias_a_source_directory(tmp_path, runtime, source):
    host = tmp_path / "host"
    host.mkdir()
    (host / "main.cjs").write_text("")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(host if source == "host" else runtime, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    def render(directory):
        pytest.fail("Unsafe output must be rejected before rendering")
    with pytest.raises(ValueError, match=f"inside the {source} directory"):
        electron.build_application(alias / "built", render, runtime=runtime, host=host)
    assert not list(host.glob("pyjs-electron-*"))
    assert not list(runtime.glob("pyjs-electron-*"))


def test_dangling_output_symlink_is_preserved(tmp_path, runtime):
    output = tmp_path / "existing-link"
    try:
        output.symlink_to(tmp_path / "missing", target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    with pytest.raises(FileExistsError):
        electron.build_application(output, page, runtime=runtime)
    assert output.is_symlink()
    assert not (tmp_path / "missing").exists()


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


def test_python_host_and_preload_are_compiled_not_copied(tmp_path, runtime, monkeypatch):
    host = tmp_path / "typed_desktop_host"
    host.mkdir()
    (host / "__init__.py").write_text("")
    (host / "main.py").write_text('''from pyjs import js
from pyjs.electron import HostContext
@js
async def main(context: HostContext):
    context.app.setName("Example")
''')
    (host / "preload.py").write_text('''from pyjs import js
from pyjs.electron import expose
@js.dictionary
class Bridge:
    def __init__(self, title: str):
        self.title = title
@js
def main():
    expose("example", Bridge("Example"))
''')
    (host / "unused.txt").write_text("not a runtime dependency")
    monkeypatch.syspath_prepend(tmp_path)
    output = tmp_path / "app"
    try:
        electron.build_application(output, page, runtime=runtime, host=host)
        compiled = output / "resources/app/host"
        assert {p.name for p in compiled.iterdir()} == {
            "main.cjs", "main.cjs.map", "preload.cjs", "preload.cjs.map",
        }
        script = (compiled / "main.cjs").read_text()
        assert "module.exports = {start: __pyjsEntry__.main}" in script
        preload = (compiled / "preload.cjs").read_text()
        assert "module.exports =" not in preload
        assert "require('electron').contextBridge.exposeInMainWorld" in preload
        for name in ("main", "preload"):
            source_map = json.loads((compiled / f"{name}.cjs.map").read_text())
            assert any(source.endswith(f"{name}.py") for source in source_map["sources"])
    finally:
        import sys
        for name in ("typed_desktop_host.main", "typed_desktop_host.preload", "typed_desktop_host"):
            sys.modules.pop(name, None)
