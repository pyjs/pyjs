from pyjs import js, nojs
from pyjs.javascript import (
    ArrayBuffer,
    BigInt64Array,
    BigUint64Array,
    DataView,
    Float16Array,
    Float32Array,
    Float64Array,
    Int8Array,
    Int16Array,
    Int32Array,
    Uint8Array,
    Uint8ClampedArray,
    Uint16Array,
    Uint32Array,
)
from pyjs.web.dom import DOMException
from pyjs.web.events import EventTarget
from pyjs.web.streams import ReadableStream


@js(builtin=True)
class Blob:
    """WebIDL source: @webref/idl/FileAPI.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Blob

    Browser support: Chrome 5, Safari 6"""

    def __init__(
        self,
        blobParts: list[
            Int8Array
            | Int16Array
            | Int32Array
            | Uint8Array
            | Uint16Array
            | Uint32Array
            | Uint8ClampedArray
            | BigInt64Array
            | BigUint64Array
            | Float16Array
            | Float32Array
            | Float64Array
            | DataView
            | ArrayBuffer
            | Blob
            | str
        ]
        | None = None,
        *,
        type: str = "",
        endings: str = "transparent",
    ):
        self.size: int = 0
        self.type: str = type

    async def arrayBuffer(self) -> ArrayBuffer: ...

    async def bytes(self) -> Uint8Array: ...

    def slice(
        self,
        start: int | None = None,
        end: int | None = None,
        contentType: str | None = None,
    ) -> Blob: ...

    def stream(self) -> ReadableStream: ...

    async def text(self) -> str: ...

    def textStream(self) -> ReadableStream: ...


@js
class BlobPropertyBag:
    """WebIDL source: @webref/idl/FileAPI.idl"""

    def __init__(self, endings: str = "transparent", type: str = ""):
        self.endings = endings
        self.type = type


@js(builtin=True)
class FileList:
    """WebIDL source: @webref/idl/FileAPI.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FileList

    Browser support: Chrome 2, Safari 4"""

    def __init__(self):
        self._items: list[File] = []
        self.length: int = 0

    @js(inline="{self}[{index}]")
    def __getitem__(self, index: int) -> File:
        return self._items[index]

    @nojs
    def __iter__(self):
        return iter(self._items)

    @js(inline="{self}.length")
    def __len__(self) -> int:
        return len(self._items)

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> File | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None


@js(builtin=True)
class FileReader(EventTarget):
    """WebIDL source: @webref/idl/FileAPI.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FileReader

    Browser support: Chrome 6, Safari 6"""

    DONE = 2
    EMPTY = 0
    LOADING = 1

    def __init__(self):
        super().__init__()
        self.error: DOMException | None = None
        self.onabort: callable = None
        self.onerror: callable = None
        self.onload: callable = None
        self.onloadend: callable = None
        self.onloadstart: callable = None
        self.onprogress: callable = None
        self.readyState: int = 0
        self.result: str | ArrayBuffer | None = None

    def abort(self) -> None: ...

    def readAsArrayBuffer(self, blob: Blob) -> None: ...

    def readAsBinaryString(self, blob: Blob) -> None: ...

    def readAsDataURL(self, blob: Blob) -> None: ...

    def readAsText(self, blob: Blob, encoding: str | None = None) -> None: ...


@js(builtin=True)
class FileReaderSync:
    """WebIDL source: @webref/idl/FileAPI.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FileReaderSync

    Browser support: Chrome 7, Safari 6"""

    def __init__(self): ...

    def readAsArrayBuffer(self, blob: Blob) -> ArrayBuffer: ...

    def readAsBinaryString(self, blob: Blob) -> str: ...

    def readAsDataURL(self, blob: Blob) -> str: ...

    def readAsText(self, blob: Blob, encoding: str | None = None) -> str: ...


@js
class FilePropertyBag:
    """WebIDL source: @webref/idl/FileAPI.idl"""

    def __init__(
        self,
        endings: str = "transparent",
        lastModified: int | None = None,
        type: str = "",
    ):
        self.endings = endings
        self.lastModified = lastModified
        self.type = type


@js(builtin=True)
class File(Blob):
    """WebIDL source: @webref/idl/FileAPI.idl

    MDN: https://developer.mozilla.org/docs/Web/API/File

    Browser support: Chrome 13, Safari 4"""

    def __init__(
        self,
        fileBits: list[
            Int8Array
            | Int16Array
            | Int32Array
            | Uint8Array
            | Uint16Array
            | Uint32Array
            | Uint8ClampedArray
            | BigInt64Array
            | BigUint64Array
            | Float16Array
            | Float32Array
            | Float64Array
            | DataView
            | ArrayBuffer
            | Blob
            | str
        ],
        fileName: str,
        *,
        type: str = "",
        endings: str = "transparent",
        lastModified: int | None = None,
    ):
        super().__init__()
        self.lastModified: int = lastModified or 0
        self.name: str = fileName
