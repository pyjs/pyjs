"""Bind text editing arguments before checked, effectful count conversion."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.python import native as builtins

from . import calls, indexing, persistent, tagged
from .analysis import expands_arguments
from .errors import LLVMUnsupported

PARAMETERS = {"ljust": "width", "rjust": "width", "center": "width", "zfill": "width",
              "expandtabs": "tabsize", "replace": "count", "split": "maxsplit", "rsplit": "maxsplit"}


def retain(node):
    target = getattr(getattr(node, "func", None), "obj", None)
    if (getattr(getattr(target, "cls", None), "py_obj", None) not in {builtins._str, builtins._bytes}
            or target.name not in PARAMETERS):
        return node
    parameter = PARAMETERS[target.name]
    position = next(index for index, item in enumerate(target.params) if item.arg == parameter)
    values = [*node.args[position:position + 1],
              *(keyword.value for keyword in node.keywords if keyword.arg == parameter)]
    node.runtime_protocols = (*getattr(node, "runtime_protocols", ()),
                             *((analyzed_value_type(value), ("__index__",)) for value in values))
    return node


def emit(e, target, receiver, node, *, binary):
    if expands_arguments(node):
        raise LLVMUnsupported("LLVM text editing requires statically bound arguments", node)
    # Builtin declarations have unanalyzed defaults (including unary -1).
    # Reuse the literal normalizer instead of duplicating default values here.
    defaults = {parameter.arg: persistent.literal(value, parameter.annotation.obj)
                for parameter, value in calls.parameter_defaults(target)}
    with calls.bind(e, target, node, load_default=lambda parameter: e.expression(defaults[parameter.arg])) as bound:
        # Binding evaluates all positional/keyword expressions in source order,
        # then supplies defaults. Only now may __index__ collect, mutate or raise.
        position = next(index for index, item in enumerate(target.params) if item.arg == PARAMETERS[target.name])
        sources = [source if source is not None else defaults[parameter.arg]
                   for parameter, source in zip(target.params, bound.sources, strict=True)]
        source = sources[position]
        count = indexing.integer(e, analyzed_value_type(source), *bound.values[position], node)
        if target.name == "expandtabs":
            e.guard_c_int(node, count)
        arguments = [tagged.untag_single_member(e, analyzed_value_type(source), *value, node)[1:]
                     for source, value in zip(sources, bound.values, strict=True)]
        arguments[position] = "i64", count
        normalized = ast.copy_location(ast.Call(func=node.func, args=sources, keywords=[]), node)
        if target.name in {"replace", "split", "rsplit"}:
            return e.string_edit_call(target.name, receiver, arguments, normalized, binary=binary)
        return e.text_extra_call(target.name, receiver, arguments, normalized, binary=binary)
