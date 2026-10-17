"""Typed application numeric constructors using ordinary protocol calls."""

import ast
import inspect

from pyjs.analysis.objects import Function

from . import calls, enum_ops, nullable, object_values, tagged
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported


def select(semantic, floating, node=None):
    # A present but disabled primary method must not fall through to __index__.
    # Inspect the class without running descriptors or consulting instance fields.
    name = "__float__" if floating else "__int__"
    absent = object()
    if inspect.getattr_static(semantic.py_obj, name, absent) is absent:
        name = "__index__"
    return name, calls.implicit_method(semantic, name, node)


def checked_result(e, semantic, storage, value, node, name):
    """Validate a numeric protocol's result without invoking another protocol.

    A returned object with its own __index__/__float__ is still invalid. This
    differs from converting an operand, which may invoke those methods once.
    """
    floating = name == "__float__"
    kind = "double" if floating else "i64"
    message = f"{name} returned a non-{'float' if floating else 'int'} value"
    semantic = tagged.effective_type(semantic, storage)
    if tagged.members(semantic):
        return tagged.dispatch(e, semantic, value, kind,
            lambda member, item_kind, item: checked_result(e, member, item_kind, item, node, name))
    if member := nullable.member(semantic):
        e.guard_exception(node, nullable.present(e, storage, value), "TypeError", message)
        payload = value if storage == "ptr" else e.emit_value(f"extractvalue {storage} {value}, 1")
        return checked_result(e, member, e.value_type(member), payload, node, name)
    if nullable.is_object(semantic):
        expected = NATIVE_ENVIRONMENT.builtins.search("float" if floating else "int")
        valid = object_values.instancecheck(e, value, expected, node)
        e.guard_exception(node, valid, "TypeError", message)
        # This is numeric conversion, not an isinstance proof that must keep
        # bool distinguishable from int. Both integer box payloads are i64.
        return object_values.known_payload(e, value, expected)
    if enum_ops.storage_name(semantic) not in ({"float"} if floating else {"int", "bool"}):
        e.guard_exception(node, "false", "TypeError", message)
        return "zeroinitializer"
    return e.emit_value(f"zext i1 {value} to i64") if storage == "i1" else value


def application(e, semantic, value, node, *, floating):
    kind = "double" if floating else "i64"

    def invoke(selected):
        name, method = selected
        if method is None:
            e.guard_exception(node, "false", "TypeError", f"{name} is not callable")
            return "zeroinitializer"
        if (not isinstance(method, Function) or method.is_classmethod or method.is_property
                or method not in e.module.functions):
            raise LLVMUnsupported("native numeric conversion requires an instance or static method", node)
        empty = ast.copy_location(ast.Call(func=node.func, args=[], keywords=[]), node)
        with calls.bind(e, method, empty) as arguments:
            storage, result = calls.invoke(e, method, arguments, node, receiver=value)
        result = checked_result(e, method.return_type, storage, result, node, name)
        if floating and name != "__float__":
            result = e.emit_value(f"sitofp i64 {result} to double")
        return result

    frame = calls.root_values(e, value)
    result = calls.runtime_protocol(e, semantic, value, kind,
        lambda candidate: select(candidate, floating, node), invoke, node)
    calls.pop_roots(e, frame)
    return kind, result
