"""Frozen typed captures and ordinary callable forwarding for functools.partial.

The descriptor retains its source descriptor, rather than copying a receiver or
flattening nested partials. Captures use the source parameter ABI; wrappers only
interleave those values with supplied parameters and invoke the existing binder.
"""

import ast
from dataclasses import dataclass

from pyjs.analysis.analyzer import analyzed_value_object, callable_value_type
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.ir import FunctionIR, Return
from pyjs.analysis.objects import Call, CallableClass, Function, Name, union_type_key

from . import callables, calls, gc_layouts
from .functional import Placeholder


def is_placeholder(value):
    target = analyzed_value_object(value)
    return (getattr(target, "py_obj", None) is Placeholder
            or getattr(getattr(target, "cls", None), "py_obj", None) is Placeholder)


def analyze(call):
    visitor, node = call.visitor, call.node

    def fail(source, message):
        visitor.fail(source, DiagnosticCode.INCOMPATIBLE_ARGUMENT, "functools.partial() " + message)

    if not node.args:
        fail(node, "requires a typed callable")
    if any(isinstance(arg, ast.Starred) for arg in node.args) or any(k.arg is None for k in node.keywords):
        fail(node, "requires explicit argument bindings")
    function = visitor.visit(node.args[0])
    target = analyzed_value_object(function)
    if isinstance(target, Function):
        visitor.ensure_call_signature_ready(node, target)
    signature = callable_value_type(function)
    if not isinstance(signature, CallableClass) or signature.parameter_types is None:
        fail(node.args[0], "requires a concrete callable signature")
    supplied = len(node.args) - 1
    if supplied > len(signature.parameter_types):
        fail(node, "binds more arguments than the callable accepts")
    representations = signature.parameter_representations or (None,) * len(signature.parameter_types)
    holes, captures, indices = [], [], []

    def capture(source, index, value=None, *, keyword=False):
        expected = signature.parameter_types[index]
        if value is None:
            value = visitor.visit_contextual_expression(source, expected,
                                                        expected_representation=representations[index])
        if is_placeholder(value):
            if keyword:
                fail(source, "Placeholder cannot be passed as a keyword argument")
            fail(source, "requires a directly named Placeholder hole; function-local Placeholder aliases are unsupported")
        visitor.validate_call_argument(source, call.function, str(index), expected, value)
        value = visitor.normalize_stored_value(source, value, representations[index], expected)
        captures.append(value)
        indices.append(index)

    for index, source in enumerate(node.args[1:]):
        value = visitor.visit_contextual_expression(source, signature.parameter_types[index],
                                                   expected_representation=representations[index])
        if getattr(analyzed_value_object(value), "py_obj", None) is Placeholder:
            holes.append(index)
        else:
            capture(source, index, value)
    if holes and holes[-1] == supplied - 1:
        fail(node.args[-1], "does not allow a trailing Placeholder")

    names, positional_only = None, frozenset()
    if isinstance(target, Function):
        methods = getattr(function, "union_functions", ()) or (target,)
        # A union's positional view may be shorter than any one declaration,
        # and positional compatibility does not imply equal keyword names.
        names = tuple(parameter.arg if all(method.params[index].arg == parameter.arg for method in methods)
                      else None for index, parameter in enumerate(target.params[:len(signature.parameter_types)]))
        positional_only = frozenset(index for index in range(len(names))
                                    if any(index < method.posonly_count for method in methods))
    elif isinstance(function, ast.Lambda):
        names = tuple(parameter.arg for parameter in (*function.args.posonlyargs, *function.args.args))
        positional_only = frozenset(range(len(function.args.posonlyargs)))
    elif isinstance(function, ast.Call):
        names = getattr(function, "partial_parameter_names", None)
        positional_only = getattr(function, "partial_positional_only", frozenset())
    keyword_indices = []
    for keyword in node.keywords:
        if names is None:
            fail(keyword.value, "keyword binding requires a callable with known parameter names")
        if keyword.arg not in names:
            fail(keyword.value, f"callable has no positional parameter {keyword.arg!r}")
        index = names.index(keyword.arg)
        if index in positional_only:
            fail(keyword.value, f"cannot bind positional-only parameter {keyword.arg!r} by keyword")
        if index < supplied:
            fail(keyword.value, f"parameter {keyword.arg!r} is already bound positionally")
        keyword_indices.append(index)
        capture(keyword.value, index, keyword=True)
    if keyword_indices and sorted(keyword_indices) != list(range(min(keyword_indices), len(names))):
        fail(node, "native keyword bindings must cover a trailing parameter suffix")
    remaining = (*holes, *(index for index in range(supplied, len(signature.parameter_types))
                           if index not in keyword_indices))
    result_type = CallableClass(tuple(signature.parameter_types[index] for index in remaining),
        signature.return_type, signature.super,
        tuple(representations[index] for index in remaining), signature.return_representation,
        minimum_arguments=(len(remaining) if keyword_indices else
                           len(holes) + max(0, signature.minimum_arguments - supplied)),
        required_keywords=signature.required_keywords)
    # Keep every evaluated capture as an AST child for reachability, expression
    # roots and the declaration's RETURNED lifetime contract. Holes have no value.
    result = ast.copy_location(Call(result_type,
        value_obj=result_type("__call_result__", visitor.scope, visitor.func),
        func=Name(call.function), args=[function, *captures], keywords=[]), node)
    result.partial_source = signature
    result.partial_indices = tuple(indices)
    result.partial_remaining = remaining
    result.partial_parameter_names = tuple(names[index] for index in remaining) if names else None
    result.partial_positional_only = frozenset(index for index, original in enumerate(remaining)
                                              if original in positional_only)
    return result


@dataclass
class Partial:
    node: Call
    owner: Function
    name: str
    storage: tuple[str, ...]

    @property
    def layout(self):
        return "{ ptr, ptr, ptr" + "".join(", " + kind for kind in self.storage) + " }"


def prepare(emitter, functions):
    for owner in functions:
        for block in owner.ir.blocks:
            for statement in getattr(block, "body", ()):
                for node in ast.walk(statement):
                    if not isinstance(node, Call) or not hasattr(node, "partial_source") or node in emitter.module.partials:
                        continue
                    _, storage = callables.signature(emitter, node.partial_source, node)
                    callables.signature(emitter, node.obj, node)
                    emitter.module.partials[node] = Partial(node, owner,
                        f"pyjs.partial.{len(emitter.module.partials)}",
                        tuple(storage[index] for index in node.partial_indices))
    emitter.module.uses_collections |= bool(emitter.module.partials)


def create(e, node):
    partial = e.module.partials[node]
    values = [e.expression(source) for source in node.args]
    # Raw AST values have ordinary expression roots. Conversions may allocate
    # too, so independently root each converted lane before the next conversion.
    slots, roots = calls.value_slots(e, ["ptr", *partial.storage])
    e.emit_line(f"store ptr {values[0][1]}, ptr {slots[0]}")
    for (kind, value), source, index, stored, slot in zip(values[1:], node.args[1:],
            node.partial_indices, partial.storage, slots[1:], strict=True):
        expected = node.partial_source.parameter_types[index]
        representations = node.partial_source.parameter_representations
        kind, value = e.coerce_value(kind, value, e.value_type(expected), source, semantic=expected,
                                    representation=representations[index] if representations else None)
        kind, value = e.narrow_numeric(kind, value, stored, source)
        e.emit_line(f"store {kind} {value}, ptr {slot}")
    result = gc_layouts.allocate(e, ("ptr", "ptr", "ptr", *partial.storage))
    signature = node.obj
    symbol = partial.name + (".arities" if signature.minimum_arguments != len(signature.parameter_types)
                             else f".{len(signature.parameter_types)}")
    e.emit_line(f"store ptr @{symbol}, ptr {result}")
    context = e.emit_value(f"getelementptr {partial.layout}, ptr {result}, i32 0, i32 1")
    e.emit_line(f"store ptr {result}, ptr {context}")
    for index, (kind, slot) in enumerate(zip(["ptr", *partial.storage], slots, strict=True), 2):
        value = e.emit_value(f"load {kind}, ptr {slot}")
        destination = e.emit_value(f"getelementptr {partial.layout}, ptr {result}, i32 0, i32 {index}")
        e.emit_line(f"store {kind} {value}, ptr {destination}")
    calls.pop_roots(e, roots)
    return "ptr", result


def _partial():
    raise NotImplementedError


class Invoke(ast.expr):
    _fields = ()

    def __init__(self, partial, count):
        self.partial, self.count = partial, count
        self.obj = partial.node.obj.return_type
        self.representation = partial.node.obj.return_representation
        ast.copy_location(self, partial.node)


def invoke(e, node):
    partial, count = node.partial, node.count
    source = partial.node.partial_source
    context = e.load_local("__context")
    values = {}
    representations = source.parameter_representations or (None,) * len(source.parameter_types)
    for field, (index, kind) in enumerate(zip(partial.node.partial_indices, partial.storage, strict=True), 3):
        slot = e.emit_value(f"getelementptr {partial.layout}, ptr {context}, i32 0, i32 {field}")
        value = e.emit_value(f"load {kind}, ptr {slot}")
        values[index] = e.widen_numeric(kind, value, callables.numeric(representations[index]))
    for index, original in enumerate(partial.node.partial_remaining[:count]):
        values[original] = e.load(f"a{index}")
    arguments = []
    for index in range(len(values)):
        kind, value = values[index]
        e.value_semantics[kind, value] = source.parameter_types[index]
        e.value_representations[kind, value] = representations[index]
        arguments.append((kind, value))
    slot = e.emit_value(f"getelementptr {partial.layout}, ptr {context}, i32 0, i32 2")
    callback = e.emit_value(f"load ptr, ptr {slot}")
    return callables.invoke_values(e, callback, source,
        calls.BoundCall(arguments, [None] * len(arguments)), node)


def prepare_definitions(parent):
    # Iterator/callable adapters can discover an omitted arity after ordinary
    # bodies. Join their worklist before publishing this partial's dispatch table.
    for partial in parent.module.partials.values():
        signature = partial.node.obj
        for count in range(signature.minimum_arguments, len(signature.parameter_types) + 1):
            key = partial.name, count
            if key in parent.module.partial_callbacks or (
                    signature.minimum_arguments != len(signature.parameter_types)
                    and (union_type_key(signature), count) not in parent.module.callable_arities):
                continue
            function = Function(_partial, parent.module.entry_module)
            function.name = f"{partial.name}.{count}"
            function.source_fragment = partial.owner.source_fragment
            function.return_type = signature.return_type
            function.set_return_representation(signature.return_representation)
            # The context is an opaque managed descriptor, represented using
            # the existing callable pointer type so it receives ordinary roots.
            types = [signature, *signature.parameter_types[:count]]
            representations = [None, *(signature.parameter_representations or
                                      (None,) * len(signature.parameter_types))[:count]]
            for index, (value, representation) in enumerate(zip(types, representations, strict=True)):
                annotation = value.annotation
                annotation.obj = value
                parameter = ast.arg(arg="__context" if index == 0 else f"a{index - 1}", annotation=annotation)
                parameter.representation = representation
                function.params.append(parameter)
            function.ir = FunctionIR()
            function.ir.enter(function.ir.new_block("entry"))
            function.ir.terminate(Return(Invoke(partial, count)))
            parent.module.function_names[function] = function.name
            parent.module.functions.add(function)
            parent.module.partial_callbacks[key] = function


def definitions(parent):
    result = []
    for partial in parent.module.partials.values():
        signature = partial.node.obj
        if signature.minimum_arguments == len(signature.parameter_types):
            continue
        entries = [f"ptr @{partial.name}.{count}" if (partial.name, count) in parent.module.partial_callbacks else "ptr null"
                   for count in range(len(signature.parameter_types) + 1)]
        result.append(f"@{partial.name}.arities = private constant [{len(entries)} x ptr] [{', '.join(entries)}]")
    return result
