import json
import os
import re
from pathlib import Path

from pyjs.transpiler import bundle

from .android import AndroidDevice, AndroidSDK
from .command import CommandRunner
from .node import Npm, cache_root

NATIVESCRIPT_VERSION = "9.0.6"
NATIVESCRIPT_TEMPLATE = "@nativescript/template-blank@9.0.0"
TAILWIND_DEPENDENCIES = {
    "@nativescript/tailwind": "4.0.9",
    "tailwindcss": "4.3.3",
}
CORE_IMPORTS = ("Application", "Button", "EventData", "Label", "Page", "StackLayout", "View")


class NativeScriptCLI:
    def __init__(
        self,
        npm: Npm | None = None,
        root: Path | None = None,
        runner: CommandRunner | None = None,
    ):
        self.npm = npm or Npm()
        self.root = root or cache_root() / "tooling" / "nativescript" / NATIVESCRIPT_VERSION
        self.runner = runner or self.npm.runner

    @property
    def executable(self) -> Path:
        if os.name == "nt":
            return self.root / "node_modules" / ".bin" / "ns.cmd"
        return self.root / "node_modules" / ".bin" / "ns"

    def environment(self, android: AndroidSDK | None = None) -> dict[str, str]:
        environment = self.npm.node.environment()
        if android is not None:
            android_environment = android.environment()
            environment.update(android_environment)
            environment["PATH"] = (
                f"{self.npm.node.bin_directory}{os.pathsep}{android_environment['PATH']}"
            )
        return environment

    def ensure(self) -> Path:
        if self.executable.exists():
            return self.executable
        self.npm.install(self.root, f"nativescript@{NATIVESCRIPT_VERSION}")
        return self.executable

    def create(self, project: Path, name: str, app_id: str) -> None:
        self.ensure()
        project.parent.mkdir(parents=True, exist_ok=True)
        self.runner.run(
            [
                self.executable,
                "create",
                name,
                "--path",
                project.parent,
                "--appid",
                app_id,
                "--template",
                NATIVESCRIPT_TEMPLATE,
            ],
            environment=self.environment(),
        )

    def install(self, project: Path, packages: dict[str, str]) -> None:
        dependencies = [f"{name}@{version}" for name, version in packages.items()]
        self.npm.install(project, *dependencies, save=True, exact=True)

    def run_android(
        self,
        project: Path,
        device: AndroidDevice,
        android: AndroidSDK,
    ) -> None:
        self.ensure()
        self.runner.run(
            [
                self.executable,
                "run",
                "android",
                "--device",
                device.identifier,
                "--no-watch",
                "--no-hmr",
                "--justlaunch",
            ],
            cwd=project,
            environment=self.environment(android),
        )


def project_name(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    return "".join(word[:1].upper() + word[1:] for word in words) or "PyJSApp"


class NativeScriptProject:
    def __init__(
        self,
        entry_point: callable,
        *,
        name: str,
        app_id: str,
        cli: NativeScriptCLI | None = None,
        android: AndroidSDK | None = None,
        build_root: Path | None = None,
    ):
        self.entry_point = entry_point
        self.name = project_name(name)
        self.app_id = app_id
        self.cli = cli or NativeScriptCLI()
        self.android = android
        app_directory = re.sub(r"[^A-Za-z0-9._-]", "-", app_id)
        self.project = (
            (build_root or cache_root() / "builds" / "nativescript") / app_directory / self.name
        )

    def javascript(self) -> str:
        source, _ = bundle(self.entry_point, include_main=True, include_css=False)
        imports = ", ".join(CORE_IMPORTS)
        return f"const {{ {imports} }} = require('@nativescript/core');\n\n{source}"

    def prepare(self) -> Path:
        if not (self.project / "package.json").exists():
            self.cli.create(self.project, self.name, self.app_id)
        package = json.loads((self.project / "package.json").read_text(encoding="utf-8"))
        dependencies = package.get("dependencies", {})
        missing = {
            name: version
            for name, version in TAILWIND_DEPENDENCIES.items()
            if dependencies.get(name) != version
        }
        if missing:
            self.cli.install(self.project, missing)
        app = self.project / "app"
        app.mkdir(parents=True, exist_ok=True)
        (app / "app.js").write_text(self.javascript(), encoding="utf-8")
        (app / "app.css").write_text(
            "@import 'tailwindcss';\n",
            encoding="utf-8",
        )
        return self.project

    def run_android(self, avd: str | None = None) -> AndroidDevice:
        project = self.prepare()
        android = self.android or AndroidSDK()
        device = android.ensure_emulator(avd)
        self.cli.run_android(project, device, android)
        return device
