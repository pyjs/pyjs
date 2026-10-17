"""Typed callable views using ordinary argument and result conversion."""

import ast

from pyjs.analysis.analyzer import callable_value_type
from pyjs.analysis.ir import FunctionIR, Return
from pyjs.analysis.objects import (
    CallableClass,
    Function,
    Instance,
    UnionType,
    same_analyzer_type,
    union_type_key,
)
from pyjs.analysis.objects import Name as AnalyzedName
from pyjs.analysis.type_relations import is_return_type_compatible
from pyjs.decorators import get_native_decoration

from . import (
    callables,
    calls,
    collection_ops,
    gc_layouts,
    nullable,
    object_values,
    tagged,
)
from .errors import LLVMUnsupported
from .runtime import objects as runtime


def compatible(source, target):
    return (isinstance(source, CallableClass) and isinstance(target, CallableClass)
            and source.parameter_types is not None and target.parameter_types is not None
            and is_return_type_compatible(target, source))


def plain_builtin(value):
    # Distinct builtin domains never implicitly convert in a native call ABI.
    # Literal strings and nominal types are deliberately not included here.
    return collection_ops.builtin_name(value) in {'bool', 'int', 'float', 'str', 'bytes', 'NoneType'}


def prepare(emitter, functions, classes):
    # Callable inputs/results can need headers before object layouts are fixed.
    # Actual descriptor signatures become available after callable preparation.
    pending = [value for function in functions for value in (
        function.return_type, *(p.annotation.obj for p in calls.parameters(function)),
        *(value.cls for value in function.scope.names.values() if isinstance(value, Instance)))]
    pending.extend(field.value_type for layout in classes for field in layout.fields)
    # Reached inline declarations have no emitted Python body, but converting
    # their arguments can still require descriptor runtimes and managed roots.
    # Include their signatures in this existing type walk, before ABI setup.
    pending.extend(value for function in emitter.module.native_functions
                   if get_native_decoration(function.py_func).kind == "inline"
                   for value in (function.return_type, *(p.annotation.obj for p in calls.parameters(function))))
    signatures, seen = [], set()
    while pending:
        value = pending.pop()
        if value is None or id(value) in seen:
            continue
        seen.add(id(value))
        from .iterator_ops import is_iterator
        if is_iterator(value):
            emitter.module.iterator_signatures[union_type_key(value)] = value
        if isinstance(value, CallableClass):
            signatures.append(value)
            pending.extend((*value.parameter_types, value.return_type) if value.parameter_types is not None
                           else (value.return_type,))
        elif isinstance(value, UnionType):
            pending.extend(value.types)
        else:
            emitter.module.uses_erased_objects |= nullable.is_object(value)
            from . import iterable_views
            if iterable_views.is_view(value):
                iterable_views.reserve(emitter)
            pending.extend((getattr(value, 'generic_types', None) or {}).values())
    return signatures


def reserve(emitter, signatures):
    # Decide from distinct signatures, not each occurrence or every AST node.
    # One incompatible input excludes a pair even if its results could adapt;
    # arity-only domain flags otherwise add GC to unrelated scalar loops.
    signatures.extend(callable_value_type(AnalyzedName(function))
                      for function in emitter.module.callables)
    signatures.extend(node.obj for node in emitter.module.lambdas)
    by_arity, seen = {}, set()
    for signature in signatures:
        key = union_type_key(signature)
        if signature.parameter_types is None or key in seen:
            continue
        seen.add(key)
        arities = range(signature.minimum_arguments, len(signature.parameter_types) + 1)
        previous = dict.fromkeys(other for count in arities for other in by_arity.get(count, ()))
        for other in previous:
            for source, target in ((signature, other), (other, signature)):
                if not compatible(source, target):
                    continue
                try:
                    check_view(source, target, None)
                except LLVMUnsupported:
                    continue
                emitter.module.uses_callable_adapters = emitter.module.uses_collections = True
                return
        for count in arities:
            by_arity.setdefault(count, []).append(signature)


def _adapter():
    raise NotImplementedError


class Invoke(ast.expr):
    # Parameters already belong to the wrapper frame; there is no source
    # subtree to evaluate, analyze again or capture a second time.
    _fields = ()

    def __init__(self, source, target, location, count, *, narrow=False):
        self.source = source
        self.target = target
        self.narrow = narrow
        self.count = count
        self.obj = target.return_type if narrow else source.return_type
        self.representation = target.return_representation if narrow else source.return_representation
        ast.copy_location(self, location)


def register(e, source, target, node, count, *, narrow=False):
    # Function references create fresh CallableClass objects. Key by semantic
    # signature (including representations), not that temporary object's id.
    pair = union_type_key(source), union_type_key(target), count
    if pair in e.module.callable_adapters:
        return e.module.callable_adapters[pair]
    function = Function(_adapter, e.module.entry_module)
    function.name = f'callable.adapt.{len(e.module.callable_adapters)}'
    # Generated bodies use the conversion expression's coordinates. Keep its
    # source fragment too so a diagnostic does not point into this module.
    function.source_fragment = e.current_function.source_fragment
    function.return_type = target.return_type
    function.set_return_representation(target.return_representation)
    representations = target.parameter_representations or (None,) * len(target.parameter_types)
    # The captured descriptor occupies the ordinary callable context position:
    # managed contexts, source descriptor, then the target's fixed parameters.
    parameters = [('__callback', source, None), *(
        (f'a{index}', value, representation) for index, (value, representation)
        in enumerate(zip(target.parameter_types[:count], representations[:count], strict=True)))]
    for name, value, representation in parameters:
        annotation = value.annotation
        annotation.obj = value
        parameter = ast.arg(arg=name, annotation=annotation)
        parameter.representation = representation
        function.params.append(parameter)
    function.ir = FunctionIR()
    function.ir.enter(function.ir.new_block('entry'))
    function.ir.terminate(Return(Invoke(source, target, node, count, narrow=narrow)))
    e.module.function_names[function] = f'pyjs.{function.name}'
    e.module.functions.add(function)
    e.module.callable_adapters[pair] = function
    return function


def convert(e, kind, value, expected, node):
    actual = e.value_semantics.get((kind, value))
    source, target = nullable.member(actual) or actual, nullable.member(expected) or expected
    if not isinstance(source, CallableClass) or not isinstance(target, CallableClass):
        return None
    if same_analyzer_type(source, target) or target.parameter_types is None:
        return kind, value
    check_view(source, target, node)
    if nullable.member(actual):
        result = nullable.dispatch(e, actual, kind, value, 'ptr', 'null',
            lambda member, storage, item: wrap(e, source, target, item, node))
    else:
        result = wrap(e, source, target, value, node)
    e.value_semantics['ptr', result] = expected
    return 'ptr', result


def check_view(source, target, node):
    """The same static ABI rules govern reservation and actual conversion."""
    if not compatible(source, target):
        raise LLVMUnsupported('LLVM callable adapters require compatible arities and types', node)
    if (not same_analyzer_type(source.return_type, target.return_type)
            and plain_builtin(source.return_type) and plain_builtin(target.return_type)):
        # Typing admits bool -> int and int -> float, but native result storage
        # requires an explicit cast. Reject before allocating an unsupported
        # view: preparation intentionally reserved no runtime for this pair.
        raise LLVMUnsupported('LLVM callable results require an explicit numeric conversion', node)
    collection_ops.require_matching_layout(source.return_type, target.return_type, node)
    for actual_parameter, expected_parameter in zip(target.parameter_types,
                                                   source.parameter_types[:len(target.parameter_types)], strict=True):
        if (not same_analyzer_type(actual_parameter, expected_parameter)
                and plain_builtin(actual_parameter) and plain_builtin(expected_parameter)):
            # Like result casts, these pairs intentionally reserve no heap;
            # reject before trying to allocate their unsupported adapter.
            raise LLVMUnsupported('LLVM callable parameters require an explicit numeric conversion', node)
        collection_ops.require_matching_layout(actual_parameter, expected_parameter, node)


def read(e, source, target, kind, value, node):
    """Expose a flow-narrowed view without changing the stored callable ABI."""
    actual, expected = nullable.member(source) or source, nullable.member(target) or target
    if (not isinstance(actual, CallableClass) or not isinstance(expected, CallableClass)
            or same_analyzer_type(actual, expected) or not compatible(expected, actual)):
        return None
    # Assignment refines the visible signature, but the slot still contains
    # its declaration's ABI. Project inputs/results without retyping that slot.
    if nullable.member(source) and nullable.member(target):
        return 'ptr', nullable.dispatch(e, source, kind, value, 'ptr', 'null',
            lambda member, storage, item: wrap(e, actual, expected, item, node, narrow=True))
    if nullable.member(source):
        nullable.check_narrowing(e, kind, value, expected, node, 'callable view')
    return 'ptr', wrap(e, actual, expected, value, node, narrow=True)


def implementation(e, source, target):
    key = union_type_key(source), union_type_key(target)
    function = e.module.callable_adapters.get((*key, target.minimum_arguments))
    if function is None:
        return None
    suffix = '.arities' if target.minimum_arguments != len(target.parameter_types) else ''
    return e.function_name(function) + suffix


def wrap(e, source, target, value, node, *, narrow=False):
    for count in range(target.minimum_arguments, len(target.parameter_types) + 1):
        register(e, source, target, node, count, narrow=narrow)
    code_pointer = implementation(e, source, target)
    roots = calls.root_values(e, value)
    inverse = implementation(e, target, source)
    if inverse is not None:
        # Cancel only this exact ABI roundtrip, never arbitrary adapter layers.
        # Otherwise repeated narrow/store pairs retain an ever-growing chain.
        result = e.emit_value('alloca ptr')
        code = e.emit_value(f'load ptr, ptr {value}')
        same = e.emit_value(f'icmp eq ptr {code}, @{inverse}')
        context = e.emit_value(f'getelementptr %pyjs.callable, ptr {value}, i32 0, i32 1')
        original = e.emit_value(f'load ptr, ptr {context}')
        e.emit_line(f'store ptr {original}, ptr {result}')
        create, done = e.new_label('adapter.create'), e.new_label('adapter.done')
        e.emit_line(f'br i1 {same}, label %{done}, label %{create}')
        e.emit_line(f'{create}:')
    descriptor = gc_layouts.allocate(e, ("ptr", "ptr"), layout="%pyjs.callable")
    e.emit_line(f'store ptr @{code_pointer}, ptr {descriptor}')
    context = e.emit_value(f'getelementptr %pyjs.callable, ptr {descriptor}, i32 0, i32 1')
    e.emit_line(f'store ptr {value}, ptr {context}')
    if inverse is not None:
        e.emit_line(f'store ptr {descriptor}, ptr {result}')
        e.emit_line(f'br label %{done}')
        e.emit_line(f'{done}:')
        descriptor = e.emit_value(f'load ptr, ptr {result}')
    calls.pop_roots(e, roots)
    if root := e.expression_roots.get(id(node)):
        e.emit_line(f'store ptr {descriptor}, ptr {root}')
    return descriptor


def integer_view(e, kind, value, expected, node, description):
    # isinstance(int) includes bool, but a fixed integer ABI has no bool tag.
    # Both input and result projections must check rather than silently cast.
    if kind == tagged.STORAGE and collection_ops.builtin_name(expected) == 'int':
        tag, value = tagged.parts(e, value)
        e.guard_exception(node, e.emit_value(f'icmp eq i64 {tag}, {tagged.TAGS["int"]}'),
                          'TypeError', f'callable {description} is not an integer')
        return 'i64', value
    return kind, value


def invoke(e, node):
    if not node.source.accepts_arity(node.count):
        # A selected override can remove defaults, and a narrowed read can
        # retain a genuinely narrower callback after reassignment. Neither
        # path may invent missing arguments or read outside the source table.
        e.guard_exception(node, "false", "TypeError", "callable does not accept this argument count")
        kind = e.result_storage_type(node.obj, None)
        return kind, "" if kind == "void" else "zeroinitializer"
    arguments = []
    # The wrapper receives the target ABI, then invokes the source ABI. Never
    # stamp an unconverted target operand with the source parameter's type.
    representations = node.target.parameter_representations or (None,) * len(node.target.parameter_types)
    projected_roots = []
    for index, (semantic, representation, expected) in enumerate(zip(
            node.target.parameter_types[:node.count], representations[:node.count],
            node.source.parameter_types[:node.count], strict=True)):
        kind, value = e.load(f'a{index}')
        if node.narrow:
            # A captured narrowing may outlive reassignment of its descriptor.
            # Check the argument against the stored ABI before callback entry,
            # just as a narrowed read checks a wider stored result afterward.
            source = tagged.Value(node, expected, kind, value)
            source.representation = (node.source.parameter_representations or
                                     (None,) * len(node.source.parameter_types))[index]
            if nullable.is_object(semantic) and not nullable.is_object(expected):
                kind, value = object_values.project(e, value, expected, source)
            elif converted := read(e, semantic, expected, kind, value, node):
                kind, value = converted
            else:
                kind, value = calls.project_value(e, semantic, representation, kind, value,
                                                 source, description="callable argument")
            kind, value = integer_view(e, kind, value, expected, node, 'argument')
            semantic, representation = expected, source.representation
            if kind == 'ptr':
                # Projecting nested callbacks or erased values can allocate
                # before later parameters; retain those converted arguments.
                projected_roots.append(calls.root_values(e, value))
        # Synthetic loads have no source expression for coerce_value to inspect.
        # Preserve object/collection semantics and portable widths explicitly.
        e.value_semantics[kind, value] = semantic
        e.value_representations[kind, value] = representation
        arguments.append((kind, value))
    arguments = calls.BoundCall(arguments, [None] * len(arguments))
    kind, value = callables.invoke_values(e, e.load_local('__callback'), node.source, arguments, node)
    for frame in reversed(projected_roots):
        calls.pop_roots(e, frame)
    if node.narrow:
        if converted := read(e, node.source.return_type, node.obj, kind, value, node):
            return converted
        if nullable.is_object(node.source.return_type) and isinstance(node.obj, UnionType):
            # Compiler-known result contracts can project every union arm;
            # ordinary authored object narrowing deliberately requires one arm.
            return object_values.project(e, value, node.obj, node)
        kind, value = calls.project_result(e, node.source, kind, value, node)
        return integer_view(e, kind, value, node.obj, node, 'result')
    return kind, value


def definitions(parent):
    # Bodies are drained together with iterator/Iterable views: conversions
    # in one family may discover a helper in another. Publish tables afterward.
    result = []
    if parent.module.uses_callable_adapters:
        names = []
        for function in parent.module.callable_adapters.values():
            operation = function.ir.blocks[0].body[-1].value
            source, target = operation.source, operation.target
            if operation.count != target.minimum_arguments:
                continue
            symbol = implementation(parent, source, target)
            names.append(symbol)
            if target.minimum_arguments != len(target.parameter_types):
                key = union_type_key(source), union_type_key(target)
                entries = ["ptr null"] * target.minimum_arguments
                entries.extend(
                    f"ptr @{parent.function_name(parent.module.callable_adapters[*key, count])}"
                    for count in range(target.minimum_arguments, len(target.parameter_types) + 1)
                )
                result.append(f"@{symbol} = private constant [{len(entries)} x ptr] [{', '.join(entries)}]")
        if names:
            result.extend(runtime.compiled_callable_runtime())
            result.extend([
                f'@pyjs.callable.adapters = private constant [{len(names)} x ptr] '
                f'[{", ".join("ptr @" + name for name in names)}]',
                'define private ptr @pyjs.callable.identity(ptr %value) {',
                '  %result = call ptr @pyjs.callable.identity.with.adapters('
                f'ptr %value, ptr @pyjs.callable.adapters, i64 {len(names)})',
                '  ret ptr %result', '}',
            ])
        else:
            result.extend(['define private ptr @pyjs.callable.identity(ptr %value) {',
                           '  ret ptr %value', '}'])
    return result


def identity(e, semantic, value):
    if e.module.uses_callable_adapters and isinstance(nullable.member(semantic) or semantic, CallableClass):
        return e.emit_value(f'call ptr @pyjs.callable.identity(ptr {value})')
    return value
