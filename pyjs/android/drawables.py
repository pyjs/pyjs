"""Native interaction backgrounds for Android views."""

from pyjs import jvm
from pyjs.android import Drawable
from pyjs.java import i32


@jvm.native("android/content/res/ColorStateList")
class ColorStateList:
    def getDefaultColor(self) -> i32: ...


@jvm.native("android/content/res/ColorStateList", name="valueOf")
def color_state_list(color: i32) -> ColorStateList:
    """Return a native state list using one ARGB color for every state."""
    ...


@jvm.native("android/graphics/drawable/RippleDrawable")
class RippleDrawable(Drawable):
    def __init__(
        self, color: ColorStateList, content: Drawable | None, mask: Drawable | None,
    ) -> None: ...
