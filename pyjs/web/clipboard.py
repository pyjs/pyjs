from pyjs import js
from pyjs.web.dragdrop import DataTransfer
from pyjs.web.events import Event, EventTarget
from pyjs.web.files import Blob


@js.native
class Clipboard(EventTarget):
    """WebIDL source: @webref/idl/clipboard-apis.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Clipboard

    Browser support: Chrome 66, Safari 13.1"""

    async def read(
        self, *, unsanitized: list[str] | None = None
    ) -> list[ClipboardItem]: ...

    async def readText(self) -> str: ...

    async def write(self, data: list[ClipboardItem]) -> None: ...

    async def writeText(self, data: str) -> None: ...


@js.native
class ClipboardChangeEvent(Event):
    """WebIDL source: @webref/idl/clipboard-apis.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ClipboardChangeEvent

    Browser support: Chrome 144"""

    def __init__(self, type: str, *, types: list[str] | None = None, changeId: int = 0):
        super().__init__()
        self.changeId: int = changeId
        self.types: list[str] = types


@js
class ClipboardChangeEventInit:
    """WebIDL source: @webref/idl/clipboard-apis.idl"""

    def __init__(self, changeId: int = 0, types: list[str] | None = None):
        self.changeId = changeId
        if types is None:
            types = []
        self.types = types


@js.native
class ClipboardEvent(Event):
    """WebIDL source: @webref/idl/clipboard-apis.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ClipboardEvent

    Browser support: Chrome 41, Safari 10.1"""

    def __init__(self, type: str, *, clipboardData: DataTransfer | None = None):
        super().__init__()
        self.clipboardData: DataTransfer | None = clipboardData


@js
class ClipboardEventInit:
    """WebIDL source: @webref/idl/clipboard-apis.idl"""

    def __init__(self, clipboardData: DataTransfer | None = None):
        self.clipboardData = clipboardData


@js.native
class ClipboardItem:
    """WebIDL source: @webref/idl/clipboard-apis.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ClipboardItem

    Browser support: Chrome 76, Safari 13.1"""

    def __init__(
        self, items: dict[str, str | Blob], *, presentationStyle: str = "unspecified"
    ):
        self.presentationStyle: str = presentationStyle
        self.types: list[str] = []

    async def getType(self, type: str) -> Blob: ...

    @staticmethod
    def supports(type: str) -> bool: ...


@js
class ClipboardItemOptions:
    """WebIDL source: @webref/idl/clipboard-apis.idl"""

    def __init__(self, presentationStyle: str = "unspecified"):
        self.presentationStyle = presentationStyle


@js
class ClipboardUnsanitizedFormats:
    """WebIDL source: @webref/idl/clipboard-apis.idl"""

    def __init__(self, unsanitized: list[str] | None = None):
        if unsanitized is not None:
            self.unsanitized = unsanitized


@js.native
class Navigator:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Navigator

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.clipboard: Clipboard = None


navigator = Navigator()
js.native(navigator)


@js
class PermissionDescriptor:
    """WebIDL source: @webref/idl/permissions.idl"""

    def __init__(self, name: str):
        self.name = name


@js
class ClipboardPermissionDescriptor:
    """WebIDL source: @webref/idl/clipboard-apis.idl"""

    def __init__(self, name: str, allowWithoutGesture: bool = False):
        self.name = name
        self.allowWithoutGesture = allowWithoutGesture
