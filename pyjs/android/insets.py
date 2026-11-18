"""AndroidX window-insets controls; visibility requests complete asynchronously."""

from pyjs import jvm
from pyjs.android import View, Window
from pyjs.java import i32


@jvm.native("androidx/core/view/WindowInsetsCompat")
class WindowInsetsCompat:
    @jvm.native("androidx/core/view/WindowInsetsCompat", name="isVisible", invocation="virtual")
    def is_visible(self, types: i32) -> bool: ...


@jvm.native("androidx/core/view/WindowInsetsControllerCompat")
class WindowInsetsControllerCompat:
    def show(self, types: i32) -> None: ...

    def hide(self, types: i32) -> None: ...


@jvm.native("androidx/core/view/WindowCompat", name="getInsetsController")
def get_insets_controller(window: Window, view: View) -> WindowInsetsControllerCompat: ...


@jvm.native("androidx/core/view/ViewCompat", name="getRootWindowInsets")
def root_window_insets(view: View) -> WindowInsetsCompat | None:
    """Return the attached root's current insets, or None for a detached view."""
    pass


@jvm.native("androidx/core/view/WindowInsetsCompat$Type", name="ime")
def ime() -> i32:
    """Return the software-keyboard inset mask, not a visibility value."""
    pass
