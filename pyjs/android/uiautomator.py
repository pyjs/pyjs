"""Device-only Python bindings for cross-app UI Automator interactions."""

from dataclasses import dataclass

from pyjs import jvm
from pyjs.java import i32


@jvm.native("org/pyjs/testing/PyjsDevice")
@dataclass
class Device:
    def press_home(self) -> None:
        pass

    def current_package(self) -> str:
        return ""


@jvm.native("org/pyjs/testing/PyjsDeviceElement")
@dataclass
class DeviceElement:
    selector: str

    def click(self) -> None:
        pass

    def drag_to(
        self, target: DeviceElement, speed: i32 = 1_000,
        offset_x: i32 = 0, offset_y: i32 = 0,
    ) -> None:
        """Long-press and drop at the target's visible center plus pixel offsets."""
        pass

    def text(self) -> str:
        return ""


@jvm.native("org/pyjs/testing/PyjsDevice", name="get")
def device() -> Device:
    return Device()


@jvm.native("org/pyjs/testing/PyjsDevice", name="findText")
def find_text(value: str, timeout_ms: int = 10_000) -> DeviceElement:
    return DeviceElement(f"text={value}, timeout={timeout_ms}")


@jvm.native("org/pyjs/testing/PyjsDevice", name="findResource")
def find_resource(value: str, timeout_ms: int = 10_000) -> DeviceElement:
    return DeviceElement(f"resource={value}, timeout={timeout_ms}")


__all__ = ["Device", "DeviceElement", "device", "find_resource", "find_text"]
