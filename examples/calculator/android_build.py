from pathlib import Path

from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_jvm import AndroidJVMApplication, AndroidJVMBuilder


def application() -> AndroidJVMApplication:
    return AndroidJVMApplication(
        Path(__file__).with_name("android.py"),
        "pyjs_examples.calculator.android",
        "org.pyjs.calculator",
        "CalculatorActivity",
        "PyJS Calculator",
        compile_sdk=35,
    )


def run_android(output: Path | None = None) -> Path:
    sdk = AndroidSDK()
    app = application()
    package = AndroidJVMBuilder(sdk).build(
        app, output or Path("build/android-calculator"),
    )
    device = sdk.ensure_emulator()
    sdk.install(device, package)
    sdk.launch(device, app.app_id, app.android_activity)
    return package
