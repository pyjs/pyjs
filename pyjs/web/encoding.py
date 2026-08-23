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
    SharedArrayBuffer,
    Uint8Array,
    Uint8ClampedArray,
    Uint16Array,
    Uint32Array,
)


@js.dictionary
class TextDecodeOptions:
    """WebIDL source: @webref/idl/encoding.idl"""

    def __init__(self, stream: bool = False):
        self.stream = stream


@js.native
class TextDecoder:
    """WebIDL source: @webref/idl/encoding.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextDecoder

    Browser support: Chrome 38, Safari 10.1"""

    def __init__(
        self, label: str = "utf-8", *, fatal: bool = False, ignoreBOM: bool = False
    ):
        self.encoding: str = ""
        self.fatal: bool = fatal
        self.ignoreBOM: bool = ignoreBOM

    def decode(
        self,
        input: ArrayBuffer
        | SharedArrayBuffer
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
        | None = None,
        *,
        stream: bool = False,
    ) -> str: ...


@js.dictionary
class TextDecoderOptions:
    """WebIDL source: @webref/idl/encoding.idl"""

    def __init__(self, fatal: bool = False, ignoreBOM: bool = False):
        self.fatal = fatal
        self.ignoreBOM = ignoreBOM


@js.native
class TextDecoderStream:
    """WebIDL source: @webref/idl/encoding.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextDecoderStream

    Browser support: Chrome 71, Safari 14.1"""

    def __init__(
        self, label: str = "utf-8", *, fatal: bool = False, ignoreBOM: bool = False
    ):
        self.encoding: str = ""
        self.fatal: bool = fatal
        self.ignoreBOM: bool = ignoreBOM


@js.native
class TextEncoder:
    """WebIDL source: @webref/idl/encoding.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextEncoder

    Browser support: Chrome 38, Safari 10.1"""

    def __init__(self):
        self.encoding: str = ""

    def encode(self, input: str = "") -> Uint8Array: ...

    def encodeInto(
        self, source: str, destination: Uint8Array
    ) -> TextEncoderEncodeIntoResult: ...


@js.dictionary
class TextEncoderEncodeIntoResult:
    """WebIDL source: @webref/idl/encoding.idl"""

    def __init__(self, read: int | None = None, written: int | None = None):
        self.read = read
        self.written = written


@js.native
class TextEncoderStream:
    """WebIDL source: @webref/idl/encoding.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextEncoderStream

    Browser support: Chrome 71, Safari 14.1"""

    def __init__(self):
        self.encoding: str = ""
