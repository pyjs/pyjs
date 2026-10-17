import typing

from .objects import (
    CallableClass,
    Class,
    Function,
    GenericClass,
    LiteralClass,
    RecursiveTypeAlias,
    TypedDictClass,
    TypeVariableClass,
    UnionType,
    literal_type,
    same_analyzer_type,
)


def get_type_members(value_type):
    if isinstance(value_type, UnionType):
        return list(value_type.types)
    return [value_type]


def is_builtin_class(value_type, name):
    """Match a concrete builtin semantic class, not an application namesake."""
    return (isinstance(value_type, Class) and value_type.container.scope.is_builtins
            and value_type.generic_name == name)


def inherited_sequence_slot(value_type, name):
    """Resolve a builtin sequence slot without erasing the receiver's type.

    Refined strings and scalar enums inherit sequence operations. A local
    application declaration (including an alias) instead provides a numeric
    method, so stop there rather than classifying it by the storage ancestor.
    """
    while isinstance(value_type, Class):
        if (value_type.container.scope.is_builtins
                and value_type.generic_name in {"str", "bytes", "list", "tuple"}):
            method = value_type.find_attrs(name)
            return method if isinstance(method, Function) else None
        if value_type.find_attrs(name, search_bases=False) is not None:
            return None
        parent = value_type.super
        # None-valued class members need not have analyzed declarations. A
        # Literal refinement shares its parent's Python class, not its own dict.
        if (value_type.py_cls is not getattr(parent, "py_cls", None)
                and name in vars(value_type.py_cls)):
            return None
        value_type = parent
    return None


def callable_member(value_type):
    members = [
        member
        for member in get_type_members(value_type)
        if isinstance(member, CallableClass)
    ]
    return members[0] if len(members) == 1 else None


def contains_callable(value_type, seen=None):
    """Whether mutable generic storage encloses a callable signature."""
    if isinstance(value_type, CallableClass):
        return True
    seen = set() if seen is None else seen
    if id(value_type) in seen:
        return False
    seen.add(id(value_type))
    members = (value_type.types if isinstance(value_type, UnionType)
               else (getattr(value_type, "generic_types", None) or {}).values())
    return any(contains_callable(member, seen) for member in members)


def generated_method(value_type, marker: str) -> Function | None:
    if not isinstance(value_type, Class):
        return None
    method_name = getattr(value_type.py_cls, marker, None)
    if method_name is None:
        return None
    # Host metadata can outlive a backend's mapped base interface (e.g. a
    # browser hydration hook on an opaque native DOM model). Only retain a
    # method present in the analyzed interface, not the unmapped Python base.
    method = value_type.find_attrs(method_name)
    return method if isinstance(method, Function) else None


def literal_member_for_value(value_type, value):
    if not isinstance(value, str):
        return None
    for member in get_type_members(value_type):
        if isinstance(member, LiteralClass) and value in member.values:
            return literal_type((value,), member.scope)
    return None


def contextual_collection_type(value_type, generic_name):
    matches = [
        member
        for member in get_type_members(value_type)
        if isinstance(member, Class)
        and (
            # An empty literal may already be erased to object. Matching that
            # name does not give its non-generic destination a collection shape.
            (member.generic_types is not None and member.generic_name == generic_name)
            or (generic_name == "dict" and isinstance(member, TypedDictClass))
        )
    ]
    return matches[0] if len(matches) == 1 else None


def is_return_type_compatible(expected, actual):
    if expected is None:
        return True
    if expected == actual:
        return True
    if isinstance(expected, Class) and expected.container.scope.is_builtins and expected.generic_name == "Iterable":
        from .iterable_protocol import resolve_iterable_protocol
        from .objects import ModuleScope

        item = next(iter(expected.generic_types.values()))
        for member in get_type_members(actual):
            if (member.container.scope.is_builtins and member.generic_name == "tuple"
                    and not member.generic_types):
                continue  # Empty sources constrain neither item type nor width.
            protocol = resolve_iterable_protocol(member, None, ModuleScope.BUILTINS)
            if protocol is None or not is_return_type_compatible(item, protocol.item_type):
                return False
        return True
    if isinstance(expected, RecursiveTypeAlias) and isinstance(actual, RecursiveTypeAlias):
        # Recursive declarations are nominal; do not try to prove structural
        # equivalence by endlessly comparing their container backedges. An
        # explicit union inclusion (B = A | None) still admits A.
        pending, seen = [expected.target], set()
        while pending:
            member = pending.pop()
            if member is actual:
                return True
            if isinstance(member, UnionType) and member not in seen:
                seen.add(member)
                if isinstance(member, RecursiveTypeAlias):
                    pending.append(member.target)
                else:
                    pending.extend(member._types.values())
        return False
    if isinstance(expected, CallableClass) and isinstance(actual, CallableClass):
        parameter_types_match = (
            expected.parameter_types is None
            or actual.parameter_types is not None
            and actual.accepts_arity(expected.minimum_arguments)
            and actual.accepts_arity(len(expected.parameter_types))
            and all(
                # The supplied function must accept every argument promised
                # by the requested callback view (contravariant inputs).
                is_return_type_compatible(actual_type, expected_type)
                for expected_type, actual_type in zip(
                    expected.parameter_types,
                    actual.parameter_types[:len(expected.parameter_types)],
                    strict=True,
                )
            )
        )
        return (
            parameter_types_match
            and (
                expected.parameter_types is None
                or expected.parameter_representations == (
                    actual.parameter_representations[:len(expected.parameter_types)]
                    if actual.parameter_representations is not None else None
                )
            )
            and is_return_type_compatible(
                expected.return_type,
                actual.return_type,
            )
            and expected.return_representation == actual.return_representation
        )
    expected_types = get_type_members(expected)
    return all(
        any((is_return_type_compatible(expected_type, actual_type)
             if expected_type.container.scope.is_builtins and expected_type.generic_name == "Iterable"
             else is_subclass(actual_type, expected_type)) for expected_type in expected_types)
        for actual_type in get_type_members(actual)
    )


def is_subclass(actual, expected):
    if same_analyzer_type(actual, expected):
        return True
    if isinstance(actual, TypeVariableClass):
        return actual.bound is not None and is_return_type_compatible(
            expected,
            actual.bound,
        )
    if (
        isinstance(actual, Class)
        and isinstance(expected, Class)
        and expected.name == "object"
        and expected.container.scope.is_builtins
    ):
        return True
    if (
        isinstance(actual, Class)
        and isinstance(expected, Class)
        and actual.generic_name == expected.generic_name == "type"
        and actual.container.scope.is_builtins and expected.container.scope.is_builtins
    ):
        actual_type = actual.generic_types["T"]
        expected_type = expected.generic_types["T"]
        return is_return_type_compatible(expected_type, actual_type)
    if isinstance(actual, TypedDictClass) and isinstance(expected, TypedDictClass):
        pending = list(getattr(actual.py_cls, "__orig_bases__", ()))
        seen = set()
        while pending:
            base = pending.pop()
            if base in seen:
                continue
            seen.add(base)
            if base is expected.py_cls:
                return True
            if typing.is_typeddict(base):
                pending.extend(getattr(base, "__orig_bases__", ()))
        return False
    if (
        isinstance(actual, Class)
        and isinstance(expected, Class)
        and actual.generic_name == expected.generic_name
        and actual.py_cls is expected.py_cls
        and expected.generic_types
    ):
        if expected.generic_name == "tuple" and expected.tuple_variadic:
            expected_item = next(iter(expected.generic_types.values()))
            return all(
                is_return_type_compatible(expected_item, actual_item)
                for actual_item in actual.generic_types.values()
            )
        if expected.generic_name == "tuple" and actual.tuple_variadic:
            return False
        if not actual.generic_types:
            return False
        if actual.generic_types.keys() == expected.generic_types.keys():
            if not expected.container.scope.is_builtins and any(
                (contains_callable(actual.generic_types[name]) or contains_callable(expected.generic_types[name]))
                and not same_analyzer_type(actual.generic_types[name], expected.generic_types[name])
                for name in expected.generic_types
            ):
                # Application specializations have separate methods and mutable
                # fields. A callback can adapt at construction/assignment, but
                # changing its enclosing object's type cannot adapt that storage
                # or move method reachability to a different generated class.
                return False
            return all(
                is_return_type_compatible(
                    actual.generic_types[name], expected.generic_types[name],
                )
                # Generator sends are consumed; yields and completion values
                # are produced. Do not apply this rule to an application class
                # merely named Generator.
                if expected.container.scope.is_builtins and expected.generic_name == "Generator" and name == "S"
                else is_return_type_compatible(expected.generic_types[name], actual.generic_types[name])
                for name in expected.generic_types
            )
    if isinstance(expected, CallableClass):
        # Union members and nested containers must use the same optional
        # arity and representation contract as a top-level callable view.
        return isinstance(actual, CallableClass) and is_return_type_compatible(expected, actual)
    if isinstance(expected, LiteralClass):
        return isinstance(actual, LiteralClass) and set(actual.values) <= set(
            expected.values
        )
    if is_numeric_promotion(actual, expected):
        return True
    if (expected.container.scope.is_builtins and expected.generic_name == "Iterator"
            and actual.container.scope.is_builtins and actual.generic_name == "Generator"):
        return is_return_type_compatible(next(iter(expected.generic_types.values())),
                                         next(iter(actual.generic_types.values())))
    if (expected.container.scope.is_builtins and expected.generic_name == "Iterator"
            and not (actual.container.scope.is_builtins and actual.generic_name in {"Iterator", "Generator"})):
        from .iterable_protocol import iteration_method, resolve_iterable_protocol
        from .objects import ModuleScope

        protocol = resolve_iterable_protocol(actual, None, ModuleScope.BUILTINS, iterator=True)
        return (protocol is not None and iteration_method(actual, "__iter__") is not None
                and is_return_type_compatible(next(iter(expected.generic_types.values())), protocol.item_type))
    if getattr(expected.py_cls, "__pyjs_structural__", False):
        try:
            if all(
                isinstance(actual.find(name), Function)
                for name in structural_method_names(expected)
            ):
                return True
        except NameError:
            pass
    while actual is not None:
        if same_analyzer_type(actual, expected):
            return True
        actual = actual.super
    return False


def is_numeric_promotion(actual, expected):
    # The typing-only int-to-float relation must not apply to namesakes in an
    # application module, nor become a runtime isinstance relationship.
    return (expected.name == "float" and actual.name in {"bool", "int"}
            and expected.container.scope.is_builtins and actual.container.scope.is_builtins)


def is_isinstance_match(actual, expected):
    if is_numeric_promotion(actual, expected):
        return False
    if getattr(getattr(expected, "py_cls", None), "__pyjs_structural__", False):
        # Structural typing permits a compatible interface, not membership in
        # its runtime class. Only an actual base chain proves that relation.
        while actual is not None:
            if same_analyzer_type(actual, expected):
                return True
            actual = getattr(actual, "super", None)
        return False
    return is_subclass(actual, expected)


def is_strict_runtime_subclass(actual, expected):
    """Operator priority follows class ancestry, not generic storage compatibility."""
    if actual.py_cls is expected.py_cls:
        return False
    base = actual.super
    while base is not None:
        if base.py_cls is expected.py_cls:
            return True
        base = base.super
    return False


def structural_method_names(cls: Class) -> tuple[str, ...]:
    if not getattr(cls.py_cls, "__pyjs_structural__", False):
        return ()
    return tuple(
        name
        for name, value in cls.internal_scope.names.items()
        if isinstance(value, Function) and not name.startswith("_")
    )


def merge_return_types(left, right):
    if left is None:
        return right
    if left == right:
        return left
    # Inferred joins retain an opaque object contract rather than manufacturing
    # redundant object|T arms. Explicit annotation unions are built elsewhere.
    merged = UnionType()
    for value_type in get_type_members(left):
        if is_builtin_class(value_type, "object"):
            return value_type
        merged.add(value_type)
    for value_type in get_type_members(right):
        if is_builtin_class(value_type, "object"):
            return value_type
        merged.add(value_type)
    return merged.type


def merge_conditional_types(left, right):
    if not isinstance(left, CallableClass) or not isinstance(right, CallableClass):
        return merge_return_types(left, right)
    if left.parameter_types is None:
        parameters = right.parameter_types
    elif right.parameter_types is None:
        parameters = left.parameter_types
    elif len(left.parameter_types) == len(right.parameter_types) and all(
        same_analyzer_type(left_type, right_type)
        for left_type, right_type in zip(
            left.parameter_types,
            right.parameter_types,
            strict=True,
        )
    ):
        parameters = left.parameter_types
    else:
        return merge_return_types(left, right)
    return CallableClass(
        parameters,
        merge_return_types(left.return_type, right.return_type),
        left.super,
        (
            left.parameter_representations
            if left.parameter_representations == right.parameter_representations
            else None
        ),
        (
            left.return_representation
            if left.return_representation == right.return_representation
            else None
        ),
        # Ellipsis hides parameter/default information; it is not evidence that
        # the opaque implementation accepts the concrete alternative's omissions.
        # Preserve the existing full-arity boundary when choosing a concrete view.
        minimum_arguments=(len(parameters or ())
                           if left.parameter_types is None or right.parameter_types is None
                           else max(left.minimum_arguments, right.minimum_arguments)),
        required_keywords=tuple(dict.fromkeys((*left.required_keywords, *right.required_keywords))),
    )


def contains_type_variable(value_type, target=None, _seen=None):
    if _seen is None:
        _seen = set()
    if id(value_type) in _seen:
        return False
    _seen.add(id(value_type))
    if isinstance(value_type, TypeVariableClass):
        return target is None or value_type is target
    if isinstance(value_type, UnionType):
        return any(
            contains_type_variable(member, target, _seen) for member in value_type.types
        )
    if isinstance(value_type, CallableClass):
        return (
            value_type.parameter_types is not None
            and any(
                contains_type_variable(parameter, target, _seen)
                for parameter in value_type.parameter_types
            )
        ) or contains_type_variable(value_type.return_type, target, _seen)
    return isinstance(value_type, Class) and any(
        contains_type_variable(member, target, _seen)
        for member in (value_type.generic_types or {}).values()
    )


def contains_json_object_schema(value_type, _seen=None):
    if _seen is None:
        _seen = set()
    if id(value_type) in _seen:
        return False
    _seen.add(id(value_type))
    if isinstance(value_type, UnionType):
        return any(contains_json_object_schema(member, _seen) for member in value_type.types)
    if not isinstance(value_type, Class):
        return False
    if (
        isinstance(value_type, TypedDictClass)
        and value_type.py_cls.__module__ == "pyjs.javascript"
        and value_type.py_cls.__qualname__ == "JSONObject"
    ):
        return True
    return any(
        contains_json_object_schema(member, _seen)
        for member in (value_type.generic_types or {}).values()
    )


def substitute_type_variables(value_type, bindings):
    if isinstance(value_type, RecursiveTypeAlias):
        return value_type
    if isinstance(value_type, TypeVariableClass):
        return bindings.get(value_type, value_type)
    if isinstance(value_type, UnionType):
        # Substitute declared edges, not the expanded semantic view.
        # T | None may expose T's concrete recursive target in .types;
        # retaining its named edge also bounds generic substitution.
        return UnionType(
            types=[
                substitute_type_variables(member, bindings)
                for member in value_type._types.values()
            ]
        ).type
    if isinstance(value_type, CallableClass):
        parameters = None
        if value_type.parameter_types is not None:
            parameters = tuple(
                substitute_type_variables(parameter, bindings)
                for parameter in value_type.parameter_types
            )
        return CallableClass(
            parameters,
            substitute_type_variables(value_type.return_type, bindings),
            value_type.super,
            value_type.parameter_representations,
            value_type.return_representation,
            minimum_arguments=value_type.minimum_arguments,
            required_keywords=value_type.required_keywords,
        )
    if not isinstance(value_type, Class) or not value_type.generic_types:
        return value_type
    members = tuple(
        substitute_type_variables(member, bindings)
        for member in value_type.generic_types.values()
    )
    if all(
        same_analyzer_type(original, replacement)
        for original, replacement in zip(
            value_type.generic_types.values(),
            members,
            strict=True,
        )
    ):
        return value_type
    generic = value_type.container.search(value_type.generic_name)
    assert isinstance(generic, GenericClass)
    return generic(
        *members,
        tuple_variadic=value_type.tuple_variadic,
    )
