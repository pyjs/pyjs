"""WGSL types and builtins with CPU reference implementations."""

import math
from types import NotImplementedType
from typing import Self

from pyjs.decorators import wgsl
from pyjs.numeric import (
    NumericFormat,
    _FixedFloat,
    _FixedInteger,
    _StaticArrayBase,
)

__all__ = [
    "Array",
    "cross",
    "dot",
    "floor",
    "f32",
    "fract",
    "i32",
    "length",
    "sign",
    "step",
    "u32",
    "vec2f",
    "vec3f",
    "vec4f",
]


@wgsl
class Array[T, N](_StaticArrayBase):
    """A fixed-length WGSL array with a CPython reference implementation."""

    __slots__ = ()
    __pyjs_array_domain__ = "wgsl"


class _WGSLInteger(_FixedInteger):
    """Reference implementation of a concrete WGSL integer scalar."""

    __slots__ = ()

    @classmethod
    def _limits(cls) -> tuple[int, int]:
        return cls.__pyjs_numeric_format__.integer_bounds

    def __new__(cls, value: int | float = 0) -> Self:
        if isinstance(value, _FixedInteger):
            return cls._new_wrapped(int(value))
        if isinstance(value, bool):
            return int.__new__(cls, int(value))
        minimum, maximum = cls._limits()
        if isinstance(value, int):
            if not minimum <= value <= maximum:
                raise OverflowError(
                    f"{value} cannot be represented as WGSL {cls.__name__}"
                )
            return int.__new__(cls, value)
        if isinstance(value, float):
            if math.isnan(value):
                return int.__new__(cls, 0)
            return int.__new__(cls, int(min(max(value, minimum), maximum)))
        raise TypeError(f"{cls.__name__}() requires a scalar value")

    def _other(self, other: object) -> int | NotImplementedType:
        if isinstance(other, _FixedInteger):
            if type(other) is type(self):
                return int(other)
            return NotImplemented
        if isinstance(other, int):
            return int(type(self)(other))
        return NotImplemented

    @staticmethod
    def _truncated_division(left: int, right: int) -> int:
        quotient = abs(left) // abs(right)
        return -quotient if (left < 0) != (right < 0) else quotient

    def __truediv__(self, other: object) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        if other_value == 0:
            return self
        minimum, _maximum = type(self)._limits()
        if int(self) == minimum and other_value == -1:
            return self
        return type(self)._new_wrapped(self._truncated_division(int(self), other_value))

    def __rtruediv__(self, other: object) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        if int(self) == 0:
            return type(self)._new_wrapped(other_value)
        minimum, _maximum = type(self)._limits()
        if other_value == minimum and int(self) == -1:
            return type(self)._new_wrapped(other_value)
        return type(self)._new_wrapped(self._truncated_division(other_value, int(self)))

    def __mod__(self, other: object) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        if other_value == 0:
            return type(self)._new_wrapped(0)
        quotient = self._truncated_division(int(self), other_value)
        return type(self)._new_wrapped(int(self) - quotient * other_value)

    def __rmod__(self, other: object) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        if int(self) == 0:
            return type(self)._new_wrapped(0)
        quotient = self._truncated_division(other_value, int(self))
        return type(self)._new_wrapped(other_value - quotient * int(self))

    def __lshift__(self, other: object) -> Self | NotImplementedType:
        count = self._shift_count(other)
        if count is NotImplemented:
            return NotImplemented
        return type(self)._new_wrapped(int(self) << count)

    def __rshift__(self, other: object) -> Self | NotImplementedType:
        count = self._shift_count(other)
        if count is NotImplemented:
            return NotImplemented
        return type(self)._new_wrapped(int(self) >> count)

    @staticmethod
    def _shift_count(other: object) -> int | NotImplementedType:
        if isinstance(other, u32):
            return int(other) % 32
        if isinstance(other, int) and 0 <= other < 32:
            return other
        if isinstance(other, int):
            raise OverflowError("a WGSL shift literal must be between 0 and 31")
        return NotImplemented


class i32(_WGSLInteger):
    """WGSL signed 32-bit integer semantics."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat(
        "integer",
        32,
        True,
        domain="wgsl",
    )


class u32(_WGSLInteger):
    """WGSL unsigned 32-bit integer semantics."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat(
        "integer",
        32,
        False,
        domain="wgsl",
    )


class f32(_FixedFloat):
    """WGSL binary32 semantics with a CPython reference implementation."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat(
        "float",
        32,
        domain="wgsl",
    )

    @staticmethod
    def _quotient(left: float, right: float) -> float:
        if right != 0.0:
            return left / right
        if left == 0.0 or math.isnan(left):
            return math.nan
        negative = math.copysign(1.0, left) != math.copysign(1.0, right)
        return -math.inf if negative else math.inf

    def __truediv__(self, other: object) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return type(self)._new_rounded(self._quotient(float(self), other_value))

    def __rtruediv__(self, other: object) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return type(self)._new_rounded(self._quotient(other_value, float(self)))

    def __mod__(self, other: object) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        if other_value == 0.0 or math.isinf(float(self)):
            return type(self)._new_rounded(math.nan)
        return type(self)._new_rounded(math.fmod(float(self), other_value))

    def __rmod__(self, other: object) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        if float(self) == 0.0 or math.isinf(other_value):
            return type(self)._new_rounded(math.nan)
        return type(self)._new_rounded(math.fmod(other_value, float(self)))


@wgsl.native
class vec2f:
    # Avoid a per-vector dict in hot CPU loops.
    __slots__ = ("x", "y")

    x: f32
    y: f32

    def __init__(self, x: f32, y: f32) -> None:
        self.x = f32(x)
        self.y = f32(y)

    def __add__(self, other: vec2f) -> vec2f:
        return vec2f(self.x + other.x, self.y + other.y)

    def __sub__(self, other: vec2f) -> vec2f:
        return vec2f(self.x - other.x, self.y - other.y)

    def __mul__(self, k: f32) -> vec2f:
        return vec2f(self.x * k, self.y * k)

    def __truediv__(self, k: f32) -> vec2f:
        return vec2f(self.x / k, self.y / k)

    def __neg__(self) -> vec2f:
        return vec2f(-self.x, -self.y)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, vec2f) and self.x == other.x and self.y == other.y

    def __ne__(self, other: object) -> bool:
        return not self == other


@wgsl.native
class vec3f:
    __slots__ = ("x", "y", "z")

    x: f32
    y: f32
    z: f32

    def __init__(self, x: f32, y: f32, z: f32) -> None:
        self.x = f32(x)
        self.y = f32(y)
        self.z = f32(z)

    def __add__(self, other: vec3f) -> vec3f:
        return vec3f(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: vec3f) -> vec3f:
        return vec3f(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, k: f32) -> vec3f:
        return vec3f(self.x * k, self.y * k, self.z * k)

    def __truediv__(self, k: f32) -> vec3f:
        return vec3f(self.x / k, self.y / k, self.z / k)

    def __neg__(self) -> vec3f:
        return vec3f(-self.x, -self.y, -self.z)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, vec3f)
            and self.x == other.x
            and self.y == other.y
            and self.z == other.z
        )

    def __ne__(self, other: object) -> bool:
        return not self == other


@wgsl.native
class vec4f:
    __slots__ = ("x", "y", "z", "w")

    x: f32
    y: f32
    z: f32
    w: f32

    def __init__(self, x: f32, y: f32, z: f32, w: f32) -> None:
        self.x = f32(x)
        self.y = f32(y)
        self.z = f32(z)
        self.w = f32(w)

    def __add__(self, other: vec4f) -> vec4f:
        return vec4f(
            self.x + other.x, self.y + other.y, self.z + other.z, self.w + other.w
        )

    def __sub__(self, other: vec4f) -> vec4f:
        return vec4f(
            self.x - other.x, self.y - other.y, self.z - other.z, self.w - other.w
        )

    def __mul__(self, k: f32) -> vec4f:
        return vec4f(self.x * k, self.y * k, self.z * k, self.w * k)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, vec4f)
            and self.x == other.x
            and self.y == other.y
            and self.z == other.z
            and self.w == other.w
        )

    def __ne__(self, other: object) -> bool:
        return not self == other


@wgsl.native
def dot(a: vec3f, b: vec3f) -> f32:
    return f32(a.x * b.x + a.y * b.y + a.z * b.z)


@wgsl.native
def cross(a: vec3f, b: vec3f) -> vec3f:
    return vec3f(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)


@wgsl.native
def length(a: vec3f) -> f32:
    return f32(math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z))


@wgsl.native
def floor(x: f32) -> f32:
    """``floor`` returning float, as WGSL's does; ``math.floor`` returns int."""
    return f32(math.floor(x))


@wgsl.native
def fract(x: f32) -> f32:
    return f32(x - math.floor(x))


@wgsl.native
def step(edge: f32, x: f32) -> f32:
    return f32(1.0 if x >= edge else 0.0)


@wgsl.native
def sign(x: f32) -> f32:
    if x > 0.0:
        return f32(1.0)
    if x < 0.0:
        return f32(-1.0)
    return f32(0.0)
