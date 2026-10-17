"""Nominal scalar enums: finite canonical values, not application layouts.

Storage may be int/str, but formatting, identity and boxing must retain the
declared enum. Never broaden collection_ops.builtin_name to erase that type.
"""

import ast
import enum

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.objects import Class, Instance, UnionType

from .errors import LLVMUnsupported


def scalar_name(semantic):
    cls = getattr(semantic, "py_obj", semantic)
    if isinstance(cls, type):
        if issubclass(cls, enum.IntEnum):
            return "int"
        if issubclass(cls, enum.StrEnum):
            return "str"
    return None


def storage_name(semantic):
    from .collection_ops import builtin_name
    from .tagged import runtime_type
    return scalar_name(semantic) or builtin_name(runtime_type(semantic))


def underlying(semantic):
    from .analysis import NATIVE_ENVIRONMENT
    name = scalar_name(semantic)
    return NATIVE_ENVIRONMENT.builtins.search(name) if name else semantic


def validate(cls):
    # Generated EnumType methods are not user code. Custom hooks would alter
    # the finite mapping used here, so reject rather than silently ignore them.
    base = enum.IntEnum if issubclass(cls, enum.IntEnum) else enum.StrEnum
    if {"name", "value"} & cls.__members__.keys():
        raise TypeError("LLVM scalar enum members cannot shadow name/value properties")
    for owner in cls.__mro__[:cls.__mro__.index(base)]:
        for name, value in vars(owner).items():
            if name in cls.__members__:
                # EnumType may install a redirecting enum.property for a
                # member named like str.upper. It is data, not an override.
                continue
            function = getattr(value, "__func__", value)
            inherited = getattr(base, name, None)
            inherited = getattr(inherited, "__func__", inherited)
            if (isinstance(value, property)
                    or (callable(function) or callable(inherited)) and function is not inherited):
                raise TypeError(f"LLVM scalar enums do not support custom behavior ({cls.__name__}.{name})")
    members = tuple(cls)
    for member in members:
        if type(member.value) is not (int if base is enum.IntEnum else str) or member.value != (
                int(member) if base is enum.IntEnum else str(member)):
            raise TypeError("LLVM scalar enum members require unchanged underlying values")
        if base is enum.IntEnum and not -(1 << 63) <= member.value < (1 << 63):
            raise TypeError("LLVM IntEnum values must fit signed i64")
    if len(cls._value2member_map_) != len(members) or any(
            cls._value2member_map_.get(member.value) is not member for member in members):
        raise TypeError("LLVM scalar enums do not support post-definition value aliases")


def check_type_conversion(actual, expected, node):
    from . import nullable

    if expected is None:
        return
    # Presence bits do not preserve an enum's nominal identity. Validate the
    # payload of optional/union sources just as strictly as a direct member.
    for member in actual.types if isinstance(actual, UnionType) else (actual,):
        if scalar_name(member) and expected is not member and nullable.member(expected) is not member:
            raise LLVMUnsupported("LLVM scalar enums cannot be erased or widened; convert to int/str explicitly", node)


def check_conversion(e, kind, value, expected, node):
    from . import object_values

    if expected is None:
        return
    # Equal string constants share storage. A later argument can overwrite
    # value_semantics for that pointer, but never the source's nominal type.
    actual = object_values.instance_type(node) if hasattr(node, "obj") else e.value_semantics.get((kind, value))
    check_type_conversion(actual, expected, node)


def literal(e, value):
    return ("i64", str(int(value))) if isinstance(value, int) else ("ptr", "@" + e.string_constant(str(value)))


def member_value(node):
    obj = getattr(node, "obj", None)
    if isinstance(obj, Instance) and isinstance(obj.py_value, (enum.IntEnum, enum.StrEnum)):
        # Only enum-class constants, never a runtime field whose
        # initializer happened to be an enum member.
        if (isinstance(node, ast.Attribute) and isinstance(getattr(node.value, "obj", None), Class)
                and scalar_name(node.value.obj)):
            return obj.py_value
    return None


def member(e, node):
    value = member_value(node)
    return literal(e, value.value) if value is not None else None


def select(e, semantic, value, project):
    """Select immutable precomputed metadata for a known-valid enum value."""
    result = "@" + e.string_constant("")
    for item in semantic.py_obj:
        kind, candidate = literal(e, item.value)
        match = equal(e, kind, value, candidate)
        output = "@" + e.string_constant(project(item))
        result = e.emit_value(f"select i1 {match}, ptr {output}, ptr {result}")
    return result


def equal(e, kind, left, right):
    return e.emit_value(f"icmp eq i64 {left}, {right}" if kind == "i64" else
                        f"call i1 @pyjs.string.equal(ptr {left}, ptr {right})")


def identity(e, left_type, left_kind, left, right_type, right_kind, right):
    from . import nullable

    if nullable.member(left_type):
        absent = e.emit_value(f"xor i1 {nullable.present(e, right_kind, right)}, true")
        return nullable.dispatch(e, left_type, left_kind, left, "i1", absent,
            lambda member, kind, value: identity(e, member, kind, value, right_type, right_kind, right))
    if nullable.member(right_type):
        return identity(e, right_type, right_kind, right, left_type, left_kind, left)
    return equal(e, left_kind, left, right) if left_type is right_type else "false"


def prepare(e, node):
    from pyjs.analysis.ir import ObjectNew

    if isinstance(node, ObjectNew) and scalar_name(node.value_type):
        # Invalid construction formats its original input and raises ValueError
        # even if the surrounding program otherwise uses only integer values.
        e.module.uses_strings = e.module.uses_repr = True
    elif isinstance(node, ast.Attribute):
        if isinstance(member_value(node), str) or (node.attr == "name"
                and scalar_name(getattr(getattr(node.value, "obj", None), "type", None))):
            e.module.uses_strings = True


def attribute(e, node):
    from . import object_values

    if not isinstance(node, ast.Attribute) or node.attr not in {"name", "value"}:
        return None
    semantic = object_values.instance_type(node.value)
    if not scalar_name(semantic):
        return None
    kind, value = e.expression(node.value)
    if node.attr == "value":
        return kind, value
    return "ptr", select(e, semantic, value, lambda member: member.name)


def construct(e, node):
    from . import calls, representation
    from .analysis import NATIVE_ENVIRONMENT

    call = node.call
    if len(call.args) != 1 or call.keywords or calls.expands_arguments(call):
        raise LLVMUnsupported("LLVM scalar enum construction takes one positional value", node)
    source = call.args[0]
    source_value = kind, value = e.expression(source)
    scalar = scalar_name(node.value_type)
    source_name = storage_name(analyzed_value_type(source))
    if scalar == "int" and source_name == "bool":
        kind, value = "i64", e.emit_value(f"zext i1 {value} to i64")
    elif source_name != scalar:
        raise LLVMUnsupported("LLVM scalar enum construction requires its underlying scalar type", node)
    result, valid = value, "false"
    for item in node.value_type.py_obj:
        _, candidate = literal(e, item.value)
        match = equal(e, kind, value, candidate)
        valid = e.emit_value(f"or i1 {valid}, {match}")
        if scalar == "str":
            result = e.emit_value(f"select i1 {match}, ptr {candidate}, ptr {result}")
    failed, passed = e.new_label("enum.invalid"), e.new_label("enum.valid")
    e.emit_line(f"br i1 {valid}, label %{passed}, label %{failed}")
    e.emit_line(f"{failed}:")
    if node.value_type.py_obj.__members__:
        _, description = representation.render(e, analyzed_value_type(source), *source_value, node)
        message = e.string_concat(description, "@" + e.string_constant(f" is not a valid {node.value_type.name}"))
        exception = "ValueError"
    else:
        message = "@" + e.string_constant(f"<enum '{node.value_type.name}'> has no members; specify `names=()` if you meant to create a new, empty, enum")
        exception = "TypeError"
    e.activate_error(node, NATIVE_ENVIRONMENT.builtins.search(exception), message)
    e.branch_to_exception_target()
    e.emit_line(f"{passed}:")
    return kind, result
