"""Lower typed API declarations without analyzing their server implementations."""

import math
from typing import get_type_hints

from pyjs.analysis.libraries import LibraryClassInfo
from pyjs.server.transport import ClientTransport

from .json import quote
from .json_codegen import JSONCodegen


def is_api(value):
    return isinstance(value, type) and any(
        base.__module__ == "pyjs.server" and base.__name__ == "API"
        for base in value.__mro__[1:]
    )


def operation_source(operation):
    if operation.kind not in {"query", "mutation", "action"} or operation.jsonapi:
        raise TypeError("JVM API clients currently support ordinary query, mutation, and action results")
    parameters = list(operation.signature.parameters.values())
    if not parameters or parameters[0].name != "self":
        raise TypeError("JVM API methods require a self receiver")
    parameters = parameters[1:]
    hints = get_type_hints(operation.function, include_extras=True)
    generator = JSONCodegen(parameter.name for parameter in parameters)
    if generator.reserved & generator.imports.keys():
        raise TypeError("JVM API parameter conflicts with a generated codec binding")
    signature, keyword_only = ["self"], False
    for index, parameter in enumerate(parameters):
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            raise TypeError("JVM API operations require statically named parameters")
        if parameter.kind == parameter.KEYWORD_ONLY and not keyword_only:
            signature.append("*")
            keyword_only = True
        annotation = hints.get(parameter.name)
        generator.validate(annotation)
        text = f"{parameter.name}: {generator.annotation(annotation)}"
        if parameter.default is not parameter.empty:
            default = parameter.default
            if type(default) not in (str, bool, int, float, type(None)) or (
                isinstance(default, float) and not math.isfinite(default)
            ):
                raise TypeError("JVM API operation defaults must be finite scalar values")
            text += f" = {default!r}"
        signature.append(text)
        if parameter.kind == parameter.POSITIONAL_ONLY and (
            index + 1 == len(parameters) or parameters[index + 1].kind != parameter.POSITIONAL_ONLY
        ):
            signature.append("/")
    result_type = hints.get("return")
    generator.validate(result_type)
    parts, reader = generator.name(), generator.name()
    generator.emit(f"{parts}: list[str] = ['{{']")
    for index, parameter in enumerate(parameters):
        prefix = ("," if index else "") + quote(parameter.name) + ":"
        generator.emit(f"{parts}.append({prefix!r})")
        generator.encode(hints[parameter.name], parameter.name, parts)
    generator.emit(f"{parts}.append('}}')")
    generator.emit(f"{reader} = _pyjs_reader(await self._request({operation.name!r}, ''.join({parts})))")
    value = generator.decode(result_type, reader)
    generator.emit(f"{reader}.finish()")
    generator.emit(f"return {value}")
    header = f"    async def {operation.name}({', '.join(signature)}) -> {generator.annotation(result_type)}:\n"
    return header + "\n".join("        " + line for line in generator.lines) + "\n", generator.imports


def class_info(cls):
    if not is_api(cls):
        return None
    if "__init__" in vars(cls):
        raise TypeError("JVM API clients do not support custom initialization")
    if getattr(cls, "__pyjs_model__", None) is not None or getattr(cls, "__pyjs_relationships__", {}):
        raise TypeError("JVM API clients do not yet support resources or relationships")
    children = cls.__pyjs_api_children__
    generator = JSONCodegen()
    generator.imports["_pyjs_transport"] = ClientTransport
    constructor = [
        '    def __init__(self, path: str = "/api", relationship: bool = False,',
        '                 transport: _pyjs_transport | None = None, timeout_ms: int = 0):',
        '        super().__init__(path, relationship, transport, timeout_ms)',
    ]
    inherited = getattr(cls.__base__, "__pyjs_api_children__", {})
    for name, child in children.items():
        if inherited.get(name) is not child:
            imported = generator.type_name(child)
            constructor.append(f"        self.{name} = {imported}(path + {'/' + name!r}, False, self._transport, timeout_ms)")
    methods = {"__init__": "\n".join(constructor) + "\n"}
    for name, operation in cls.__pyjs_operations__.items():
        methods[name], imports = operation_source(operation)
        generator.imports.update(imports)
    return LibraryClassInfo(dict(children), {}, (), opaque=True,
                            methods=methods, imports=generator.imports)
