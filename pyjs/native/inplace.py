"""Application in-place protocols with ordinary binary fallback and writeback."""

import ast
import types

from pyjs.analysis.analyzer import analyzed_value_type, is_return_type_compatible
from pyjs.analysis.objects import Class, Function
from pyjs.analysis.representation import apply_representation
from pyjs.analysis.type_relations import get_type_members
from pyjs.analysis.value_representation import (
    analyzed_representation,
    analyzed_value_object,
)

from . import binary, calls, collection_ops, tagged
from .errors import LLVMUnsupported


def resolve(semantic, name, node):
    # Analysis omits None-valued class members from its attribute scope. Do not
    # mistake an explicitly disabled/shadowed protocol for an absent method (or
    # silently inherit the base implementation through that shadow).
    for base in semantic.py_obj.__mro__:
        if name in vars(base):
            descriptor = vars(base)[name]
            method = semantic.find_attrs(name)
            if not isinstance(descriptor, types.FunctionType):
                raise LLVMUnsupported("LLVM in-place operators require an ordinary application method", node)
            if isinstance(method, Function) and method.py_func is descriptor:
                return method
            # Class-body aliases have no independent analyzed declaration. A
            # binary-method alias can reuse that exact function, not a virtual
            # lookup by name which could select an unrelated override.
            owner = semantic
            binary = "__" + name[3:]
            while owner is not None:
                method = owner.find_attrs(binary, search_bases=False)
                if isinstance(method, Function) and method.py_func is descriptor:
                    return method
                owner = owner.super
            raise LLVMUnsupported("LLVM in-place aliases must reference an analyzed binary method", node)
    return None


def binary_call(node):
    invocation = ast.Call(func=node.func, args=node.args, keywords=node.keywords)
    invocation.__dict__.update(vars(node))
    del invocation.inplace_method
    invocation.obj = analyzed_value_object(node)
    return invocation


def emit(e, node):
    if len(node.args) != 1 or node.keywords:
        raise LLVMUnsupported("LLVM in-place operators require one positional operand", node)
    receiver, argument = node.func.value, node.args[0]
    reverse = getattr(node, "reverse", False)
    left, right = (argument, receiver) if reverse else (receiver, argument)
    semantic = analyzed_value_type(left)
    members = get_type_members(semantic)
    if len(members) > 1:
        # Layout retention also includes annotation-only classes, which need
        # not occur at runtime. Match protocol reachability, plus the explicit
        # members (which may arrive through a host boundary without construction).
        reached = e.module.entry_function.compilation_objects
        for candidate in e.module.classes:
            if ((candidate in reached or candidate in members)
                    and any(collection_ops.is_layout_subclass(candidate, member) for member in members)):
                method = resolve(candidate, node.inplace_method, node)
                # A binary alias is equivalent only while the runtime binary
                # method remains that exact function. An intervening override
                # or reflected selection must not replace the captured alias.
                if method is not None and (reverse or e.resolve_method(candidate, node.func.attr) is not method):
                    raise LLVMUnsupported("LLVM union receivers with in-place methods require narrowing", node)
        return e.call(binary_call(node))
    if semantic not in e.module.classes:
        raise LLVMUnsupported("LLVM in-place operators require an application receiver", node)
    result_type = analyzed_value_type(node)
    result_kind = e.expression_type(node)
    # Both operands are evaluated once, left first, before protocol dispatch.
    # Retain the left even if the RHS releases its last application owner.
    kinds = [e.expression_type(value) for value in (left, right)]
    slots, frame = calls.value_slots(e, kinds)
    with calls.BoundCall([], [], e, frame):
        values = []
        for source, slot, expected_kind in zip((left, right), slots, kinds, strict=True):
            kind, value = e.expression(source)
            if kind == "void":
                kind, value = e.coerce_value(kind, value, expected_kind, source)
            e.emit_line(f"store {kind} {value}, ptr {slot}")
            evaluated = tagged.Value(source, analyzed_value_type(source), kind, value)
            if isinstance(evaluated.obj, Class):
                # These are instance operands, not class-qualified calls.
                evaluated.obj = evaluated.obj._self
            # This emitter-local value borrows the canonical type witness;
            # attach representation to the expression, never mutate that witness.
            apply_representation(evaluated, analyzed_representation(source))
            values.append(evaluated)
        left_value, right_value = values

        def select(candidate):
            method = resolve(candidate, node.inplace_method, node)
            if method is None:
                return None
            binary.require_supported_result(method.return_type, node)
            if method not in e.module.functions:
                raise LLVMUnsupported("LLVM in-place operators require a reached ordinary application method", node)
            if len(method.params) != 1 or method.vararg is not None or method.kwarg is not None:
                raise LLVMUnsupported("LLVM in-place methods require exactly one fixed operand parameter", node)
            parameter = method.params[0]
            if (not is_return_type_compatible(parameter.annotation.obj, analyzed_value_type(right))
                    or parameter.representation != analyzed_representation(right)):
                raise LLVMUnsupported("LLVM runtime in-place operand must preserve its analyzed type and representation", node)
            if not is_return_type_compatible(result_type, method.return_type):
                raise LLVMUnsupported("LLVM runtime in-place result must preserve the analyzed result type", node)
            if method.return_representation != analyzed_representation(node):
                raise LLVMUnsupported("LLVM runtime in-place result must preserve its numeric representation", node)
            collection_ops.require_matching_layout(method.return_type, result_type, node)
            return method

        def invoke(method):
            invocation = ast.copy_location(ast.Call(func=node.func, args=[right_value], keywords=[]), node)
            if method is None:
                # Reuse the analyzed normal/reflected operator, including its
                # virtual dispatch, conversions and exception ABI. Replacing
                # only the operands avoids a second evaluation or call binder.
                invocation = binary_call(node)
                invocation.func = ast.Attribute(value=right_value if reverse else left_value,
                                                attr=node.func.attr, ctx=ast.Load())
                invocation.func.obj = node.func.obj
                invocation.args = [left_value if reverse else right_value]
                actual, result = e.call(invocation)
            else:
                with calls.bind(e, method, invocation) as bound:
                    actual, result = calls.invoke(e, method, bound, node, receiver=left_value.value)
                e.value_semantics[actual, result] = method.return_type
                e.value_representations[actual, result] = method.return_representation
            return e.coerce_value(actual, result, result_kind, node, semantic=result_type)[1]

        result = calls.runtime_protocol(e, semantic, left_value.value, result_kind,
                                        select, invoke, node, compatible=collection_ops.is_layout_subclass)
        return result_kind, result
