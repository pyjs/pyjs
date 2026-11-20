"""Eager comprehension frames use ordinary JVM arguments for outer bindings."""

import ast

from pyjs.analysis.analyzer import BUILTINS, analyzed_value_type
from pyjs.analysis.comprehensions import lower as lower_ir
from pyjs.analysis.lifetime import lambda_captures
from pyjs.analysis.objects import Call, CallableClass, Name
from pyjs.analysis.value_representation import analyzed_representation


class CaptureValue(ast.expr):
    _fields = ()

    def __init__(self, value):
        self.name = value.id
        self.obj = analyzed_value_type(value)


class CaptureBound(ast.expr):
    _fields = ()

    def __init__(self, value):
        self.name = value.id
        self.obj = BUILTINS.search("bool")


def lower(visitor, analyzed, source):
    node = lower_ir(visitor, analyzed, source)
    function = node.function
    captures = list(lambda_captures(function).values())
    node.captures = captures
    for value in captures:
        function.args.args.append(ast.arg(arg=value.id))
    function.jvm_capture_flags = {}
    for value in captures:
        flag = function.ir.new_name("__capture_bound")
        function.args.args.append(ast.arg(arg=flag))
        function.jvm_capture_flags[value.id] = flag
    original = function.obj
    function.obj = CallableClass(
        (*original.parameter_types, *(analyzed_value_type(value) for value in captures),
         *((BUILTINS.search("bool"),) * len(captures))),
        original.return_type, BUILTINS.search("callable"),
        (*original.parameter_representations, *(analyzed_representation(value) for value in captures),
         *((None,) * len(captures))),
        original.return_representation,
    )
    return node


def expression(emitter, node):
    target = emitter.lambdas[node.function]
    # Read binding flags with their slots, but check them only if the body
    # actually consumes a capture. Empty/filtered iterations must not raise.
    arguments = [node.source, *(CaptureValue(value) for value in node.captures),
                 *(CaptureBound(value) for value in node.captures)]
    call = Call(node.obj, func=Name(target), args=arguments, keywords=[])
    return emitter.call(ast.copy_location(call, node))
