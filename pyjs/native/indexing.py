"""Checked integer-index conversion shared by native integer consumers."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.objects import Function

from . import (
    calls,
    collection_ops,
    enum_ops,
    nullable,
    numeric_protocols,
    object_values,
    tagged,
)
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported


def sequence_positions(node):
    """Select index parameters, keeping slice subscripts and mapping keys separate."""
    if not isinstance(node, ast.Call) or not node.args:
        return ()
    target = getattr(node.func, "obj", None)
    owner = getattr(target, "cls", None)
    if owner is None or not owner.container.scope.is_builtins:
        return ()
    name = collection_ops.builtin_name(owner)
    operation = target.name
    if name in {"str", "bytes", "list", "tuple"} and operation in {"__mul__", "__rmul__", "__imul__"}:
        return (0,)
    if name in {"list", "tuple"} and operation == "index":
        return range(1, len(node.args))
    if (operation == "__getitem__" and name in {"str", "bytes", "list", "tuple", "range"}
            or name == "list" and operation in {"__setitem__", "__delitem__", "insert", "pop"}):
        source = node.args[0]
        if (operation not in {"__getitem__", "__setitem__", "__delitem__"}
                or collection_ops.builtin_name(analyzed_value_type(source)) != "slice"):
            return (0,)
    return ()


def retain_sequence(node):
    # Syntax synthesizes calls without necessarily visiting visit_Call.
    positions = sequence_positions(node)
    if positions:
        from .binary import repeat_uses_index
        if not repeat_uses_index(node):
            return node
        node.runtime_protocols = (*getattr(node, "runtime_protocols", ()),
            *((analyzed_value_type(node.args[index]), ("__index__",)) for index in positions))
    return node


def integer(e, semantic, kind, value, node, *, error=None):
    # isinstance(x, int) retains bool/int tagged storage until a numeric
    # consumer selects the payload. Do not pass that aggregate as an i64.
    semantic = tagged.effective_type(semantic, kind)
    if nullable.is_object(semantic):
        identity = e.emit_value(f"call ptr @pyjs.runtime.typeof.with.types(ptr {value}, "
                                f"ptr @pyjs.object.types, i64 {len(object_values.runtime_types(e))})")

        def builtin():
            valid = object_values.instancecheck(e, value, NATIVE_ENVIRONMENT.builtins.search("int"), node)
            e.guard_exception(node, valid, "TypeError", error or "object cannot be interpreted as an integer")
            slot = e.emit_value(f"getelementptr %pyjs.object.scalar, ptr {value}, i32 0, i32 1")
            return e.emit_value(f"load i64, ptr {slot}")
    else:
        identity, builtin = None, None
        if tagged.members(semantic):
            return tagged.dispatch(e, semantic, value, "i64",
                lambda member, storage, payload: integer(e, member, storage, payload, node, error=error))
        if nullable.member(semantic):
            present = nullable.present(e, kind, value)
            e.guard_exception(node, present, "TypeError", error or "None cannot be interpreted as an integer")
            payload = value if kind == "ptr" else e.emit_value(f"extractvalue {kind} {value}, 1")
            member = nullable.member(semantic)
            return integer(e, member, e.value_type(member), payload, node, error=error)
        if enum_ops.storage_name(semantic) in {"int", "bool"}:
            return e.emit_value(f"zext i1 {value} to i64") if kind == "i1" else value
        if semantic not in e.module.classes:
            e.guard_exception(node, "false", "TypeError", error or "object cannot be interpreted as an integer")
            return "0"

    def invoke(method):
        if not isinstance(method, Function):
            e.guard_exception(node, "false", "TypeError", error or "object cannot be interpreted as an integer")
            return "0"
        if method.is_static or method.is_classmethod or method.is_property:
            raise LLVMUnsupported("LLVM __index__ requires an instance method returning int", node)
        empty = ast.copy_location(ast.Call(func=node.func, args=[], keywords=[]), node)
        with calls.bind(e, method, empty) as bound:
            storage, result = calls.invoke(e, method, bound, node, receiver=value)
        return numeric_protocols.checked_result(e, method.return_type, storage, result, node, "__index__")

    frame = calls.root_values(e, value)
    result = calls.runtime_protocol(e, semantic, value, "i64",
                                    lambda cls: calls.implicit_method(cls, "__index__", node),
                                    invoke, node, identity=identity, fallback=builtin)
    calls.pop_roots(e, frame)
    return result


def optional(e, semantic, kind, value, default, node, *, error):
    """Convert an optional index exactly once, without invoking None's protocol."""
    semantic = tagged.effective_type(semantic, kind)
    if collection_ops.builtin_name(semantic) == "NoneType" or kind == "void":
        return str(default)
    if nullable.member(semantic):
        return nullable.dispatch(e, semantic, kind, value, "i64", str(default),
            lambda member, storage, payload: integer(e, member, storage, payload, node, error=error))
    if tagged.members(semantic):
        return tagged.dispatch(e, semantic, value, "i64",
            lambda member, storage, payload: optional(e, member, storage, payload, default, node, error=error))
    if nullable.is_object(semantic):
        # Erased None is null too. Do not call __index__ in the absent arm.
        result = e.emit_value("alloca i64")
        e.emit_line(f"store i64 {default}, ptr {result}")
        yes, done = e.new_label("index.present"), e.new_label("index.done")
        present = e.emit_value(f"icmp ne ptr {value}, null")
        e.emit_line(f"br i1 {present}, label %{yes}, label %{done}")
        e.emit_line(f"{yes}:")
        converted = integer(e, semantic, kind, value, node, error=error)
        e.emit_line(f"store i64 {converted}, ptr {result}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")
        return e.emit_value(f"load i64, ptr {result}")
    return integer(e, semantic, kind, value, node, error=error)
