from pathlib import Path

from pyjs.android.dependencies import resolve_androidx_runtime
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_jvm import AndroidJVMApplication, AndroidJVMBuilder


def build_android(output: Path | None = None) -> Path:
    source = Path(__file__).with_name("android.py")
    cache = Path.home() / ".cache" / "pyjs" / "android-runtime"
    application = AndroidJVMApplication(
        source,
        "pyjs_examples.notes.android",
        "org.pyjs.notes.jvm",
        "NotesActivity",
        "PyJS Notes",
        compile_sdk=35,
    )
    return AndroidJVMBuilder().build(
        application,
        output or Path("build/android-notes"),
        dependencies=resolve_androidx_runtime(cache),
    )


def run_android(output: Path | None = None) -> Path:
    package = build_android(output)
    sdk = AndroidSDK()
    device = sdk.ensure_emulator()
    sdk.install(device, package)
    sdk.launch(
        device,
        "org.pyjs.notes.jvm",
        "org.pyjs.notes.jvm.PyjsAndroid$NotesActivity",
    )
    return package
