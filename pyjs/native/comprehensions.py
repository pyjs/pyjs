"""Native closure and iterator integration for shared comprehension IR."""

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.comprehensions import lower as lower_ir

from . import callables, calls, iterator_ops, tagged, unpacking
from .mapping_keys import retain


def lower(visitor, analyzed, source):
    return lower_ir(visitor, analyzed, source, retain=retain, unpack=unpacking.assign)


def expression(emitter, node):
    argument = emitter.expression(node.source)
    source = node.source
    if node.function.is_generator:
        # Capture the outer iterator before entering the factory. Keep the
        # original source in the IR so lifetime inference sees its retention.
        argument = "ptr", iterator_ops.create(emitter, analyzed_value_type(node.source), argument[1], node)
        source = tagged.Value(node.source, node.function.obj.parameter_types[0], *argument)
    _, callback = emitter.expression(node.function)
    return callables.invoke_values(emitter, callback, node.function.obj, calls.BoundCall([argument], [source]), node)
