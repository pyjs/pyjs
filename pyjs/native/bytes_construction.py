"""Checked bytes construction through the shared index and iterable protocols."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.ir import CollectionNew
from pyjs.analysis.objects import Class, Function
from pyjs.analysis.type_relations import get_type_members, is_subclass

from . import calls, collection_ops, enum_ops, indexing
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .protocols import compatible_source

PROTOCOLS = ("__bytes__", "__index__", "__iter__")


def view_required(e, target):
    # Only retain an extra view callback when a reached bytes consumer can
    # receive this interface. Ordinary iteration must not analyze __bytes__.
    return any(names == PROTOCOLS and receiver is not None
               and any(is_subclass(target, member) for member in get_type_members(receiver))
               for receiver, names in e.module.entry_function.runtime_dunder_dependencies)


def from_count(e, count, node):
    e.guard_exception(node, e.emit_value(f"icmp sge i64 {count}, 0"), "ValueError", "negative count")
    return e.owned_text_call("pyjs.text.new_bytes", [f"i64 {count}", "ptr null"])[1]


def from_items(e, semantic, value, node):
    frame = None
    if (collection_ops.builtin_name(semantic) == "list"
            and e.value_type(collection_ops.item_type(semantic)) == "i64"):
        valid = e.emit_value(f"call i1 @pyjs.text.valid_byte_items(ptr {value})")
        e.guard_exception(node, valid, "ValueError", "bytes must be in range(0, 256)")
    else:
        integer = NATIVE_ENVIRONMENT.builtins.search("int")
        staged = collection_ops.new_list(e, integer)
        frame = calls.root_values(e, staged)

        def consume(actual, item):
            kind = e.value_type(actual)
            if kind not in {"i64", "i1"}:
                raise LLVMUnsupported("LLVM bytes() iterable items must be integers", node)
            if kind == "i1":
                item = e.emit_value(f"zext i1 {item} to i64")
            valid = e.emit_value(f"icmp ule i64 {item}, 255")
            # Fail on this item before requesting the next callback.
            e.guard_exception(node, valid, "ValueError", "bytes must be in range(0, 256)")
            collection_ops.append(e, staged, integer, integer, item, node)

        collection_ops.loop(e, semantic, value, consume, node)
        value = staged
    count = e.emit_value(f"load i64, ptr {value}")
    result = e.owned_text_call("pyjs.text.new_bytes", [f"i64 {count}", f"ptr {value}"])[1]
    calls.pop_roots(e, frame)
    return result


def construct(e, node):
    if node.keywords or len(node.args) > 1:
        raise LLVMUnsupported("LLVM bytes() requires at most one positional argument", node)
    if not node.args:
        return "ptr", f"@{e.string_constant(b'')}"
    source = node.args[0]
    if isinstance(source, CollectionNew) and isinstance(source.source, ast.List) and not source.source.elts:
        return "ptr", f"@{e.string_constant(b'')}"
    semantic = analyzed_value_type(source)
    if not isinstance(semantic, Class):
        raise LLVMUnsupported("LLVM bytes() requires a concrete count or iterable; narrow unions before use", node)
    storage, value = e.expression(source)
    return "ptr", convert(e, semantic, storage, value, node)


def convert(e, semantic, storage, value, node):
    from . import iterable_views, iterator_ops
    kind = collection_ops.builtin_name(semantic)
    if iterable_views.is_view(semantic):
        return iterable_views.invoke(e, value, node, operation="bytes")
    if kind == "bytes":
        return value
    if enum_ops.storage_name(semantic) in {"int", "bool"}:
        count = indexing.integer(e, semantic, storage, value, node)
        return from_count(e, count, node)

    # Keep a temporary producer alive through cursor callbacks, staging-buffer
    # growth and the final output allocation. Checked exceptions unwind roots.
    frame = calls.root_values(e, value)
    if semantic in e.module.classes:
        result = application(e, semantic, value, node)
    elif iterator_ops.is_iterator(semantic) and e.module.application_iterators:
        from .protocols import dispatch_source
        result = dispatch_source(e, value, "ptr",
            lambda source: application(e, semantic, source, node, checked=True),
            lambda: from_items(e, semantic, value, node))
    else:
        if kind not in {"list", "tuple", "range", "set", "frozenset", "dict", "KeysView", "ValuesView", "Iterator", "Generator"}:
            raise LLVMUnsupported("LLVM bytes() requires bytes, an integer count, or a typed integer iterable", node)
        result = from_items(e, semantic, value, node)
    calls.pop_roots(e, frame)
    return result


def application(e, semantic, value, node, *, checked=False):
    def select(candidate):
        # Runtime-class protocols can be introduced only by a subclass.
        for name in PROTOCOLS[:2]:
            if (method := candidate.find_attrs(name)) is not None:
                return name, method, candidate
        return ("__iter__" if candidate.find_attrs("__iter__") is not None else "missing"), None, candidate

    def invoke(selected):
        name, method, candidate = selected
        if name == "missing":
            e.guard_exception(node, "false", "TypeError", f"cannot convert '{candidate.name}' object to bytes")
            return "null"
        if name == "__index__":
            count = indexing.integer(e, candidate, "ptr", value, node)
            return from_count(e, count, node)
        if name == "__bytes__":
            if (not isinstance(method, Function) or method.is_static or method.is_classmethod or method.is_property
                    or collection_ops.builtin_name(method.return_type) != "bytes"):
                raise LLVMUnsupported("LLVM __bytes__ requires an instance method returning bytes", node)
            empty = ast.copy_location(ast.Call(func=node.func, args=[], keywords=[]), node)
            with calls.bind(e, method, empty) as arguments:
                return calls.invoke(e, method, arguments, node, receiver=value)[1]
        return from_items(e, candidate, value, node)

    def unknown():
        # A handle can outlive or arrive through another acquisition path.
        # Never call the sole candidate with an unverified object layout.
        e.guard_exception(node, "false", "TypeError", "unknown application byte conversion source")
        return "null"

    return calls.runtime_protocol(e, semantic, value, "ptr", select, invoke, node,
                                  fallback=unknown if checked else None,
                                  compatible=lambda candidate, target: compatible_source(e, candidate, target))
