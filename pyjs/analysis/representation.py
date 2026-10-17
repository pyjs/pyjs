import annotationlib
import collections.abc
import sys
import types
import typing
from dataclasses import dataclass

from pyjs.numeric import (
    ArrayFormat,
    NumericFormat,
    array_format,
    array_item,
    numeric_format,
    unwrap_representation_annotation,
)


@dataclass(frozen=True)
class ValueRepresentation:
    """Target-neutral representation metadata mirroring a Python value type."""

    kind: str | None = None
    numeric: NumericFormat | None = None
    array: ArrayFormat | None = None
    arguments: tuple[ValueRepresentation | None, ...] = ()
    fields: tuple[tuple[str, ValueRepresentation | None], ...] = ()
    parameters: tuple[ValueRepresentation | None, ...] | None = None
    result: ValueRepresentation | None = None

    def __post_init__(self) -> None:
        if self.kind not in {None, "generic", "record", "tuple", "union"}:
            raise ValueError(f"unknown compound representation kind: {self.kind}")
        if self.numeric is not None and self.array is not None:
            raise TypeError("a value cannot have two direct representations")
        if self.direct is not None and self.kind is not None:
            raise TypeError("a direct representation cannot have a compound kind")
        if self.fields and self.kind != "record":
            raise TypeError("record fields require a record representation")
        if self.kind == "record":
            names = tuple(name for name, _value in self.fields)
            if any(type(name) is not str or not name for name in names):
                raise TypeError("record representation fields require names")
            if len(names) != len(set(names)):
                raise TypeError("record representation fields must be unique")
        if self.direct is None and self.kind is None and (
            self.arguments
            or self.parameters is not None
            or self.result is not None
        ):
            raise TypeError("compound members require a compound representation kind")
        if self.kind == "record" and (
            self.arguments or self.parameters is not None or self.result is not None
        ):
            raise TypeError("a record representation cannot have generic members")
        if self.numeric is not None and (
            self.arguments
            or self.fields
            or self.parameters is not None
            or self.result is not None
        ):
            raise TypeError(
                "a direct representation cannot also describe a compound value"
            )
        if self.array is not None and (
            len(self.arguments) > 1
            or self.fields
            or self.parameters is not None
            or self.result is not None
        ):
            raise TypeError("an array representation accepts only one represented item")
        callable_shape = self.parameters is not None or self.result is not None
        if self.kind in {"tuple", "union"} and callable_shape:
            raise TypeError("tuple and union representations accept only arguments")
        if self.kind == "generic" and self.arguments and callable_shape:
            raise TypeError(
                "a generic representation cannot be both a container and callable"
            )

    @property
    def direct(self) -> NumericFormat | ArrayFormat | None:
        return self.numeric or self.array

    @property
    def is_empty(self) -> bool:
        return (
            self.direct is None
            and not any(self.arguments)
            and not any(value for _name, value in self.fields)
            and not any(self.parameters or ())
            and self.result is None
        )

    @property
    def item_representation(self) -> ValueRepresentation | None:
        if self.array is not None:
            if self.arguments:
                return self.arguments[0]
            if self.array.item_numeric is not None:
                return ValueRepresentation(numeric=self.array.item_numeric)
            if self.array.item_array is not None:
                return ValueRepresentation(array=self.array.item_array)
            return None
        if self.kind == "tuple":
            items = self.arguments
        elif self.kind == "union":
            items = tuple(
                value.item_representation if value is not None else None
                for value in self.arguments
            )
        else:
            return self.arguments[0] if self.arguments else None
        if items and all(item == items[0] for item in items[1:]):
            return items[0]
        return None

    @property
    def numeric_formats(self) -> frozenset[NumericFormat]:
        formats = {self.numeric} if self.numeric is not None else set()
        array = self.array
        while array is not None:
            if array.item_numeric is not None:
                formats.add(array.item_numeric)
            array = array.item_array
        children = (
            *self.arguments,
            *(value for _name, value in self.fields),
            *(self.parameters or ()),
            self.result,
        )
        for child in children:
            if child is not None:
                formats.update(child.numeric_formats)
        return frozenset(formats)

    @property
    def direct_numeric_formats(self) -> frozenset[NumericFormat]:
        if self.numeric is not None:
            return frozenset((self.numeric,))
        if self.kind != "union":
            return frozenset()
        return frozenset(
            numeric
            for branch in self.arguments
            if branch is not None
            for numeric in branch.direct_numeric_formats
        )

    @property
    def item_numeric_formats(self) -> frozenset[NumericFormat]:
        if self.array is not None:
            item = self.item_representation
            return item.numeric_formats if item is not None else frozenset()
        if self.kind == "tuple":
            items = self.arguments
        elif self.kind == "union":
            return frozenset(
                numeric
                for branch in self.arguments
                if branch is not None
                for numeric in branch.item_numeric_formats
            )
        else:
            items = self.arguments[:1]
        return frozenset(
            numeric
            for item in items
            if item is not None
            for numeric in item.numeric_formats
        )

    @property
    def contains_only_numeric_representations(self) -> bool:
        if self.numeric is not None:
            return True
        if self.array is not None:
            item = self.item_representation
            return item is None or item.contains_only_numeric_representations
        if (
            self.parameters is not None
            or self.result is not None
        ):
            return False
        members = (
            *self.arguments,
            *(value for _name, value in self.fields),
        )
        return bool(members) and all(
            value is None or value.contains_only_numeric_representations
            for value in members
        )


def direct_representation(
    numeric: NumericFormat | None,
    array: ArrayFormat | None,
) -> ValueRepresentation | None:
    if numeric is None and array is None:
        return None
    return ValueRepresentation(numeric=numeric, array=array)


def apply_representation(target, representation: ValueRepresentation | None) -> None:
    target.representation = representation


def array_representation(
    array: ArrayFormat,
    item: ValueRepresentation | None = None,
) -> ValueRepresentation:
    return ValueRepresentation(
        array=array,
        arguments=(item,) if item is not None else (),
    )


def compound_representation(
    *,
    kind: str = "generic",
    arguments: tuple[ValueRepresentation | None, ...] = (),
    fields: tuple[tuple[str, ValueRepresentation | None], ...] = (),
    parameters: tuple[ValueRepresentation | None, ...] | None = None,
    result: ValueRepresentation | None = None,
) -> ValueRepresentation | None:
    value = ValueRepresentation(
        kind=kind,
        arguments=arguments,
        fields=fields,
        parameters=parameters,
        result=result,
    )
    return None if value.is_empty else value


def tuple_representation(
    arguments: tuple[ValueRepresentation | None, ...],
) -> ValueRepresentation | None:
    return compound_representation(kind="tuple", arguments=arguments)


def numeric_comparison_representations_compatible(
    left: ValueRepresentation | None,
    right: ValueRepresentation | None,
) -> bool:
    """Allow ordinary and fixed numeric values to compare without conversion."""
    if left == right:
        return True
    if left is None:
        return right is not None and right.contains_only_numeric_representations
    if right is None:
        return left.contains_only_numeric_representations
    # A scalar union can carry one represented numeric arm plus ordinary
    # alternatives (e.g. int8 | None). Compare its numeric domains, not the
    # wrapper shape, while still rejecting conflicting represented widths.
    left_members = left.arguments if left.kind == "union" else (left,)
    right_members = right.arguments if right.kind == "union" else (right,)
    if ((left.kind == "union" or right.kind == "union")
            and all(member is None or member.numeric is not None
                    for member in (*left_members, *right_members))):
        return all(numeric_comparison_representations_compatible(a, b)
                   for a in left_members for b in right_members)
    if left.numeric is not None or right.numeric is not None:
        return False
    if left.array is not None or right.array is not None:
        left_item = (
            left.item_representation
            if left.array is not None
            else left.arguments[0]
            if left.kind == "generic" and len(left.arguments) == 1
            else None
        )
        right_item = (
            right.item_representation
            if right.array is not None
            else right.arguments[0]
            if right.kind == "generic" and len(right.arguments) == 1
            else None
        )
        return numeric_comparison_representations_compatible(
            left_item,
            right_item,
        )
    left_fields = tuple(name for name, _value in left.fields)
    right_fields = tuple(name for name, _value in right.fields)
    if (
        left.kind != right.kind
        or len(left.arguments) != len(right.arguments)
        or left_fields != right_fields
        or left.parameters != right.parameters
        or left.result != right.result
    ):
        return False
    return all(
        numeric_comparison_representations_compatible(left_value, right_value)
        for left_value, right_value in zip(
            (
                *left.arguments,
                *(value for _name, value in left.fields),
            ),
            (
                *right.arguments,
                *(value for _name, value in right.fields),
            ),
            strict=True,
        )
    )


def type_alias_value(alias):
    """Quoted references require a type statement in its real module globals."""
    value = alias.__value__
    evaluator = alias.evaluate_value
    module = sys.modules.get(alias.__module__)
    if (module is not None
            and getattr(evaluator, "__qualname__", None) == alias.__name__
            and getattr(evaluator, "__globals__", None) is vars(module)):
        return value  # exec() in another namespace can have the same qualname.
    pending, seen = [value], set()
    while pending:
        member = pending.pop()
        if id(member) in seen:
            continue
        seen.add(id(member))
        if isinstance(member, (str, annotationlib.ForwardRef)):
            raise TypeError("Quoted references require a type statement in its defining module's globals")
        if isinstance(member, typing.TypeAliasType):
            continue  # The referenced alias validates its own lexical boundary.
        unwrapped = unwrap_representation_annotation(member, aliases=False)
        if unwrapped is not member:
            pending.append(unwrapped)
            continue
        if typing.get_origin(member) is typing.Literal:
            continue  # Literal strings are values, not forward type references.
        if isinstance(member, (list, tuple)):
            pending.extend(member)  # Callable parameter annotations.
        elif (item := array_item(member)) is not None:
            pending.append(item)
        else:
            pending.extend(typing.get_args(member))
    return value


def annotation_representation(annotation: object) -> ValueRepresentation | None:
    """Build recursive representation metadata from a Python annotation."""
    active = {}
    recursive = set()
    owner = None

    def visit(value):
        nonlocal owner
        if owner is not None and isinstance(value, (str, annotationlib.ForwardRef)):
            reference = annotationlib.ForwardRef(value, owner=owner) if isinstance(value, str) else value
            value = reference.evaluate(owner=owner)
        key = id(value)
        if key in active:
            # Mark the cycle suffix, not unrelated represented outer siblings.
            recursive.update(tuple(active)[active[key]:])
            return None
        active[key] = len(active)
        previous_owner = owner
        if isinstance(value, typing.TypeAliasType):
            owner = sys.modules.get(value.__module__)
        try:
            result = _annotation_representation(value, visit)
            if key in recursive and result is not None:
                # A finite representation tree cannot describe a represented
                # cycle. Unrelated represented siblings outside it are fine.
                raise TypeError("Recursive annotations with numeric or array representations are not supported")
            return result
        finally:
            owner = previous_owner
            del active[key]

    return visit(annotation)


def _annotation_representation(annotation, visit):
    if isinstance(annotation, typing.TypeAliasType):
        return visit(type_alias_value(annotation))
    numeric = numeric_format(annotation)
    if numeric is not None:
        return direct_representation(numeric, array_format(annotation))
    # Transparent wrappers must not skip an alias's owner/cycle frame. Numeric
    # metadata above is interpreted before discarding an Annotated wrapper.
    unwrapped = unwrap_representation_annotation(annotation, aliases=False)
    if unwrapped is not annotation:
        return visit(unwrapped)
    array = array_format(annotation)
    if array is not None:
        item = visit(array_item(annotation))
        direct_item = direct_representation(array.item_numeric, array.item_array)
        return array_representation(
            array,
            None if item == direct_item else item,
        )

    origin = typing.get_origin(annotation)
    if origin in (types.UnionType, typing.Union):
        return compound_representation(
            kind="union",
            arguments=tuple(
                visit(value) for value in typing.get_args(annotation)
            ),
        )
    if origin in (collections.abc.Callable, typing.Callable):
        parameters, result = typing.get_args(annotation)
        parameter_representations = None
        if parameters is not Ellipsis:
            parameter_representations = tuple(
                visit(parameter) for parameter in parameters
            )
        return compound_representation(
            parameters=parameter_representations,
            result=visit(result),
        )
    if typing.is_typeddict(annotation):
        return compound_representation(
            kind="record",
            fields=tuple(
                (name, visit(value))
                for name, value in typing.get_type_hints(
                    annotation,
                    include_extras=True,
                ).items()
            ),
        )
    if origin is None or origin is typing.Literal:
        return None
    arguments = tuple(
        visit(value)
        for value in typing.get_args(annotation)
        if value is not Ellipsis
    )
    if origin is tuple:
        return tuple_representation(arguments)
    return compound_representation(arguments=arguments)
