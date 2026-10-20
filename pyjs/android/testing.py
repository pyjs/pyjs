"""Pythonic in-application Android view testing backed by Espresso."""

from dataclasses import dataclass
from typing import Annotated

from pyjs import jvm
from pyjs.android import Activity, Bundle, Context, Runnable, View
from pyjs.java import i32
from pyjs.java.primitives import Reference

ActivityClass = Annotated[type[Activity], Reference("java/lang/Class")]


@jvm.native("android/app/Instrumentation")
class Instrumentation:
    def runOnMainSync(self, task: Runnable) -> None: ...


@jvm.native("androidx/test/platform/app/InstrumentationRegistry", name="getInstrumentation")
def _instrumentation() -> Instrumentation: ...


def run_on_main(task: Runnable) -> None:
    """Run a test callback on the main thread without needing an Activity."""
    _instrumentation().runOnMainSync(task)


@jvm.native("androidx/test/espresso/NoMatchingViewException")
class NoMatchingViewException:
    pass


@jvm.native("androidx/test/espresso/ViewAssertion", interface=True)
class ViewAssertion:
    """Inspect a matched native view on Espresso's synchronized UI thread."""

    def check(
        self, view: View | None, error: NoMatchingViewException | None,
    ) -> None:
        pass


@jvm.native("org/pyjs/testing/PyjsView")
@dataclass
class ViewInteraction:
    selector: str

    def in_dialog(self) -> ViewInteraction:
        """Match only views in a dialog window."""
        return self

    def click(self) -> None:
        pass

    def close_keyboard(self) -> None:
        pass

    def long_click(self) -> None:
        pass

    def replace_text(self, value: str) -> None:
        pass

    def press_key(self, key_code: i32) -> None:
        """Send a key through Espresso to the matched focused view."""
        pass

    def ime_action(self) -> None:
        """Perform the matched text field's input-method action."""
        pass

    def scroll_to(self) -> None:
        pass

    def assert_displayed(self) -> None:
        pass

    def assert_absent(self) -> None:
        pass

    def assert_text(self, value: str) -> None:
        pass

    def check(self, assertion: ViewAssertion) -> None:
        """Run a custom assertion, including when no matching view exists."""
        pass


@jvm.native("org/pyjs/testing/PyjsView", name="fromText")
def by_text(value: str) -> ViewInteraction:
    return ViewInteraction(f"text={value}")


@jvm.native("org/pyjs/testing/PyjsView", name="fromId")
def by_id(value: i32) -> ViewInteraction:
    return ViewInteraction(f"id={value}")


@jvm.native("org/pyjs/testing/PyjsAndroid", name="launch")
def launch(activity: ActivityClass) -> None:
    instance = activity()
    instance.onCreate(Bundle())


@jvm.native("org/pyjs/testing/PyjsAndroid", name="pressBack")
def press_back() -> None:
    pass


@jvm.native("org/pyjs/testing/PyjsAndroid", name="recreate")
def recreate() -> None:
    """Recreate the launched activity with its saved instance state."""
    pass


@jvm.native("org/pyjs/testing/PyjsAndroid", name="background")
def background() -> None:
    """Move the launched activity to its stopped (CREATED) state."""
    pass


@jvm.native("org/pyjs/testing/PyjsAndroid", name="resume")
def resume() -> None:
    """Return the launched activity to its RESUMED state."""
    pass


@jvm.native(
    "androidx/test/core/app/ApplicationProvider",
    name="getApplicationContext",
)
def application_context() -> Context:
    pass


__all__ = [
    "NoMatchingViewException",
    "ViewAssertion",
    "ViewInteraction",
    "application_context",
    "background",
    "by_id",
    "by_text",
    "launch",
    "press_back",
    "recreate",
    "resume",
    "run_on_main",
]
