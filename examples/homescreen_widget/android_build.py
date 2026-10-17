from pathlib import Path

from pyjs.tooling.android_jvm import (
    AndroidJVMApplication,
    AndroidJVMBuilder,
    AndroidManifestComponent,
)


def build_android_widget(output: Path | None = None) -> Path:
    directory = Path(__file__).parent
    application = AndroidJVMApplication(
        directory / "android.py",
        "pyjs_examples.homescreen_widget.android",
        "org.pyjs.widgets",
        "WidgetActivity",
        "PyJS Home Screen Widget",
        compile_sdk=35,
        resources=(directory / "res",),
        components=(
            AndroidManifestComponent(
                "receiver",
                "NotesWidgetProvider",
                actions=("android.appwidget.action.APPWIDGET_UPDATE",),
                metadata=(
                    (
                        "android.appwidget.provider",
                        "@xml/notes_widget_info",
                    ),
                ),
            ),
            AndroidManifestComponent(
                "service",
                "NotesRemoteViewsService",
                permission="android.permission.BIND_REMOTEVIEWS",
            ),
        ),
    )
    return AndroidJVMBuilder().build(
        application,
        output or Path("build/android-widget"),
    )
