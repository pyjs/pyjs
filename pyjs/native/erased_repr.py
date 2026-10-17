"""Outline erased and recursive formatting edges with the concrete formatter.

A list[object] may contain itself. Emitting its formatter inline at every object
edge would recurse in the compiler; checked helpers make that recursion runtime
recursion, using the existing arena reentry stack and output-buffer cleanup.
"""

from pyjs.analysis.objects import RecursiveTypeAlias, specialization_cache_key

from . import calls, format_ops, nullable, object_values, representation, tagged
from .analysis import NATIVE_ENVIRONMENT


def call(e, semantic, kind, value, quoted, node, *, spec=None, output=None, standalone=False):
    if spec is None and output is None and not standalone:
        buffer = representation.Buffer(e, node)
        roots = (value,) if kind == "ptr" else ()
        return buffer.render(lambda: call(e, semantic, kind, value, quoted, node, output=buffer.output), *roots)
    if not standalone and nullable.is_object(semantic):
        semantic = NATIVE_ENVIRONMENT.builtins.search("object")
    # Narrowed tagged ints synthesize equivalent int|bool types at each site.
    # Reuse the analysis specialization key: unions share equivalent edges,
    # but concrete classes/containers retain their exact model identity. Keep
    # the incoming ABI too, plus a representative type for the helper body.
    key = specialization_cache_key(semantic), kind, quoted, spec, standalone
    if key not in e.module.erased_formatters:
        e.module.erased_formatters[key] = f"pyjs.object.format.{len(e.module.erased_formatters)}", node, semantic
    symbol, _, _ = e.module.erased_formatters[key]
    arguments = [*e.context_arguments(), (kind, value)]
    if output is not None:
        arguments.append(("ptr", output))
    actual = ", ".join(f"{storage} {item}" for storage, item in arguments)
    if spec is None and not standalone:
        e.emit_line(f"call void @{symbol}({actual})")
        result = None
    else:
        result = e.emit_value(f"call ptr @{symbol}({actual})")
    e.check_active_exception(node)
    return result


def dispatch(e, value, quoted, node, spec, output):
    def render(semantic, represented, storage, payload):
        if object_values.runtime_name(semantic) == "dom":
            # DOM boxing enables transport, not a Python object-repr model.
            # An unrelated boxed DOM must not prevent formatting other values.
            e.guard_exception(node, "false", "TypeError", "unsupported erased formatting layout")
            return "null" if spec is not None else None
        if storage == "void":
            if spec:
                e.guard_exception(node, "false", "TypeError", "unsupported format string passed to NoneType.__format__")
            if spec is not None:
                return "@" + e.string_constant("None")
            representation.Buffer(e, node, output=output).append("@" + e.string_constant("None"))
            return None
        return call(e, semantic, storage, payload, quoted, node, spec=spec, output=output)

    return object_values.dispatch(e, value, "ptr" if spec is not None else "void", node, render,
                                  description="formatting")


def definitions(parent):
    from .llvm import FunctionEmitter

    output, emitted = [], set()
    # All authored bodies have registered their boxing layouts. Outlining a
    # concrete container may discover another object edge, but no new layout.
    while pending := [key for key in parent.module.erased_formatters if key not in emitted]:
        for key in pending:
            emitted.add(key)
            _, kind, quoted, spec, standalone = key
            symbol, node, semantic = parent.module.erased_formatters[key]
            e = FunctionEmitter(parent.module)
            e.stack_allocations = []
            e.allocation_node = node
            returns_text = standalone or spec is not None
            e.return_type = e.return_storage_type = "ptr" if returns_text else "void"
            # Container edges borrow their caller's output. Only the outer
            # render finishes/destroys it, avoiding quadratic intermediate text
            # copies for deeply nested heterogeneous containers.
            # Standalone roots return text (possibly an existing scalar string),
            # while nested edges borrow their caller's buffer as before.
            output_buffer = None if returns_text else "%output"
            parameters = [name for name, enabled in (("__arena", e.module.uses_arena),
                          ("__heap", e.module.uses_gc), ("__exception", e.module.uses_exceptions)) if enabled]
            for name in parameters:
                e.slots[name], e.slot_types[name] = f"%slot.{name}", "ptr"
                e.emit_line(f"%slot.{name} = alloca ptr")
                e.emit_line(f"store ptr %{name}, ptr %slot.{name}")
            if e.module.uses_gc:
                slots, e.gc_frame = calls.value_slots(e, [kind])
                e.emit_line(f"store {kind} %value, ptr {slots[0]}")
            if standalone:
                _, value = representation.render(e, semantic, kind, "%value", node,
                                                  representation=quoted, outline=False)
            elif nullable.is_object(semantic):
                value = dispatch(e, "%value", quoted, node, spec, output_buffer)
            elif spec is not None:
                value = format_ops.format_value(e, semantic, kind, "%value", "@" + e.string_constant(spec), spec, node)
            else:
                # Expand the root once. Nested unions (including normalized
                # optional edges) register/reuse helpers, bounding code size.
                target, storage, value = tagged.untag_single_member(e, semantic, kind, "%value", node)
                target = target.target if isinstance(target, RecursiveTypeAlias) else target
                representation.Formatter(e, node, output=output_buffer).value(target, storage, value, quoted, outline=False)
            calls.pop_roots(e, e.gc_frame)
            e.emit_line(f"ret ptr {value}" if returns_text else "ret void")
            if e.module.uses_exceptions:
                e.emit_line("pyjs.exception.return:")
                e.restore_gc_frame()
                calls.pop_roots(e, e.gc_frame)
                e.emit_line("ret ptr null" if returns_text else "ret void")
            signature = ", ".join([*(f"ptr %{name}" for name in parameters), f"{kind} %value",
                                    *([] if returns_text else ["ptr %output"])])
            output.extend([f"define private {e.return_type} @{symbol}({signature}) {{", "entry:",
                           *(f"  {line}" for line in (*e.stack_allocations, *e.lines)), "}"])
    return output
