from dataclasses import dataclass
from typing import TypedDict

from pyjs import js


class AnimationPair(TypedDict):
    x: float
    y: float


class AnimationDefinition(TypedDict, total=False):
    backgroundColor: object | str
    curve: object | str
    delay: int | float
    duration: int | float
    height: int | float | str
    iterations: int | float
    opacity: float
    rotate: float | object
    scale: AnimationPair
    target: object
    translate: AnimationPair
    width: int | float | str


@dataclass(frozen=True)
class NativeScriptModule:
    name: str
    version: str
    exports: tuple[str, ...]


@js.native
class HttpContent:
    def toString(self) -> str: ...


@js.native
class HttpResponse:
    def __init__(self):
        self.content = HttpContent()
        self.statusCode = 0


@js.native
class _Http:
    async def request(self, options: object) -> HttpResponse: ...


Http = _Http()
js.native(Http)


@js.native
def setTimeout(callback: callable, milliseconds: int = 0) -> int: ...


@js.native
def clearTimeout(timer: int | None = None) -> None: ...


@js.native
class EventData:
    def __init__(self):
        self.eventName = ""
        self.object = View()


@js.native
class TouchGestureEventData(EventData):
    def __init__(self):
        super().__init__()
        self.action = ""
        self._x = 0.0
        self._y = 0.0
        self._raw_x = 0.0
        self._raw_y = 0.0

    def getActivePointers(self) -> list[object]: ...

    def getX(self) -> float:
        return self._x

    def getY(self) -> float:
        return self._y

    @js.inline("{self}.android.getRawX() / Screen.mainScreen.scale")
    def getRawX(self) -> float:
        return self._raw_x

    @js.inline("{self}.android.getRawY() / Screen.mainScreen.scale")
    def getRawY(self) -> float:
        return self._raw_y


@js.native
class Point:
    def __init__(self, x: float = 0, y: float = 0):
        self.x = x
        self.y = y


@js.native
class Size:
    def __init__(self, width: float = 0, height: float = 0):
        self.width = width
        self.height = height


@js.native
class ScreenMetrics:
    def __init__(self):
        self.widthPixels = 400
        self.heightPixels = 800
        self.widthDIPs = 400
        self.heightDIPs = 800
        self.scale = 1.0


@js.native
class _Screen:
    mainScreen = ScreenMetrics()


Screen = _Screen()
js.native(Screen)


@js.native
class _GestureTypes:
    tap = 1
    doubleTap = 2
    pinch = 4
    pan = 8
    swipe = 16
    rotation = 32
    longPress = 64
    touch = 128


GestureTypes = _GestureTypes()
js.native(GestureTypes)


@js.native
class FileSystemEntity:
    def __init__(self):
        self.name = ""
        self.path = ""

    def removeSync(self, on_error: callable | None = None): ...

    def renameSync(self, new_name: str, on_error: callable | None = None): ...


@js.native
class File(FileSystemEntity):
    @staticmethod
    def exists(path: str) -> bool: ...

    @staticmethod
    def fromPath(path: str) -> File: ...

    def readTextSync(self) -> str: ...

    def writeTextSync(self, content: str): ...


@js.native
class Folder(FileSystemEntity):
    @staticmethod
    def exists(path: str) -> bool: ...

    @staticmethod
    def fromPath(path: str) -> Folder: ...

    def contains(self, name: str) -> bool: ...

    def getFile(self, name: str) -> File: ...

    def getFolder(self, name: str) -> Folder: ...


@js.native
class _KnownFolders:
    def documents(self) -> Folder: ...

    def temp(self) -> Folder: ...

    def currentApp(self) -> Folder: ...


knownFolders = _KnownFolders()
js.native(knownFolders)


@js.native
class AndroidActivityBackPressedEventData(EventData):
    def __init__(self):
        super().__init__()
        self.cancel = False


@js.native
class View:
    loadedEvent = "loaded"
    unloadedEvent = "unloaded"
    layoutChangedEvent = "layoutChanged"

    def __init__(self):
        self.id = ""
        self.testID = ""
        self.className = ""
        self.accessible = False
        self.accessibilityLabel = ""
        self.accessibilityHint = ""
        self.accessibilityHidden = False
        self.accessibilityLiveRegion = "none"
        self.accessibilityRole = ""
        self.accessibilityState = ""
        self.accessibilityValue = ""
        self.backgroundColor = ""
        self.borderColor = ""
        self.borderRadius: int | float | str = 0
        self.borderWidth: int | float | str = 0
        self.color = ""
        self.fontFamily = ""
        self.fontSize: int | float = 14
        self.fontWeight: int | str = "normal"
        self.height: int | float | str = "auto"
        self.width: int | float | str = "auto"
        self.horizontalAlignment = "stretch"
        self.verticalAlignment = "stretch"
        self.margin: int | str = 0
        self.marginTop: int | float | str = 0
        self.marginRight: int | float | str = 0
        self.marginBottom: int | float | str = 0
        self.marginLeft: int | float | str = 0
        self.padding: int | str = 0
        self.visibility = "visible"
        self.isEnabled = True
        self.opacity = 1.0
        self.scaleX = 1.0
        self.scaleY = 1.0
        self.statusBarStyle = "light"
        self.translateX = 0.0
        self.translateY = 0.0
        self.zIndex = 0
        self.androidElevation = 0
        self.androidDynamicElevationOffset = 0
        self.row = 0
        self.column = 0
        self.rowSpan = 1
        self.columnSpan = 1

    def on(self, event_name: str | int, callback: callable): ...

    def off(self, event_name: str | int, callback: callable): ...

    def focus(self) -> bool:
        return True

    def accessibilityAnnouncement(self, message: str = ""): ...

    def getViewById(self, view_id: str) -> View | None:
        if self.id == view_id:
            return self
        return None

    def getLocationRelativeTo(self, other_view: View) -> Point:
        return Point()

    def getLocationOnScreen(self) -> Point:
        return Point()

    def getActualSize(self) -> Size:
        width = self.width if isinstance(self.width, int) else 0
        height = self.height if isinstance(self.height, int) else 0
        return Size(width, height)

    async def animate(self, options: AnimationDefinition): ...


@js.native
class LayoutBase(View):
    def __init__(self):
        super().__init__()
        self.children: list[View] = []

    def addChild(self, child: View):
        self.children.append(child)

    def insertChild(self, child: View, index: int) -> bool:
        self.children.insert(index, child)
        return True

    def removeChild(self, child: View):
        self.children.remove(child)

    def removeChildren(self):
        self.children.clear()

    def getChildrenCount(self) -> int:
        return len(self.children)

    def getChildAt(self, index: int) -> View:
        return self.children[index]

    def getChildIndex(self, child: View) -> int:
        index = 0
        for candidate in self.children:
            if candidate is child:
                return index
            index += 1
        return -1

    def getViewById(self, view_id: str) -> View | None:
        if self.id == view_id:
            return self
        for child in self.children:
            match = child.getViewById(view_id)
            if match is not None:
                return match
        return None


@js.native
class StackLayout(LayoutBase):
    def __init__(self):
        super().__init__()
        self.orientation = "vertical"


@js.native
class GridLayout(LayoutBase):
    def __init__(self):
        super().__init__()
        self.rows = ""
        self.columns = ""


@js.native
class ScrollView(View):
    scrollEvent = "scroll"

    def __init__(self):
        super().__init__()
        self.content = View()
        self.orientation = "vertical"
        self.isScrollEnabled = True
        self.scrollBarIndicatorVisible = True
        self.horizontalOffset = 0.0
        self.verticalOffset = 0.0
        self.scrollableHeight = 0.0
        self.scrollableWidth = 0.0

    def scrollToHorizontalOffset(self, value: float, animated: bool):
        self.horizontalOffset = value

    def scrollToVerticalOffset(self, value: float, animated: bool):
        self.verticalOffset = value

    def getViewById(self, view_id: str) -> View | None:
        if self.id == view_id:
            return self
        return self.content.getViewById(view_id)


@js.native
class Page(View):
    def __init__(self):
        super().__init__()
        self.actionBarHidden = False
        self.content = View()


@js.native
class Label(View):
    def __init__(self):
        super().__init__()
        self.text = ""
        self.fontSize = 14
        self.fontWeight = "normal"
        self.lineHeight = 0
        self.textAlignment = "left"
        self.textTransform = "none"
        self.textWrap = False


@js.native
class Button(View):
    tapEvent = "tap"

    def __init__(self):
        super().__init__()
        self.text = ""
        self.fontSize = 14
        self.lineHeight = 0
        self.textTransform = "none"
        self.textWrap = False


@js.native
class EditableTextBase(View):
    blurEvent = "blur"
    focusEvent = "focus"
    textChangeEvent = "textChange"

    def __init__(self):
        super().__init__()
        self.text = ""
        self.hint = ""
        self.lineHeight = 0
        self.editable = True
        self.autocorrect = True
        self.maxLength = 0
        self.keyboardType = "text"
        self.returnKeyType = "done"
        self.updateTextTrigger = "textChanged"
        self.autocapitalizationType = "sentences"
        self.selectionStart = 0
        self.selectionEnd = 0

    def dismissSoftInput(self): ...

    def setSelection(self, start: int, stop: int = -1):
        self.selectionStart = start
        self.selectionEnd = start if stop < 0 else stop


@js.native
class TextField(EditableTextBase):
    returnPressEvent = "returnPress"

    def __init__(self):
        super().__init__()
        self.secure = False
        self.closeOnReturn = True


@js.native
class TextView(EditableTextBase):
    returnPressEvent = "returnPress"

    def __init__(self):
        super().__init__()
        self.maxLines = 0


@js.native
class _Application:
    suspendEvent = "suspend"
    resumeEvent = "resume"
    orientationChangedEvent = "orientationChanged"

    def __init__(self):
        self.android = _AndroidApplication()

    def on(self, event_name: str, callback: callable): ...

    def off(self, event_name: str, callback: callable): ...

    @js.inline("{self}.run({{ create: {create} }})")
    def run(self, create: callable) -> None: ...


@js.native
class _AndroidApplication:
    activityBackPressedEvent = "activityBackPressed"

    def on(self, event_name: str, callback: callable): ...

    def off(self, event_name: str, callback: callable): ...


Application = _Application()
js.native(Application)

__all__ = [
    "AndroidActivityBackPressedEventData",
    "AnimationDefinition",
    "AnimationPair",
    "Application",
    "Button",
    "EditableTextBase",
    "EventData",
    "File",
    "FileSystemEntity",
    "Folder",
    "GestureTypes",
    "GridLayout",
    "Http",
    "HttpContent",
    "HttpResponse",
    "Label",
    "LayoutBase",
    "Page",
    "Point",
    "Screen",
    "ScreenMetrics",
    "ScrollView",
    "Size",
    "StackLayout",
    "TextField",
    "TextView",
    "TouchGestureEventData",
    "View",
    "NativeScriptModule",
    "clearTimeout",
    "knownFolders",
    "setTimeout",
]
