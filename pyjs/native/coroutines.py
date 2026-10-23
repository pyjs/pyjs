"""Coroutine call signatures and views over managed suspension frames."""

from pyjs.analysis.objects import Function
from pyjs.analysis.value_representation import compound_representation

from .analysis import NATIVE_ENVIRONMENT


def result_type(function):
    result = function.return_type
    if isinstance(function, Function) and function.is_async:
        return NATIVE_ENVIRONMENT.builtins.search("Awaitable")(result)
    return result


def result_representation(function):
    result = function.return_representation
    if isinstance(function, Function) and function.is_async:
        return compound_representation(arguments=(result,))
    return result


def result_numeric(function):
    return None if isinstance(function, Function) and function.is_async else function.return_numeric_format


def cursor_type(awaitable):
    builtins = NATIVE_ENVIRONMENT.builtins
    object_type = builtins.search("object")
    return builtins.search("Generator")(object_type, object_type, awaitable.generic_types["T"])


def acquire(emitter, value, awaitable, node):
    from . import iterator_ops, iterator_views
    from .runtime import iteration

    cursor = cursor_type(awaitable)
    if getattr(node, "native_coroutine_await", False):
        position = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, value, iteration.INDEX)}")
        exhausted = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, value, iteration.EXHAUSTED)}")
        fresh = emitter.emit_value(f"icmp eq i64 {position}, 0")
        closed = emitter.emit_value(f"icmp ne i64 {exhausted}, 0")
        emitter.guard_exception(node, emitter.emit_value(f"or i1 {fresh}, {closed}"),
                                "RuntimeError", "coroutine is being awaited already")
    # Each __await__ call produces its own iterator object. The view forwards
    # send/throw/close to the same coroutine frame and owns that frame through
    # the normal managed iterator source edge.
    return "ptr", iterator_views.wrap(emitter, cursor, cursor, value, node, kind=iteration.AWAIT_ITERATOR)
