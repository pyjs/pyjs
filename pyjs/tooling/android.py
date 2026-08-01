import os
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

    def start_emulator(self, name: str):
        if name not in self.avds():
            raise ValueError(f"Android virtual device {name!r} does not exist.")
        return self.runner.start(
            [self.emulator, f"@{name}", "-no-snapshot-save"],
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

    def ensure_emulator(self, name: str | None = None) -> AndroidDevice:
        for device in self.devices():
            if device.state == "device" and device.identifier.startswith("emulator-"):
                return device
        avd = name or next(iter(self.avds()), None)
        if avd is None:
            raise RuntimeError("No Android virtual devices are configured.")
        self.start_emulator(avd)
        return self.wait_for_emulator()
