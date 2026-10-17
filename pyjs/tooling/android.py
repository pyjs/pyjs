import os
import re
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
        configured = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        candidates = [
            Path(configured) if configured else None,
            Path.home() / "Android" / "Sdk",
            Path.home() / "Library" / "Android" / "sdk",
        ]
        for candidate in candidates:
            if candidate and (candidate / "platform-tools" / "adb").exists():
                return candidate
        raise RuntimeError("Android SDK not found. Set ANDROID_HOME or install the Android SDK.")

    @staticmethod
    def find_java_home() -> Path:
        configured = os.environ.get("JAVA_HOME")
        candidates = [
            Path(configured) if configured else None,
            Path.home() / ".local/share/JetBrains/Toolbox/apps/android-studio/jbr",
            Path("/opt/android-studio/jbr"),
            Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home"),
        ]
        for candidate in candidates:
            if candidate and (candidate / "bin" / "javac").exists():
                return candidate
        raise RuntimeError("JDK not found. Set JAVA_HOME to a JDK containing javac.")

    @property
    def adb(self) -> Path:
        return self.root / "platform-tools" / "adb"

    @property
    def emulator(self) -> Path:
        return self.root / "emulator" / "emulator"

    @property
    def avdmanager(self) -> Path:
        return self.root / "cmdline-tools" / "latest" / "bin" / "avdmanager"

    @property
    def sdkmanager(self) -> Path:
        return self.root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"

    def build_tool(self, name: str) -> Path:
        candidates = [
            path
            for path in (self.root / "build-tools").glob(f"*/{name}")
            if path.is_file()
        ]
        if not candidates:
            raise RuntimeError(f"Android SDK build tool {name!r} is not installed.")
        return max(candidates, key=self._build_tools_version)

    @staticmethod
    def _build_tools_version(
        path: Path,
    ) -> tuple[tuple[int, ...], int, tuple[int, ...]]:
        version = path.parent.name
        numbers = tuple(int(value) for value in re.findall(r"\d+", version))
        return numbers[:3], int("-" not in version), numbers[3:]

    def environment(self) -> dict[str, str]:
        paths = [
            self.java_home / "bin",
            self.root / "platform-tools",
            self.root / "emulator",
            self.root / "cmdline-tools" / "latest" / "bin",
        ]
        return {
            "ANDROID_HOME": str(self.root),
            "ANDROID_SDK_ROOT": str(self.root),
            "JAVA_HOME": str(self.java_home),
            "PATH": os.pathsep.join(map(str, paths)) + os.pathsep + os.environ.get("PATH", ""),
        }

    def devices(self) -> list[AndroidDevice]:
        result = self.runner.run(
            [self.adb, "devices"],
            environment=self.environment(),
            capture_output=True,
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

    def wait_for_emulator(self, timeout: float = 180) -> AndroidDevice:
        deadline = time.monotonic() + timeout
        self.runner.run([self.adb, "wait-for-device"], environment=self.environment())
        while time.monotonic() < deadline:
            devices = [device for device in self.devices() if device.state == "device"]
            for device in devices:
                result = self.runner.run(
                    [self.adb, "-s", device.identifier, "shell", "getprop", "sys.boot_completed"],
                    environment=self.environment(),
                    capture_output=True,
                )
                if result.stdout.strip() == "1":
                    return device
            time.sleep(1)
        raise TimeoutError("Android emulator did not finish booting.")

    def ensure_emulator(
        self,
        name: str | None = None,
        *,
        headless: bool = False,
    ) -> AndroidDevice:
        for device in self.devices():
            if device.state == "device" and device.identifier.startswith("emulator-"):
                return device
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
