"""Portable numeric types and their compilation contract.

PyJS has four deliberately separate numeric domains. Types from different
domains never convert implicitly, even when they have the same physical
representation.

| Domain | Names | General backends | WGSL |
| --- | --- | --- | --- |
| Python | Built-ins and ``Decimal`` | Python semantics | Rejected |
| Portable | Root fixed-width types | Fixed semantics | Rejected |
| WGSL | ``pyjs.shader`` types | WGSL emulation | Native |
| Target | A backend module's types | Owning target only | Rejected |

The general backends are JavaScript, JVM, LLVM, and direct WebAssembly. They
must eventually support ordinary Python numeric behavior, including arbitrary
precision ``int`` and ``decimal.Decimal``. A backend may use optimized small
representations, but it must use a runtime shim when native behavior differs.
WGSL is the intentional exception: shader code uses WGSL types and WGSL rules,
not Python numeric types.

Shader signatures and storage use explicit types from ``pyjs.shader``. Plain
integer and floating-point literals remain ergonomic: analysis gives them the
WGSL type required by their context, while an explicit ``int`` or ``float``
annotation is rejected.

Portable fixed-width types
--------------------------

The root package exports ``int8``, ``uint8``, ``int16``, ``uint16``,
``int32``, ``uint32``, ``int64``, ``float32``, and ``float64``. They are also
defined by this module. Fixed integers wrap on construction and after every
integer-producing operation. Different widths and signedness do not mix
implicitly:

```python
from pyjs import int8, uint32

wrapped = int8(127) + 1
converted = uint32(wrapped)
```

Division with ``/`` returns ``float``. Comparisons return ``bool``. Division
by zero and other invalid operations fail consistently rather than acquiring
target-specific behavior. ``float32`` rounds as IEEE-754 binary32 after each
operation; ``float64`` uses IEEE-754 binary64.

Portable floats currently support addition, subtraction, multiplication, true
division, unary operations, comparisons, and ``round()`` on backends that
support that built-in. Supplying ``ndigits`` to ``round()`` returns the same
portable type; omitting it returns an ordinary ``int``. Floor division, modulo,
power, and ``divmod()`` are deliberately excluded until every general backend
can provide the same edge behavior without target-specific surprises.

Compiled fixed-integer construction accepts integer expressions and finite
float literals. Convert a dynamic float to ``int`` after validating it is
finite before constructing a fixed-width integer; this avoids the incompatible
NaN and infinity conversion rules of JavaScript, JVM, LLVM, and WebAssembly.

JavaScript preserves the full ``int64`` range while a value remains fixed
width. Converting an ``int64`` outside JavaScript's safe integer range back to
an ordinary ``int`` currently raises ``ValueError`` instead of truncating it.
Use ``str(value)`` for an exact textual value until arbitrary-precision Python
``int`` lowering is available. Python integer-index operations such as ranges,
slices, repetition, and string bounds accept ``int64`` within that safe range
and raise ``ValueError`` outside it. JavaScript converts ``int64`` to
``Number`` at ordinary ``float`` parameter boundaries, including functions in
``pyjs.stdlib.math``. Integer-returning operations such as ``ceil()`` and
``floor()`` reject results outside the safe ordinary-integer range.

Static arrays
-------------

``StaticArray[Item, length]`` is a mutable sequence whose positive length is
part of its type. The name distinguishes a compile-time layout promise from a
particular target representation: a backend may use a native fixed array or a
compatible internal carrier. Items may be replaced, but operations that
change length are rejected. Fixed-width numeric items are normalized on
construction and assignment. Represented items inside lists, tuples, mappings,
sets, unions, and TypedDict records are normalized recursively, making the
storage boundary observable under CPython as well as compiled targets.

Represented items retain their semantics through ordinary typed collections,
variadic parameters, iteration, comprehensions, and typed callable results.
Use ``StaticArray`` when length is part of the contract. A ``StaticArray``
cannot implicitly widen to a mutable ``list`` because doing so would expose
length-changing methods.

```python
from pyjs import StaticArray, float32

Point = StaticArray[float32, 3]
origin = Point([float32(0), float32(0), float32(0)])
```

Array layout is recursive and target-neutral. Shared IR records the length,
domain, nested array layout, and fixed-width item format without choosing JVM,
LLVM, WebAssembly, or JavaScript storage. ``pyjs.shader.Array`` is deliberately
separate: it follows WGSL array rules and emits native ``array<T, N>`` types.

Compound types
--------------

Representation metadata follows the complete annotation rather than sitting
beside only its outer type. This preserves fixed-width values and static arrays
through ``list``, ``set``, ``dict``, ``tuple``, ``Callable``, ``Awaitable``,
unions, iterators, and nested combinations of those types. Reads, writes,
unpacking, slicing, collection copies, comprehensions, and common iterable
built-ins retain the represented item contract.

Some unions are intentionally invalid. For example, ``int8 | int16`` erases
to ``int`` at runtime, so an ``isinstance`` check cannot identify which storage
contract applies. Convert such values to one represented type before crossing
the union boundary. ``int8 | None`` is sound because the branches remain
distinguishable and narrowing restores the ``int8`` representation.

Generic functions preserve represented type arguments. Generic classes do not
yet support them because their concrete class specialization currently erases
the representation. Use a concrete class with represented field annotations
until generic class specializations carry that metadata soundly.

Exact decimals
--------------

``pyjs.stdlib.decimal.Decimal`` provides the initial finite exact-decimal
subset for application values such as money. CPython delegates to
``decimal.Decimal``. JavaScript stores a ``BigInt`` coefficient and decimal
exponent, preserving exact construction from strings and integers, addition,
subtraction, multiplication, ordering, and string conversion. Division,
contexts, special values, signed zero, and exponent notation remain
unsupported rather than silently acquiring binary floating-point behavior.
Other general backends will add native or runtime implementations when an
application needs them.

Backend representation
----------------------

| Type | JavaScript | JVM |
| --- | --- | --- |
| Python ``int`` | Safe ``Number`` subset | ``i64`` subset |
| Python ``float`` | ``Number`` | ``double`` |
| ``Decimal`` | BigInt coefficient | Planned |
| 8-bit integer | Normalized number | ``byte`` |
| 16-bit integer | Normalized number | 16-bit |
| 32-bit integer | Normalized number | ``int`` |
| ``int64`` | ``BigInt`` | ``long`` |
| ``float32`` | ``Math.fround`` | ``float`` |
| ``float64`` | ``Number`` | ``double`` |
| ``StaticArray`` | ``Array`` | Typed wrapper |

| Type | LLVM | WebAssembly |
| --- | --- | --- |
| Python ``int`` | ``i64`` subset | ``i64`` subset |
| Python ``float`` | ``double`` | ``f64`` |
| ``Decimal`` | Planned | Planned |
| 8-bit integer | ``i8`` | Normalized ``i32`` |
| 16-bit integer | ``i16`` | Normalized ``i32`` |
| 32-bit integer | ``i32`` | ``i32`` |
| ``int64`` | ``i64`` | ``i64`` |
| ``float32`` | ``float`` | ``f32`` |
| ``float64`` | ``double`` | ``f64`` |
| ``StaticArray`` | Arena list | GC list |

The Python ``int`` row names the current carriers, not the completed contract.
Every general backend must eventually preserve arbitrary-precision Python
integer behavior with optimized native values and runtime shims as needed.

WGSL compatibility
------------------

Portable ``int32``, ``uint32``, and ``float32`` are representation-compatible
with WGSL ``i32``, ``u32``, and ``f32``. They are not semantically
interchangeable. Explicit conversion between matching representations can be
zero-cost, but shader functions use the types from ``pyjs.shader``. Other
portable numeric types have no direct WGSL scalar representation.

WGSL code follows WGSL conversion, overflow, floating-point, shift, and error
rules. Its CPython and general-backend implementations are reference emulators
for testing. Operations whose WGSL result is indeterminate may use a documented
deterministic reference result or be rejected; PyJS does not promise a
bit-identical result where the WGSL specification permits implementations to
differ.

Target-specific types
---------------------

Every target-specific type has a CPython implementation so its semantics can
be unit tested without launching that target. A function that reaches a
target-specific type can only be compiled for that target. The analyzer rejects
calls, assignments, and implicit conversions between target domains with a
focused diagnostic.

Serialization
-------------

JSON has one untyped decimal number grammar. It does not define ``BigInt``,
``Decimal``, complex numbers, fixed widths, ``NaN``, or infinity. Only integers
between ``-(2**53) + 1`` and ``(2**53) - 1`` are guaranteed to interoperate
exactly across common JSON implementations. Typed codecs therefore serialize
larger integers and exact decimals as strings, and complex values as structured
data. Fixed integers through 32 bits can use JSON numbers directly.

Use explicit typed-array and ABI APIs when a physical representation must be
observable. Backend-specific declarations remain appropriate for external
platform APIs, but they intentionally sacrifice cross-target compilation.
"""

import ast
import math
import operator
import re
import struct
import types
import typing
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from types import NotImplementedType
from typing import Annotated, Self, TypeAliasType, get_args, get_origin

from pyjs.decorators import js

_NUMERIC_DOMAIN = re.compile(r"[a-z][a-z0-9_]*\Z")
_TRANSPARENT_ANNOTATION_WRAPPERS = frozenset(
    {"ClassVar", "Final", "NotRequired", "ReadOnly", "Required"}
)


def _is_transparent_annotation_wrapper(origin: object) -> bool:
    return (
        origin is not None
        and getattr(origin, "__name__", "") in _TRANSPARENT_ANNOTATION_WRAPPERS
    )


def unwrap_representation_annotation(annotation: object, *, aliases: bool = True) -> object:
    """Remove wrappers, optionally leaving named aliases for graph visitors."""
    seen_aliases = set()
    while True:
        if isinstance(annotation, TypeAliasType):
            if not aliases:
                return annotation
            if annotation in seen_aliases:
                raise TypeError(f"Recursive type alias {annotation.__name__!r} has no concrete member")
            seen_aliases.add(annotation)
            annotation = annotation.__value__
            continue
        origin = get_origin(annotation)
        if origin is Annotated or _is_transparent_annotation_wrapper(origin):
            annotation = get_args(annotation)[0]
            continue
        return annotation


@dataclass(frozen=True)
class NumericFormat:
    """The target-neutral representation of a Python numeric value."""

    kind: str
    bits: int
    signed: bool | None = None
    domain: str = "portable"

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in {"integer", "float"}:
            raise TypeError(f"unsupported numeric format kind {self.kind!r}")
        if (
            type(self.domain) is not str
            or _NUMERIC_DOMAIN.fullmatch(self.domain) is None
        ):
            raise TypeError(f"unsupported numeric domain {self.domain!r}")
        if self.kind == "integer" and type(self.signed) is not bool:
            raise TypeError("integer numeric formats require signedness")
        if self.kind == "float" and self.signed is not None:
            raise TypeError("floating-point numeric formats do not use signedness")
        if self.kind == "integer" and self.bits == 64 and not self.signed:
            raise TypeError("unsigned 64-bit numeric formats are not supported")
        allowed = {8, 16, 32, 64} if self.kind == "integer" else {32, 64}
        if type(self.bits) is not int or self.bits not in allowed:
            raise TypeError(
                f"{self.kind} numeric formats do not support {self.bits} bits"
            )

    @property
    def integer_bounds(self) -> tuple[int, int]:
        """Return the inclusive range of an integer format."""
        if self.kind != "integer":
            raise TypeError("floating-point numeric formats do not have integer bounds")
        if self.signed:
            limit = 1 << (self.bits - 1)
            return -limit, limit - 1
        return 0, (1 << self.bits) - 1


def wrapped_integer_value(value: int, numeric: NumericFormat) -> int:
    modulus = 1 << numeric.bits
    value %= modulus
    if numeric.signed and value >= modulus >> 1:
        value -= modulus
    return value


@dataclass(frozen=True)
class ArrayFormat:
    """The target-neutral layout of one fixed-length array value."""

    length: int
    domain: str = "portable"
    item_numeric: NumericFormat | None = None
    item_array: ArrayFormat | None = None

    def __post_init__(self) -> None:
        if type(self.length) is not int or self.length <= 0:
            raise TypeError("a static array length must be a positive integer")
        if (
            type(self.domain) is not str
            or _NUMERIC_DOMAIN.fullmatch(self.domain) is None
        ):
            raise TypeError(f"unsupported array domain {self.domain!r}")
        if self.item_numeric is not None and not isinstance(
            self.item_numeric,
            NumericFormat,
        ):
            raise TypeError("an array numeric item requires NumericFormat metadata")
        if self.item_array is not None and not isinstance(
            self.item_array,
            ArrayFormat,
        ):
            raise TypeError("an array item layout requires ArrayFormat metadata")
        if self.item_numeric is not None and self.item_array is not None:
            raise TypeError("an array item cannot have two storage formats")
        item_format = self.item_numeric or self.item_array
        if item_format is not None and item_format.domain != self.domain:
            raise TypeError("an array and its stored item must use the same domain")


_STATIC_ARRAY_TYPES = weakref.WeakValueDictionary()


def _matches_exact_type(value, annotation) -> bool:
    annotation = unwrap_representation_annotation(annotation)
    if annotation is None:
        annotation = type(None)
    return annotation is type(value)


def _matches_annotation(value, annotation) -> bool:
    annotation = unwrap_representation_annotation(annotation)
    numeric = numeric_format(annotation)
    if numeric is not None:
        return isinstance(value, int if numeric.kind == "integer" else float)
    if array_format(annotation) is not None:
        return isinstance(value, list)
    origin = get_origin(annotation)
    if origin in (types.UnionType, typing.Union):
        return any(_matches_annotation(value, member) for member in get_args(annotation))
    if origin is typing.Literal:
        return value in get_args(annotation)
    if typing.is_typeddict(annotation):
        return isinstance(value, dict)
    if origin is not None:
        return isinstance(value, origin)
    if annotation is None or annotation is type(None):
        return value is None
    return isinstance(annotation, type) and isinstance(value, annotation)


def _coerce_represented_value(annotation, value) -> tuple[bool, object]:
    annotation = unwrap_representation_annotation(annotation)
    numeric = numeric_format(annotation)
    if numeric is not None:
        value_numeric = numeric_format(type(value))
        if value_numeric is not None and value_numeric != numeric:
            raise TypeError("a static array item requires an explicit conversion")
        return True, annotation(value)
    expected_array = array_format(annotation)
    if expected_array is not None:
        value_array = array_format(type(value))
        if value_array is not None and value_array != expected_array:
            raise TypeError("a static array item requires an explicit conversion")
        return True, value if type(value) is annotation else annotation(value)

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in (types.UnionType, typing.Union):
        matching = [member for member in arguments if _matches_annotation(value, member)]
        exact = [member for member in matching if _matches_exact_type(value, member)]
        if exact:
            matching = exact
        actual_numeric = numeric_format(type(value))
        if actual_numeric is not None and not exact:
            exact = [
                member for member in matching if numeric_format(member) == actual_numeric
            ]
            if exact:
                matching = exact
        if len(matching) != 1:
            raise TypeError("a static array union item is ambiguous")
        return _coerce_represented_value(matching[0], value)
    if origin is typing.Literal:
        return False, value
    if typing.is_typeddict(annotation):
        if not isinstance(value, dict):
            raise TypeError("a static array item requires a TypedDict value")
        result = dict(value)
        represented = False
        for name, field_type in typing.get_type_hints(
            annotation,
            include_extras=True,
        ).items():
            if name not in result:
                continue
            found, result[name] = _coerce_represented_value(
                field_type,
                result[name],
            )
            represented |= found
        return represented, result if represented else value
    if origin in (list, set):
        if not isinstance(value, origin):
            raise TypeError(f"a static array item requires a {origin.__name__}")
        found_items = [_coerce_represented_value(arguments[0], item) for item in value]
        represented = any(found for found, _item in found_items)
        if not represented:
            return False, value
        return True, origin(item for _found, item in found_items)
    if origin is tuple:
        if not isinstance(value, tuple):
            raise TypeError("a static array item requires a tuple")
        item_types = (
            arguments[:1] * len(value)
            if len(arguments) == 2 and arguments[1] is Ellipsis
            else arguments
        )
        if len(item_types) != len(value):
            raise TypeError("a static array tuple item has the wrong length")
        found_items = [
            _coerce_represented_value(item_type, item)
            for item_type, item in zip(item_types, value, strict=True)
        ]
        represented = any(found for found, _item in found_items)
        if not represented:
            return False, value
        return True, tuple(item for _found, item in found_items)
    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError("a static array item requires a dict")
        key_type, item_type = arguments
        represented = False
        result = {}
        for key, item in value.items():
            key_found, key = _coerce_represented_value(key_type, key)
            item_found, item = _coerce_represented_value(item_type, item)
            represented |= key_found or item_found
            result[key] = item
        return (True, result) if represented else (False, value)
    if origin in (Callable, typing.Callable):
        if not callable(value):
            raise TypeError("a static array item requires a callable")
        represented = any(
            numeric_format(member) is not None or array_format(member) is not None
            for member in arguments
            if member is not Ellipsis
        )
        return represented, value
    return False, value


class _StaticArrayBase(list[object]):
    __slots__ = ()

    __pyjs_array_domain__: str
    __pyjs_array_item__: object | None = None
    __pyjs_array_length__: int | None = None

    @classmethod
    def __class_getitem__(cls, parameters):
        if not isinstance(parameters, tuple) or len(parameters) != 2:
            raise TypeError(f"{cls.__name__} expects an item type and length")
        item, length = parameters
        if type(length) is not int or length <= 0:
            raise TypeError(f"{cls.__name__} length must be a positive integer")
        key = cls, item, length
        specialized = _STATIC_ARRAY_TYPES.get(key)
        if specialized is None:
            item_name = getattr(item, "__name__", repr(item))
            specialized = type(
                f"{cls.__name__}[{item_name}, {length}]",
                (cls,),
                {
                    "__module__": cls.__module__,
                    "__pyjs_array_item__": item,
                    "__pyjs_array_length__": length,
                },
            )
            _STATIC_ARRAY_TYPES[key] = specialized
        return specialized

    def __init__(self, values) -> None:
        length = type(self).__pyjs_array_length__
        if length is None:
            raise TypeError("parameterize a static array with its item type and length")
        super().__init__(self._coerce_item(value) for value in values)
        if len(self) != length:
            raise ValueError(
                f"{type(self).__name__} requires {length} items, got {len(self)}"
            )

    def _coerce_item(self, value):
        item_type = type(self).__pyjs_array_item__
        _represented, result = _coerce_represented_value(item_type, value)
        return result

    def _fixed_length(self, *args, **kwargs) -> None:
        raise TypeError("a static array cannot change length")

    append = clear = extend = insert = pop = remove = _fixed_length
    __iadd__ = __imul__ = __mul__ = __rmul__ = _fixed_length

    def __delitem__(self, key) -> None:
        self._fixed_length()

    def __setitem__(self, key, value) -> None:
        if not isinstance(key, slice):
            return super().__setitem__(key, self._coerce_item(value))
        replacement = [self._coerce_item(item) for item in value]
        removed = len(range(*key.indices(len(self))))
        if len(replacement) != removed:
            self._fixed_length()
        super().__setitem__(key, replacement)


@js
class StaticArray[T, N](_StaticArrayBase):
    """A mutable array whose positive length is part of its static type."""

    __slots__ = ()
    __pyjs_array_domain__ = "portable"


def array_format(annotation: object) -> ArrayFormat | None:
    """Return fixed-array metadata carried by a specialized annotation."""
    annotation = unwrap_representation_annotation(annotation)
    length = getattr(annotation, "__pyjs_array_length__", None)
    if length is None:
        return None
    item = annotation.__pyjs_array_item__
    return ArrayFormat(
        length,
        domain=annotation.__pyjs_array_domain__,
        item_numeric=numeric_format(item),
        item_array=array_format(item),
    )


def array_item(annotation: object) -> object | None:
    """Return the item annotation carried by a specialized static array."""
    annotation = unwrap_representation_annotation(annotation)
    return getattr(annotation, "__pyjs_array_item__", None)


def numeric_format(annotation: object) -> NumericFormat | None:
    """Return the PyJS numeric metadata nested in one Python annotation."""
    found = None
    aliases = set()
    while True:
        if isinstance(annotation, TypeAliasType):
            if annotation in aliases:
                raise TypeError(f"Recursive type alias {annotation.__name__!r} has no concrete member")
            aliases.add(annotation)
            annotation = annotation.__value__
            continue
        origin = get_origin(annotation)
        if origin is Annotated:
            annotation, *metadata = get_args(annotation)
            formats = [value for value in metadata if isinstance(value, NumericFormat)]
            if len(formats) + (found is not None) > 1:
                raise TypeError("a numeric annotation may contain only one format")
            if formats:
                found = formats[0]
            continue
        if _is_transparent_annotation_wrapper(origin):
            annotation = get_args(annotation)[0]
            continue
        declared = getattr(annotation, "__pyjs_numeric_format__", None)
        if declared is not None:
            if found is not None:
                raise TypeError("a numeric annotation may contain only one format")
            found = declared
        if found is not None:
            expected = int if found.kind == "integer" else float
            if (
                not isinstance(annotation, type)
                or annotation is bool
                or not issubclass(annotation, expected)
            ):
                raise TypeError(
                    f"{found.kind} numeric formats require {expected.__name__}"
                )
        return found


def integer_literal(
    node: ast.expr,
    *,
    allow_bool: bool = False,
) -> int | None:
    """Return a statically known integer expression without executing code."""
    if isinstance(node, ast.Constant):
        if type(node.value) is int:
            return node.value
        if allow_bool and type(node.value) is bool:
            return int(node.value)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "abs"
        and len(node.args) == 1
        and not node.keywords
    ):
        value = integer_literal(node.args[0], allow_bool=allow_bool)
        return abs(value) if value is not None else None
    if isinstance(node, ast.UnaryOp):
        value = integer_literal(node.operand, allow_bool=allow_bool)
        if value is None:
            return None
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Invert):
            return ~value
        return None
    if not isinstance(node, ast.BinOp):
        return None
    left = integer_literal(node.left, allow_bool=allow_bool)
    right = integer_literal(node.right, allow_bool=allow_bool)
    if left is None or right is None:
        return None
    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        return left * right
    if isinstance(node.op, ast.FloorDiv) and right:
        return left // right
    if isinstance(node.op, ast.Mod) and right:
        return left % right
    if isinstance(node.op, ast.Pow) and 0 <= right <= 4096:
        return left**right
    if isinstance(node.op, ast.BitAnd):
        return left & right
    if isinstance(node.op, ast.BitOr):
        return left | right
    if isinstance(node.op, ast.BitXor):
        return left ^ right
    if isinstance(node.op, ast.LShift) and 0 <= right <= 4096:
        return left << right
    if isinstance(node.op, ast.RShift) and right >= 0:
        return left >> right
    return None


def float_literal(node: ast.expr) -> float | None:
    """Return one finite or non-finite floating-point literal."""
    if isinstance(node, ast.Constant) and type(node.value) is float:
        return node.value
    if not isinstance(node, ast.UnaryOp):
        return None
    value = float_literal(node.operand)
    if value is None:
        return None
    if isinstance(node.op, ast.UAdd):
        return value
    if isinstance(node.op, ast.USub):
        return -value
    return None


class _FixedInteger(int):
    __slots__ = ()

    __pyjs_numeric_format__: NumericFormat
    __hash__ = int.__hash__

    @classmethod
    def _new_wrapped(cls, value: int) -> Self:
        return int.__new__(
            cls,
            wrapped_integer_value(value, cls.__pyjs_numeric_format__),
        )

    def __new__(cls, value: int | float = 0) -> Self:
        if not isinstance(value, (int, float)):
            raise TypeError(f"{cls.__name__}() requires a number")
        return cls._new_wrapped(int(value))

    def _other(self, other: object) -> int | NotImplementedType:
        if isinstance(other, _FixedInteger) and type(other) is not type(self):
            return NotImplemented
        if isinstance(other, int):
            return int(other)
        return NotImplemented

    def _binary(self, other: object, operation) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return type(self)._new_wrapped(operation(int(self), other_value))

    def _reflected(self, other: object, operation) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return type(self)._new_wrapped(operation(other_value, int(self)))

    def _comparison_other(self, other: object) -> int | NotImplementedType:
        if isinstance(other, _FixedInteger) and type(other) is not type(self):
            raise TypeError("different fixed-width integer types cannot be compared")
        if isinstance(other, int):
            return int(other)
        return NotImplemented

    def _compare(self, other: object, operation) -> bool | NotImplementedType:
        other_value = self._comparison_other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return operation(int(self), other_value)

    def __eq__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.eq)

    def __ne__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.ne)

    def __lt__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.lt)

    def __le__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.le)

    def __gt__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.gt)

    def __ge__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.ge)

    def __add__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.add)

    def __radd__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.add)

    def __sub__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.sub)

    def __rsub__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.sub)

    def __mul__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.mul)

    def __rmul__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.mul)

    def __truediv__(self, other: object) -> float | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return int(self) / other_value

    def __rtruediv__(self, other: object) -> float | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return other_value / int(self)

    def __floordiv__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.floordiv)

    def __rfloordiv__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.floordiv)

    def __mod__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.mod)

    def __rmod__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.mod)

    def __divmod__(
        self,
        other: object,
    ) -> tuple[Self, Self] | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        quotient, remainder = divmod(int(self), other_value)
        return (
            type(self)._new_wrapped(quotient),
            type(self)._new_wrapped(remainder),
        )

    def __rdivmod__(
        self,
        other: object,
    ) -> tuple[Self, Self] | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        quotient, remainder = divmod(other_value, int(self))
        return (
            type(self)._new_wrapped(quotient),
            type(self)._new_wrapped(remainder),
        )

    def __pow__(
        self,
        exponent: object,
        modulo: object | None = None,
    ) -> Self | NotImplementedType:
        exponent_value = self._other(exponent)
        if exponent_value is NotImplemented:
            return NotImplemented
        if exponent_value < 0:
            raise ValueError(
                "negative exponent is not supported for fixed-width integers"
            )
        if modulo is None:
            result = pow(int(self), exponent_value)
        else:
            modulo_value = self._other(modulo)
            if modulo_value is NotImplemented:
                return NotImplemented
            result = pow(int(self), exponent_value, modulo_value)
        return type(self)._new_wrapped(result)

    def __rpow__(
        self,
        base: object,
        modulo: object | None = None,
    ) -> Self | NotImplementedType:
        base_value = self._other(base)
        if base_value is NotImplemented:
            return NotImplemented
        if int(self) < 0:
            raise ValueError(
                "negative exponent is not supported for fixed-width integers"
            )
        if modulo is None:
            result = pow(base_value, int(self))
        else:
            modulo_value = self._other(modulo)
            if modulo_value is NotImplemented:
                return NotImplemented
            result = pow(base_value, int(self), modulo_value)
        return type(self)._new_wrapped(result)

    def __and__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.and_)

    def __rand__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.and_)

    def __or__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.or_)

    def __ror__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.or_)

    def __xor__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.xor)

    def __rxor__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.xor)

    def __lshift__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.lshift)

    def __rlshift__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.lshift)

    def __rshift__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.rshift)

    def __rrshift__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.rshift)

    def __neg__(self) -> Self:
        return type(self)._new_wrapped(-int(self))

    def __pos__(self) -> Self:
        return self

    def __invert__(self) -> Self:
        return type(self)._new_wrapped(~int(self))

    def __abs__(self) -> Self:
        return type(self)._new_wrapped(abs(int(self)))

    def __round__(self, ndigits: int | None = None) -> Self:
        return type(self)._new_wrapped(round(int(self), ndigits))


class _FixedFloat(float):
    __slots__ = ()

    __pyjs_numeric_format__: NumericFormat
    __hash__ = float.__hash__

    @classmethod
    def _new_rounded(cls, value: float) -> Self:
        if cls.__pyjs_numeric_format__.bits == 32:
            try:
                value = struct.unpack("!f", struct.pack("!f", value))[0]
            except OverflowError:
                value = math.copysign(math.inf, value)
        return float.__new__(cls, value)

    def __new__(cls, value: int | float = 0.0) -> Self:
        if not isinstance(value, (int, float)):
            raise TypeError(f"{cls.__name__}() requires a number")
        return cls._new_rounded(float(value))

    def _other(self, other: object) -> float | NotImplementedType:
        if isinstance(other, (_FixedFloat, _FixedInteger)):
            if type(other) is not type(self):
                return NotImplemented
        if isinstance(other, (int, float)):
            return float(other)
        return NotImplemented

    def _binary(self, other: object, operation) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return type(self)._new_rounded(operation(float(self), other_value))

    def _reflected(self, other: object, operation) -> Self | NotImplementedType:
        other_value = self._other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return type(self)._new_rounded(operation(other_value, float(self)))

    def _comparison_other(self, other: object) -> float | NotImplementedType:
        if isinstance(other, (_FixedFloat, _FixedInteger)):
            if type(other) is not type(self):
                raise TypeError("different fixed-width numeric types cannot be compared")
        if isinstance(other, (int, float)):
            return float(other)
        return NotImplemented

    def _compare(self, other: object, operation) -> bool | NotImplementedType:
        other_value = self._comparison_other(other)
        if other_value is NotImplemented:
            return NotImplemented
        return operation(float(self), other_value)

    def __eq__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.eq)

    def __ne__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.ne)

    def __lt__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.lt)

    def __le__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.le)

    def __gt__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.gt)

    def __ge__(self, other: object) -> bool | NotImplementedType:
        return self._compare(other, operator.ge)

    def __add__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.add)

    def __radd__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.add)

    def __sub__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.sub)

    def __rsub__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.sub)

    def __mul__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.mul)

    def __rmul__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.mul)

    def __truediv__(self, other: object) -> Self | NotImplementedType:
        return self._binary(other, operator.truediv)

    def __rtruediv__(self, other: object) -> Self | NotImplementedType:
        return self._reflected(other, operator.truediv)

    def __floordiv__(self, other: object) -> Self | NotImplementedType:
        raise TypeError("portable fixed-width floats do not support //")

    def __rfloordiv__(self, other: object) -> Self | NotImplementedType:
        raise TypeError("portable fixed-width floats do not support //")

    def __mod__(self, other: object) -> Self | NotImplementedType:
        raise TypeError("portable fixed-width floats do not support %")

    def __rmod__(self, other: object) -> Self | NotImplementedType:
        raise TypeError("portable fixed-width floats do not support %")

    def __divmod__(
        self,
        other: object,
    ) -> tuple[Self, Self] | NotImplementedType:
        raise TypeError("portable fixed-width floats do not support divmod()")

    def __rdivmod__(
        self,
        other: object,
    ) -> tuple[Self, Self] | NotImplementedType:
        raise TypeError("portable fixed-width floats do not support divmod()")

    def __pow__(self, other: object) -> Self | NotImplementedType:
        raise TypeError("portable fixed-width floats do not support **")

    def __rpow__(self, other: object) -> Self | NotImplementedType:
        raise TypeError("portable fixed-width floats do not support **")

    def __neg__(self) -> Self:
        return type(self)._new_rounded(-float(self))

    def __pos__(self) -> Self:
        return self

    def __abs__(self) -> Self:
        return type(self)._new_rounded(abs(float(self)))

    def __round__(self, ndigits: int | None = None) -> int | Self:
        rounded = round(float(self), ndigits)
        if ndigits is None:
            return rounded
        return type(self)._new_rounded(rounded)


class int8(_FixedInteger):
    """Signed 8-bit integer with modular arithmetic."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("integer", 8, True)


class uint8(_FixedInteger):
    """Unsigned 8-bit integer with modular arithmetic."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("integer", 8, False)


class int16(_FixedInteger):
    """Signed 16-bit integer with modular arithmetic."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("integer", 16, True)


class uint16(_FixedInteger):
    """Unsigned 16-bit integer with modular arithmetic."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("integer", 16, False)


class int32(_FixedInteger):
    """Signed 32-bit integer with modular arithmetic."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("integer", 32, True)


class uint32(_FixedInteger):
    """Unsigned 32-bit integer with modular arithmetic."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("integer", 32, False)


class int64(_FixedInteger):
    """Signed 64-bit integer with modular arithmetic."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("integer", 64, True)


class float32(_FixedFloat):
    """IEEE-754 binary32 value rounded after each arithmetic operation."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("float", 32)


class float64(_FixedFloat):
    """IEEE-754 binary64 value with an explicit portable type identity."""

    __slots__ = ()
    __pyjs_numeric_format__ = NumericFormat("float", 64)


__all__ = [
    "StaticArray",
    "float32",
    "float64",
    "int8",
    "int16",
    "int32",
    "int64",
    "uint8",
    "uint16",
    "uint32",
]
