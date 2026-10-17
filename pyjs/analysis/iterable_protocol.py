from dataclasses import dataclass

from pyjs.numeric import NumericFormat

from .objects import (
    CallableClass,
    Class,
    DependencyError,
    Function,
    TypedDictClass,
    UnionType,
)
from .representation import (
    ValueRepresentation,
    direct_representation,
    tuple_representation,
)
from .type_relations import get_type_members, merge_return_types
from .value_representation import (
    merged_representation,
    representation_for_member,
    representations_conflict,
)


def is_abstract_iterable(value_type):
    return (isinstance(value_type, Class) and value_type.container.scope.is_builtins
            and value_type.generic_name == "Iterable")


def is_abstract_iterator(value_type):
    return (isinstance(value_type, Class) and value_type.container.scope.is_builtins
            and value_type.generic_name in {"Iterator", "Generator"})


def retain_iterable_conversion(node, expected):
    """An interface conversion retains protocols, also in nested callbacks."""
    # Untyped callback registrations need not infer the handler's result yet;
    # resolving every function here would introduce initializer/body cycles.
    if not any(is_abstract_iterable(member) or is_abstract_iterator(member) or isinstance(member, CallableClass)
               for member in get_type_members(expected)):
        return
    from .analyzer import callable_value_type
    _retain_iterable_conversions(node, [(callable_value_type(node), expected)])


def acquired_conversions(methods, target):
    """Implicit handle conversions made by acquisition, not source coercion."""
    return [(member, target) for method in methods if method.name == "__iter__"
            for member in get_type_members(method.declared_return_type or method.return_type)
            if not member.container.scope.is_builtins]


def retain_iterator_acquisition(node, source, expected):
    from .analyzer import iterable_protocol
    if protocol := iterable_protocol(source):
        _retain_iterable_conversions(node, acquired_conversions(protocol.methods, expected))


def _retain_iterable_conversions(node, pending):
    from .analyzer import BUILTINS, iterable_protocol
    seen, methods, required, views = set(), [], [], []
    while pending:
        source, target = pending.pop()
        if source is None or target is None or (source, target) in seen:
            continue
        seen.add((source, target))
        if isinstance(source, UnionType) or isinstance(target, UnionType):
            pending.extend((a, b) for a in get_type_members(source) for b in get_type_members(target))
        elif isinstance(source, CallableClass) and isinstance(target, CallableClass):
            pending.append((source.return_type, target.return_type))
            if source.parameter_types is not None and target.parameter_types is not None:
                # Callback inputs are contravariant: the source function
                # receives values promised by the target signature.
                pending.extend(zip(target.parameter_types, source.parameter_types, strict=False))
        elif is_abstract_iterator(source) and is_abstract_iterator(target):
            pending.append((next(iter(source.generic_types.values())), next(iter(target.generic_types.values()))))
            if source.generic_name == target.generic_name == "Generator":
                pending.extend(((target.generic_types['S'], source.generic_types['S']),
                                (source.generic_types['R'], target.generic_types['R'])))
        elif is_abstract_iterable(source) and is_abstract_iterable(target):
            pending.append((source.generic_types['V'], target.generic_types['V']))
        elif is_abstract_iterator(target) and source.generic_name != "NoneType":
            # Nested send/callback conversions are not direct argument uses.
            # Retain both advancing and reacquiring the concrete cursor here.
            protocol = iterable_protocol(source, iterator=True)
            if protocol is not None:
                methods.extend(protocol.methods)
                # Native cursor views adapt through this source signature.
                # Resolve its generic dependencies while analysis can retry.
                BUILTINS.search("Iterator")(protocol.item_type)
                pending.append((protocol.item_type, next(iter(target.generic_types.values()))))
                cursor_methods = cursor_protocol_methods(source)
                methods.extend(cursor_methods)
                pending.extend(acquired_conversions(cursor_methods, target))
                if not source.container.scope.is_builtins:
                    required.append((source, ("__iter__", "__next__")))
                    views.append((source, target))
        elif is_abstract_iterable(target) and not is_abstract_iterable(source) and source.generic_name != "NoneType":
            # Resolve while analysis is active so retryable signature
            # dependencies finish before reachability traverses the body.
            protocol = iterable_protocol(source)
            if protocol is not None:
                methods.extend(protocol.methods)
                pending.append((protocol.item_type, target.generic_types['V']))
                # A view's acquisition adapter needs both cursor signatures.
                # Tuple iteration can refine the source item beyond its generic
                # __iter__ declaration; resolve that type while retries are legal.
                BUILTINS.search("Iterator")(protocol.item_type)
                cursor = BUILTINS.search("Iterator")(target.generic_types['V'])
                pending.extend(acquired_conversions(protocol.methods, cursor))
                if not source.container.scope.is_builtins:
                    required.extend(((source, ("__iter__",)), (source, ("__bool__", "__len__"))))
                    views.append((source, target))
    if methods:
        node.conversion_methods = tuple(dict.fromkeys((*getattr(node, "conversion_methods", ()), *methods)))
    if required:
        node.conversion_protocols = tuple(dict.fromkeys((*getattr(node, "conversion_protocols", ()), *required)))
    if views:
        node.conversion_views = tuple(dict.fromkeys((*getattr(node, "conversion_views", ()), *views)))


@dataclass(frozen=True)
class IterableProtocol:
    item_type: Class | UnionType
    item_representation: ValueRepresentation | None
    item_numeric_formats: frozenset[NumericFormat]
    ordinary_item_types: frozenset[str]
    methods: tuple[Function, ...]
    representation_conflict: bool = False


def iteration_method(value_type, name):
    method = value_type.find_attrs(name)
    if not isinstance(method, Function):
        return None
    if not method.signature_analyzed:
        raise DependencyError(method)
    if (method.is_static or method.is_classmethod or method.params
            or method.vararg is not None or method.kwonlyargs or method.kwarg is not None):
        return None
    return method


def cursor_protocol_methods(value_type):
    """Retain advancement and the acquisition closure of an interface cursor."""
    pending, seen, methods = get_type_members(value_type), set(), []
    while pending:
        member = pending.pop()
        if member in seen or member.generic_name in {"Iterator", "Generator"}:
            continue
        seen.add(member)
        for name in ("__next__", "__iter__"):
            method = iteration_method(member, name)
            if method is None:
                continue
            methods.append(method)
            if name == "__iter__":
                returned = method.declared_return_type or method.return_type
                if returned is None:
                    raise DependencyError(method)
                # A stored cursor can acquire another concrete cursor later.
                # Walk through all such returns, stopping Self/mutual cycles.
                pending.extend(get_type_members(returned))
    return tuple(dict.fromkeys(methods))


def resolve_iterable_protocol(value_type, representation, builtins, *, iterator=False):
    item_type = None
    represented_items = []
    representation_conflict = False
    methods = []
    members = get_type_members(value_type)
    representations = (
        representation.arguments
        if isinstance(value_type, UnionType)
        and representation is not None
        and representation.kind == "union"
        and len(representation.arguments) == len(members)
        else (representation,) * len(members)
    )
    for member, member_representation in zip(
        members,
        representations,
        strict=True,
    ):
        if iterator and not is_abstract_iterator(member):
            # A host-native iterator model (JavaScript's result-record next)
            # is not automatically compatible with Python's __next__ protocol.
            if not hasattr(builtins.search("Iterator").py_cls, "__next__"):
                return None
            method = iteration_method(member, "__next__")
            if method is None:
                return None
            member_type = method.declared_return_type or method.return_type
            if member_type is None:
                raise DependencyError(method)
            member_item_representation = method.return_representation
            methods.append(method)
        elif isinstance(member, TypedDictClass):
            member_type = builtins.search("str")
            member_item_representation = (
                member_representation.arguments[0]
                if member_representation is not None
                and member_representation.arguments
                else None
            )
        else:
            method = iteration_method(member, "__iter__")
            if method is None:
                return None
            return_type = method.declared_return_type or method.return_type
            methods.append(method)
            if not is_abstract_iterator(return_type):
                if return_type is None:
                    raise DependencyError(method)
                returned = resolve_iterable_protocol(return_type, None, builtins, iterator=True)
                if returned is None:
                    return None
                member_type = returned.item_type
                member_item_representation = returned.item_representation
                representation_conflict |= returned.representation_conflict
                methods.extend(returned.methods)
                # iter(value) exposes this cursor as Iterator, so later users
                # can acquire it again without knowing its concrete class.
                methods.extend(cursor_protocol_methods(return_type))
            elif member.container.scope.is_builtins and member.generic_name == "tuple":
                tuple_types = tuple(member.generic_types.values())
                member_type = builtins.search("object") if not tuple_types else None
                for tuple_type in tuple_types:
                    member_type = merge_return_types(member_type, tuple_type)
                tuple_representations = (
                    member_representation.arguments
                    if member_representation is not None
                    else (None,) * len(tuple_types)
                )
                # Iterable context may give a fixed tuple one homogeneous
                # generic witness rather than a per-position tuple vector.
                if (member_representation is not None and member_representation.kind == "generic"
                        and len(tuple_representations) == 1):
                    tuple_representations *= len(tuple_types)
                tuple_items = tuple(zip(tuple_types, tuple_representations, strict=True))
                representation_conflict = (
                    representation_conflict or representations_conflict(tuple_items)
                )
                member_item_representation = merged_representation(
                    member_type,
                    tuple_items,
                )
            elif member.container.scope.is_builtins and member.generic_name == "ItemsView":
                # A view stores K/V contracts; its iterator yields one tuple.
                # Keep annotated views and dict.items() results in the same
                # representation instead of interpreting K as the whole row.
                member_type = return_type.generic_types["V"]
                member_item_representation = tuple_representation(
                    member_representation.arguments if member_representation is not None else (None, None))
            else:
                member_type = return_type.generic_types["V"]
                if (
                    member_representation is not None
                    and member_representation.arguments
                ):
                    member_item_representation = member_representation.arguments[0]
                elif (
                    member_representation is not None
                    and member_representation.array
                ):
                    member_item_representation = direct_representation(
                        member_representation.array.item_numeric,
                        member_representation.array.item_array,
                    )
                elif method.return_representation is not None:
                    arguments = method.return_representation.arguments
                    member_item_representation = arguments[0] if arguments else None
                else:
                    member_item_representation = None
        item_type = merge_return_types(item_type, member_type)
        represented_items.append((member_type, member_item_representation))
    if item_type is None:
        return None
    representation_conflict = representation_conflict or representations_conflict(
        represented_items
    )
    item_representation = (
        None
        if representation_conflict
        else merged_representation(item_type, represented_items)
    )
    return IterableProtocol(
        item_type,
        item_representation,
        frozenset(
            numeric
            for _item_type, item in represented_items
            if item is not None
            for numeric in item.numeric_formats
        ),
        frozenset(
            member.generic_name
            for represented_type, item in represented_items
            for member in get_type_members(represented_type)
            if representation_for_member(represented_type, item, member) is None
        ),
        tuple(dict.fromkeys(methods)),
        representation_conflict,
    )


def expects_iterable(value_type):
    return any(
        isinstance(member, Class) and member.generic_name == "Iterable"
        for member in get_type_members(value_type)
    )
