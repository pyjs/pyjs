"""Optional control targets the acquired cursor, not its iterable factory."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.objects import Function

from . import (
    calls,
    exception_values,
    generators,
    iterator_callbacks,
    iterator_views,
    protocols,
)
from .errors import LLVMUnsupported
from .runtime import iteration as runtime


def completion(e, node):
    _, error = e.expression(node.args[0])
    # Inspect the caught snapshot, not the active exception or the outer cursor:
    # handler entry clears active state and wrappers may forward another
    # generator's completion. Typed capture and discarded results skip this.
    value = exception_values.erased_payload(e, error, node,
        "erased delegation cannot expose represented scalar completion; use a concrete Generator")
    return "ptr", value


def close(e, node):
    _, view = e.expression(node.args[0])
    frame = calls.root_values(e, view)
    state = iterator_views.control(e, view)
    kind = iterator_callbacks.load(e, state, 0, "i64")
    generator, application, done = (e.new_label("delegate.close." + name)
                                    for name in ("generator", "application", "done"))
    e.emit_line(f"switch i64 {kind}, label %{done} [i64 {runtime.GENERATOR}, label %{generator} "
                f"i64 {runtime.APPLICATION}, label %{application}]")
    e.emit_line(f"{generator}:")
    generators.close(e, state, None, node, discard=True)
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{application}:")
    source = iterator_callbacks.load(e, state, runtime.SOURCE)

    def select(cls):
        target = cls.find_attrs("close")
        if target is not None and (not isinstance(target, Function) or target.is_property
                                   or target.is_static or target.is_classmethod):
            raise LLVMUnsupported("native delegated close requires an ordinary instance method", node)
        return target

    def invoke(target):
        if target is not None:
            # Select first, then bind that method's own defaults; close results
            # are intentionally discarded without a common return ABI.
            with calls.bind(e, target, node, positional=[]) as arguments:
                calls.invoke(e, target, arguments, node, receiver=source)

    calls.runtime_protocol(e, analyzed_value_type(node.args[0]), source, "void", select, invoke,
                           node, compatible=lambda cls, target: cls in e.module.application_iterators
                           and protocols.compatible_source(e, cls, target),
                           fallback=lambda: None)
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    calls.pop_roots(e, frame)
    return "void", ""


def throw(e, node):
    _, view = e.expression(node.args[0])
    frame = calls.root_values(e, view)
    state = iterator_views.control(e, view)
    tag = iterator_callbacks.load(e, state, 0, "i64")
    is_generator = e.emit_value(f"icmp eq i64 {tag}, {runtime.GENERATOR}")
    generator, other, done = (e.new_label("delegate.throw." + name)
                              for name in ("generator", "other", "done"))
    kind = e.value_type(analyzed_value_type(node))
    result = e.emit_value(f"alloca {kind}") if kind != "void" else None
    forwarded = ast.copy_location(ast.Call(func=node.func, args=node.args[1:], keywords=[]), node)
    e.emit_line(f"br i1 {is_generator}, label %{generator}, label %{other}")
    e.emit_line(f"{generator}:")
    _, value = generators.throw(e, view, analyzed_value_type(node.args[0]), forwarded)
    if result is not None:
        e.emit_line(f"store {kind} {value}, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{other}:")
    # Application exception arguments are still borrowed snapshots, not
    # general first-class values. Never silently skip an authored throw method.
    for cls in e.module.application_iterators:
        if (protocols.compatible_source(e, cls, analyzed_value_type(node.args[0]))
                and cls.find_attrs("throw") is not None):
            raise LLVMUnsupported("native application delegate throw methods require first-class exceptions", node)
    raised = generators.thrown_exception(forwarded)
    e.activate_exception(raised, e.exception_payload(raised), include_frame=False)
    e.branch_to_exception_target()
    e.emit_line(f"{done}:")
    calls.pop_roots(e, frame)
    return kind, e.emit_value(f"load {kind}, ptr {result}") if result is not None else ""
