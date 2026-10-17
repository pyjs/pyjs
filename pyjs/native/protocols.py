"""Application iterable protocol boundaries.

Application __iter__ may return a builtin handle or an application cursor.
Cursor adapters use normal checked/virtual calls and the shared iterator state
layout; consumers never reinterpret an application object as a builtin handle.
"""

import ast

from pyjs.analysis.iterable_protocol import resolve_iterable_protocol
from pyjs.analysis.objects import Function, union_type_key
from pyjs.analysis.representation import compound_representation
from pyjs.analysis.type_relations import is_subclass, same_analyzer_type

from . import calls
from .errors import LLVMUnsupported


def compatible_source(e, candidate, target):
    """Match abstract consumers only to their reached concrete view sources."""
    from . import iterable_views, iterator_ops
    if iterable_views.is_view(target) or iterator_ops.is_iterator(target):
        return any(is_subclass(view, target) and is_subclass(candidate, source)
                   for source, view in e.module.entry_function.runtime_view_sources)
    return is_subclass(candidate, target)


def item_protocol(value_type):
    from .analysis import NATIVE_ENVIRONMENT
    # Also used by layout helpers outside emission; resolve with the native
    # builtin model explicitly, independent of the caller's active environment.
    return resolve_iterable_protocol(value_type, None, NATIVE_ENVIRONMENT.builtins)


def method(value_type):
    if getattr(value_type.py_obj, "__builtin__", False):
        return None
    result = value_type.find_attrs("__iter__")
    if isinstance(result, Function):
        return result
    return None


def create(emitter, value_type, source, node):
    target = method(value_type)
    if target is None or target not in emitter.module.functions:
        raise LLVMUnsupported("LLVM application iterables require a reached __iter__ method", node)
    # Validate reached runtime overrides too: a base instance method can
    # otherwise hide an unsupported descriptor behind virtual dispatch.
    for implementation in calls.protocol_groups(emitter, value_type, method):
        if implementation is not None and (
                implementation.is_property or implementation.is_static or implementation.is_classmethod):
            raise LLVMUnsupported("LLVM application __iter__ requires an instance method", node)
    arguments = calls.BoundCall([], [])
    if target in emitter.module.virtual_methods:
        result = calls.virtual(emitter, target, source, arguments, node)[1]
    else:
        result = calls.invoke(emitter, target, arguments, node, receiver=source)[1]
    from .iterator_ops import is_iterator
    return result if is_iterator(target.return_type) else wrap(emitter, target.return_type, result, node)


def consumer(emitter, value_type, source, node):
    """Retain a method-created cursor until the consumer's common exit.

    Short-circuit consumers pop this frame outside the loop they can jump out of.
    """
    from . import iterable_views
    from .iterator_ops import is_iterator
    if iterable_views.is_view(value_type):
        source = iterable_views.invoke(emitter, source, node)
    elif value_type in emitter.module.classes:
        source = create(emitter, value_type, source, node)
    elif is_iterator(value_type):
        source = reiterate(emitter, source, node)
    else:
        return value_type, source, None
    return value_type, source, calls.root_values(emitter, source)


class Advance(ast.expr):
    _fields = ()

    def __init__(self, value_type, *, reiterate=False):
        from .analysis import NATIVE_ENVIRONMENT
        self.value_type = value_type
        self.reiterate = reiterate
        self.obj = NATIVE_ENVIRONMENT.builtins.search("int")


def cursor_types(module):
    for value_type in module.classes:
        target = value_type.find_attrs("__next__")
        # An explicit call to a method named __next__ is not by itself an
        # iterator conversion and must not require or analyze __iter__.
        if (isinstance(target, Function) and target in module.functions
                and method(value_type) in module.functions):
            yield value_type


def prepare(emitter, functions):
    from .iterable_views import cursor_type
    from .iterator_callbacks import register
    from .iterator_ops import is_iterator

    # Only reached interface conversions need a typed source signature. A
    # direct __next__/__iter__ call must not create generic dependencies here.
    for source, target in emitter.module.entry_function.runtime_view_sources:
        if (is_iterator(target) and source in emitter.module.classes
                and item_protocol(source) is not None):
            cursor = cursor_type(source)
            emitter.module.iterator_signatures[union_type_key(cursor)] = cursor

    for value_type in cursor_types(emitter.module):
        target = value_type.find_attrs("__next__")
        emitter.module.application_iterators.add(value_type)
        for name in ("next", "iter"):
            register(emitter, functions, target, (value_type, name),
                     ast.copy_location(Advance(value_type, reiterate=name == "iter"), target.original_node))
        emitter.module.uses_iterators = emitter.module.uses_collections = True
        emitter.module.uses_strings = emitter.module.uses_ranges = True


def wrap(emitter, value_type, source, node):
    from . import collection_ops, iterator_ops
    from .runtime import iteration as runtime

    factory = emitter.module.iterator_steps.get((value_type, "iter"))
    if factory is None:
        raise LLVMUnsupported("LLVM application cursors require a reached __iter__ method", node)
    target = emitter.module.iterator_steps.get((value_type, "next"))
    protocol = item_protocol(value_type)
    if protocol is None:
        raise LLVMUnsupported("LLVM application cursors require __iter__ returning an iterator", node)
    advancing = value_type.find_attrs("__next__")
    if (not same_analyzer_type(protocol.item_type, advancing.return_type)
            or protocol.item_representation != advancing.return_representation):
        raise LLVMUnsupported("LLVM application cursors require matching __iter__ and __next__ item layouts", node)
    result = iterator_ops.new(emitter, runtime.APPLICATION, source,
                              size=emitter.llvm_size(emitter.value_type(collection_ops.item_type(value_type))))
    iterator_ops.store(emitter, result, runtime.ADVANCE, "ptr", "@" + emitter.function_name(target))
    iterator_ops.store(emitter, result, runtime.CALLBACK_VALUE, "ptr", "@" + emitter.function_name(factory))
    # Coercion runs after expression() rooted the raw cursor. The new handle
    # owns that cursor, so replace its expression root before a later sibling
    # can invoke application code/GC and before the container stores the handle.
    if root := emitter.expression_roots.get(id(node)):
        emitter.emit_line(f"store ptr {result}, ptr {root}")
    return result


def advance(emitter, node):
    from . import iterator_callbacks
    from .runtime import iteration as runtime

    state, output = emitter.load_local("state"), emitter.load_local("output")
    source = iterator_callbacks.load(emitter, state, runtime.SOURCE)
    if node.reiterate:
        kind, value = "ptr", create(emitter, node.value_type, source, node)
    else:
        target = node.value_type.find_attrs("__next__")
        arguments = calls.BoundCall([], [])
        if target in emitter.module.virtual_methods:
            kind, value = calls.virtual(emitter, target, source, arguments, node)
        else:
            kind, value = calls.invoke(emitter, target, arguments, node, receiver=source)
        expected = target.return_type
        kind, value = emitter.coerce_value(kind, value, emitter.value_type(expected), node, semantic=expected)
    emitter.emit_line(f"store {kind} {value}, ptr {output}")
    return "i64", "1"


def reiterate(emitter, source, node):
    from . import iterator_ops
    if not emitter.module.application_iterators:
        return source
    context = iterator_ops.context(emitter)
    result = emitter.emit_value(f"call ptr @pyjs.iterator.iter(ptr {source}, ptr {context})")
    emitter.check_active_exception(node)
    return result


def dispatch_source(e, value, kind, application, builtin):
    """Select a cursor's application source without interpreting builtin state.

    Callers retain the original handle across collecting callbacks. Typed
    adapters peel to their source, but builtin consumers may still need the
    adapter's yielded-value conversions, so their closure keeps the input view.
    """
    from . import iterator_callbacks, iterator_views
    from .runtime import iteration as runtime

    if not e.module.application_iterators:
        return builtin()
    original = iterator_views.control(e, value)
    tag = iterator_callbacks.load(e, original, 0, "i64")
    selected, plain, done = (e.new_label("cursor.source." + name)
                             for name in ("application", "builtin", "done"))
    output = e.emit_value(f"alloca {kind}")
    test = e.emit_value(f"icmp eq i64 {tag}, {runtime.APPLICATION}")
    e.emit_line(f"br i1 {test}, label %{selected}, label %{plain}")
    e.emit_line(f"{selected}:")
    result = application(iterator_callbacks.load(e, original, runtime.SOURCE))
    e.emit_line(f"store {kind} {result}, ptr {output}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{plain}:")
    result = builtin()
    e.emit_line(f"store {kind} {result}, ptr {output}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return e.emit_value(f"load {kind}, ptr {output}")


def instancecheck(e, value, expected, node):
    """A cursor handle's callback identifies its concrete source ABI.

    Peel only typed adapters, then discriminate APPLICATION before reading its
    source. Builtin iterators use the same handle layout but are not instances
    of an application cursor. Virtual sources still need their nominal check.
    """
    from . import iterator_callbacks, iterator_views, nullable
    from .runtime import iteration as runtime

    state = iterator_views.control(e, value)
    result = e.emit_value("alloca i1")
    e.emit_line(f"store i1 false, ptr {result}")
    visit, done = e.new_label("cursor.class"), e.new_label("cursor.checked")
    tag = e.emit_value(f"load i64, ptr {state}")
    application = e.emit_value(f"icmp eq i64 {tag}, {runtime.APPLICATION}")
    e.emit_line(f"br i1 {application}, label %{visit}, label %{done}")
    e.emit_line(f"{visit}:")
    callback = iterator_callbacks.load(e, state, runtime.ADVANCE)
    source = iterator_callbacks.load(e, state, runtime.SOURCE)
    for concrete in e.module.classes:
        if concrete not in e.module.application_iterators:
            continue
        step = e.module.iterator_steps[concrete, "next"]
        matched = e.emit_value(f"icmp eq ptr {callback}, @{e.function_name(step)}")
        selected, following = e.new_label("cursor.source"), e.new_label("cursor.other")
        e.emit_line(f"br i1 {matched}, label %{selected}, label %{following}")
        e.emit_line(f"{selected}:")
        valid = nullable.instancecheck(e, concrete, "ptr", source, expected, node)
        e.emit_line(f"store i1 {valid}, ptr {result}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{following}:")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return e.emit_value(f"load i1, ptr {result}")


def convert(emitter, kind, value, expected, node):
    from . import iterable_views, iterator_ops, iterator_views, nullable
    actual = emitter.value_semantics.get((kind, value))
    source = nullable.member(actual) or actual
    target = nullable.member(expected) or expected
    if iterator_ops.is_iterator(target) and source in emitter.module.classes:
        def adapt(member, storage, payload):
            # Preserve the concrete protocol diagnostics before inspecting a
            # typed view; next-only or invalid acquisition is not a signature.
            result = wrap(emitter, member, payload, node)
            cursor = iterable_views.cursor_type(member)
            iterator_views.check(cursor, target, node)
            if iterator_views.needed(cursor, target):
                # Reuse the same lazy item conversion and completion/error
                # forwarding as builtin cursor views, including reacquisition.
                represented = compound_representation(arguments=(item_protocol(member).item_representation,))
                result = iterator_views.wrap(emitter, cursor, target, result, node,
                                             representation=represented)
            return result

        if nullable.member(actual):
            result = nullable.dispatch(emitter, actual, kind, value, "ptr", "null", adapt)
        else:
            result = adapt(source, kind, value)
        emitter.value_semantics["ptr", result] = expected
        return "ptr", result
    return None
