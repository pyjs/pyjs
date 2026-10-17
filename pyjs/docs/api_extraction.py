import ast
from pathlib import Path

import griffe

from .api import (
    ApiDocItem,
    ApiDocSection,
    ApiModule,
    ApiObject,
    ApiParameter,
    ApiReference,
    ApiSignature,
    ApiType,
    ApiTypeParameter,
    ApiTypePart,
)

PYJS_IMPLEMENTATION_DECORATORS = {"analyze", "client", "inline"}


def _implementation_decorator(node: ast.expr, name: str) -> bool:
    if isinstance(node, ast.Call):
        node = node.func
    return (
        isinstance(node, ast.Attribute)
        and node.attr in PYJS_IMPLEMENTATION_DECORATORS
        and isinstance(node.value, ast.Name)
        and node.value.id == name
    )


class _PreservePyJSInterfaces(griffe.Extension):
    """Keep public interfaces when a same-name PyJS implementation follows."""

    def __init__(self):
        self.interfaces = {}

    def on_function_node(self, *, node, agent, **kwargs):
        if not any(
            _implementation_decorator(decorator, node.name)
            for decorator in node.decorator_list
        ):
            return
        previous = agent.current.members.get(node.name)
        if previous is not None and previous.is_function:
            self.interfaces[id(node)] = previous

    def on_function_instance(self, *, node, func, agent, **kwargs):
        interface = self.interfaces.pop(id(node), None)
        if interface is not None:
            agent.current.set_member(func.name, interface)


def _type(value) -> ApiType | None:
    if value is None:
        return None
    if isinstance(value, str):
        return ApiType((ApiTypePart(value),))
    parts = []
    for part in value.iterate(flat=True):
        if isinstance(part, str):
            parts.append(ApiTypePart(part))
        else:
            parts.append(ApiTypePart(str(part), part.canonical_path))
    return ApiType(tuple(parts))


def _type_parameters(value) -> tuple[ApiTypeParameter, ...]:
    parameters = []
    for parameter in value:
        parameters.append(
            ApiTypeParameter(
                name=parameter.name,
                kind=parameter.kind.value,
                bound=_type(parameter.bound),
                default=_type(parameter.default),
            )
        )
    return tuple(parameters)


def _parameters(value, *, method: bool) -> tuple[ApiParameter, ...]:
    parameters = []
    for parameter in value:
        if method and parameter.name in {"self", "cls"}:
            continue
        parameters.append(
            ApiParameter(
                name=parameter.name,
                kind=parameter.kind.value,
                annotation=_type(parameter.annotation),
                default=None if parameter.required else str(parameter.default),
            )
        )
    return tuple(parameters)


def _signature(value, *, method: bool = False) -> ApiSignature | None:
    if not value.is_function and not value.is_class:
        return None
    return ApiSignature(
        parameters=_parameters(value.parameters, method=method or value.is_class),
        returns=_type(value.returns) if value.is_function else None,
        type_parameters=_type_parameters(value.type_parameters),
        asynchronous=value.is_function and "async" in value.labels,
    )


def _section_title(kind: str) -> str:
    return {
        "parameters": "Parameters",
        "other parameters": "Other parameters",
        "type parameters": "Type parameters",
        "returns": "Returns",
        "yields": "Yields",
        "receives": "Receives",
        "raises": "Raises",
        "warns": "Warnings",
        "examples": "Examples",
        "attributes": "Attributes",
        "functions": "Functions",
        "classes": "Classes",
        "modules": "Modules",
        "deprecated": "Deprecated",
    }.get(kind, kind.replace("_", " ").title())


def _doc_item(value, kind: str) -> ApiDocItem:
    name = getattr(value, "name", "")
    annotation = getattr(value, "annotation", None)
    if kind in {"raises", "warns"} and annotation is not None:
        name = str(annotation)
    return ApiDocItem(
        name=name,
        description=getattr(value, "description", ""),
        annotation=_type(annotation),
    )


def _doc(value) -> tuple[ApiDocSection, ...]:
    if value.docstring is None:
        return ()
    sections = []
    for section in value.docstring.parse("google"):
        kind = section.kind.value
        if kind == "text":
            sections.append(ApiDocSection(kind=kind, text=section.value))
        elif kind == "examples":
            text = "\n\n".join(item[1] for item in section.value)
            sections.append(
                ApiDocSection(kind=kind, title="Examples", text=text)
            )
        elif isinstance(section.value, list):
            sections.append(
                ApiDocSection(
                    kind=kind,
                    title=_section_title(kind),
                    items=tuple(_doc_item(item, kind) for item in section.value),
                )
            )
        else:
            sections.append(
                ApiDocSection(
                    kind=kind,
                    title=_section_title(kind),
                    text=str(section.value),
                )
            )
    return tuple(sections)


def _source_path(value) -> Path | None:
    filepath = value.filepath
    return Path(filepath) if filepath is not None else None


def _public_class_members(value, public_path: str) -> tuple[ApiObject, ...]:
    members = []
    for name, member in value.members.items():
        if name.startswith("_"):
            continue
        members.append(_object(member, f"{public_path}.{name}", method=True))
    return tuple(members)


def _object(value, public_path: str, *, method: bool = False) -> ApiObject:
    target = value.final_target if value.is_alias else value
    if target.is_module:
        kind = "module"
    elif target.is_class:
        kind = "class"
    elif target.is_function:
        kind = "function"
    elif target.is_type_alias:
        kind = "type alias"
    else:
        kind = "attribute"
    return ApiObject(
        name=public_path.rsplit(".", 1)[-1],
        path=public_path,
        canonical_path=target.path,
        kind=kind,
        source_path=_source_path(target),
        line=target.lineno or 1,
        end_line=target.endlineno or target.lineno or 1,
        signature=_signature(target, method=method),
        annotation=_type(getattr(target, "annotation", None)),
        value=(
            str(target.value)
            if target.is_attribute and target.value is not None
            else None
        ),
        bases=tuple(_type(base) for base in getattr(target, "bases", ())),
        doc=_doc(target),
        members=(
            _public_class_members(target, public_path) if target.is_class else ()
        ),
    )


def _public_member_names(module) -> tuple[str, ...]:
    if module.exports is not None:
        return tuple(str(name) for name in module.exports)
    return tuple(
        name
        for name, member in module.members.items()
        if not name.startswith("_") and member.is_public
    )


def _exported_member(module, name: str):
    member = module.members[name]
    imported_path = module.imports.get(name)
    if imported_path is None or not member.is_module or imported_path == member.path:
        return member
    try:
        return module.modules_collection.get_member(imported_path)
    except KeyError:
        return member


def _module(value, name: str) -> ApiModule:
    public_names = _public_member_names(value)
    missing = [member_name for member_name in public_names if member_name not in value.members]
    if missing:
        raise ValueError(
            f"{name} exports names that static analysis could not resolve: "
            + ", ".join(missing)
        )
    members = tuple(
        _object(_exported_member(value, member_name), f"{name}.{member_name}")
        for member_name in public_names
    )
    source_path = _source_path(value)
    if source_path is None:
        raise ValueError(f"{name} does not resolve to a Python source file")
    return ApiModule(
        name=name,
        source_path=source_path,
        line=value.lineno or 1,
        end_line=value.endlineno or value.lineno or 1,
        doc=_doc(value),
        members=members,
    )


def extract_api(project_root: Path, module_names: tuple[str, ...]) -> ApiReference:
    extensions = griffe.load_extensions("dataclasses")
    extensions.add(_PreservePyJSInterfaces())
    loader = griffe.GriffeLoader(
        extensions=extensions,
        search_paths=[project_root, project_root / "src"],
        docstring_parser="google",
        allow_inspection=False,
    )
    roots = {}
    for name in module_names:
        root_name = name.partition(".")[0]
        if root_name not in roots:
            roots[root_name] = loader.load(root_name)
    modules = []
    for name in module_names:
        root_name = name.partition(".")[0]
        value = roots[root_name]
        if name != root_name:
            value = loader.modules_collection.get_member(name)
        modules.append(_module(value, name))
    return ApiReference(tuple(modules))
