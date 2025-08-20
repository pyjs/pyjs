from pyjs import js


class _object:

    def __init__(self):
        pass

    # ast.Compare

    @js(inline="{self} === {other}")
    def __is__(self, other: object) -> bool:
        pass

    @js(inline="{self} !== {other}")
    def __is_not__(self, other: object) -> bool:
        pass

    @js(inline="{self} === {other}")
    def __eq__(self, other: object) -> bool:
        pass

    @js(inline="{self} !== {other}")
    def __ne__(self, other: object) -> bool:
        pass


class _type:
    pass


class _tuple[T](_object):
    pass


class _Generic(_object):
    pass


from collections.abc import Iterable


class _Iterable[V](_object):
    pass


class _NoneType(_object):
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
    def __bool__(self) -> bool:
        pass

    # ast.Compare

    @js(inline=int_op("lt", "<"))
    def __lt__(self, other: int) -> bool:
        pass

    @js(inline=int_op("le", "<="))
    def __le__(self, other: int) -> bool:
        pass

    @js(inline=int_op("gt", ">"))
    def __gt__(self, other: int) -> bool:
        pass

    @js(inline=int_op("ge", ">="))
    def __ge__(self, other: int) -> bool:
        pass

    @js(inline=int_op("eq", "=="))
    def __eq__(self, other: int) -> bool:
        pass

    @js(inline=int_op("ne", "!="))
    def __ne__(self, other: int) -> bool:
        pass

    # ast.BinOp

    @js(inline=int_op("add", "+"))
    def __add__(self, other: int) -> int:
        pass
    @js(inline=int_op("radd", "+", True))
    def __radd__(self, other: int) -> int:
        pass

    @js(inline=int_op("sub", "-"))
    def __sub__(self, other: int) -> int:
        pass
    @js(inline=int_op("rsub", "-", True))
    def __rsub__(self, other: int) -> int:
        pass

    @js(inline=int_op("mul", "*"))
    def __mul__(self, other: int) -> int:
        pass
    @js(inline=int_op("rmul", "*", True))
    def __rmul__(self, other: int) -> int:
        pass

    @js(inline=int_op("truediv", "/"))
    def __truediv__(self, other: int) -> int:
        pass
    @js(inline=int_op("rtruediv", "/", True))
    def __rtruediv__(self, other: int) -> int:
        pass

    @js(inline=int_op("floordiv", "/", wrap="Math.floor"))
    def __floordiv__(self, other: int) -> int:
        pass
    @js(inline=int_op("rfloordiv", "/", True, wrap="Math.floor"))
    def __rfloordiv__(self, other: int) -> int:
        pass

    @js(inline=int_op("mod", "**"))
    def __mod__(self, other: int) -> int:
        pass
    @js(inline=int_op("rmod", "**", True))
    def __rmod__(self, other: int) -> int:
        pass


class _bool(_int):

    @js(inline="Boolean({arg})")
    def __init__(self, arg: object):
        pass


class _str(_object):

    @js
    def __init__(self, other: object = 0):
        super().__init__()
    @__init__.inline
    def init_inline(self, other, _arg_types, **kwargs):
        #arg_type = _arg_types[0].name
        #if arg_type == "int":
        return f"String({other})"

    @js(inline="{self}")
    def __bool__(self) -> bool:
        pass

    @js(inline="{self} + {other}")
    def __add__(self, other: str) -> str:
        pass

    @js(inline="{self}.repeat({times})")
    def __mul__(self, times: int) -> str:
        pass

    @js(inline="{self}.repeat({times})")
    def __rmul__(self, times: int) -> str:
        pass

    @js(inline="{self}.trim()")
    def strip(self) -> str:
        pass


class _list[V](_object):

    @js(inline="{self}.push({item})")
    def append(self, item: V) -> None:
        pass

    @js(inline="{self}.push(...{item})")
    def extend(self, item: list[V]) -> None:
        pass

    @js(inline="{self}.splice({index}, 0, {item})")
    def insert(self, index: int, item: V) -> None:
        pass

    @js(inline="({self}.indexOf({item}) !== -1 && {self}.splice({self}.indexOf({item}), 1))")
    def remove(self, item: V) -> None:
        pass

    def pop(self) -> V:
        pass

    @js(inline="{self}.length")
    def __bool__(self) -> bool:
        pass

    @js
    def __add__(self, other: list[V]) -> list[V]:
        pass
    @__add__.inline
    def __add__(self, other, _arg_types, **kwargs):
        arg_type = _arg_types[0].name
        if arg_type == "list":
            return f"{self}.concat({other})"
        return NotImplemented

    @js(inline="{self}[{idx}]")
    def __getitem__(self, idx: int) -> V:
        pass

    @js(inline="{self}[{idx}] = {value}")
    def __setitem__(self, idx: int, value: V) -> V:
        pass


class _dict[K, V](_object):

    def keys(self) -> Iterable[K]:
        pass

    def values(self) -> Iterable[V]:
        pass

    @js(inline="{self}.entries()")
    def items(self) -> Iterable[tuple[K,V]]:
        pass

    #@js(inline="{self}.push({item})")
    def set(self, key: K, value: V):
        pass

    @js(inline="{self}?.size")
    def __bool__(self) -> bool:
        pass

    @js(inline="{self}[{key}]")
    def __getitem__(self, key: K) -> V:
        pass

    @js(inline="{self}.has({key}) ? {self}[{key}] : {default}")
    def get(self, key: K, default: V) -> V:
        pass

    @js(inline="{self}[{key}] = {value}")
    def __setitem__(self, key: K, value: V) -> V:
        pass


@js
def _len(obj: object) -> int:
    pass
@_len.inline
def _len(obj, _arg_types, **kwargs):
    arg_type = _arg_types[0].generic_name
    if arg_type in ("str", "list"):
        return f"{obj}.length"
    elif arg_type == "dict":
        return f"{obj}.size"
    return NotImplemented


@js
def _isinstance(obj: object, obj_type: type) -> bool:
    pass
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
    else:
        return f"({obj} instanceof {obj_type})"


@js(inline="{attr} in {object}")
def _hasattr(obj: object, attr: str) -> bool:
    pass


@js(inline="callable")
class _callable:
    pass


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
def _bin(num: int) -> str:
    pass


@js(inline="('0o'+({num}).toString(8))")
def _oct(num: int) -> str:
    pass


@js(inline="('0x'+({num}).toString(16))")
def _hex(num: int) -> str:
    pass


# pre-generate tuple[object] and dict[object,object] concrete
# classes as these are used as types for *args, **kwargs in
# functions parameters
def _cache_tuple_object() -> tuple[object]:
    pass
def _cache_dict_object_object() -> dict[object,object]:
    pass
