"""Retained exception values and lazy checked message formatting."""

import ast

from pyjs.analysis.analyzer import (
    analyzed_value_type,
    get_type_members,
    runtime_dunder_methods,
)
from pyjs.analysis.ir import ExceptionRaise, ObjectNew, Return
from pyjs.analysis.objects import Class, Name
from pyjs.analysis.type_relations import is_return_type_compatible, is_subclass
from pyjs.analysis.value_representation import (
    analyzed_representation,
    representation_for_member,
)

from . import calls, collection_ops, erased_repr, nullable, object_values, tagged
from .analysis import NATIVE_ENVIRONMENT


def payload(e, node, *, completion=False):
    semantic = analyzed_value_type(node.message)
    kind, value = e.expression(node.message)
    semantic = tagged.effective_type(semantic, kind)
    representation = analyzed_representation(node.message)
    represented = "false"
    if completion and representation is not None and representation.direct_numeric_formats:
        def marker(member, storage, item):
            selected = representation_for_member(semantic, representation, member)
            return "true" if selected is not None and selected.direct_numeric_formats else "false"

        # Mark the actual return arm before boxing erases scalar arithmetic.
        # The exception snapshot transports this bit through arbitrary cursor
        # wrappers; reference/ordinary union arms keep their normal semantics.
        if kind == tagged.STORAGE:
            represented = tagged.dispatch(e, semantic, value, "i1", marker)
        elif nullable.member(semantic):
            represented = nullable.dispatch(e, semantic, kind, value, "i1", "false", marker)
        else:
            represented = "true"
    source = node.message if hasattr(node.message, "lineno") else node

    def box(member, storage, item):
        # Only scalar arithmetic is erased. A union's reference arm must keep
        # its represented contents and layout token (e.g. list[int8]).
        selected = representation_for_member(semantic, representation, member)
        if completion and selected is not None and selected.direct_numeric_formats:
            selected = None
        if storage == "float":
            storage, item = "double", e.emit_value(f"fpext float {item} to double")
        return object_values.convert(e, storage, item, NATIVE_ENVIRONMENT.builtins.search("object"),
                                     source, actual=member, representation=selected)[1]

    if kind == tagged.STORAGE:
        retained = tagged.dispatch(e, semantic, value, "ptr", box)
    elif nullable.member(semantic):
        retained = nullable.dispatch(e, semantic, kind, value, "ptr", "null", box)
    else:
        retained = box(semantic, kind, value)
    return retained, represented


def erased_payload(e, receiver, node, description):
    # Typed completion consumers recover their declared R. An object read has
    # no such witness: reject only the actual represented scalar arm, retaining
    # ordinary scalars and represented reference layouts in the same union.
    represented = e.emit_value(f"load i1, ptr {e.exception_field(6, receiver)}")
    valid = e.emit_value(f"xor i1 {represented}, true")
    e.guard_exception(node, valid, "TypeError", description)
    return e.emit_value(f"load ptr, ptr {e.exception_field(5, receiver)}")


def retains(value_type, message):
    """Keep mutable/custom messages lazy; scalar messages retain their fast path."""
    return message is not None and (
        is_subclass(value_type, NATIVE_ENVIRONMENT.builtins.search("StopIteration"))
        or any(collection_ops.builtin_name(member) not in {"str", "int", "bool", "float", "NoneType"}
               for member in get_type_members(analyzed_value_type(message))))


def retain_methods(node, value_type, message):
    if not retains(value_type, message):
        return
    from .representation import protocols
    quoted = is_subclass(value_type, NATIVE_ENVIRONMENT.builtins.search("KeyError"))
    dependencies = protocols(analyzed_value_type(message), quoted)
    node.runtime_methods = (*getattr(node, "runtime_methods", ()),
                            *(method for receiver, names in dependencies
                              for method in runtime_dunder_methods(receiver, *names)))
    node.runtime_protocols = (*getattr(node, "runtime_protocols", ()),
                             *dependencies)


def formats(functions):
    """Discover lazy str/repr consumers without retaining unused formatters."""
    stop = NATIVE_ENVIRONMENT.builtins.search("StopIteration")
    result = {}

    def add(quoted, message):
        result.setdefault(quoted, set()).add(analyzed_value_type(message))

    for function in functions:
        for node in object_values.nodes((function,)):
            if ((function.is_generator or function.is_async) and isinstance(node, Return) and node.value is not None
                    and not (isinstance(node.value, ast.Constant) and node.value.value is None)):
                add(False, node.value)
            value_type = (node.value_type if isinstance(node, (ExceptionRaise, ObjectNew)) else
                          getattr(getattr(node, "func", None), "obj", None))
            message = (node.message if isinstance(node, ExceptionRaise) else
                       node.call.args[0] if isinstance(node, ObjectNew) and node.call.args else
                       node.args[0] if isinstance(node, ast.Call) and node.args else None)
            if (isinstance(value_type, Class)
                    and is_subclass(value_type, NATIVE_ENVIRONMENT.builtins.search("BaseException"))
                    and retains(value_type, message)):
                add(is_subclass(value_type, NATIVE_ENVIRONMENT.builtins.search("KeyError")), message)
            elif isinstance(value_type, Class) and is_subclass(value_type, stop):
                result.setdefault(False, set()).add(NATIVE_ENVIRONMENT.builtins.search("NoneType"))
    return result


def text(e, receiver, node):
    if not e.module.uses_exception_values:
        return e.emit_value(f"load ptr, ptr {e.exception_field(3, receiver)}")
    arguments = ", ".join([*(f"{kind} {value}" for kind, value in e.context_arguments()), f"ptr {receiver}"])
    result = e.emit_value(f"call ptr @pyjs.exception.text({arguments})")
    e.check_active_exception(node)
    return result


def definition(owner):
    if not owner.module.uses_exception_values:
        return []
    from .llvm import FunctionEmitter
    e = FunctionEmitter(owner.module)
    e.stack_allocations = []
    e.return_type = e.return_storage_type = "ptr"
    node = ast.Call(func=Name(NATIVE_ENVIRONMENT.builtins.search("str")), args=[], keywords=[])
    e.allocation_node = node
    parameters = ("__arena", "__heap", "__exception")
    for name in parameters:
        e.slots[name], e.slot_types[name] = f"%slot.{name}", "ptr"
        e.emit_line(f"%slot.{name} = alloca ptr")
        e.emit_line(f"store ptr %{name}, ptr %slot.{name}")
    value = e.emit_value(f"load ptr, ptr {e.exception_field(5, '%receiver')}")
    e.gc_frame = calls.root_values(e, "%receiver", value)
    message = e.emit_value(f"load ptr, ptr {e.exception_field(3, '%receiver')}")
    lazy = e.emit_value(f"icmp eq ptr {message}, null")
    e.emit_line(f"br i1 {lazy}, label %render, label %stored")
    e.emit_line("stored:")
    calls.pop_roots(e, e.gc_frame)
    e.emit_line(f"ret ptr {message}")
    e.emit_line("render:")
    # A null message denotes a supplied payload, including None. An omitted
    # argument instead has the ordinary non-null empty message. Never cache:
    # Python re-renders mutable payloads and repeats custom __str__ calls.
    # KeyError uses repr even for an application object; all other supported
    # single-message exceptions use str. Dispatch on the exception token, not
    # the payload's class, so borrowed/reraised snapshots preserve this choice.
    formats = sorted(owner.module.exception_formats)
    if len(formats) == 2:
        token = e.emit_value(f"load ptr, ptr {e.exception_field(1, '%receiver')}")
        quoted = e.exception_matches(token, (NATIVE_ENVIRONMENT.builtins.search("KeyError"),))
        e.emit_line(f"br i1 {quoted}, label %quoted, label %unquoted")
    else:
        e.emit_line(f"br label %{'quoted' if formats[0] else 'unquoted'}")
    for quoted in formats:
        label = "quoted" if quoted else "unquoted"
        e.emit_line(f"{label}:")
        domains = owner.module.exception_formats[quoted]
        candidates = tuple((semantic, represented) for semantic, represented in e.module.erased_candidates
                           if any(is_return_type_compatible(domain, semantic) for domain in domains))

        def render(semantic, represented, storage, payload, quoted=quoted):
            if storage == "void":
                return "@" + e.string_constant("None")
            return erased_repr.call(e, semantic, storage, payload, quoted, node)

        # The box ABI is shared, but unrelated payloads must not pull in this
        # mode's methods. Recursive object edges keep their normal broad dispatch.
        rendered = object_values.dispatch(e, value, "ptr", node, render,
                                           description="exception formatting", candidates=candidates)
        calls.pop_roots(e, e.gc_frame)
        e.emit_line(f"ret ptr {rendered}")
    e.emit_line("pyjs.exception.return:")
    e.restore_gc_frame()
    calls.pop_roots(e, e.gc_frame)
    e.emit_line("ret ptr null")
    signature = ", ".join([*(f"ptr %{name}" for name in parameters), "ptr %receiver"])
    return [f"define private ptr @pyjs.exception.text({signature}) {{", "entry:",
            *(f"  {line}" for line in (*e.stack_allocations, *e.lines)), "}"]
