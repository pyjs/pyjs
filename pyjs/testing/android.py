"""Android UI-tree inspection, image assertions, and test sessions."""

import logging
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image

from pyjs.tooling.android import AndroidDevice, AndroidSDK
from pyjs.ui.interaction import InteractionSample

from .artifacts import Artifact, ArtifactManifest
from .interaction.gesture import GestureScript

BOUNDS_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
ANDROID_ERROR_PATTERN = re.compile(
    r"FATAL EXCEPTION|Uncaught Exception",
    re.IGNORECASE,
)
ANDROID_STACK_PATTERN = re.compile(
    r"(?:^\s*|:\s+)(?:at\s|Caused by:|\.\.\. \d+ more)",
    re.IGNORECASE,
)
LOGCAT_RECORD_PATTERN = re.compile(
    r"^(?:(?P<timestamp>\d\d-\d\d\s+\S+)\s+"
    r"(?P<pid>\d+)\s+\d+\s+)?"
    r"(?P<priority>[VDIWEF])\s+(?P<tag>[^:]+):"
)


@dataclass(frozen=True)
class AndroidBounds:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)

    @classmethod
    def parse(cls, value: str) -> AndroidBounds:
        match = BOUNDS_PATTERN.fullmatch(value)
        if match is None:
            raise ValueError(f"Invalid Android bounds: {value!r}")
        return cls(*(int(part) for part in match.groups()))


@dataclass(frozen=True)
class AndroidElement:
    text: str
    test_id: str
    resource_id: str
    description: str
    class_name: str
    clickable: bool
    enabled: bool
    checkable: bool
    checked: bool
    selected: bool
    focused: bool
    bounds: AndroidBounds


def parse_ui_tree(source: str) -> list[AndroidElement]:
    root = ET.fromstring(source)
    elements = []
    for node in root.iter("node"):
        attributes = node.attrib
        bounds = attributes.get("bounds")
        if not bounds:
            continue
        resource_id = attributes.get("resource-id", "")
        elements.append(
            AndroidElement(
                text=attributes.get("text", ""),
                test_id=resource_id.rsplit("/", 1)[-1],
                resource_id=resource_id,
                description=attributes.get("content-desc", ""),
                class_name=attributes.get("class", ""),
                clickable=attributes.get("clickable") == "true",
                enabled=attributes.get("enabled") == "true",
                checkable=attributes.get("checkable") == "true",
                checked=attributes.get("checked") == "true",
                selected=attributes.get("selected") == "true",
                focused=attributes.get("focused") == "true",
                bounds=AndroidBounds.parse(bounds),
            )
        )
    return elements


def assert_android_image(
    actual_path: Path,
    expected_path: Path,
    *,
    pixel_threshold: int = 8,
    max_different_pixel_ratio: float = 0.01,
    diff_path: Path | None = None,
) -> None:
    with Image.open(actual_path) as image:
        actual = image.convert("RGBA")
    with Image.open(expected_path) as image:
        expected = image.convert("RGBA")
    if actual.size != expected.size:
        raise AssertionError(
            f"Android image size {actual.size} does not match expected {expected.size}."
        )

    different = 0
    for actual_pixel, expected_pixel in zip(
        actual.get_flattened_data(), expected.get_flattened_data(), strict=True
    ):
        channel_difference = max(
            abs(actual_channel - expected_channel)
            for actual_channel, expected_channel in zip(
                actual_pixel, expected_pixel, strict=True
            )
        )
        if channel_difference > pixel_threshold:
            different += 1

    total = actual.width * actual.height
    ratio = different / total
    if ratio <= max_different_pixel_ratio:
        return
    if diff_path is not None:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff = Image.new("RGBA", actual.size, (0, 0, 0, 255))
        diff_pixels = []
        for actual_pixel, expected_pixel in zip(
            actual.get_flattened_data(), expected.get_flattened_data(), strict=True
        ):
            channel_difference = max(
                abs(actual_channel - expected_channel)
                for actual_channel, expected_channel in zip(
                    actual_pixel, expected_pixel, strict=True
                )
            )
            if channel_difference > pixel_threshold:
                diff_pixels.append((255, 0, 255, 255))
            else:
                diff_pixels.append((0, 0, 0, 255))
        diff.putdata(diff_pixels)
        diff.save(diff_path)
    raise AssertionError(
        f"{different}/{total} Android pixels differ ({ratio:.2%}); "
        f"allowed {max_different_pixel_ratio:.2%}."
    )


def extract_android_errors(source: str) -> str:
    """Retain Android crash headings and their following JVM stack frames."""
    blocks = []
    block = []
    error_record = None
    unstructured_error = False

    def finish_block() -> None:
        nonlocal block
        if block:
            blocks.append(block)
            block = []

    for line in source.splitlines():
        record = LOGCAT_RECORD_PATTERN.match(line)
        identity = None
        if record is not None:
            identity = (
                record.group("pid"),
                record.group("priority"),
                record.group("tag").strip(),
            )
        if error_record is not None and identity == error_record:
            block.append(line)
        elif ANDROID_ERROR_PATTERN.search(line):
            finish_block()
            error_record = identity
            unstructured_error = identity is None
            block.append(line)
        elif unstructured_error and ANDROID_STACK_PATTERN.search(line):
            block.append(line)
        else:
            finish_block()
            error_record = None
            unstructured_error = False
    finish_block()
    if any("FATAL EXCEPTION" in line for block in blocks for line in block):
        blocks = [
            block
            for block in blocks
            if not any("System.err: An uncaught Exception" in line for line in block)
        ]
    return "\n".join(line for block in blocks for line in block)


class AndroidTestSession:
    def __init__(
        self,
        sdk: AndroidSDK,
        device: AndroidDevice,
        app_id: str,
        *,
        activity: str,
    ):
        self.sdk = sdk
        self.device = device
        self.app_id = app_id
        self.activity = activity

    def adb(
        self, *arguments: str, text: bool = True, check: bool = True,
        timeout: float | None = None,
    ):
        return self.sdk.runner.run(
            [self.sdk.adb, "-s", self.device.identifier, *arguments],
            environment=self.sdk.environment(),
            capture_output=True,
            text=text,
            check=check,
            timeout=timeout,
        )

    def clear_logcat(self) -> None:
        self.adb("logcat", "-c")

    def force_stop(self) -> None:
        self.adb("shell", "am", "force-stop", self.app_id)

    def is_running(self) -> bool:
        return bool(
            self.adb("shell", "pidof", self.app_id, check=False).stdout.strip()
        )

    def launch(self) -> None:
        self.clear_logcat()
        self.adb(*self.sdk.launch_arguments(self.app_id, self.activity))

    def ui_tree(self) -> str:
        # dump can return exit code zero on idle failure without writing a file.
        remote_path = "/data/local/tmp/pyjs-window-" + uuid4().hex + ".xml"
        try:
            result = self.adb("shell", "uiautomator", "dump", remote_path, timeout=20)
            if "dumped to: " + remote_path not in result.stdout:
                raise RuntimeError("Android UI dump was not produced: "
                                   + result.stdout + result.stderr)
            return self.adb("shell", "cat", remote_path, timeout=5).stdout
        finally:
            try:
                self.adb("shell", "rm", "-f", remote_path, timeout=5)
            except (OSError, subprocess.SubprocessError) as error:
                logging.getLogger(__name__).warning(
                    "Could not remove Android UI dump %s: %s", remote_path, error,
                )

    def elements(self) -> list[AndroidElement]:
        return parse_ui_tree(self.ui_tree())

    def find_element(
        self,
        *,
        text: str | None = None,
        test_id: str | None = None,
        resource_id: str | None = None,
    ) -> AndroidElement | None:
        for element in self.elements():
            if text is not None and element.text != text:
                continue
            if test_id is not None and element.test_id != test_id:
                continue
            if resource_id is not None and element.resource_id != resource_id:
                continue
            return element
        return None

    def wait_for_element(
        self,
        *,
        text: str | None = None,
        test_id: str | None = None,
        resource_id: str | None = None,
        timeout: float = 15,
        interval: float = 0.25,
    ) -> AndroidElement:
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                element = self.find_element(text=text, test_id=test_id, resource_id=resource_id)
            except Exception as exc:
                last_error = exc
            else:
                if element is not None:
                    return element
            if not self.is_running():
                message = (
                    f"Android application {self.app_id!r} stopped while waiting for UI."
                )
                errors = self.log_errors(10_000)
                if errors:
                    message += f"\n{errors}"
                raise RuntimeError(message)
            time.sleep(interval)
        selector = {"text": text, "test_id": test_id, "resource_id": resource_id}
        details = ", ".join(f"{key}={value!r}" for key, value in selector.items() if value)
        message = f"Timed out waiting for Android element with {details}."
        if last_error is not None:
            message += f" Last UI inspection failed: {last_error}"
        raise TimeoutError(message)

    def tap(self, element: AndroidElement) -> None:
        x, y = element.bounds.center
        self.adb("shell", "input", "tap", str(x), str(y))

    def tap_element(self, **selector) -> AndroidElement:
        element = self.wait_for_element(**selector)
        self.tap(element)
        return element

    def dispatch_pointer_sample(self, sample: InteractionSample) -> None:
        action = "MOVE"
        if sample.phase == "down":
            action = "DOWN"
        elif sample.phase == "up":
            action = "UP"
        elif sample.phase == "cancel":
            action = "CANCEL"
        elif sample.phase != "hold" and sample.phase != "move":
            raise ValueError(f"Unsupported pointer phase: {sample.phase!r}")
        self.adb(
            "shell",
            "input",
            "motionevent",
            action,
            str(round(sample.x)),
            str(round(sample.y)),
        )

    def dispatch_gesture(
        self,
        script: GestureScript,
        *,
        settle_ms: float = 0,
        wait: callable = time.sleep,
    ) -> None:
        """Send one target-neutral gesture to the device with declared timing."""

        previous_elapsed = 0.0
        for sample in script.samples:
            delay_ms = sample.elapsed_ms - previous_elapsed
            if delay_ms < 0:
                raise ValueError("Gesture sample times must not move backwards.")
            if delay_ms > 0:
                wait(delay_ms / 1_000)
            self.dispatch_pointer_sample(sample)
            previous_elapsed = sample.elapsed_ms
        if not script.active and settle_ms > 0:
            wait(settle_ms / 1_000)

    @contextmanager
    def held_gesture(
        self,
        script: GestureScript,
        *,
        settle_ms: float = 0,
        wait: callable = time.sleep,
    ):
        """Hold an active gesture open while the caller inspects the device."""

        if not script.active:
            raise ValueError("A held Android gesture must remain pressed.")
        self.dispatch_gesture(script, wait=wait)
        try:
            yield
        except BaseException:
            self.dispatch_pointer_sample(
                InteractionSample("cancel", script.x, script.y, script.pointer_id)
            )
            raise
        else:
            self.dispatch_pointer_sample(
                InteractionSample("up", script.x, script.y, script.pointer_id)
            )
        finally:
            if settle_ms > 0:
                wait(settle_ms / 1_000)

    def screenshot(self, path: Path) -> Path:
        result = self.adb("exec-out", "screencap", "-p", text=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result.stdout)
        return path

    def logcat(self, lines: int = 1000) -> str:
        process = self.adb("shell", "pidof", self.app_id, check=False).stdout.strip()
        arguments = ["logcat"]
        if process:
            arguments.extend(["--pid", process.split()[0]])
        arguments.extend(["-d", "-t", str(lines)])
        return self.adb(*arguments).stdout

    def log_errors(self, lines: int = 1000) -> str:
        return extract_android_errors(self.logcat(lines))

    def capture_artifacts(self, directory: Path, name: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        prefix = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "android"
        artifacts = []
        errors = {}

        def capture(
            artifact_name: str,
            kind: str,
            path: Path,
            media_type: str,
            writer,
        ) -> None:
            try:
                writer(path)
            except Exception as exc:
                errors[artifact_name] = f"{type(exc).__name__}: {exc}"
            else:
                artifacts.append(Artifact(artifact_name, kind, path.resolve(), media_type))

        capture(
            "screenshot",
            "image",
            directory / f"{prefix}.png",
            "image/png",
            self.screenshot,
        )
        capture(
            "ui_tree",
            "tree",
            directory / f"{prefix}.xml",
            "application/xml",
            lambda path: path.write_text(self.ui_tree(), encoding="utf-8"),
        )
        capture(
            "logcat",
            "log",
            directory / f"{prefix}.logcat.txt",
            "text/plain",
            lambda path: path.write_text(self.logcat(), encoding="utf-8"),
        )
        metadata = {
            "app_id": self.app_id,
            "activity": self.activity,
            "device": self.device.identifier,
        }
        if errors:
            metadata["capture_errors"] = errors
        manifest = ArtifactManifest(
            target="android",
            metadata=metadata,
            artifacts=artifacts,
        )
        return manifest.write(directory / f"{prefix}.manifest.json")

    @contextmanager
    def artifacts_on_failure(self, directory: Path, name: str):
        try:
            yield
        except BaseException as exc:
            try:
                manifest = self.capture_artifacts(directory, name)
            except Exception as capture_error:
                exc.add_note(f"Android failure artifact capture failed: {capture_error}")
            else:
                exc.add_note(f"Android failure artifacts: {manifest}")
                errors = self._captured_errors(directory, name)
                if errors:
                    exc.add_note(f"Android runtime errors:\n{errors}")
            raise

    def _captured_errors(self, directory: Path, name: str) -> str:
        prefix = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "android"
        path = directory / f"{prefix}.logcat.txt"
        try:
            return extract_android_errors(path.read_text(encoding="utf-8"))
        except OSError:
            return ""
