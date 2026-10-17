"""Read-only native views of validated host Pydantic models, not validators."""

import builtins
from types import UnionType
from typing import Annotated, Literal, TypeAliasType, Union, get_args, get_origin

from pyjs.analysis.libraries import LibraryClassInfo
from pyjs.analysis.objects import LiteralClass
from pyjs.analysis.objects import UnionType as AnalyzedUnion
from pyjs.numeric import numeric_format


def host_annotation(annotation):
    """Unwrap aliases/metadata without losing a host model's nominal identity."""
    while True:
        if isinstance(annotation, TypeAliasType):
            annotation = annotation.__value__
        elif get_origin(annotation) is Annotated:
            annotation = get_args(annotation)[0]
        else:
            return annotation


def host_identity(annotation, seen=()):
    """Only nominal model identities distinguish otherwise equal ABI shapes.

    Ordinary aliases must still share schemas so cyclic/shared host containers
    are copied once. Metadata and primitive union order do not affect copy-in.
    """
    if any(annotation is item for item in seen):
        return None
    seen = (*seen, annotation)
    annotation = host_annotation(annotation)
    if is_model(annotation):
        return annotation
    identities = tuple(host_identity(item, seen) for item in get_args(annotation))
    if not any(identity is not None for identity in identities):
        return None
    origin = get_origin(annotation)
    # Equivalent unions share copied views regardless of member order. Keep
    # container origins/positions so swapping their model types cannot collide.
    return (UnionType, frozenset(identities)) if origin in (UnionType, Union) else (origin, identities)


def _union_members(annotation):
    annotation = host_annotation(annotation)
    if get_origin(annotation) in (UnionType, Union):
        for member in get_args(annotation):
            yield from _union_members(member)
    else:
        yield annotation


def _matches_argument(annotation, semantic, seen=()):
    """Compare an already-analyzed generic argument without analyzing new code.

    Host annotations retain nominal Pydantic specializations, whereas analyzed
    classes retain their origin and semantic arguments. Compare those arguments
    by identity/structure, never their names or union order. The pair guard
    preserves recursive aliases without expanding their graph indefinitely.
    """
    if any(annotation is old and semantic is value for old, value in seen):
        return True
    seen = (*seen, (annotation, semantic))
    annotation = host_annotation(annotation)
    origin, args = get_origin(annotation), get_args(annotation)
    if isinstance(semantic, AnalyzedUnion):
        args = tuple(dict.fromkeys(_union_members(annotation)))
        return origin in (UnionType, Union) and len(args) == len(semantic.types) and all(
            any(_matches_argument(arg, member, seen) for arg in args) for member in semantic.types)
    if isinstance(semantic, LiteralClass):
        return origin is Literal and set(args) == set(semantic.values)
    if (numeric := numeric_format(annotation)) is not None:
        annotation = int if numeric.kind == "integer" else float
    if is_model(annotation):
        metadata = annotation.__pydantic_generic_metadata__
        origin, args = metadata.get("origin"), metadata.get("args", ())
    expected = (getattr(builtins, semantic.generic_name, type(None) if semantic.generic_name == "NoneType" else None)
                if semantic.container.scope.is_builtins else semantic.py_obj)
    actual = origin or annotation
    if not semantic.container.scope.is_builtins:
        actual = semantic.container.library_mappings.resolve(actual)
    if actual is not expected:
        return False
    if getattr(semantic, "tuple_variadic", False):
        if args[-1:] != (Ellipsis,):
            return False
        args = args[:-1]
    parameters = tuple((semantic.generic_types or {}).values())
    return len(args) == len(parameters) and all(
        _matches_argument(arg, parameter, seen) for arg, parameter in zip(args, parameters, strict=True))


def union_member(annotation, expected, semantic=None):
    """Project by runtime identity, not annotation order or a class spelling.

    Native tagged unions reject duplicate container layouts before using this
    projection. Aliases may hide either the union or one of its members.
    """
    candidates = []
    for member in _union_members(annotation):
        origin = (member.__pydantic_generic_metadata__.get("origin")
                  if is_model(member) else get_origin(member))
        if (origin or member) is expected:
            candidates.append(member)
    # Keep an unambiguous host annotation verbatim, including nominal details
    # intentionally normalized by analysis. Only competing specializations
    # need argument matching; ordinary optional/model inputs are unchanged.
    if len(candidates) > 1 and semantic is not None:
        candidates = [member for member in candidates if _matches_argument(member, semantic)]
    return candidates[0] if candidates else None


class BaseModel:
    # These declarations preserve the fact that model operations differ from
    # object operations. Native analysis rejects their operations when reached;
    # inheriting object equality/repr would silently change Python behavior.
    # The initializer is only a reachability placeholder for annotated types;
    # native analysis rejects source-level construction and initializer access.
    def __init__(self, **values: object) -> None: ...

    def __eq__(self, other: object) -> bool: ...

    def __ne__(self, other: object) -> bool: ...

    def __str__(self) -> str: ...

    def __repr__(self) -> str: ...

    def __hash__(self) -> int: ...

    def __bool__(self) -> bool: ...


def is_model(cls):
    return (isinstance(cls, type) and any(
        base.__module__ == "pydantic.main" and base.__name__ == "BaseModel"
        for base in cls.__mro__[1:]))


def class_info(cls):
    if not is_model(cls):
        return None
    if cls.__pydantic_root_model__:
        raise TypeError(
            "native Pydantic inputs do not support RootModel; "
            "pass its root value with a supported annotation instead"
        )
    if not cls.__pydantic_complete__:
        raise TypeError(f"Rebuild Pydantic model {cls.__name__} before native compilation")
    # Values already passed host validation. Never invoke defaults/factories
    # during compilation or reinterpret Field metadata as executable code.
    return LibraryClassInfo(
        {name: field.rebuild_annotation() for name, field in cls.model_fields.items()},
        {}, (), opaque=True,
    )
