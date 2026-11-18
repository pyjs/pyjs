import math
from types import UnionType
from typing import Union, get_args, get_origin


def expand_metadata(items):
    from annotated_types import GroupedMetadata

    for item in items:
        if isinstance(item, GroupedMetadata):
            yield from expand_metadata(item)
        else:
            yield item


def field_constraints(field, *, model_config=None):
    from annotated_types import Ge, Gt, Le, Lt, MaxLen, MinLen

    names = {Ge: "ge", Gt: "gt", Le: "le", Lt: "lt",
             MinLen: "min_length", MaxLen: "max_length"}
    constraints = {}
    metadata_items = list(expand_metadata(field.metadata))
    for metadata in metadata_items:
        name = names.get(type(metadata))
        if name is None:
            continue
        bound = getattr(metadata, name)
        if type(bound) not in (int, float):
            continue
        if type(bound) is float and not math.isfinite(bound):
            raise TypeError("Client model constraints require finite numeric bounds")
        constraints[name] = bound
    annotation = field.annotation
    text_field = annotation is str or (
        get_origin(annotation) in (Union, UnionType) and str in get_args(annotation))
    if constraints and text_field:
        config = model_config or {}
        transforms = {name: config.get("str_" + name, False)
                      for name in ("strip_whitespace", "to_lower", "to_upper")}
        for metadata in metadata_items:
            for name in transforms:
                value = getattr(metadata, name, None)
                if value is not None:
                    transforms[name] = value
        if any(transforms.values()):
            raise TypeError("Client model field constraints do not support string transformations")
    return constraints
