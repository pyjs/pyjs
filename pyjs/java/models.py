"""Field-only Pydantic client models; server validation stays on the server."""

import math
from types import UnionType
from typing import Annotated, Literal, Union, get_args, get_origin

from pyjs.analysis.libraries import LibraryClassInfo, LibraryImplementation, LibrarySpec
from pyjs.analysis.objects import _annotation_source

LIBRARY = LibrarySpec("pydantic", (
    LibraryImplementation(
        module="pyjs.java.models", minimum=(2, 0), maximum=(3, 0),
        imports={("pydantic.main", "BaseModel"): "BaseModel"},
    ),
))


class BaseModel:
    def __init__(self, **values: object) -> None: ...

    def __eq__(self, other: object) -> bool: ...

    def __ne__(self, other: object) -> bool: ...

    def __str__(self) -> str: ...

    def __repr__(self) -> str: ...

    def __hash__(self) -> int: ...

    def model_dump_json(self) -> str: ...

    @classmethod
    def model_validate_json(cls, json_data: str): ...


def is_model(cls):
    return isinstance(cls, type) and any(
        base.__module__ == "pydantic.main" and base.__name__ == "BaseModel"
        for base in cls.__mro__[1:]
    )


def is_json_factory(function):
    return (function.is_classmethod and function.name == "model_validate_json"
            and function.cls is not None and is_model(function.cls.py_obj)
            and function.cls.library_info is not None
            and "model_validate_json" in function.cls.library_info.methods)


def unsupported_json_codec() -> None:
    """Analyzer sentinel for an unsupported model's shadowing codec methods."""
    raise NotImplementedError("Unsupported JVM model JSON codec")


def field_only_codecs(info, cls):
    # Own stubs prevent lookup from falling through to a generated parent
    # codec. They remain lazy: field construction still needs no JSON support.
    return LibraryClassInfo(info.annotations, info.defaults, info.required, opaque=True,
        methods={**info.methods,
            "model_dump_json": "    def model_dump_json(self) -> str:\n        _pyjs_no_codec()\n",
            "model_validate_json": (
                "    @classmethod\n"
                "    def model_validate_json(cls, json_data: str) -> _pyjs_model_type:\n"
                "        _pyjs_no_codec()\n")},
        imports={"_pyjs_no_codec": unsupported_json_codec, "_pyjs_model_type": cls})


def field_type(annotation):
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    if annotation in (str, bool, int, float, type(None)) or is_model(annotation):
        return True
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is Literal:
        return all(type(value) is str for value in arguments)
    if origin in (UnionType, Union):
        members = [value for value in arguments if value is not type(None)]
        if len(members) > 1 and any(value in (bool, int, float) for value in members):
            return False
        return all(field_type(value) for value in arguments)
    if origin is list:
        return all(field_type(value) for value in arguments)
    if origin is dict:
        return arguments[0] is str and field_type(arguments[1])
    return False


def field_info(cls):
    if not is_model(cls):
        return None
    if cls.__pydantic_root_model__ or not cls.__pydantic_complete__:
        raise TypeError("JVM client models require a rebuilt ordinary Pydantic model")
    if cls.__pydantic_custom_init__ or cls.__pydantic_post_init__:
        raise TypeError("JVM client models do not support custom initialization")
    generic = cls.__pydantic_generic_metadata__
    if generic.get("origin") is not None or generic.get("parameters"):
        raise TypeError("JVM client models do not yet support generic models")
    decorators = cls.__pydantic_decorators__
    if any((decorators.validators, decorators.field_validators, decorators.root_validators,
            decorators.model_validators, decorators.field_serializers, decorators.model_serializers,
            decorators.computed_fields)):
        raise TypeError("JVM client models do not yet support custom validators or serializers")
    unsupported = set(cls.model_config) - {"extra", "strict", "title"}
    if unsupported:
        raise TypeError("Unsupported JVM client model configuration: " + ", ".join(sorted(unsupported)))
    if cls.model_config.get("extra") == "allow":
        raise TypeError("JVM client models do not support dynamic extra fields")
    annotations, defaults, required, parameters, body = {}, {}, [], [], []
    for name, field in cls.model_fields.items():
        if name == "self":
            raise TypeError("JVM client model fields cannot be named 'self'")
        if field.alias is not None or field.validation_alias is not None or field.serialization_alias is not None:
            raise TypeError(f"JVM client model field {name!r} does not support aliases")
        if field.default_factory is not None:
            raise TypeError(f"JVM client model field {name!r} does not support default factories")
        if field.frozen or field.exclude or getattr(field, "exclude_if", None) is not None:
            raise TypeError(f"JVM client model field {name!r} does not support freezing or exclusion")
        if not field_type(field.annotation):
            raise TypeError(f"JVM client model field {name!r} has an unsupported type")
        annotations[name] = field.annotation
        parameter = f"{name}: {_annotation_source(field.annotation)}"
        if field.is_required():
            required.append(name)
        else:
            default = field.default
            if type(default) not in (str, bool, int, float, type(None)):
                raise TypeError(f"JVM client model field {name!r} requires a scalar default")
            if isinstance(default, float) and not math.isfinite(default):
                raise TypeError(f"JVM client model field {name!r} requires a finite default")
            defaults[name] = default
            parameter += f" = {default!r}"
        parameters.append(parameter)
        body.append(f"        self.{name} = {name}")
    signature = "self, *, " + ", ".join(parameters) if parameters else "self"
    initializer = f"    def __init__({signature}):\n" + "\n".join(body or ["        pass"]) + "\n"
    return LibraryClassInfo(annotations, defaults, tuple(required), opaque=True,
                            methods={"__init__": initializer})


def _class_info(cls):
    from .json_codegen import JSONCodegen

    info = field_info(cls)
    if info is None:
        return None
    for base in cls.__mro__:
        if base.__module__ == "pydantic.main" and base.__name__ == "BaseModel":
            break
        if any(name in vars(base) for name in ("model_dump_json", "model_validate_json")):
            # Field-only lowering must not silently replace an application codec.
            return field_only_codecs(info, cls)
    generator = JSONCodegen()
    try:
        generator.validate(cls)
        generator.emit("parts: list[str] = []")
        generator.encode(cls, "self", "parts")
        generator.emit("return ''.join(parts)")
        encode = "    def model_dump_json(self) -> str:\n" + "\n".join(
            "        " + line for line in generator.lines) + "\n"
        generator.lines = []
        generator.emit("reader = _pyjs_reader(json_data)")
        result = generator.decode(cls, "reader")
        generator.emit("reader.finish()")
        generator.emit(f"return {result}")
        decode = ("    @classmethod\n"
                  f"    def model_validate_json(cls, json_data: str) -> {generator.annotation(cls)}:\n"
                  + "\n".join("        " + line for line in generator.lines) + "\n")
    except TypeError:
        # Construction supports more field types than the wire codec. Keep
        # such models constructible; calls fall through to the focused model
        # operation diagnostic, not a partially generated implementation.
        return field_only_codecs(info, cls)
    return LibraryClassInfo(info.annotations, info.defaults, info.required, opaque=True,
                            methods={**info.methods, "model_dump_json": encode,
                                     "model_validate_json": decode}, imports=generator.imports)
