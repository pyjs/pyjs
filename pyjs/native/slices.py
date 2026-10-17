"""First-class slice values and shared optional-bound normalization.

Bounds keep None/bool/int tags until use, so repr and field access do not turn
True into 1. The three immutable scalar values need no GC pointer scanning.
"""

import ast

from pyjs.analysis.analyzer import analyzed_value_type, dynamic_slice_index
from pyjs.analysis.ir import FunctionIR, Return
from pyjs.analysis.iterable_protocol import resolve_iterable_protocol
from pyjs.analysis.objects import Class, Function, UnionType
from pyjs.analysis.type_relations import get_type_members, is_return_type_compatible
from pyjs.analysis.value_representation import (
    analyzed_representation,
    representation_for_member,
    representations_conflict,
)

from . import (
    calls,
    collection_ops,
    comparisons,
    indexing,
    nullable,
    object_values,
    tagged,
)
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported

STORAGE = f"[3 x {tagged.STORAGE}]"
FIELDS = ("start", "stop", "step")


def bound_type():
    return UnionType(types=[NATIVE_ENVIRONMENT.builtins.search(name)
                            for name in ("int", "bool", "NoneType")]).type


def field(e, value, index):
    slot = e.emit_value(f"getelementptr {tagged.STORAGE}, ptr {value}, i64 {index}")
    return e.emit_value(f"load {tagged.STORAGE}, ptr {slot}")


def check_bound_type(source):
    # A first-class slice retains its field objects. Consuming syntax instead
    # invokes the index protocol below, without changing stored field identity.
    for member in get_type_members(analyzed_value_type(source)):
        name = collection_ops.builtin_name(tagged.runtime_type(member))
        if name not in {"int", "bool", "NoneType"}:
            raise LLVMUnsupported("LLVM slice bounds support only integers, booleans and None", source)


def retain(node):
    """Syntax lowers to calls without necessarily visiting visit_Call."""
    target = getattr(getattr(node, "func", None), "obj", None)
    owner = getattr(target, "cls", None)
    if (isinstance(node, ast.Call) and getattr(target, "name", None)
            in {"__slice__", "__setslice__", "__delslice__"}
            and isinstance(owner, Class) and owner.container.scope.is_builtins):
        arguments = node.args[1:] if target.name == "__setslice__" else node.args
        node.runtime_protocols = (*getattr(node, "runtime_protocols", ()),
            *((analyzed_value_type(value), ("__index__",)) for value in arguments))
    if (isinstance(node, ast.Call) and getattr(target, "name", None) == "__setitem__"
            and isinstance(owner, Class) and owner.container.scope.is_builtins
            and owner.generic_name == "list" and dynamic_slice_index(node.args[0])):
        node.runtime_protocols = (*getattr(node, "runtime_protocols", ()),
            (analyzed_value_type(node.args[1]), ("__iter__", "__getitem__")))
    return node


def syntax_arguments(e, operation, arguments, node):
    """Convert once, step first, after all source expressions have run.

    Kernels may inspect length/storage only after these callbacks: __index__
    can mutate the receiver, allocate, collect or raise. Normalized optional
    pairs reuse the existing scalar kernels and retain absent-bound semantics.
    """
    offset = int(operation == "__setslice__")
    result = list(arguments)
    for index in (offset + 2, offset, offset + 1):
        if index >= len(arguments):
            continue
        kind, value = arguments[index]
        if kind == "void":
            continue
        semantic = analyzed_value_type(node.args[index])
        present = nullable.present(e, kind, value)
        default = 1 if index == offset + 2 else 0
        converted = indexing.optional(e, semantic, kind, value, default, node,
            error="slice indices must be integers or None or have an __index__ method")
        if index == offset + 2:
            e.guard_exception(node, e.emit_value(f"icmp ne i64 {converted}, 0"),
                              "ValueError", "slice step cannot be zero")
        if present == "true":
            result[index] = "i64", converted
            continue
        storage = nullable.pair("i64")
        pair = e.emit_value(f"insertvalue {storage} zeroinitializer, i1 {present}, 0")
        result[index] = storage, e.emit_value(f"insertvalue {storage} {pair}, i64 {converted}, 1")
    return result


def construct(e, node):
    if node.keywords or not 1 <= len(node.args) <= 3:
        raise LLVMUnsupported("LLVM slice() takes one to three positional integer/None bounds", node)
    for source in node.args:
        check_bound_type(source)
    values = [e.coerce_value(*e.expression(source), tagged.STORAGE, source, semantic=bound_type())[1]
              for source in node.args]
    missing = "zeroinitializer"  # None has tag zero and no payload.
    if len(values) == 1:
        values = [missing, values[0], missing]
    elif len(values) == 2:
        values.append(missing)
    size = e.llvm_size(STORAGE)
    if e.module.uses_gc:
        value = e.allocated_value(f"call ptr @pyjs.gc.try.alloc.described(ptr {e.load_local('__heap')}, "
                                  f"i64 {size}, ptr @pyjs.gc.descriptor.atomic)")
    else:
        value = e.allocated_value(f"call ptr @pyjs.arena.try.alloc(ptr {e.load_local('__arena')}, i64 {size}, i64 8)")
    for index, bound in enumerate(values):
        slot = e.emit_value(f"getelementptr {tagged.STORAGE}, ptr {value}, i64 {index}")
        e.emit_line(f"store {tagged.STORAGE} {bound}, ptr {slot}")
    return "ptr", value


def bounds(e, value):
    result = []
    for index in range(3):
        tag, payload = tagged.parts(e, field(e, value, index))
        result.append((payload, e.emit_value(f"icmp ne i64 {tag}, 0")))
    return result


def bound(e, argument, node, default=0):
    """Normalize a checked scalar bound; construction and syntax validate types."""
    kind, value = argument
    if kind == "void" or kind == "ptr" and value == "null":
        return str(default), "false"
    if kind == tagged.STORAGE:
        tag, payload = tagged.parts(e, value)
        present = e.emit_value(f"icmp ne i64 {tag}, 0")
    elif kind in {nullable.pair("i64"), nullable.pair("i1")}:
        present = e.emit_value(f"extractvalue {kind} {value}, 0")
        payload = e.emit_value(f"extractvalue {kind} {value}, 1")
        if kind == nullable.pair("i1"):
            payload = e.emit_value(f"zext i1 {payload} to i64")
    elif kind in {"i64", "i1"}:
        return (e.emit_value(f"zext i1 {value} to i64") if kind == "i1" else value), "true"
    else:
        raise LLVMUnsupported("LLVM slice bounds require integers or None", node)
    return e.emit_value(f"select i1 {present}, i64 {payload}, i64 {default}"), present


def subscript(e, operation, semantic, receiver, arguments, node):
    selected = [(tagged.STORAGE, field(e, arguments[0][1], index)) for index in range(3)]
    operation = {"__getitem__": "__slice__", "__setitem__": "__setslice__", "__delitem__": "__delslice__"}[operation]
    if operation == "__setslice__":
        selected.insert(0, arguments[1])
    name = collection_ops.builtin_name(semantic)
    if name in {"str", "bytes"}:
        return e.string_edit_call(operation, receiver, selected, node, binary=name == "bytes")
    if name == "range":
        return e.range_call(operation, receiver, selected, node)
    if name == "tuple":
        return collection_ops.method(e, operation, semantic, receiver, selected, node)
    if name == "list":
        return e.sequence_call(operation, semantic, receiver, selected, node)
    raise LLVMUnsupported("LLVM first-class slice indexing requires a builtin sequence", node)


def _dynamic_assignment():
    raise NotImplementedError


class Assignment(ast.expr):
    """Delayed object decoding, after authored bodies register boxing layouts."""
    _fields = ()

    def __init__(self, semantic, node):
        ast.copy_location(self, node)
        self.semantic, self.node = semantic, node
        self.obj = NATIVE_ENVIRONMENT.builtins.search("NoneType")


def assignment(e, node):
    index_type = analyzed_value_type(node.node.args[0])
    return dynamic_subscript(e, node.semantic, e.load_local("receiver"),
        [(e.value_type(index_type), e.load_local("index")), ("ptr", e.load_local("replacement"))],
        node.node, defer=False)


def defer_assignment(e, semantic, receiver, arguments, node):
    key = semantic, analyzed_representation(node.func.value), analyzed_value_type(node.args[0])
    if key not in e.module.erased_subscripts:
        function = Function(_dynamic_assignment, e.module.entry_module)
        function.name = f"subscript.assignment.{len(e.module.erased_subscripts)}"
        function.source_fragment = e.current_function.source_fragment
        function.return_type = NATIVE_ENVIRONMENT.builtins.search("NoneType")
        function.params = [ast.arg(arg=name, annotation=kind.annotation) for name, kind in (
            ("receiver", semantic), ("index", key[2]),
            ("replacement", NATIVE_ENVIRONMENT.builtins.search("object")))]
        function.ir = FunctionIR()
        function.ir.enter(function.ir.new_block("entry"))
        function.ir.terminate(Return(Assignment(semantic, node)))
        e.module.function_names[function] = "pyjs." + function.name
        e.module.functions.add(function)
        e.module.erased_subscripts[key] = function
    function = e.module.erased_subscripts[key]
    # The operands already have their typed ABI. Ordinary function emission
    # supplies parameter roots, exception cleanup and source frames to helpers.
    return calls.checked(e, function.return_type, None, "@" + e.function_name(function),
                         [*e.context_arguments(), ("ptr", receiver), *arguments], node)


def definitions(parent):
    if not parent.module.erased_subscripts:
        return []
    from .llvm import FunctionEmitter

    # Replacement iteration can box nested items for a list[object]. Discover
    # those layouts before outlining any decoder, not in authored-call order.
    pending = [*parent.module.erased_candidates, *((cls, None) for cls in parent.module.classes)]
    seen = set()
    while pending:
        semantic, represented = pending.pop()
        if (semantic, represented) in seen or nullable.is_object(semantic):
            continue
        seen.add((semantic, represented))
        if isinstance(semantic, UnionType):
            pending.extend((member, representation_for_member(semantic, represented, member))
                           for member in get_type_members(semantic))
            continue
        if represented is not None and represented.direct_numeric_formats:
            continue
        parent.module.erased_candidates[semantic, represented] = None
        protocol = resolve_iterable_protocol(semantic, represented, NATIVE_ENVIRONMENT.builtins)
        if protocol is not None:
            pending.append((protocol.item_type, protocol.item_representation))
    return [line for function in parent.module.erased_subscripts.values()
            for line in FunctionEmitter(parent.module).function(function)]


def dynamic_subscript(e, semantic, receiver, arguments, node, *, defer=True):
    """Select item or slice before invoking the existing typed builtin path.

    Operands have already run in source order. Synthetic values reuse those
    operands, so dispatch neither reevaluates them nor repeats __index__.
    """
    operation = node.func.obj.name
    if operation not in {"__getitem__", "__setitem__", "__delitem__"} or not dynamic_slice_index(node.args[0]):
        return None
    if defer and operation == "__setitem__" and nullable.is_object(analyzed_value_type(node.args[1])):
        return defer_assignment(e, semantic, receiver, arguments, node)
    source = analyzed_value_type(node.args[0])
    kind, value = arguments[0]
    slice_type = NATIVE_ENVIRONMENT.builtins.search("slice")
    if nullable.is_object(source):
        sliced = object_values.instancecheck(e, value, slice_type, node)
    elif kind == tagged.STORAGE:
        tag, bits = tagged.parts(e, value)
        sliced = e.emit_value(f"icmp eq i64 {tag}, {tagged.tag(e, slice_type)}")
    elif nullable.member(source) is slice_type:
        sliced = nullable.present(e, kind, value)
    else:
        raise LLVMUnsupported("LLVM dynamic slice index requires a preserved runtime kind", node)

    empty_tuple = collection_ops.builtin_name(semantic) == "tuple" and not semantic.generic_types
    item_type = NATIVE_ENVIRONMENT.builtins.search("object") if empty_tuple else collection_ops.item_type(semantic, node)
    slice_result = semantic
    if collection_ops.builtin_name(semantic) == "tuple" and not empty_tuple:
        slice_result = NATIVE_ENVIRONMENT.builtins.search("tuple")(item_type, tuple_variadic=True)
    result_type = analyzed_value_type(node)
    result_kind = e.value_type(result_type)
    result = e.emit_value(f"alloca {result_kind}") if result_kind != "void" else None
    yes, no, done = (e.new_label("subscript." + part) for part in ("slice", "item", "done"))
    e.emit_line(f"br i1 {sliced}, label %{yes}, label %{no}")

    def invoke(index_type, index_kind, index_value, returned, replacement=None):
        function = ast.Attribute(value=tagged.Value(node.func.value, semantic, "ptr", receiver),
                                 attr=node.func.attr, ctx=ast.Load())
        function.value.representation = analyzed_representation(node.func.value)
        function.obj = node.func.obj
        selected = ast.copy_location(ast.Call(func=function, args=[], keywords=[]), node)
        selected.obj = returned
        selected.representation = representation_for_member(result_type, analyzed_representation(node), returned)
        selected.args = [tagged.Value(node.args[0], index_type, index_kind, index_value)]
        if replacement is not None:
            actual, represented, storage, payload = replacement
            argument = tagged.Value(node.args[1], actual, storage, payload)
            argument.representation = represented
            selected.args.append(argument)
        output_kind, output = e.call(selected)
        e.value_semantics[output_kind, output] = returned
        e.value_representations[output_kind, output] = selected.representation
        if result is not None:
            converted = e.coerce_value(output_kind, output, result_kind, selected, semantic=result_type)[1]
            e.emit_line(f"store {result_kind} {converted}, ptr {result}")

    def run(index_type, index_kind, index_value, returned, *, sliced):
        if empty_tuple and not sliced:
            e.guard_exception(node, "false", "IndexError", "tuple index out of range")
        elif operation != "__setitem__":
            invoke(index_type, index_kind, index_value, returned)
        else:
            replacement_type = analyzed_value_type(node.args[1])
            replacement_representation = analyzed_representation(node.args[1])
            replacement_kind, replacement_value = arguments[1]
            destination = analyzed_representation(node.func.value)
            expected_item_representation = destination.arguments[0] if destination and destination.arguments else None

            def assign(actual, represented, storage, payload):
                empty = collection_ops.builtin_name(actual) == "tuple" and not actual.generic_types
                if sliced:
                    protocol = resolve_iterable_protocol(actual, represented, NATIVE_ENVIRONMENT.builtins)
                    if protocol is None:
                        if any(isinstance(actual.find_attrs(name), Function) for name in ("__iter__", "__getitem__")):
                            raise LLVMUnsupported("LLVM slice replacement requires a supported iterable protocol", node)
                        e.guard_exception(node, "false", "TypeError", "must assign iterable to extended slice")
                        return
                    replacement_item = protocol.item_type
                    item_representation = protocol.item_representation
                    compatible = is_return_type_compatible(item_type, replacement_item)
                else:
                    replacement_item, item_representation = actual, represented
                    compatible = is_return_type_compatible(item_type, actual)
                conflicts = representations_conflict(((replacement_item, item_representation),
                                                      (item_type, expected_item_representation)))
                scalar_erasure = (nullable.is_object(item_type) and item_representation is not None
                                  and item_representation.direct_numeric_formats)
                if expected_item_representation is not None and expected_item_representation.direct is not None:
                    conflicts |= item_representation != expected_item_representation
                bool_widening = (collection_ops.builtin_name(replacement_item) == "bool"
                                 and collection_ops.builtin_name(item_type) == "int")
                if not (sliced and empty) and (not compatible or conflicts or scalar_erasure or bool_widening):
                    e.guard_exception(node, "false", "TypeError", "list assignment has incompatible item representation")
                    return
                invoke(index_type, index_kind, index_value, result_type,
                       (actual, represented, storage, payload))

            def typed(actual, storage, payload):
                assign(actual, representation_for_member(replacement_type, replacement_representation, actual),
                       storage, payload)

            if nullable.is_object(replacement_type):
                object_values.dispatch(e, replacement_value, "void", node, assign,
                                       description="slice replacement")
            elif replacement_kind == tagged.STORAGE:
                tagged.dispatch(e, replacement_type, replacement_value, "void", typed)
            elif member := nullable.member(replacement_type):
                # Mutation must visit both arms: None is a scalar value, not
                # an absent result to skip, and is not an iterable for slices.
                present, absent, joined = (e.new_label("replacement." + name)
                                           for name in ("present", "absent", "done"))
                available = nullable.present(e, replacement_kind, replacement_value)
                e.emit_line(f"br i1 {available}, label %{present}, label %{absent}")
                e.emit_line(f"{present}:")
                payload = replacement_value if replacement_kind == "ptr" else e.emit_value(
                    f"extractvalue {replacement_kind} {replacement_value}, 1")
                typed(member, e.value_type(member), payload)
                e.emit_line(f"br label %{joined}")
                e.emit_line(f"{absent}:")
                typed(NATIVE_ENVIRONMENT.builtins.search("NoneType"), "void", "")
                e.emit_line(f"br label %{joined}")
                e.emit_line(f"{joined}:")
            else:
                typed(replacement_type, replacement_kind, replacement_value)
        e.emit_line(f"br label %{done}")

    e.emit_line(f"{yes}:")
    if nullable.is_object(source):
        pointer = object_values.known_payload(e, value, slice_type)
    elif kind == tagged.STORAGE:
        pointer = e.emit_value(f"inttoptr i64 {bits} to ptr")
    else:
        pointer = value
    if operation == "__setitem__":
        # Python validates the slice step before trying to iterate its RHS,
        # including a non-iterable RHS. Keep that precedence during dispatch.
        step = bound(e, (tagged.STORAGE, field(e, pointer, 2)), node, 1)[0]
        e.guard_exception(node, e.emit_value(f"icmp ne i64 {step}, 0"),
                          "ValueError", "slice step cannot be zero")
    run(slice_type, "ptr", pointer, slice_result if result is not None else result_type, sliced=True)
    e.emit_line(f"{no}:")
    integer = indexing.integer(e, source, kind, value, node)
    run(NATIVE_ENVIRONMENT.builtins.search("int"), "i64", integer,
        item_type if result is not None else result_type, sliced=False)
    e.emit_line(f"{done}:")
    return (result_kind, e.emit_value(f"load {result_kind}, ptr {result}")) if result is not None else ("void", "")


def equal(e, left, right, node):
    result = "true"
    for index in range(3):
        same = comparisons.compare_value(e, bound_type(), field(e, left, index),
                                         bound_type(), field(e, right, index), node, operation="__eq__")
        result = e.emit_value(f"and i1 {result}, {same}")
    return result


def method(e, operation, receiver, arguments, node):
    if operation in {"__eq__", "__ne__"}:
        matching = collection_ops.builtin_name(analyzed_value_type(node.args[0])) == "slice"
        if not matching and getattr(node, "operator", None) is None:
            raise LLVMUnsupported("LLVM explicit slice comparison may return NotImplemented; use comparison syntax", node)
        same = equal(e, receiver, arguments[0][1], node) if matching else "false"
        return "i1", e.emit_value(f"xor i1 {same}, true") if operation == "__ne__" else same
    if operation != "indices" or len(arguments) != 1 or node.keywords:
        raise LLVMUnsupported(f"LLVM slice.{operation} is not supported", node)
    length = e.index_integer(*arguments[0], node, "LLVM slice.indices length requires an integer")
    e.guard_exception(node, e.emit_value(f"icmp sge i64 {length}, 0"), "ValueError", "length should not be negative")
    selected = bounds(e, receiver)
    step, present = selected[2]
    valid = e.emit_value(f"icmp ne i64 {step}, 0")
    absent = e.emit_value(f"xor i1 {present}, true")
    e.guard_exception(node, e.emit_value(f"or i1 {valid}, {absent}"), "ValueError", "slice step cannot be zero")
    wide = e.emit_value(f"zext i64 {length} to i128")
    output = e.emit_value("alloca [3 x i128]")
    parameters = ", ".join(f"i64 {value}, i1 {exists}" for value, exists in selected)
    e.emit_line(f"call void @pyjs.slice.indices(i128 {wide}, {parameters}, ptr {output})")
    values = []
    for index in range(3):
        slot = e.emit_value(f"getelementptr i128, ptr {output}, i64 {index}")
        value = e.emit_value(f"load i128, ptr {slot}")
        values.append(("i64", e.emit_value(f"trunc i128 {value} to i64")))
    return "ptr", collection_ops.new_tuple(e, analyzed_value_type(node), values)
