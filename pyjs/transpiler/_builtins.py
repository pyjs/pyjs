from collections.abc import Iterable

from pyjs import js
from pyjs.decorators import dunder_dispatch


def identity_op(default_op: str, none_op: str):
    def inline(self, other, _arg_types, **kwargs):
        other_type = _arg_types[0]
        compares_with_none = (
            self == "null"
            or getattr(other_type, "name", None) == "NoneType"
        )
        operator = none_op if compares_with_none else default_op
        return f"{self} {operator} {other}"

    return inline


class _object:
    def __init__(self):
        pass

    # ast.Compare

    @js(inline=identity_op("===", "=="))
    def __is__(self, other: object) -> bool: ...

    @js(inline=identity_op("!==", "!="))
    def __is_not__(self, other: object) -> bool: ...

    @js(inline="{self} === {other}")
    def __eq__(self, other: object) -> bool: ...

    @js(inline="{self} !== {other}")
    def __ne__(self, other: object) -> bool: ...


class _type: ...


class _tuple[T](_object):
    @js(inline="{self}.length")
    def __len__(self) -> int: ...


class _Generic(_object): ...


class _Iterable[V](_object): ...


class _Awaitable[T](_object): ...


class _NoneType(_object): ...


class _Exception(_object):
    def __init__(self, message: str = ""):
        self.message = message
        self.stack: str | None = None


class _ValueError(_Exception):
    pass


class _TypeError(_Exception):
    pass


def int_op(name, op, r=False, wrap=""):
    def inline(self, other, _arg_types, **kwargs):
        arg_type = _arg_types[0].name
        if arg_type in ("int", "bool"):
            src = []
            if wrap:
                src.append(f"{wrap}(")
            if r:
                src.append(f"{other} {op} {self}")
            else:
                src.append(f"{self} {op} {other}")
            if wrap:
                src.append(")")
            return "".join(src)
        return NotImplemented

    return inline


def float_op(op, r=False):
    def inline(self, other, _arg_types, **kwargs):
        if _arg_types[0].name not in ("int", "float", "bool"):
            return NotImplemented
        return f"{other} {op} {self}" if r else f"{self} {op} {other}"

    return inline


def str_split(self, _arg_strs, **kwargs):
    if _arg_strs:
        return f"{self}.split({_arg_strs[0]})"
    return f"(value => value.trim() ? value.trim().split(/\\s+/) : [])({self})"


class _int(_object):
    @js
    def __init__(self, other: object = 0):
        super().__init__()

    @__init__.inline
    def init_inline(self, other, _arg_types, **kwargs):
        arg_type = _arg_types[0].name
        if arg_type == "str":
            return f"parseInt({other}, 10)"

    @js(inline="{self}")
    def __bool__(self) -> bool: ...

    @js(inline="Math.abs({self})")
    def __abs__(self) -> int: ...

    @js(inline="Math.round({self})")
    def __round__(self) -> int: ...

    # ast.Compare

    @js(inline=int_op("lt", "<"))
    def __lt__(self, other: int) -> bool: ...

    @js(inline=int_op("le", "<="))
    def __le__(self, other: int) -> bool: ...

    @js(inline=int_op("gt", ">"))
    def __gt__(self, other: int) -> bool: ...

    @js(inline=int_op("ge", ">="))
    def __ge__(self, other: int) -> bool: ...

    @js(inline=int_op("eq", "=="))
    def __eq__(self, other: int) -> bool: ...

    @js(inline=int_op("ne", "!="))
    def __ne__(self, other: int) -> bool: ...

    # ast.BinOp

    @js(inline=int_op("add", "+"))
    def __add__(self, other: int) -> int: ...
    @js(inline=int_op("radd", "+", True))
    def __radd__(self, other: int) -> int: ...

    @js(inline=int_op("sub", "-"))
    def __sub__(self, other: int) -> int: ...
    @js(inline=int_op("rsub", "-", True))
    def __rsub__(self, other: int) -> int: ...

    @js(inline=int_op("mul", "*"))
    def __mul__(self, other: int) -> int: ...
    @js(inline=int_op("rmul", "*", True))
    def __rmul__(self, other: int) -> int: ...

    @js(inline=int_op("truediv", "/"))
    def __truediv__(self, other: int) -> int: ...
    @js(inline=int_op("rtruediv", "/", True))
    def __rtruediv__(self, other: int) -> int: ...

    @js(inline=int_op("floordiv", "/", wrap="Math.floor"))
    def __floordiv__(self, other: int) -> int: ...
    @js(inline=int_op("rfloordiv", "/", True, wrap="Math.floor"))
    def __rfloordiv__(self, other: int) -> int: ...

    @js(inline=int_op("mod", "%"))
    def __mod__(self, other: int) -> int: ...
    @js(inline=int_op("rmod", "%", True))
    def __rmod__(self, other: int) -> int: ...

    @js(inline=int_op("pow", "**"))
    def __pow__(self, other: int) -> int: ...
    @js(inline=int_op("rpow", "**", True))
    def __rpow__(self, other: int) -> int: ...

    @js(inline=int_op("or", "|"))
    def __or__(self, other: int) -> int: ...

    @js(inline=int_op("ror", "|", True))
    def __ror__(self, other: int) -> int: ...


class _bool(_int):
    @js(inline="Boolean({arg})")
    def __init__(self, arg: object):
        super().__init__(arg)

    @js(inline="Boolean({self} | {other})")
    def __or__(self, other: bool) -> bool: ...

    @js(inline="Boolean({other} | {self})")
    def __ror__(self, other: bool) -> bool: ...


class _float(_object):
    @js(inline="Number({other})")
    def __init__(self, other: object = 0):
        super().__init__()

    @js(inline="{self}")
    def __bool__(self) -> bool: ...

    @js(inline="Math.abs({self})")
    def __abs__(self) -> float: ...

    @js(inline="Math.round({self})")
    def __round__(self) -> int: ...

    @js(inline=float_op("<"))
    def __lt__(self, other: int | float | bool) -> bool: ...

    @js(inline=float_op("<="))
    def __le__(self, other: int | float | bool) -> bool: ...

    @js(inline=float_op(">"))
    def __gt__(self, other: int | float | bool) -> bool: ...

    @js(inline=float_op(">="))
    def __ge__(self, other: int | float | bool) -> bool: ...

    @js(inline=float_op("==="))
    def __eq__(self, other: int | float | bool) -> bool: ...

    @js(inline=float_op("!=="))
    def __ne__(self, other: int | float | bool) -> bool: ...

    @js(inline=float_op("+"))
    def __add__(self, other: int | float | bool) -> float: ...

    @js(inline=float_op("+", True))
    def __radd__(self, other: int | float | bool) -> float: ...

    @js(inline=float_op("-"))
    def __sub__(self, other: int | float | bool) -> float: ...

    @js(inline=float_op("-", True))
    def __rsub__(self, other: int | float | bool) -> float: ...

    @js(inline=float_op("*"))
    def __mul__(self, other: int | float | bool) -> float: ...

    @js(inline=float_op("*", True))
    def __rmul__(self, other: int | float | bool) -> float: ...

    @js(inline=float_op("/"))
    def __truediv__(self, other: int | float | bool) -> float: ...

    @js(inline=float_op("/", True))
    def __rtruediv__(self, other: int | float | bool) -> float: ...


class _str(_object):
    @js(inline="String({other})")
    def __init__(self, other: object = 0):
        super().__init__()

    @js(inline="{self}")
    def __bool__(self) -> bool: ...

    @js(inline="{self}.length")
    def __len__(self) -> int: ...

    @js(inline="{self} + {other}")
    def __add__(self, other: str) -> str: ...

    @js(inline="{self}.repeat({times})")
    def __mul__(self, times: int) -> str: ...

    @js(inline="{self}.repeat({times})")
    def __rmul__(self, times: int) -> str: ...

    @js(inline="{self}.trim()")
    def strip(self) -> str: ...

    @js(inline="{self}.toLowerCase()")
    def lower(self) -> str: ...

    @js(inline="{self}.substring({start}, {end})")
    def substring(self, start: int, end: int) -> str: ...

    @js(inline=str_split)
    def split(self, sep: str | None = None) -> list[str]: ...

    @js(inline="{values}.join({self})")
    def join(self, values: list[str]) -> str: ...

    @js(inline="{self}.includes({item})")
    def __contains__(self, item: str) -> bool: ...

    @js(inline="{self}[{idx}]")
    def __getitem__(self, idx: int) -> str: ...


class _list[V](_object):
    @js(inline="{self}.length")
    def __len__(self) -> int: ...

    @js(inline="{self}.push({item})")
    def append(self, item: V) -> None: ...

    @js(inline="{self}.push(...{item})")
    def extend(self, item: list[V]) -> None: ...

    @js(inline="{self}.splice({index}, 0, {item})")
    def insert(self, index: int, item: V) -> None: ...

    @js(
        inline="({self}.indexOf({item}) !== -1 && {self}.splice({self}.indexOf({item}), 1))"
    )
    def remove(self, item: V) -> None: ...

    def pop(self) -> V: ...

    @js(inline="{self}.length")
    def __bool__(self) -> bool: ...

    @js
    def __add__(self, other: list[V]) -> list[V]: ...
    @__add__.inline
    def __add__(self, other, _arg_types, **kwargs):
        arg_type = _arg_types[0].name
        if arg_type == "list":
            return f"{self}.concat({other})"
        return NotImplemented

    @js(inline="{self}[{idx}]")
    def __getitem__(self, idx: int) -> V: ...

    @js(inline="{self}[{idx}] = {value}")
    def __setitem__(self, idx: int, value: V) -> V: ...

    @js(inline="{self}.includes({item})")
    def __contains__(self, item: V) -> bool: ...


class _dict[K, V](_object):
    @js(inline="{self}.size")
    def __len__(self) -> int: ...

    def keys(self) -> Iterable[K]: ...

    def values(self) -> Iterable[V]: ...

    @js(inline="{self}.entries()")
    def items(self) -> Iterable[tuple[K, V]]: ...

    # @js(inline="{self}.push({item})")
    def set(self, key: K, value: V): ...

    @js(inline="{self}?.size")
    def __bool__(self) -> bool: ...

    @js(inline="{self}[{key}]")
    def __getitem__(self, key: K) -> V: ...

    @js(inline="{self}.has({key}) ? {self}[{key}] : {default}")
    def get(self, key: K, default: V) -> V: ...

    @js(
        inline="((mapping, key) => {{ const value = mapping.get(key); "
        "mapping.delete(key); return value; }})({self}, {key})"
    )
    def pop(self, key: K) -> V: ...

    @js(inline="{self}[{key}] = {value}")
    def __setitem__(self, key: K, value: V) -> V: ...

    @js(inline="{self}.has({key})")
    def __contains__(self, key: K) -> bool: ...


@dunder_dispatch("__len__")
def _len(obj: object) -> int: ...


@dunder_dispatch("__abs__")
def _abs(number: int | float | bool) -> int | float: ...


def range_inline(_arg_strs, **kwargs):
    if not _arg_strs[1:]:
        start, stop, step = "0", _arg_strs[0], "1"
    elif not _arg_strs[2:]:
        start, stop, step = _arg_strs[0], _arg_strs[1], "1"
    else:
        start, stop, step = _arg_strs
    return (
        "(function*(start,stop,step){for(let i=start;"
        "step>0?i<stop:i>stop;i+=step)yield i})"
        f"({start},{stop},{step})"
    )


@js(inline=range_inline)
def _range(start: int, stop: int | None = None, step: int = 1) -> Iterable[int]: ...


def sum_inline(values, start="0", **kwargs):
    return (
        "((values,total)=>{for(const value of values)total+=value;return total;})"
        f"({values},{start})"
    )


@js(inline=sum_inline)
def _sum(values: Iterable[int], start: int = 0) -> int: ...


@dunder_dispatch("__round__")
def _round(number: int | float | bool) -> int: ...


@js
def _isinstance(obj: object, obj_type: type) -> bool: ...
@_isinstance.inline
def _isinstance(obj, obj_type, **kwargs):
    if obj_type == "list":
        return f"Array.isArray({obj})"
    elif obj_type == "dict":
        return f"({obj} instanceof Map)"
    elif obj_type == "int":
        return f"Number.isInteger({obj})"
    elif obj_type == "float":
        return f"(typeof {obj} === 'number' && !Number.isInteger({obj}))"
    elif obj_type == "str":
        return f"(typeof {obj} === 'string')"
    elif obj_type == "bool":
        return f"(typeof {obj} === 'boolean')"
    elif obj_type == "Exception":
        return f"({obj} instanceof Error)"
    else:
        return f"({obj} instanceof {obj_type})"


@js(inline="{attr} in {object}")
def _hasattr(obj: object, attr: str) -> bool: ...


@js(inline="callable")
class _callable:
    def __call__(self, *args: object) -> object: ...


def _classmethod():
    pass


@js
def _print(obj: object) -> None:
    pass


@_print.inline
def _print(obj, _arg_types, **kwargs):
    arg_type = _arg_types[0].name
    if arg_type == "iter":
        obj = f"...{obj}"
    return f"console.log({obj})"


@js(inline="('0b'+({num}).toString(2))")
def _bin(num: int) -> str: ...


@js(inline="('0o'+({num}).toString(8))")
def _oct(num: int) -> str: ...


@js(inline="('0x'+({num}).toString(16))")
def _hex(num: int) -> str: ...


# pre-generate tuple[object] and dict[object,object] concrete
# classes as these are used as types for *args, **kwargs in
# functions parameters
def _cache_tuple_object() -> tuple[object]: ...
def _cache_dict_object_object() -> dict[object, object]: ...
