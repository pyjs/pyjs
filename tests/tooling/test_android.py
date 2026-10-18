import os
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from pyjs.tooling.android import AndroidDevice, AndroidSDK
from pyjs.tooling.android_jvm import AndroidJVMApplication, AndroidJVMBuilder


def test_java_discovery_uses_sdkmgr_without_installing(monkeypatch, tmp_path):
    manager = Mock()
    manager.find.return_value.home = tmp_path / "jdk"
    factory = Mock(return_value=manager)
    monkeypatch.setattr("pyjs.tooling.android.Manager", factory)

    assert AndroidSDK.find_java_home() == tmp_path / "jdk"
    factory.assert_called_once_with(interactive=False)
    manager.find.assert_called_once_with("java", version="21")
    manager.ensure.assert_not_called()


def test_missing_java_provides_sdkmgr_instructions(monkeypatch):
    manager = Mock()
    manager.find.return_value = None
    monkeypatch.setattr("pyjs.tooling.android.Manager", Mock(return_value=manager))
    with pytest.raises(RuntimeError, match="sdkmgr install java@21"):
        AndroidSDK.find_java_home()
    manager.ensure.assert_not_called()


def test_sdk_discovery_reuses_packages_without_a_management_cli(monkeypatch, tmp_path):
    import sys

    adb = tmp_path / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb")
    adb.parent.mkdir()
    adb.touch()
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    assert AndroidSDK.find_root() == tmp_path
    assert not (tmp_path / "cmdline-tools").exists()


def test_conflicting_android_roots_are_not_silently_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "first"))
    monkeypatch.setenv("ANDROID_SDK_ROOT", str(tmp_path / "second"))
    with pytest.raises(RuntimeError, match="disagree"):
        AndroidSDK.find_root()


def test_missing_android_sdk_does_not_install_packages(monkeypatch, tmp_path):
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "missing"))
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="sdkmgr android install"):
        AndroidSDK.find_root()
    assert not (tmp_path / "missing").exists()


def test_android_sdk_parses_adb_devices():
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [],
        0,
        stdout=("List of devices attached\nemulator-5554\tdevice\nR58M1234567\toffline\n\n"),
        stderr="",
    )
    sdk = AndroidSDK(Path("/android"), Path("/java"), runner)

    assert sdk.devices() == [
        AndroidDevice("emulator-5554", "device"),
        AndroidDevice("R58M1234567", "offline"),
    ]


def test_android_environment_contains_sdk_and_jdk_paths():
    android = Path("/android")
    java = Path("/java")
    sdk = AndroidSDK(android, java)

    environment = sdk.environment()

    assert environment["ANDROID_HOME"] == str(android)
    assert environment["ANDROID_SDK_ROOT"] == str(android)
    assert environment["JAVA_HOME"] == str(java)
    assert environment["PATH"].startswith(
        os.pathsep.join((str(java / "bin"), str(android / "platform-tools"))) + os.pathsep
    )


def test_android_sdk_installs_and_launches_an_application():
    runner = Mock()
    sdk = AndroidSDK(Path("/android"), Path("/java"), runner)
    device = AndroidDevice("emulator-5554", "device")
    package = Path("/build/application.apk")

    sdk.install(device, package)
    sdk.launch(device, "org.pyjs.example", "org.pyjs.example.ExampleActivity")

    assert [call.args[0] for call in runner.run.call_args_list] == [
        [
            Path("/android/platform-tools/adb"),
            "-s",
            "emulator-5554",
            "install",
            "-r",
            package,
        ],
        [
            Path("/android/platform-tools/adb"),
            "-s",
            "emulator-5554",
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            "org.pyjs.example/org.pyjs.example.ExampleActivity",
            "-c",
            "android.intent.category.LAUNCHER",
            "-a",
            "android.intent.action.MAIN",
        ],
    ]


def test_android_sdk_escapes_generated_inner_activity_names():
    assert AndroidSDK.launch_arguments(
        "org.pyjs.example",
        "org.pyjs.example.PyjsAndroid$ExampleActivity",
    )[5] == "org.pyjs.example/org.pyjs.example.PyjsAndroid\\$ExampleActivity"


def test_android_sdk_starts_managed_headless_emulators_without_snapshots():
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [],
        0,
        stdout="Example_Test\n",
        stderr="",
    )
    sdk = AndroidSDK(Path("/android"), Path("/java"), runner)

    sdk.start_emulator("Example_Test", headless=True)

    assert runner.start.call_args.args[0] == [
        Path("/android/emulator/emulator"),
        "@Example_Test",
        "-no-snapshot-save",
        "-no-snapshot-load",
        "-no-window",
        "-no-audio",
        "-no-boot-anim",
    ]


def test_existing_emulator_waits_for_boot_instead_of_only_adb(monkeypatch):
    runner = Mock()
    runner.run.side_effect = [
        subprocess.CompletedProcess([], 0, stdout=""),
        subprocess.CompletedProcess([], 0, stdout="1\n"),
    ]
    sdk = AndroidSDK(Path("/android"), Path("/java"), runner)
    device = AndroidDevice("emulator-5554", "device")
    sdk.devices = Mock(return_value=[device])
    monkeypatch.setattr("pyjs.tooling.android.time.sleep", lambda _: None)
    assert sdk.ensure_emulator() == device
    assert runner.run.call_count == 2
    assert all(call.args[0][1:5] == ["-s", device.identifier, "shell", "getprop"]
               for call in runner.run.call_args_list)
    runner.start.assert_not_called()


def test_emulator_wait_does_not_select_physical_devices(monkeypatch):
    sdk = AndroidSDK(Path("/android"), Path("/java"), Mock())
    sdk.devices = Mock(return_value=[AndroidDevice("physical", "device")])
    monkeypatch.setattr("pyjs.tooling.android.time.monotonic", Mock(side_effect=[0, 0, 0, 2]))
    monkeypatch.setattr("pyjs.tooling.android.time.sleep", lambda _: None)
    with pytest.raises(TimeoutError, match="did not finish booting"):
        sdk.wait_for_emulator(timeout=1)
    sdk.runner.run.assert_not_called()


def test_android_jvm_application_derives_package_qualified_names():
    application = AndroidJVMApplication(
        Path("calculator.py"),
        "example.calculator",
        "org.pyjs.calculator",
        "CalculatorActivity",
        "Calculator",
        35,
    )

    assert application.jvm_class == "org/pyjs/calculator/PyjsAndroid"
    assert (
        application.android_activity
        == "org.pyjs.calculator.PyjsAndroid$CalculatorActivity"
    )


@pytest.mark.parametrize("app_id", ["calculator", "bad-id.example", "org..example"])
def test_android_jvm_application_rejects_invalid_application_ids(app_id):
    with pytest.raises(ValueError, match="application ID"):
        AndroidJVMApplication(
            Path("calculator.py"),
            "example.calculator",
            app_id,
            "CalculatorActivity",
            "Calculator",
            35,
        )


def test_android_jvm_builder_rejects_activity_initializers():
    application = AndroidJVMApplication(
        Path("calculator.py"),
        "example.calculator",
        "org.pyjs.calculator",
        "CalculatorActivity",
        "Calculator",
        35,
    )

    with pytest.raises(ValueError, match="without calling its Python __init__"):
        AndroidJVMBuilder._validate_activity_source(
            application,
            """
class CalculatorActivity:
    def __init__(self) -> None:
        self.value = 1
""",
        )


def test_android_jvm_application_validates_sdk_relationships():
    arguments = (
        Path("calculator.py"),
        "example.calculator",
        "org.pyjs.calculator",
        "CalculatorActivity",
        "Calculator",
    )

    with pytest.raises(ValueError, match="compile SDK cannot be older"):
        AndroidJVMApplication(*arguments, compile_sdk=20, min_sdk=21)
    with pytest.raises(ValueError, match="target SDK cannot be newer"):
        AndroidJVMApplication(*arguments, compile_sdk=34, target_sdk=35)


def test_android_jvm_builder_selects_the_exact_compile_sdk(tmp_path):
    sdk = AndroidSDK(tmp_path, Path("/java"))
    platform = tmp_path / "platforms" / "android-35" / "android.jar"
    platform.parent.mkdir(parents=True)
    platform.touch()
    builder = AndroidJVMBuilder(sdk)

    assert builder._platform(35) == platform
    with pytest.raises(RuntimeError, match="compile SDK 34 is not installed"):
        builder._platform(34)


def test_android_jvm_builder_packages_every_dex_file(tmp_path):
    package = tmp_path / "application.apk"
    dex = tmp_path / "dex"
    dex.mkdir()
    with zipfile.ZipFile(package, "w"):
        pass
    (dex / "classes.dex").write_bytes(b"first")
    (dex / "classes2.dex").write_bytes(b"second")

    AndroidJVMBuilder._append_dex_files(package, dex)

    with zipfile.ZipFile(package) as archive:
        assert archive.read("classes.dex") == b"first"
        assert archive.read("classes2.dex") == b"second"


def test_android_jvm_builder_orders_stable_and_preview_build_tools():
    stable = Path("/android/build-tools/36.0.0/d8")
    preview = Path("/android/build-tools/36.0.0-rc1/d8")

    assert AndroidSDK._build_tools_version(stable) > (
        AndroidSDK._build_tools_version(preview)
    )
