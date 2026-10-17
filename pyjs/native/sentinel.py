"""Callable-sentinel iteration through the ordinary callback and equality ABI."""

from pyjs.analysis.analyzer import analyzed_value_type

from . import callback_ops, calls, comparisons, iterator_callbacks, iterator_ops
from .analysis import NATIVE_ENVIRONMENT
from .runtime import iteration as runtime


def create(emitter, node):
    _, callback = emitter.expression(node.args[0])
    kind, sentinel = emitter.expression(node.args[1])
    member = analyzed_value_type(node.args[1])
    kind, sentinel = emitter.coerce_value(kind, sentinel, emitter.value_type(member), node, semantic=member)
    # Allocate and root the payload before allocating the iterator handle.
    # Semantic values use widened storage in the same way as callback frames.
    root = calls.root_values(emitter, callback, *([sentinel] if kind == "ptr" else []))
    values = iterator_ops.array(emitter, [("ptr", callback), (kind, sentinel)])
    payload_root = calls.root_values(emitter, values)
    state = iterator_ops.new(emitter, runtime.CALLBACK, values)
    iterator_ops.store(emitter, state, runtime.ADVANCE, "ptr",
                       "@" + emitter.function_name(emitter.module.iterator_steps[node]))
    calls.pop_roots(emitter, payload_root)
    calls.pop_roots(emitter, root)
    return "ptr", state


def advance(emitter, node):
    source = node.source
    contract = callback_ops.signature(source.args[0], 0)
    member = analyzed_value_type(source.args[1])
    kind = emitter.value_type(member)
    state, output = emitter.load_local("state"), emitter.load_local("output")
    payload = iterator_callbacks.load(emitter, state, runtime.SOURCE)
    callback = iterator_callbacks.load(emitter, payload, 0)
    sentinel = iterator_callbacks.load(emitter, payload, 8, kind)
    # A recursive pull can finish the handle and clear its payload while this
    # invocation still needs the callback and sentinel.
    (slot, callback_slot, sentinel_slot), frame = calls.value_slots(emitter, [kind, "ptr", kind])
    emitter.emit_line(f"store ptr {callback}, ptr {callback_slot}")
    emitter.emit_line(f"store {kind} {sentinel}, ptr {sentinel_slot}")
    result = emitter.emit_value("alloca i64")
    emitter.emit_line(f"store i64 0, ptr {result}")
    error, stop, done = (emitter.new_label(name) for name in ("sentinel.error", "sentinel.stop", "sentinel.done"))
    outer = emitter.exception_target
    emitter.exception_target = error
    try:
        _, value = callback_ops.invoke(emitter, callback, contract, [], source)
        emitter.emit_line(f"store {kind} {value}, ptr {slot}")
        # A recursive callback can exhaust this same handle. CPython discards
        # the outer result in that case and does not call sentinel equality.
        exhausted = iterator_callbacks.load(emitter, state, runtime.EXHAUSTED, "i64")
        active = emitter.emit_value(f"icmp eq i64 {exhausted}, 0")
        compare = emitter.new_label("sentinel.compare")
        emitter.emit_line(f"br i1 {active}, label %{compare}, label %{done}")
        emitter.emit_line(f"{compare}:")
        equality_error = emitter.new_label("sentinel.equality.error")
        emitter.exception_target = equality_error
        # CPython compares sentinel == value (including its identity shortcut),
        # not value == sentinel: callbacks can observe operand order.
        matched = comparisons.equal_value(emitter, member, sentinel, member, value, source)
    finally:
        emitter.exception_target = outer
    ready = emitter.new_label("sentinel.item")
    emitter.emit_line(f"br i1 {matched}, label %{stop}, label %{ready}")
    emitter.emit_line(f"{ready}:")
    emitter.emit_line(f"store {kind} {value}, ptr {output}")
    emitter.emit_line(f"store i64 1, ptr {result}")
    emitter.emit_line(f"br label %{done}")
    # Equality's StopIteration ends this attempt but does not exhaust the
    # callable; only the callable's own StopIteration does that permanently.
    iterator_callbacks.callback_failure(emitter, equality_error, frame)
    emitter.emit_line(f"{emitter.name(error, 'block')}:")
    calls.restore_roots(emitter, frame)
    token = emitter.emit_value(f"load ptr, ptr {emitter.exception_field(1)}")
    stopped = emitter.exception_matches(token, (NATIVE_ENVIRONMENT.builtins.search("StopIteration"),))
    failed = emitter.new_label("sentinel.failed")
    emitter.emit_line(f"br i1 {stopped}, label %{stop}, label %{failed}")
    emitter.emit_line(f"{failed}:")
    calls.pop_roots(emitter, frame)
    emitter.branch_to_exception_target()
    emitter.emit_line(f"{stop}:")
    emitter.emit_line(f"store i1 false, ptr {emitter.exception_field(0)}")
    emitter.emit_line(f"call i64 @pyjs.iterator.finish(ptr {state})")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    calls.pop_roots(emitter, frame)
    return "i64", emitter.emit_value(f"load i64, ptr {result}")
