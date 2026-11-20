"""Lift an analyzed lambda body into the ordinary function-emission pipeline."""

from copy import copy

from .objects import Function, Module


def lift_lambda(owner, node, name):
    module = owner.container if isinstance(owner.container, Module) else owner.container.container
    function = Function(owner.py_func, module)
    function.name = name
    function.cls = None
    function.scope = node.scope
    function.ir = node.ir
    function.original_node = node
    function.lineno = owner.lineno
    function.return_type = node.obj.return_type
    function.is_generator = getattr(node, "is_generator", False)
    function.set_return_representation(node.obj.return_representation)
    representations = node.obj.parameter_representations or (None,) * len(node.obj.parameter_types)
    for parameter, value_type, representation in zip(
        (*node.args.posonlyargs, *node.args.args), node.obj.parameter_types,
        representations, strict=True,
    ):
        parameter = copy(parameter)
        parameter.annotation = value_type.annotation
        # Synthetic annotation names must not be resolved in the owner's scope.
        parameter.annotation.obj = value_type
        parameter.representation = representation
        function.params.append(parameter)
    return function
