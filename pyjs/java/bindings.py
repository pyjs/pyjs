"""Deterministic Python declarations for selected JVM class members."""

import keyword
import re
from dataclasses import dataclass

from .classpath import (
    JVMClass,
    JVMClasspath,
    JVMField,
    JVMMethod,
    parse_jvm_method_descriptor,
)

_PUBLIC = 0x0001
_PRIVATE = 0x0002
_PROTECTED = 0x0004
_STATIC = 0x0008
_FINAL = 0x0010
_INTERFACE = 0x0200
_PYTHON_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class JVMBindingError(ValueError):
    """A requested JVM declaration cannot be represented faithfully."""


@dataclass(frozen=True)
class JVMMethodBinding:
    """Select one exact JVM method overload for a Python declaration."""

    name: str
    descriptor: str
    python_name: str | None = None
    parameter_names: tuple[str, ...] | None = None
    nullable_return: bool | None = None
    nullable_parameters: tuple[int, ...] | None = None

    @classmethod
    def constructor(
        cls,
        descriptor: str,
        parameter_names: tuple[str, ...] | None = None,
    ) -> JVMMethodBinding:
        return cls("<init>", descriptor, "__init__", parameter_names)


@dataclass(frozen=True)
class JVMFieldBinding:
    """Select one exact JVM field for a Python declaration."""

    name: str
    descriptor: str
    python_name: str | None = None
    nullable: bool | None = None


@dataclass(frozen=True)
class JVMClassBinding:
    """Select the members exposed for one JVM class."""

    name: str
    python_name: str | None = None
    methods: tuple[JVMMethodBinding, ...] = ()
    fields: tuple[JVMFieldBinding, ...] = ()


@dataclass(frozen=True)
class JVMExternalClass:
    """Reuse a native class declaration imported from another Python module."""

    name: str
    module: str
    python_name: str


def _internal_name(name: str) -> str:
    return name.removesuffix(".class").replace(".", "/")


def _python_identifier(value: str, description: str) -> str:
    if _PYTHON_IDENTIFIER.fullmatch(value) is None or keyword.iskeyword(value):
        raise JVMBindingError(f"{description} {value!r} is not a Python identifier")
    return value


def _snake_case(name: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9_]", "_", value).lower()
    if not value or value[0].isdigit():
        value = "value_" + value
    if keyword.iskeyword(value):
        value += "_"
    return value


def _class_name(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", name.rsplit("/", 1)[-1])
    if not value or value[0].isdigit():
        value = "JVM_" + value
    if keyword.iskeyword(value):
        value += "_"
    return value


def _field_name(name: str) -> str:
    if name.isupper():
        return re.sub(r"[^A-Za-z0-9_]", "_", name)
    return _snake_case(name)


def _references(descriptor: str) -> tuple[str, ...]:
    result = []
    offset = 0
    while offset < len(descriptor):
        if descriptor[offset] == "[":
            offset += 1
            continue
        if descriptor[offset] != "L":
            offset += 1
            continue
        end = descriptor.find(";", offset)
        if end < 0:
            raise JVMBindingError(f"invalid JVM descriptor {descriptor!r}")
        result.append(descriptor[offset + 1:end])
        offset = end + 1
    return tuple(result)


class _SourceRenderer:
    def __init__(
        self,
        classpath: JVMClasspath,
        bindings: tuple[JVMClassBinding, ...],
        external_classes: tuple[JVMExternalClass, ...],
    ) -> None:
        self.classpath = classpath
        self.bindings = {_internal_name(value.name): value for value in bindings}
        if len(self.bindings) != len(bindings):
            raise JVMBindingError("a JVM class binding is duplicated")
        self.externals = {
            _internal_name(value.name): value for value in external_classes
        }
        if len(self.externals) != len(external_classes):
            raise JVMBindingError("an external JVM class binding is duplicated")
        for value in external_classes:
            _python_identifier(value.python_name, "external JVM class name")
            if not value.module or any(
                _PYTHON_IDENTIFIER.fullmatch(part) is None
                or keyword.iskeyword(part)
                for part in value.module.split(".")
            ):
                raise JVMBindingError(
                    f"external JVM module {value.module!r} is not a Python module name"
                )
        overlap = self.bindings.keys() & self.externals.keys()
        if overlap:
            raise JVMBindingError(
                f"JVM class {min(overlap)!r} is both generated and external"
            )
        self.classes: dict[str, JVMClass | None] = {}
        self.names: dict[str, str] = {}
        self.imports: set[tuple[str, str]] = set()
        self.static_names: set[str] = set()

    def render(self) -> str:
        self._resolve_classes()
        self._assign_names()
        declarations = []
        for name in self._class_order():
            declarations.extend(self._render_class(name))
            declarations.append("")
        for name in sorted(self.bindings):
            declaration = self.classes[name]
            binding = self.bindings[name]
            for selected in binding.methods:
                method = self._method(declaration, selected)
                if not method.access & _STATIC:
                    continue
                python_name = selected.python_name or (
                    _snake_case(self.names[name]) + "_" + _snake_case(method.name)
                )
                _python_identifier(python_name, "Python JVM function name")
                self._unique_member(self.static_names, python_name, "module")
                declarations.extend(
                    self._render_static_method(
                        name,
                        method,
                        python_name,
                        selected.parameter_names,
                        selected.nullable_return or False,
                        selected.nullable_parameters or (),
                    )
                )
                declarations.append("")
        imports = self._render_imports()
        return "\n".join([*imports, "", *declarations]).rstrip() + "\n"

    def _resolve_classes(self) -> None:
        pending = list(self.bindings)
        while pending:
            name = pending.pop()
            if name in self.classes or name in self.externals or name in {
                "java/lang/String",
                "java/lang/CharSequence",
            }:
                continue
            declaration = self.classpath.find_class(name)
            if name in self.bindings and declaration is None:
                raise JVMBindingError(
                    f"JVM class {name!r} was not found on the classpath"
                )
            if (
                name in self.bindings
                and declaration is not None
                and not declaration.access & (_PUBLIC | _PROTECTED)
            ):
                raise JVMBindingError(
                    f"JVM class {name!r} is not externally accessible"
                )
            self.classes[name] = declaration
            if declaration is None:
                continue
            if declaration.super_name is not None:
                pending.append(declaration.super_name)
            binding = self.bindings.get(name)
            if binding is None:
                continue
            for method_binding in binding.methods:
                method = self._method(declaration, method_binding)
                parameters, result = parse_jvm_method_descriptor(
                    method.descriptor
                )
                for descriptor in (*parameters, result):
                    pending.extend(_references(descriptor))
            for field_binding in binding.fields:
                field = self._field(declaration, field_binding)
                pending.extend(_references(field.descriptor))

    def _assign_names(self) -> None:
        explicit = {
            name: binding.python_name
            for name, binding in self.bindings.items()
            if binding.python_name is not None
        }
        used = {}
        for name, value in sorted(self.externals.items()):
            if value.python_name in used:
                raise JVMBindingError(
                    f"Python JVM class name {value.python_name!r} is duplicated"
                )
            used[value.python_name] = name
            self.names[name] = value.python_name
            self.imports.add((value.module, value.python_name))
        for name in sorted(self.classes):
            candidate = explicit.get(name) or _class_name(name)
            _python_identifier(candidate, "Python JVM class name")
            if candidate in used:
                if name in explicit or used[candidate] in explicit:
                    raise JVMBindingError(
                        f"Python JVM class name {candidate!r} is duplicated"
                    )
                candidate = _class_name(name.replace("/", "_"))
            if candidate in used:
                raise JVMBindingError(
                    f"Python JVM class name {candidate!r} is duplicated"
                )
            used[candidate] = name
            self.names[name] = candidate

    def _class_order(self) -> tuple[str, ...]:
        result = []
        visiting = set()

        def visit(name: str) -> None:
            if name in result:
                return
            if name in visiting:
                raise JVMBindingError(f"cyclic JVM class hierarchy at {name!r}")
            visiting.add(name)
            value = self.classes[name]
            if value is not None and value.super_name in self.classes:
                visit(value.super_name)
            visiting.remove(name)
            result.append(name)

        for name in sorted(self.classes):
            visit(name)
        return tuple(result)

    def _render_class(self, name: str) -> list[str]:
        declaration = self.classes[name]
        interface = declaration is not None and bool(declaration.access & _INTERFACE)
        decorator = f'@jvm.native("{name}"'
        if interface:
            decorator += ", interface=True"
        decorator += ")"
        base = None
        if declaration is not None and declaration.super_name in self.names:
            base = self.names[declaration.super_name]
        heading = f"class {self.names[name]}"
        if base is not None:
            heading += f"({base})"
        lines = [decorator, heading + ":"]
        binding = self.bindings.get(name)
        if binding is None or not binding.methods and not binding.fields:
            lines.append("    pass")
            return lines
        member_names = set()
        rendered_member = False
        for field_binding in binding.fields:
            field = self._field(declaration, field_binding)
            python_name = field_binding.python_name or _field_name(field.name)
            _python_identifier(python_name, "Python JVM field name")
            self._unique_member(member_names, python_name, name)
            lines.extend(
                self._render_field(
                    name,
                    field,
                    python_name,
                    field_binding.nullable or False,
                )
            )
            rendered_member = True
        for method_binding in binding.methods:
            method = self._method(declaration, method_binding)
            if method.access & _STATIC:
                continue
            python_name = method_binding.python_name or (
                "__init__" if method.name == "<init>" else _snake_case(method.name)
            )
            _python_identifier(python_name, "Python JVM method name")
            self._unique_member(member_names, python_name, name)
            lines.extend(
                self._render_method(
                    name,
                    method,
                    python_name,
                    method_binding.parameter_names,
                    method_binding.nullable_return or False,
                    method_binding.nullable_parameters or (),
                )
            )
            rendered_member = True
        if not rendered_member:
            lines.append("    pass")
        return lines

    @staticmethod
    def _unique_member(names: set[str], value: str, owner: str) -> None:
        if value in names:
            raise JVMBindingError(
                f"Python JVM member name {value!r} is duplicated on {owner!r}; "
                "set an explicit python_name for each overload"
            )
        names.add(value)

    def _render_field(
        self,
        owner: str,
        field: JVMField,
        python_name: str,
        nullable: bool,
    ) -> list[str]:
        if field.access & _PRIVATE or not field.access & (_PUBLIC | _PROTECTED):
            raise JVMBindingError(
                f"JVM field {owner}.{field.name}:{field.descriptor} "
                "is not externally accessible"
            )
        self.imports.add(("typing", "Annotated"))
        options = []
        if python_name != field.name:
            options.append(f'name="{field.name}"')
        if field.access & _FINAL:
            options.append("writable=False")
        metadata = "jvm.field(" + ", ".join(options) + ")"
        annotation = f"Annotated[{self._type(field.descriptor, nullable)}, {metadata}]"
        if field.access & _STATIC:
            self.imports.add(("typing", "ClassVar"))
            annotation = f"ClassVar[{annotation}]"
            value = field.constant
            if value is None:
                value = self._fallback(field.descriptor)
            return [f"    {python_name}: {annotation} = {value!r}"]
        return [f"    {python_name}: {annotation}"]

    def _render_method(
        self,
        owner: str,
        method: JVMMethod,
        python_name: str,
        parameter_names: tuple[str, ...] | None,
        nullable_return: bool,
        nullable_parameters: tuple[int, ...],
    ) -> list[str]:
        if method.name == "<clinit>":
            raise JVMBindingError("JVM class initializers cannot be bound")
        if method.access & _PRIVATE or not method.access & (_PUBLIC | _PROTECTED):
            raise JVMBindingError(
                f"JVM method {owner}.{method.name}{method.descriptor} "
                "is not externally accessible"
            )
        lines = []
        if method.name != "<init>" and python_name != method.name:
            lines.extend(
                [
                    "    @jvm.native(",
                    f'        "{owner}",',
                    f'        name="{method.name}",',
                    '        invocation="virtual",',
                    "    )",
                ]
            )
        parameters, result = parse_jvm_method_descriptor(method.descriptor)
        self._validate_nullable_parameters(method, nullable_parameters, parameters)
        names = self._parameter_names(method, parameter_names)
        used = {"self"}
        unique_names = []
        for candidate in names:
            while candidate in used:
                candidate += "_"
            used.add(candidate)
            unique_names.append(candidate)
        arguments = ["self"]
        arguments.extend(
            f"{name}: {self._type(descriptor, index in nullable_parameters)}"
            for index, (name, descriptor) in enumerate(
                zip(unique_names, parameters, strict=True)
            )
        )
        if method.name == "<init>" and nullable_return:
            raise JVMBindingError("JVM constructors cannot have nullable returns")
        return_type = (
            "None" if method.name == "<init>" else self._type(result, nullable_return)
        )
        signature = f"    def {python_name}({', '.join(arguments)}) -> {return_type}:"
        if len(signature) <= 88:
            lines.append(signature)
        else:
            lines.append(f"    def {python_name}(")
            lines.extend(f"        {argument}," for argument in arguments)
            lines.append(f"    ) -> {return_type}:")
        lines.append("        pass")
        return lines

    def _render_static_method(
        self,
        owner: str,
        method: JVMMethod,
        python_name: str,
        parameter_names: tuple[str, ...] | None = None,
        nullable_return: bool = False,
        nullable_parameters: tuple[int, ...] = (),
    ) -> list[str]:
        if method.name in {"<init>", "<clinit>"}:
            raise JVMBindingError(
                f"JVM initializer {owner}.{method.name} has invalid static access"
            )
        if method.access & _PRIVATE or not method.access & (_PUBLIC | _PROTECTED):
            raise JVMBindingError(
                f"JVM method {owner}.{method.name}{method.descriptor} "
                "is not externally accessible"
            )
        parameters, result = parse_jvm_method_descriptor(method.descriptor)
        self._validate_nullable_parameters(method, nullable_parameters, parameters)
        names = self._parameter_names(method, parameter_names)
        used = set()
        unique_names = []
        for candidate in names:
            while candidate in used:
                candidate += "_"
            used.add(candidate)
            unique_names.append(candidate)
        arguments = [
            f"{name}: {self._type(descriptor, index in nullable_parameters)}"
            for index, (name, descriptor) in enumerate(
                zip(unique_names, parameters, strict=True)
            )
        ]
        lines = [
            "@jvm.native(",
            f'    "{owner}",',
            f'    name="{method.name}",',
            ")",
        ]
        signature = (
            f"def {python_name}({', '.join(arguments)}) -> "
            f"{self._type(result, nullable_return)}:"
        )
        if len(signature) <= 88:
            lines.append(signature)
        else:
            lines.append(f"def {python_name}(")
            lines.extend(f"    {argument}," for argument in arguments)
            lines.append(f") -> {self._type(result, nullable_return)}:")
        lines.append("    pass")
        return lines

    @staticmethod
    def _parameter_names(
        method: JVMMethod,
        selected: tuple[str, ...] | None,
    ) -> list[str]:
        if selected is not None and len(selected) != len(method.parameters):
            raise JVMBindingError(
                f"JVM method {method.name}{method.descriptor} has "
                f"{len(method.parameters)} parameters, not {len(selected)}"
            )
        values = selected or tuple(
            parameter.name or f"argument_{index + 1}"
            for index, parameter in enumerate(method.parameters)
        )
        return [_snake_case(value) for value in values]

    @staticmethod
    def _validate_nullable_parameters(
        method: JVMMethod,
        nullable: tuple[int, ...],
        parameters: tuple[str, ...],
    ) -> None:
        invalid = [index for index in nullable if not 0 <= index < len(parameters)]
        if invalid:
            raise JVMBindingError(
                f"JVM method {method.name}{method.descriptor} has no nullable "
                f"parameter {invalid[0]}"
            )

    def _type(self, descriptor: str, nullable: bool = False) -> str:
        primitive = {
            "V": "None",
            "Z": "bool",
            "B": "int8",
            "C": "uint16",
            "S": "int16",
            "I": "i32",
            "J": "int",
            "F": "f32",
            "D": "f64",
        }.get(descriptor)
        if primitive is not None:
            if descriptor in {"B", "C", "S"}:
                self.imports.add(("pyjs", primitive))
            elif descriptor in {"I", "F", "D"}:
                self.imports.add(("pyjs.java", primitive))
            if nullable:
                raise JVMBindingError(
                    f"primitive JVM type {descriptor!r} cannot be nullable"
                )
            return primitive
        if descriptor.startswith("["):
            self.imports.add(("pyjs.java", "JVMArray"))
            value = f"JVMArray[{self._type(descriptor[1:])}]"
            return f"{value} | None" if nullable else value
        if not descriptor.startswith("L") or not descriptor.endswith(";"):
            raise JVMBindingError(f"invalid JVM type descriptor {descriptor!r}")
        owner = descriptor[1:-1]
        if owner == "java/lang/String":
            return "str | None" if nullable else "str"
        if owner == "java/lang/CharSequence":
            self.imports.add(("typing", "Annotated"))
            self.imports.add(("pyjs.java.primitives", "Reference"))
            value = 'Annotated[str, Reference("java/lang/CharSequence")]'
            return f"{value} | None" if nullable else value
        try:
            value = self.names[owner]
            return f"{value} | None" if nullable else value
        except KeyError:
            raise JVMBindingError(
                f"JVM reference {owner!r} was not resolved for generation"
            ) from None

    @staticmethod
    def _fallback(descriptor: str) -> object:
        if descriptor == "Z":
            return False
        if descriptor in "BCSIJ":
            return 0
        if descriptor in "FD":
            return 0.0
        if descriptor == "Ljava/lang/String;":
            return ""
        return None

    def _render_imports(self) -> list[str]:
        self.imports.add(("pyjs", "jvm"))
        grouped: dict[str, list[str]] = {}
        for module, name in sorted(self.imports):
            grouped.setdefault(module, []).append(name)
        lines = []
        if names := grouped.pop("typing", None):
            lines.append(f"from typing import {', '.join(names)}")
            lines.append("")
        for module, names in sorted(grouped.items()):
            lines.append(f"from {module} import {', '.join(names)}")
        return lines

    @staticmethod
    def _method(value: JVMClass, binding: JVMMethodBinding) -> JVMMethod:
        matches = [
            method
            for method in value.methods
            if method.name == binding.name and method.descriptor == binding.descriptor
        ]
        if len(matches) != 1:
            raise JVMBindingError(
                f"JVM method {value.name}.{binding.name}{binding.descriptor} "
                "was not found exactly once"
            )
        return matches[0]

    @staticmethod
    def _field(value: JVMClass, binding: JVMFieldBinding) -> JVMField:
        matches = [
            field
            for field in value.fields
            if field.name == binding.name and field.descriptor == binding.descriptor
        ]
        if len(matches) != 1:
            raise JVMBindingError(
                f"JVM field {value.name}.{binding.name}:{binding.descriptor} "
                "was not found exactly once"
            )
        return matches[0]


def render_jvm_bindings(
    classpath: JVMClasspath,
    bindings: tuple[JVMClassBinding, ...],
    *,
    external_classes: tuple[JVMExternalClass, ...] = (),
) -> str:
    """Render selected class members as importable typed Python declarations."""
    if not bindings:
        raise JVMBindingError("at least one JVM class binding is required")
    return _SourceRenderer(classpath, bindings, external_classes).render()


__all__ = [
    "JVMBindingError",
    "JVMClassBinding",
    "JVMExternalClass",
    "JVMFieldBinding",
    "JVMMethodBinding",
    "render_jvm_bindings",
]
