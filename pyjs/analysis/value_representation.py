import ast

from pyjs.numeric import NumericFormat, integer_literal

from .objects import (
    CallableClass,
    Class,
    Function,
    Instance,
    UnionType,
    same_analyzer_type,
)
from .representation import (
    ValueRepresentation,
    apply_representation,
    compound_representation,
)


def _type_members(value_type):
    return value_type.types if isinstance(value_type, UnionType) else (value_type,)


def analyzed_value_object(value):
    return getattr(value, "value_obj", value.obj)


def _stored_representation(value):
    representation = getattr(value, "representation", None)
    if representation is not None:
        return representation
    if not hasattr(value, "obj"):
        return None
    value_obj = analyzed_value_object(value)
    return value_obj.representation if isinstance(value_obj, Instance) else None


def analyzed_numeric_format(value):
    """Return representation metadata carried by one analyzed expression."""
    representation = _stored_representation(value)
    return representation.numeric if representation is not None else None


def analyzed_array_format(value):
    representation = _stored_representation(value)
    return representation.array if representation is not None else None


def is_portable_float_format(value):
    return (
        value is not None
        and value.domain == "portable"
        and value.kind == "float"
    )


def integer_numeric_formats(values):
    """Return distinct fixed-width integer formats carried by expressions."""
    return {
        value_format
        for value in values
        if (value_format := analyzed_numeric_format(value)) is not None
        and value_format.kind == "integer"
    }


def numeric_formats(values):
    """Return distinct explicit numeric formats carried by expressions."""
    return {
        value_format
        for value in values
        if (value_format := analyzed_numeric_format(value)) is not None
    }


def possible_numeric_formats(values):
    """Return each direct numeric representation a value may hold."""
    formats = numeric_formats(values)
    for value in values:
        representation = analyzed_representation(value)
        if representation is not None:
            formats.update(representation.direct_numeric_formats)
    return formats


def operation_numeric_format(values):
    """Preserve an unambiguous fixed-width representation through an operation."""
    formats = numeric_formats(values)
    return next(iter(formats)) if len(formats) == 1 else None


def common_array_format(values):
    formats = [analyzed_array_format(value) for value in values]
    if (
        formats
        and formats[0] is not None
        and all(value == formats[0] for value in formats)
    ):
        return formats[0]
    return None


def mixed_array_formats(values):
    formats = [analyzed_array_format(value) for value in values]
    return any(formats) and any(value != formats[0] for value in formats[1:])


def common_numeric_format(values):
    formats = [analyzed_numeric_format(value) for value in values]
    if (
        formats
        and formats[0] is not None
        and all(value == formats[0] for value in formats)
    ):
        return formats[0]
    explicit = {value for value in formats if value is not None}
    if len(explicit) != 1:
        return None
    result = next(iter(explicit))
    if result.domain != "wgsl":
        return None
    for value, value_format in zip(values, formats, strict=True):
        if value_format is not None:
            continue
        source = getattr(value, "python_node", None)
        if source is None:
            source = getattr(value, "static_value", None)
        if result.kind == "integer":
            if integer_literal(source) is None:
                return None
        elif not (
            isinstance(source, ast.Constant) and type(source.value) in {int, float}
        ):
            return None
    return result


def mixed_numeric_formats(values):
    formats = [analyzed_numeric_format(value) for value in values]
    return any(formats) and common_numeric_format(values) is None


def inconsistent_numeric_formats(values):
    formats = [analyzed_numeric_format(value) for value in values]
    return any(formats) and any(value != formats[0] for value in formats[1:])


def resolve_sum_numeric_format(
    common_item: NumericFormat | None,
    possible_items: frozenset[NumericFormat],
    ordinary_item_types: frozenset[str],
    start: NumericFormat | None,
    *,
    ordinary_float_start: bool,
    guaranteed_ordinary_float: bool,
    provably_nonempty: bool,
) -> tuple[NumericFormat | None, str | None]:
    """Resolve a fixed-width ``sum()`` result or its ambiguity reason."""
    numeric = common_item
    if numeric is None and start is not None and not possible_items:
        if start.kind == "integer" and "float" in ordinary_item_types:
            if guaranteed_ordinary_float:
                return None, None
            return None, "ambiguous"
        numeric = start
    if numeric is None and possible_items:
        if (
            start is not None
            and possible_items == {start}
            and not (
                start.kind == "integer" and "float" in ordinary_item_types
            )
        ):
            numeric = start
        elif ordinary_float_start and all(
            value.kind == "integer" for value in possible_items
        ):
            return None, None
        else:
            return None, "ambiguous"
    if numeric is None:
        return None, None
    if start not in {None, numeric}:
        return None, "incompatible_start"
    if numeric.kind == "integer" and ordinary_float_start:
        return None, None
    if not provably_nonempty and start != numeric:
        return None, "potentially_empty"
    return numeric, None


def numeric_format_matches_type(value_format, value_type) -> bool:
    if value_format is None or not isinstance(value_type, Class):
        return False
    expected = "int" if value_format.kind == "integer" else "float"
    return value_type.generic_name == expected


def analyzed_representation(value) -> ValueRepresentation | None:
    representation = _stored_representation(value)
    if representation is not None:
        return representation
    if not hasattr(value, "obj"):
        return None
    value_obj = analyzed_value_object(value)
    if isinstance(value_obj, Function):
        result = value_obj.return_representation
        if value_obj.is_async:
            result = compound_representation(arguments=(result,))
        return compound_representation(
            parameters=tuple(
                getattr(parameter, "representation", None)
                for parameter in value_obj.params
            ),
            result=result,
        )
    callable_type = None
    if isinstance(value_obj, CallableClass):
        callable_type = value_obj
    elif isinstance(value_obj, Instance) and isinstance(
        value_obj.cls,
        CallableClass,
    ):
        callable_type = value_obj.cls
    if callable_type is not None:
        return compound_representation(
            parameters=callable_type.parameter_representations,
            result=callable_type.return_representation,
        )
    return None


def set_analyzed_representation(value, representation) -> None:
    apply_representation(value, representation)
    value_obj = analyzed_value_object(value)
    if isinstance(value_obj, Instance):
        apply_representation(value_obj, representation)


def same_erased_type(left, right) -> bool:
    """Compare analyzer types without their separately tracked representation."""
    if isinstance(left, CallableClass) or isinstance(right, CallableClass):
        if not isinstance(left, CallableClass) or not isinstance(right, CallableClass):
            return False
        if left.parameter_types is None or right.parameter_types is None:
            parameters_match = left.parameter_types is right.parameter_types
        else:
            parameters_match = len(left.parameter_types) == len(
                right.parameter_types
            ) and all(
                same_erased_type(left_type, right_type)
                for left_type, right_type in zip(
                    left.parameter_types,
                    right.parameter_types,
                    strict=True,
                )
            )
        return (
            parameters_match
            and left.minimum_arguments == right.minimum_arguments
            and left.required_keywords == right.required_keywords
            and same_erased_type(left.return_type, right.return_type)
        )
    return same_analyzer_type(left, right)


def representation_for_member(value_type, representation, member):
    if isinstance(value_type, UnionType):
        members = tuple(value_type.types)
        if (
            representation is not None
            and representation.kind == "union"
            and len(representation.arguments) == len(members)
        ):
            for candidate, candidate_representation in zip(
                members,
                representation.arguments,
                strict=True,
            ):
                if candidate is member:
                    return candidate_representation
        return None
    return representation if value_type is member else None


def matching_member_representation(value_type, representation, target):
    for member in _type_members(value_type):
        if same_erased_type(member, target):
            return representation_for_member(
                value_type,
                representation,
                member,
            )
    return None


def representations_conflict(values) -> bool:
    """Return whether equal runtime types carry incompatible representations."""
    values = tuple(values)
    for index, (left_type, left_representation) in enumerate(values):
        for right_type, right_representation in values[index + 1 :]:
            for left_member in _type_members(left_type):
                for right_member in _type_members(right_type):
                    if not same_erased_type(left_member, right_member):
                        continue
                    if representation_for_member(
                        left_type,
                        left_representation,
                        left_member,
                    ) != representation_for_member(
                        right_type,
                        right_representation,
                        right_member,
                    ):
                        return True
    return False


def merged_representation(
    result_type,
    values,
) -> ValueRepresentation | None:
    """Merge already validated representations by runtime-distinguishable type."""
    values = tuple(values)
    members = tuple(_type_members(result_type))
    representations = tuple(
        next(
            (
                matching_member_representation(
                    value_type,
                    representation,
                    member,
                )
                for value_type, representation in values
                if any(
                    same_erased_type(candidate, member)
                    for candidate in _type_members(value_type)
                )
            ),
            None,
        )
        for member in members
    )
    if isinstance(result_type, UnionType):
        return compound_representation(
            kind="union",
            arguments=representations,
        )
    return representations[0] if representations else None


def narrowed_representation(
    original_type,
    representation,
    narrowed_type,
) -> ValueRepresentation | None:
    if (
        representation is None
        or not isinstance(original_type, UnionType)
        or representation.kind != "union"
        or len(representation.arguments) != len(tuple(original_type.types))
    ):
        return representation
    narrowed_members = set(_type_members(narrowed_type))
    selected = tuple(
        member_representation
        for member, member_representation in zip(
            original_type.types,
            representation.arguments,
            strict=True,
        )
        if member in narrowed_members
    )
    if len(selected) == 1:
        return selected[0]
    return compound_representation(kind="union", arguments=selected)
