"""Checked text search arguments over allocation-free Python-authored scans."""

from pyjs.analysis.analyzer import analyzed_value_type

from . import collection_ops, enum_ops, indexing, nullable, object_values, tagged
from .errors import LLVMUnsupported

MODES = {"find": 0, "index": 0, "rfind": 1, "rindex": 1,
         "count": 2, "startswith": 3, "endswith": 4}
BOUND_ERROR = "slice indices must be integers or None or have an __index__ method"


def contains(e, receiver, argument, node, *, binary):
    """Dispatch a closed needle union without re-evaluating either operand."""
    expected = "bytes" if binary else "str"
    none_error = ("a bytes-like object is required, not 'NoneType'" if binary else
                  "'in <string>' requires string as left operand, not NoneType")

    def check(semantic, kind, value):
        semantic, kind, value = tagged.untag_single_member(e, semantic, kind, value, node.args[0])
        if nullable.is_object(semantic):
            raise LLVMUnsupported("LLVM erased text membership requires narrowing the needle", node)
        concrete = nullable.member(semantic)
        if concrete is not None:
            e.guard_exception(node, nullable.present(e, kind, value), "TypeError", none_error)
            return check(concrete, *e.coerce_value(kind, value, e.value_type(concrete), node))
        if tagged.members(semantic):
            return tagged.dispatch(e, semantic, value, "i1", check)
        name = enum_ops.storage_name(semantic)
        if name == "NoneType":
            e.guard_exception(node, "false", "TypeError", none_error)
            return "false"
        if binary and name in {"int", "bool"}:
            value = indexing.integer(e, semantic, kind, value, node)
            e.guard_exception(node, e.emit_value(f"icmp ule i64 {value}, 255"),
                              "ValueError", "byte must be in range(0, 256)")
            return e.emit_value(f"call i1 @pyjs.bytes.contains.byte(ptr {receiver}, i64 {value})")
        if name == expected and kind == "ptr":
            return e.emit_value(f"call i1 @pyjs.string.contains(ptr {receiver}, ptr {value})")
        raise LLVMUnsupported(f"LLVM {expected} membership requires a compatible concrete needle", node)

    semantic = tagged.runtime_type(object_values.instance_type(node.args[0]))
    return "i1", check(semantic, *argument)


def emit(e, operation, receiver, arguments, node, *, binary):
    mode = MODES[operation]
    # All argument expressions have already run. Converting start then stop
    # can call application code; finish both before borrowing any text data.
    limits = [indexing.optional(e, analyzed_value_type(node.args[index]), *arguments[index], default, node,
                               error=BOUND_ERROR)
              if index < len(arguments) else str(default)
              for index, default in ((1, 0), (2, 9223372036854775807))]
    start, stop = limits
    expected = "bytes" if binary else "str"
    binary_flag = str(binary).lower()

    def search(semantic, kind, value):
        semantic, kind, value = tagged.untag_single_member(e, semantic, kind, value, node)
        if tagged.members(semantic):
            return tagged.dispatch(e, semantic, value, "i64", search)
        name = enum_ops.storage_name(semantic)
        if mode >= 3 and collection_ops.builtin_name(semantic) == "tuple":
            if not semantic.generic_types:
                return "0"
            if any(enum_ops.storage_name(member) != expected or e.value_type(member) != "ptr"
                   for member in semantic.generic_types.values()):
                raise LLVMUnsupported("LLVM affix tuples require matching concrete text items", node)
            symbol = "affix"
        elif binary and mode < 3 and name in {"int", "bool"}:
            value = indexing.integer(e, semantic, kind, value, node)
            e.guard_exception(node, e.emit_value(f"icmp ule i64 {value}, 255"),
                              "ValueError", "byte must be in range(0, 256)")
            return e.emit_value(f"call i64 @pyjs.string.search.byte(ptr {receiver}, i64 {value}, "
                                f"i64 {start}, i64 {stop}, i64 {mode})")
        elif name == expected and kind == "ptr":
            symbol = "search"
        else:
            raise LLVMUnsupported(f"LLVM {expected} search requires a compatible concrete needle", node)
        return e.emit_value(f"call i64 @pyjs.string.{symbol}(ptr {receiver}, ptr {value}, "
                            f"i64 {start}, i64 {stop}, i64 {mode}, i1 {binary_flag})")

    value = search(analyzed_value_type(node.args[0]), *arguments[0])
    if operation in {"index", "rindex"}:
        e.guard_exception(node, e.emit_value(f"icmp sge i64 {value}, 0"),
                          "ValueError", "subsection not found" if binary else "substring not found")
    if mode >= 3:
        return "i1", e.emit_value(f"icmp ne i64 {value}, 0")
    return "i64", value
