from pyjs import js
from pyjs.web.events import EventTarget
from pyjs.web.files import Blob
from pyjs.web.javascript import (
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
from pyjs.web.streams import ReadableStream
from pyjs.web.url import URLSearchParams


@js(builtin=True)
class FormData:
    """WebIDL source: @webref/idl/xhr.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FormData

    Browser support: Chrome 5, Safari 5"""

    pass


@js(builtin=True)
class Headers:
    """WebIDL source: @webref/idl/fetch.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Headers

    Browser support: Chrome 42, Safari 10.1"""

    pass


@js(builtin=True)
class Response:
    """WebIDL source: @webref/idl/fetch.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Response

    Browser support: Chrome 42, Safari 10.1"""

    def __init__(
        self,
        body: ReadableStream
        | Blob
        | Int8Array
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
        | FormData
        | URLSearchParams
        | str
        | None = None,
        *,
        status: int = 200,
        statusText: str = "",
        headers: list[list[str]] | dict[str, str] | None = None,
    ):
        self.body: ReadableStream | None = body
        self.bodyUsed: bool = False
        self.headers: Headers = headers
        self.ok: bool = False
        self.redirected: bool = False
        self.status: int = status
        self.statusText: str = statusText
        self.type: str = ""
        self.url: str = ""

    async def arrayBuffer(self) -> ArrayBuffer: ...

    async def blob(self) -> Blob: ...

    async def bytes(self) -> Uint8Array: ...

    def clone(self) -> Response: ...

    @staticmethod
    def error() -> Response: ...

    async def formData(self) -> FormData: ...

    @staticmethod
    def json(
        data: object,
        *,
        status: int = 200,
        statusText: str = "",
        headers: list[list[str]] | dict[str, str] | None = None,
    ) -> Response: ...

    @staticmethod
    def redirect(url: str, status: int = 302) -> Response: ...

    async def text(self) -> str: ...

    def textStream(self) -> ReadableStream: ...


@js
class ResponseInit:
    """WebIDL source: @webref/idl/fetch.idl"""

    def __init__(
        self,
        headers: list[list[str]] | dict[str, str] | None = None,
        status: int = 200,
        statusText: str = "",
    ):
        self.headers = headers
        self.status = status
        self.statusText = statusText


@js(builtin=True)
class WebSocket(EventTarget):
    """WebIDL source: @webref/idl/websockets.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WebSocket

    Browser support: Chrome 5, Safari 5"""

    CLOSED = 3
    CLOSING = 2
    CONNECTING = 0
    OPEN = 1

    def __init__(self, url: str, protocols: str | list[str] | None = None):
        super().__init__()
        self.binaryType: str = ""
        self.bufferedAmount: int = 0
        self.extensions: str = ""
        self.onclose: callable = None
        self.onerror: callable = None
        self.onmessage: callable = None
        self.onopen: callable = None
        self.protocol: str = ""
        self.readyState: int = 0
        self.url: str = url

    def close(self, code: int | None = None, reason: str | None = None) -> None: ...

    def send(
        self,
        data: Int8Array
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
        | str,
    ) -> None: ...


def rewrite_fetch(_arg_strs, **kwargs):
    if len(_arg_strs) == 1:
        return f"fetch({_arg_strs[0]})"
    options = _arg_strs[1]
    return f"fetch({_arg_strs[0]}, (options => options instanceof Map ? Object.fromEntries(options) : options)({options}))"


@js(builtin=True, inline=rewrite_fetch)
async def fetch(url: str, options: object | None = None) -> Response: ...
