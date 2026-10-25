"""Package a hydrated PyJS page with the stock Electron distribution."""

import json
import os
import platform
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from pyjs.tooling.node import Npm

ELECTRON_VERSION = "45.0.0"

MAIN = r'''const {app, BrowserWindow} = require('electron');
const path = require('node:path');
const renderer = path.join(__dirname, 'renderer', __HTML__);
function createWindow(options = {}) {
  const window = new BrowserWindow({width: 1280, height: 900, ...options,
    webPreferences: {sandbox: true, contextIsolation: true, nodeIntegration: false,
      ...options.webPreferences}});
  window.setMenu(null);
  window.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
  window.webContents.on('will-navigate', event => event.preventDefault());
  return window;
}
app.whenReady().then(async () => {
  __START__
}).catch(error => {console.error(error); app.exit(1);});
app.on('window-all-closed', () => app.quit());
'''


def runtime_layout(system: str) -> tuple[str, str]:
    if system == "Linux":
        return "electron", "resources/app"
    if system == "Windows":
        return "electron.exe", "resources/app"
    if system == "Darwin":
        return "Electron.app/Contents/MacOS/Electron", "Electron.app/Contents/Resources/app"
    raise RuntimeError(f"Electron packaging is not supported on {system}")


def managed_runtime() -> Path:
    """Let Electron's exact npm package provision the host's stock runtime."""
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pyjs/electron"
    name = f"{ELECTRON_VERSION}-{platform.system()}-{platform.machine()}"
    destination = cache / name
    runtime = destination / "node_modules/electron/dist"
    executable, _ = runtime_layout(platform.system())
    if (runtime / executable).is_file():
        return runtime
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-", dir=cache) as temporary:
        staging = Path(temporary) / "package"
        staging.mkdir()
        (staging / "package.json").write_text(json.dumps({
            "private": True, "dependencies": {"electron": ELECTRON_VERSION},
        }), encoding="utf-8")
        npm = Npm()
        npm.sync(staging)
        # Electron 45 exposes install-electron instead of an npm postinstall hook.
        npm.runner.run(
            [npm.node.executable, staging / "node_modules/electron/install.js"],
            environment=npm.node.environment(),
        )
        if not (staging / "node_modules/electron/dist" / executable).is_file():
            raise RuntimeError("Electron installation did not provide the host runtime")
        try:
            staging.rename(destination)
        except OSError:
            # Another build may have installed the same pinned package.
            if not (runtime / executable).is_file():
                raise
    return runtime


def build_application(
    output: Path, render: Callable[[Path], Path], *,
    runtime: Path | None = None, host: Path | None = None,
) -> Path:
    """Publish a new application directory only after the whole build succeeds.

    A custom host's main.cjs exports async start({app, BrowserWindow,
    createWindow, renderer}). It owns preload/service wiring and window creation.
    Its sibling files are copied verbatim; it must be self-contained at runtime.
    """
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to overwrite {output}; choose a new output directory")
    if host is not None:
        host = host.resolve()
        if not (host / "main.cjs").is_file():
            raise ValueError("--electron-host must contain main.cjs")
        if output.is_relative_to(host):
            raise ValueError("Electron output cannot be inside the host directory")
    executable, app_path = runtime_layout(platform.system())
    runtime = runtime.resolve() if runtime is not None else managed_runtime()
    if not (runtime / executable).is_file():
        raise ValueError(f"Electron runtime is missing {executable}: {runtime}")
    if output.is_relative_to(runtime):
        raise ValueError("Electron output cannot be inside the runtime directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pyjs-electron-", dir=output.parent) as temporary:
        staging = Path(temporary)
        renderer = staging / "renderer"
        renderer.mkdir()
        html = render(renderer)
        if not html.is_file() or html.parent != renderer or html.suffix != ".html":
            raise RuntimeError("Electron builds require a generated HTML page")
        application = staging / "application"
        # Independent files: modifying the packaged app must never corrupt the cache.
        shutil.copytree(runtime, application, symlinks=True)
        app = application / app_path
        if app.exists():
            raise ValueError("Electron runtime already contains resources/app")
        app.mkdir(parents=True)
        renderer.rename(app / "renderer")
        start = "const window = createWindow(); await window.loadFile(renderer);"
        if host is not None:
            shutil.copytree(host, app / "host")
            start = "await require('./host/main.cjs').start({app, BrowserWindow, createWindow, renderer});"
        (app / "main.cjs").write_text(
            MAIN.replace("__HTML__", json.dumps(html.name)).replace("__START__", start), encoding="utf-8",
        )
        (app / "package.json").write_text(json.dumps({
            "name": "pyjs-desktop-app", "version": "0.1.0", "main": "main.cjs", "private": True,
        }) + "\n", encoding="utf-8")
        application.rename(output)
    return output / executable
