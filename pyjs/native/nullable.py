"""Native optional values: null references or inline presence/scalar pairs.

The presence bit is independent of the payload: zero, false and NaN are all
present values. Absent scalar payloads are initialized, never LLVM poison.
General multi-member unions still require a separate tagged-value contract.
"""

import ast

from pyjs.analysis.objects import Class, GenericClass, UnionType
from pyjs.analysis.type_relations import is_isinstance_match, is_subclass

from .errors import LLVMUnsupported

SCALARS = {"i1", "i64", "double"}


def member(semantic):
    if not isinstance(semantic, UnionType) or len(semantic.types) != 2:
        return None
    concrete = [item for item in semantic.types if item.generic_name != "NoneType"]
    return concrete[0] if len(concrete) == 1 else None


def is_object(semantic):
    """An erased slot, including redundant unions inferred for method defaults.

    ``dict[str, object].get(key, 1)`` may retain ``object | int`` in analysis;
    object already includes every arm, so it must not become a closed union.
    Nested container members do not make the container itself an erased slot.
    """
    if isinstance(semantic, UnionType):
        return any(is_object(item) for item in semantic.types)
    # Used while the native builtin environment initializes: keep this identity
    # check independent of collection_ops, which imports that environment.
    return (isinstance(semantic, Class) and semantic.container.scope.is_builtins
            and semantic.generic_name == "object")


def pair(kind):
    return f"{{ i1, {kind} }}"


def contains(semantic, name, _seen=None):
    if _seen is None:
        _seen = set()
    if id(semantic) in _seen:
        return False
    _seen.add(id(semantic))
    if isinstance(semantic, UnionType):
        return any(contains(item, name, _seen) for item in semantic.types)
    return ((isinstance(semantic, Class) and semantic.container.scope.is_builtins
             and semantic.generic_name == name)
            or any(contains(item, name, _seen) for item in (getattr(semantic, "generic_types", None) or {}).values()))


def payload_kind(kind):
    return next((scalar for scalar in SCALARS if kind == pair(scalar)), None)


def convert(emitter, kind, value, expected, node):
    if kind == expected:
        return kind, value
    if expected == "ptr" and kind == "void":
        return "ptr", "null"
    scalar = payload_kind(expected)
    if scalar is not None:
        if kind == "void":
            return expected, "zeroinitializer"
        if kind != scalar:
            from . import tagged
            if kind == tagged.STORAGE and scalar == "i64":
                raise LLVMUnsupported(
                    "narrowed optional int may be bool; use an explicit conversion "
                    "int(value) if value is not None else None before integer-only storage", node)
            raise LLVMUnsupported("LLVM optional payload requires its declared numeric type; use an explicit conversion", node)
        present = emitter.emit_value(f"insertvalue {expected} zeroinitializer, i1 true, 0")
        return expected, emitter.emit_value(f"insertvalue {expected} {present}, {kind} {value}, 1")
    scalar = payload_kind(kind)
    if scalar is not None and expected == "void":
        return "void", ""
    if scalar is not None and expected == scalar:
        # Only analysis-proven narrowing may call this direction. Storage
        # remains optional even when a Name/FieldLoad is narrowed in a branch.
        return expected, emitter.emit_value(f"extractvalue {kind} {value}, 1")
    return None


def present(emitter, kind, value):
    from .tagged import STORAGE
    if kind == STORAGE:
        tag = emitter.emit_value(f"extractvalue {STORAGE} {value}, 0")
        return emitter.emit_value(f"icmp ne i64 {tag}, 0")
    if kind == "void":
        return "false"
    if payload_kind(kind) is not None:
        return emitter.emit_value(f"extractvalue {kind} {value}, 0")
    if kind == "ptr":
        return emitter.emit_value(f"icmp ne ptr {value}, null")
    return "true"


def check_narrowing(emitter, kind, value, narrowed, node, label):
    """Check a flow proof before consuming a nullable storage slot as concrete."""
    if member(narrowed):
        return
    valid = present(emitter, kind, value)
    if getattr(narrowed, "generic_name", None) == "NoneType":
        valid = emitter.emit_value(f"xor i1 {valid}, true")
    emitter.guard_exception(node, valid, "TypeError",
                            f"optional {label} changed after narrowing")


def dispatch(emitter, semantic, kind, value, result_kind, absent, callback):
    """Visit only the present payload, so null references are never dereferenced."""
    concrete = member(semantic)
    concrete_kind = emitter.value_type(concrete)
    result = emitter.emit_value(f"alloca {result_kind}")
    emitter.emit_line(f"store {result_kind} {absent}, ptr {result}")
    yes, done = emitter.new_label("optional.present"), emitter.new_label("optional.done")
    emitter.emit_line(f"br i1 {present(emitter, kind, value)}, label %{yes}, label %{done}")
    emitter.emit_line(f"{yes}:")
    payload = value if kind == "ptr" else emitter.emit_value(f"extractvalue {kind} {value}, 1")
    returned = callback(concrete, concrete_kind, payload)
    emitter.emit_line(f"store {result_kind} {returned}, ptr {result}")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    return emitter.emit_value(f"load {result_kind}, ptr {result}")


def typed_node(node, semantic):
    result = ast.copy_location(ast.Name(id="__optional_payload", ctx=ast.Load()), node)
    result.obj = semantic._self
    return result


def compare(emitter, left_type, left, right_type, right, node, *, operation="__eq__", identity=False):
    from .analysis import NATIVE_ENVIRONMENT
    from .comparisons import compare_value, order_value

    def visit(semantic, value, callback):
        concrete = member(semantic)
        if concrete is None:
            return callback(semantic, value)
        kind = emitter.value_type(semantic)
        result = emitter.emit_value("alloca i1")
        yes, no, done = (emitter.new_label("optional.compare." + suffix)
                         for suffix in ("present", "absent", "done"))
        emitter.emit_line(f"br i1 {present(emitter, kind, value)}, label %{yes}, label %{no}")
        emitter.emit_line(f"{yes}:")
        payload = value if kind == "ptr" else emitter.emit_value(f"extractvalue {kind} {value}, 1")
        matched = callback(concrete, payload)
        emitter.emit_line(f"store i1 {matched}, ptr {result}")
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{no}:")
        # None is a real comparison operand: an application callback can
        # accept it, decline it or raise. Never invoke that callback on the
        # present branch with an absent payload typed as a concrete object.
        matched = callback(NATIVE_ENVIRONMENT.builtins.search("NoneType"), "null")
        emitter.emit_line(f"store i1 {matched}, ptr {result}")
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{done}:")
        return emitter.emit_value(f"load i1, ptr {result}")

    def compare_members(a, av, b, bv):
        if operation not in {"__eq__", "__ne__"}:
            return order_value(emitter, operation, a, av, b, bv, node)
        return compare_value(emitter, a, av, b, bv, node,
                             operation=operation, identity=identity, dynamic=True)

    return visit(left_type, left, lambda a, av: visit(right_type, right,
        lambda b, bv: compare_members(a, av, b, bv)))


def string(emitter, semantic, kind, value, node):
    from . import tagged
    from .collection_ops import builtin_name

    if kind == tagged.STORAGE:
        return tagged.dispatch(emitter, tagged.effective_type(semantic, kind), value, "ptr",
            lambda member, storage, payload: string(emitter, member, storage, payload, node))
    if builtin_name(semantic) == "NoneType":
        return f"@{emitter.string_constant('None')}"
    if member(semantic):
        return dispatch(emitter, semantic, kind, value, "ptr", f"@{emitter.string_constant('None')}",
                        lambda concrete, storage, payload: string(emitter, concrete, storage, payload, node))
    if kind == "i1":
        return emitter.string_from_bool(value)
    if kind == "i64":
        return emitter.string_from_int(value)
    if kind == "double":
        return emitter.string_from_float(value)
    if builtin_name(semantic) == "str":
        return value
    if builtin_name(semantic) == "bytes":
        return emitter.owned_text_call("pyjs.text.repr_bytes", [f"ptr {value}"])[1]
    raise LLVMUnsupported("LLVM optional str() requires a scalar, str or bytes value", node)


def instancecheck(emitter, semantic, kind, value, expected, node):
    from .iterable_views import is_view
    if is_view(semantic) and not is_object(expected) and getattr(expected, "generic_name", None) != "NoneType":
        # The interface is not the source's runtime class. In particular a
        # list-backed view must not silently answer False to isinstance(list).
        raise LLVMUnsupported("LLVM isinstance on Iterable views requires concrete source recovery", node)
    if is_object(semantic):
        from . import object_values
        return object_values.instancecheck(emitter, value, expected, node)
    if member(semantic):
        absent = str(is_object(expected) or getattr(expected, "generic_name", None) == "NoneType").lower()
        return dispatch(emitter, semantic, kind, value, "i1", absent,
                        lambda concrete, storage, payload: instancecheck(emitter, concrete, storage, payload, expected, node))
    from . import iterator_ops, protocols
    if (iterator_ops.is_iterator(semantic) and isinstance(expected, (Class, GenericClass))
            and not expected.container.scope.is_builtins):
        return protocols.instancecheck(emitter, value, expected, node)
    if emitter.is_opaque_web_element_type(semantic):
        from . import dom_ops
        if (matched := dom_ops.instancecheck(emitter, kind, value, expected)) is not None:
            return matched
    if isinstance(expected, GenericClass):
        # isinstance(..., list) names the unspecialized class; list[T] is the
        # concrete storage type, not a different Python runtime class.
        actual = semantic
        while actual is not None:
            if getattr(actual, "py_cls", None) is expected.py_cls:
                return "true"
            actual = getattr(actual, "super", None)
        return "false"
    structural = getattr(getattr(semantic, "py_cls", None), "__pyjs_structural__", False)
    if is_isinstance_match(semantic, expected) and (not structural or is_object(expected)):
        return "true"
    if semantic in emitter.module.vtable_roots and expected in emitter.module.classes:
        # The static interface admits assignment-compatible objects; it does
        # not make those objects nominal members of the queried class. Keep
        # these two relations distinct, including for structural receivers.
        candidates = [concrete for concrete in emitter.module.classes if is_subclass(concrete, semantic)]
        if any(concrete not in emitter.module.vtable_roots for concrete in candidates):
            raise LLVMUnsupported("LLVM structural isinstance requires runtime class identity for all concrete sources", node)
        table = emitter.emit_value(f"load ptr, ptr {value}")
        result = "false"
        for concrete in candidates:
            if is_isinstance_match(concrete, expected):
                matches = emitter.emit_value(f"icmp eq ptr {table}, @{emitter.vtable_name(concrete)}")
                result = emitter.emit_value(f"or i1 {result}, {matches}")
        return result
    if (semantic.generic_name == "object" or semantic in emitter.module.classes) and is_subclass(expected, semantic):
        raise LLVMUnsupported("LLVM subclass isinstance requires runtime class identity", node)
    if structural and any(is_subclass(concrete, semantic) and is_isinstance_match(concrete, expected)
                          for concrete in emitter.module.classes):
        # A compatible implementation may inherit the query target even when
        # that target does not implement the structural interface itself.
        raise LLVMUnsupported("LLVM structural isinstance requires runtime class identity for all concrete sources", node)
    return "false"
