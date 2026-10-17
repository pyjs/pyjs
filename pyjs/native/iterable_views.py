"""Reusable Iterable views retain a source, not an eagerly acquired cursor.

The managed descriptor holds source, acquire, truth and canonical identity,
plus an optional byte-conversion callback when a reached consumer needs one.
Typed operations use ordinary emission and the module's checked call ABI.
Each acquisition invokes the original protocol again; failures never publish
or cache a cursor. Typed cursor views convert items only as they are consumed.
"""

import ast

from pyjs.analysis.ir import FunctionIR, Return
from pyjs.analysis.iterable_protocol import is_abstract_iterable as is_view
from pyjs.analysis.objects import (
    Class,
    Function,
    Name,
    same_analyzer_type,
    union_type_key,
)
from pyjs.analysis.representation import apply_representation, compound_representation
from pyjs.analysis.value_representation import (
    analyzed_representation,
    representation_for_member,
)

from .errors import LLVMUnsupported


def cursor_type(value_type):
    from . import collection_ops
    from .analysis import NATIVE_ENVIRONMENT
    return NATIVE_ENVIRONMENT.builtins.search("Iterator")(collection_ops.item_type(value_type))


def check(source, target, node, *, adapt=True):
    from . import collection_ops, iterator_views
    if same_analyzer_type(source, target):
        return
    if not adapt:
        raise LLVMUnsupported("LLVM stored Iterable views require matching layouts", node)
    if collection_ops.builtin_name(source) == "tuple" and not source.generic_types:
        return  # No item will ever be loaded from the empty tuple.
    iterator_views.check(cursor_type(source), cursor_type(target), node)


def reserve(emitter):
    emitter.module.uses_iterable_views = True
    # Acquiring an Iterable can discover a typed cursor view after preparation.
    # Reserve its checked runtime without a second graph walk; matching-item
    # acquisitions still return their original cursor without an allocation.
    emitter.module.uses_iterator_views = True
    emitter.module.uses_iterators = emitter.module.uses_collections = True
    emitter.module.uses_strings = emitter.module.uses_ranges = True


def _operation():
    raise NotImplementedError


class Operation(ast.expr):
    _fields = ()

    def __init__(self, source, result, operation, representation, target_representation):
        self.source, self.obj, self.operation = source, result, operation
        self.source_representation = representation
        self.target_representation = target_representation
        # Protocol emitters use the normal call binder for defaults and errors.
        self.func = Name(result)


def register(e, source, target, node, *, representation=None, target_representation=None):
    from . import bytes_construction, collection_ops
    key = union_type_key(source), union_type_key(target), representation, target_representation
    if key in e.module.iterable_views:
        return e.module.iterable_views[key]
    from .analysis import NATIVE_ENVIRONMENT
    item = collection_ops.item_type(target)
    functions = []
    operations = ["iter", "truth"]
    if bytes_construction.view_required(e, target):
        operations.append("bytes")
    for operation in operations:
        result = NATIVE_ENVIRONMENT.builtins.search({"iter": "Iterator", "truth": "bool", "bytes": "bytes"}[operation])
        if operation == "iter":
            result = result(item)
        function = Function(_operation, e.module.entry_module)
        function.name = f'iterable.{len(e.module.iterable_views)}.{operation}'
        function.source_fragment = e.current_function.source_fragment
        function.return_type = result
        annotation = source.annotation
        annotation.obj = source
        function.params = [ast.arg(arg="source", annotation=annotation)]
        apply_representation(function.params[0], representation)
        function.ir = FunctionIR()
        function.ir.enter(function.ir.new_block("entry"))
        function.ir.terminate(Return(ast.copy_location(
            Operation(source, result, operation, representation, target_representation), node)))
        e.module.function_names[function] = f"pyjs.{function.name}"
        e.module.functions.add(function)
        functions.append(function)
    e.module.iterable_views[key] = tuple(functions)
    return tuple(functions)


def operation(e, node):
    from . import (
        bytes_construction,
        collection_ops,
        iterator_ops,
        iterator_views,
        nullable,
    )
    source = e.load_local("source")
    if node.operation == "truth":
        return "i1", e.truth_value(nullable.typed_node(node, node.source), "ptr", source)
    if node.operation == "bytes":
        return "ptr", bytes_construction.convert(e, node.source, "ptr", source, node)
    value = iterator_ops.create(e, node.source, source, node)
    if collection_ops.builtin_name(node.source) != "tuple" or node.source.generic_types:
        actual = cursor_type(node.source)
        if iterator_views.needed(actual, node.obj):
            from pyjs.analysis.analyzer import iterable_protocol
            item = iterable_protocol(node.source, node.source_representation).item_representation
            represented = compound_representation(arguments=(item,))
            value = iterator_views.wrap(e, actual, node.obj, value, node, representation=represented,
                                        target_representation=node.target_representation)
    return "ptr", value


def invoke(e, value, node, *, operation="iter"):
    from . import calls, iterator_ops
    source = e.emit_value(f"load ptr, ptr {value}")
    slot = iterator_ops.slot(e, value, {"iter": 8, "truth": 16, "bytes": 32}[operation])
    implementation = e.emit_value(f"load ptr, ptr {slot}")
    kind = "i1" if operation == "truth" else "ptr"
    arguments = ", ".join(f"{stored} {operand}" for stored, operand in
                          (*e.context_arguments(), ("ptr", source)))
    roots = calls.root_values(e, value)
    result = e.emit_value(f"call {kind} {implementation}({arguments})")
    e.check_active_exception(node)
    calls.pop_roots(e, roots)
    return result


def wrap(e, source, target, value, node, *, representation=None, target_representation=None):
    from . import calls, iterator_ops
    functions = register(e, source, target, node, representation=representation,
                         target_representation=target_representation)
    roots = calls.root_values(e, value)
    # Application Iterator interfaces may wrap the source in another handle.
    # Keep that handle for acquisition, but cache its underlying identity while
    # its concrete source type is known. Identity reads need no runtime dispatch.
    original = (e.emit_value(f"call ptr @pyjs.iterator.identity(ptr {value})")
                if iterator_ops.is_iterator(source) else identity(e, source, value))
    result = iterator_ops.array(e, [("ptr", value), *(("ptr", "@" + e.function_name(f)) for f in functions[:2]),
                                   ("ptr", original),
                                   ("ptr", "@" + e.function_name(functions[2]) if len(functions) > 2 else "null")])
    calls.pop_roots(e, roots)
    if root := e.expression_roots.get(id(node)):
        e.emit_line(f"store ptr {result}, ptr {root}")
    return result


def convert(e, kind, value, expected, node, *, representation=None):
    from . import collection_ops, nullable
    actual = e.value_semantics.get((kind, value))
    source, target = nullable.member(actual) or actual, nullable.member(expected) or expected
    if not is_view(target):
        return None
    if collection_ops.builtin_name(source) == "NoneType" or kind == "void":
        return None  # Ordinary nullable conversion owns absent values.
    if not isinstance(source, Class) or kind != "ptr":
        raise LLVMUnsupported("LLVM Iterable views require a concrete source; narrow unions first", node)
    check(source, target, node)
    if is_view(source) and same_analyzer_type(source, target):
        return kind, value
    represented = representation_for_member(actual, e.value_representations.get((kind, value)), source)
    target_representation = representation_for_member(expected, representation, target)
    if nullable.member(actual):
        result = nullable.dispatch(e, actual, kind, value, "ptr", "null",
                                  lambda member, stored, payload: wrap(e, member, target, payload, node,
                                      representation=represented, target_representation=target_representation))
    else:
        result = wrap(e, source, target, value, node, representation=represented,
                      target_representation=target_representation)
    e.value_semantics["ptr", result] = expected
    e.value_representations["ptr", result] = representation
    return "ptr", result


def read(e, declared, narrowed, kind, value, node, *, representation=None):
    from . import collection_ops, iterator_ops, nullable
    source, target = nullable.member(declared) or declared, nullable.member(narrowed) or narrowed
    represented = representation_for_member(declared, representation, source)
    if not is_view(source) or same_analyzer_type(source, target) or collection_ops.builtin_name(target) == "NoneType":
        return None
    # Flow proofs can outlive captured-cell reassignment. An exact factory
    # check proves the stored source layout before exposing its original pointer.
    if nullable.member(declared) and nullable.member(narrowed):
        return "ptr", nullable.dispatch(e, declared, kind, value, "ptr", "null",
            lambda member, stored, payload: read(e, member, target, stored, payload, node,
                                                representation=represented)[1])
    if nullable.member(declared):
        nullable.check_narrowing(e, kind, value, target, node, "Iterable view")
    check(target, source, node)
    factory = register(e, target, source, node, representation=analyzed_representation(node),
                       target_representation=represented)[0]
    actual = e.emit_value(f"load ptr, ptr {iterator_ops.slot(e, value, 8)}")
    valid = e.emit_value(f"icmp eq ptr {actual}, @{e.function_name(factory)}")
    e.guard_exception(node, valid, "TypeError", "Iterable view has a different source layout")
    return "ptr", e.emit_value(f"load ptr, ptr {value}")


def identity(e, semantic, value):
    from . import iterator_ops

    if is_view(semantic):
        return e.emit_value(f"load ptr, ptr {iterator_ops.slot(e, value, 24)}")
    return value
