"""Application round() calls expressed as ordinary typed method dispatch."""

import ast
import inspect

from pyjs.analysis.analyzer import (
    analyzed_value_object,
    analyzed_value_type,
    declared_protocol_method,
)
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.objects import (
    EvaluateOnce,
    Function,
    LocalScope,
)
from pyjs.analysis.representation import apply_representation
from pyjs.analysis.type_relations import get_type_members
from pyjs.analysis.value_representation import (
    analyzed_representation,
    set_analyzed_representation,
)

from .analysis import expands_arguments
from .nullable import is_object


def application_round(call, result):
    if expands_arguments(result):
        call.visitor.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native application round requires statically bound arguments")
    visitor = call.visitor.child_visitor(LocalScope(call.visitor.scope))
    arguments = list(zip(("number", "ndigits"), result.args, strict=False))
    arguments.extend((keyword.arg, keyword.value) for keyword in result.keywords)
    bindings, values = [], {}
    # round(ndigits=effect1(), number=effect2()) evaluates in that order before
    # lookup, but the method call needs number as receiver. Root lexical lets
    # preserve both that order and one evaluation across the None branch.
    for position, (name, value) in enumerate(arguments):
        semantic = analyzed_value_type(value)
        instance = semantic(f"$round{position}", visitor.scope, visitor.func)
        temporary = ast.copy_location(ast.Name(id=instance.name, ctx=ast.Load()), value)
        visitor.scope.add(instance)
        apply_representation(instance, analyzed_representation(value))
        bindings.append((value, temporary.id))
        values[name] = temporary

    receiver = visitor.visit(values["number"])
    for member in get_type_members(analyzed_value_type(receiver)):
        # This analysis hook is shared by LLVM/JVM/WASM. Validate the same
        # declaration as native dispatch, but report target-neutral diagnostics.
        declaration = inspect.getattr_static(member.py_obj, "__round__", None)
        method = declared_protocol_method(member, "__round__", declaration)
        if not isinstance(method, Function) or method.is_property or method.is_classmethod:
            visitor.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                         "native round requires an instance or static __round__ method")

    def invoke(digits):
        # Implicit protocols search the class, not instance callable fields.
        method = ast.Attribute(value=values["number"], attr="__round__", ctx=ast.Load())
        method.class_lookup = True
        return ast.Call(func=method, args=digits, keywords=[])

    digits = values.get("ndigits")
    members = get_type_members(analyzed_value_type(visitor.visit(digits))) if digits is not None else ()
    present = tuple(member for member in members
                    if not member.container.scope.is_builtins or member.generic_name != "NoneType")
    if not present:
        result = invoke([])
    elif len(present) == len(members) and not any(is_object(member) for member in members):
        result = invoke([digits])
    else:
        result = ast.IfExp(test=ast.Compare(left=digits, ops=[ast.Is()], comparators=[ast.Constant(value=None)]),
                           body=invoke([]), orelse=invoke([digits]))
    # Analyze regular Python shapes so overload selection, argument checking,
    # None narrowing and result/representation joins stay owned by the analyzer.
    result = visitor.visit(ast.fix_missing_locations(ast.copy_location(result, call.node)))
    for value, name in reversed(bindings):
        representation = analyzed_representation(result)
        result = EvaluateOnce(analyzed_value_object(result), value, result, name, lineno=call.node.lineno)
        set_analyzed_representation(result, representation)
    return result
