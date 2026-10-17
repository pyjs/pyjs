"""Operator functions expressed through ordinary Python syntax lowering."""

import ast
import copy
import operator
from builtins import abs as _abs
from collections.abc import Iterable

from pyjs.decorators import configure_js, native_operation


@native_operation("operator.index")
def index(value: object, /) -> int:
    return operator.index(value)


# Explicit conversion consumes represented scalars without erasing them into
# object storage first. The result is an ordinary Python integer.
configure_js(index, analysis=lambda call: call.standard(defer_representation_arguments=(0,)))


@native_operation("operator.call")
def call(function: object, /, *args: object, **kwargs: object) -> object:
    return operator.call(function, *args, **kwargs)


def _analyze_call(call):
    from pyjs.analysis.diagnostics import DiagnosticCode

    if not call.node.args or isinstance(call.node.args[0], ast.Starred):
        call.visitor.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "operator.call requires an explicit first positional callable")
    # The normal call binder owns callee evaluation, typed argument expansion,
    # keyword conflicts, return representations and exceptions. Do not erase
    # the callee/arguments into this declaration's object parameters first.
    forwarded = ast.Call(func=call.node.args[0], args=call.node.args[1:], keywords=call.node.keywords)
    return call.visitor.visit_contextual_expression(
        ast.copy_location(forwarded, call.node),
        call.visitor.contextual_types.get(call.node),
        call.visitor.contextual_numeric_formats.get(call.node),
        call.visitor.contextual_representations.get(call.node),
    )


configure_js(call, analysis=_analyze_call)


def _concat_template(call, left, inplace):
    from pyjs.analysis.analyzer import analyzed_value_type
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.type_relations import inherited_sequence_slot
    from pyjs.analysis.value_representation import analyzed_array_format

    left_type = analyzed_value_type(left)
    if inherited_sequence_slot(left_type, "__add__") is None:
        call.visitor.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native operator concatenation requires a concrete builtin sequence receiver",
                          help="Narrow to a list, tuple, str or bytes before concatenating.")
    if inplace and analyzed_array_format(left) is not None:
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "Static arrays do not support whole-array augmented assignment",
                          help="Assign individual items or create another static array.")
    method = "__iadd__" if inplace and inherited_sequence_slot(left_type, "__iadd__") else "__add__"
    # Sequence slots do not try a foreign numeric __radd__. Use the builtin's
    # explicit method, not the ordinary binary dispatcher.
    return ast.Call(func=ast.Attribute(value=ast.Name(id="left", ctx=ast.Load()), attr=method, ctx=ast.Load()),
                    args=[ast.Name(id="right", ctx=ast.Load())], keywords=[])


def _analyze_expression(call):
    from pyjs.analysis.analyzer import (
        BUILTINS,
        analyzed_value_object,
        analyzed_value_type,
    )
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.objects import EvaluateOnce, LocalScope, Name
    from pyjs.analysis.representation import apply_representation
    from pyjs.analysis.type_relations import is_builtin_class
    from pyjs.analysis.value_representation import (
        analyzed_representation,
        set_analyzed_representation,
    )

    if any(isinstance(value, ast.Starred) for value in call.node.args) or call.node.keywords:
        call.visitor.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native operator functions require fixed positional arguments")
    sources = list(call.node.args)
    # The object annotations accept every operand; syntax inference supplies
    # the concrete contract. Validate shape without analyzing operands twice
    # or first erasing their numeric/container representations to object.
    call.visitor.validate_call_shape(call.node, call.function)
    visitor = call.visitor.child_visitor(LocalScope(call.visitor.scope))
    bindings = []

    def capture(value):
        instance = analyzed_value_type(value)(f"$operator{len(bindings)}", visitor.scope, visitor.func)
        visitor.scope.add(instance)
        apply_representation(instance, analyzed_representation(value))
        bindings.append((value, instance.name))
        return ast.Name(id=instance.name, ctx=ast.Load())

    arguments = dict(zip((parameter.arg for parameter in call.function.params), sources, strict=True))
    body = call.function.original_node.body
    inplace = len(body) == 2 and isinstance(body[0], ast.AugAssign)
    mutation = len(body) == 1 and isinstance(body[0], (ast.Assign, ast.Delete))
    concatenation = call.function.py_func in {concat, iconcat}
    if call.function.py_func is contains or inplace or mutation or concatenation:
        # Membership reverses call order; in-place dispatch must retain both
        # operand values across callbacks. Item assignment syntax evaluates
        # its RHS first, unlike operator.setitem's container/key/value order.
        # Mutation values need the destination's contextual typing first, so
        # capture only their receiver here; the normal binder analyzes the rest.
        # Ordinary templates keep syntax for constant indexes and refinements.
        for position, (parameter, source) in enumerate(zip(call.function.params, sources, strict=True)):
            if not mutation or position == 0:
                arguments[parameter.arg] = capture(call.visitor.visit(source))

    class Substitute(ast.NodeTransformer):
        def visit_Name(self, node):
            # Resolve helper globals in the template's scope, not the caller's:
            # a caller's variable named _abs must not replace builtin abs().
            value = arguments.get(node.id)
            if value is not None:
                return value
            builtin = BUILTINS.search(call.function.py_func.__globals__[node.id].__name__)
            alias = "$operator_global" + node.id
            visitor.scope.add(builtin, alias)
            return ast.copy_location(Name(builtin, id=alias, ctx=ast.Load()), call.node)

    if concatenation:
        left, right = (binding[0] for binding in bindings)
        left_type = analyzed_value_type(left)
        if is_builtin_class(left_type, "tuple"):
            return call.visitor.concatenate_tuples(call.node, left, right)
        template = _concat_template(call, left, inplace)
    elif mutation:
        statement = body[0]
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Subscript):
            raise TypeError("mutation operator templates require one subscript target")
        target = statement.targets[0]
        # Explicit dunder calls use normal call order rather than assignment's
        # RHS-first rewrite, and share existing item/slice protocol validation.
        template = ast.Call(
            func=ast.Attribute(value=copy.deepcopy(target.value),
                               attr="__setitem__" if isinstance(statement, ast.Assign) else "__delitem__",
                               ctx=ast.Load()),
            args=[copy.deepcopy(target.slice)] +
                 ([copy.deepcopy(statement.value)] if isinstance(statement, ast.Assign) else []),
            keywords=[],
        )
        template.func.class_lookup = True
    elif inplace:
        if (not isinstance(body[0].target, ast.Name) or not isinstance(body[1], ast.Return)
                or not isinstance(body[1].value, ast.Name) or body[1].value.id != body[0].target.id):
            raise TypeError("in-place operator templates must return their local assignment target")
        assignment = copy.deepcopy(body[0])
        # Return the operation's value, not a synthetic assignment: unlike
        # caller-local `x += y`, operator.iadd may change the result type.
        template = ast.BinOp(left=assignment.target, op=assignment.op, right=assignment.value)
        template.augmented = True
    else:
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            raise TypeError("operator templates require a single return expression")
        template = copy.deepcopy(body[0].value)
    result = visitor.visit(ast.fix_missing_locations(ast.copy_location(Substitute().visit(template), call.node)))
    if mutation:
        # Application setters/deleters can return arbitrary values; operator
        # mutation always returns None, while retaining failures and side effects.
        none = visitor.visit(ast.copy_location(ast.Constant(value=None), call.node))
        result = EvaluateOnce(analyzed_value_object(none), result, none, "$operator_discard",
                              lineno=call.node.lineno)
    # All call arguments run before the operation, including reversed syntax
    # such as contains(container, item) -> item in container. Lexical lets also
    # retain temporary objects through effectful protocol calls and GC.
    for value, name in reversed(bindings):
        representation = analyzed_representation(result)
        result = EvaluateOnce(analyzed_value_object(result), value, result, name, lineno=call.node.lineno)
        set_analyzed_representation(result, representation)
    return result


def _expression(function):
    native_operation("operator." + function.__name__)(function)
    configure_js(function, analysis=_analyze_expression)
    return function


def adapt_callback(visitor, node, target):
    """Specialize known operator callbacks using contextual lambda inference."""
    from pyjs.analysis.analyzer import analyzed_value_object
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.objects import Module, ModuleAlias

    if target is None:
        return
    module = getattr(getattr(target, "py_func", None), "__module__", None)
    builtin = isinstance(target.container, Module) and target.container.scope.is_builtins
    position, keyword, predicate = 0, None, False
    if builtin and target.name in {"map", "filter"}:
        predicate = target.name == "filter"
    elif module == "pyjs.native.functional" and target.name == "reduce":
        pass
    elif module == __package__ + ".itertools" and target.name == "accumulate":
        position, keyword = 1, "func"
    elif module == __package__ + ".itertools" and target.name in {"filterfalse", "takewhile", "dropwhile"}:
        predicate = True
    else:
        return
    option = next((item for item in node.keywords if item.arg == keyword), None) if keyword else None
    source = node.args[position] if position < len(node.args) else option.value if option else None
    if not isinstance(source, (ast.Name, ast.Attribute)):
        return
    callback = visitor.visit(source)
    if (isinstance(callback, ast.Attribute)
            and not isinstance(analyzed_value_object(callback.value), (Module, ModuleAlias))):
        return  # Do not discard evaluation of an application receiver.
    function = analyzed_value_object(callback)
    if getattr(function, "analysis", None) is not _analyze_expression:
        return
    visitor.ensure_call_signature_ready(source, function)
    expected = len(node.args) - 1 if builtin and target.name == "map" else 1 if predicate else 2
    if expected == 0:
        visitor.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                     "map() requires at least one iterable after the callback")
    if not any(isinstance(argument, ast.Starred) for argument in node.args) and len(function.params) != expected:
        visitor.fail(source, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                     f"operator.{function.name} takes {len(function.params)} "
                     f"{'argument' if len(function.params) == 1 else 'arguments'}, "
                     f"but {target.name} supplies {expected}")
    # These names cannot be spelled in Python source, so they cannot capture
    # an import alias used as the callback's original callee below.
    names = [f"$operator_argument{index}" for index in range(len(function.params))]
    # Preserve the import/module spelling. Replacing op.abs with a bare abs
    # would accidentally bind a same-named application function in the lambda.
    body = ast.Call(func=source, args=[ast.Name(id=name, ctx=ast.Load()) for name in names], keywords=[])
    if predicate:
        body = ast.UnaryOp(op=ast.Not(), operand=ast.UnaryOp(op=ast.Not(), operand=body))
    replacement = ast.fix_missing_locations(ast.copy_location(ast.Lambda(
        args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=name) for name in names],
                           vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
        body=body,
    ), source))
    if position < len(node.args):
        node.args[position] = replacement
    else:
        option.value = replacement


@_expression
def add(left: object, right: object, /) -> object:
    return left + right


@_expression
def concat(left: object, right: object, /) -> object:
    return left + right


@_expression
def iconcat(left: object, right: object, /) -> object:
    left += right
    return left


@_expression
def sub(left: object, right: object, /) -> object:
    return left - right


@_expression
def mul(left: object, right: object, /) -> object:
    return left * right


@_expression
def truediv(left: object, right: object, /) -> object:
    return left / right


@_expression
def floordiv(left: object, right: object, /) -> object:
    return left // right


@_expression
def mod(left: object, right: object, /) -> object:
    return left % right


@_expression
def pow(left: object, right: object, /) -> object:
    return left ** right


@_expression
def and_(left: object, right: object, /) -> object:
    return left & right


@_expression
def or_(left: object, right: object, /) -> object:
    return left | right


@_expression
def xor(left: object, right: object, /) -> object:
    return left ^ right


@_expression
def lshift(left: object, right: object, /) -> object:
    return left << right


@_expression
def rshift(left: object, right: object, /) -> object:
    return left >> right


@_expression
def neg(value: object, /) -> object:
    return -value


@_expression
def pos(value: object, /) -> object:
    return +value


@_expression
def invert(value: object, /) -> object:
    return ~value


@_expression
def inv(value: object, /) -> object:
    return ~value


@_expression
def abs(value: object, /) -> object:
    return _abs(value)


@_expression
def not_(value: object, /) -> bool:
    return not value


@_expression
def truth(value: object, /) -> bool:
    return not not value


@_expression
def eq(left: object, right: object, /) -> object:
    return left == right


@_expression
def ne(left: object, right: object, /) -> object:
    return left != right


@_expression
def lt(left: object, right: object, /) -> object:
    return left < right


@_expression
def le(left: object, right: object, /) -> object:
    return left <= right


@_expression
def gt(left: object, right: object, /) -> object:
    return left > right


@_expression
def ge(left: object, right: object, /) -> object:
    return left >= right


@_expression
def is_(left: object, right: object, /) -> bool:
    return left is right


@_expression
def is_not(left: object, right: object, /) -> bool:
    return left is not right


@_expression
def is_none(value: object, /) -> bool:
    return value is None


@_expression
def is_not_none(value: object, /) -> bool:
    return value is not None


@_expression
def getitem(container: object, key: object, /) -> object:
    return container[key]


@_expression
def setitem(container: object, key: object, value: object, /) -> None:
    container[key] = value


@_expression
def delitem(container: object, key: object, /) -> None:
    del container[key]


@_expression
def contains(container: object, item: object, /) -> bool:
    return item in container


def countOf(values: Iterable[object], target: object, /) -> int:
    count = 0
    for value in values:
        if value is target or value == target:
            count += 1
    return count


def indexOf(values: Iterable[object], target: object, /) -> int:
    position = 0
    for value in values:
        if value is target or value == target:
            return position
        position += 1
    raise ValueError("sequence.index(x): x not in sequence")


@_expression
def iadd(left: object, right: object, /) -> object:
    left += right
    return left


@_expression
def isub(left: object, right: object, /) -> object:
    left -= right
    return left


@_expression
def imul(left: object, right: object, /) -> object:
    left *= right
    return left


@_expression
def itruediv(left: object, right: object, /) -> object:
    left /= right
    return left


@_expression
def ifloordiv(left: object, right: object, /) -> object:
    left //= right
    return left


@_expression
def imod(left: object, right: object, /) -> object:
    left %= right
    return left


@_expression
def ipow(left: object, right: object, /) -> object:
    left **= right
    return left


@_expression
def iand(left: object, right: object, /) -> object:
    left &= right
    return left


@_expression
def ior(left: object, right: object, /) -> object:
    left |= right
    return left


@_expression
def ixor(left: object, right: object, /) -> object:
    left ^= right
    return left


@_expression
def ilshift(left: object, right: object, /) -> object:
    left <<= right
    return left


@_expression
def irshift(left: object, right: object, /) -> object:
    left >>= right
    return left
