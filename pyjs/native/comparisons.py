"""Callback-aware native comparisons and sequence search."""

from contextlib import nullcontext

from pyjs.analysis.iterable_protocol import resolve_iterable_protocol
from pyjs.analysis.objects import CallableClass, RecursiveTypeAlias
from pyjs.analysis.type_relations import (
    get_type_members,
    is_return_type_compatible,
    is_strict_runtime_subclass,
    is_subclass,
    same_analyzer_type,
)
from pyjs.analysis.value_representation import (
    analyzed_representation,
    representation_for_member,
)

from . import callables, calls, dom_ops, enum_ops, nullable, tagged
from . import collection_ops as collections
from . import dataclasses as dataclass_ops
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported

REFLECTED = {"__eq__": "__eq__", "__ne__": "__ne__", "__lt__": "__gt__",
             "__le__": "__ge__", "__gt__": "__lt__", "__ge__": "__le__"}


def supported_result(semantic):
    allowed = {NATIVE_ENVIRONMENT.builtins.search(name) for name in ("bool", "NotImplementedType")}
    return all(member in allowed for member in get_type_members(semantic))


def boolean_result(emitter, semantic, kind, value, declined):
    """Consume only the bool arm; a sentinel delegates without truth conversion."""
    if kind == "i1":
        return value
    if semantic is NATIVE_ENVIRONMENT.builtins.search("NotImplementedType"):
        emitter.emit_line(f"br label %{declined}")
        return None
    tag = emitter.emit_value(f"extractvalue {kind} {value}, 0")
    missing = emitter.emit_value(f"icmp eq i64 {tag}, {tagged.TAGS['NotImplementedType']}")
    accepted = emitter.new_label("comparison.accepted")
    emitter.emit_line(f"br i1 {missing}, label %{declined}, label %{accepted}")
    emitter.emit_line(f"{accepted}:")
    payload = emitter.emit_value(f"extractvalue {kind} {value}, 1")
    return emitter.emit_value(f"icmp ne i64 {payload}, 0")


def disabled_method(semantic, name):
    """An explicit non-callable protocol is not the inherited object default."""
    return not callable(getattr(semantic.py_obj, name))


def has_comparison_callback(emitter, semantic, inequality):
    if nullable.is_object(semantic):
        return True  # An erased value does not prove default identity.
    if semantic not in emitter.module.classes:
        return False
    names = ("__eq__", "__ne__") if inequality else ("__eq__",)
    # Match object_compare's application-method boundary, including reached
    # overrides and disabled methods: neither permits an identity-only shortcut.
    # The shared analyzer's object model is not the native builtin.
    return any(is_subclass(candidate, semantic)
               and any(disabled_method(candidate, name)
                       or getattr(candidate.find_attrs(name), "cls", None) in emitter.module.classes
                       for name in names)
               for candidate in emitter.module.classes)


def check_representations(emitter, node, left, right, *, inequality=False):
    """Validate paired leaf formats and represented callback arguments.

    Recursive comparators carry item types, not numeric representations. Walk
    paired slots, not each operand independently: a represented dictionary key
    or tuple sibling does not change an application argument in another slot.
    """
    pending = [(*left, *right, inequality)]
    seen = set()
    while pending:
        pair = pending.pop()
        if pair in seen:
            continue
        seen.add(pair)
        a_type, a_rep, b_type, b_rep, inequality = pair
        if a_rep is None and b_rep is None:
            continue
        a_members, b_members = get_type_members(a_type), get_type_members(b_type)
        if len(a_members) > 1 or len(b_members) > 1:
            pending.extend((a, representation_for_member(a_type, a_rep, a),
                            b, representation_for_member(b_type, b_rep, b), inequality)
                           for a in a_members for b in b_members)
            continue
        if any(has_comparison_callback(emitter, value, inequality) for value in (a_type, b_type)):
            raise LLVMUnsupported("Native object comparison callbacks require ordinary item representations", node)
        a_name, b_name = collections.builtin_name(a_type), collections.builtin_name(b_type)
        if a_name in {"bool", "int", "float"} and b_name in {"bool", "int", "float"}:
            formats = {representation.numeric for representation in (a_rep, b_rep)
                       if representation is not None and representation.numeric is not None}
            if len(formats) > 1:
                raise LLVMUnsupported("different fixed-width numeric types cannot be compared implicitly", node)
            if (any(value.kind == "integer" and value.bits == 64 for value in formats)
                    and "float" in {a_name, b_name}):
                raise LLVMUnsupported("int64 and float comparisons cannot be mixed implicitly", node)
        if a_name != b_name and {a_name, b_name} != {"set", "frozenset"}:
            continue  # Unlike builtin families compare unequal without callbacks.
        if a_name not in {"list", "tuple", "dict", "set", "frozenset"}:
            continue
        a_items = tuple((getattr(a_type, "generic_types", None) or {}).values())
        b_items = tuple((getattr(b_type, "generic_types", None) or {}).values())
        a_parts = a_rep.arguments if a_rep is not None else (None,) * len(a_items)
        b_parts = b_rep.arguments if b_rep is not None else (None,) * len(b_items)
        if a_name == "tuple":
            if a_type.tuple_variadic:
                a_items, a_parts = a_items * len(b_items), a_parts * len(b_items)
            elif b_type.tuple_variadic:
                b_items, b_parts = b_items * len(a_items), b_parts * len(a_items)
        # Container inequality still compares its elements with __eq__, never
        # their authored __ne__. Tuples compare their common prefix even with
        # different lengths, so its formats/callbacks still need validation.
        pending.extend((*items, False) for items in zip(a_items, a_parts, b_items, b_parts, strict=False))


def retain_erased(node, *semantics, inequality=False):
    """Implicit equality consumers need reached callbacks just like operators."""
    if any(nullable.contains(semantic, "object") for semantic in semantics):
        names = ("__eq__", "__ne__") if inequality else ("__eq__",)
        required = ((NATIVE_ENVIRONMENT.builtins.search("object"), (name,)) for name in names)
        node.runtime_protocols = tuple(dict.fromkeys((*getattr(node, "runtime_protocols", ()), *required)))
    return node


def set_compare(emitter, operation, left_type, left, right_type, right, node):
    from . import mapping_keys

    if any(collections.builtin_name(semantic) not in {"set", "frozenset"}
           for semantic in (left_type, right_type)):
        raise LLVMUnsupported("LLVM set comparison requires set or frozenset operands", node)
    emitter.module.uses_mappings = True
    member = collections.item_type(left_type)
    other_member = collections.item_type(right_type)
    distinct = not same_analyzer_type(other_member, member) and all(
        collections.builtin_name(item) in {"bool", "int", "float", "str", "bytes", "NoneType"}
        for semantic in (member, other_member) for item in get_type_members(semantic))
    if not distinct and not same_analyzer_type(other_member, member):
        if mapping_keys.can_reuse(emitter, other_member, member):
            member = other_member
        elif not mapping_keys.can_reuse(emitter, member, other_member):
            raise LLVMUnsupported("LLVM set comparisons require matching item types", node)
    if not distinct and mapping_keys.uses_callbacks(member):
        return mapping_keys.compare_sets(emitter, operation, member, left, right, node)
    if operation in {"__gt__", "__ge__", "issuperset"}:
        left, right = right, left
        member, other_member = other_member, member
    disjoint = str(operation == "isdisjoint").lower()
    if distinct:
        result = emitter.emit_value(
            f"call i1 @pyjs.set.subset.distinct(ptr {emitter.load_local('__arena')}, "
            f"ptr {emitter.load_local('__heap') if emitter.module.uses_gc else 'null'}, "
            f"ptr {emitter.load_local('__exception') if emitter.module.uses_exceptions else 'null'}, "
            f"ptr {left}, ptr {right}, i64 {emitter.llvm_size(emitter.value_type(member))}, "
            f"i64 {emitter.llvm_size(emitter.value_type(other_member))}, "
            f"ptr @{mapping_keys.comparator(emitter, member, node, query=other_member)}, i1 {disjoint})")
    else:
        size, kind = emitter.llvm_size(emitter.value_type(member)), emitter.dictionary_key_kind(member)
        result = emitter.emit_value(f"call i1 @pyjs.set.subset(ptr {left}, ptr {right}, i64 {size}, i8 {kind}, i1 {disjoint})")
    if operation in {"__eq__", "__ne__", "__lt__", "__gt__"}:
        left_length = emitter.emit_value(f"load i64, ptr {left}")
        right_length = emitter.emit_value(f"load i64, ptr {right}")
        predicate = "eq" if operation in {"__eq__", "__ne__"} else "slt"
        shape = emitter.emit_value(f"icmp {predicate} i64 {left_length}, {right_length}")
        result = emitter.emit_value(f"and i1 {result}, {shape}")
    return emitter.emit_value(f"xor i1 {result}, true") if operation == "__ne__" else result


def object_compare(emitter, left_type, left, right_type, right, node, *, operation="__eq__", identity=True,
                   dynamic=False):
    ordering = operation not in {"__eq__", "__ne__"}
    identity = identity and not ordering
    result = emitter.emit_value("alloca i1")
    # Only application instances can share identity with an application
    # receiver. A pointer-shaped builtin is a different allocation/layout.
    pointer_operands = all(value_type in emitter.module.classes or nullable.is_object(value_type)
                           for value_type in (left_type, right_type))
    same = "false" if ordering or not pointer_operands else emitter.emit_value(f"icmp eq ptr {left}, {right}")
    initial = emitter.emit_value(f"xor i1 {same}, true") if operation == "__ne__" else same
    emitter.emit_line(f"store i1 {initial}, ptr {result}")
    compare, done = emitter.new_label("object.compare"), emitter.new_label("object.compare.done")
    emitter.emit_line(f"br i1 {same if identity else 'false'}, label %{done}, label %{compare}")
    emitter.emit_line(f"{compare}:")

    def invoke(receiver_type, receiver, other_type, other, missing, method_name):
        fallback = emitter.new_label("unequal.delegate") if method_name == "__ne__" else missing
        root = emitter.module.vtable_roots.get(receiver_type)
        names = emitter.module.vtable_slots.get(root, ())
        # Check only the selected protocol, after member identity and reflected
        # priority. A callable right-subtype override may handle the comparison
        # before a disabled left method is ever invoked. Virtual receivers need
        # the concrete class check even if their static base is callable.
        for candidate in emitter.module.classes:
            if (receiver_type in emitter.module.classes and collections.is_layout_subclass(candidate, receiver_type)
                    and disabled_method(candidate, method_name)):
                valid = "false"
                if root is not None:
                    table = emitter.emit_value(f"load ptr, ptr {receiver}")
                    valid = emitter.emit_value(f"icmp ne ptr {table}, @{emitter.vtable_name(candidate)}")
                message = f"'{type(getattr(candidate.py_obj, method_name)).__name__}' object is not callable"
                emitter.guard_exception(node, valid, "TypeError", message)
        implementation = None
        if method_name in names:
            methods = {emitter.resolve_method(value_type, method_name) for value_type in emitter.module.classes
                       if collections.is_layout_subclass(value_type, receiver_type)} - {None}
            table = emitter.emit_value(f"load ptr, ptr {receiver}")
            slot = emitter.emit_value(calls.vtable_slot(emitter, table, root, names.index(method_name)))
            implementation = emitter.emit_value(f"load ptr, ptr {slot}")
            present = emitter.emit_value(f"icmp ne ptr {implementation}, null")
            called = emitter.new_label("equal.override")
            emitter.emit_line(f"br i1 {present}, label %{called}, label %{fallback}")
            emitter.emit_line(f"{called}:")
        else:
            method = receiver_type.find_attrs(method_name)
            methods = {method} if getattr(method, "cls", None) in emitter.module.classes else set()
        if not methods:
            emitter.emit_line(f"br label %{fallback}")
        else:
            incompatible = set()
            for method in sorted(methods, key=emitter.function_name):
                if len(method.params) != 1 or not supported_result(method.return_type):
                    raise LLVMUnsupported(f"LLVM collection {method_name} requires a compatible typed argument and bool result or NotImplemented", node)
                if not is_return_type_compatible(method.params[0].annotation.obj, other_type):
                    if not dynamic:
                        raise LLVMUnsupported(f"LLVM collection {method_name} requires a compatible typed argument and bool result or NotImplemented", node)
                    incompatible.add(method)
                    continue
                collections.require_matching_layout(other_type, method.params[0].annotation.obj, node)
            generated = [method for method in methods if dataclass_ops.is_generated_equality(method)]
            if generated:
                from . import object_values

                # The shared generated body has a bool ABI. Python's implicit
                # NotImplemented on unlike record classes belongs to binary
                # dispatch: continue with the reflected method, not False.
                selected = "true" if implementation is None else "false"
                for candidate in sorted(generated, key=emitter.function_name):
                    if implementation is not None:
                        match = emitter.emit_value(f"icmp eq ptr {implementation}, @{emitter.function_name(candidate)}")
                        selected = emitter.emit_value(f"or i1 {selected}, {match}")
                different = (emitter.emit_value(f"xor i1 {object_values.same_type(emitter, receiver, other)}, true")
                             if other_type in emitter.module.classes or nullable.is_object(other_type) else "true")
                decline = emitter.emit_value(f"and i1 {selected}, {different}")
                accepted = emitter.new_label("record.equal.accepted")
                emitter.emit_line(f"br i1 {decline}, label %{missing}, label %{accepted}")
                emitter.emit_line(f"{accepted}:")
            kind = "void" if other_type is NATIVE_ENVIRONMENT.builtins.search("NoneType") else emitter.value_type(other_type)
            emitter.value_semantics[kind, other] = other_type
            arguments = calls.BoundCall([(kind, other)], [None])
            def consume(method, code):
                if method in incompatible:
                    # A union can select valid and invalid callback argument
                    # types. Fail only the selected incompatible arm; never
                    # reinterpret None or scalar bits as a concrete instance.
                    emitter.guard_exception(node, "false", "TypeError",
                                            f"{method_name} requires a compatible typed argument")
                    emitter.emit_line(f"br label %{done}")
                    return
                # Checked binding preserves pointer payload semantics and roots
                # boxed arguments. An authored ne declining goes to the other
                # operand; absent object.ne instead delegates to its own eq.
                kind, value = calls.invoke(emitter, method, arguments, node, receiver=receiver,
                                           implementation=code)
                matched = boolean_result(emitter, method.return_type, kind, value, missing)
                if matched is not None:
                    if operation == "__ne__" and method_name == "__eq__":
                        matched = emitter.emit_value(f"xor i1 {matched}, true")
                    emitter.emit_line(f"store i1 {matched}, ptr {result}")
                    emitter.emit_line(f"br label %{done}")

            if implementation is not None and (incompatible
                    or len({emitter.method_signature(method)[1] for method in methods}) > 1):
                # Covariant overrides can physically return bool, sentinel ptr
                # or a tagged union. Never call a raw slot with another body's
                # return ABI. Argument checks likewise belong to the selected
                # implementation. Uniform valid families keep one indirect call.
                for method in sorted(methods, key=emitter.function_name):
                    selected, following = emitter.new_label("comparison.body"), emitter.new_label("comparison.next")
                    match = emitter.emit_value(f"icmp eq ptr {implementation}, @{emitter.function_name(method)}")
                    emitter.emit_line(f"br i1 {match}, label %{selected}, label %{following}")
                    emitter.emit_line(f"{selected}:")
                    consume(method, None)
                    emitter.emit_line(f"{following}:")
                emitter.emit_line(f"br label %{missing}")
            else:
                consume(method, implementation)
        if method_name == "__ne__":
            emitter.emit_line(f"{fallback}:")
            invoke(receiver_type, receiver, other_type, other, missing, "__eq__")

    # A proper subtype on the right gets first refusal. All reached concrete
    # classes are known, so reuse their vtable identities without a new RTTI ABI.
    reflected = "true" if is_strict_runtime_subclass(right_type, left_type) else "false"
    left_virtual = left_type in emitter.module.vtable_roots
    right_virtual = right_type in emitter.module.vtable_roots
    if left_virtual or right_virtual:
        a_table = emitter.emit_value(f"load ptr, ptr {left}") if left_virtual else None
        b_table = emitter.emit_value(f"load ptr, ptr {right}") if right_virtual else None
        reflected = "false"
        # Generic specializations may have different layouts/vtable families
        # but the same runtime Python base. A nonvirtual operand still has a
        # known class; only the virtual side needs a table-identity check.
        for a in emitter.module.classes if left_virtual else (left_type,):
            if not collections.is_layout_subclass(a, left_type):
                continue
            for b in emitter.module.classes if right_virtual else (right_type,):
                if not is_strict_runtime_subclass(b, a) or not collections.is_layout_subclass(b, right_type):
                    continue
                a_matches = emitter.emit_value(f"icmp eq ptr {a_table}, @{emitter.vtable_name(a)}") if left_virtual else "true"
                b_matches = emitter.emit_value(f"icmp eq ptr {b_table}, @{emitter.vtable_name(b)}") if right_virtual else "true"
                pair = emitter.emit_value(f"and i1 {a_matches}, {b_matches}")
                reflected = emitter.emit_value(f"or i1 {reflected}, {pair}")
    forward, backward = emitter.new_label("equal.left"), emitter.new_label("equal.right")
    unsupported = emitter.new_label("order.unsupported") if ordering else done
    emitter.emit_line(f"br i1 {reflected}, label %{backward}, label %{forward}")
    for label, arguments in ((forward, (left_type, left, right_type, right)),
                             (backward, (right_type, right, left_type, left))):
        emitter.emit_line(f"{label}:")
        fallback = emitter.new_label("equal.fallback")
        first_method = operation if label == forward else REFLECTED[operation]
        invoke(*arguments, fallback, first_method)
        emitter.emit_line(f"{fallback}:")
        invoke(*arguments[2:], *arguments[:2], unsupported, REFLECTED[first_method])
    if ordering:
        emitter.emit_line(f"{unsupported}:")
        if emitter.module.uses_exceptions:
            message = ordering_error_message(emitter, operation, left_type, left, right_type, right)
            emitter.activate_error(node, NATIVE_ENVIRONMENT.builtins.search("TypeError"), message)
            emitter.branch_to_exception_target()
        else:
            emitter.trap_unless("false")
            emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    return emitter.emit_value(f"load i1, ptr {result}")


def ordering_error_message(emitter, operation, left_type, left, right_type, right):
    symbol = {"__lt__": "<", "__le__": "<=", "__gt__": ">", "__ge__": ">="}[operation]

    def message(a, b):
        # Report Python class names, not specialized storage symbols (set__int).
        text = f"'{symbol}' not supported between instances of '{a.generic_name}' and '{b.generic_name}'"
        return f"@{emitter.string_constant(text)}"

    def candidates(value_type, value):
        if value_type not in emitter.module.vtable_roots:
            return [(value_type, "true")]
        table = emitter.emit_value(f"load ptr, ptr {value}")
        return [(concrete, emitter.emit_value(f"icmp eq ptr {table}, @{emitter.vtable_name(concrete)}"))
                for concrete in emitter.module.classes if collections.is_layout_subclass(concrete, value_type)]

    # Select constant messages on the failure path without allocating while
    # raising. Layouts without runtime type identities retain their static name.
    result = message(left_type, right_type)
    left_types, right_types = candidates(left_type, left), candidates(right_type, right)
    for a, a_matches in left_types:
        for b, b_matches in right_types:
            matches = emitter.emit_value(f"and i1 {a_matches}, {b_matches}")
            result = emitter.emit_value(f"select i1 {matches}, ptr {message(a, b)}, ptr {result}")
    return result


def equal_value(emitter, left_type, left, right_type, right, node):
    # Container members use identity-or-equality, regardless of the operation
    # on their enclosing container. Root comparisons preserve their own dunder.
    return compare_value(emitter, left_type, left, right_type, right, node,
                         operation="__eq__", identity=True)


def compare_value(emitter, left_type, left, right_type, right, node, *, operation, identity=False,
                  dynamic=False, expand_recursive=False):
    # Literal values have ordinary scalar equality. In particular, optional
    # dispatch passes its Literal payload here without another AST lowering.
    left_type, right_type = tagged.runtime_type(left_type), tagged.runtime_type(right_type)
    if ((nullable.member(left_type) or nullable.member(right_type))
            and any(getattr(value, "generic_name", None) == "NoneType" for value in (left_type, right_type))):
        # Split optional storage before interpreting an erased payload; both
        # present and absent arms keep their ordinary comparison protocol.
        return nullable.compare(emitter, left_type, left, right_type, right, node,
                                operation=operation, identity=identity)
    if not expand_recursive and any(isinstance(item, RecursiveTypeAlias) for item in (left_type, right_type)):
        symbol = callback(emitter, left_type, right_type, node, operation=operation, identity=identity)
        # A literal None expression has no SSA value, but its callback slot
        # uses pointer storage just like a materialized None value.
        values = [(emitter.value_type(semantic), "null" if getattr(semantic, "generic_name", None) == "NoneType" else value)
                  for semantic, value in ((left_type, left), (right_type, right))]
        slots, frame = calls.value_slots(emitter, [kind if kind != "void" else "i1" for kind, _ in values])
        for slot, (kind, value) in zip(slots, values, strict=True):
            emitter.emit_line(f"store {kind} {value}, ptr {slot}" if kind != "void" else f"store i1 false, ptr {slot}")
        result = emitter.emit_value(
            f"call i64 @{symbol}(ptr {emitter.load_local('__arena')}, "
            f"ptr {emitter.load_local('__heap') if emitter.module.uses_gc else 'null'}, "
            f"ptr {emitter.load_local('__exception') if emitter.module.uses_exceptions else 'null'}, "
            f"ptr {slots[0]}, ptr {slots[1]})")
        emitter.check_active_exception(node)
        calls.pop_roots(emitter, frame)
        return emitter.emit_value(f"icmp ne i64 {result}, 0")
    if (nullable.is_object(left_type) or nullable.is_object(right_type)
            or getattr(emitter, "erased_comparison", False)):
        from . import erased_comparison
        return erased_comparison.call(emitter, left_type, left, right_type, right, node,
                                      operation=operation, identity=identity)
    if tagged.members(left_type):
        return tagged.dispatch(emitter, left_type, left, "i1",
                               lambda member, kind, payload: compare_value(emitter, member, payload, right_type, right, node,
                                                                          operation=operation, identity=identity, dynamic=True))
    if tagged.members(right_type):
        return tagged.dispatch(emitter, right_type, right, "i1",
                               lambda member, kind, payload: compare_value(emitter, left_type, left, member, payload, node,
                                                                          operation=operation, identity=identity, dynamic=True))
    if nullable.member(left_type) or nullable.member(right_type):
        return nullable.compare(emitter, left_type, left, right_type, right, node,
                                operation=operation, identity=identity)
    if result := dom_ops.comparison(emitter, left_type, left, right_type, right, node, operation):
        return result
    # A parent container can release these operands during a nested callback.
    # Keep the entire recursive comparison alive, not just its current leaf.
    values = [value for value_type, value in ((left_type, left), (right_type, right))
              if collections.builtin_name(value_type) not in {"int", "bool", "float", "str", "bytes", "NoneType"}
              and emitter.value_type(value_type) == "ptr"]
    frame = calls.root_values(emitter, *values) if values else None
    if left_type in emitter.module.classes or right_type in emitter.module.classes:
        result = object_compare(emitter, left_type, left, right_type, right, node,
                                operation=operation, identity=identity, dynamic=dynamic)
    else:
        # Builtin inequality inverts equality; authored __ne__ must not. Keep
        # this after tagged dispatch so every application arm keeps its method.
        result = _equal_value(emitter, left_type, left, right_type, right, node, identity=identity)
        if operation == "__ne__":
            result = emitter.emit_value(f"xor i1 {result}, true")
    calls.pop_roots(emitter, frame)
    return result


def callback(e, left_type, right_type, node, *, operation="__eq__", identity=True):
    """Share typed equality callbacks between mapping keys and recursive edges."""
    key = left_type, right_type, operation, identity
    if key not in e.module.value_comparators:
        e.module.value_comparators[key] = f"pyjs.value.compare.{len(e.module.value_comparators)}", node
        e.module.value_comparator_queue.append(key)
    return e.module.value_comparators[key][0]


def definitions(parent, emitted):
    from .llvm import FunctionEmitter

    output = []
    # Queue traversal includes helpers discovered while emitting a body without
    # rescanning previously emitted pairs at each recursive type boundary.
    while len(emitted) < len(parent.module.value_comparator_queue):
        pending = parent.module.value_comparator_queue[len(emitted):]
        for key in pending:
            emitted.add(key)  # Publish before descending through a named cycle.
            left_type, right_type, operation, identity = key
            symbol, node = parent.module.value_comparators[key]
            e = FunctionEmitter(parent.module)
            e.stack_allocations = []
            e.allocation_node = node
            e.return_type = e.return_storage_type = "i64"
            # Mapping runtimes use this fixed ABI even without a GC/exception
            # context. Recursive edges share it without requiring a mapping.
            for name in ("__arena", "__heap", "__exception"):
                e.slots[name], e.slot_types[name] = f"%slot.{name}", "ptr"
                e.emit_line(f"%slot.{name} = alloca ptr")
                e.emit_line(f"store ptr %{name}, ptr %slot.{name}")
            kinds = [e.value_type(semantic) for semantic in (left_type, right_type)]
            values = [e.emit_value(f"load {kind}, ptr %{side}") if kind != "void" else ""
                      for kind, side in zip(kinds, ("left", "right"), strict=True)]
            rooted = [(kind, value) for kind, value in zip(kinds, values, strict=True) if kind != "void"]
            # Root loaded values, not borrowed array slots: comparison callbacks
            # can replace the owning mapping's storage before another GC.
            slots, e.gc_frame = calls.value_slots(e, [kind for kind, _ in rooted])
            for slot, (kind, value) in zip(slots, rooted, strict=True):
                e.emit_line(f"store {kind} {value}, ptr {slot}")
            recursive = any(isinstance(item, RecursiveTypeAlias) for item in (left_type, right_type))
            scope = calls.recursion_scope(e, node, "maximum recursion depth exceeded in comparison") if recursive else nullcontext()
            with scope:
                matched = compare_value(e, left_type, values[0], right_type, values[1], node,
                                        operation=operation, identity=identity, expand_recursive=True)
            result = e.emit_value(f"zext i1 {matched} to i64")
            calls.pop_roots(e, e.gc_frame)
            e.emit_line(f"ret i64 {result}")
            if e.module.uses_exceptions:
                e.emit_line("pyjs.exception.return:")
                e.restore_gc_frame()
                calls.pop_roots(e, e.gc_frame)
                e.emit_line("ret i64 0")
            attribute = " noinline" if recursive else ""
            output.extend([f"define private i64 @{symbol}(ptr %__arena, ptr %__heap, ptr %__exception, "
                           f"ptr %left, ptr %right){attribute} {{", "entry:",
                           *(f"  {line}" for line in (*e.stack_allocations, *e.lines)), "}"])
    return output


def _equal_value(emitter, left_type, left, right_type, right, node, *, identity=False):
    left_type, right_type = enum_ops.underlying(left_type), enum_ops.underlying(right_type)
    if isinstance(left_type, CallableClass) or isinstance(right_type, CallableClass):
        if not isinstance(left_type, CallableClass) or not isinstance(right_type, CallableClass):
            return "false"
        return callables.equal(emitter, left_type, left, right_type, right)
    if left_type in emitter.module.classes or right_type in emitter.module.classes:
        return "false"  # Default application identity cannot equal a builtin value.
    from . import mapping_views
    if collections.builtin_name(left_type) in mapping_views.VIEWS:
        return mapping_views.compare(emitter, "__eq__", left_type, left, right_type, right, node, identity=identity)
    if collections.builtin_name(right_type) in mapping_views.VIEWS:
        return mapping_views.compare(emitter, "__eq__", right_type, right, left_type, left, node, identity=identity)
    name = left_type.generic_name
    if name == right_type.generic_name == "NoneType":
        return "true"
    if collections.builtin_name(left_type) == collections.builtin_name(right_type) == "NotImplementedType":
        return "true"
    if left_type is right_type and collections.builtin_name(left_type) == "WebTokenList":
        return emitter.emit_value(f"icmp eq ptr {left}, {right}")
    if collections.builtin_name(left_type) in {"set", "frozenset"} and collections.builtin_name(right_type) in {"set", "frozenset"}:
        return set_compare(emitter, "__eq__", left_type, left, right_type, right, node)
    if left_type is not right_type:
        if {name, right_type.generic_name} <= {"bool", "int"}:
            if name == "bool":
                left = emitter.emit_value(f"zext i1 {left} to i64")
            if right_type.generic_name == "bool":
                right = emitter.emit_value(f"zext i1 {right} to i64")
            return emitter.emit_value(f"icmp eq i64 {left}, {right}")
        if name in {"int", "bool", "float"} and right_type.generic_name in {"int", "bool", "float"}:
            integer_type, integer, floating = ((right_type, right, left) if name == "float" else (left_type, left, right))
            if integer_type.generic_name == "bool":
                integer = emitter.emit_value(f"zext i1 {integer} to i64")
            return emitter.emit_value(f"call i1 @pyjs.float.integer.equal(i64 {integer}, double {floating})")
        if name != right_type.generic_name:
            return "false"
        if name not in {"tuple", "list", "dict"}:
            raise LLVMUnsupported("LLVM collection comparisons require matching item types", node)
    if name in {"int", "bool", "float", "str", "bytes"}:
        return collections.scalar_compare(emitter, "equal", left_type, left, right, node)
    if name == "range":
        arguments = ", ".join(f"i64 {value}" for value in (*emitter.range_values(left), *emitter.range_values(right)))
        return emitter.emit_value(f"call i1 @pyjs.range.equal({arguments})")
    if name == "slice":
        from . import slices
        return slices.equal(emitter, left, right, node)
    # Equality reads each operand using its own layout; it is not a storage
    # conversion. The sequence loop already has separate member types/strides.
    homogeneous_tuple = (name == "tuple"
                         and collections.sequence_name(left_type) == collections.sequence_name(right_type) == "list")
    if name == "tuple" and not homogeneous_tuple:
        if not left_type.generic_types or not right_type.generic_types:
            value = left if left_type.generic_types else right
            length = emitter.emit_value(f"load i64, ptr {value}")
            return emitter.emit_value(f"icmp eq i64 {length}, 0")
        left_members = tuple(left_type.generic_types.values())
        right_members = tuple(right_type.generic_types.values())
        if left_type.tuple_variadic:
            left_members *= len(right_members)
        elif right_type.tuple_variadic:
            right_members *= len(left_members)
        result = emitter.emit_value("alloca i1")
        same = emitter.emit_value(f"icmp eq ptr {left}, {right}")
        emitter.emit_line(f"store i1 {same}, ptr {result}")
        compare, finish, done = (emitter.new_label(label) for label in
                                 ("tuple.equal", "tuple.equal.lengths", "tuple.equal.done"))
        emitter.emit_line(f"br i1 {same}, label %{done}, label %{compare}")
        emitter.emit_line(f"{compare}:")
        a_length = emitter.emit_value(f"load i64, ptr {left}")
        b_length = emitter.emit_value(f"load i64, ptr {right}")
        for index, (a_type, b_type) in enumerate(zip(left_members, right_members, strict=False)):
            if left_type.tuple_variadic or right_type.tuple_variadic:
                # Tuples compare the common prefix before lengths. Guard each
                # read instead of skipping observable callbacks on a mismatch.
                a_available = emitter.emit_value(f"icmp ult i64 {index}, {a_length}")
                b_available = emitter.emit_value(f"icmp ult i64 {index}, {b_length}")
                available = emitter.emit_value(f"and i1 {a_available}, {b_available}")
                fields = emitter.new_label("tuple.equal.fields")
                emitter.emit_line(f"br i1 {available}, label %{fields}, label %{finish}")
                emitter.emit_line(f"{fields}:")
            values = []
            for value_type, value, member in ((left_type, left, a_type), (right_type, right, b_type)):
                if collections.sequence_name(value_type) == "list":
                    values.append(collections.read_item(emitter, "list", member, value, str(index))[0])
                else:
                    slot = collections.field(emitter, collections.storage(emitter, value, 2), emitter.tuple_type(value_type), index)
                    values.append(emitter.emit_value(f"load {emitter.value_type(member)}, ptr {slot}"))
            current = equal_value(emitter, a_type, values[0], b_type, values[1], node)
            emitter.emit_line(f"store i1 {current}, ptr {result}")
            following = emitter.new_label("tuple.equal.next")
            emitter.emit_line(f"br i1 {current}, label %{following}, label %{done}")
            emitter.emit_line(f"{following}:")
        emitter.emit_line(f"br label %{finish}")
        emitter.emit_line(f"{finish}:")
        matches = emitter.emit_value(f"icmp eq i64 {a_length}, {b_length}")
        emitter.emit_line(f"store i1 {matches}, ptr {result}")
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{done}:")
        return emitter.emit_value(f"load i1, ptr {result}")
    if name == "list" or homogeneous_tuple:
        member = collections.item_type(left_type)
        other_member = collections.item_type(right_type)
        kind = emitter.value_type(member)
        if (same_analyzer_type(member, other_member)
                and collections.builtin_name(member) in {"int", "bool", "float", "str", "bytes"}):
            emitter.module.uses_ordering = True
            size = emitter.llvm_size(kind)
            comparison = emitter.emit_value(f"call i8 @pyjs.list.compare(ptr {left}, ptr {right}, i64 {size}, i8 {collections.scalar_kind(member, node)})")
            return emitter.emit_value(f"icmp eq i8 {comparison}, 0")
        result = emitter.emit_value("alloca i1")
        cursor = emitter.emit_value("alloca i64")
        emitter.emit_line(f"store i64 0, ptr {cursor}")
        same = emitter.emit_value(f"icmp eq ptr {left}, {right}")
        emitter.emit_line(f"store i1 {same}, ptr {result}")
        shape, compare, done = (emitter.new_label(label) for label in ("list.shape", "list.compare", "list.done"))
        emitter.emit_line(f"br i1 {same}, label %{done}, label %{shape}")
        emitter.emit_line(f"{shape}:")
        a_length = emitter.emit_value(f"load i64, ptr {left}")
        b_length = emitter.emit_value(f"load i64, ptr {right}")
        matches = emitter.emit_value(f"icmp eq i64 {a_length}, {b_length}")
        emitter.emit_line(f"store i1 {matches}, ptr {result}")
        if homogeneous_tuple:
            emitter.emit_line(f"br label %{compare}")
        else:
            # Lists, unlike tuples, reject unequal lengths before callbacks.
            emitter.emit_line(f"br i1 {matches}, label %{compare}, label %{done}")
        emitter.emit_line(f"{compare}:")
        # __eq__ can resize either operand. Never retain a buffer address or
        # length across it, and stop when either current sequence is exhausted.
        check, body, finish = (emitter.new_label(label) for label in ("equal.check", "equal.item", "equal.lengths"))
        emitter.emit_line(f"br label %{check}")
        emitter.emit_line(f"{check}:")
        index = emitter.emit_value(f"load i64, ptr {cursor}")
        a_length = emitter.emit_value(f"load i64, ptr {left}")
        b_length = emitter.emit_value(f"load i64, ptr {right}")
        a_available = emitter.emit_value(f"icmp ult i64 {index}, {a_length}")
        b_available = emitter.emit_value(f"icmp ult i64 {index}, {b_length}")
        available = emitter.emit_value(f"and i1 {a_available}, {b_available}")
        emitter.emit_line(f"br i1 {available}, label %{body}, label %{finish}")
        emitter.emit_line(f"{body}:")
        a = collections.read_item(emitter, "list", member, left, index)[0]
        b = collections.read_item(emitter, "list", other_member, right, index)[0]
        matches = equal_value(emitter, member, a, other_member, b, node)
        emitter.emit_line(f"store i1 {matches}, ptr {result}")
        following = emitter.emit_value(f"add i64 {index}, 1")
        emitter.emit_line(f"store i64 {following}, ptr {cursor}")
        emitter.emit_line(f"br i1 {matches}, label %{check}, label %{done}")
        emitter.emit_line(f"{finish}:")
        matches = emitter.emit_value(f"icmp eq i64 {a_length}, {b_length}")
        emitter.emit_line(f"store i1 {matches}, ptr {result}")
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{done}:")
        return emitter.emit_value(f"load i1, ptr {result}")
    if name == "dict":
        from . import mapping_keys

        emitter.module.uses_mappings = True
        key_type, member = emitter.dictionary_types(left_type)
        other_key, other_member = emitter.dictionary_types(right_type)
        if not mapping_keys.comparable(emitter, key_type, other_key):
            raise LLVMUnsupported("LLVM mapping comparisons require matching key types", node)
        key_kind = emitter.value_type(key_type)
        value_kind = emitter.value_type(member)
        other_value_kind = emitter.value_type(other_member)
        (key_root, value_root), frame = calls.value_slots(emitter, [key_kind, value_kind])
        result = emitter.emit_value("alloca i1")
        a_length = emitter.emit_value(f"load i64, ptr {left}")
        b_length = emitter.emit_value(f"load i64, ptr {right}")
        shape = emitter.emit_value(f"icmp eq i64 {a_length}, {b_length}")
        emitter.emit_line(f"store i1 {shape}, ptr {result}")
        check, done = emitter.new_label("mapping.compare"), emitter.new_label("mapping.done")
        same = emitter.emit_value(f"icmp eq ptr {left}, {right}")
        different = emitter.emit_value(f"xor i1 {same}, true")
        compare_values = emitter.emit_value(f"and i1 {shape}, {different}")
        emitter.emit_line(f"br i1 {compare_values}, label %{check}, label %{done}")
        emitter.emit_line(f"{check}:")
        # Equality is an internal mapping scan, not a Python iterator: key or
        # value equality can delete entries without a size-change exception.
        # Reuse insertion ordinals so dense compaction cannot skip a survivor.
        tracked = emitter.emit_value(f"call i1 @pyjs.dict.track.order(ptr {emitter.load_local('__arena')}, ptr {left})")
        emitter.guard_exception(node, tracked, "MemoryError", "native mapping comparison allocation failed")
        cursor = emitter.emit_value("alloca i64")
        emitter.emit_line(f"store i64 0, ptr {cursor}")
        scan, body, missing = (emitter.new_label(label) for label in ("mapping.scan", "mapping.entry", "mapping.missing"))
        emitter.emit_line(f"br label %{scan}")
        emitter.emit_line(f"{scan}:")
        ordinal = emitter.emit_value(f"load i64, ptr {cursor}")
        index = emitter.emit_value(f"call i64 @pyjs.dict.repr.index(ptr {left}, i64 {ordinal})")
        length = emitter.emit_value(f"load i64, ptr {left}")
        available = emitter.emit_value(f"icmp ult i64 {index}, {length}")
        emitter.emit_line(f"br i1 {available}, label %{body}, label %{done}")
        emitter.emit_line(f"{body}:")
        key = collections.read_item(emitter, "dict", key_type, left, index)[0]
        a_slot = mapping_keys.value_slot(emitter, left, index, emitter.llvm_size(value_kind))
        a = emitter.emit_value(f"load {value_kind}, ptr {a_slot}")
        emitter.emit_line(f"store {key_kind} {key}, ptr {key_root}")
        emitter.emit_line(f"store {value_kind} {a}, ptr {value_root}")
        order = collections.storage(emitter, left, 6)
        ordinal_slot = emitter.emit_value(f"getelementptr i64, ptr {order}, i64 {index}")
        ordinal = emitter.emit_value(f"load i64, ptr {ordinal_slot}")
        following = emitter.emit_value(f"add i64 {ordinal}, 1")
        emitter.emit_line(f"store i64 {following}, ptr {cursor}")
        if mapping_keys.uses_callbacks(key_type):
            hashes = collections.storage(emitter, left, 8)
            hash_slot = emitter.emit_value(f"getelementptr i64, ptr {hashes}, i64 {index}")
            hashed = emitter.emit_value(f"load i64, ptr {hash_slot}")
            # Equality reads cached hashes and each key's original layout.
            # A base/derived query must not become a writable mapping upcast.
            b_slot = mapping_keys.lookup(emitter, right, other_key, key_kind, key,
                                         emitter.llvm_size(other_value_kind), node,
                                         known_hash=hashed, query_type=key_type)
        else:
            b_slot, _ = emitter.dictionary_lookup(right, right_type, key_kind, key, node, source_type=key_type)
        present = emitter.emit_value(f"icmp ne ptr {b_slot}, null")
        compare_items = emitter.new_label("mapping.values")
        emitter.emit_line(f"br i1 {present}, label %{compare_items}, label %{missing}")
        emitter.emit_line(f"{compare_items}:")
        b = emitter.emit_value(f"load {other_value_kind}, ptr {b_slot}")
        matches = equal_value(emitter, member, a, other_member, b, node)
        emitter.emit_line(f"br i1 {matches}, label %{scan}, label %{missing}")
        emitter.emit_line(f"{missing}:")
        emitter.emit_line(f"store i1 false, ptr {result}")
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{done}:")
        calls.pop_roots(emitter, frame)
        return emitter.emit_value(f"load i1, ptr {result}")
    raise LLVMUnsupported(f"LLVM collection equality for {left_type.name} is not implemented", node)


def order_value(emitter, operation, left_type, left, right_type, right, node):
    left_type, right_type = tagged.runtime_type(left_type), tagged.runtime_type(right_type)
    if tagged.members(left_type):
        return tagged.dispatch(emitter, left_type, left, "i1",
                               lambda member, kind, payload: order_value(
                                   emitter, operation, member, payload, right_type, right, node))
    if tagged.members(right_type):
        return tagged.dispatch(emitter, right_type, right, "i1",
                               lambda member, kind, payload: order_value(
                                   emitter, operation, left_type, left, member, payload, node))
    if nullable.member(left_type) or nullable.member(right_type):
        return nullable.compare(emitter, left_type, left, right_type, right, node, operation=operation)
    values = [value for value_type, value in ((left_type, left), (right_type, right))
              if emitter.value_type(value_type) == "ptr" and value_type.generic_name != "NoneType"]
    frame = calls.root_values(emitter, *values) if values else None
    result = _order_value(emitter, operation, left_type, left, right_type, right, node)
    calls.pop_roots(emitter, frame)
    return result


def _order_value(emitter, operation, left_type, left, right_type, right, node):
    if left_type in emitter.module.classes or right_type in emitter.module.classes:
        return object_compare(emitter, left_type, left, right_type, right, node, operation=operation, dynamic=True)
    # Application callbacks need nominal enum arguments, including reflected
    # calls. Only builtin ordering consumes their underlying scalar values.
    left_type, right_type = enum_ops.underlying(left_type), enum_ops.underlying(right_type)
    if any(value.generic_name == "NoneType" for value in (left_type, right_type)):
        symbol = {"__lt__": "<", "__le__": "<=", "__gt__": ">", "__ge__": ">="}[operation]
        emitter.guard_exception(node, "false", "TypeError",
                                f"'{symbol}' not supported between instances of '{left_type.generic_name}' and '{right_type.generic_name}'")
        return "false"
    left_name, right_name = collections.builtin_name(left_type), collections.builtin_name(right_type)
    from . import mapping_views
    if left_name in mapping_views.VIEWS or right_name in mapping_views.VIEWS:
        return mapping_views.compare(emitter, operation, left_type, left, right_type, right, node)
    if left_name in {"set", "frozenset"} and right_name in {"set", "frozenset"}:
        return set_compare(emitter, operation, left_type, left, right_type, right, node)
    if left_name == right_name and left_name in {"list", "tuple"}:
        return sequence_order(emitter, operation, left_type, left, right_type, right, node)
    predicate = {"__lt__": "lt", "__le__": "le", "__gt__": "gt", "__ge__": "ge"}[operation]
    if left_type is not right_type and {left_name, right_name} <= {"bool", "int", "float"}:
        if left_name == "bool":
            left = emitter.emit_value(f"zext i1 {left} to i64")
        if right_name == "bool":
            right = emitter.emit_value(f"zext i1 {right} to i64")
        if "float" not in {left_name, right_name}:
            return emitter.emit_value(f"icmp s{predicate} i64 {left}, {right}")
        integer, floating = (right, left) if left_name == "float" else (left, right)
        # Converting the integer to double would lose ordering above 2**53.
        # The Python-authored helper also handles NaN and signed-i64 boundaries.
        comparison = emitter.emit_value(f"call i64 @pyjs.float.integer.order(i64 {integer}, double {floating})")
        if left_name == "float":
            predicate = {"lt": "gt", "le": "ge", "gt": "lt", "ge": "le"}[predicate]
        result = emitter.emit_value(f"icmp s{predicate} i64 {comparison}, 0")
        ordered = emitter.emit_value(f"icmp ne i64 {comparison}, 2")
        return emitter.emit_value(f"and i1 {ordered}, {result}")
    if left_type is not right_type or left_name not in {"bool", "int", "float", "str", "bytes"}:
        # A union's incompatible arm is a runtime error only when selected.
        # Lexicographic comparisons may never reach it after an earlier result.
        symbol = {"__lt__": "<", "__le__": "<=", "__gt__": ">", "__ge__": ">="}[operation]
        emitter.guard_exception(node, "false", "TypeError",
                                f"'{symbol}' not supported between instances of '{left_type.generic_name}' and '{right_type.generic_name}'")
        return "false"
    collections.require_matching_layout(left_type, right_type, node)
    scalar = collections.scalar_kind(left_type, node)
    if scalar in {1, 2, 4}:
        instruction = "fcmp o" if scalar == 4 else "icmp u" if scalar == 1 else "icmp s"
        return emitter.emit_value(f"{instruction}{predicate} {emitter.value_type(left_type)} {left}, {right}")
    if operation in {"__gt__", "__le__"}:
        left, right = right, left
    result = collections.scalar_compare(emitter, "less", left_type, left, right, node)
    return emitter.emit_value(f"xor i1 {result}, true") if operation in {"__le__", "__ge__"} else result


def sequence_order(emitter, operation, left_type, left, right_type, right, node):
    result = emitter.emit_value("alloca i1")
    done = emitter.new_label("order.done")
    body = emitter.new_label("order.sequence")
    same = emitter.emit_value(f"icmp eq ptr {left}, {right}")
    emitter.emit_line(f"store i1 {str(operation in {'__le__', '__ge__'}).lower()}, ptr {result}")
    emitter.emit_line(f"br i1 {same}, label %{done}, label %{body}")
    emitter.emit_line(f"{body}:")

    def compare(a_type, a, b_type, b, index=None):
        equal = equal_value(emitter, a_type, a, b_type, b, node)
        unequal, following = emitter.new_label("order.unequal"), emitter.new_label("order.next")
        emitter.emit_line(f"br i1 {equal}, label %{following}, label %{unequal}")
        emitter.emit_line(f"{unequal}:")
        if left_type.generic_name == "list":
            # Python rechecks the index after equality and orders the current
            # items. A callback may replace them or shrink past this position.
            a_length = emitter.emit_value(f"load i64, ptr {left}")
            b_length = emitter.emit_value(f"load i64, ptr {right}")
            a_valid = emitter.emit_value(f"icmp ult i64 {index}, {a_length}")
            b_valid = emitter.emit_value(f"icmp ult i64 {index}, {b_length}")
            valid = emitter.emit_value(f"and i1 {a_valid}, {b_valid}")
            present, exhausted = emitter.new_label("order.present"), emitter.new_label("order.exhausted")
            emitter.emit_line(f"br i1 {valid}, label %{present}, label %{exhausted}")
            emitter.emit_line(f"{exhausted}:")
            finish_lengths(a_length, b_length)
            emitter.emit_line(f"{present}:")
            a = collections.read_item(emitter, "list", a_type, left, index)[0]
            b = collections.read_item(emitter, "list", b_type, right, index)[0]
        ordered = order_value(emitter, operation, a_type, a, b_type, b, node)
        emitter.emit_line(f"store i1 {ordered}, ptr {result}")
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{following}:")

    def finish_lengths(a_length, b_length):
        predicate = {"__lt__": "ult", "__le__": "ule", "__gt__": "ugt", "__ge__": "uge"}[operation]
        ordered = emitter.emit_value(f"icmp {predicate} i64 {a_length}, {b_length}")
        emitter.emit_line(f"store i1 {ordered}, ptr {result}")
        emitter.emit_line(f"br label %{done}")

    homogeneous = collections.sequence_name(left_type) == collections.sequence_name(right_type) == "list"
    if homogeneous:
        a_type, b_type = collections.item_type(left_type), collections.item_type(right_type)
        cursor = emitter.emit_value("alloca i64")
        emitter.emit_line(f"store i64 0, ptr {cursor}")
        check, body, finish = (emitter.new_label(label) for label in ("order.check", "order.item", "order.lengths"))
        emitter.emit_line(f"br label %{check}")
        emitter.emit_line(f"{check}:")
        index = emitter.emit_value(f"load i64, ptr {cursor}")
        a_length = emitter.emit_value(f"load i64, ptr {left}")
        b_length = emitter.emit_value(f"load i64, ptr {right}")
        a_valid = emitter.emit_value(f"icmp ult i64 {index}, {a_length}")
        b_valid = emitter.emit_value(f"icmp ult i64 {index}, {b_length}")
        valid = emitter.emit_value(f"and i1 {a_valid}, {b_valid}")
        emitter.emit_line(f"br i1 {valid}, label %{body}, label %{finish}")
        emitter.emit_line(f"{body}:")
        a = collections.read_item(emitter, "list", a_type, left, index)[0]
        b = collections.read_item(emitter, "list", b_type, right, index)[0]
        compare(a_type, a, b_type, b, index)
        following = emitter.emit_value(f"add i64 {index}, 1")
        emitter.emit_line(f"store i64 {following}, ptr {cursor}")
        emitter.emit_line(f"br label %{check}")
        emitter.emit_line(f"{finish}:")
    else:
        a_types, b_types = tuple(left_type.generic_types.values()), tuple(right_type.generic_types.values())
        dynamic_left = collections.sequence_name(left_type) == "list"
        dynamic_right = collections.sequence_name(right_type) == "list"
        if dynamic_left:
            a_types *= len(b_types)
        if dynamic_right:
            b_types *= len(a_types)
        for index, (a_type, b_type) in enumerate(zip(a_types, b_types, strict=False)):
            if dynamic_left or dynamic_right:
                # The fixed side bounds code generation, not the runtime length
                # of the other tuple. Do not read past an exhausted dynamic side.
                a_length = emitter.emit_value(f"load i64, ptr {left}")
                b_length = emitter.emit_value(f"load i64, ptr {right}")
                length = a_length if dynamic_left else b_length
                present, exhausted = emitter.new_label("order.slot"), emitter.new_label("order.lengths")
                valid = emitter.emit_value(f"icmp ult i64 {index}, {length}")
                emitter.emit_line(f"br i1 {valid}, label %{present}, label %{exhausted}")
                emitter.emit_line(f"{exhausted}:")
                finish_lengths(a_length, b_length)
                emitter.emit_line(f"{present}:")
            values = []
            for value_type, value, member in ((left_type, left, a_type), (right_type, right, b_type)):
                if collections.sequence_name(value_type) == "list":
                    values.append(collections.read_item(emitter, "list", member, value, str(index))[0])
                else:
                    slot = collections.field(emitter, collections.storage(emitter, value, 2), emitter.tuple_type(value_type), index)
                    values.append(emitter.emit_value(f"load {emitter.value_type(member)}, ptr {slot}"))
            compare(a_type, values[0], b_type, values[1])
        a_length = emitter.emit_value(f"load i64, ptr {left}")
        b_length = emitter.emit_value(f"load i64, ptr {right}")
    finish_lengths(a_length, b_length)
    emitter.emit_line(f"{done}:")
    return emitter.emit_value(f"load i1, ptr {result}")


def search(emitter, operation, value_type, receiver, arguments, node):
    semantic = emitter.runtime_value_type(node.args[0])
    if semantic is None:
        # Class tokens have an ABI, but are not ordinary analyzed instances.
        # Do not instantiate type[T] late just to reject unsupported equality.
        raise LLVMUnsupported("LLVM tuple/view searches do not support class-token needles", node)
    expected = tagged.effective_type(semantic, arguments[0][0])
    representation = analyzed_representation(node.func.value)
    query_representation = analyzed_representation(node.args[0])
    if representation is not None or query_representation is not None:
        if collections.builtin_name(value_type) == "tuple":
            # Validate each fixed slot independently. Merging heterogeneous tuple
            # items first can discard conflicting formats before we compare them.
            members = tuple(value_type.generic_types.values())
            parts = representation.arguments if representation is not None else (None,) * len(members)
            items = zip(members, parts, strict=True)
        else:
            protocol = resolve_iterable_protocol(value_type, representation, NATIVE_ENVIRONMENT.builtins)
            items = ((protocol.item_type, protocol.item_representation),)
        for item in items:
            check_representations(emitter, node, item, (semantic, query_representation))
    result = emitter.emit_value("alloca i64")
    position = emitter.emit_value("alloca i64")
    emitter.emit_line(f"store i64 {'0' if operation == 'count' else '-1'}, ptr {result}")
    emitter.emit_line(f"store i64 0, ptr {position}")
    done = emitter.new_label("search.done")
    start, stop = "0", "9223372036854775807"
    if operation == "index" and len(arguments) > 1:
        length = emitter.emit_value(f"load i64, ptr {receiver}")
        bounds = []
        for argument in arguments[1:]:
            value = emitter.index_integer(*argument, node, "LLVM sequence.index bounds require integers")
            negative = emitter.emit_value(f"icmp slt i64 {value}, 0")
            translated = emitter.emit_value(f"add i64 {value}, {length}")
            bound = emitter.emit_value(f"select i1 {negative}, i64 {translated}, i64 {value}")
            bounds.append(bound)
        start = bounds[0]
        if len(bounds) == 2:
            stop = bounds[1]

    def consume(actual, value):
        index = emitter.emit_value(f"load i64, ptr {position}")
        following = emitter.new_label("search.next")
        if operation == "index":
            above = emitter.emit_value(f"icmp sge i64 {index}, {start}")
            below = emitter.emit_value(f"icmp slt i64 {index}, {stop}")
            bounded = emitter.emit_value(f"and i1 {above}, {below}")
            compare = emitter.new_label("search.compare")
            emitter.emit_line(f"br i1 {bounded}, label %{compare}, label %{following}")
            emitter.emit_line(f"{compare}:")
        matches = equal_value(emitter, actual, value, expected, arguments[0][1], node)
        previous = emitter.emit_value(f"load i64, ptr {result}")
        found = emitter.new_label("search.found")
        emitter.emit_line(f"br i1 {matches}, label %{found}, label %{following}")
        emitter.emit_line(f"{found}:")
        value = emitter.emit_value(f"add i64 {previous}, 1") if operation == "count" else index
        emitter.emit_line(f"store i64 {value}, ptr {result}")
        emitter.emit_line(f"br label %{following if operation == 'count' else done}")
        emitter.emit_line(f"{following}:")
        next_index = emitter.emit_value(f"add i64 {index}, 1")
        emitter.emit_line(f"store i64 {next_index}, ptr {position}")

    collections.loop(emitter, value_type, receiver, consume, node)
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    result = emitter.emit_value(f"load i64, ptr {result}")
    if operation == "count":
        return "i64", result
    found = emitter.emit_value(f"icmp sge i64 {result}, 0")
    if operation == "__contains__":
        return "i1", found
    name = value_type.generic_name
    emitter.guard_exception(node, found, "ValueError", f"{name}.{operation}(x): x not in {name}")
    if operation == "remove":
        # Python deletes a slice at the matched position: a callback that
        # already removed that position makes deletion a successful no-op.
        size = emitter.llvm_size(emitter.value_type(collections.item_type(value_type)))
        emitter.emit_line(f"call i1 @pyjs.list.remove(ptr {receiver}, i64 {result}, i64 {size})")
        return "void", ""
    return "i64", result
