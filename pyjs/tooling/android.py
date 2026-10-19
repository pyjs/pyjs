import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .command import CommandRunner


@dataclass(frozen=True)
class AndroidDevice:
    identifier: str
    state: str


class AndroidSDK:
    def __init__(
        self,
        root: Path | None = None,
        java_home: Path | None = None,
        runner: CommandRunner | None = None,
    ):
        self.root = root or self.find_root()
        self.java_home = java_home or self.find_java_home()
        self.runner = runner or CommandRunner()

    @staticmethod
    def find_root() -> Path:
        from sdkmgr import Manager, SDKError

        try:
            sdk = Manager(interactive=False).inspect_android()
            if sdk is not None and sdk.executable("adb").is_file():
                return sdk.home
        except SDKError as error:
            raise RuntimeError(str(error)) from error
        raise RuntimeError(
            "Android SDK not found. Install packages with sdkmgr android install "
            "after accepting their licenses, or set ANDROID_HOME to an existing SDK."
        )

    @staticmethod
    def find_java_home() -> Path:
        from sdkmgr import Manager, SDKError

        try:
            installation = Manager(interactive=False).find("java", version="21")
        except SDKError as error:
            raise RuntimeError(str(error)) from error
        if installation is not None:
            return installation.home
        raise RuntimeError(
            "JDK 21 not found. Run sdkmgr install java@21, or set JAVA_HOME "
            "to an existing JDK 21."
        )

    @property
    def adb(self) -> Path:
        return self._installation().executable("adb")

    @property
    def emulator(self) -> Path:
        return self._installation().executable("emulator")

    def _installation(self):
        from sdkmgr import AndroidInstallation, Manager, SDKError

        try:
            manager = Manager(interactive=False)
            return manager.inspect_android(sdk_root=self.root) or AndroidInstallation(
                self.root, None, manager.platform,
            )
        except SDKError as error:
            raise RuntimeError(str(error)) from error

    @property
    def avdmanager(self) -> Path:
        name = "avdmanager.bat" if os.name == "nt" else "avdmanager"
        return self.root / "cmdline-tools" / "latest" / "bin" / name

    @property
    def sdkmanager(self) -> Path:
        name = "sdkmanager.bat" if os.name == "nt" else "sdkmanager"
        return self.root / "cmdline-tools" / "latest" / "bin" / name

    def build_tool(self, name: str) -> Path:
        from sdkmgr import SDKError

        installation = self._installation()
        candidates = []
        for directory in (self.root / "build-tools").glob("*"):
            if not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\d+)?", directory.name):
                continue
            try:
                candidates.append(installation.build_tool(name, version=directory.name))
            except SDKError:
                continue
        if not candidates:
            raise RuntimeError(f"Android SDK build tool {name!r} is not installed.")
        return max(candidates, key=self._build_tools_version)

    def platform_jar(self, api: int) -> Path:
        from sdkmgr import SDKError

        try:
            return self._installation().platform_jar(api)
        except SDKError as error:
            raise RuntimeError(str(error)) from error

    @staticmethod
    def _build_tools_version(
        path: Path,
    ) -> tuple[tuple[int, ...], int, tuple[int, ...]]:
        version = path.parent.name
        numbers = tuple(int(value) for value in re.findall(r"\d+", version))
        return numbers[:3], int("-" not in version), numbers[3:]

    def environment(self) -> dict[str, str]:
        environment = self._installation().environment()
        environment["JAVA_HOME"] = str(self.java_home)
        environment["PATH"] = str(self.java_home / "bin") + os.pathsep + environment["PATH"]
        return environment

    def devices(self, *, timeout: float = 10) -> list[AndroidDevice]:
        result = self.runner.run(
            [self.adb, "devices"],
            environment=self.environment(),
            capture_output=True,
            timeout=timeout,
        )
        devices = []
        for line in result.stdout.splitlines()[1:]:
            if not line.strip():
                continue
            identifier, state = line.split(maxsplit=1)
            devices.append(AndroidDevice(identifier, state))
        return devices

    def avds(self) -> list[str]:
        result = self.runner.run(
            [self.emulator, "-list-avds"],
            environment=self.environment(),
            capture_output=True,
        )
        return [line for line in result.stdout.splitlines() if line]

    def start_emulator(self, name: str, *, headless: bool = False):
        if name not in self.avds():
            raise ValueError(f"Android virtual device {name!r} does not exist.")
        arguments = [self.emulator, f"@{name}", "-no-snapshot-save"]
        if headless:
            arguments.extend(
                [
                    "-no-snapshot-load",
                    "-no-window",
                    "-no-audio",
                    "-no-boot-anim",
                ]
            )
        return self.runner.start(
            arguments,
            environment=self.environment(),
            detached=True,
        )

    def wait_for_emulator(self, timeout: float = 180, *, identifier: str | None = None) -> AndroidDevice:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                devices = self.devices(timeout=min(5, remaining))
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                devices = []
            for device in devices:
                if (device.state != "device" or not device.identifier.startswith("emulator-")
                        or (identifier is not None and device.identifier != identifier)):
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    result = self.runner.run(
                        [self.adb, "-s", device.identifier, "shell", "getprop", "sys.boot_completed"],
                        environment=self.environment(),
                        capture_output=True,
                        timeout=min(5, remaining),
                    )
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                    continue
                if result.stdout.strip() == "1":
                    return device
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise TimeoutError("Android emulator did not finish booting.")

    def ensure_emulator(
        self,
        name: str | None = None,
        *,
        headless: bool = False,
    ) -> AndroidDevice:
        for device in self.devices():
            if device.state == "device" and device.identifier.startswith("emulator-"):
                return self.wait_for_emulator(identifier=device.identifier)
        avd = name or next(iter(self.avds()), None)
        if avd is None:
            raise RuntimeError("No Android virtual devices are configured.")
        self.start_emulator(avd, headless=headless)
        return self.wait_for_emulator()

    def install(self, device: AndroidDevice, package: Path) -> None:
        self.runner.run(
            [self.adb, "-s", device.identifier, "install", "-r", package],
            environment=self.environment(),
        )

    def prepare_for_tests(
        self,
        device: AndroidDevice,
        timeout: float = 30,
    ) -> None:
        prefix = [self.adb, "-s", device.identifier, "shell"]
        environment = self.environment()
        for command in (
            ("input", "keyevent", "KEYCODE_WAKEUP"),
            ("wm", "dismiss-keyguard"),
            ("settings", "put", "global", "window_animation_scale", "0"),
            ("settings", "put", "global", "transition_animation_scale", "0"),
            ("settings", "put", "global", "animator_duration_scale", "0"),
            ("input", "keyevent", "KEYCODE_HOME"),
        ):
            self.runner.run([*prefix, *command], environment=environment)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.runner.run(
                [*prefix, "dumpsys", "window"],
                environment=environment,
                capture_output=True,
            )
            focus = next(
                (
                    line
                    for line in result.stdout.splitlines()
                    if "mCurrentFocus=" in line
                ),
                "",
            )
            if "Application Not Responding" in focus:
                self.runner.run(
                    [*prefix, "input", "keyevent", "KEYCODE_ENTER"],
                    environment=environment,
                )
            elif focus and "=null" not in focus:
                return
            time.sleep(0.25)
        raise TimeoutError("Android emulator did not acquire a focused window")

    @staticmethod
    def launch_arguments(app_id: str, activity: str) -> tuple[str, ...]:
        # adb joins shell arguments into a command interpreted by the device's
        # shell. Escape the JVM inner-class marker used by generated activities.
        activity = activity.replace("$", r"\$")
        return (
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            f"{app_id}/{activity}",
            "-c",
            "android.intent.category.LAUNCHER",
            "-a",
            "android.intent.action.MAIN",
        )

    def launch(
        self,
        device: AndroidDevice,
        app_id: str,
        activity: str,
    ) -> None:
        self.runner.run(
            [
                self.adb,
                "-s",
                device.identifier,
                *self.launch_arguments(app_id, activity),
            ],
            environment=self.environment(),
        )
