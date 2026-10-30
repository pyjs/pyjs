"""Typed ECMAScript APIs shared by JavaScript targets."""

import json
import random
import time
from datetime import UTC, datetime
from typing import TypedDict
from urllib.parse import quote

from pyjs import js
from pyjs.decorators import configure_js

__all__ = [
    "ArrayBuffer",
    "BigInt64Array",
    "BigUint64Array",
    "DataView",
    "Date",
    "Float16Array",
    "Float32Array",
    "Float64Array",
    "Int8Array",
    "Int16Array",
    "Int32Array",
    "JSON",
    "JSONObject",
    "Math",
    "SharedArrayBuffer",
    "TypedArray",
    "Uint8Array",
    "Uint8ClampedArray",
    "Uint16Array",
    "Uint32Array",
    "encodeURIComponent",
]


@js.native
class ArrayBuffer:
    """Fixed-length or resizable raw binary data buffer."""
    def __init__(self, length: int):
        if length < 0:
            raise ValueError("ArrayBuffer length cannot be negative")
        self.byteLength: int = length
        self.maxByteLength: int = length
        self.resizable: bool = False
        allocate_buffer(self, length)

    @staticmethod
    def isView(value: object) -> bool:
        return isinstance(value, (DataView, TypedArray))

    def slice(self, begin: int = 0, end: int | None = None) -> ArrayBuffer:
        start, stop, _step = slice(begin, end).indices(self.byteLength)
        result = ArrayBuffer(max(0, stop - start))
        result._bytes[:] = self._bytes[start:stop]
        return result


@js.native
class SharedArrayBuffer:
    """Raw binary data buffer shared between JavaScript agents."""
    def __init__(self, length: int):
        if length < 0:
            raise ValueError("SharedArrayBuffer length cannot be negative")
        self.byteLength: int = length
        self.growable: bool = False
        self.maxByteLength: int = length
        allocate_buffer(self, length)

    def grow(self, newLength: int) -> None: ...

    def slice(self, begin: int = 0, end: int | None = None) -> SharedArrayBuffer:
        start, stop, _step = slice(begin, end).indices(self.byteLength)
        result = SharedArrayBuffer(max(0, stop - start))
        result._bytes[:] = self._bytes[start:stop]
        return result


@js.native
class DataView:
    """Low-level view over an array buffer."""
    def __init__(
        self,
        buffer: ArrayBuffer | SharedArrayBuffer,
        byteOffset: int = 0,
        byteLength: int | None = None,
    ):
        if byteOffset < 0 or byteOffset > buffer.byteLength or (
            byteLength is not None
            and (byteLength < 0 or byteOffset + byteLength > buffer.byteLength)
        ):
            raise ValueError("DataView range is outside its buffer")
        self.buffer: ArrayBuffer | SharedArrayBuffer = buffer
        self.byteLength: int = (
            buffer.byteLength - byteOffset if byteLength is None else byteLength
        )
        self.byteOffset: int = byteOffset


@js.native
class TypedArray:
    """Base interface shared by JavaScript typed arrays."""

    _format = "f"
    _kind = "float"
    _size = 4
    BYTES_PER_ELEMENT = 4

    def __init__(
        self,
        values: object = 0,
        byteOffset: int = 0,
        length: int | None = None,
    ):
        self.buffer: ArrayBuffer | SharedArrayBuffer = ArrayBuffer(0)
        self.byteLength: int = 0
        self.byteOffset: int = 0
        self.length: int = 0
        fill_typed_array(self, values, byteOffset, length)

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> int | float:
        return read_typed_array_item(self, index)

    @js.inline("{self}[{index}] = {value}")
    def __setitem__(self, index: int, value: int | float) -> None:
        write_typed_array_item(self, index, value)

    @js.inline("{self}.length")
    def __len__(self) -> int:
        return self.length

    def set(self, values: object, offset: int = 0) -> None:
        items = typed_array_values(values)
        if offset < 0 or offset + len(items) > self.length:
            raise ValueError("typed array set range is outside the destination")
        for index, value in enumerate(items, offset):
            write_typed_array_item(self, index, value)

    def slice(self, start: int = 0, end: int | None = None) -> TypedArray:
        first, stop, _step = slice(start, end).indices(self.length)
        return type(self)([
            read_typed_array_item(self, index) for index in range(first, stop)
        ])

    def subarray(self, begin: int = 0, end: int | None = None) -> TypedArray:
        first, stop, _step = slice(begin, end).indices(self.length)
        return type(self)(
            self.buffer,
            self.byteOffset + first * self._size,
            max(0, stop - first),
        )


@js.native
class BigInt64Array(TypedArray):
    _format = "q"
    _kind = "signed"
    _size = 8
    BYTES_PER_ELEMENT = 8


@js.native
class BigUint64Array(TypedArray):
    _format = "Q"
    _kind = "unsigned"
    _size = 8
    BYTES_PER_ELEMENT = 8


@js.native
class Float16Array(TypedArray):
    _format = "e"
    _kind = "float"
    _size = 2
    BYTES_PER_ELEMENT = 2


@js.native
class Float32Array(TypedArray):
    _format = "f"
    _kind = "float"
    _size = 4
    BYTES_PER_ELEMENT = 4


@js.native
class Float64Array(TypedArray):
    _format = "d"
    _kind = "float"
    _size = 8
    BYTES_PER_ELEMENT = 8


@js.native
class Int8Array(TypedArray):
    _format = "b"
    _kind = "signed"
    _size = 1
    BYTES_PER_ELEMENT = 1


@js.native
class Int16Array(TypedArray):
    _format = "h"
    _kind = "signed"
    _size = 2
    BYTES_PER_ELEMENT = 2


@js.native
class Int32Array(TypedArray):
    _format = "i"
    _kind = "signed"
    _size = 4
    BYTES_PER_ELEMENT = 4


@js.native
class Uint8Array(TypedArray):
    _format = "B"
    _kind = "unsigned"
    _size = 1
    BYTES_PER_ELEMENT = 1


@js.native
class Uint8ClampedArray(TypedArray):
    _format = "B"
    _kind = "clamped"
    _size = 1
    BYTES_PER_ELEMENT = 1


@js.native
class Uint16Array(TypedArray):
    _format = "H"
    _kind = "unsigned"
    _size = 2
    BYTES_PER_ELEMENT = 2


@js.native
class Uint32Array(TypedArray):
    _format = "I"
    _kind = "unsigned"
    _size = 4
    BYTES_PER_ELEMENT = 4


@js.native
def allocate_buffer(buffer: object, length: int) -> None:
    buffer._bytes = bytearray(length)


@js.native
def fill_typed_array(
    array: object,
    values: object,
    byte_offset: int,
    length: int | None,
) -> None:
    import struct

    if isinstance(values, int):
        if values < 0:
            raise ValueError("typed array length cannot be negative")
        if byte_offset != 0 or length is not None:
            raise TypeError("byteOffset and length require an array buffer")
        array.length = values
        array.buffer = ArrayBuffer(values * array._size)
    elif isinstance(values, (ArrayBuffer, SharedArrayBuffer)):
        if byte_offset < 0 or byte_offset % array._size:
            raise ValueError("typed array byteOffset is not aligned")
        if byte_offset > values.byteLength:
            raise ValueError("typed array byteOffset is outside its buffer")
        remaining = values.byteLength - byte_offset
        if length is None:
            if remaining % array._size:
                raise ValueError("buffer byte length is not aligned for this typed array")
            array.length = remaining // array._size
        else:
            if length < 0 or length * array._size > remaining:
                raise ValueError("typed array length is outside its buffer")
            array.length = length
        array.buffer = values
        array.byteOffset = byte_offset
    else:
        if byte_offset != 0 or length is not None:
            raise TypeError("byteOffset and length require an array buffer")
        items = typed_array_values(values)
        array.length = len(items)
        array.buffer = ArrayBuffer(array.length * array._size)
        converted = [coerce_typed_array_item(array, item) for item in items]
        struct.pack_into(
            f"<{array.length}{array._format}",
            array.buffer._bytes,
            0,
            *converted,
        )
    array.byteLength = array.length * array._size


@js.native
def coerce_typed_array_item(array: object, value: object) -> object:
    import math
    import struct

    kind = array._kind
    if kind == "float":
        number = float(value)
        if array._size < 8 and math.isfinite(number):
            try:
                struct.pack(f"<{array._format}", number)
            except OverflowError:
                return math.copysign(math.inf, number)
        return number
    if kind == "clamped":
        number = float(value)
        if math.isnan(number) or number <= 0:
            return 0
        if number >= 255:
            return 255
        return round(number)
    if isinstance(value, float) and not math.isfinite(value):
        converted = 0
    else:
        converted = int(value)
    bits = array._size * 8
    converted &= (1 << bits) - 1
    if kind == "signed" and converted >= 1 << (bits - 1):
        converted -= 1 << bits
    return converted


@js.native
def typed_array_values(values: object) -> list[object]:
    if isinstance(values, TypedArray):
        return [read_typed_array_item(values, index) for index in range(values.length)]
    return list(values)


@js.native
def read_typed_array_item(array: object, index: int) -> object:
    import struct

    if index < 0 or index >= array.length:
        raise IndexError("typed array index out of range")
    offset = array.byteOffset + index * array._size
    return struct.unpack_from(f"<{array._format}", array.buffer._bytes, offset)[0]


@js.native
def write_typed_array_item(array: object, index: int, value: object) -> None:
    import struct

    if index < 0 or index >= array.length:
        raise IndexError("typed array index out of range")
    offset = array.byteOffset + index * array._size
    struct.pack_into(
        f"<{array._format}",
        array.buffer._bytes,
        offset,
        coerce_typed_array_item(array, value),
    )


@js.native
def typed_array_bytes(array: object) -> object:
    start = array.byteOffset
    return bytes(array.buffer._bytes[start:start + array.byteLength])


@js.native
class Date:
    """JavaScript date with a CPython implementation for SSR and tests."""
    def __init__(self, value: int | str | None = None):
        if value is None:
            self._datetime = datetime.now(UTC)
        elif isinstance(value, str):
            self._datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            self._datetime = datetime.fromtimestamp(value / 1_000, UTC)

    @staticmethod
    def now() -> int:
        return time.time_ns() // 1_000_000

    def toISOString(self) -> str:
        return self._datetime.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def getMonth(self) -> int:
        return self._datetime.astimezone().month - 1

    def getDate(self) -> int:
        return self._datetime.astimezone().day

    def getFullYear(self) -> int:
        return self._datetime.astimezone().year

    def getHours(self) -> int:
        return self._datetime.astimezone().hour

    def getMinutes(self) -> int:
        return self._datetime.astimezone().minute

    def toLocaleDateString(self) -> str:
        return self._datetime.astimezone().strftime("%x")


@js.native
class Math:
    """JavaScript mathematical APIs not supplied by Python modules."""
    @staticmethod
    def random() -> float:
        return random.random()


class JSONObject(TypedDict):
    """Statically declared plain object accepted by JSON operations."""
    pass


type JSONScalar = str | bool | int | float | None


@js.inline("JSON.stringify({value})")
def _stringify_unchecked(value: object) -> str:
    return json.dumps(value, default=vars, separators=(",", ":"))


@js.native
class JSON:
    """Parse typed object records and serialize JSON-compatible values."""
    @staticmethod
    def parse[T: JSONObject | list[JSONObject]](value: str) -> T:
        return json.loads(value)

    @staticmethod
    @js.inline("JSON.stringify(({value}) ?? null)")
    def stringify(value: JSONObject | list[JSONObject] | JSONScalar | list[JSONScalar]) -> str:
        return _stringify_unchecked(value)


def _analyze_stringify(call):
    import ast

    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.value_representation import analyzed_representation

    call.visitor.validate_call_shape(call.node, call.function)
    if any(isinstance(value, ast.Starred) for value in call.node.args):
        call.visitor.fail(
            call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            "JSON.stringify requires one explicit value argument",
        )
    result = call.standard()
    value = result.args[0] if result.args else result.keywords[0].value
    representation = analyzed_representation(value)
    if representation is not None and any(
        numeric.kind == "integer" and numeric.bits == 64
        for numeric in representation.numeric_formats
    ):
        call.visitor.fail(
            call.node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            "JSON.stringify cannot serialize int64 values as JavaScript BigInt",
            help="Convert int64 values to strings, or explicitly to int within the safe integer range.",
        )
    # Native keyword calls normally build an options object; JSON takes a value.
    result.args = [value]
    result.keywords = []
    return result


def _stringify_value(value: JSONObject | list[JSONObject] | JSONScalar | list[JSONScalar]) -> str:
    return JSON.stringify(value)


JSON.stringify.value(_stringify_value)
configure_js(JSON.stringify, analysis=_analyze_stringify)


@js.native
def encodeURIComponent(value: str) -> str:
    return quote(value, safe="-_.!~*'()")
