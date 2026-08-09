from collections.abc import Iterable
from functools import partial

import pyjs.python as python_runtime
from pyjs import js
from pyjs.decorators import dunder_dispatch


def type_name(value_type):
    return getattr(value_type, "generic_name", None) or value_type.name


def inherits_type(value_type, expected_name):
    while value_type is not None:
        if value_type.name == expected_name:
            return True
        value_type = getattr(value_type, "super", None)
    return False


def repr_value(self, container=None, **kwargs):
    render = (
        "const render=(value)=>{"
        "if(value===null)return 'None';"
        "if(typeof value==='boolean')return value?'True':'False';"
        "if(typeof value==='string'){"
        "const quote=value.includes(\"'\")&&!value.includes('\\\"')?'\\\"':\"'\";"
        "const escaped=value.replaceAll('\\\\','\\\\\\\\')"
        ".replaceAll('\\n','\\\\n').replaceAll('\\r','\\\\r')"
        ".replaceAll('\\t','\\\\t').replaceAll(quote,'\\\\'+quote);"
        "return quote+escaped+quote;}"
        "if(Array.isArray(value))return '['+value.map(render).join(', ')+']';"
        "if(value instanceof Map)return '{'+Array.from(value.entries(),"
        "([key,item])=>render(key)+': '+render(item)).join(', ')+'}';"
        "if(typeof value?.__repr__==='function')return value.__repr__();"
        "return String(value);};"
    )
    if container == "tuple":
        result = (
            "const parts=value.map(render);"
            "return '('+parts.join(', ')+(parts.length===1?',':'')+')';"
        )
    else:
        result = "return render(value);"
    return f"((value)=>{{{render}{result}}})({self})"


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


def sequence_equality(self, other, _arg_types, sequence_type, negate=False, **kwargs):
    other_type = type_name(_arg_types[0])
    if other_type in {"list", "tuple"} and other_type != sequence_type:
        comparison = "false"
    else:
        comparison = (
            "((left,right)=>{const equal=(a,b)=>Array.isArray(a)&&Array.isArray(b)"
            "?a.length===b.length&&a.every((value,index)=>equal(value,b[index]))"
            ":a===b;return equal(left,right);})"
            f"({self},{other})"
        )
    return f"!{comparison}" if negate else comparison


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

    @js(inline="String({self})")
    def __str__(self) -> str: ...

    @js(inline="String({self})")
    def __repr__(self) -> str: ...


class _type: ...


class _tuple[T](_object):
    @js(inline="{self}.length")
    def __len__(self) -> int: ...

    @js(inline=partial(sequence_equality, sequence_type="tuple"))
    def __eq__(self, other: object) -> bool: ...

    @js(inline=partial(sequence_equality, sequence_type="tuple", negate=True))
    def __ne__(self, other: object) -> bool: ...

    @js(inline=partial(repr_value, container="tuple"))
    def __str__(self) -> str: ...

    @js(inline=partial(repr_value, container="tuple"))
    def __repr__(self) -> str: ...


class _Generic(_object): ...


class _Iterable[V](_object): ...


class _Awaitable[T](_object): ...


class _NoneType(_object):
    @js(inline="'None'")
    def __str__(self) -> str: ...

    @js(inline="'None'")
    def __repr__(self) -> str: ...


class _Exception(_object):
    def __init__(self, message: str = ""):
        self.message = message
        self.stack: str | None = None

    @js(inline="{self}.message")
    def __str__(self) -> str: ...


class _ValueError(_Exception):
    pass


class _TypeError(_Exception):
    pass


def int_op(op, r=False, wrap=""):
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


def modulo_op(self, other, reverse=False, **kwargs):
    left, right = (other, self) if reverse else (self, other)
    return (
        "((left,right)=>{if(right===0)throw new Error('division by zero');"
        f"return ((left%right)+right)%right;}})({left},{right})"
    )


def division_op(self, other, reverse=False, floor=False, **kwargs):
    left, right = (other, self) if reverse else (self, other)
    result = "Math.floor(left/right)" if floor else "left/right"
    return (
        "((left,right)=>{if(right===0)throw new Error('division by zero');"
        f"return {result};}})({left},{right})"
    )


def bool_init(arg="false", _arg_types=(), **kwargs):
    if not _arg_types:
        return "false"
    arg_type = _arg_types[0]
    arg_type_name = type_name(arg_type)
    if arg_type_name in {"list", "str", "tuple"}:
        return f"{arg}.length!==0"
    if arg_type_name == "dict":
        return f"{arg}.size!==0"
    if inherits_type(arg_type, "typed_dict"):
        return f"Object.keys({arg}).length!==0"
    return f"Boolean({arg})"


def int_init(other="0", _arg_types=(), **kwargs):
    if not _arg_types:
        return "0"
    if _arg_types[0].name == "str":
        return (
            "((value)=>{const text=value.trim();"
            "if(!/^[+-]?\\d(?:_?\\d)*$/.test(text))"
            "throw new Error(`invalid literal for int() with base 10: '${value}'`);"
            "const number=Number.parseInt(text.replaceAll('_',''),10);"
            "return number===0?0:number;})"
            f"({other})"
        )
    return f"Math.trunc(Number({other}))"


def float_init(other="0", _arg_types=(), **kwargs):
    if not _arg_types:
        return "0"
    if _arg_types[0].name == "str":
        return (
            "((value)=>{const text=value.trim();"
            "if(/^[+-]?nan$/i.test(text))return NaN;"
            "if(/^[+-]?inf(?:inity)?$/i.test(text))"
            "return text[0]==='-'?-Infinity:Infinity;"
            "if(!/^[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:e[+-]?\\d+)?$/i"
            ".test(text))throw new Error(`could not convert string to float: '${value}'`);"
            "return Number(text);})"
            f"({other})"
        )
    return f"Number({other})"


def round_half_even(self, **kwargs):
    return (
        "((value)=>{const floor=Math.floor(value);return value-floor===0.5"
        "?(floor%2===0?floor:floor+1):Math.round(value);})"
        f"({self})"
    )


def str_split(self, _arg_strs, **kwargs):
    if _arg_strs:
        sep = _arg_strs[0]
        if not _arg_strs[1:]:
            return f"{self}.split({sep})"
        maxsplit = _arg_strs[1]
        return (
            "((value,sep,maxsplit)=>{if(maxsplit<0)return value.split(sep);"
            "const parts=[];let start=0;for(let count=0;count<maxsplit;count++){"
            "const index=value.indexOf(sep,start);if(index<0)break;"
            "parts.push(value.slice(start,index));start=index+sep.length;}"
            "parts.push(value.slice(start));return parts;})"
            f"({self},{sep},{maxsplit})"
        )
    return (
        "((value)=>{const trimmed=value.trim();"
        "return trimmed?trimmed.split(/\\s+/):[];})"
        f"({self})"
    )


def list_pop(self, index="-1", **kwargs):
    return f"{self}.splice({index},1)[0]"


def list_remove(self, item, **kwargs):
    return (
        "((values,item)=>{const index=values.indexOf(item);"
        "if(index<0)throw new Error('list.remove(x): x not in list');"
        f"values.splice(index,1);}})({self},{item})"
    )


def slice_value(self, slice=None, start="null", stop="null", step="null", **kwargs):
    if step in {"null", "1"}:
        if start == "null" and stop == "null":
            return f"{self}.slice()"
        if start == "null":
            start = "0"
        if stop == "null":
            return f"{self}.slice({start})"
        return f"{self}.slice({start},{stop})"
    return f"{slice}({self},{start},{stop},{step})"


def list_set_slice(
    self,
    values,
    set_slice,
    start="null",
    stop="null",
    step="null",
    **kwargs,
):
    return f"{set_slice}({self},{values},{start},{stop},{step})"


def list_delete_slice(
    self,
    delete_slice,
    start="null",
    stop="null",
    step="null",
    **kwargs,
):
    return f"{delete_slice}({self},{start},{stop},{step})"


def list_delete_item(self, idx, delete_item, **kwargs):
    return f"{delete_item}({self},{idx})"


def dict_delete_item(self, key, delete_item, **kwargs):
    return f"{delete_item}({self},{key})"


def typed_dict_init(_arg_strs, _arg_types, _keyword_strs, **kwargs):
    if _arg_strs[1:]:
        raise TypeError("TypedDict accepts at most one positional mapping")
    entries = []
    if _arg_strs:
        value = _arg_strs[0]
        arg_type = _arg_types[0]
        arg_type_name = type_name(arg_type)
        if arg_type_name == "dict":
            value = f"Object.fromEntries({value})"
        elif not inherits_type(arg_type, "typed_dict"):
            value = f"({value} instanceof Map?Object.fromEntries({value}):{value})"
        entries.append(f"...{value}")
    entries.extend(f"{key}: {value}" for key, value in _keyword_strs.items())
    return "({" + ", ".join(entries) + "})"


def typed_dict_get(self, key, default="null", **kwargs):
    return (
        "((mapping,key,fallback)=>Object.hasOwn(mapping,key)"
        f"?mapping[key]:fallback)({self},{key},{default})"
    )


def dict_get(self, key, default, **kwargs):
    return (
        "((mapping,key,fallback)=>mapping.has(key)"
        f"?mapping.get(key):fallback)({self},{key},{default})"
    )


class _int(_object):
    @js(inline=int_init)
    def __init__(self, other: object = 0): ...

    @js(inline="{self}")
    def __bool__(self) -> bool: ...

    @js(inline="String({self})")
    def __str__(self) -> str: ...

    @js(inline="String({self})")
    def __repr__(self) -> str: ...

    @js(inline="Math.abs({self})")
    def __abs__(self) -> int: ...

    @js(inline="Math.round({self})")
    def __round__(self) -> int: ...

    # ast.Compare

    @js(inline=int_op("<"))
    def __lt__(self, other: int) -> bool: ...

    @js(inline=int_op("<="))
    def __le__(self, other: int) -> bool: ...

    @js(inline=int_op(">"))
    def __gt__(self, other: int) -> bool: ...

    @js(inline=int_op(">="))
    def __ge__(self, other: int) -> bool: ...

    @js(inline=int_op("=="))
    def __eq__(self, other: int) -> bool: ...

    @js(inline=int_op("!="))
    def __ne__(self, other: int) -> bool: ...

    # ast.BinOp

    @js(inline=int_op("+"))
    def __add__(self, other: int) -> int: ...
    @js(inline=int_op("+", True))
    def __radd__(self, other: int) -> int: ...

    @js(inline=int_op("-"))
    def __sub__(self, other: int) -> int: ...
    @js(inline=int_op("-", True))
    def __rsub__(self, other: int) -> int: ...

    @js(inline=int_op("*"))
    def __mul__(self, other: int) -> int: ...
    @js(inline=int_op("*", True))
    def __rmul__(self, other: int) -> int: ...

    @js(inline=division_op)
    def __truediv__(self, other: int) -> float: ...
    @js(inline=partial(division_op, reverse=True))
    def __rtruediv__(self, other: int) -> float: ...

    @js(inline=partial(division_op, floor=True))
    def __floordiv__(self, other: int) -> int: ...
    @js(inline=partial(division_op, reverse=True, floor=True))
    def __rfloordiv__(self, other: int) -> int: ...

    @js(inline=modulo_op)
    def __mod__(self, other: int) -> int: ...
    @js(inline=partial(modulo_op, reverse=True))
    def __rmod__(self, other: int) -> int: ...

    @js(inline=int_op("**"))
    def __pow__(self, other: int) -> int: ...
    @js(inline=int_op("**", True))
    def __rpow__(self, other: int) -> int: ...

    @js(inline=int_op("|"))
    def __or__(self, other: int) -> int: ...

    @js(inline=int_op("|", True))
    def __ror__(self, other: int) -> int: ...


class _bool(_int):
    @js(inline=bool_init)
    def __init__(self, arg: object = False):
        super().__init__(arg)

    @js(inline="({self}?'True':'False')")
    def __str__(self) -> str: ...

    @js(inline="({self}?'True':'False')")
    def __repr__(self) -> str: ...

    @js(inline="Boolean({self} | {other})")
    def __or__(self, other: bool) -> bool: ...

    @js(inline="Boolean({other} | {self})")
    def __ror__(self, other: bool) -> bool: ...


class _float(_object):
    @js(inline=float_init)
    def __init__(self, other: object = 0): ...

    @js(inline="{self}")
    def __bool__(self) -> bool: ...

    @js(inline="String({self})")
    def __str__(self) -> str: ...

    @js(inline="String({self})")
    def __repr__(self) -> str: ...

    @js(inline="Math.abs({self})")
    def __abs__(self) -> float: ...

    @js(inline=round_half_even)
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

    @js(inline=division_op)
    def __truediv__(self, other: int | float | bool) -> float: ...

    @js(inline=partial(division_op, reverse=True))
    def __rtruediv__(self, other: int | float | bool) -> float: ...


@dunder_dispatch("__str__")
class _str(_object):
    @js(inline="''")
    def __init__(self, other: object = ""):
        super().__init__()

    @js(inline="{self}")
    def __bool__(self) -> bool: ...

    @js(inline="{self}")
    def __str__(self) -> str: ...

    @js(inline=repr_value)
    def __repr__(self) -> str: ...

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
    def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]: ...

    @js(inline="{values}.join({self})")
    def join(self, values: list[str]) -> str: ...

    @js(inline="{self}.includes({item})")
    def __contains__(self, item: str) -> bool: ...

    @js(inline="{self}.at({idx})")
    def __getitem__(self, idx: int) -> str: ...

    @js(inline=slice_value, dependencies={"slice": python_runtime.slice_string})
    def __slice__(
        self,
        start: int | None = None,
        stop: int | None = None,
        step: int | None = None,
    ) -> str: ...


class _list[V](_object):
    @js(inline="{self}.length")
    def __len__(self) -> int: ...

    @js(inline="{self}.push({item})")
    def append(self, item: V) -> None: ...

    @js(inline="{self}.push(...{item})")
    def extend(self, item: list[V]) -> None: ...

    @js(inline="{self}.splice({index}, 0, {item})")
    def insert(self, index: int, item: V) -> None: ...

    @js(inline=list_remove)
    def remove(self, item: V) -> None: ...

    @js(inline=list_pop)
    def pop(self, index: int = -1) -> V: ...

    @js(inline="{self}.length")
    def __bool__(self) -> bool: ...

    @js(inline=repr_value)
    def __str__(self) -> str: ...

    @js(inline=repr_value)
    def __repr__(self) -> str: ...

    @js(inline=partial(sequence_equality, sequence_type="list"))
    def __eq__(self, other: object) -> bool: ...

    @js(inline=partial(sequence_equality, sequence_type="list", negate=True))
    def __ne__(self, other: object) -> bool: ...

    @js
    def __add__(self, other: list[V]) -> list[V]: ...
    @__add__.inline
    def __add__(self, other, _arg_types, **kwargs):
        arg_type = _arg_types[0].name
        if arg_type == "list":
            return f"{self}.concat({other})"
        return NotImplemented

    @js(inline="{self}.at({idx})")
    def __getitem__(self, idx: int) -> V: ...

    @js(inline=slice_value, dependencies={"slice": python_runtime.slice_list})
    def __slice__(
        self,
        start: int | None = None,
        stop: int | None = None,
        step: int | None = None,
    ) -> list[V]: ...

    @js(inline="{self}[{idx}] = {value}")
    def __setitem__(self, idx: int, value: V) -> V: ...

    @js(
        inline=list_set_slice,
        dependencies={"set_slice": python_runtime.set_list_slice},
    )
    def __setslice__(
        self,
        values: list[V],
        start: int | None = None,
        stop: int | None = None,
        step: int | None = None,
    ) -> None: ...

    @js(
        inline=list_delete_item,
        dependencies={"delete_item": python_runtime.delete_list_item},
    )
    def __delitem__(self, idx: int) -> None: ...

    @js(
        inline=list_delete_slice,
        dependencies={"delete_slice": python_runtime.delete_list_slice},
    )
    def __delslice__(
        self,
        start: int | None = None,
        stop: int | None = None,
        step: int | None = None,
    ) -> None: ...

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

    @js(inline="{self}.size")
    def __bool__(self) -> bool: ...

    @js(inline=repr_value)
    def __str__(self) -> str: ...

    @js(inline=repr_value)
    def __repr__(self) -> str: ...

    @js(inline="{self}.get({key})")
    def __getitem__(self, key: K) -> V: ...

    @js(inline=dict_get)
    def get(self, key: K, default: V) -> V: ...

    @js(
        inline="((mapping, key) => {{ const value = mapping.get(key); "
        "mapping.delete(key); return value; }})({self}, {key})"
    )
    def pop(self, key: K) -> V: ...

    @js(inline="{self}.set({key}, {value})")
    def __setitem__(self, key: K, value: V) -> V: ...

    @js(
        inline=dict_delete_item,
        dependencies={"delete_item": python_runtime.delete_dict_item},
    )
    def __delitem__(self, key: K) -> None: ...

    @js(inline="{self}.has({key})")
    def __contains__(self, key: K) -> bool: ...


class _typed_dict(_object):
    @js
    def __init__(self, values: object | None = None, **fields: object): ...

    __init__.inline(typed_dict_init)

    @js(inline="{self}[{key}]")
    def __getitem__(self, key: str) -> object: ...

    @js(inline="{self}[{key}] = {value}")
    def __setitem__(self, key: str, value: object) -> None: ...

    @js(inline=typed_dict_get)
    def get(self, key: str, default: object = None) -> object: ...

    @js(inline="Object.keys({self})")
    def keys(self) -> Iterable[str]: ...

    @js(inline="Object.values({self})")
    def values(self) -> Iterable[object]: ...

    @js(inline="Object.entries({self})")
    def items(self) -> Iterable[tuple[str, object]]: ...

    @js(inline="Object.keys({self}).length")
    def __len__(self) -> int: ...

    @js(inline="Object.keys({self}).length > 0")
    def __bool__(self) -> bool: ...

    @js(inline="Object.hasOwn({self}, {key})")
    def __contains__(self, key: str) -> bool: ...


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


def sum_inline(values, _arg_types, start="0", **kwargs):
    value_type = _arg_types[0]
    if type_name(value_type) in {"list", "tuple"}:
        return f"({values}).reduce((total,value)=>total+value,{start})"
    return (
        "((values,total)=>{for(const value of values)total+=value;return total;})"
        f"({values},{start})"
    )


@js(inline=sum_inline)
def _sum(values: Iterable[int], start: int = 0) -> int: ...


@dunder_dispatch("__round__")
def _round(number: int | float | bool) -> int: ...


@dunder_dispatch("__repr__")
def _repr(obj: object) -> str: ...


@js
def _isinstance(obj: object, obj_type: type) -> bool: ...
@_isinstance.inline
def _isinstance(obj, obj_type, **kwargs):
    if obj_type == "list":
        return f"Array.isArray({obj})"
    elif obj_type == "dict":
        return f"({obj} instanceof Map)"
    elif obj_type == "int":
        return (
            "((value)=>typeof value==='boolean'||Number.isInteger(value))"
            f"({obj})"
        )
    elif obj_type == "float":
        return (
            "((value)=>typeof value==='number'&&!Number.isInteger(value))"
            f"({obj})"
        )
    elif obj_type == "str":
        return f"(typeof {obj} === 'string')"
    elif obj_type == "bool":
        return f"(typeof {obj} === 'boolean')"
    elif obj_type == "Exception":
        return f"({obj} instanceof Error)"
    else:
        return f"({obj} instanceof {obj_type})"


@js(inline="{attr} in {obj}")
def _hasattr(obj: object, attr: str) -> bool: ...


@js(inline="callable")
class _callable:
    def __call__(self, *args: object) -> object: ...


def _classmethod():
    pass


@js
def _print(*objects: object, sep: str = " ", end: str = "\n") -> None:
    pass


@_print.inline
def _print(_arg_strs, _arg_types, _keyword_strs, **kwargs):
    objects = []
    for obj, arg_type in zip(_arg_strs, _arg_types, strict=True):
        if arg_type.name == "iter":
            obj = f"...{obj}"
        elif arg_type.name == "NoneType":
            obj = "'None'"
        elif arg_type.name == "bool":
            obj = f"({obj} ? 'True' : 'False')"
        objects.append(obj)

    sep = _keyword_strs.get("sep", "' '")
    end = _keyword_strs.get("end")
    args = ", ".join(objects)
    if "sep" not in _keyword_strs and end is None:
        return f"console.log({args})"

    text = f"[{args}].join({sep})"
    if end is None:
        return f"console.log({text})"
    return (
        "((text,end)=>globalThis.process?.stdout?.write(text+end)??"
        "console.log(text+(end==='\\n'?'':end)))"
        f"({text}, {end})"
    )


def base_string(num, _arg_types, prefix, base, **kwargs):
    if _arg_types[0].name == "bool":
        num = f"Number({num})"
    return (
        f"((value)=>value<0?'-{prefix}'+(-value).toString({base}):"
        f"'{prefix}'+value.toString({base}))({num})"
    )


@js(inline=partial(base_string, prefix="0b", base=2))
def _bin(num: int) -> str: ...


@js(inline=partial(base_string, prefix="0o", base=8))
def _oct(num: int) -> str: ...


@js(inline=partial(base_string, prefix="0x", base=16))
def _hex(num: int) -> str: ...


# pre-generate tuple[object] and dict[object,object] concrete
# classes as these are used as types for *args, **kwargs in
# functions parameters
def _cache_tuple_object() -> tuple[object]: ...
def _cache_dict_object_object() -> dict[object, object]: ...
