"""Decode object-valued builder arguments after all boxing layouts are known."""

from . import calls, collection_ops, dom_ops, object_values


def call(e, arguments, value, node, receiver, target, *, children_only=False):
    # The enclosing builder retains all evaluated arguments. One outlined
    # decoder per receiver contract avoids emission-order-dependent type sets.
    contract = receiver, children_only
    if contract not in e.module.erased_dom_builders:
        e.module.erased_dom_builders[contract] = f"pyjs.dom.argument.{len(e.module.erased_dom_builders)}", node
    symbol, _ = e.module.erased_dom_builders[contract]
    values = [*e.context_arguments(), ("ptr", arguments), ("ptr", value), ("ptr", target or "null")]
    e.emit_line(f"call void @{symbol}({', '.join(f'{kind} {item}' for kind, item in values)})")
    e.check_active_exception(node)


def definitions(parent):
    return [line for contract in parent.module.erased_dom_builders for line in definition(parent, contract)]


def definition(parent, contract):
    from .llvm import FunctionEmitter

    receiver, children_only = contract
    symbol, node = parent.module.erased_dom_builders[contract]
    e = FunctionEmitter(parent.module)
    e.stack_allocations = []
    e.allocation_node = node
    e.return_type = e.return_storage_type = "void"
    parameters = [name for name, enabled in (("__arena", e.module.uses_arena),
                  ("__heap", e.module.uses_gc), ("__exception", e.module.uses_exceptions)) if enabled]
    for name in parameters:
        e.slots[name], e.slot_types[name] = f"%slot.{name}", "ptr"
        e.emit_line(f"%slot.{name} = alloca ptr")
        e.emit_line(f"store ptr %{name}, ptr %slot.{name}")
    if e.module.uses_gc:
        e.gc_frame = calls.root_values(e, "%value")
    target = "%target" if receiver is not None else None
    pending = (target, "%arguments") if target is not None else None

    def invalid():
        # The CPython DOM append body ignores values other than Node/str;
        # domx builders instead reject unknown children/attributes. Share the
        # layout decoder, not those intentionally different body contracts.
        if not children_only:
            dom_ops.guard_argument(e, node, "false", "TypeError", "", pending)

    def append(semantic, represented, kind, value):
        name = collection_ops.builtin_name(semantic)
        valid = (name == "str" or dom_ops.is_element(e, semantic)
                 or not children_only and e.is_proxy_element_type(semantic))
        if name == "dict" and not children_only:
            valid = all(collection_ops.builtin_name(item) == "str" for item in e.dictionary_types(semantic))
        if not valid:
            invalid()
            return
        dom_ops.append(e, "%arguments", semantic, kind, value, node,
                       builder_receiver=receiver, builder_target=target)

    object_values.dispatch(e, "%value", "void", node, append, description="DOM argument", on_unsupported=invalid)
    calls.pop_roots(e, e.gc_frame)
    e.emit_line("ret void")
    if e.module.uses_exceptions:
        e.emit_line("pyjs.exception.return:")
        e.restore_gc_frame()
        calls.pop_roots(e, e.gc_frame)
        e.emit_line("ret void")
    signature = ", ".join([*(f"ptr %{name}" for name in parameters),
                           "ptr %arguments", "ptr %value", "ptr %target"])
    return [f"define private void @{symbol}({signature}) {{", "entry:",
            *(f"  {line}" for line in (*e.stack_allocations, *e.lines)), "}"]
