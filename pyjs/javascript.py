import json
import random
import time
from datetime import UTC, datetime
from typing import TypedDict

from pyjs import js


@js.native
class ArrayBuffer:
    def __init__(self, length: int):
        self.byteLength: int = length
        self.maxByteLength: int = length
        self.resizable: bool = False

    @staticmethod
    def isView(value: object) -> bool: ...

    def slice(self, begin: int = 0, end: int | None = None) -> ArrayBuffer: ...


@js.native
class SharedArrayBuffer:
    def __init__(self, length: int):
        self.byteLength: int = length
        self.growable: bool = False
        self.maxByteLength: int = length

    def grow(self, newLength: int) -> None: ...

    def slice(self, begin: int = 0, end: int | None = None) -> SharedArrayBuffer: ...


@js.native
class DataView:
    def __init__(
        self,
        buffer: ArrayBuffer,
        byteOffset: int = 0,
        byteLength: int | None = None,
    ):
        self.buffer: ArrayBuffer = buffer
        self.byteLength: int = byteLength or 0
        self.byteOffset: int = byteOffset


@js.native
class TypedArray:
    def __init__(self, values: object):
        self.buffer: ArrayBuffer = ArrayBuffer(0)
        self.byteLength: int = 0
        self.byteOffset: int = 0
        self.length: int = 0

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> int | float: ...

    @js.inline("{self}[{index}] = {value}")
    def __setitem__(self, index: int, value: int | float) -> None: ...

    @js.inline("{self}.length")
    def __len__(self) -> int: ...

    def set(self, values: object, offset: int = 0) -> None: ...

    def slice(self, start: int = 0, end: int | None = None) -> TypedArray: ...

    def subarray(self, begin: int = 0, end: int | None = None) -> TypedArray: ...


@js.native
class BigInt64Array(TypedArray): ...


@js.native
class BigUint64Array(TypedArray): ...


@js.native
class Float16Array(TypedArray): ...


@js.native
class Float32Array(TypedArray): ...


@js.native
class Float64Array(TypedArray): ...


@js.native
class Int8Array(TypedArray): ...


@js.native
class Int16Array(TypedArray): ...


@js.native
class Int32Array(TypedArray): ...


@js.native
class Uint8Array(TypedArray): ...


@js.native
class Uint8ClampedArray(TypedArray): ...


@js.native
class Uint16Array(TypedArray): ...


@js.native
class Uint32Array(TypedArray): ...


@js.native
class Date:
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

    def toLocaleDateString(self) -> str:
        return self._datetime.astimezone().strftime("%x")


@js.native
class Math:
    @staticmethod
    def random() -> float:
        return random.random()


class JSONObject(TypedDict):
    pass


@js.inline("JSON.stringify({value})")
def _stringify_unchecked(value: object) -> str:
    return json.dumps(value, default=vars, separators=(",", ":"))


@js.native
class JSON:
    @staticmethod
    def parse[T: JSONObject | list[JSONObject]](value: str) -> T:
        return json.loads(value)

    @staticmethod
    def stringify(value: JSONObject | list[JSONObject]) -> str:
        return _stringify_unchecked(value)


@js.native
def encodeURIComponent(value: str) -> str: ...
