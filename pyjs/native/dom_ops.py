"""Bridge application custom-element layouts to the request-owned DOM.

Custom elements are ordinary native objects (fields, inheritance, GC, dispatch),
with two private prefix fields after the vtable: DOM node and initialization
phase. Element transport keeps either that managed wrapper or a plain arena
node. Only DOM consumers unwrap known wrapper headers; application dispatch,
GC roots and type narrowing retain the original object.

Phase 0 means _initialized is absent, 1 means the base initializer established
False, and 2 means metaclass finalization established True. The whole i64 slot
is initialized so conservative GC never scans uninitialized alignment padding.
Scalar state only needs presence (nonzero); the false/true distinction records
the lifecycle boundary for suppressing callbacks during construction.
"""

import ast

from pyjs.analysis.analyzer import analyzed_value_object, analyzed_value_type
from pyjs.analysis.objects import Class, Function, StaticCast, UnionType
from pyjs.analysis.type_relations import get_type_members, is_subclass, same_analyzer_type
from pyjs.decorators import get_native_decoration
from pyjs.native import Attribute, Element
from pyjs.web.dom import Element as WebElement
from pyjs.web.domx import CustomElement, ProxyElement

from . import calls, collection_ops, dom_state, nullable, object_values, tagged
from .bindings import local_storage_binding
from .errors import LLVMUnsupported


def slot(e, semantic, instance, index):
    index += int(semantic in e.module.vtable_roots)
    return e.emit_value(
        f"getelementptr %{e.class_name(semantic)}, ptr {instance}, i32 0, i32 {index}")


def is_element(e, semantic):
    if isinstance(semantic, UnionType):
        return all(item.generic_name == "NoneType" or is_element(e, item) for item in semantic.types)
    return e.is_web_element_type(semantic) or getattr(semantic, "py_obj", None) is Element


def has_element(e, semantic):
    return any(is_element(e, member) for member in semantic.types) if isinstance(semantic, UnionType) else is_element(e, semantic)


def check_type_query(e, actual, expected, node):
    if e.is_opaque_web_element_type(expected):
        # Mapping all public DOM declarations to one storage model does not
        # prove a concrete HTML interface. Analysis retains the query's source
        # class so aliases cannot silently turn is-a-div into is-an-element.
        if getattr(node, "native_dom_query", None) is not WebElement:
            raise LLVMUnsupported("LLVM DOM isinstance supports Element, not concrete DOM interfaces", node)


def instancecheck(e, kind, value, expected):
    """Recover a custom class only from a known DOM transport, never scalar bits."""
    if expected not in e.module.custom_element_types:
        return None
    matched = "false"
    if kind == tagged.STORAGE:
        actual, bits = tagged.parts(e, value)
        matched = tagged.matches(e, actual, expected)
        opaque = e.emit_value(f"icmp eq i64 {actual}, {tagged.DOM_TAG}")
        payload = e.emit_value(f"inttoptr i64 {bits} to ptr")
        # Unrelated tags can contain integers, doubles or empty allocations.
        # The runtime helper must never inspect their first word.
        value = e.emit_value(f"select i1 {opaque}, ptr {payload}, ptr null")
    elif kind != "ptr":
        return None
    custom = e.emit_value(f"call i1 @pyjs.native.element.isinstance(ptr {value}, "
                          f"ptr @{e.vtable_name(expected)}, ptr @pyjs.dom.types, "
                          f"i64 {len(e.module.custom_element_types)})")
    return e.emit_value(f"or i1 {matched}, {custom}") if kind == tagged.STORAGE else custom


def narrow_union(e, value, expected, node):
    """Recover class tags when an opaque DOM arm becomes a custom-class union."""
    candidates = [member for member in tagged.members(expected) if member in e.module.custom_element_types]
    if not candidates:
        return value
    actual, bits = tagged.parts(e, value)
    result = e.emit_value(f"alloca {tagged.STORAGE}")
    e.emit_line(f"store {tagged.STORAGE} {value}, ptr {result}")
    opaque = e.emit_value(f"icmp eq i64 {actual}, {tagged.DOM_TAG}")
    inspect, done = e.new_label("dom.union.inspect"), e.new_label("dom.union.done")
    e.emit_line(f"br i1 {opaque}, label %{inspect}, label %{done}")
    e.emit_line(f"{inspect}:")
    pointer = e.emit_value(f"inttoptr i64 {bits} to ptr")
    for member in candidates:
        valid = instancecheck(e, "ptr", pointer, member)
        yes, no = e.new_label("dom.union.member"), e.new_label("dom.union.next")
        e.emit_line(f"br i1 {valid}, label %{yes}, label %{no}")
        e.emit_line(f"{yes}:")
        packed = tagged.pack(e, member, "ptr", pointer, node)
        e.emit_line(f"store {tagged.STORAGE} {packed}, ptr {result}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{no}:")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return e.emit_value(f"load {tagged.STORAGE}, ptr {result}")


def require_matching_abi(e, actual, expected, node):
    """A virtual slot has no call-site conversion between its implementations."""
    def wrappers(semantic):
        members = semantic.types if isinstance(semantic, UnionType) else (semantic,)
        return {item in e.module.custom_element_types for item in members if is_element(e, item)}

    left, right = wrappers(actual), wrappers(expected)
    if left != right and left | right == {True, False}:
        raise LLVMUnsupported("LLVM virtual overrides must preserve custom-element versus opaque DOM storage", node)


def comparison(e, left_type, left, right_type, right, node, operation):
    if operation not in {"__eq__", "__ne__"} or not (is_element(e, left_type) and is_element(e, right_type)):
        return None
    from .comparisons import has_comparison_callback

    opaque = any(member not in e.module.custom_element_types for member in (left_type, right_type))
    candidates = e.module.custom_element_types if opaque else (left_type, right_type)
    if any(has_comparison_callback(e, member, operation == "__ne__") for member in candidates):
        if opaque:
            raise LLVMUnsupported("LLVM DOM comparison with custom callbacks requires application-typed operands", node)
        return None
    left, right = pointer(e, left_type, left), pointer(e, right_type, right)
    predicate = "eq" if operation == "__eq__" else "ne"
    return e.emit_value(f"icmp {predicate} ptr {left}, {right}")


def identity_value(e, semantic, kind, value, node):
    """Canonicalize only DOM identity; other union tags retain their contract."""
    if not has_element(e, semantic):
        return value if kind == tagged.STORAGE else tagged.pack(e, semantic, kind, value, node)

    def canonical(member, storage, item):
        if is_element(e, member):
            item = pointer(e, member, item)
            bits = e.emit_value(f"ptrtoint ptr {item} to i64")
            result = e.emit_value(f"insertvalue {tagged.STORAGE} zeroinitializer, i64 {tagged.DOM_TAG}, 0")
            return e.emit_value(f"insertvalue {tagged.STORAGE} {result}, i64 {bits}, 1")
        return tagged.pack(e, member, storage, item, node)

    if tagged.members(semantic):
        return tagged.dispatch(e, semantic, value, tagged.STORAGE, canonical)
    if nullable.member(semantic):
        return nullable.dispatch(e, semantic, kind, value, tagged.STORAGE, "zeroinitializer", canonical)
    return canonical(semantic, kind, value)


def identity_pointer(e, semantic, kind, value, node):
    """Compare an Element with a possibly erased reference, without downcasts."""
    if nullable.is_object(semantic):
        # Identity needs no erased payload/layout inventory. That inventory
        # grows during emission, so using it here would depend on whether a
        # caller happened to be emitted before this function. All application
        # headers are already fixed; only custom classes need unwrapping.
        # Inspect the box/header before unboxing ordinary references. An empty
        # string payload, for example, has no readable pointer-sized header.
        unwrapped = e.emit_value(f"call ptr @pyjs.native.element.unwrap(ptr {value}, "
                                 f"ptr @pyjs.dom.types, i64 {len(e.module.custom_element_types)})")
        return object_values.unbox_reference(e, unwrapped)
    if tagged.members(semantic):
        return tagged.dispatch(e, semantic, value, "ptr",
            lambda member, storage, item: identity_pointer(e, member, storage, item, node))
    if kind == "void":
        return "null"
    if kind != "ptr":
        # Numbers cannot be identical to a DOM node (or to its absent None).
        # Use a non-null immutable sentinel, never an integer cast to a pointer.
        return f"@{e.string_constant('')}"
    return pointer(e, semantic, value)


def identity_definitions(e):
    types = [f"ptr @{e.vtable_name(member)}"
             for member in sorted(e.module.custom_element_types, key=e.class_name)]
    return [f"@pyjs.dom.types = private constant [{len(types)} x ptr] [{', '.join(types)}]"]


def pointer(e, semantic, value):
    """Unwrap only a present custom instance; retain plain DOM node identity."""
    if nullable.member(semantic):
        return nullable.dispatch(e, semantic, "ptr", value, "ptr", "null",
                                 lambda member, kind, item: pointer(e, member, item))
    if tagged.members(semantic):
        return tagged.dispatch(e, semantic, value, "ptr",
                               lambda member, kind, item: pointer(e, member, item))
    if semantic in e.module.custom_element_types:
        return e.emit_value(f"load ptr, ptr {slot(e, semantic, value, 0)}")
    if e.is_opaque_web_element_type(semantic) and e.module.custom_element_types:
        return e.emit_value(f"call ptr @pyjs.native.element.unwrap(ptr {value}, "
                            f"ptr @pyjs.dom.types, i64 {len(e.module.custom_element_types)})")
    return value


def argument(e, node, value):
    return pointer(e, analyzed_value_type(node), value)


def extend(e, element, arguments, node):
    success = e.emit_value(
        f"call i1 @pyjs.native.element.extend(ptr {e.load_local('__arena')}, ptr {element}, ptr {arguments})")
    e.guard_exception(node, success, "MemoryError", "native DOM builder allocation failed")


def guard_argument(e, node, valid, exception, message, pending=None):
    if pending is None:
        e.guard_exception(node, valid, exception, message)
        return
    passed, failed = e.new_label("dom.argument.valid"), e.new_label("dom.argument.invalid")
    e.emit_line(f"br i1 {valid}, label %{passed}, label %{failed}")
    e.emit_line(f"{failed}:")
    # tag(existing, ...) mutates incrementally after argument evaluation.
    # Keep its successful prefix on failure, without paying for an extend
    # per child on success. Builder hooks are rejected separately, so no user
    # callback can observe the otherwise deferred publication.
    extend(e, *pending, node)
    e.raise_error(node, exception, message)
    e.emit_line(f"{passed}:")


def check_proxy_field(e, semantic, name, value, node, *, pending=None):
    if name == "element" and e.is_proxy_element_type(semantic):
        # Unlike a DOM node, the ordinary proxy may exist before its element
        # is assigned. Its reserved null field represents an absent attribute.
        guard_argument(e, node, e.emit_value(f"icmp ne ptr {value}, null"),
                       "AttributeError", "ProxyElement has no element", pending)


def proxy_element(e, semantic, receiver, node, *, pending=None):
    attribute = ast.copy_location(ast.Attribute(
        value=ast.Name(id="__proxy", ctx=ast.Load()), attr="element", ctx=ast.Load()), node)
    kind, field, address = e.field_pointer(attribute, (semantic, receiver))
    if kind != "ptr" or not is_element(e, field.value_type):
        raise LLVMUnsupported("LLVM proxy element must be a non-optional Element field", node)
    value = e.emit_value(f"load ptr, ptr {address}")
    check_proxy_field(e, semantic, "element", value, node, pending=pending)
    return pointer(e, field.value_type, value)


def reference_action(e, semantic, kind, value, node, action):
    """Visit present DOM values without confusing a proxy with its node."""
    if nullable.is_object(semantic):
        raise LLVMUnsupported("LLVM hydration references require a typed value; narrow object before ref or assignment", node)
    if tagged.members(semantic):
        return tagged.dispatch(e, semantic, value, "void", lambda member, storage, item:
                               reference_action(e, member, storage, item, node, action))
    concrete = nullable.member(semantic) or semantic
    # The low-level pyjs.native.Element wrapper is not a public web Element;
    # ref() is deliberately an identity-only operation for that Python value.
    if not (e.is_web_element_type(concrete) or e.is_proxy_element_type(concrete)):
        return
    if nullable.member(semantic):
        yes, done = e.new_label("reference.present"), e.new_label("reference.done")
        e.emit_line(f"br i1 {nullable.present(e, kind, value)}, label %{yes}, label %{done}")
        e.emit_line(f"{yes}:")
        action(concrete, value)
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")
    else:
        action(concrete, value)


def mark_reference(e, semantic, kind, value, node):
    def mark(concrete, item):
        if e.is_proxy_element_type(concrete):
            # Do not touch .element: ref(empty_proxy) is valid, and rebinding
            # the backing node must neither lose nor transfer this marker.
            e.emit_line(f"store i64 1, ptr {slot(e, concrete, item, 0)}")
            return
        # ref() writes __pyjs_ref__ through the child's __setattr__, separately
        # from the owner's later assignment hook. Opaque DOM views can refer
        # to any reached custom element, so retain that conservative boundary.
        candidates = e.module.custom_element_types
        if concrete in candidates:
            candidates = [member for member in candidates
                          if collection_ops.is_layout_subclass(member, concrete)]
        overrides = sorted(member.name for member in candidates
                           if member.py_obj.__setattr__ is not CustomElement.__setattr__)
        if overrides:
            view = f"{concrete.name} value" if concrete in e.module.custom_element_types else "an opaque DOM value"
            raise LLVMUnsupported(
                "LLVM ref marking does not support child __setattr__ overrides: "
                f"{overrides[0]}.__setattr__ is reachable through {view}", node)
        child = pointer(e, concrete, item)
        e.emit_line(f"call void @pyjs.native.element.ref(ptr {child})")

    reference_action(e, semantic, kind, value, node, mark)


def bind_reference(e, semantic, receiver, name, assigned, node):
    """Match CustomElement.__setattr__ before a field write or setter call."""
    if (not e.module.uses_dom_references or semantic not in e.module.custom_element_types
            or name in {"parentElement", "parentNode"}):
        return
    kind, value = assigned
    if kind not in {"ptr", tagged.STORAGE}:
        return
    actual = e.value_semantics.get((kind, value))
    if actual is None:
        raise LLVMUnsupported("LLVM hydration assignment requires the source value's type", node)
    reference_action(e, actual, kind, value, node,
                     lambda concrete, item: bind_present_reference(e, semantic, receiver, name, concrete, item, node))


def bind_present_reference(e, semantic, receiver, name, actual, value, node):
    # These Python hooks can affect the id or reject the write. Do not bypass
    # application overrides while lowering the built-in hydration protocol.
    if any(getattr(member.py_obj, hook) is not getattr(CustomElement, hook)
           for member in e.module.custom_element_types
           if collection_ops.is_layout_subclass(member, semantic)
           for hook in ("__setattr__", "get_data")):
        raise LLVMUnsupported("LLVM hydration assignment does not support custom __setattr__ or get_data", node)
    check_dispatch(e, semantic, "getAttribute", node)
    check_dispatch(e, actual, "getAttribute", node)
    check_dispatch(e, actual, "setAttribute", node, attribute_name="id")
    proxy = e.is_proxy_element_type(actual)
    if proxy:
        if any(getattr(member.py_obj, hook) is not getattr(ProxyElement, hook)
               for member in e.module.classes if collection_ops.is_layout_subclass(member, actual)
               for hook in ("getAttribute", "setAttribute")):
            raise LLVMUnsupported("LLVM proxy hydration does not support getAttribute or setAttribute overrides", node)
        marked = e.emit_value(f"load i64, ptr {slot(e, actual, value, 0)}")
        present = e.emit_value(f"icmp ne i64 {marked}, 0")
        yes, done = e.new_label("reference.marked"), e.new_label("reference.bound")
        e.emit_line(f"br i1 {present}, label %{yes}, label %{done}")
        e.emit_line(f"{yes}:")
        child = proxy_element(e, actual, value, node)
    else:
        child = pointer(e, actual, value)
    owner = pointer(e, semantic, receiver)
    operation = "assign" if proxy else "bind"
    result = e.emit_value(
        f"call i8 @pyjs.native.element.{operation}.ref(ptr {e.load_local('__arena')}, ptr {owner}, ptr {child}, "
        f"ptr @{e.string_constant(name)}, ptr @{e.string_constant('id')}, "
        f"ptr @{e.string_constant('data-self-id')})")
    e.guard_exception(node, e.emit_value(f"icmp ne i8 {result}, 1"), "ValueError",
                      "element ids are used for hydration and should not be set")
    e.guard_exception(node, e.emit_value(f"icmp ne i8 {result}, 2"), "MemoryError",
                      "native hydration reference allocation failed")
    if proxy:
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")


def read(e, declared, narrowed, kind, value, node):
    # Flow narrowing changes an expression's analyzed type, not its storage.
    # Callers perform optional-presence checks before exposing this DOM view.
    if (kind == tagged.STORAGE and declared != narrowed
            and any(e.is_opaque_web_element_type(member) for member in get_type_members(declared))
            and any(member in e.module.custom_element_types for member in tagged.members(narrowed))):
        return tagged.narrow(e, value, narrowed, node)
    if (kind == "ptr" and is_element(e, declared) and is_element(e, narrowed)
            and declared != narrowed):
        if tagged.members(narrowed):
            packed = tagged.pack(e, declared, kind, value, node)
            return tagged.narrow(e, packed, narrowed, node)
        if narrowed in e.module.custom_element_types and not is_subclass(nullable.member(declared) or declared, narrowed):
            valid = instancecheck(e, kind, value, narrowed)
            e.guard_exception(node, valid, "TypeError", "DOM value changed after narrowing")
        return "ptr", value
    return None


def root(e, node):
    semantic = analyzed_value_type(node)
    if (not is_element(e, semantic) or isinstance(semantic, UnionType)
            and any(member.generic_name == "NoneType" for member in semantic.types)):
        raise LLVMUnsupported("LLVM rendering requires a non-optional Element", node)
    _, value = e.expression(node)
    return pointer(e, semantic, value)


def convert(e, kind, value, expected, node):
    if kind == "void":
        return None  # None has no DOM view to unwrap; nullable conversion owns it.
    alternatives = tagged.members(expected)
    opaque = next((member for member in alternatives
                   if is_element(e, member) and member not in e.module.custom_element_types), None)
    if opaque is not None:
        actual = e.value_semantics.get((kind, value)) or analyzed_value_type(node)
        if actual is expected:
            return None

        def pack(member, storage, item):
            # A form-control member is not a base of application custom
            # elements. Keep their wrapper/tag so union property dispatch and
            # GC still see the application object, not its opaque DOM node.
            if is_element(e, member) and is_subclass(member, opaque):
                if any(target in e.module.custom_element_types and is_subclass(member, target)
                       for target in alternatives):
                    return tagged.pack(e, member, storage, item, node)
                return tagged.pack(e, opaque, "ptr", item, node)
            return tagged.pack(e, member, storage, item, node)

        if tagged.members(actual):
            return tagged.STORAGE, tagged.dispatch(e, actual, value, tagged.STORAGE, pack)
        if nullable.member(actual):
            return tagged.STORAGE, nullable.dispatch(e, actual, kind, value, tagged.STORAGE,
                                                     "zeroinitializer", pack)
        if is_element(e, actual):
            return tagged.STORAGE, pack(actual, kind, value)
    concrete = nullable.member(expected) or expected
    if (isinstance(concrete, UnionType) or not is_element(e, concrete)
            or concrete in e.module.custom_element_types):
        return None
    actual = e.value_semantics.get((kind, value)) or analyzed_value_type(node)
    if is_element(e, actual) and actual != expected:
        if tagged.members(actual):
            return "ptr", tagged.dispatch(e, actual, value, "ptr",
                lambda member, storage, item: "null" if storage == "void" else item)
        return "ptr", value
    return None


def append(e, arguments, semantic, kind, value, node, *, builder_receiver=None, builder_target=None,
           allow_erased=False, children_only=False):
    """Append concrete or tagged DOM children without flattening object layouts."""
    if nullable.is_object(semantic):
        # Only web builders request the header/layout contract used by this
        # decoder. Low-level Document wrappers do not share its erased ABI.
        if not allow_erased:
            raise LLVMUnsupported("LLVM native argument object is not supported", node)
        from . import erased_dom
        erased_dom.call(e, arguments, value, node, builder_receiver, builder_target,
                        children_only=children_only)
        return
    if tagged.members(semantic):
        tagged.dispatch(e, semantic, value, "void",
                        lambda member, storage, item: append(e, arguments, member, storage, item, node,
                                                             builder_receiver=builder_receiver,
                                                             builder_target=builder_target, allow_erased=allow_erased,
                                                             children_only=children_only))
        return
    pending = (builder_target, arguments) if builder_target is not None else None
    if getattr(semantic, "generic_name", None) == "NoneType":
        if not children_only:
            guard_argument(e, node, "false", "TypeError", "", pending)
        return
    if concrete := nullable.member(semantic):
        if children_only:
            present, done = e.new_label("child.present"), e.new_label("child.done")
            e.emit_line(f"br i1 {nullable.present(e, kind, value)}, label %{present}, label %{done}")
            e.emit_line(f"{present}:")
            payload = value if kind == "ptr" else e.emit_value(f"extractvalue {kind} {value}, 1")
            append(e, arguments, concrete, e.value_type(concrete), payload, node,
                   allow_erased=allow_erased, children_only=True)
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{done}:")
            return
        if kind != "ptr":
            raise LLVMUnsupported("LLVM DOM children require elements or strings", node)
        guard_argument(e, node, nullable.present(e, kind, value), "TypeError", "", pending)
        return append(e, arguments, concrete, kind, value, node,
                      builder_receiver=builder_receiver, builder_target=builder_target,
                      allow_erased=allow_erased)
    if children_only and collection_ops.builtin_name(semantic) != "str" and not is_element(e, semantic):
        # The builtin mutation body ignores non-Node/str arguments. Builders
        # instead consume mappings as attributes and reject unknown values.
        return
    if kind != "ptr":
        raise LLVMUnsupported("LLVM DOM children require elements or strings", node)
    if collection_ops.builtin_name(semantic) == "dict":
        if builder_receiver is not None:
            check_dispatch(e, builder_receiver, "setAttribute", node)
        key_type, value_type = e.dictionary_types(semantic)
        if any(collection_ops.builtin_name(member) != "str" for member in (key_type, value_type)):
            raise LLVMUnsupported("LLVM DOM attributes require dict[str, str]", node)

        def attribute(member, name):
            address, _ = e.dictionary_lookup(value, semantic, "ptr", name, node, source_type=member)
            text = e.emit_value(f"load ptr, ptr {address}")
            arena = e.load_local("__arena")
            item = e.native_attribute(arena, name, text)
            e.append_native_argument(arena, arguments, 8, 1, item)

        collection_ops.loop(e, semantic, value, attribute, node)
        return
    if getattr(semantic, "py_obj", None) is Attribute:
        if builder_receiver is not None:
            check_dispatch(e, builder_receiver, "setAttribute", node)
        tag = 1
    elif is_element(e, semantic):
        tag, value = 2, pointer(e, semantic, value)
    elif e.is_proxy_element_type(semantic):
        tag, value = 2, proxy_element(e, semantic, value, node, pending=pending)
    elif semantic.generic_name == "str":
        tag = 3
    else:
        raise LLVMUnsupported(f"LLVM native argument {semantic.name} is not supported", node)
    if tag in {2, 3} and builder_receiver is not None:
        check_dispatch(e, builder_receiver, "append", node)
    e.append_native_argument(e.load_local("__arena"), arguments, 8, tag, value)


def requires_checked_receiver(expression, function):
    """Do not reproduce emission's runtime type proofs for erased expressions.

    With competing erased-method overrides, only unchanged local storage and fresh
    allocations establish identity without evaluation. Everything else must be
    bound first: properties, overloads, protocols and lowered generator bodies
    can all need checks that their static result annotation does not describe.
    Run after inference stabilizes, never during provisional loop analysis.
    """
    if isinstance(expression, ast.Name):
        binding = local_storage_binding(function, expression)
        return not same_analyzer_type(getattr(binding, "cls", None), analyzed_value_type(expression))
    if isinstance(expression, StaticCast):
        object_values.check_static_cast(expression)
        return (object_values.needs_result_check(analyzed_value_type(expression.value), analyzed_value_type(expression))
                or requires_checked_receiver(expression.value, function))
    if isinstance(expression, ast.Call):
        target = analyzed_value_object(expression.func)
        if isinstance(target, Class):
            # Native construction allocates this class; __init__ cannot replace
            # its receiver. Its side effects are erased like all other arguments.
            return not same_analyzer_type(target, analyzed_value_type(expression))
        if isinstance(target, Function) and (decoration := get_native_decoration(target.py_func)):
            if decoration.operation == "element":
                return False  # Fixed-name native DOM builders allocate fresh nodes.
            if decoration.operation == "tag" and expression.args:
                name = expression.args[0]
                return not (isinstance(name, ast.Constant) and isinstance(name.value, str))
    return True


def check_dispatch(e, semantic, name, node, *, base_implementation=False, allow_effects=False,
                   attribute_name=None, candidates=None):
    """Direct calls and builder shortcuts must obey the same callback boundary."""
    filter_receiver = candidates is not None or semantic in e.module.custom_element_types
    if candidates is None:
        candidates = e.module.custom_element_types
    if filter_receiver:
        # Supplied inventories include materialized but unrelated classes.
        # Builtin receivers and unions need nominal filtering too; neither is
        # necessarily an item in that inventory.
        receivers = semantic.types if isinstance(semantic, UnionType) else (semantic,)
        candidates = [member for member in candidates
                      if any(collection_ops.is_layout_subclass(member, receiver) for receiver in receivers)]
    # Direct calls select custom wrappers first. Builder/property shortcuts
    # that call this guard instead must not silently bypass application hooks.
    owner = CustomElement if name in {"get_data", "set_data"} else WebElement
    if not base_implementation and any(
            getattr(member.py_obj, name) is not getattr(owner, name)
            for member in candidates):
        operation = name if name in {
            "append", "replaceChildren", "textContent", "querySelector", "addEventListener",
        } else "attribute"
        raise LLVMUnsupported(f"LLVM DOM {operation} overrides require a concrete application method call", node)
    if name in {"setAttribute", "removeAttribute"} and any(
            dom_state.has_callbacks(member.py_obj, allow_effects=allow_effects, attribute_name=attribute_name)
            for member in candidates):
        raise LLVMUnsupported("LLVM DOM observed-attribute callbacks are not implemented", node)


def child_argument_projector(e, target, node):
    """Share checked child transport across opaque and exact-union dispatch."""
    if target.name not in {"append", "replaceChildren"} or target.cls not in e.module.custom_element_types:
        return None

    def project(actual, expected, value, on_mismatch):
        # Untyped constructor forwarding erases children, not their runtime
        # kinds. Recover scalar DOM arguments without reinterpreting aliased
        # containers or suppressing the binder's remaining operand effects.
        if (nullable.is_object(actual) and all(
                member.generic_name == "str" or is_element(e, member)
                for member in get_type_members(expected))):
            return object_values.project(e, value, expected, node, on_mismatch=on_mismatch)
        return None

    return project


def method_call(e, target, semantic, receiver, node, *, base_implementation=False):
    """Use the same wrapper-aware operations for ordinary and union calls."""
    opaque = e.is_opaque_web_element_type(semantic)
    if not base_implementation and (semantic in e.module.custom_element_types or opaque):
        owner = CustomElement if target.name in {"get_data", "set_data"} else WebElement
        candidates = [member for member in e.module.custom_element_types
                      if (is_subclass(member, semantic) if opaque
                          else collection_ops.is_layout_subclass(member, semantic))]
        # With no override, the builtin consumer can unwrap one opaque value
        # directly. Selecting every class would duplicate identical bodies.
        if any(getattr(member.py_obj, target.name) is not getattr(owner, target.name)
               for member in candidates):
            # An inherited builtin has no application vtable slot, but the
            # receiver is still a managed wrapper. Select its actual class
            # before binding defaults/operands; super() deliberately bypasses
            # this selection. Opaque transport also admits plain arena nodes,
            # which take the builtin fallback without wrapper interpretation.
            result_kind = e.expression_type(node)
            captured = calls.capture_operands(e, node)

            def select(member):
                implementation = member.find_attrs(target.name)
                if not isinstance(implementation, Function):
                    raise LLVMUnsupported("LLVM DOM override must remain an instance method", node)
                # Application code binds against its defining implementation,
                # so inheriting leaves share an arm. Builtin lowering still
                # needs the exact class for state effects and wrapper layout.
                return member if e.is_opaque_web_element_type(implementation.cls) else implementation

            def invoke(selected):
                member = selected if isinstance(selected, Class) else None
                implementation = member.find_attrs(target.name) if member is not None else selected
                if e.is_opaque_web_element_type(implementation.cls):
                    actual, result = method_call(e, implementation, member, receiver, captured,
                                                 base_implementation=True)
                elif (implementation in e.module.functions and not implementation.is_static
                      and not implementation.is_classmethod and not implementation.is_property):
                    bound = calls.bind(e, implementation, captured, runtime_errors=True,
                                       project_argument=child_argument_projector(e, implementation, node))
                    if bound is None:
                        return "zeroinitializer" if result_kind != "void" else ""
                    with bound:
                        actual, result = calls.invoke(e, implementation, bound, node, receiver=receiver)
                else:
                    raise LLVMUnsupported("LLVM DOM override requires a reached instance method", node)
                return calls.join_result(e, implementation, actual, result, node)[1]

            def fallback():
                actual, value = method_call(e, target, semantic, receiver, captured,
                                            base_implementation=True)
                return calls.join_result(e, target, actual, value, node)[1]

            result = calls.runtime_protocol(e, semantic, receiver, result_kind,
                                            select, invoke, node,
                                            fallback=fallback if opaque else None,
                                            compatible=lambda member, _: member in candidates)
            return result_kind, result
    if target.name == "querySelector":
        check_dispatch(e, semantic, target.name, node, base_implementation=base_implementation)
        # Match the CPython SSR stand-in, not browser descendant selection.
        # Even an ignored selector must bind/evaluate normally (including errors).
        with calls.bind(e, target, node):
            return "ptr", receiver
    if target.name in {"append", "replaceChildren"}:
        return children_call(e, target, semantic, receiver, node, base_implementation=base_implementation)
    if target.name in {"getAttribute", "hasAttribute", "setAttribute", "removeAttribute", "get_data", "set_data"}:
        return attribute_call(e, target, semantic, receiver, node, base_implementation=base_implementation)
    raise LLVMUnsupported(f"LLVM DOM method {target.name} is not implemented", node)


def nested_call(e, target, semantic, receiver, node, values):
    """Call a default's virtual child operation using already evaluated values."""
    function = ast.Name(id=target.name, ctx=ast.Load())
    function.obj = target
    call = ast.copy_location(ast.Call(func=function, args=values, keywords=[]), node)
    call.obj = target.return_type
    return method_call(e, target, semantic, receiver, call)


def attribute_call(e, target, semantic, receiver, node, *, base_implementation=False):
    concrete = semantic in e.module.custom_element_types
    operation = {"get_data": "getAttribute", "set_data": "setAttribute"}.get(target.name, target.name)
    element = pointer(e, semantic, receiver)
    with calls.bind(e, target, node) as bound:
        source = bound.sources[0]
        while isinstance(source, tagged.Value):
            source = source.source
        known_name = source.value if isinstance(source, ast.Constant) and isinstance(source.value, str) else None
        if operation != target.name and known_name is not None:
            known_name = "data-" + known_name
        check_dispatch(e, semantic, target.name, node, base_implementation=base_implementation,
                       allow_effects=concrete, attribute_name=known_name)
        name = bound.values[0][1]
        if operation != target.name:
            name = e.string_concat(f"@{e.string_constant('data-')}", name)
            nested = target.cls.find_attrs(operation)
            parameters = calls.parameters(nested)
            name_source = ast.Constant(value=known_name) if known_name is not None else node
            values = [tagged.Value(name_source, parameters[0].annotation.obj, "ptr", name)]
            if operation == "setAttribute":
                values.append(tagged.Value(node, parameters[1].annotation.obj, *bound.values[1]))
            # The synthesized prefix can be collected by the selected getter
            # or setter; it is not an ordinary source-expression root.
            with calls.BoundCall([], [], e, calls.root_values(e, receiver, name)):
                return nested_call(e, nested, semantic, receiver, node, values)
        if operation in {"getAttribute", "hasAttribute"}:
            arguments = e.native_element_arguments(element)
            value = e.emit_value(f"call ptr @pyjs.native.attribute.get(ptr {arguments}, ptr {name})")
            if operation == "getAttribute":
                return "ptr", value
            return "i1", e.emit_value(f"icmp ne ptr {value}, null")
        arena = e.load_local("__arena")
        old = (e.emit_value(f"call ptr @pyjs.native.attribute.get(ptr {e.native_element_arguments(element)}, ptr {name})")
               if dom_state.has_effects(e, semantic) else "null")
        value = bound.values[1][1] if operation == "setAttribute" else "null"
        attribute = (e.native_attribute(arena, name, bound.values[1][1])
                     if operation == "setAttribute" else "null")
        success = e.emit_value(
            f"call i1 @pyjs.native.attribute.change(ptr {arena}, ptr {element}, ptr {name}, ptr {attribute})")
        e.guard_exception(node, success, "MemoryError", "native DOM attribute allocation failed")
        dom_state.notify(e, semantic, receiver, name, old, value, node, known_name=known_name)
        return "void", ""


def children_call(e, target, semantic, receiver, node, *, base_implementation=False):
    check_dispatch(e, semantic, target.name, node, base_implementation=base_implementation)
    nested_append = target.name == "replaceChildren" and any(
        is_subclass(member, semantic) and member.py_obj.append is not WebElement.append
        for member in e.module.custom_element_types)
    element = pointer(e, semantic, receiver)
    member = collection_ops.item_type(target.vararg.annotation.obj)
    members = UnionType(types=(member,))
    for argument in node.args:
        actual = analyzed_value_type(argument.value if isinstance(argument, ast.Starred) else argument)
        items = (actual,)
        if isinstance(argument, ast.Starred):
            items = tuple(item for arm in get_type_members(actual)
                          for item in (tuple(arm.generic_types.values()) if collection_ops.is_fixed_tuple(arm)
                                       else (collection_ops.item_type(arm),)))
        if erased := next((leaf for item in items for leaf in get_type_members(item)
                           if nullable.is_object(leaf)), None):
            # Untyped constructor forwarding uses ordinary object transport.
            # Decode only this temporary pack; typed children keep their union
            # layout, and the shared declaration is never widened or mutated.
            member = erased
            break
        for item in items:
            members.add(item)
    else:
        # Preserve expanded argument kinds until the builtin body decides
        # which to ignore. This is copied temporary storage, not a widening
        # of the public signature or a reinterpretation of aliased containers.
        member = members.type
    with calls.bind(e, target, node, vararg_type=member) as bound:
        # Ordinary binding snapshots expansions and roots all values before
        # mutation. Read the latest DOM pack only after argument callbacks.
        additions = e.native_argument_pack([])
        if nested_append:
            # CPython clears first and invokes self.append separately for each
            # child. A callback can observe the prefix or raise; neither bulk
            # insertion nor one append(*children) has those semantics.
            arena = e.load_local("__arena")
            success = e.emit_value(
                f"call i1 @pyjs.native.element.replace.children(ptr {arena}, ptr {element}, ptr {additions})")
            e.guard_exception(node, success, "MemoryError", "native DOM child allocation failed")
            operation = target.cls.find_attrs("append")

            def invoke(actual, kind, value):
                return nested_call(e, operation, semantic, receiver, node,
                                   [tagged.Value(node, actual, kind, value)])[1]

            def child(actual, value):
                # A valid prefix must reach the override before a later
                # incompatible member fails its typed binding. Do not reject
                # every value merely because its pack also admits None/maps.
                if tagged.members(actual):
                    tagged.dispatch(e, actual, value, "void", invoke)
                else:
                    invoke(actual, e.value_type(actual), value)

            collection_ops.loop_storage(e, "list", member, bound.values[0][1],
                                        child, node)
            return "void", ""
        def child(actual, value):
            append(e, additions, actual, e.value_type(actual), value, node,
                   allow_erased=True, children_only=True)

        collection_ops.loop_storage(e, "list", member, bound.values[0][1], child, node)
        operation = "replace.children" if target.name == "replaceChildren" else "extend"
        arena = e.load_local("__arena")
        success = e.emit_value(
            f"call i1 @pyjs.native.element.{operation}(ptr {arena}, ptr {element}, ptr {additions})")
        e.guard_exception(node, success, "MemoryError", "native DOM child allocation failed")
        return "void", ""


def property_access(e, target, semantic, receiver, node, assigned, *, base_implementation=False):
    if target.name == "classList":
        # This view retains only the arena-owned DOM, not a custom wrapper.
        # Reject observable callbacks at acquisition so stored/returned views
        # cannot later bypass application dispatch or keep hidden GC pointers.
        check_dispatch(e, semantic, "classList", node, base_implementation=base_implementation)
        check_dispatch(e, semantic, "getAttribute", node)
        check_dispatch(e, semantic, "setAttribute", node, attribute_name="class")
        element = pointer(e, semantic, receiver)
        # CPython creates a new view on every property read. Keep that identity
        # while all views borrow the same live, request-owned node.
        view = e.allocated_value(f"call ptr @pyjs.arena.try.alloc(ptr {e.load_local('__arena')}, i64 8, i64 8)")
        e.emit_line(f"store ptr {element}, ptr {view}")
        return view
    if target.name == "value":
        element = pointer(e, semantic, receiver)
        if assigned is None:
            stored = e.emit_value(f"call ptr @pyjs.native.element.value(ptr {element})")
            missing = e.emit_value(f"icmp eq ptr {stored}, null")
            return e.emit_value(f"select i1 {missing}, ptr @{e.string_constant('')}, ptr {stored}")
        # Arena ownership keeps aliases and retained reads valid across GC;
        # publish only after copying succeeds, never touch HTML attributes.
        value = e.arena_string(e.load_local("__arena"), assigned[1])
        e.emit_line(f"call void @pyjs.native.element.value.set(ptr {element}, ptr {value})")
        return None
    if target.name != "textContent":
        raise LLVMUnsupported(f"LLVM DOM property {target.name} is not implemented", node)
    check_dispatch(e, semantic, target.name, node, base_implementation=base_implementation)
    element = pointer(e, semantic, receiver)
    arena = e.load_local("__arena")
    if assigned is None:
        result = e.emit_value(f"call ptr @pyjs.native.element.text(ptr {arena}, ptr {element})")
        e.require_allocation(result)
        return result
    kind, value = assigned
    _, value = e.coerce_value(kind, value, "ptr", node)
    empty = f"@{e.string_constant('')}"
    missing = e.emit_value(f"icmp eq ptr {value}, null")
    value = e.emit_value(f"select i1 {missing}, ptr {empty}, ptr {value}")
    if e.module.uses_gc:
        # Empty text retains no borrowed bytes and clearing must not allocate.
        # Nonempty replacements still cross the ordinary arena ownership gate.
        slot = e.emit_value("alloca ptr")
        e.emit_line(f"store ptr {empty}, ptr {slot}")
        length = e.emit_value(f"load i64, ptr {value}")
        nonempty = e.emit_value(f"icmp ne i64 {length}, 0")
        copy, ready = e.new_label("text.copy"), e.new_label("text.ready")
        e.emit_line(f"br i1 {nonempty}, label %{copy}, label %{ready}")
        e.emit_line(f"{copy}:")
        copied = e.arena_string(arena, value)
        e.emit_line(f"store ptr {copied}, ptr {slot}")
        e.emit_line(f"br label %{ready}")
        e.emit_line(f"{ready}:")
        value = e.emit_value(f"load ptr, ptr {slot}")
    success = e.emit_value(
        f"call i1 @pyjs.native.element.text.set(ptr {arena}, ptr {element}, ptr {value})")
    e.guard_exception(node, success, "MemoryError", "native DOM text allocation failed")
    return None


def token_query(e, receiver, token="null"):
    from .runtime.text import WHITESPACE

    element = e.emit_value(f"load ptr, ptr {receiver}")
    return e.emit_value(
        f"call i64 @pyjs.native.class.query(ptr {element}, ptr {token}, "
        f"ptr @{e.string_constant('class')}, ptr @{e.string_constant(WHITESPACE)})")


def token_call(e, target, receiver, node):
    from .runtime.text import WHITESPACE

    with calls.bind(e, target, node) as bound:
        if target.name == "contains":
            index = token_query(e, receiver, bound.values[0][1])
            return "i1", e.emit_value(f"icmp sge i64 {index}, 0")
        if target.name not in {"add", "remove"}:
            raise LLVMUnsupported(f"LLVM classList method {target.name} is not implemented", node)
        # The shared binder evaluates and roots every fixed/starred argument
        # before mutation. Its variadic tuple uses the ordinary sequence header.
        values = bound.values[0][1]
        count = e.emit_value(f"load i64, ptr {values}")
        data_slot = e.emit_value(f"getelementptr %pyjs.list, ptr {values}, i32 0, i32 2")
        data = e.emit_value(f"load ptr, ptr {data_slot}")
        element = e.emit_value(f"load ptr, ptr {receiver}")
        remove = "true" if target.name == "remove" else "false"
        success = e.emit_value(
            f"call i1 @pyjs.native.class.mutate(ptr {e.load_local('__arena')}, ptr {element}, "
            f"ptr {data}, i64 {count}, i1 {remove}, ptr @{e.string_constant('class')}, "
            f"ptr @{e.string_constant(WHITESPACE)}, ptr @{e.string_constant('')})")
        e.guard_exception(node, success, "MemoryError", "native class token allocation failed")
        return "void", ""


def construct(e, node, layout, bound):
    name = node.value_type.py_obj.__pyjs_ssr_tag_name__
    if name is None:
        raise LLVMUnsupported("LLVM custom element construction requires a concrete tag; subclass Widget", node)
    arena = e.load_local("__arena")
    arguments = e.native_argument_pack([])
    element = e.native_element(arena, "null", f"@{e.string_constant(name)}", arguments)
    # Application wrappers use the managed heap when GC is active, so ordinary
    # fields and subclass payloads are traced. DOM content remains request-arena
    # owned and holds copies of text, not hidden pointers into managed strings.
    result = e.allocate_instance(node.value_type, e.module.uses_gc)
    e.emit_line(f"store ptr {element}, ptr {slot(e, node.value_type, result, 0)}")
    e.emit_line(f"store i64 0, ptr {slot(e, node.value_type, result, 1)}")
    frame = calls.root_values(e, result)
    with calls.BoundCall([], [], e, frame):
        e.invoke_constructor(node, layout, result, bound)
        if node.value_type.py_obj.__init__ is CustomElement.__init__:
            initialize_identity(e, node.value_type, result)
        dom_state.finish(e, node.value_type, result, node.call)
    return "ptr", result


def initialize_identity(e, semantic, instance):
    """Assign IDs at super().__init__, not before the Python constructor runs."""
    initialized_slot = slot(e, semantic, instance, 1)
    arena = e.load_local("__arena")
    counter_slot = e.emit_value(f"getelementptr %pyjs.arena, ptr {arena}, i32 0, i32 1")
    counter = e.emit_value(f"load i64, ptr {counter_slot}")
    counter = e.emit_value(f"add i64 {counter}, 1")
    identity = e.string_concat(f"@{e.string_constant('ce')}", e.string_from_int(counter))
    element = pointer(e, semantic, instance)
    attribute = e.native_attribute(arena, f"@{e.string_constant('data-self-id')}", identity)
    arguments = e.native_argument_pack([])
    e.append_native_argument(arena, arguments, 8, 1, attribute)
    argument_slot = e.emit_value(f"getelementptr %pyjs.native.element, ptr {element}, i32 0, i32 1")
    # Publish only once all allocations succeed, so a caught MemoryError does
    # not leave an identity with no corresponding DOM attribute. Explicitly
    # repeating the base initializer resets DOM content, just as CPython does;
    # ordinary application fields remain part of the wrapper, not that reset.
    e.emit_line(f"store ptr {arguments}, ptr {argument_slot}")
    e.emit_line(f"store i64 1, ptr {initialized_slot}")
    e.emit_line(f"store i64 {counter}, ptr {counter_slot}")
