"""Python semantics available while analyzing WGSL functions.

These definitions describe the Python operations that have a meaningful WGSL
counterpart. Their bodies are interfaces: CPython executes the real builtins,
and the WGSL emitter lowers the analyzed operations directly.
"""

from collections.abc import Iterable, Iterator
from typing import overload

from pyjs import js
from pyjs.decorators import (
    get_wgsl_decoration,
    is_declaration,
    is_native_for,
    preserves_numeric_format,
)

analyze_all_definitions = False


def include_definition(name, value, module) -> bool:
    """Select definitions that can participate in one WGSL compilation.

    WGSL is a library target rather than a whole-module target. Keeping this
    policy beside its semantic builtins lets the shared analyzer construct
    only shader roots, their imports, and scalar module constants.
    """
    if get_wgsl_decoration(value) is not None:
        return True
    if isinstance(value, type) and hasattr(value, "__pyjs_array_domain__"):
        return True
    return name in module.js_annotations and type(value) in {bool, int, float}


def should_analyze_body(func) -> bool:
    """Return whether WGSL needs the Python body for type inference.

    Native and inline bodies are CPU implementations, so analyzing them with
    WGSL's deliberately smaller Python surface would reject otherwise valid
    fallback code. Native vector constructors are the exception: their
    assignments establish the component fields used by shader expressions.
    Dataclass-generated comparison and representation methods are likewise
    unnecessary because the WGSL emitter handles struct equality directly.
    """
    if is_declaration(func.py_func, "wgsl"):
        return False
    class_decoration = (
        get_wgsl_decoration(func.cls.py_cls)
        if func.cls is not None
        else None
    )
    class_native = func.cls is not None and is_native_for(func.cls.py_cls, "wgsl")
    if class_native and func.name != "__init__":
        return False
    return not (
        class_decoration is not None
        and class_decoration.kind == "emit"
        and func.name in {"__eq__", "__ne__", "__repr__"}
        and hasattr(func.cls.py_cls, "__dataclass_fields__")
    )


class _object:
    def __init__(self) -> None: ...

    def __is__(self, other: object) -> bool: ...

    def __is_not__(self, other: object) -> bool: ...

    def __eq__(self, other: object) -> bool: ...

    def __ne__(self, other: object) -> bool: ...


class _type[T](_object): ...


class _Generic(_object): ...


class _Iterable[V](_object):
    def __iter__(self) -> Iterator[V]: ...


class _Iterator[V](_Iterable[V]): ...


class _Awaitable[T](_object): ...


class _NoneType(_object): ...


class _Exception(_object): ...


class _AssertionError(_Exception): ...


class _str(_object):
    """Structural analyzer type; WGSL emission rejects string values."""


class _tuple[T](_object):
    """Structural analyzer type; WGSL emission rejects tuple values."""

    def __iter__(self) -> Iterator[object]: ...

    def __getitem__(self, index: int) -> object: ...


class _dict[K, V](_object):
    """Structural analyzer type; WGSL emission rejects dictionaries."""


class _set[T](_object):
    """Structural analyzer type; WGSL emission rejects sets."""


class _int(_object):
    def __init__(self, value: int | float | bool = 0) -> None: ...

    def __bool__(self) -> bool: ...

    @preserves_numeric_format
    def __abs__(self) -> int: ...

    def __invert__(self) -> int: ...

    def __lt__(self, other: int) -> bool: ...

    def __le__(self, other: int) -> bool: ...

    def __gt__(self, other: int) -> bool: ...

    def __ge__(self, other: int) -> bool: ...

    def __eq__(self, other: int) -> bool: ...

    def __ne__(self, other: int) -> bool: ...

    def __add__(self, other: int) -> int: ...

    def __radd__(self, other: int) -> int: ...

    def __sub__(self, other: int) -> int: ...

    def __rsub__(self, other: int) -> int: ...

    def __mul__(self, other: int) -> int: ...

    def __rmul__(self, other: int) -> int: ...

    def __truediv__(self, other: int) -> float: ...

    def __rtruediv__(self, other: int) -> float: ...

    def __floordiv__(self, other: int) -> int: ...

    def __rfloordiv__(self, other: int) -> int: ...

    def __mod__(self, other: int) -> int: ...

    def __rmod__(self, other: int) -> int: ...

    def __or__(self, other: int) -> int: ...

    def __ror__(self, other: int) -> int: ...

    def __and__(self, other: int) -> int: ...

    def __rand__(self, other: int) -> int: ...

    def __xor__(self, other: int) -> int: ...

    def __rxor__(self, other: int) -> int: ...

    def __lshift__(self, other: int) -> int: ...

    def __rlshift__(self, other: int) -> int: ...

    def __rshift__(self, other: int) -> int: ...

    def __rrshift__(self, other: int) -> int: ...


class _bool(_int):
    def __init__(self, value: int | float | bool = False) -> None: ...

    def __or__(self, other: bool) -> bool: ...

    def __ror__(self, other: bool) -> bool: ...

    def __and__(self, other: bool) -> bool: ...

    def __rand__(self, other: bool) -> bool: ...

    def __xor__(self, other: bool) -> bool: ...

    def __rxor__(self, other: bool) -> bool: ...


class _float(_object):
    def __init__(self, value: int | float | bool = 0.0) -> None: ...

    def __bool__(self) -> bool: ...

    @preserves_numeric_format
    def __abs__(self) -> float: ...

    def __lt__(self, other: int | float | bool) -> bool: ...

    def __le__(self, other: int | float | bool) -> bool: ...

    def __gt__(self, other: int | float | bool) -> bool: ...

    def __ge__(self, other: int | float | bool) -> bool: ...

    def __eq__(self, other: int | float | bool) -> bool: ...

    def __ne__(self, other: int | float | bool) -> bool: ...

    def __add__(self, other: int | float | bool) -> float: ...

    def __radd__(self, other: int | float | bool) -> float: ...

    def __sub__(self, other: int | float | bool) -> float: ...

    def __rsub__(self, other: int | float | bool) -> float: ...

    def __mul__(self, other: int | float | bool) -> float: ...

    def __rmul__(self, other: int | float | bool) -> float: ...

    def __truediv__(self, other: int | float | bool) -> float: ...

    def __rtruediv__(self, other: int | float | bool) -> float: ...

    def __floordiv__(self, other: int | float | bool) -> float: ...

    def __rfloordiv__(self, other: int | float | bool) -> float: ...

    def __mod__(self, other: int | float | bool) -> float: ...

    def __rmod__(self, other: int | float | bool) -> float: ...


class _list[V](_object):
    def __iter__(self) -> Iterator[V]: ...

    def __getitem__(self, index: int) -> V: ...

    def __setitem__(self, index: int, value: V) -> None: ...


def _range(
    start: int,
    stop: int | None = None,
    step: int = 1,
) -> Iterable[int]: ...


@overload
@preserves_numeric_format
def _abs(value: int | bool) -> int: ...


@overload
@preserves_numeric_format
def _abs(value: float) -> float: ...


@preserves_numeric_format
@js.dispatch("__abs__")
def _abs(value: int | float | bool) -> int | float: ...


@overload
def _min[T](values: Iterable[T]) -> T: ...


@overload
def _min[T](first: T, second: T, *values: T) -> T: ...


@js
def _min(*values: object) -> object: ...


@_min.analyze
def _min(call):
    return call.extreme()


@overload
def _max[T](values: Iterable[T]) -> T: ...


@overload
def _max[T](first: T, second: T, *values: T) -> T: ...


@js
def _max(*values: object) -> object: ...


@_max.analyze
def _max(call):
    return call.extreme()


@js.inline("callable")
class _callable:
    def __call__(self, *args: object) -> object: ...


def _unpack_exact(values: list[object], expected: int) -> list[object]: ...


def _unpack_starred(
    values: list[object],
    before: int,
    after: int,
) -> list[object]: ...


# The analyzer creates these structural specializations for variadic calls.
def _cache_tuple_object() -> tuple[object]: ...


def _cache_dict_object_object() -> dict[object, object]: ...
