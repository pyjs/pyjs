"""Typed function values using the ordinary native call and memory ABI."""

import ast
from copy import copy

from pyjs.analysis.analyzer import analyzed_value_type, callable_value_type
from pyjs.analysis.ir import FunctionIR, Return
from pyjs.analysis.objects import (
    Class,
    Function,
    Module,
    ModuleAlias,
    same_analyzer_type,
    union_type_key,
)
from pyjs.analysis.objects import Name as AnalyzedName
from pyjs.analysis.type_relations import get_type_members
from pyjs.analysis.value_representation import analyzed_value_object

from . import calls, collection_ops, gc_layouts, tagged
from .errors import LLVMUnsupported


def numeric(representation):
    return representation.numeric if representation is not None else None


def signature(emitter, value_type, node=None):
    if value_type.parameter_types is None:
        raise LLVMUnsupported("LLVM callable values require explicit parameter types", node)
    representations = value_type.parameter_representations or (None,) * len(value_type.parameter_types)
    parameters = [emitter.storage_type(value, numeric(representation))
                  for value, representation in zip(value_type.parameter_types, representations, strict=True)]
    return emitter.result_storage_type(value_type.return_type, numeric(value_type.return_representation)), parameters


def prepare(emitter, functions):
    for function in functions:
        try:
            prepare_function(emitter, function)
        except LLVMUnsupported as error:
            error.add_function_context(function)
            raise


def prepare_function(emitter, function):
    for block in function.ir.blocks:
        for statement in getattr(block, "body", ()):
            direct = {id(node.func) for node in ast.walk(statement) if isinstance(node, ast.Call)}
            for node in ast.walk(statement):
                target = getattr(node, "obj", None)
                if (id(node) in direct or not isinstance(node, (ast.Name, ast.Attribute))
                        or not isinstance(target, Function)):
                    continue
                if isinstance(node, ast.Attribute) and node.attr == "__hash__" and target.cls in emitter.module.classes:
                    from .hashing import check_method_reference
                    check_method_reference(emitter, node)
                if (any(method.is_staticmethod for method in getattr(node, "union_functions", ()))
                        and not uniform_static_union(emitter, node)):
                    raise LLVMUnsupported(
                        "LLVM union static-method values require one shared runtime implementation", node)
                bound = target.cls is not None and not target.is_static
                if bound and not isinstance(node, ast.Attribute):
                    raise LLVMUnsupported("LLVM method values require a bound receiver", node)
                if bound and isinstance(node.value, (ast.Name, ast.Attribute)) and isinstance(analyzed_value_object(node.value), Class):
                    raise LLVMUnsupported("LLVM method values require a bound receiver", node)
                if bound and (members := tagged.members(analyzed_value_type(node.value))):
                    for member in members:
                        if member not in emitter.module.classes:
                            raise LLVMUnsupported("LLVM union method values require application receivers on every member", node)
                        for implementation in calls.protocol_groups(emitter, member,
                                lambda candidate, attr=node.attr: candidate.find_attrs(attr),
                                compatible=collection_ops.is_layout_subclass):
                            register(emitter, node, implementation)
                    continue
                register(emitter, node, target)
                if dynamic_receiver(emitter, node) is not None:
                    for implementation in calls.protocol_groups(emitter, analyzed_value_type(node.value),
                            lambda candidate, attr=node.attr: candidate.find_attrs(attr),
                            compatible=collection_ops.is_layout_subclass):
                        register(emitter, node, implementation)
                if receiver := calls.static_receiver(node, emitter.module.functions):
                    for implementation in calls.protocol_groups(emitter, receiver,
                            lambda candidate, attr=node.attr: candidate.find_attrs(attr),
                            compatible=collection_ops.is_layout_subclass):
                        register(emitter, node, implementation)


def uniform_static_union(emitter, node):
    # An unbound constant descriptor needs no union payload decode. Checking
    # only union_functions is insufficient: a reached subclass may override an
    # inherited declaration shared by all the statically named union members.
    if not node.obj.is_staticmethod:
        return False
    for member in get_type_members(analyzed_value_type(node.value)):
        # Application descendants cannot prove a builtin/unmodeled member's
        # own behavior. Every arm needs a modeled declaration and family.
        if member not in emitter.module.classes:
            return False
        implementations = calls.protocol_groups(emitter, member,
            lambda candidate: candidate.find_attrs(node.attr),
            compatible=collection_ops.is_layout_subclass)
        # Require a nonempty proof per arm; flattening groups drops empty arms.
        if set(implementations) != {node.obj}:
            return False
    return True


def register(emitter, node, target):
    if (not isinstance(target, Function) or target not in emitter.module.functions or target.is_async
            or target.vararg is not None or target.kwarg is not None
            or any(value is None for value in target.kw_defaults) and target is node.obj
            or target.is_classmethod):
        raise LLVMUnsupported(
            "LLVM function values require an application function with fixed positional parameters", node)
    # A union may expose only the arities shared by its members. Validate the
    # selected declaration against that view; extraction installs an adapter
    # rather than reinterpreting an optional table as a fixed code pointer.
    actual, expected = callable_value_type(AnalyzedName(target)), callable_value_type(node)
    if not same_analyzer_type(actual, expected):
        from .callable_adapters import check_view
        checked = actual
        if target is not node.obj:
            # A selected override may remove optional arguments. Its descriptor
            # still has its actual ABI; adapters reject unsupported call counts
            # at invocation, rather than rejecting method capture itself.
            checked = copy(actual)
            checked.minimum_arguments = min(actual.minimum_arguments, expected.minimum_arguments)
            checked.required_keywords = expected.required_keywords
        check_view(checked, expected, node)
    signature(emitter, callable_value_type(node), node)
    bound = target.cls is not None and not target.is_static
    emitter.module.callables[target] = bound
    if bound:
        emitter.module.uses_collections = True


def name(emitter, target):
    return emitter.function_name(target) + ".callback"


def dynamic_receiver(emitter, node):
    # Select the actual method when binding, as Python does. Besides retaining
    # override defaults, this gives base/derived views the same code/context
    # identity without another virtual callback ABI or identity registry.
    target = node.obj
    if (isinstance(node, ast.Attribute) and not target.is_static
            and target in emitter.module.virtual_methods
            and not emitter.is_super_call(node.value)):
        return analyzed_value_type(node.value)
    return None


def reference(emitter, node):
    if (isinstance(node, ast.Attribute) and not node.obj.is_static
            and tagged.members(semantic := analyzed_value_type(node.value))):
        # A callback captures the decoded receiver, never the tagged aggregate.
        # Select the concrete declaration now, just as Python binds a method;
        # invocation then uses the ordinary descriptor ABI without another switch.
        _, receiver = emitter.expression(node.value)
        return "ptr", tagged.dispatch(emitter, semantic, receiver, "ptr",
            lambda member, kind, value: selected_descriptor(
                emitter, node, member.find_attrs(node.attr), value),
            runtime_classes=True, group=lambda member: member.find_attrs(node.attr))
    if semantic := (dynamic_receiver(emitter, node)
                    or calls.static_receiver(node, emitter.module.functions)):
        _, receiver = emitter.expression(node.value)
        groups = calls.protocol_groups(emitter, semantic, lambda candidate: candidate.find_attrs(node.attr),
                                       compatible=collection_ops.is_layout_subclass)
        if len(groups) == 1:
            return "ptr", selected_descriptor(emitter, node, next(iter(groups)), receiver)
        function = binding(emitter, node, semantic)
        arguments = ", ".join(f"{kind} {value}" for kind, value in
                              (*emitter.context_arguments(), ("ptr", receiver)))
        value = emitter.emit_value(f"call ptr @{emitter.function_name(function)}({arguments})")
        emitter.check_active_exception(node)
        return "ptr", value
    if node.obj not in emitter.module.callables:
        raise LLVMUnsupported("LLVM function reference has no callable implementation", node)
    receiver = None
    # Access through an instance still evaluates its receiver, even for a
    # static method. A class or module qualifier has no runtime value.
    if isinstance(node, ast.Attribute) and not isinstance(analyzed_value_object(node.value), (Class, Module, ModuleAlias)):
        _, receiver = emitter.expression(node.value)
    return "ptr", descriptor(emitter, node.obj, receiver)


class BindMethod(ast.expr):
    _fields = ()

    def __init__(self, reference, source):
        self.reference, self.source = reference, source
        self.obj = callable_value_type(reference)
        ast.copy_location(self, reference)


def binding(e, node, source):
    # Share selection across extraction sites, not across receiver objects.
    # Each call still allocates a fresh bound descriptor. The ordinary function
    # ABI roots its receiver and propagates failures at the caller's location.
    result = callable_value_type(node)
    key = union_type_key(source), node.attr, union_type_key(result)
    if key not in e.module.callable_bindings:
        function = Function(_callback, e.module.entry_module)
        function.name = f"callable.bind.{len(e.module.callable_bindings)}"
        function.source_fragment = e.current_function.source_fragment
        function.return_type = result
        annotation = source.annotation
        annotation.obj = source
        function.params = [ast.arg(arg="receiver", annotation=annotation)]
        function.ir = FunctionIR()
        function.ir.enter(function.ir.new_block("entry"))
        function.ir.terminate(Return(BindMethod(node, source)))
        e.module.function_names[function] = f"pyjs.{function.name}"
        e.module.functions.add(function)
        e.module.callable_bindings[key] = function
    return e.module.callable_bindings[key]


def select_bound(e, node, source, receiver):
    return calls.runtime_protocol(e, source, receiver, "ptr",
        lambda candidate: candidate.find_attrs(node.attr),
        lambda target: selected_descriptor(e, node, target, receiver), node,
        compatible=collection_ops.is_layout_subclass)


def selected_descriptor(emitter, node, target, receiver):
    value = descriptor(emitter, target, receiver)
    actual, expected = callable_value_type(AnalyzedName(target)), callable_value_type(node)
    if same_analyzer_type(actual, expected):
        return value
    from .callable_adapters import wrap
    return wrap(emitter, actual, expected, value, node)


def descriptor(emitter, target, receiver):
    symbol = name(emitter, target)
    if not emitter.module.callables[target]:
        return f"@{symbol}.value"
    value = gc_layouts.allocate(emitter, ("ptr", "ptr"), layout="%pyjs.callable")
    implementation = (f"{symbol}.arities" if target.defaults else
                      f"{symbol}.{len(target.params)}" if target.kwonlyargs else symbol)
    emitter.emit_line(f"store ptr @{implementation}, ptr {value}")
    context = emitter.emit_value(f"getelementptr %pyjs.callable, ptr {value}, i32 0, i32 1")
    emitter.emit_line(f"store ptr {receiver}, ptr {context}")
    return value


def identity_fields(emitter, semantic, value):
    """Canonical implementation/context, independent of signature adapters."""
    from . import callable_adapters

    value = callable_adapters.identity(emitter, semantic, value)
    fields = []
    for index in range(2):
        slot = emitter.emit_value(f"getelementptr %pyjs.callable, ptr {value}, i32 0, i32 {index}")
        fields.append(emitter.emit_value(f"load ptr, ptr {slot}"))
    return fields


def equal(emitter, left_type, left, right_type, right):
    same = [emitter.emit_value(f"icmp eq ptr {a}, {b}")
            for a, b in zip(identity_fields(emitter, left_type, left),
                            identity_fields(emitter, right_type, right), strict=True)]
    # Bound methods compare implementation and receiver identity. Closures and
    # partials keep unique contexts, so two fresh but equivalent captures are
    # not equal. No user receiver __eq__ is called, and no allocation occurs.
    return emitter.emit_value(f"and i1 {same[0]}, {same[1]}")


def hash_value(emitter, semantic, value):
    from .hashing import normalize

    # Fresh bound descriptors compare equal when their implementation/receiver
    # pair matches. Hashing the descriptor address would violate that invariant.
    # Closures and partials have unique contexts; no user hash callback runs.
    bits = [emitter.emit_value(f"ptrtoint ptr {field} to i64")
            for field in identity_fields(emitter, semantic, value)]
    return normalize(emitter, emitter.emit_value(f"xor i64 {bits[0]}, {bits[1]}"))


def definitions(emitter):
    result = []
    for target, bound in emitter.module.callables.items():
        symbol = name(emitter, target)
        if target.defaults or target.kwonlyargs:
            result.extend(default_definitions(emitter, target, bound))
            continue
        if not bound:
            result.append(f"@{symbol}.value = private constant %pyjs.callable {{ ptr @{symbol}, ptr null }}")
        context = [("ptr", "%" + field) for field, enabled in (
            ("__arena", emitter.module.uses_arena), ("__heap", emitter.module.uses_gc),
            ("__exception", emitter.module.uses_exceptions),
        ) if enabled]
        arguments = [(emitter.annotation_storage_type(parameter.annotation, numeric(parameter.representation)), f"%a{index}")
                     for index, parameter in enumerate(target.params)]
        parameters = [*context, ("ptr", "%context"), *arguments]
        returned = emitter.result_storage_type(target.return_type, target.return_numeric_format)
        result.append(f"define private {returned} @{symbol}({', '.join(f'{kind} {value}' for kind, value in parameters)}) {{")
        implementation = "@" + emitter.function_name(target)
        # The descriptor always has the caller's managed ABI. A raw runtime
        # helper receives only its explicit operands, not those hidden contexts.
        forwarded = [*([] if emitter.is_runtime_helper(target) else context),
                     *((("ptr", "%context"),) if bound else ()), *arguments]
        invocation = f"call {returned} {implementation}({', '.join(f'{kind} {value}' for kind, value in forwarded)})"
        # No allocation or safe point intervenes here. The caller roots the
        # descriptor; managed callees install roots, while raw helpers cannot
        # allocate or collect and borrow their operands from the caller.
        result.extend([f"  {invocation}", "  ret void"] if returned == "void" else
                      [f"  %result = {invocation}", f"  ret {returned} %result"])
        result.append("}")
    return result


def _callback():
    raise NotImplementedError


class ReferenceInvoke(ast.expr):
    _fields = ()

    def __init__(self, target, count, bound):
        self.target, self.count, self.bound = target, count, bound
        self.obj = target.return_type
        self.representation = target.return_representation
        ast.copy_location(self, target.original_node)


def default_definitions(parent, target, bound):
    """Default binding uses the ordinary checked emitter, not another binder.

    Optional positional arguments use an arity-indexed table in the code slot.
    Fixed signatures keep the original direct code pointer and 16-byte layout.
    Adapters cross that distinction explicitly; callers never guess defaults.
    """
    from .analysis import NATIVE_ENVIRONMENT
    from .llvm import FunctionEmitter

    symbol = name(parent, target)
    minimum, maximum = len(target.params) - len(target.defaults), len(target.params)
    signature_key = union_type_key(callable_value_type(AnalyzedName(target)))
    entries, result = ["ptr null"] * minimum, []
    for count in range(minimum, maximum + 1):
        if minimum != maximum and (signature_key, count) not in parent.module.callable_arities:
            # Closed native code reaches table slots only through invoke_values;
            # adapters record source arities too. Keep uncalled slots empty rather
            # than rejecting full-arity uses because an unused default is unsupported.
            entries.append("ptr null")
            continue
        function = Function(_callback, parent.module.entry_module)
        function.name = f"{symbol}.{count}"
        function.source_fragment = target.source_fragment
        function.return_type = target.return_type
        function.set_return_representation(target.return_representation)
        context_type = target.cls if bound else NATIVE_ENVIRONMENT.builtins.search("NoneType")
        annotation = context_type.annotation
        annotation.obj = context_type
        function.params = [ast.arg(arg="__context", annotation=annotation)]
        for index, parameter in enumerate(target.params[:count]):
            copied = ast.arg(arg=f"a{index}", annotation=parameter.annotation)
            copied.representation = parameter.representation
            function.params.append(copied)
        function.ir = FunctionIR()
        function.ir.enter(function.ir.new_block("entry"))
        function.ir.terminate(Return(ReferenceInvoke(target, count, bound)))
        parent.module.function_names[function] = function.name
        parent.module.functions.add(function)
        result.extend(FunctionEmitter(parent.module).function(function))
        entries.append(f"ptr @{function.name}")
    if minimum == maximum:
        # Keyword-only defaults do not change positional arity.
        if not bound:
            result.append(f"@{symbol}.value = private constant %pyjs.callable {{ {entries[-1]}, ptr null }}")
    else:
        result.append(f"@{symbol}.arities = private constant [{maximum + 1} x ptr] [{', '.join(entries)}]")
        if not bound:
            result.append(f"@{symbol}.value = private constant %pyjs.callable {{ ptr @{symbol}.arities, ptr null }}")
    return result


def invoke_reference(emitter, node):
    positional, sources = [], []
    for index, parameter in enumerate(node.target.params[:node.count]):
        kind, value = emitter.load(f"a{index}")
        source = tagged.Value(node, parameter.annotation.obj, kind, value)
        source.representation = parameter.representation
        positional.append((kind, value))
        sources.append(source)
    call = ast.copy_location(ast.Call(func=AnalyzedName(node.target), args=sources, keywords=[]), node)
    binding = calls.bind(emitter, node.target, call, positional=positional, runtime_errors=True)
    if binding is None:
        kind = emitter.value_type(node.target.return_type)
        return kind, "" if kind == "void" else "zeroinitializer"
    with binding as arguments:
        return calls.invoke(emitter, node.target, arguments, call,
                            receiver=emitter.load_local("__context") if node.bound else None)


def invoke(emitter, node, value_type):
    signature(emitter, value_type, node)
    if node.keywords or any(isinstance(argument, ast.Starred) for argument in node.args):
        raise LLVMUnsupported("LLVM typed callable invocation requires positional arguments", node)
    if not value_type.accepts_arity(len(node.args)):
        raise LLVMUnsupported("LLVM typed callable invocation has incompatible arity", node)
    _, callback = emitter.expression(node.func)
    arguments = []
    for source, expected in zip(node.args, value_type.parameter_types[:len(node.args)], strict=True):
        kind, value = emitter.expression(source)
        collection_ops.require_matching_layout(callable_value_type(source), expected, source)
        arguments.append((kind, value))
    return invoke_values(emitter, callback, value_type, calls.BoundCall(arguments, node.args), node)


def invoke_values(emitter, callback, value_type, arguments, node):
    _, storage = signature(emitter, value_type, node)
    count = len(arguments.values)
    if not value_type.accepts_arity(count):
        raise LLVMUnsupported("LLVM typed callable invocation has incompatible arity", node)
    emitter.module.callable_arities.add((union_type_key(value_type), count))
    parameters = value_type.parameter_types[:count]
    roots, frame = calls.object_argument_roots(emitter, parameters)
    # As with direct calls, the call node supplies a location, never an
    # argument type. Synthetic loads use SSA metadata when no source exists.
    origin = ast.copy_location(ast.expr(), node)
    converted = []
    representations = value_type.parameter_representations or (None,) * len(value_type.parameter_types)
    for index, ((kind, value), source, expected, stored, representation) in enumerate(zip(
            arguments.values, arguments.sources, parameters, storage[:count], representations[:count], strict=True)):
        kind, value = emitter.coerce_value(kind, value, emitter.value_type(expected),
                                          source if source is not None else origin, semantic=expected,
                                          representation=representation)
        if index in roots:
            emitter.emit_line(f"store ptr {value}, ptr {roots[index]}")
        converted.append(emitter.narrow_numeric(kind, value, stored, node))
    implementation = emitter.emit_value(f"load ptr, ptr {callback}")
    if value_type.minimum_arguments != len(value_type.parameter_types):
        slot = emitter.emit_value(f"getelementptr ptr, ptr {implementation}, i64 {count}")
        implementation = emitter.emit_value(f"load ptr, ptr {slot}")
    context = emitter.emit_value(f"getelementptr %pyjs.callable, ptr {callback}, i32 0, i32 1")
    receiver = emitter.emit_value(f"load ptr, ptr {context}")
    arguments = [*emitter.context_arguments(), ("ptr", receiver), *converted]
    result = calls.checked(emitter, value_type.return_type, numeric(value_type.return_representation),
                           implementation, arguments, node)
    calls.pop_roots(emitter, frame)
    # Callback consumers store results directly (map, sort keys, grouping,
    # reductions). A void ABI call still produces the Python value None.
    result = ("ptr", "null") if result[0] == "void" else result
    # Synthetic consumers bypass expression(), which ordinarily records these
    # types. Their location node describes the consumer, not its callback value.
    emitter.value_semantics[result] = value_type.return_type
    emitter.value_representations[result] = value_type.return_representation
    return result
