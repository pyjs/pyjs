from pyjs import js

from . import View

ANDROID_KEYCODE_TAB = 61
ANDROID_KEYCODE_DELETE = 67
ANDROID_KEYCODE_LEFT_BRACKET = 71
ANDROID_KEYCODE_RIGHT_BRACKET = 72


@js
class AndroidKeyCodes:
    tab = 61
    delete = 67
    leftBracket = 71
    rightBracket = 72


@js.native
class AndroidKeyEventData:
    def __init__(self):
        self.object = View()
        self.keyCode = 0
        self.action = ""
        self.shiftKey = False
        self.ctrlKey = False
        self.altKey = False
        self.returnValue = False


@js.inline(
    "{view}.android.setOnKeyListener(new android.view.View.OnKeyListener({{ "
    "onKey: (_nativeView, keyCode, event) => {{ "
    "const data = {{ object: {view}, keyCode: keyCode, "
    "action: event.getAction() === android.view.KeyEvent.ACTION_DOWN "
    "? 'down' : 'up', shiftKey: event.isShiftPressed(), "
    "ctrlKey: event.isCtrlPressed(), altKey: event.isAltPressed(), "
    "returnValue: false }}; {callback}(data); return data.returnValue; "
    "}} }}))"
)
def observe_android_keys(view: View, callback: callable) -> None: ...


__all__ = [
    "ANDROID_KEYCODE_DELETE",
    "ANDROID_KEYCODE_LEFT_BRACKET",
    "ANDROID_KEYCODE_RIGHT_BRACKET",
    "ANDROID_KEYCODE_TAB",
    "AndroidKeyEventData",
    "AndroidKeyCodes",
    "observe_android_keys",
]
