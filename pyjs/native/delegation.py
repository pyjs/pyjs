"""Lower generator delegation through ordinary checked calls and exception CFGs."""

import ast
from collections.abc import Iterator
from textwrap import indent

from pyjs.analysis.analyzer import (
    BUILTINS,
    DependencyError,
    analyzed_value_object,
    analyzed_value_type,
    should_analyze_target_body,
)
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.iterable_protocol import iteration_method
from pyjs.analysis.objects import (
    AnalyzedExpression,
    Class,
    Function,
    Name,
    resolve_imported,
)
from pyjs.analysis.type_relations import (
    is_builtin_class,
    merge_return_types,
    same_analyzer_type,
)
from pyjs.analysis.value_representation import (
    analyzed_representation,
    merged_representation,
    set_analyzed_representation,
)
from pyjs.decorators import ParameterLifetime, configure_js, native_operation

from .object_values import ResultProjection


@native_operation("delegation.close", source=ParameterLifetime.BORROWED)
def close_cursor[T](source: Iterator[T]) -> None:
    try:
        close = source.close
    except AttributeError:
        return
    close()


@native_operation("delegation.throw", source=ParameterLifetime.BORROWED,
                  error=ParameterLifetime.BORROWED)
def throw_cursor[T](source: Iterator[T], error: BaseException) -> T:
    try:
        throw = source.throw
    except AttributeError:
        raise error from None
    return throw(error)


@native_operation("delegation.completion", error=ParameterLifetime.RETURNED)
def completion_cursor(error: StopIteration) -> object:
    return error.value


def control_dependencies(call, name):
    result = call.standard()
    result.runtime_protocols = (*result.runtime_protocols,
                               (analyzed_value_type(result.args[0]), (name,)))
    if name == "throw":
        protocol = call.visitor.require_iterable(call.node, result.args[0])
        return call.set_result_representation(result, protocol.item_representation)
    return result


configure_js(close_cursor, analysis=lambda call: control_dependencies(call, "close"))
configure_js(throw_cursor, analysis=lambda call: control_dependencies(call, "throw"))

# Keep the forwarding algorithm readable as Python. Analysis still owns every
# call, exception edge and suspension; there is no parallel delegation ABI.
_FORWARD = """
try:
    item = next(source)
except StopIteration{binding}:
    {completion}
else:
    while True:
        try:
            received = yield item
        except GeneratorExit:
            {close}
            raise
        except BaseException as error:
{throw}
        else:
            try:
{send}
            except StopIteration{binding}:
                {completion}
                break
"""

_THROW = """try:
    {advance}
except StopIteration{binding}:
    {completion}
    break"""

# These concrete containers acquire builtin iterators with no optional
# send/throw/close protocol. Do not apply this rule to erased Iterator views:
# those may contain generators or application cursors with such methods.
_BUILTIN_ITERATORS = {
    "list": "list_iterator", "tuple": "tuple_iterator", "dict": "dict_keyiterator",
    "set": "set_iterator", "frozenset": "set_iterator", "range": "range_iterator",
    "str": "str_iterator", "bytes": "bytes_iterator", "KeysView": "dict_keyiterator",
    "ValuesView": "dict_valueiterator", "ItemsView": "dict_itemiterator",
}


def concrete_factory(visitor, node, source):
    """Recover only a direct compiled factory's frame, not an erased cursor."""
    target = analyzed_value_object(source.func) if isinstance(source, ast.Call) else None
    actual = analyzed_value_type(source)
    if (isinstance(target, Function) and target.is_generator and target.cls is None
            and is_builtin_class(actual, "Iterator")
            and should_analyze_target_body(target)):
        if not target.is_analyzed:
            # A declared Iterator makes its call signature available before
            # body analysis. Hidden send/completion types need that body first.
            if target is visitor.func:
                visitor.fail(node, DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                             "recursive delegation requires an explicit Generator return annotation")
            raise DependencyError(target)
        signature = target.native_generator_signature
        if (signature is not None and same_analyzer_type(actual, target.return_type)
                and analyzed_representation(source) == target.return_representation):
            # An overload may share the erased item type but select a different
            # portable width. Do not replace that contract with the body's one.
            source.obj = source.value_obj = signature[0]
            set_analyzed_representation(source, signature[1])
    return source


def acquire_application_source(visitor, node, source):
    value_type = analyzed_value_type(source)
    if isinstance(value_type, Class) and not value_type.container.scope.is_builtins:
        # Preserve a known Generator's send/completion contract. Other sources
        # acquire through iter() below, once, without reacquiring its result.
        method = iteration_method(value_type, "__iter__")
        if method is None:
            return source
        # Signature analysis can expose the declaration before the method's
        # body has finalized return_type. Do not erase that known contract.
        returned = method.declared_return_type or method.return_type
        if returned is None:
            raise DependencyError(method)
        if not is_builtin_class(returned, "Generator"):
            return source
        source = visitor.visit(ast.fix_missing_locations(ast.copy_location(ast.Call(
            func=ast.Attribute(value=source, attr="__iter__", ctx=ast.Load()), args=[], keywords=[],
        ), node)))
        visitor.require_iterable(node, source)
    return source


def analyze(visitor, node):
    source = concrete_factory(visitor, node.value, visitor.visit(node.value))
    source = acquire_application_source(visitor, node.value, source)
    value_type = analyzed_value_type(source)
    protocol = visitor.require_iterable(node, source)
    representation = analyzed_representation(source)
    parts = representation.arguments if representation else (None, None, None)
    item_type = protocol.item_type
    item_obj = item_type("__delegated_item", visitor.scope, visitor.func) if isinstance(item_type, Class) else item_type
    item = Name(item_obj, ctx=ast.Load())
    set_analyzed_representation(item, protocol.item_representation)
    visitor.analyze_yield_value(node, item)
    result = ast.copy_location(ast.YieldFrom(value=source), node)
    if not is_builtin_class(value_type, "Generator"):
        # A builtin iterator normally completes with None, but CPython treats
        # an injected StopIteration as delegation completion even without a
        # throw method. Its arbitrary payload becomes the expression's value.
        result.obj = BUILTINS.search("object")
        return result
    completed, completion = value_type.generic_types["R"], parts[2]
    target = analyzed_value_object(source.func) if isinstance(source, ast.Call) else None
    fresh = isinstance(target, Function) and target.is_generator and target.cls is None
    if not fresh:
        # A reusable generator can already be exhausted: its subsequent
        # StopIteration has value None, regardless of its first return contract.
        # Only a direct non-virtual generator factory proves a fresh frame.
        none = BUILTINS.search("NoneType")
        result.obj = merge_return_types(completed, none)
        completion = merged_representation(result.obj, ((completed, completion), (none, None)))
    else:
        result.obj = completed
    set_analyzed_representation(result, completion)
    return result


def lower_statement(visitor, node, *, capture=None):
    source = visitor.ir.new_name("__delegate_source")
    value = concrete_factory(visitor, node, visitor.visit(node.value.value))
    assignment = ast.copy_location(ast.Assign(
        targets=[ast.Name(id=source, ctx=ast.Store())], value=AnalyzedExpression(value),
    ), node)
    visitor.visit(ast.fix_missing_locations(assignment))
    original = visitor.visit(ast.copy_location(ast.Name(id=source, ctx=ast.Load()), node))
    acquired_source = acquire_application_source(visitor, node, original)
    if acquired_source is not original:
        # Statement-form delegation has not passed through analyze(); acquire
        # here exactly once and outside the advancement StopIteration handler.
        source = visitor.ir.new_name("__delegate_acquired")
        visitor.visit(ast.fix_missing_locations(ast.copy_location(ast.Assign(
            targets=[ast.Name(id=source, ctx=ast.Store())], value=acquired_source,
        ), node)))
    source_type = visitor.scope.lookup(source).cls
    visitor.require_iterable(node.value, visitor.visit(ast.copy_location(ast.Name(id=source, ctx=ast.Load()), node)))
    representation = visitor.scope.lookup(source).representation
    generator = is_builtin_class(source_type, "Generator")
    # Application namesakes still need optional protocol dispatch, not a
    # builtin container's no-close path or a Generator's frame layout.
    erased = not generator and not (source_type.container.scope.is_builtins
                                    and source_type.generic_name in _BUILTIN_ITERATORS)
    if erased:
        declared = visitor.func.declared_return_type
        sent = (declared.generic_types["S"] if is_builtin_class(declared, "Generator")
                else visitor.func.send_type)
        if sent is not None and not is_builtin_class(sent, "NoneType"):
            visitor.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                         "native erased delegation requires a None send contract",
                         help="Use a concrete Generator annotation to preserve non-None send types.")
    if generator and visitor.func.declared_return_type is None and visitor.func.send_type is None:
        # An unannotated forwarding generator receives the delegate's input
        # domain, not None merely because this hidden yield has no annotation.
        visitor.func.send_type = source_type.generic_types["S"]
        visitor.func.send_representation = representation.arguments[1] if representation else None

    container = source
    if not generator:
        # Acquire exactly once, before catching advancement's StopIteration.
        # Keep the original container separately typed from its iterator handle.
        acquired, acquire = visitor.ir.new_name("__delegate_iterator"), visitor.ir.new_name("__delegate_iter")
        visitor.scope.add(BUILTINS.search("iter"), name=acquire)
        visitor.visit(ast.fix_missing_locations(ast.copy_location(ast.Assign(
            targets=[ast.Name(id=acquired, ctx=ast.Store())],
            value=ast.Call(func=ast.Name(id=acquire, ctx=ast.Load()),
                           args=[ast.Name(id=source, ctx=ast.Load())], keywords=[]),
        ), node)))
        source = acquired

    names = {"source": source, "container": container}
    if erased:
        for operation in (close_cursor, throw_cursor, completion_cursor):
            names[operation.__name__] = visitor.ir.new_name("__delegate_" + operation.__name__)
            visitor.scope.add(resolve_imported(operation, visitor.module), name=names[operation.__name__])
    builtins = ("object", "next", "StopIteration", "GeneratorExit", "BaseException", "AttributeError", "OverflowError", "len")
    for name in ("item", "received", "error", "result", "completed", *builtins):
        names[name] = visitor.ir.new_name("__delegate_" + name)
        if name in builtins:
            visitor.scope.add(BUILTINS.search(name), name=names[name])
    binding, completion = " as completed" if capture else "", "result = completed.value" if capture else "pass"
    if erased and capture:
        completion = "result = completion_cursor(completed)"
    send = "item = source.send(received)"
    if erased:
        send = "item = next(source)"
    elif not generator:
        def missing(name):
            return repr(f"'{name}' object has no attribute 'send'")

        message = missing(_BUILTIN_ITERATORS[source_type.generic_name])
        if source_type.generic_name == "str":
            message = f"{missing('str_ascii_iterator')} if container.isascii() else {message}"
        failure = f"raise AttributeError({message})"
        if source_type.generic_name == "range":
            # Match CPython range_iter's C-long length and terminal-step guards
            # on the error path only. A resumed delegate has yielded, so its
            # range was nonempty. Endpoints/step already fit native signed i64.
            long_error = f"raise AttributeError({missing('longrange_iterator')})"
            failure = ("try:\n    len(container)\nexcept OverflowError:\n"
                       f"    {long_error}\n"
                       "if (container.step > 0 and container.stop > 9223372036854775807 - (container.step - 1)) or "
                       "(container.step < 0 and container.stop < -9223372036854775808 + (-1 - container.step)):\n"
                       f"    {long_error}\n{failure}")
        send = "if received is None:\n    item = next(source)\nelse:\n" + indent(failure, " " * 4)
    tree = ast.parse(("result: object = None\n" if capture else "") + _FORWARD.format(
        binding=binding, completion=completion,
        close="source.close()" if generator else "close_cursor(source)" if erased else "pass",
        throw=indent(_THROW.format(advance="item = source.throw(error)" if generator else
                                  "item = throw_cursor(source, error)" if erased else "raise",
                                  binding=binding, completion=completion), " " * 12),
        send=indent(send, " " * 16),
    ))
    for child in ast.walk(tree):
        if (generator and isinstance(child, ast.Attribute) and child.attr == "value"
                and isinstance(child.value, ast.Name) and child.value.id == "completed"):
            # This compiler-owned object temporary is projected back to the
            # delegate's R below; it is not an authored erased payload read.
            child.native_typed_completion = True
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "throw_cursor":
            child.native_delegated_throw = True
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "completion_cursor":
            child.native_delegated_completion = True
        if isinstance(child, ast.Name):
            child.id = names.get(child.id, child.id)
        elif isinstance(child, ast.ExceptHandler) and child.name is not None:
            child.name = names[child.name]
        if isinstance(child, (ast.expr, ast.stmt, ast.ExceptHandler)):
            ast.copy_location(child, node)
    visitor.visit_body(tree.body)
    if not capture:
        return ast.copy_location(ast.Pass(), node)
    value = visitor.visit(ast.copy_location(ast.Name(id=names["result"], ctx=ast.Load()), node))
    result_type, result_representation = capture
    return ast.copy_location(ResultProjection(
        value, result_type, result_representation,
    ), node)
