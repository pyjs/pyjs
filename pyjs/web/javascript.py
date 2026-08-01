from pyjs import js


@js(builtin=True)
class ArrayBuffer:
    def __init__(self, length: int):
        self.byteLength: int = length
        self.maxByteLength: int = length
        self.resizable: bool = False

    @staticmethod
    def isView(value: object) -> bool: ...

    def slice(self, begin: int = 0, end: int | None = None) -> ArrayBuffer: ...


@js(builtin=True)
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


@js(builtin=True)
class TypedArray:
    def __init__(self, values: object):
        self.buffer: ArrayBuffer = ArrayBuffer(0)
        self.byteLength: int = 0
        self.byteOffset: int = 0
        self.length: int = 0

    @js(inline="{self}[{index}]")
    def __getitem__(self, index: int) -> int | float: ...

    @js(inline="{self}[{index}] = {value}")
    def __setitem__(self, index: int, value: int | float) -> None: ...

    @js(inline="{self}.length")
    def __len__(self) -> int: ...

    def set(self, values: object, offset: int = 0) -> None: ...

    def slice(self, start: int = 0, end: int | None = None) -> TypedArray: ...

    def subarray(self, begin: int = 0, end: int | None = None) -> TypedArray: ...


@js(builtin=True)
class BigInt64Array(TypedArray): ...


@js(builtin=True)
class BigUint64Array(TypedArray): ...


@js(builtin=True)
class Float16Array(TypedArray): ...


@js(builtin=True)
class Float32Array(TypedArray): ...


@js(builtin=True)
class Float64Array(TypedArray): ...


@js(builtin=True)
class Int8Array(TypedArray): ...


@js(builtin=True)
class Int16Array(TypedArray): ...


@js(builtin=True)
class Int32Array(TypedArray): ...


@js(builtin=True)
class Uint8Array(TypedArray): ...


@js(builtin=True)
class Uint8ClampedArray(TypedArray): ...


@js(builtin=True)
class Uint16Array(TypedArray): ...


@js(builtin=True)
class Uint32Array(TypedArray): ...


@js(builtin=True)
class JSON:
    @staticmethod
    def parse(value: str) -> object: ...

    @staticmethod
    def stringify(value: object) -> str: ...


@js(builtin=True)
def encodeURIComponent(value: str) -> str: ...
