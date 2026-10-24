"""Compile-time JSON codecs for statically known client schemas."""

from hashlib import sha256
from types import UnionType
from typing import Annotated, Literal, Union, cast, get_args, get_origin

from . import double_to_string
from .json import JSONReader, quote
from .models import _class_info, is_model


class JSONCodegen:
    def __init__(self):
        self.lines = []
        self.imports = {
            "_pyjs_reader": JSONReader,
            "_pyjs_quote": quote,
            "_pyjs_double": double_to_string,
            "_pyjs_cast": cast,
            "_pyjs_literal": Literal,
        }
        self.next_name = 0
        self.level = 0
        self.schema_heights = {}

    def name(self):
        self.next_name += 1
        return f"_pyjs_value_{self.next_name}"

    def emit(self, line):
        if len(self.lines) >= 4096:
            raise TypeError("JVM JSON codec exceeds the generated-source limit")
        self.lines.append("    " * self.level + line)

    @staticmethod
    def unwrap(annotation):
        while get_origin(annotation) is Annotated:
            annotation = get_args(annotation)[0]
        return annotation

    def annotation(self, annotation):
        return self._annotation(annotation, 0)

    def _annotation(self, annotation, depth):
        if depth >= 32:
            raise TypeError("JVM JSON schemas must be acyclic and at most 32 levels deep")
        annotation = self.unwrap(annotation)
        if annotation is type(None):
            return "None"
        if annotation in (str, bool, int, float):
            return annotation.__name__
        if is_model(annotation):
            for name, value in self.imports.items():
                if value is annotation:
                    return name
            identity = f"{annotation.__module__}.{annotation.__qualname__}"
            name = "_pyjs_json_model_" + sha256(identity.encode()).hexdigest()[:16]
            if name in self.imports:
                raise TypeError("JVM JSON model identities must be unique within a compilation")
            self.imports[name] = annotation
            return name
        origin, args = get_origin(annotation), get_args(annotation)
        if origin is Literal and args and all(type(value) is str for value in args):
            return "_pyjs_literal[" + ", ".join(repr(value) for value in args) + "]"
        if origin in (Union, UnionType) and len(args) == 2 and type(None) in args:
            return " | ".join(self._annotation(value, depth + 1) for value in args)
        if origin is list and len(args) == 1:
            return f"list[{self._annotation(args[0], depth + 1)}]"
        if origin is dict and len(args) == 2 and args[0] is str:
            return f"dict[str, {self._annotation(args[1], depth + 1)}]"
        raise TypeError(f"Unsupported JVM JSON schema: {annotation!r}")

    def validate(self, annotation, parents=()):
        annotation = self.unwrap(annotation)
        self.annotation(annotation)
        if annotation in parents:
            raise TypeError("JVM JSON schemas must be acyclic and at most 32 levels deep")
        height = self.schema_heights.get(annotation)
        if height is None:
            if len(parents) >= 32:
                raise TypeError("JVM JSON schemas must be acyclic and at most 32 levels deep")
            if is_model(annotation):
                _class_info(annotation)
                children = [field.annotation for field in annotation.model_fields.values()]
            else:
                children = [] if get_origin(annotation) is Literal else get_args(annotation)
            height = 1 + max((self.validate(child, (*parents, annotation)) for child in children), default=0)
            self.schema_heights[annotation] = height
        if len(parents) + height > 32:
            raise TypeError("JVM JSON schemas must be acyclic and at most 32 levels deep")
        return height

    def encode(self, annotation, value, parts):
        annotation = self.unwrap(annotation)
        origin, args = get_origin(annotation), get_args(annotation)
        if annotation is type(None):
            expression = repr("null")
        elif annotation is str or origin is Literal:
            expression = f"_pyjs_quote({value})"
        elif annotation is bool:
            expression = f"('true' if {value} else 'false')"
        elif annotation is int:
            expression = f"str({value})"
        elif annotation is float:
            self.emit(f"if {value} != {value} or {value} > 1.7976931348623157e308 or {value} < -1.7976931348623157e308:")
            self.emit("    raise ValueError('JSON numbers must be finite')")
            expression = f"_pyjs_double({value})"
        elif origin in (Union, UnionType):
            self.emit(f"if {value} is None:")
            self.emit(f"    {parts}.append('null')")
            self.emit("else:")
            self.level += 1
            self.encode(next(member for member in args if member is not type(None)), value, parts)
            self.level -= 1
            return
        elif origin in (list, dict):
            is_list = origin is list
            self.emit(f"{parts}.append({('[' if is_list else '{')!r})")
            first, item = self.name(), self.name()
            self.emit(f"{first} = True")
            self.emit(f"for {item} in {value}:")
            self.level += 1
            self.emit(f"if not {first}:")
            self.emit(f"    {parts}.append(',')")
            self.emit(f"{first} = False")
            if not is_list:
                self.emit(f"{parts}.append(_pyjs_quote({item}) + ':')")
                entry = self.name()
                self.emit(f"{entry} = {value}[{item}]")
                item = entry
            self.encode(args[0] if is_list else args[1], item, parts)
            self.level -= 1
            self.emit(f"{parts}.append({(']' if is_list else '}')!r})")
            return
        elif is_model(annotation):
            self.emit(f"{parts}.append('{{')")
            for index, (field, info) in enumerate(annotation.model_fields.items()):
                key = ("," if index else "") + quote(field) + ":"
                self.emit(f"{parts}.append({key!r})")
                item = self.name()
                self.emit(f"{item} = {value}.{field}")
                self.encode(info.annotation, item, parts)
            self.emit(f"{parts}.append('}}')")
            return
        else:
            raise TypeError(f"Unsupported JVM JSON schema: {annotation!r}")
        self.emit(f"{parts}.append({expression})")

    def decode(self, annotation, reader, depth=0):
        annotation = self.unwrap(annotation)
        origin, args = get_origin(annotation), get_args(annotation)
        result = self.name()
        if annotation in (str, bool, int, float):
            method = {str: "string", bool: "boolean", int: "integer", float: "floating"}[annotation]
            self.emit(f"{result} = {reader}.{method}()")
        elif annotation is type(None):
            self.emit(f"{reader}.expect('null')")
            self.emit(f"{result} = None")
        elif origin is Literal:
            self.emit(f"{result} = {reader}.string()")
            self.emit("if " + " and ".join(f"{result} != {value!r}" for value in args) + ":")
            self.emit("    raise ValueError('Invalid JSON literal value')")
            narrowed = self.name()
            self.emit(f"{narrowed} = _pyjs_cast({self.annotation(annotation)}, {result})")
            result = narrowed
        elif origin in (Union, UnionType):
            self.emit(f"{result}: {self.annotation(annotation)} = None")
            self.emit(f"if not {reader}.take('null'):")
            self.level += 1
            item = self.decode(next(member for member in args if member is not type(None)), reader, depth)
            self.emit(f"{result} = {item}")
            self.level -= 1
        elif origin in (list, dict):
            is_list = origin is list
            self.emit(f"{result}: {self.annotation(annotation)} = {'[]' if is_list else '{}'}")
            self.emit(f"{reader}.expect({('[' if is_list else '{')!r})")
            end = "]" if is_list else "}"
            self.emit(f"if not {reader}.take({end!r}):")
            self.emit("    while True:")
            self.level += 2
            key = None
            if not is_list:
                key = self.decode(str, reader)
                self.emit(f"{reader}.expect(':')")
            item = self.decode(args[0] if is_list else args[1], reader, depth + 1)
            self.emit(f"{result}.append({item})" if is_list else f"{result}[{key}] = {item}")
            self.emit(f"if {reader}.take({end!r}):")
            self.emit("    break")
            self.emit(f"{reader}.expect(',')")
            self.level -= 2
        elif is_model(annotation):
            self.decode_model(annotation, reader, result, depth)
        else:
            raise TypeError(f"Unsupported JVM JSON schema: {annotation!r}")
        return result

    def decode_model(self, annotation, reader, result, depth):
        fields = []
        for name, field in annotation.model_fields.items():
            value, seen = self.name(), self.name()
            field_type = self.annotation(field.annotation)
            default = "None" if field.is_required() else repr(field.default)
            self.emit(f"{value}: {field_type} | None = {default}")
            self.emit(f"{seen} = False")
            fields.append((name, field, value, seen))
        self.emit(f"{reader}.expect('{{')")
        self.emit(f"if not {reader}.take('}}'):")
        self.emit("    while True:")
        self.level += 2
        key = self.decode(str, reader)
        self.emit(f"{reader}.expect(':')")
        for index, (name, field, value, seen) in enumerate(fields):
            self.emit(f"{'if' if index == 0 else 'elif'} {key} == {name!r}:")
            self.level += 1
            item = self.decode(field.annotation, reader, depth + 1)
            self.emit(f"{value} = {item}")
            self.emit(f"{seen} = True")
            self.level -= 1
        if fields:
            self.emit("else:")
            self.level += 1
        if annotation.model_config.get("extra") == "forbid":
            self.emit("raise ValueError('Unexpected JSON model field')")
        else:
            self.emit(f"{reader}.skip({63 - depth})")
        if fields:
            self.level -= 1
        self.emit(f"if {reader}.take('}}'):")
        self.emit("    break")
        self.emit(f"{reader}.expect(',')")
        self.level -= 2
        arguments = []
        for name, field, value, seen in fields:
            if field.is_required():
                self.emit(f"if not {seen}:")
                self.emit(f"    raise ValueError({'Missing JSON model field: ' + name!r})")
            field_type = self.annotation(field.annotation)
            arguments.append(f"{name}=_pyjs_cast({field_type}, {value})")
        self.emit(f"{result} = {self.annotation(annotation)}({', '.join(arguments)})")
