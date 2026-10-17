"""Attribute-backed scalar state; no second copy in application field slots."""

import ast
import struct

from pyjs.state import StateField
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement

from . import calls, collection_ops, dom_ops, tagged
from .errors import LLVMUnsupported


def fields(semantic):
    return getattr(semantic.py_obj, "__pyjs_state_fields__", {})


def field(e, semantic, name):
    return fields(semantic).get(name) if semantic in e.module.custom_element_types else None


def has_callbacks(python_type, *, allow_effects=False, attribute_name=None):
    """Whether this call path would skip unsupported observation work."""
    state = getattr(python_type, "__pyjs_state_fields__", {})
    effects = getattr(python_type, "__pyjs_state_effects__", {})
    observed_effect = any(name in effects and (attribute_name is None or item.attribute_name == attribute_name)
                          for name, item in state.items())
    return (python_type._is_observed_attribute is not Element._is_observed_attribute
            or bool(python_type.observedAttributes) and (
                not state or observed_effect and not allow_effects
                or python_type.observedAttributes != [item.attribute_name for item in state.values()]
                or python_type.attributeChangedCallback is not CustomElement.attributeChangedCallback
                or python_type._notify_state_change is not CustomElement._notify_state_change))


def validate(e, semantic):
    state = fields(semantic)
    if not state:
        return
    python_type = semantic.py_obj
    if any(type(item) is not StateField for item in state.values()):
        raise LLVMUnsupported("LLVM state requires standard StateField descriptors", semantic.annotation)
    if (python_type.__pyjs_state_effects__
            and python_type._run_initial_effects is not CustomElement._run_initial_effects):
        raise LLVMUnsupported("LLVM custom initial-effect hooks are not implemented", semantic.annotation)
    reserved = {"_initialized", "__pyjs_ref__"}
    if (reserved.intersection(python_type.__dict__)
            or any(item.name in reserved for item in e.module.classes[semantic].fields)):
        raise LLVMUnsupported("LLVM state classes cannot redefine framework initialization or reference fields", semantic.annotation)
    if (python_type.__setattr__ is not CustomElement.__setattr__
            or python_type.__getattribute__ is not CustomElement.__getattribute__):
        raise LLVMUnsupported("LLVM state does not support custom attribute access hooks", semantic.annotation)
    if any(getattr(python_type, name) is not item for name, item in state.items()):
        raise LLVMUnsupported("LLVM state descriptors cannot be shadowed by other class attributes", semantic.annotation)
    if any(item.value_type is int and not -9223372036854775808 <= item.default <= 9223372036854775807
           for item in state.values()):
        raise LLVMUnsupported("LLVM state integer default is outside native signed i64 range", semantic.annotation)
    for base in python_type.__mro__[1:]:
        if any(name in state and state[name] is not item
               for name, item in getattr(base, "__pyjs_state_fields__", {}).items()):
            raise LLVMUnsupported("LLVM state descriptor overrides are not implemented", semantic.annotation)
    base = e.module.classes[semantic].base
    while base in e.module.classes:
        layout = e.module.classes[base]
        ordinary = {item.name for item in layout.fields if item.name not in fields(base)}
        ordinary.update(name for name in base.py_obj.__dict__ if name not in fields(base))
        if ordinary.intersection(reserved):
            raise LLVMUnsupported("LLVM state classes cannot redefine framework initialization or reference fields", semantic.annotation)
        if ordinary.intersection(state):
            raise LLVMUnsupported("LLVM state cannot replace ordinary application members", semantic.annotation)
        base = layout.base
    for operation in ("getAttribute", "hasAttribute", "setAttribute", "removeAttribute"):
        dom_ops.check_dispatch(e, semantic, operation, semantic.annotation, allow_effects=True)


def has_effects(e, semantic):
    return semantic in e.module.custom_element_types and any(
        member.py_obj.__pyjs_state_effects__ for member in e.module.custom_element_types
        if collection_ops.is_layout_subclass(member, semantic))


def run_effects(e, semantic, receiver, node, attribute_name=None, *, known_name=None):
    """Group concrete classes by their callbacks, using ordinary checked calls."""
    if not has_effects(e, semantic):
        return

    def select(candidate):
        state = fields(candidate)
        groups = candidate.py_obj.__pyjs_state_effects__
        if attribute_name is None:
            names = tuple(dict.fromkeys(name for group in groups.values() for name in group))
            groups = {None: names}
        return tuple((state[name].attribute_name if name is not None else None,
                      tuple(e.resolve_method(candidate, method) for method in names))
                     for name, names in groups.items()
                     if known_name is None or state[name].attribute_name == known_name)

    def invoke(groups):
        for name, methods in groups:
            # State writes and literal attribute calls already identify the
            # field; do not emit every field's callbacks at every write site.
            dynamic = name is not None and known_name is None
            if dynamic:
                matched = e.emit_value(f"call i1 @pyjs.string.equal(ptr {attribute_name}, ptr @{e.string_constant(name)})")
                run, following = e.new_label("state.effect"), e.new_label("state.next.effect")
                e.emit_line(f"br i1 {matched}, label %{run}, label %{following}")
                e.emit_line(f"{run}:")
            for target in methods:
                if target not in e.module.functions or target.is_classmethod:
                    raise LLVMUnsupported("LLVM state effects require reached ordinary methods", node)
                call = ast.copy_location(ast.Call(func=ast.Name(id=target.name), args=[], keywords=[]), node)
                with calls.bind(e, target, call) as bound:
                    calls.invoke(e, target, bound, node, receiver=receiver)
            if dynamic:
                e.emit_line(f"br label %{following}")
                e.emit_line(f"{following}:")
        return "true"  # runtime_protocol joins a value, not a void expression.

    # A callback may collect or release the caller's last application reference.
    # set_data also creates a managed attribute name outside the normal AST
    # expression-root path; later dispatch cases still need that name.
    pointers = [receiver] if attribute_name is None else [receiver, attribute_name]
    frame = calls.root_values(e, *pointers)
    with calls.BoundCall([], [], e, frame):
        # Analyzer covariance relates Panel[bool] to Panel[int], but those
        # independent specializations do not share an identity/layout header.
        calls.runtime_protocol(e, semantic, receiver, "i1", select, invoke, node,
                               compatible=collection_ops.is_layout_subclass)


def notify(e, semantic, receiver, name, old, new, node, *, known_name=None):
    if not has_effects(e, semantic):
        return
    phase = e.emit_value(f"load i64, ptr {dom_ops.slot(e, semantic, receiver, 1)}")
    ready = e.emit_value(f"icmp eq i64 {phase}, 2")
    distinct = e.emit_value(f"icmp ne ptr {old}, {new}")
    ready = e.emit_value(f"and i1 {ready}, {distinct}")
    compare, text, changed, done = (e.new_label(f"state.{part}") for part in ("compare", "text", "changed", "notified"))
    e.emit_line(f"br i1 {ready}, label %{compare}, label %{done}")
    e.emit_line(f"{compare}:")
    old_present = e.emit_value(f"icmp ne ptr {old}, null")
    new_present = e.emit_value(f"icmp ne ptr {new}, null")
    both = e.emit_value(f"and i1 {old_present}, {new_present}")
    e.emit_line(f"br i1 {both}, label %{text}, label %{changed}")
    e.emit_line(f"{text}:")
    equal = e.emit_value(f"call i1 @pyjs.string.equal(ptr {old}, ptr {new})")
    e.emit_line(f"br i1 {equal}, label %{done}, label %{changed}")
    e.emit_line(f"{changed}:")
    run_effects(e, semantic, receiver, node, name, known_name=known_name)
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")


def attribute(e, semantic, receiver, descriptor):
    element = dom_ops.pointer(e, semantic, receiver)
    arguments = e.native_element_arguments(element)
    name = f"@{e.string_constant(descriptor.attribute_name)}"
    value = e.emit_value(f"call ptr @pyjs.native.attribute.get(ptr {arguments}, ptr {name})")
    return element, name, value


def read(e, semantic, receiver, descriptor, node):
    _, _, value = attribute(e, semantic, receiver, descriptor)
    present = e.emit_value(f"icmp ne ptr {value}, null")
    if descriptor.value_type is bool:
        return "i1", present
    if descriptor.value_type is str:
        default = f"@{e.string_constant(descriptor.default)}"
        return "ptr", e.emit_value(f"select i1 {present}, ptr {value}, ptr {default}")
    floating = descriptor.value_type is float
    kind = "double" if floating else "i64"
    default = (f"0x{struct.pack('>d', descriptor.default).hex().upper()}" if floating
               else str(descriptor.default))
    result = e.emit_value(f"alloca {kind}")
    e.emit_line(f"store {kind} {default}, ptr {result}")
    parse, done = e.new_label("state.parse"), e.new_label("state.read")
    e.emit_line(f"br i1 {present}, label %{parse}, label %{done}")
    e.emit_line(f"{parse}:")
    _, parsed = e.parse_numeric_text(node, value, floating=floating)
    e.emit_line(f"store {kind} {parsed}, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return kind, e.emit_value(f"load {kind}, ptr {result}")


def scalar_text(e, kind, value, node):
    if kind == tagged.STORAGE:
        semantic = e.value_semantics.get((kind, value))
        if semantic is None:
            raise LLVMUnsupported("LLVM state assignment requires its scalar source type", node)
        return tagged.dispatch(e, tagged.effective_type(semantic, kind), value, "ptr",
                               lambda member, storage, item: scalar_text(e, storage, item, node))
    if kind == "i1":
        return e.string_from_bool(value)
    if kind == "i64":
        return e.string_from_int(value)
    if kind == "double":
        return e.string_from_float(value)
    if kind == "ptr":
        return value
    raise LLVMUnsupported("LLVM state assignment requires an ordinary scalar", node)


def write(e, semantic, receiver, descriptor, assigned, node):
    # StateField.__set__ ignores writes before the base initializer establishes
    # _initialized, but the RHS has already run. A completed no-super constructor
    # also establishes it through CustomElementMetaclass.__call__.
    flag = e.emit_value(f"load i64, ptr {dom_ops.slot(e, semantic, receiver, 1)}")
    present = e.emit_value(f"icmp ne i64 {flag}, 0")
    update, done = e.new_label("state.write"), e.new_label("state.written")
    e.emit_line(f"br i1 {present}, label %{update}, label %{done}")
    e.emit_line(f"{update}:")
    element = dom_ops.pointer(e, semantic, receiver)
    name = f"@{e.string_constant(descriptor.attribute_name)}"
    arena = e.load_local("__arena")
    old = (e.emit_value(f"call ptr @pyjs.native.attribute.get(ptr {e.native_element_arguments(element)}, ptr {name})")
           if has_effects(e, semantic) else "null")
    kind, value = assigned
    if descriptor.value_type is bool:
        _, value = e.coerce_value(kind, value, "i1", node)
        text = e.emit_value(f"select i1 {value}, ptr @{e.string_constant('')}, ptr null")
        item = e.emit_value("alloca ptr")
        e.emit_line(f"store ptr null, ptr {item}")
        add, change = e.new_label("state.true"), e.new_label("state.change")
        e.emit_line(f"br i1 {value}, label %{add}, label %{change}")
        e.emit_line(f"{add}:")
        record = e.native_attribute(arena, name, f"@{e.string_constant('')}")
        e.emit_line(f"store ptr {record}, ptr {item}")
        e.emit_line(f"br label %{change}")
        e.emit_line(f"{change}:")
        record = e.emit_value(f"load ptr, ptr {item}")
    else:
        # Preserve the RHS's Python kind: assigning True to an int descriptor
        # writes 'True', whose later int() read raises, rather than storing '1'.
        text = scalar_text(e, kind, value, node)
        record = e.native_attribute(arena, name, text)
    success = e.emit_value(
        f"call i1 @pyjs.native.attribute.change(ptr {arena}, ptr {element}, ptr {name}, ptr {record})")
    e.guard_exception(node, success, "MemoryError", "native state attribute allocation failed")
    notify(e, semantic, receiver, name, old, text, node, known_name=descriptor.attribute_name)
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")


def finish(e, semantic, receiver, node):
    for descriptor in fields(semantic).values():
        if descriptor.value_type is bool and not descriptor.default:
            continue
        _, _, value = attribute(e, semantic, receiver, descriptor)
        missing = e.emit_value(f"icmp eq ptr {value}, null")
        initialize, done = e.new_label("state.default"), e.new_label("state.materialized")
        e.emit_line(f"br i1 {missing}, label %{initialize}, label %{done}")
        e.emit_line(f"{initialize}:")
        if descriptor.value_type is bool:
            assigned = "i1", "true"
        elif descriptor.value_type is int:
            assigned = "i64", str(descriptor.default)
        elif descriptor.value_type is float:
            assigned = "double", f"0x{struct.pack('>d', descriptor.default).hex().upper()}"
        else:
            assigned = "ptr", f"@{e.string_constant(descriptor.default)}"
        write(e, semantic, receiver, descriptor, assigned, node)
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")
    e.emit_line(f"store i64 2, ptr {dom_ops.slot(e, semantic, receiver, 1)}")
    run_effects(e, semantic, receiver, node)
