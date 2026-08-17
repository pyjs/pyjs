from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.events import MouseEvent
from pyjs.web.files import File, FileList


@js.native
class DataTransfer:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DataTransfer

    Browser support: Chrome 3, Safari 4"""

    def __init__(self):
        self.dropEffect: str = ""
        self.effectAllowed: str = ""
        self.files: FileList = None
        self.items: DataTransferItemList = None
        self.types: list[str] = []

    def clearData(self, format: str | None = None) -> None: ...

    def getData(self, format: str) -> str: ...

    def setData(self, format: str, data: str) -> None: ...

    def setDragImage(self, image: Element, x: int, y: int) -> None: ...


@js.native
class DataTransferItem:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DataTransferItem

    Browser support: Chrome 11, Safari 5.1"""

    def __init__(self):
        self.kind: str = ""
        self.type: str = ""

    def getAsFile(self) -> File | None: ...

    def getAsString(self, callback: callable | None) -> None: ...


@js.native
class DataTransferItemList:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DataTransferItemList

    Browser support: Chrome 13, Safari 6"""

    def __init__(self):
        self.length: int = 0

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> DataTransferItem: ...

    def add(self, data: str, type: str) -> DataTransferItem | None: ...

    def clear(self) -> None: ...

    def remove(self, index: int) -> None: ...


@js.native
class DragEvent(MouseEvent):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DragEvent

    Browser support: Chrome 46, Safari 14"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        clientX: int = 0,
        clientY: int = 0,
        dataTransfer: DataTransfer | None = None,
    ):
        super().__init__(
            type, bubbles=bubbles, cancelable=cancelable, clientX=clientX, clientY=clientY
        )
        self.dataTransfer: DataTransfer | None = dataTransfer


@js
class DragEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, dataTransfer: DataTransfer | None = None):
        self.dataTransfer = dataTransfer
