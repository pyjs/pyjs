from pyjs import js

from . import View


@js
class AndroidHapticFeedback:
    """Widely supported Android feedback types used by custom gestures."""

    longPress = 0
    virtualKey = 1


@js
def perform_haptic_feedback(_view: View, _feedback_type: int) -> bool:
    """Perform system-governed Android haptics when a native view is present."""

    return False


@perform_haptic_feedback.client
@js.inline(
    "(() => {{ const nativeView = {view}.android; "
    "return !!(nativeView && nativeView.performHapticFeedback && "
    "nativeView.performHapticFeedback({feedback_type})); }})()"
)
def _perform_haptic_feedback_client(view: View, feedback_type: int) -> bool: ...


__all__ = ["AndroidHapticFeedback", "perform_haptic_feedback"]
