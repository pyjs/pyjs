from pyjs import js
from pyjs.javascript import (
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
from pyjs.web.events import AbortSignal


@js(builtin=True)
class ByteLengthQueuingStrategy:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ByteLengthQueuingStrategy

    Browser support: Chrome 52, Safari 10.1"""

    def __init__(self, *, highWaterMark: float):
        self.highWaterMark: float = highWaterMark
        self.size: callable = None


@js(builtin=True)
class CountQueuingStrategy:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CountQueuingStrategy

    Browser support: Chrome 52, Safari 10.1"""

    def __init__(self, *, highWaterMark: float):
        self.highWaterMark: float = highWaterMark
        self.size: callable = None


@js
class QueuingStrategy:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(self, highWaterMark: float | None = None, size: callable | None = None):
        if highWaterMark is not None:
            self.highWaterMark = highWaterMark
        if size is not None:
            self.size = size


@js
class QueuingStrategyInit:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(self, highWaterMark: float):
        self.highWaterMark = highWaterMark


@js(builtin=True)
class ReadableByteStreamController:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ReadableByteStreamController

    Browser support: Chrome 89, Safari 26.4"""

    def __init__(self):
        self.byobRequest: ReadableStreamBYOBRequest | None = None
        self.desiredSize: float | None = None

    def close(self) -> None: ...

    def enqueue(
        self,
        chunk: Int8Array
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
        | DataView,
    ) -> None: ...

    def error(self, e: object | None = None) -> None: ...


@js(builtin=True)
class ReadableStream:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ReadableStream

    Browser support: Chrome 43, Safari 10.1"""

    def __init__(self, source: object | None = None, strategy: object | None = None):
        self.locked: bool = False

    async def cancel(self, reason: object | None = None) -> None: ...

    @staticmethod
    @js(inline="{self}.from({_args_joined})")
    def from_(asyncIterable: object) -> ReadableStream: ...

    def getReader(
        self, *, mode: str | None = None
    ) -> ReadableStreamDefaultReader | ReadableStreamBYOBReader: ...

    def pipeThrough(
        self,
        transform: ReadableWritablePair,
        *,
        preventClose: bool = False,
        preventAbort: bool = False,
        preventCancel: bool = False,
        signal: AbortSignal | None = None,
    ) -> ReadableStream: ...

    async def pipeTo(
        self,
        destination: WritableStream,
        *,
        preventClose: bool = False,
        preventAbort: bool = False,
        preventCancel: bool = False,
        signal: AbortSignal | None = None,
    ) -> None: ...

    def tee(self) -> list[ReadableStream]: ...


@js(builtin=True)
class ReadableStreamBYOBReader:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ReadableStreamBYOBReader

    Browser support: Chrome 89, Safari 26.4"""

    def __init__(self, stream: ReadableStream):
        self.closed: None = None

    async def cancel(self, reason: object | None = None) -> None: ...

    async def read(
        self,
        view: Int8Array
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
        | DataView,
        *,
        min: int = 1,
    ) -> ReadableStreamReadResult: ...

    def releaseLock(self) -> None: ...


@js
class ReadableStreamBYOBReaderReadOptions:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(self, min: int = 1):
        self.min = min


@js(builtin=True)
class ReadableStreamBYOBRequest:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ReadableStreamBYOBRequest

    Browser support: Chrome 89, Safari 26.4"""

    def __init__(self):
        self.view: Uint8Array | None = None

    def respond(self, bytesWritten: int) -> None: ...

    def respondWithNewView(
        self,
        view: Int8Array
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
        | DataView,
    ) -> None: ...


@js(builtin=True)
class ReadableStreamDefaultController:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ReadableStreamDefaultController

    Browser support: Chrome 52, Safari 10"""

    def __init__(self):
        self.desiredSize: float | None = None

    def close(self) -> None: ...

    def enqueue(self, chunk: object | None = None) -> None: ...

    def error(self, e: object | None = None) -> None: ...


@js(builtin=True)
class ReadableStreamDefaultReader:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ReadableStreamDefaultReader

    Browser support: Chrome 43, Safari 10"""

    def __init__(self, stream: ReadableStream):
        self.closed: None = None

    async def cancel(self, reason: object | None = None) -> None: ...

    async def read(self) -> ReadableStreamReadResult: ...

    def releaseLock(self) -> None: ...


@js
class ReadableStreamGetReaderOptions:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(self, mode: str | None = None):
        if mode is not None:
            self.mode = mode


@js
class ReadableStreamIteratorOptions:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(self, preventCancel: bool = False):
        self.preventCancel = preventCancel


@js
class ReadableStreamReadResult:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(self, done: bool | None = None, value: object | None = None):
        if done is not None:
            self.done = done
        if value is not None:
            self.value = value


@js
class ReadableWritablePair:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(self, readable: ReadableStream, writable: WritableStream):
        self.readable = readable
        self.writable = writable


@js
class StreamPipeOptions:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(
        self,
        preventAbort: bool = False,
        preventCancel: bool = False,
        preventClose: bool = False,
        signal: AbortSignal | None = None,
    ):
        self.preventAbort = preventAbort
        self.preventCancel = preventCancel
        self.preventClose = preventClose
        if signal is not None:
            self.signal = signal


@js
class Transformer:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(
        self,
        cancel: callable | None = None,
        flush: callable | None = None,
        readableType: object | None = None,
        start: callable | None = None,
        transform: callable | None = None,
        writableType: object | None = None,
    ):
        if cancel is not None:
            self.cancel = cancel
        if flush is not None:
            self.flush = flush
        if readableType is not None:
            self.readableType = readableType
        if start is not None:
            self.start = start
        if transform is not None:
            self.transform = transform
        if writableType is not None:
            self.writableType = writableType


@js(builtin=True)
class TransformStream:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TransformStream

    Browser support: Chrome 67, Safari 14.1"""

    def __init__(
        self,
        transformer: object | None = None,
        writableStrategy: QueuingStrategy | None = None,
        *,
        highWaterMark: float | None = None,
        size: callable | None = None,
    ):
        self.readable: ReadableStream = None
        self.writable: WritableStream = None


@js(builtin=True)
class TransformStreamDefaultController:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TransformStreamDefaultController

    Browser support: Chrome 67, Safari 14.1"""

    def __init__(self):
        self.desiredSize: float | None = None

    def enqueue(self, chunk: object | None = None) -> None: ...

    def error(self, reason: object | None = None) -> None: ...

    def terminate(self) -> None: ...


@js
class UnderlyingSink:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(
        self,
        abort: callable | None = None,
        close: callable | None = None,
        start: callable | None = None,
        type: object | None = None,
        write: callable | None = None,
    ):
        if abort is not None:
            self.abort = abort
        if close is not None:
            self.close = close
        if start is not None:
            self.start = start
        if type is not None:
            self.type = type
        if write is not None:
            self.write = write


@js
class UnderlyingSource:
    """WebIDL source: @webref/idl/streams.idl"""

    def __init__(
        self,
        autoAllocateChunkSize: int | None = None,
        cancel: callable | None = None,
        pull: callable | None = None,
        start: callable | None = None,
        type: str | None = None,
    ):
        if autoAllocateChunkSize is not None:
            self.autoAllocateChunkSize = autoAllocateChunkSize
        if cancel is not None:
            self.cancel = cancel
        if pull is not None:
            self.pull = pull
        if start is not None:
            self.start = start
        if type is not None:
            self.type = type


@js(builtin=True)
class WritableStream:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WritableStream

    Browser support: Chrome 59, Safari 14.1"""

    def __init__(
        self,
        underlyingSink: object | None = None,
        *,
        highWaterMark: float | None = None,
        size: callable | None = None,
    ):
        self.locked: bool = False

    async def abort(self, reason: object | None = None) -> None: ...

    async def close(self) -> None: ...

    def getWriter(self) -> WritableStreamDefaultWriter: ...


@js(builtin=True)
class WritableStreamDefaultController:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WritableStreamDefaultController

    Browser support: Chrome 59, Safari 14.1"""

    def __init__(self):
        self.signal: AbortSignal = None

    def error(self, e: object | None = None) -> None: ...


@js(builtin=True)
class WritableStreamDefaultWriter:
    """WebIDL source: @webref/idl/streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WritableStreamDefaultWriter

    Browser support: Chrome 59, Safari 14.1"""

    def __init__(self, stream: WritableStream):
        self.closed: None = None
        self.desiredSize: float | None = None
        self.ready: None = None

    async def abort(self, reason: object | None = None) -> None: ...

    async def close(self) -> None: ...

    def releaseLock(self) -> None: ...

    async def write(self, chunk: object | None = None) -> None: ...
