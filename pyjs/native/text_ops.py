"""Character construction using checked indices and the shared UTF-8 encoder."""

from pyjs.analysis.analyzer import analyzed_value_type

from . import calls, collection_ops, indexing
from .errors import LLVMUnsupported


def character(e, node):
    if len(node.args) != 1 or node.keywords or calls.expands_arguments(node):
        raise LLVMUnsupported("LLVM chr takes one positional argument", node)
    source = node.args[0]
    kind, value = e.expression(source)
    value = indexing.integer(e, analyzed_value_type(source), kind, value, node)
    valid = e.emit_value(f"icmp ule i64 {value}, 1114111")
    e.guard_exception(node, valid, "ValueError", "chr() arg not in range(0x110000)")
    # All native string consumers assume valid UTF-8. Do not publish a WTF-8
    # surrogate that indexing, codecs and host adapters would interpret differently.
    offset = e.emit_value(f"sub i64 {value}, 55296")
    scalar = e.emit_value(f"icmp ugt i64 {offset}, 2047")
    e.guard_exception(node, scalar, "ValueError", "native chr() does not support lone surrogates")
    codepoint = e.emit_value(f"trunc i64 {value} to i32")
    length = e.emit_value(f"call i64 @pyjs.utf8.encode.at(ptr null, i64 0, i32 {codepoint})")
    result = e.allocated_value(f"call ptr @pyjs.string.new.owned({collection_ops.owner(e)}, i64 {length})")
    field = e.emit_value(f"getelementptr %pyjs.string, ptr {result}, i32 0, i32 1")
    data = e.emit_value(f"load ptr, ptr {field}")
    e.emit_line(f"call i64 @pyjs.utf8.encode.at(ptr {data}, i64 0, i32 {codepoint})")
    return "ptr", result
