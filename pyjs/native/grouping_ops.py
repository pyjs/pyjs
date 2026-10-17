"""Typed key/equality calls for the Python-authored grouping state machine."""

from pyjs.analysis.analyzer import analyzed_value_type

from . import (
    callback_ops,
    calls,
    collection_ops,
    comparisons,
    gc_layouts,
    iterator_callbacks,
    iterator_ops,
    tagged,
)
from .runtime import iteration as runtime


def arguments(node):
    return dict(zip(("iterable", "key"), node.args, strict=False)) | {value.arg: value.value for value in node.keywords}


def create(emitter, node):
    named = arguments(node)
    values = {value: emitter.expression(value) for value in [*node.args, *(value.value for value in node.keywords)]}
    row = collection_ops.item_type(analyzed_value_type(node))
    key, cursor = row.generic_types.values()
    member = collection_ops.item_type(cursor)
    item_kind, key_kind = emitter.value_type(member), emitter.value_type(key)
    codes = [runtime.GROUP_TAGGED if kind == tagged.STORAGE else
             runtime.GROUP_REFERENCE if kind == "ptr" else runtime.GROUP_SCALAR
             for kind in (item_kind, key_kind)]
    layout = codes[0] | (codes[1] << runtime.GROUP_KEY_SHIFT)
    key_allocator = gc_layouts.item_allocator(key_kind) if emitter.module.uses_gc else "null"
    source = iterator_ops.create(emitter, analyzed_value_type(named["iterable"]), values[named["iterable"]][1], node)
    state = emitter.allocated_value(
        f"call ptr @pyjs.iterator.group.typed({collection_ops.owner(emitter)}, ptr {source}, "
        f"i64 {emitter.llvm_size(item_kind)}, i64 {emitter.llvm_size(key_kind)}, ptr {key_allocator}, i64 {layout})")
    offsets = iterator_ops.row_layout(emitter, state, row)
    iterator_ops.store(emitter, state, runtime.STRICT, "i64", offsets[1])
    key_value = values[named["key"]] if "key" in named else ("void", "")
    iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", key_value[1] if key_value[0] != "void" else "null")
    for offset, helper in ((runtime.ADVANCE, node), (runtime.OFFSETS, (node, "equal"))):
        iterator_ops.store(emitter, state, offset, "ptr", "@" + emitter.function_name(emitter.module.iterator_steps[helper]))
    return "ptr", state


def callback(emitter, node):
    source = node.source
    named = arguments(source)
    row = collection_ops.item_type(analyzed_value_type(source))
    key, cursor = row.generic_types.values()
    member = collection_ops.item_type(cursor)
    state, output = emitter.load_local("state"), emitter.load_local("output")
    outcome = emitter.emit_value("alloca i64")
    emitter.emit_line(f"store i64 0, ptr {outcome}")
    kinds = [emitter.value_type(key)] * 2 if node.comparison else [emitter.value_type(member)]
    slots, frame = calls.value_slots(emitter, kinds)
    addresses = [state, output] if node.comparison else [output]
    values = []
    for kind, slot, address in zip(kinds, slots, addresses, strict=True):
        value = emitter.emit_value(f"load {kind}, ptr {address}")
        emitter.emit_line(f"store {kind} {value}, ptr {slot}")
        values.append(value)
    error, done = emitter.new_label("group.callback.error"), emitter.new_label("group.callback.done")
    outer = emitter.exception_target
    emitter.exception_target = error
    try:
        if node.comparison:
            equal = comparisons.equal_value(emitter, key, values[0], key, values[1], source)
            # Positive statuses distinguish unequal/equal results. Callback
            # failures retain their exception and return a negative status.
            result = emitter.emit_value(f"select i1 {equal}, i64 2, i64 1")
        else:
            key_node = named.get("key")
            if key_node is None or analyzed_value_type(key_node).generic_name == "NoneType":
                kind, value = kinds[0], values[0]
                emitter.value_semantics[kind, value] = member
            else:
                contract = callback_ops.signature(key_node, 1)
                callback = iterator_callbacks.load(emitter, state, runtime.CALLBACK_VALUE)
                kind, value = callback_ops.invoke(emitter, callback, contract, [(member, values[0])], source)
            kind, value = emitter.coerce_value(kind, value, emitter.value_type(key), source, semantic=key)
            data = iterator_callbacks.load(emitter, state, runtime.CHILDREN)
            stride = emitter.emit_value(f"load i64, ptr {data}")
            iterator_ops.store(emitter, output, stride, kind, value)
            result = "1"
    finally:
        emitter.exception_target = outer
    emitter.emit_line(f"store i64 {result}, ptr {outcome}")
    emitter.emit_line(f"br label %{done}")
    iterator_callbacks.callback_failure(emitter, error, frame)
    emitter.emit_line(f"{done}:")
    calls.pop_roots(emitter, frame)
    return "i64", emitter.emit_value(f"load i64, ptr {outcome}")
