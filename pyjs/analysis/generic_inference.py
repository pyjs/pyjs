from .objects import (
    CallableClass,
    Class,
    RecursiveTypeAlias,
    TypeVariableClass,
    UnionType,
)
from .representation import (
    ValueRepresentation,
    compound_representation,
    direct_representation,
    tuple_representation,
)
from .type_relations import (
    contains_type_variable,
    is_return_type_compatible,
    merge_return_types,
)


def infer_type_variables(
    pattern,
    actual,
    bindings,
    iterable_item_type,
    *,
    defaults=False,
):
    if isinstance(pattern, TypeVariableClass):
        if defaults:
            bindings.setdefault(pattern, actual)
            return
        current = bindings.get(pattern)
        bindings[pattern] = merge_return_types(current, actual)
        return
    if isinstance(pattern, UnionType):
        candidates = [
            member for member in pattern.types if contains_type_variable(member)
        ]
        if len(candidates) == 1:
            infer_type_variables(
                candidates[0],
                actual,
                bindings,
                iterable_item_type,
                defaults=defaults,
            )
            return
        concrete = [
            member for member in pattern.types if not contains_type_variable(member)
        ]
        if any(is_return_type_compatible(member, actual) for member in concrete):
            return
        return
    if isinstance(pattern, CallableClass) and isinstance(actual, CallableClass):
        if pattern.parameter_types is not None and actual.parameter_types is not None:
            for pattern_parameter, actual_parameter in zip(
                pattern.parameter_types,
                actual.parameter_types,
                strict=False,
            ):
                parameter_bindings = {}
                infer_type_variables(
                    pattern_parameter,
                    actual_parameter,
                    parameter_bindings,
                    iterable_item_type,
                    defaults=defaults,
                )
                for parameter, value_type in parameter_bindings.items():
                    bindings.setdefault(parameter, value_type)
        infer_type_variables(
            pattern.return_type,
            actual.return_type,
            bindings,
            iterable_item_type,
            defaults=defaults,
        )
        return
    if not isinstance(pattern, Class) or not pattern.generic_types:
        return
    if pattern.generic_name in {"Iterable", "Iterator"}:
        if (not defaults and isinstance(actual, Class) and actual.container.scope.is_builtins
                and actual.generic_name == "tuple" and not actual.generic_types):
            return
        pattern_item = next(iter(pattern.generic_types.values()))
        infer_type_variables(
            pattern_item,
            iterable_item_type(actual, iterator=pattern.generic_name == "Iterator"),
            bindings,
            iterable_item_type,
            defaults=defaults,
        )
        return
    if not isinstance(actual, Class):
        return
    while actual is not None and pattern.generic_name != actual.generic_name:
        actual = actual.super
    if actual is None:
        return
    for pattern_member, actual_member in zip(
        pattern.generic_types.values(),
        actual.generic_types.values(),
        strict=False,
    ):
        infer_type_variables(
            pattern_member,
            actual_member,
            bindings,
            iterable_item_type,
            defaults=defaults,
        )


def _representation_arguments(value_type, representation):
    members = tuple((getattr(value_type, "generic_types", None) or {}).values())
    if representation is not None and representation.arguments:
        return representation.arguments
    if representation is not None and representation.array is not None:
        return (
            direct_representation(
                representation.array.item_numeric,
                representation.array.item_array,
            ),
        )
    return (None,) * len(members)


def infer_representation_variables(
    pattern,
    actual,
    representation,
    bindings,
    iterable_protocol,
) -> bool:
    if isinstance(pattern, TypeVariableClass):
        if pattern in bindings:
            return bindings[pattern] == representation
        bindings[pattern] = representation
        return True
    if isinstance(pattern, UnionType):
        candidates = [
            member for member in pattern.types if contains_type_variable(member)
        ]
        if len(candidates) == 1:
            return infer_representation_variables(
                candidates[0],
                actual,
                representation,
                bindings,
                iterable_protocol,
            )
        return True
    if isinstance(pattern, CallableClass) and isinstance(actual, CallableClass):
        if pattern.parameter_types is not None and actual.parameter_types is not None:
            actual_parameters = actual.parameter_representations or (None,) * len(
                actual.parameter_types
            )
            for pattern_type, actual_type, actual_representation in zip(
                pattern.parameter_types,
                actual.parameter_types,
                actual_parameters,
                strict=False,
            ):
                if not infer_representation_variables(
                    pattern_type,
                    actual_type,
                    actual_representation,
                    bindings,
                    iterable_protocol,
                ):
                    return False
        return infer_representation_variables(
            pattern.return_type,
            actual.return_type,
            actual.return_representation,
            bindings,
            iterable_protocol,
        )
    if not isinstance(pattern, Class) or not pattern.generic_types:
        return True
    if pattern.generic_name in {"Iterable", "Iterator"}:
        # An empty tuple contributes no item constraint. In particular it must
        # not erase a portable representation established by another argument.
        if (isinstance(actual, Class) and actual.container.scope.is_builtins
                and actual.generic_name == "tuple" and not actual.generic_types):
            return True
        protocol = iterable_protocol(actual, representation, iterator=pattern.generic_name == "Iterator")
        if protocol is None:
            return representation is None
        if protocol.representation_conflict:
            return False
        return infer_representation_variables(
            next(iter(pattern.generic_types.values())),
            protocol.item_type,
            protocol.item_representation,
            bindings,
            iterable_protocol,
        )
    if not isinstance(actual, Class):
        return True
    while actual is not None and pattern.generic_name != actual.generic_name:
        actual = actual.super
    if actual is None:
        return True
    actual_representations = _representation_arguments(actual, representation)
    for pattern_member, actual_member, actual_representation in zip(
        pattern.generic_types.values(),
        actual.generic_types.values(),
        actual_representations,
        strict=False,
    ):
        if not infer_representation_variables(
            pattern_member,
            actual_member,
            actual_representation,
            bindings,
            iterable_protocol,
        ):
            return False
    return True


def substitute_representation_variables(
    value_type,
    representation,
    bindings,
) -> ValueRepresentation | None:
    if isinstance(value_type, RecursiveTypeAlias):
        return representation
    if isinstance(value_type, TypeVariableClass):
        return bindings.get(value_type, representation)
    if isinstance(value_type, UnionType):
        # Expanded optional aliases can cycle through their concrete members.
        # Closed unions have no substitutions; preserve their metadata instead
        # of recursively rebuilding it. contains_type_variable is cycle-aware.
        if not contains_type_variable(value_type):
            return representation
        members = tuple(value_type.types)
        declared = (
            representation.arguments
            if representation is not None
            and representation.kind == "union"
            and len(representation.arguments) == len(members)
            else (None,) * len(members)
        )
        return compound_representation(
            kind="union",
            arguments=tuple(
                substitute_representation_variables(member, child, bindings)
                for member, child in zip(members, declared, strict=True)
            ),
        )
    if isinstance(value_type, CallableClass):
        parameters = None
        if value_type.parameter_types is not None:
            declared_parameters = (
                representation.parameters
                if representation is not None
                and representation.parameters is not None
                else (None,) * len(value_type.parameter_types)
            )
            parameters = tuple(
                substitute_representation_variables(parameter, child, bindings)
                for parameter, child in zip(
                    value_type.parameter_types,
                    declared_parameters,
                    strict=True,
                )
            )
        return compound_representation(
            parameters=parameters,
            result=substitute_representation_variables(
                value_type.return_type,
                representation.result if representation is not None else None,
                bindings,
            ),
        )
    if representation is not None and representation.direct is not None:
        return representation
    if not isinstance(value_type, Class) or not value_type.generic_types:
        return representation
    declared = _representation_arguments(value_type, representation)
    kind = representation.kind if representation is not None else "generic"
    arguments = tuple(
        substitute_representation_variables(member, child, bindings)
        for member, child in zip(
            value_type.generic_types.values(),
            declared,
            strict=True,
        )
    )
    if value_type.generic_name == "tuple":
        return tuple_representation(arguments)
    return compound_representation(kind=kind, arguments=arguments)
