from pyjs import js
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
from pyjs.web.dom import Document
from pyjs.web.events import AbortSignal, Event, EventTarget
from pyjs.web.files import Blob, File
from pyjs.web.html import HTMLElement, HTMLFormElement
from pyjs.web.streams import ReadableStream
from pyjs.web.url import URLSearchParams


@js(builtin=True)
class CloseEvent(Event):
    """WebIDL source: @webref/idl/websockets.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CloseEvent

    Browser support: Chrome 15, Safari 6"""

    def __init__(
        self, type: str, *, wasClean: bool = False, code: int = 0, reason: str = ""
    ):
        super().__init__()
        self.code: int = code
        self.reason: str = reason
        self.wasClean: bool = wasClean


@js
class CloseEventInit:
    """WebIDL source: @webref/idl/websockets.idl"""

    def __init__(self, code: int = 0, reason: str = "", wasClean: bool = False):
        self.code = code
        self.reason = reason
        self.wasClean = wasClean


@js(builtin=True)
class FetchLaterResult:
    """WebIDL source: @webref/idl/fetch.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FetchLaterResult

    Browser support: Chrome 135"""

    def __init__(self):
        self.activated: bool = False


@js(builtin=True)
class FormData:
    """WebIDL source: @webref/idl/xhr.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FormData

    Browser support: Chrome 5, Safari 5"""

    pass

    def __init__(
        self, form: HTMLFormElement | None = None, submitter: HTMLElement | None = None
    ): ...

    def append(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...

    def get(self, name: str) -> File | str | None: ...

    def getAll(self, name: str) -> list[File | str]: ...

    def has(self, name: str) -> bool: ...

    def set(self, name: str, value: str) -> None: ...


@js(builtin=True)
class Headers:
    """WebIDL source: @webref/idl/fetch.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Headers

    Browser support: Chrome 42, Safari 10.1"""

    pass

    def __init__(self, init: list[list[str]] | dict[str, str] | None = None): ...

    def append(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...

    def get(self, name: str) -> str | None: ...

    def getSetCookie(self) -> list[str]: ...

    def has(self, name: str) -> bool: ...

    def set(self, name: str, value: str) -> None: ...


@js
class PrivateToken:
    """WebIDL source: @webref/idl/trust-token-api.idl"""

    def __init__(
        self,
        operation: str,
        version: str,
        issuers: list[str] | None = None,
        refreshPolicy: str = "none",
    ):
        self.operation = operation
        self.version = version
        self.issuers = issuers
        self.refreshPolicy = refreshPolicy


@js(builtin=True)
class Request:
    """WebIDL source: @webref/idl/fetch.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Request

    Browser support: Chrome 42, Safari 10.1"""

    def __init__(
        self,
        input: Request | str,
        *,
        method: str | None = None,
        headers: list[list[str]] | dict[str, str] | None = None,
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
        referrer: str | None = None,
        referrerPolicy: str | None = None,
        mode: str | None = None,
        credentials: str | None = None,
        cache: str | None = None,
        redirect: str | None = None,
        integrity: str | None = None,
        keepalive: bool | None = None,
        signal: AbortSignal | None = None,
        duplex: str | None = None,
        priority: str | None = None,
        window: object | None = None,
        targetAddressSpace: str | None = None,
        privateToken: PrivateToken | None = None,
    ):
        self.body: ReadableStream | None = body
        self.bodyUsed: bool = False
        self.cache: str = cache
        self.credentials: str = credentials
        self.destination: str = ""
        self.duplex: str = duplex
        self.headers: Headers = headers
        self.integrity: str = integrity
        self.isHistoryNavigation: bool = False
        self.isReloadNavigation: bool = False
        self.keepalive: bool = keepalive
        self.method: str = method
        self.mode: str = mode
        self.redirect: str = redirect
        self.referrer: str = referrer
        self.referrerPolicy: str = referrerPolicy
        self.signal: AbortSignal = signal
        self.targetAddressSpace: str = targetAddressSpace
        self.url: str = ""

    async def arrayBuffer(self) -> ArrayBuffer: ...

    async def blob(self) -> Blob: ...

    async def bytes(self) -> Uint8Array: ...

    def clone(self) -> Request: ...

    async def formData(self) -> FormData: ...

    async def json(self) -> object: ...

    async def text(self) -> str: ...

    def textStream(self) -> ReadableStream: ...


@js
class RequestInit:
    """WebIDL source: @webref/idl/fetch.idl"""

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
        cache: str | None = None,
        credentials: str | None = None,
        duplex: str | None = None,
        headers: list[list[str]] | dict[str, str] | None = None,
        integrity: str | None = None,
        keepalive: bool | None = None,
        method: str | None = None,
        mode: str | None = None,
        priority: str | None = None,
        privateToken: PrivateToken | None = None,
        redirect: str | None = None,
        referrer: str | None = None,
        referrerPolicy: str | None = None,
        signal: AbortSignal | None = None,
        targetAddressSpace: str | None = None,
        window: object | None = None,
    ):
        self.body = body
        self.cache = cache
        self.credentials = credentials
        self.duplex = duplex
        self.headers = headers
        self.integrity = integrity
        self.keepalive = keepalive
        self.method = method
        self.mode = mode
        self.priority = priority
        self.privateToken = privateToken
        self.redirect = redirect
        self.referrer = referrer
        self.referrerPolicy = referrerPolicy
        self.signal = signal
        self.targetAddressSpace = targetAddressSpace
        self.window = window


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


@js(builtin=True)
class XMLHttpRequestEventTarget(EventTarget):
    """WebIDL source: @webref/idl/xhr.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XMLHttpRequestEventTarget

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.onabort: callable = None
        self.onerror: callable = None
        self.onload: callable = None
        self.onloadend: callable = None
        self.onloadstart: callable = None
        self.onprogress: callable = None
        self.ontimeout: callable = None


@js
class DeferredRequestInit:
    """WebIDL source: @webref/idl/fetch.idl"""

    def __init__(
        self,
        activateAfter: float | None = None,
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
        cache: str | None = None,
        credentials: str | None = None,
        duplex: str | None = None,
        headers: list[list[str]] | dict[str, str] | None = None,
        integrity: str | None = None,
        keepalive: bool | None = None,
        method: str | None = None,
        mode: str | None = None,
        priority: str | None = None,
        redirect: str | None = None,
        referrer: str | None = None,
        referrerPolicy: str | None = None,
        signal: AbortSignal | None = None,
        window: object | None = None,
    ):
        if activateAfter is not None:
            self.activateAfter = activateAfter
        if body is not None:
            self.body = body
        if cache is not None:
            self.cache = cache
        if credentials is not None:
            self.credentials = credentials
        if duplex is not None:
            self.duplex = duplex
        if headers is not None:
            self.headers = headers
        if integrity is not None:
            self.integrity = integrity
        if keepalive is not None:
            self.keepalive = keepalive
        if method is not None:
            self.method = method
        if mode is not None:
            self.mode = mode
        if priority is not None:
            self.priority = priority
        if redirect is not None:
            self.redirect = redirect
        if referrer is not None:
            self.referrer = referrer
        if referrerPolicy is not None:
            self.referrerPolicy = referrerPolicy
        if signal is not None:
            self.signal = signal
        if window is not None:
            self.window = window


@js(builtin=True)
class XMLHttpRequest(XMLHttpRequestEventTarget):
    """WebIDL source: @webref/idl/xhr.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XMLHttpRequest

    Browser support: Chrome 1, Safari 1.2"""

    DONE = 4
    HEADERS_RECEIVED = 2
    LOADING = 3
    OPENED = 1
    UNSENT = 0

    def __init__(self):
        super().__init__()
        self.onreadystatechange: callable = None
        self.readyState: int = 0
        self.response: object = None
        self.responseText: str = ""
        self.responseType: str = ""
        self.responseURL: str = ""
        self.responseXML: Document | None = None
        self.status: int = 0
        self.statusText: str = ""
        self.timeout: int = 0
        self.upload: XMLHttpRequestUpload = None
        self.withCredentials: bool = False

    def abort(self) -> None: ...

    def getAllResponseHeaders(self) -> str: ...

    def getResponseHeader(self, name: str) -> str | None: ...

    def open(self, method: str, url: str) -> None: ...

    def overrideMimeType(self, mime: str) -> None: ...

    def send(
        self,
        body: Document
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
    ) -> None: ...

    def setRequestHeader(self, name: str, value: str) -> None: ...


@js(builtin=True)
class XMLHttpRequestUpload(XMLHttpRequestEventTarget):
    """WebIDL source: @webref/idl/xhr.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XMLHttpRequestUpload

    Browser support: Chrome 2, Safari 4"""

    pass
