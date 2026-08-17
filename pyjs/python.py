from collections.abc import Callable, Iterable, Iterator
from functools import partial
from typing import Self, overload

from pyjs import js


@js
def require_unpack_count(values: list[object], expected: int) -> list[object]:
    actual = len(values)
    if actual > expected:
        raise ValueError(
            "too many values to unpack (expected "
            + str(expected)
            + ", got "
            + str(actual)
            + ")"
        )
    if actual < expected:
        raise ValueError(
            "not enough values to unpack (expected "
            + str(expected)
            + ", got "
            + str(actual)
            + ")"
        )
    return values


@js
def unpack_starred(
    values: list[object],
    before: int,
    after: int,
) -> list[object]:
    actual = len(values)
    expected = before + after
    if actual < expected:
        raise ValueError(
            "not enough values to unpack (expected at least "
            + str(expected)
            + ", got "
            + str(actual)
            + ")"
        )
    suffix_start = actual - after
    result: list[object] = values[:before]
    result.append(values[before:suffix_start])
    result.extend(values[suffix_start:])
    return result


@js.inline(
    "typeof {value}?.__repr__ === 'function' "
    "? {value}.__repr__() : null"
)
def custom_repr_or_none(value: object) -> str | None:
    ...


@js.inline(
    "typeof {value}?.__ne__ === 'function' "
    "? {value}.__ne__({other}) : null"
)
def custom_ne_or_none(value: object, other: object) -> bool | None: ...


@js.inline("{value}.replaceAll({old}, {replacement})")
def replace_all(value: str, old: str, replacement: str) -> str:
    """Use native replaceAll internally without exposing it on Python str."""
    ...


@js
def repr_string(value: str) -> str:
    quote = "'"
    if "'" in value and '"' not in value:
        quote = '"'
    escaped = replace_all(value, "\\", "\\\\")
    escaped = replace_all(escaped, "\n", "\\n")
    escaped = replace_all(escaped, "\r", "\\r")
    escaped = replace_all(escaped, "\t", "\\t")
    escaped = replace_all(escaped, quote, "\\" + quote)
    return quote + escaped + quote


@js
def repr_value(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return repr_string(value)

    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.append(repr_value(item))
        return "[" + ", ".join(parts) + "]"

    if isinstance(value, dict):
        entries: list[str] = []
        for key, item in value.items():
            entries.append(repr_value(key) + ": " + repr_value(item))
        return "{" + ", ".join(entries) + "}"

    if isinstance(value, set):
        if not value:
            return "set()"
        set_parts: list[str] = []
        for item in value:
            set_parts.append(repr_value(item))
        return "{" + ", ".join(set_parts) + "}"

    custom = custom_repr_or_none(value)
    if custom is not None:
        return custom
    return str(value)


@js
def repr_tuple(values: tuple[object]) -> str:
    parts: list[str] = []
    for value in values:
        parts.append(repr_value(value))
    suffix = "," if len(parts) == 1 else ""
    return "(" + ", ".join(parts) + suffix + ")"


@js.inline("{values}.splice({start}, {delete_count}, ...{replacement})")
def splice(
    values: list[object],
    start: int,
    delete_count: int,
    replacement: list[object],
) -> None: ...


@js.inline("{values}.splice({index}, 1)[0]")
def splice_list_item(values: list[object], index: int) -> object: ...


@js
def equal_value(left: object, right: object) -> bool:
    return left == right


equal_value.source(
    """\
if (left === right) return true;
const leftNumeric = typeof left === 'number' || typeof left === 'boolean';
const rightNumeric = typeof right === 'number' || typeof right === 'boolean';
if (leftNumeric && rightNumeric) return Number(left) === Number(right);
if (Array.isArray(left) && Array.isArray(right)) {
    return left.length === right.length &&
        left.every((value, index) => equal_value(value, right[index]));
}
if (left instanceof Map && right instanceof Map) {
    if (left.size !== right.size) return false;
    for (const [key, value] of left) {
        if (!right.has(key) || !equal_value(value, right.get(key))) return false;
    }
    return true;
}
if (left instanceof Set && right instanceof Set) {
    if (left.size !== right.size) return false;
    for (const value of left) if (!right.has(value)) return false;
    return true;
}
if (left !== null && typeof left?.__eq__ === 'function') {
    return left.__eq__(right);
}
if (right !== null && typeof right?.__eq__ === 'function') {
    return right.__eq__(left);
}
return false;
"""
)


@js
def not_equal_value(left: object, right: object) -> bool:
    custom = custom_ne_or_none(left, right)
    if custom is not None:
        return custom
    custom = custom_ne_or_none(right, left)
    if custom is not None:
        return custom
    return not equal_value(left, right)


@js
def truthy(value: object) -> bool: ...


truthy.source(
    """\
if (value === null || value === false) return false;
if (typeof value === 'number') return value !== 0 || Number.isNaN(value);
if (typeof value === 'string' || Array.isArray(value)) return value.length !== 0;
if (value instanceof Map || value instanceof Set) return value.size !== 0;
if (typeof value === 'object') {
    if (Object.getPrototypeOf(value) === Object.prototype) {
        return Object.keys(value).length !== 0;
    }
    if (typeof value.__bool__ === 'function') return value.__bool__();
    if (typeof value.__len__ === 'function') {
        const length = value.__len__();
        if (length < 0) throw new RangeError('__len__() should return >= 0');
        return length !== 0;
    }
}
return true;
"""
)


@js
def find_equal_sequence_item(
    values: list[object],
    item: object,
    start: int = 0,
    stop: int | None = None,
) -> int:
    bounds = slice_indices(len(values), start, stop, 1)
    for index in range(bounds[0], bounds[1]):
        if equal_value(values[index], item):
            return index
    return -1


@js
def sequence_index(
    values: list[object],
    item: object,
    start: int = 0,
    stop: int | None = None,
) -> int:
    index = find_equal_sequence_item(values, item, start, stop)
    if index < 0:
        raise ValueError(repr(item) + " is not in list")
    return index


@js
def remove_list_item(values: list[object], item: object) -> None:
    index = find_equal_sequence_item(values, item)
    if index < 0:
        raise ValueError("list.remove(x): x not in list")
    splice_list_item(values, index)


@js.inline("{mapping}.delete({key})")
def delete_mapping_item(mapping: dict[object, object], key: object) -> None: ...


@js.inline(
    "typeof {key} === 'string' ? \"'\" + {key} + \"'\" : String({key})"
)
def key_error_message(key: object) -> str:
    ...


@js
def slice_indices(
    length: int,
    start: int | None,
    stop: int | None,
    step: int | None,
) -> list[int]:
    actual_step = 1 if step is None else step
    if actual_step == 0:
        raise ValueError("slice step cannot be zero")
    forward = actual_step > 0

    if start is None:
        actual_start = 0 if forward else length - 1
    else:
        actual_start = start
        if actual_start < 0:
            actual_start += length
        if forward:
            if actual_start < 0:
                actual_start = 0
            elif actual_start > length:
                actual_start = length
        elif actual_start < -1:
            actual_start = -1
        elif actual_start >= length:
            actual_start = length - 1

    if stop is None:
        actual_stop = length if forward else -1
    else:
        actual_stop = stop
        if actual_stop < 0:
            actual_stop += length
        if forward:
            if actual_stop < 0:
                actual_stop = 0
            elif actual_stop > length:
                actual_stop = length
        elif actual_stop < -1:
            actual_stop = -1
        elif actual_stop >= length:
            actual_stop = length - 1

    return [actual_start, actual_stop, actual_step]


@js
def slice_list(
    values: list[object],
    start: int | None,
    stop: int | None,
    step: int | None,
) -> list[object]:
    bounds = slice_indices(len(values), start, stop, step)
    result: list[object] = []
    index = bounds[0]
    while index < bounds[1] if bounds[2] > 0 else index > bounds[1]:
        result.append(values[index])
        index += bounds[2]
    return result


@js
def slice_string(
    value: str,
    start: int | None,
    stop: int | None,
    step: int | None,
) -> str:
    bounds = slice_indices(len(value), start, stop, step)
    result: list[str] = []
    index = bounds[0]
    while index < bounds[1] if bounds[2] > 0 else index > bounds[1]:
        result.append(value[index])
        index += bounds[2]
    return "".join(result)


@js.inline("[...{value}]")
def string_characters(value: str) -> list[str]:
    ...


@js
def replace_string(
    value: str,
    old: str,
    replacement: str,
    count: int = -1,
) -> str:
    if old != "":
        return replacement.join(value.split(old, count))

    characters = string_characters(value)
    replacements = len(characters) + 1
    if count >= 0 and count < replacements:
        replacements = count
    result = ""
    index = 0
    while index < len(characters):
        if index < replacements:
            result += replacement
        result += characters[index]
        index += 1
    if index < replacements:
        result += replacement
    return result


@js.inline(
    "new Set({values} instanceof Map ? {values}.keys() : "
    "({values} != null && typeof {values} === 'object' && "
    "!{values}[Symbol.iterator] ? Object.keys({values}) : {values}))"
)
def copy_set(values: Iterable[object]) -> set[object]:
    ...


@js
def update_set(target: set[object], values: Iterable[object]) -> None:
    for value in copy_set(values):
        target.add(value)
    return None


@js
def union_set(left: set[object], right: Iterable[object]) -> set[object]:
    result = left.copy()
    update_set(result, right)
    return result


@js
def intersection_set(left: set[object], right: Iterable[object]) -> set[object]:
    right_set = copy_set(right)
    result = set[object]()
    for value in left:
        if value in right_set:
            result.add(value)
    return result


@js
def difference_set(left: set[object], right: Iterable[object]) -> set[object]:
    result = left.copy()
    for value in copy_set(right):
        result.discard(value)
    return result


@js
def symmetric_difference_set(left: set[object], right: Iterable[object]) -> set[object]:
    result = left.copy()
    for value in copy_set(right):
        if value in result:
            result.discard(value)
        else:
            result.add(value)
    return result


@js
def equal_set(left: set[object], right: set[object]) -> bool:
    if len(left) != len(right):
        return False
    for value in left:
        if value in right:
            continue
        return False
    return True


@js
def subset_set(left: set[object], right: Iterable[object]) -> bool:
    right_set = copy_set(right)
    for value in left:
        if value in right_set:
            continue
        return False
    return True


@js
def superset_set(left: set[object], right: Iterable[object]) -> bool:
    return subset_set(copy_set(right), left)


@js
def disjoint_set(left: set[object], right: Iterable[object]) -> bool:
    right_set = copy_set(right)
    for value in left:
        if value in right_set:
            return False
    return True


@js
def set_list_slice(
    target: list[object],
    values: list[object],
    start: int | None = None,
    stop: int | None = None,
    step: int | None = None,
) -> None:
    copied: list[object] = []
    for value in values:
        copied.append(value)

    bounds = slice_indices(len(target), start, stop, step)
    actual_start = bounds[0]
    actual_stop = bounds[1]
    actual_step = bounds[2]
    if actual_step == 1:
        delete_count = actual_stop - actual_start
        if delete_count < 0:
            delete_count = 0
        splice(target, actual_start, delete_count, copied)
        return

    indexes: list[int] = []
    index = actual_start
    while index < actual_stop if actual_step > 0 else index > actual_stop:
        indexes.append(index)
        index += actual_step
    if len(indexes) != len(copied):
        raise ValueError(
            f"attempt to assign sequence of size {len(copied)} "
            f"to extended slice of size {len(indexes)}"
        )
    offset = 0
    while offset < len(indexes):
        target[indexes[offset]] = copied[offset]
        offset += 1


@js
def delete_list_slice(
    target: list[object],
    start: int | None = None,
    stop: int | None = None,
    step: int | None = None,
) -> None:
    bounds = slice_indices(len(target), start, stop, step)
    actual_start = bounds[0]
    actual_stop = bounds[1]
    actual_step = bounds[2]
    if actual_step == 1:
        delete_count = actual_stop - actual_start
        if delete_count < 0:
            delete_count = 0
        splice(target, actual_start, delete_count, [])
        return

    indexes: list[int] = []
    index = actual_start
    while index < actual_stop if actual_step > 0 else index > actual_stop:
        indexes.append(index)
        index += actual_step
    offset = len(indexes) - 1 if actual_step > 0 else 0
    while 0 <= offset and offset < len(indexes):
        target.pop(indexes[offset])
        offset += -1 if actual_step > 0 else 1


@js
def delete_list_item(target: list[object], index: int) -> None:
    actual_index = index + len(target) if index < 0 else index
    if actual_index < 0 or actual_index >= len(target):
        raise IndexError("list assignment index out of range")
    splice_list_item(target, actual_index)


@js.inline("{target}[Number({index})]")
def sequence_item_value(target: object, index: int) -> object: ...


@js.inline("{target}[Number({index})]")
def character_value(target: list[str], index: int) -> str: ...


@js.inline("({target}[Number({index})] = {value}, null)")
def assign_list_item(target: list[object], index: int, value: object) -> None: ...


@js
def get_list_item(target: list[object], index: int) -> object:
    actual_index = index + len(target) if index < 0 else index
    if actual_index < 0 or actual_index >= len(target):
        raise IndexError("list index out of range")
    return sequence_item_value(target, actual_index)


@js
def get_tuple_item(target: tuple[object], index: int) -> object:
    actual_index = index + len(target) if index < 0 else index
    if actual_index < 0 or actual_index >= len(target):
        raise IndexError("tuple index out of range")
    return sequence_item_value(target, actual_index)


@js
def get_string_item(target: str, index: int) -> str:
    characters = list(target)
    actual_index = index + len(characters) if index < 0 else index
    if actual_index < 0 or actual_index >= len(characters):
        raise IndexError("string index out of range")
    return character_value(characters, actual_index)


@js
def set_list_item(target: list[object], index: int, value: object) -> None:
    actual_index = index + len(target) if index < 0 else index
    if actual_index < 0 or actual_index >= len(target):
        raise IndexError("list assignment index out of range")
    assign_list_item(target, actual_index, value)


@js
def pop_list_item(target: list[object], index: int = -1) -> object:
    actual_index = index + len(target) if index < 0 else index
    if actual_index < 0 or actual_index >= len(target):
        raise IndexError("pop index out of range")
    return splice_list_item(target, actual_index)


@js
def delete_dict_item(mapping: dict[object, object], key: object) -> None:
    if key not in mapping:
        raise KeyError(key_error_message(key))
    delete_mapping_item(mapping, key)


@js.inline("{mapping}.get({key})")
def mapping_value(mapping: dict[object, object], key: object) -> object: ...


@js
def get_dict_item(mapping: dict[object, object], key: object) -> object:
    if key not in mapping:
        raise KeyError(key_error_message(key))
    return mapping_value(mapping, key)


@js
def pop_dict_item(
    mapping: dict[object, object],
    key: object,
    has_default: bool,
    default: object,
) -> object:
    if key not in mapping:
        if has_default:
            return default
        raise KeyError(key_error_message(key))
    value = mapping_value(mapping, key)
    delete_mapping_item(mapping, key)
    return value


@js
def update_dict(
    target: dict[object, object],
    values: dict[object, object],
) -> None:
    for key, value in values.items():
        target[key] = value


@js
def remove_set_item(values: set[object], item: object) -> None:
    if item not in values:
        raise KeyError(key_error_message(item))
    values.discard(item)


@js.inline("{values}.values().next().value")
def first_set_item(values: set[object]) -> object: ...


@js
def pop_set_item(values: set[object]) -> object:
    if len(values) == 0:
        raise KeyError(key_error_message("pop from an empty set"))
    item = first_set_item(values)
    values.discard(item)
    return item


def type_name(value_type):
    return getattr(value_type, "generic_name", None) or value_type.name


def inherits_type(value_type, expected_name):
    while value_type is not None:
        if value_type.name == expected_name:
            return True
        value_type = getattr(value_type, "super", None)
    return False


def runtime_repr(function):
    return js.inline(call=function)


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


def sequence_repeat(self, times, **kwargs):
    return (
        "((values,times)=>{const result=[];for(let index=0;index<times;index++)"
        f"result.push(...values);return result;}})({self},{times})"
    )


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


@js
def compare_values(left: object, right: object) -> int: ...


compare_values.source(
    """\
if (typeof left === 'string' && typeof right === 'string') {
    const leftChars = Array.from(left);
    const rightChars = Array.from(right);
    const length = Math.min(leftChars.length, rightChars.length);
    for (let index = 0; index < length; index++) {
        const leftCode = leftChars[index].codePointAt(0);
        const rightCode = rightChars[index].codePointAt(0);
        if (leftCode !== rightCode) return leftCode < rightCode ? -1 : 1;
    }
    return leftChars.length < rightChars.length ? -1 :
        leftChars.length > rightChars.length ? 1 : 0;
}
if (Array.isArray(left) && Array.isArray(right)) {
    const length = Math.min(left.length, right.length);
    for (let index = 0; index < length; index++) {
        const order = compare_values(left[index], right[index]);
        if (order !== 0) return order;
    }
    return left.length < right.length ? -1 : left.length > right.length ? 1 : 0;
}
if (typeof left?.__lt__ === 'function') {
    if (left.__lt__(right)) return -1;
    if (right.__lt__(left)) return 1;
    return 0;
}
if ((typeof left === 'number' || typeof left === 'boolean') &&
    (typeof right === 'number' || typeof right === 'boolean')) {
    return left < right ? -1 : left > right ? 1 : 0;
}
throw new TypeError('values do not define a portable ordering');
"""
)


@js
def sort_values(
    values: list[object],
    key: callable,
    reverse: bool,
) -> list[object]: ...


sort_values.source(
    """\
const decorated = values.map((value, index) => ({
    value,
    key: key === null ? value : key(value),
    index,
}));
decorated.sort((left, right) => {
    const order = compare_values(left.key, right.key);
    return order === 0 ? left.index - right.index : reverse ? -order : order;
});
for (let index = 0; index < values.length; index++) {
    values[index] = decorated[index].value;
}
return values;
"""
)
sort_values.__js_source_imports__ = {"compare_values": compare_values}


class _object:
    def __init__(self):
        pass

    # ast.Compare

    @js.inline(identity_op("===", "=="))
    def __is__(self, other: object) -> bool: ...

    @js.inline(identity_op("!==", "!="))
    def __is_not__(self, other: object) -> bool: ...

    @js.inline("{self} === {other}")
    def __eq__(self, other: object) -> bool: ...

    @js.inline("{self} !== {other}")
    def __ne__(self, other: object) -> bool: ...

    @js.inline(call=equal_value)
    def __dynamic_eq__(self, other: object) -> bool: ...

    @js.inline(call=not_equal_value)
    def __dynamic_ne__(self, other: object) -> bool: ...

    @js.inline(call=truthy)
    def __dynamic_bool__(self) -> bool: ...

    @js.inline("String({self})")
    def __str__(self) -> str: ...

    @runtime_repr(repr_value)
    def __repr__(self) -> str: ...


@js.inline("undefined")
def _dataclass_missing() -> object: ...


@js.inline("{left}.constructor === {right}.constructor")
def _same_dataclass_type(left: object, right: object) -> bool: ...


class _type[T](_object): ...


class _tuple[T](_object):
    @js
    def __init__(self, values: Iterable[object] | None = None): ...

    @__init__.inline
    def __init__(values=None, _arg_strs=(), _arg_types=(), **kwargs):
        if not _arg_strs:
            return "[]"
        return f"Array.from({iterable_source(values, _arg_types[0])})"

    @js.inline("{self}.length")
    def __len__(self) -> int: ...

    @js.inline(call=get_tuple_item)
    def __getitem__(self, idx: int) -> object: ...

    @js.inline(sequence_repeat)
    def __mul__(self, times: int) -> Self: ...

    @js.inline(sequence_repeat)
    def __rmul__(self, times: int) -> Self: ...

    @js.inline(call=sequence_index)
    @js.runtime_dunders("__eq__", item_of="self")
    def index(
        self,
        item: object,
        start: int = 0,
        stop: int | None = None,
    ) -> int: ...

    @js.inline(partial(sequence_equality, sequence_type="tuple"))
    def __eq__(self, other: object) -> bool: ...

    @js.inline(partial(sequence_equality, sequence_type="tuple", negate=True))
    def __ne__(self, other: object) -> bool: ...

    @runtime_repr(repr_tuple)
    def __str__(self) -> str: ...

    @runtime_repr(repr_tuple)
    def __repr__(self) -> str: ...


class _Generic(_object): ...


class _Iterable[V](_object): ...


class _Iterator[V](_Iterable[V]): ...


class _Awaitable[T](_object): ...


class _NoneType(_object):
    @js.inline("'None'")
    def __str__(self) -> str: ...

    @js.inline("'None'")
    def __repr__(self) -> str: ...


class _Exception(_object):
    def __init__(self, message: str = ""):
        self.message = message
        self.stack: str | None = None

    @js.inline("{self}.message")
    def __str__(self) -> str: ...


class _ValueError(_Exception):
    pass


class _TypeError(_Exception):
    pass


@js
class RuntimeError(Exception):
    pass


@js
class LookupError(Exception):
    pass


@js
class KeyError(LookupError):
    pass


@js
class IndexError(LookupError):
    pass


@js
class AssertionError(Exception):
    pass


@js
class StopIteration(Exception):
    pass


class _RuntimeError(_Exception):
    __js_runtime__ = RuntimeError


class _LookupError(_Exception):
    __js_runtime__ = LookupError


class _KeyError(_LookupError):
    __js_runtime__ = KeyError


class _IndexError(_LookupError):
    __js_runtime__ = IndexError


class _AssertionError(_Exception):
    __js_runtime__ = AssertionError


class _StopIteration(_Exception):
    __js_runtime__ = StopIteration


@js
def raise_stop_iteration() -> None:
    raise StopIteration()


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


class _int(_object):
    @js
    def __init__(self, other: object = 0): ...

    @__init__.inline
    def __init__(other="0", _arg_types=(), **kwargs):
        if not _arg_types:
            return "0"
        if _arg_types[0].name == "str":
            return (
                "((value)=>{const text=value.trim();"
                "if(!/^[+-]?\\d(?:_?\\d)*$/.test(text))"
                "throw new Error(`invalid literal for int() with base 10: "
                "'${value}'`);"
                "const number=Number.parseInt(text.replaceAll('_',''),10);"
                "return number===0?0:number;})"
                f"({other})"
            )
        return f"Math.trunc(Number({other}))"

    @js.inline("{self}")
    def __bool__(self) -> bool: ...

    @js.inline("String({self})")
    def __str__(self) -> str: ...

    @js.inline("String({self})")
    def __repr__(self) -> str: ...

    @js.inline("Math.abs({self})")
    def __abs__(self) -> int: ...

    @js.inline("Math.round({self})")
    def __round__(self) -> int: ...

    # ast.Compare

    @js.inline(int_op("<"))
    def __lt__(self, other: int) -> bool: ...

    @js.inline(int_op("<="))
    def __le__(self, other: int) -> bool: ...

    @js.inline(int_op(">"))
    def __gt__(self, other: int) -> bool: ...

    @js.inline(int_op(">="))
    def __ge__(self, other: int) -> bool: ...

    @js.inline(int_op("=="))
    def __eq__(self, other: int) -> bool: ...

    @js.inline(int_op("!="))
    def __ne__(self, other: int) -> bool: ...

    # ast.BinOp

    @js.inline(int_op("+"))
    def __add__(self, other: int) -> int: ...
    @js.inline(int_op("+", True))
    def __radd__(self, other: int) -> int: ...

    @js.inline(int_op("-"))
    def __sub__(self, other: int) -> int: ...
    @js.inline(int_op("-", True))
    def __rsub__(self, other: int) -> int: ...

    @js.inline(int_op("*"))
    def __mul__(self, other: int) -> int: ...
    @js.inline(int_op("*", True))
    def __rmul__(self, other: int) -> int: ...

    @js.inline(division_op)
    def __truediv__(self, other: int) -> float: ...
    @js.inline(partial(division_op, reverse=True))
    def __rtruediv__(self, other: int) -> float: ...

    @js.inline(partial(division_op, floor=True))
    def __floordiv__(self, other: int) -> int: ...
    @js.inline(partial(division_op, reverse=True, floor=True))
    def __rfloordiv__(self, other: int) -> int: ...

    @js.inline(modulo_op)
    def __mod__(self, other: int) -> int: ...
    @js.inline(partial(modulo_op, reverse=True))
    def __rmod__(self, other: int) -> int: ...

    @js.inline(int_op("**"))
    def __pow__(self, other: int) -> int: ...
    @js.inline(int_op("**", True))
    def __rpow__(self, other: int) -> int: ...

    @js.inline(int_op("|"))
    def __or__(self, other: int) -> int: ...

    @js.inline(int_op("|", True))
    def __ror__(self, other: int) -> int: ...


class _bool(_int):
    @js
    def __init__(self, arg: object = False): ...

    @__init__.inline
    def __init__(arg="false", _arg_types=(), **kwargs):
        if not _arg_types:
            return "false"
        arg_type = _arg_types[0]
        arg_type_name = type_name(arg_type)
        if arg_type_name in {"list", "str", "tuple"}:
            return f"{arg}.length!==0"
        if arg_type_name in {"dict", "set"}:
            return f"{arg}.size!==0"
        if inherits_type(arg_type, "typed_dict"):
            return f"Object.keys({arg}).length!==0"
        return f"Boolean({arg})"

    @js.inline("({self}?'True':'False')")
    def __str__(self) -> str: ...

    @js.inline("({self}?'True':'False')")
    def __repr__(self) -> str: ...

    @js.inline("Boolean({self} | {other})")
    def __or__(self, other: bool) -> bool: ...

    @js.inline("Boolean({other} | {self})")
    def __ror__(self, other: bool) -> bool: ...


class _float(_object):
    @js
    def __init__(self, other: object = 0): ...

    @__init__.inline
    def __init__(other="0", _arg_types=(), **kwargs):
        if not _arg_types:
            return "0"
        if _arg_types[0].name == "str":
            return (
                "((value)=>{const text=value.trim();"
                "if(/^[+-]?nan$/i.test(text))return NaN;"
                "if(/^[+-]?inf(?:inity)?$/i.test(text))"
                "return text[0]==='-'?-Infinity:Infinity;"
                "if(!/^[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:e[+-]?\\d+)?$/i"
                ".test(text))throw new Error(`could not convert string to float: "
                "'${value}'`);"
                "return Number(text);})"
                f"({other})"
            )
        return f"Number({other})"

    @js.inline("{self}")
    def __bool__(self) -> bool: ...

    @js.inline("String({self})")
    def __str__(self) -> str: ...

    @js.inline("String({self})")
    def __repr__(self) -> str: ...

    @js.inline("Math.abs({self})")
    def __abs__(self) -> float: ...

    @js
    def __round__(self) -> int: ...

    @__round__.inline
    def __round__(self, **kwargs):
        return (
            "((value)=>{const floor=Math.floor(value);return value-floor===0.5"
            "?(floor%2===0?floor:floor+1):Math.round(value);})"
            f"({self})"
        )

    @js.inline(float_op("<"))
    def __lt__(self, other: int | float | bool) -> bool: ...

    @js.inline(float_op("<="))
    def __le__(self, other: int | float | bool) -> bool: ...

    @js.inline(float_op(">"))
    def __gt__(self, other: int | float | bool) -> bool: ...

    @js.inline(float_op(">="))
    def __ge__(self, other: int | float | bool) -> bool: ...

    @js.inline(float_op("==="))
    def __eq__(self, other: int | float | bool) -> bool: ...

    @js.inline(float_op("!=="))
    def __ne__(self, other: int | float | bool) -> bool: ...

    @js.inline(float_op("+"))
    def __add__(self, other: int | float | bool) -> float: ...

    @js.inline(float_op("+", True))
    def __radd__(self, other: int | float | bool) -> float: ...

    @js.inline(float_op("-"))
    def __sub__(self, other: int | float | bool) -> float: ...

    @js.inline(float_op("-", True))
    def __rsub__(self, other: int | float | bool) -> float: ...

    @js.inline(float_op("*"))
    def __mul__(self, other: int | float | bool) -> float: ...

    @js.inline(float_op("*", True))
    def __rmul__(self, other: int | float | bool) -> float: ...

    @js.inline(division_op)
    def __truediv__(self, other: int | float | bool) -> float: ...

    @js.inline(partial(division_op, reverse=True))
    def __rtruediv__(self, other: int | float | bool) -> float: ...


@js.dispatch("__str__")
class _str(_object):
    @js.inline("''")
    def __init__(self, other: object = ""): ...

    @js.inline("{self}")
    def __bool__(self) -> bool: ...

    @js.inline("{self}")
    def __str__(self) -> str: ...

    @runtime_repr(repr_value)
    def __repr__(self) -> str: ...

    @js.inline("{self}.length")
    def __len__(self) -> int: ...

    @js.inline("{self} + {other}")
    def __add__(self, other: str) -> str: ...

    @js.inline("{self}.repeat({times})")
    def __mul__(self, times: int) -> str: ...

    @js.inline("{self}.repeat({times})")
    def __rmul__(self, times: int) -> str: ...

    @js.inline("{self}.trim()")
    def strip(self) -> str: ...

    @js.inline("{self}.toLowerCase()")
    def lower(self) -> str: ...

    @js.inline("{self}.toUpperCase()")
    def upper(self) -> str: ...

    @js.inline(
        "((value)=>value.length?"
        "value.charAt(0).toUpperCase()+value.slice(1).toLowerCase():value)({self})"
    )
    def capitalize(self) -> str: ...

    @js.inline("{self}.startsWith({prefix})")
    def startswith(self, prefix: str) -> bool: ...

    @js.inline("{self}.endsWith({suffix})")
    def endswith(self, suffix: str) -> bool: ...

    @js.inline(call=replace_string)
    def replace(self, old: str, new: str, count: int = -1) -> str: ...

    @js.inline("{self}.substring({start}, {end})")
    def substring(self, start: int, end: int) -> str: ...

    @js
    def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]: ...

    @split.inline
    def split(self, _arg_strs, **kwargs):
        if _arg_strs:
            sep = _arg_strs[0]
            if not _arg_strs[1:]:
                return f"{self}.split({sep})"
            maxsplit = _arg_strs[1]
            return (
                "((value,sep,maxsplit)=>{if(maxsplit<0)return value.split(sep);"
                "const parts=[];let start=0;for(let count=0;count<maxsplit;"
                "count++){const index=value.indexOf(sep,start);"
                "if(index<0)break;parts.push(value.slice(start,index));"
                "start=index+sep.length;}parts.push(value.slice(start));"
                "return parts;})"
                f"({self},{sep},{maxsplit})"
            )
        return (
            "((value)=>{const trimmed=value.trim();"
            "return trimmed?trimmed.split(/\\s+/):[];})"
            f"({self})"
        )

    @js.inline("{values}.join({self})")
    def join(self, values: Iterable[str]) -> str: ...

    @js.inline("{self}.includes({item})")
    def __contains__(self, item: str) -> bool: ...

    @js.inline(call=get_string_item)
    def __getitem__(self, idx: int) -> str: ...

    @js.inline(slice_value, dependencies={"slice": slice_string})
    def __slice__(
        self,
        start: int | None = None,
        stop: int | None = None,
        step: int | None = None,
    ) -> str: ...


class _list[V](_object):
    @js
    def __init__(self, values: Iterable[V] | None = None): ...

    @__init__.inline
    def __init__(values=None, _arg_strs=(), _arg_types=(), **kwargs):
        if not _arg_strs:
            return "[]"
        return f"Array.from({iterable_source(values, _arg_types[0])})"

    @js.inline("{self}.length")
    def __len__(self) -> int: ...

    @js.inline("{self}.push({item})")
    def append(self, item: V) -> None: ...

    @js.inline("{self}.push(...{item})")
    def extend(self, item: list[V]) -> None: ...

    @js.inline("{self}.splice({index}, 0, {item})")
    def insert(self, index: int, item: V) -> None: ...

    @js.inline(call=remove_list_item)
    @js.runtime_dunders("__eq__", item_of="self")
    def remove(self, item: V) -> None: ...

    @js.inline(call=sequence_index)
    @js.runtime_dunders("__eq__", item_of="self")
    def index(
        self,
        item: V,
        start: int = 0,
        stop: int | None = None,
    ) -> int: ...

    @js.inline(call=pop_list_item)
    def pop(self, index: int = -1) -> V: ...

    @js.inline("({self}.length = 0, null)")
    def clear(self) -> None: ...

    @js.inline("[...{self}]")
    def copy(self) -> list[V]: ...

    @js
    def sort[K](
        self,
        *,
        key: Callable[[V], K] | None = None,
        reverse: bool = False,
    ) -> None: ...

    @sort.analyze
    def sort(call):
        return call.sortable(method=True)

    @sort.inline(dependencies={"sort_values": sort_values})
    def sort(self, sort_values, _keyword_strs, **kwargs):
        key = _keyword_strs.get("key", "null")
        reverse = _keyword_strs.get("reverse", "false")
        return f"({sort_values}({self},{key},{reverse}), null)"

    @js.inline("{self}.length")
    def __bool__(self) -> bool: ...

    @runtime_repr(repr_value)
    def __str__(self) -> str: ...

    @runtime_repr(repr_value)
    def __repr__(self) -> str: ...

    @js.inline(partial(sequence_equality, sequence_type="list"))
    def __eq__(self, other: object) -> bool: ...

    @js.inline(partial(sequence_equality, sequence_type="list", negate=True))
    def __ne__(self, other: object) -> bool: ...

    @js
    def __add__(self, other: list[V]) -> list[V]: ...
    @__add__.inline
    def __add__(self, other, _arg_types, **kwargs):
        if type_name(_arg_types[0]) == "list":
            return f"{self}.concat({other})"
        return NotImplemented

    @js.inline(sequence_repeat)
    def __mul__(self, times: int) -> Self: ...

    @js.inline(sequence_repeat)
    def __rmul__(self, times: int) -> Self: ...

    @js.inline(call=get_list_item)
    def __getitem__(self, idx: int) -> V: ...

    @js.inline(slice_value, dependencies={"slice": slice_list})
    def __slice__(
        self,
        start: int | None = None,
        stop: int | None = None,
        step: int | None = None,
    ) -> list[V]: ...

    @js.inline(call=set_list_item)
    def __setitem__(self, idx: int, value: V) -> None: ...

    @js.inline(call=set_list_slice)
    def __setslice__(
        self,
        values: list[V],
        start: int | None = None,
        stop: int | None = None,
        step: int | None = None,
    ) -> None: ...

    @js.inline(call=delete_list_item)
    def __delitem__(self, idx: int) -> None: ...

    @js.inline(call=delete_list_slice)
    def __delslice__(
        self,
        start: int | None = None,
        stop: int | None = None,
        step: int | None = None,
    ) -> None: ...

    @js.inline("{self}.includes({item})")
    def __contains__(self, item: V) -> bool: ...


class _dict[K, V](_object):
    @js
    def __init__(
        self,
        values: Iterable[tuple[K, V]] | None = None,
    ): ...

    @__init__.inline
    def __init__(values=None, _arg_strs=(), _arg_types=(), **kwargs):
        if not _arg_strs:
            return "new Map()"
        value_type = _arg_types[0]
        if inherits_type(value_type, "typed_dict"):
            return f"new Map(Object.entries({values}))"
        return f"new Map({values})"

    @js.inline("{self}.size")
    def __len__(self) -> int: ...

    def keys(self) -> Iterable[K]: ...

    def values(self) -> Iterable[V]: ...

    @js.inline("{self}.entries()")
    def items(self) -> Iterable[tuple[K, V]]: ...

    # @js.inline("{self}.push({item})")
    def set(self, key: K, value: V): ...

    @js.inline("{self}.size")
    def __bool__(self) -> bool: ...

    @runtime_repr(repr_value)
    def __str__(self) -> str: ...

    @runtime_repr(repr_value)
    def __repr__(self) -> str: ...

    @js.inline(call=get_dict_item)
    def __getitem__(self, key: K) -> V: ...

    @overload
    def get(self, key: K) -> V | None: ...

    @overload
    def get[D](self, key: K, default: D) -> V | D: ...

    @js
    def get(self, key: K, default: object = None) -> V | object: ...

    @get.inline
    def get(self, key, default="null", **kwargs):
        return (
            "((mapping,key,fallback)=>mapping.has(key)"
            f"?mapping.get(key):fallback)({self},{key},{default})"
        )

    @js.inline(
        "((mapping,key,value)=>{{if(!mapping.has(key))"
        "mapping.set(key,value);return mapping.get(key);}})({self},{key},{default})"
    )
    def setdefault(self, key: K, default: V) -> V: ...

    @overload
    def pop(self, key: K) -> V: ...

    @overload
    def pop[D](self, key: K, default: D) -> V | D: ...

    @js
    def pop(self, key: K, default: object = None) -> V | object: ...

    @pop.inline(dependencies={"pop_dict_item": pop_dict_item})
    def pop(self, key, _arg_strs, pop_dict_item, **kwargs):
        if _arg_strs[1:]:
            return f"{pop_dict_item}({self},{key},true,{_arg_strs[1]})"
        return f"{pop_dict_item}({self},{key},false,null)"

    @js.inline("({self}.clear(), null)")
    def clear(self) -> None: ...

    @js.inline("new Map({self})")
    def copy(self) -> dict[K, V]: ...

    @js.inline(call=update_dict)
    def update(self, values: dict[K, V]) -> None: ...

    @js.inline("{self}.set({key}, {value})")
    def __setitem__(self, key: K, value: V) -> V: ...

    @js.inline(call=delete_dict_item)
    def __delitem__(self, key: K) -> None: ...

    @js.inline("{self}.has({key})")
    def __contains__(self, key: K) -> bool: ...


class _set[V](_object):
    @js
    def __init__(self, values: Iterable[V] | None = None): ...

    @__init__.inline
    def __init__(values=None, _arg_strs=(), _arg_types=(), **kwargs):
        if not _arg_strs:
            return "new Set()"
        value_type = _arg_types[0]
        if type_name(value_type) == "dict":
            return f"new Set({values}.keys())"
        if inherits_type(value_type, "typed_dict"):
            return f"new Set(Object.keys({values}))"
        return f"new Set({values})"

    @js.inline("{self}.size")
    def __len__(self) -> int: ...

    @js.inline("{self}.size")
    def __bool__(self) -> bool: ...

    @runtime_repr(repr_value)
    def __str__(self) -> str: ...

    @runtime_repr(repr_value)
    def __repr__(self) -> str: ...

    @js.inline("{self}.has({item})")
    def __contains__(self, item: V) -> bool: ...

    @js.inline("({self}.add({item}), null)")
    def add(self, item: V) -> None: ...

    @js.inline("({self}.delete({item}), null)")
    def discard(self, item: V) -> None: ...

    @js.inline(call=remove_set_item)
    def remove(self, item: V) -> None: ...

    @js.inline(call=pop_set_item)
    def pop(self) -> V: ...

    @js.inline("({self}.clear(), null)")
    def clear(self) -> None: ...

    @js.inline("new Set({self})")
    def copy(self) -> set[V]: ...

    @js.inline(call=update_set)
    def update(self, values: Iterable[V]) -> None: ...

    @js.inline(call=union_set)
    def union(self, other: Iterable[V]) -> set[V]: ...

    @js.inline(call=intersection_set)
    def intersection(self, other: Iterable[V]) -> set[V]: ...

    @js.inline(call=difference_set)
    def difference(self, other: Iterable[V]) -> set[V]: ...

    @js.inline(call=symmetric_difference_set)
    def symmetric_difference(self, other: Iterable[V]) -> set[V]: ...

    @js.inline(call=disjoint_set)
    def isdisjoint(self, other: Iterable[V]) -> bool: ...

    @js.inline(call=subset_set)
    def issubset(self, other: Iterable[V]) -> bool: ...

    @js.inline(call=superset_set)
    def issuperset(self, other: Iterable[V]) -> bool: ...

    @js.inline(
        "{other} instanceof Set && {equal_set}({self}, {other})",
        dependencies={"equal_set": equal_set},
    )
    def __eq__(self, other: set[V]) -> bool: ...

    @js.inline(
        "!({other} instanceof Set && {equal_set}({self}, {other}))",
        dependencies={"equal_set": equal_set},
    )
    def __ne__(self, other: set[V]) -> bool: ...

    @js.inline(call=subset_set)
    def __le__(self, other: set[V]) -> bool: ...

    @js.inline(
        "{subset_set}({self}, {other}) && {self}.size < {other}.size",
        dependencies={"subset_set": subset_set},
    )
    def __lt__(self, other: set[V]) -> bool: ...

    @js.inline(
        "{subset_set}({other}, {self})",
        dependencies={"subset_set": subset_set},
    )
    def __ge__(self, other: set[V]) -> bool: ...

    @js.inline(
        "{subset_set}({other}, {self}) && {other}.size < {self}.size",
        dependencies={"subset_set": subset_set},
    )
    def __gt__(self, other: set[V]) -> bool: ...

    @js.inline(call=union_set)
    def __or__(self, other: set[V]) -> set[V]: ...

    @js.inline(call=intersection_set)
    def __and__(self, other: set[V]) -> set[V]: ...

    @js.inline(call=difference_set)
    def __sub__(self, other: set[V]) -> set[V]: ...

    @js.inline(call=symmetric_difference_set)
    def __xor__(self, other: set[V]) -> set[V]: ...


class _typed_dict(_object):
    @js
    def __init__(self, values: object | None = None, **fields: object): ...

    @__init__.inline
    def __init__(_arg_strs, _arg_types, _keyword_strs, **kwargs):
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
                value = (
                    f"({value} instanceof Map?Object.fromEntries({value}):{value})"
                )
            entries.append(f"...{value}")
        entries.extend(f"{key}: {value}" for key, value in _keyword_strs.items())
        return "({" + ", ".join(entries) + "})"

    @js.inline("{self}[{key}]")
    def __getitem__(self, key: str) -> object: ...

    @js.inline("{self}[{key}] = {value}")
    def __setitem__(self, key: str, value: object) -> None: ...

    @js
    def get(self, key: str, default: object = None) -> object: ...

    @get.analyze
    def get(call):
        return call.typed_dict_get()

    @get.inline
    def get(self, key, default="null", **kwargs):
        return (
            "((mapping,key,fallback)=>Object.hasOwn(mapping,key)"
            f"?mapping[key]:fallback)({self},{key},{default})"
        )

    @js.inline("Object.keys({self})")
    def keys(self) -> Iterable[str]: ...

    @js.inline("Object.values({self})")
    def values(self) -> Iterable[object]: ...

    @js.inline("Object.entries({self})")
    def items(self) -> Iterable[tuple[str, object]]: ...

    @js.inline("Object.keys({self}).length")
    def __len__(self) -> int: ...

    @js.inline("Object.keys({self}).length > 0")
    def __bool__(self) -> bool: ...

    @js.inline("Object.hasOwn({self}, {key})")
    def __contains__(self, key: str) -> bool: ...


@js.dispatch("__len__")
def _len(value: object) -> int: ...


_len.value.source(
    """\
if (typeof value === 'string' || Array.isArray(value)) return value.length;
if (value instanceof Map || value instanceof Set) return value.size;
if (value !== null && typeof value === 'object') {
    if (Object.getPrototypeOf(value) === Object.prototype) {
        return Object.keys(value).length;
    }
    if (typeof value.__len__ === 'function') return value.__len__();
    if (typeof value.length === 'number') return value.length;
}
throw new TypeError(`object of type '${typeof value}' has no len()`);
"""
)


@js.dispatch("__abs__")
def _abs(value: int | float | bool) -> int | float: ...


_abs.value.source(
    """\
if (value !== null && typeof value === 'object' &&
    typeof value.__abs__ === 'function') return value.__abs__();
return Math.abs(value);
"""
)


@js
def _range(start: int, stop: int | None = None, step: int = 1) -> Iterable[int]: ...


@_range.inline
def _range(_arg_strs, **kwargs):
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


@js
def _enumerate[T](
    values: Iterable[T],
    start: int = 0,
) -> Iterator[tuple[int, T]]: ...


@_enumerate.inline
def _enumerate(values, _arg_types, start="0", **kwargs):
    return (
        "(function*(values,start){let index=start;for(const value of values)"
        f"yield [index++,value]}})({iterable_source(values, _arg_types[0])},{start})"
    )


@js
def _zip(*iterables: Iterable[object]) -> Iterator[tuple[object]]: ...


@_zip.analyze
def _zip(call):
    return call.zipped()


@_zip.inline
def _zip(_arg_strs, _arg_types, **kwargs):
    iterables = ", ".join(
        iterable_source(value, value_type)
        for value, value_type in zip(_arg_strs, _arg_types, strict=True)
    )
    return (
        "(function*(iterables){const iterators=iterables.map("
        "value=>value[Symbol.iterator]());while(iterators.length){"
        "const values=iterators.map(iterator=>iterator.next());"
        "if(values.some(value=>value.done))return;"
        "yield values.map(value=>value.value)}})(["
        f"{iterables}])"
    )


@js
def _iter[T](values: Iterable[T]) -> Iterator[T]: ...


@_iter.inline
def _iter(values, _arg_types, **kwargs):
    return f"{iterable_source(values, _arg_types[0])}[Symbol.iterator]()"


@overload
def _next[T](iterator: Iterator[T]) -> T: ...


@overload
def _next[T, D](iterator: Iterator[T], default: D) -> T | D: ...


@js
def _next(iterator: Iterator[object], default: object = None) -> object: ...


@_next.inline(dependencies={"raise_stop_iteration": raise_stop_iteration})
def _next(iterator, raise_stop_iteration, _arg_strs, **kwargs):
    if _arg_strs[1:]:
        fallback = _arg_strs[1]
        exhausted = f"return {fallback};"
    else:
        exhausted = f"return {raise_stop_iteration}();"
    return (
        "((result)=>{if(result.done){"
        f"{exhausted}}}return result.value;}})({iterator}.next())"
    )


@js
def _sum(values: Iterable[int], start: int = 0) -> int: ...


@_sum.inline
def _sum(values, _arg_types, start="0", **kwargs):
    value_type = _arg_types[0]
    if type_name(value_type) in {"list", "tuple"}:
        return f"({values}).reduce((total,value)=>total+value,{start})"
    return (
        "((values,total)=>{for(const value of values)total+=value;return total;})"
        f"({iterable_source(values, value_type)},{start})"
    )


def iterable_source(value, value_type):
    value_types = getattr(value_type, "types", (value_type,))
    mappings = [type_name(type_) == "dict" for type_ in value_types]
    typed_mappings = [inherits_type(type_, "typed_dict") for type_ in value_types]
    if all(mappings):
        return f"{value}.keys()"
    if all(typed_mappings):
        return f"Object.keys({value})"
    if any(mappings) or any(typed_mappings):
        return (
            "((value)=>value instanceof Map?value.keys():"
            "Object.getPrototypeOf(value)===Object.prototype?"
            f"Object.keys(value):value)({value})"
        )
    return value


def truth_test_inline(values, truthy, stop_on_truthy, _arg_types, **kwargs):
    comparison = "===" if stop_on_truthy else "!=="
    result = str(stop_on_truthy).lower()
    fallback = str(not stop_on_truthy).lower()
    return (
        "((values)=>{for(const value of values){"
        f"if({truthy}(value){comparison}true)return {result};"
        f"}}return {fallback};}})({iterable_source(values, _arg_types[0])})"
    )


@js.runtime_dunders("__bool__", "__len__", item_of=0)
@js.inline(
    partial(truth_test_inline, stop_on_truthy=False),
    dependencies={"truthy": truthy},
)
def _all(values: Iterable[object]) -> bool: ...


@js.runtime_dunders("__bool__", "__len__", item_of=0)
@js.inline(
    partial(truth_test_inline, stop_on_truthy=True),
    dependencies={"truthy": truthy},
)
def _any(values: Iterable[object]) -> bool: ...


@js
def _sorted[T, K](
    values: Iterable[T],
    *,
    key: Callable[[T], K] | None = None,
    reverse: bool = False,
) -> list[T]: ...


@_sorted.analyze
def _sorted(call):
    return call.sortable()


@_sorted.inline(dependencies={"sort_values": sort_values})
def _sorted(values, sort_values, _arg_types, _keyword_strs, **kwargs):
    key = _keyword_strs.get("key", "null")
    reverse = _keyword_strs.get("reverse", "false")
    source = iterable_source(values, _arg_types[0])
    return f"{sort_values}(Array.from({source}),{key},{reverse})"


@js
def _reversed[T](values: Iterable[T]) -> Iterator[T]: ...


@_reversed.analyze
def _reversed(call):
    return call.reversible()


@_reversed.inline
def _reversed(values, _arg_types, **kwargs):
    return (
        "(function*(values){const items=Array.from(values);"
        "for(let index=items.length-1;index>=0;index--)yield items[index];})"
        f"({iterable_source(values, _arg_types[0])})"
    )


@js.inline(call=require_unpack_count)
def _unpack_exact(values: list[object], expected: int) -> list[object]: ...


@js.inline(call=unpack_starred)
def _unpack_starred(
    values: list[object],
    before: int,
    after: int,
) -> list[object]: ...


def extreme_inline(
    _arg_strs,
    _arg_types,
    _keyword_strs,
    name,
    comparison,
    compare_values,
    **kwargs,
):
    values = _arg_strs[:]
    key = _keyword_strs.get("key", "null")
    has_default = "default" in _keyword_strs
    default = _keyword_strs.get("default", "null")
    if not values:
        return (
            f"(()=>{{throw new Error('{name} expected at least 1 argument, got 0');}})()"
        )
    if values[1:] and has_default:
        return (
            "(()=>{throw new Error('Cannot specify a default for "
            f"{name}() with multiple positional arguments');}})()"
        )
    if not values[1:]:
        iterable = values[0]
        source = iterable_source(iterable, _arg_types[0])
    else:
        source = "[" + ",".join(values) + "]"
    has_default_literal = "true" if has_default else "false"
    return (
        "((values,key,hasDefault,defaultValue)=>{"
        "let found=false;let best;let bestKey;"
        "for(const value of values){const valueKey=key===null?value:key(value);"
        f"if(!found||{compare_values}(valueKey,bestKey){comparison}0){{"
        "found=true;best=value;bestKey=valueKey;}}"
        f"if(!found){{if(hasDefault)return defaultValue;"
        f"throw new Error('{name}() iterable argument is empty');}}"
        "return best;})"
        f"({source},{key},{has_default_literal},{default})"
    )


@overload
def _min[T, K](
    values: Iterable[T],
    *,
    key: Callable[[T], K] | None = None,
) -> T: ...


@overload
def _min[T, K, D](
    values: Iterable[T],
    *,
    key: Callable[[T], K] | None = None,
    default: D,
) -> T | D: ...


@overload
def _min[T, K](
    first: T,
    second: T,
    *values: T,
    key: Callable[[T], K] | None = None,
) -> T: ...


@js.inline(
    partial(extreme_inline, name="min", comparison="<"),
    dependencies={"compare_values": compare_values},
)
def _min(
    *values: object,
    key: Callable[..., object] | None = None,
    default: object = None,
) -> object: ...


@_min.analyze
def _min(call):
    return call.extreme()


@overload
def _max[T, K](
    values: Iterable[T],
    *,
    key: Callable[[T], K] | None = None,
) -> T: ...


@overload
def _max[T, K, D](
    values: Iterable[T],
    *,
    key: Callable[[T], K] | None = None,
    default: D,
) -> T | D: ...


@overload
def _max[T, K](
    first: T,
    second: T,
    *values: T,
    key: Callable[[T], K] | None = None,
) -> T: ...


@js.inline(
    partial(extreme_inline, name="max", comparison=">"),
    dependencies={"compare_values": compare_values},
)
def _max(
    *values: object,
    key: Callable[..., object] | None = None,
    default: object = None,
) -> object: ...


@_max.analyze
def _max(call):
    return call.extreme()


@js.dispatch("__round__")
def _round(number: int | float | bool) -> int: ...


@js.dispatch("__repr__")
@js.inline(call=repr_value)
def _repr(obj: object) -> str: ...


@js
def _isinstance(obj: object, obj_type: type[object]) -> bool: ...
@_isinstance.inline
def _isinstance(obj, obj_type, **kwargs):
    if obj_type == "list":
        return f"Array.isArray({obj})"
    elif obj_type == "dict":
        return f"({obj} instanceof Map)"
    elif obj_type == "set":
        return f"({obj} instanceof Set)"
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


@js.inline("{attr} in {obj}")
def _hasattr(obj: object, attr: str) -> bool: ...


@js
def _getattr(obj: object, name: str, default: object = None) -> object: ...


@_getattr.analyze
def _getattr(call):
    return call.literal_attribute()


@_getattr.inline
def _getattr(obj, name, default="undefined", **kwargs):
    return (
        "((obj,name,fallback)=>{if(!(name in Object(obj)))return fallback;"
        "const value=obj[name];return typeof value==='function'?"
        "value.bind(obj):value;})"
        f"({obj},{name},{default})"
    )


@js.inline("callable")
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


@js.inline(partial(base_string, prefix="0b", base=2))
def _bin(num: int) -> str: ...


@js.inline(partial(base_string, prefix="0o", base=8))
def _oct(num: int) -> str: ...


@js.inline(partial(base_string, prefix="0x", base=16))
def _hex(num: int) -> str: ...


# pre-generate tuple[object] and dict[object,object] concrete
# classes as these are used as types for *args, **kwargs in
# functions parameters
def _cache_tuple_object() -> tuple[object]: ...
def _cache_dict_object_object() -> dict[object, object]: ...
