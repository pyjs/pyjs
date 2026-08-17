import dataclasses

from pyjs import js


def _field_type(value_type, name):
    return value_type._self.find(name).cls


class _RecursiveDataclass(Exception):
    pass


def _asdict_fields(source, value_type, seen, converters):
    entries = []
    for field in dataclasses.fields(value_type.py_cls):
        field_source = f"{source}.{field.name}"
        field_type = _field_type(value_type, field.name)
        converted = _asdict_value(
            field_source,
            field_type,
            seen,
            converters,
        )
        entries.append(f"[{field.name!r}, {converted}]")
    return f"new Map([{', '.join(entries)}])"


def _asdict_value(source: str, value_type, seen=(), converters=None) -> str:
    union_types = tuple(getattr(value_type, "types", ()))
    dataclass_types = [
        member for member in union_types if getattr(member, "is_dataclass", False)
    ]
    other_types = [member for member in union_types if member not in dataclass_types]
    if (
        len(dataclass_types) == 1
        and len(other_types) == 1
        and other_types[0].name == "NoneType"
    ):
        return (
            f"({source} == null ? null : "
            f"{_asdict_value(source, dataclass_types[0], seen, converters)})"
        )
    if getattr(value_type, "is_dataclass", False):
        if converters is not None:
            return f"{converters[value_type]}({source})"
        if value_type in seen:
            raise _RecursiveDataclass
        return _asdict_fields(
            source,
            value_type,
            (*seen, value_type),
            converters,
        )
    if getattr(value_type, "generic_name", None) == "list":
        item_type = next(iter(value_type.generic_types.values()))
        item = _asdict_value("value", item_type, seen, converters)
        return f"{source}.map((value) => {item})"
    if getattr(value_type, "generic_name", None) == "tuple":
        item_types = tuple(value_type.generic_types.values())
        values = ", ".join(
            _asdict_value(f"{source}[{index}]", item_type, seen, converters)
            for index, item_type in enumerate(item_types)
        )
        return f"[{values}]"
    if getattr(value_type, "generic_name", None) == "dict":
        key = _asdict_value(
            "key",
            value_type.generic_types["K"],
            seen,
            converters,
        )
        value = _asdict_value(
            "value",
            value_type.generic_types["V"],
            seen,
            converters,
        )
        return (
            f"new Map(Array.from({source}, ([key, value]) => "
            f"[{key}, {value}]))"
        )
    if getattr(value_type, "generic_name", None) == "set":
        item = _asdict_value(
            "value",
            value_type.generic_types["V"],
            seen,
            converters,
        )
        return f"new Set(Array.from({source}, (value) => {item}))"
    return source


def _collect_dataclass_types(value_type, collected):
    for member in getattr(value_type, "types", ()):
        _collect_dataclass_types(member, collected)
    if getattr(value_type, "is_dataclass", False):
        if value_type in collected:
            return
        collected.append(value_type)
        for field in dataclasses.fields(value_type.py_cls):
            _collect_dataclass_types(_field_type(value_type, field.name), collected)
    for member in (getattr(value_type, "generic_types", None) or {}).values():
        _collect_dataclass_types(member, collected)


@js
def asdict(obj: object) -> dict[str, object]: ...


@asdict.analyze
def asdict(call):
    return call.dataclass()


@asdict.inline
def asdict(obj, _arg_types, **kwargs):
    value_type = _arg_types[0]
    if not getattr(value_type, "is_dataclass", False):
        raise TypeError("asdict() requires a dataclass instance")
    try:
        return _asdict_value(obj, value_type)
    except _RecursiveDataclass:
        value_types = []
        _collect_dataclass_types(value_type, value_types)
        converters = {
            value_type: f"$dataclass{index}"
            for index, value_type in enumerate(value_types)
        }
        definitions = "".join(
            f"const {converters[item_type]}=(value)=>"
            f"{_asdict_fields('value', item_type, (), converters)};"
            for item_type in value_types
        )
        return (
            f"((value)=>{{{definitions}return {converters[value_type]}(value);}})"
            f"({obj})"
        )


@js
def replace[T](obj: T, **changes: object) -> T: ...


@replace.analyze
def replace(call):
    return call.dataclass(replace=True)


@replace.inline
def replace(obj, _arg_types, _keyword_strs, **kwargs):
    value_type = _arg_types[0]
    if not getattr(value_type, "is_dataclass", False):
        raise TypeError("replace() requires a dataclass instance")
    initializer = value_type.init
    required_count = len(initializer.params) - len(initializer.defaults)
    required = [
        _keyword_strs.get(param.arg, f"{obj}.{param.arg}")
        for param in initializer.params[:required_count]
    ]
    optional = [*initializer.params[required_count:], *initializer.kwonlyargs]
    if optional:
        values = ", ".join(
            f"{param.arg}: {_keyword_strs.get(param.arg, f'{obj}.{param.arg}')}"
            for param in optional
        )
        required.append(f"{{{values}}}")
    return f"new ({obj}.constructor)({', '.join(required)})"
