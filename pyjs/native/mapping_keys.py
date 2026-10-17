"""Typed adapters for callback-key hashes and mutation-safe comparisons."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type, runtime_dunder_methods
from pyjs.analysis.objects import Class
from pyjs.analysis.type_relations import is_return_type_compatible, same_analyzer_type
from pyjs.analysis.value_representation import analyzed_representation

from . import calls, comparisons, hashing, nullable, tagged
from .errors import LLVMUnsupported

KEY_ARGUMENT_METHODS = {
    "__getitem__", "__setitem__", "__delitem__", "__contains__",
    "get", "setdefault", "pop", "add", "remove", "discard",
}
MEMBER_ARGUMENT_METHODS = KEY_ARGUMENT_METHODS | {
    "update", "union", "intersection", "difference", "symmetric_difference",
    "intersection_update", "difference_update", "symmetric_difference_update",
    "issubset", "issuperset", "isdisjoint",
    "__or__", "__ror__", "__and__", "__sub__", "__xor__",
    "__ior__", "__iand__", "__isub__", "__ixor__",
    "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
}


def uses_callbacks(semantic):
    return bool(tagged.members(semantic)) or (isinstance(semantic, Class)
            and (semantic.generic_name in {"tuple", "frozenset"}
                 or not getattr(semantic.py_obj, "__builtin__", False)))


def can_reuse(e, expected, actual):
    """Cached keys can be copied only when their semantic and storage contracts agree."""
    compatible = (uses_callbacks(expected) and uses_callbacks(actual)
            and is_return_type_compatible(expected, actual)
            and e.value_type(expected) == e.value_type(actual))
    if compatible:
        from .collection_ops import require_matching_layout
        require_matching_layout(actual, expected, e.allocation_node)
    return compatible


def comparable(e, left, right):
    """Read-only key comparison keeps layouts, unlike copying stored keys."""
    return (same_analyzer_type(left, right)
            or left in e.module.classes and right in e.module.classes
            and e.hierarchy_root(left) is e.hierarchy_root(right))


def protocols(semantic, names=("__hash__", "__eq__")):
    """Retain callbacks on reached subclasses, not just their static bases."""
    if members := tagged.members(semantic):
        return tuple(item for member in members for item in protocols(member, names))
    if not uses_callbacks(semantic):
        return ()
    if semantic.container.scope.is_builtins and semantic.generic_name in {"tuple", "frozenset"}:
        return tuple(item for member in semantic.generic_types.values() for item in protocols(member, names))
    return tuple((semantic, (name,)) for name in names)


def formats_missing_key(node):
    if not isinstance(node, ast.Call):
        return False
    name = getattr(getattr(node.func, "obj", None), "name", None)
    return name in {"__getitem__", "__delitem__", "remove"} or name == "pop" and len(node.args) == 1


def is_tuple_query(stored, query):
    """Read-only tuple queries keep both layouts; insertion never uses this gate."""
    return all(isinstance(value, Class) and value.container.scope.is_builtins
               and value.generic_name == "tuple" for value in (stored, query))


def retain_key(node, semantic, *, missing_key=False):
    required = (*protocols(semantic), *(protocols(semantic, ("__repr__",)) if missing_key else ()))
    node.runtime_protocols = tuple(dict.fromkeys((*getattr(node, "runtime_protocols", ()), *required)))
    # Declaration-only keys still need adapters even without a reached constructor.
    methods = (method for receiver, names in required for method in runtime_dunder_methods(receiver, *names))
    node.runtime_methods = tuple(dict.fromkeys((*getattr(node, "runtime_methods", ()), *methods)))


def retain(node, semantic, *, missing_key=False):
    if (isinstance(semantic, Class) and semantic.container.scope.is_builtins
            and semantic.generic_name in {"dict", "set", "frozenset"}):
        members = tuple(semantic.generic_types.values())
        if members:
            retain_key(node, members[0], missing_key=missing_key)


def retain_receiver(node):
    """Retain the receiver's mapping contract for authored or lowered calls."""
    call = node.operand if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) else node
    if isinstance(call, ast.Call):
        # An operator's result need not invoke any key callbacks. For example,
        # len(list[set[Key]][0]) does not hash, compare or format a Key.
        target = getattr(call.func, "obj", None)
        if (isinstance(call.func, ast.Attribute) and not getattr(target, "is_classmethod", False)
                and getattr(getattr(target, "cls", None), "generic_name", None) in {"dict", "set", "frozenset"}):
            receiver = analyzed_value_type(call.func.value)
            retain(call, receiver, missing_key=formats_missing_key(call))
            if (isinstance(receiver, Class) and receiver.container.scope.is_builtins
                    and call.args and target.name in MEMBER_ARGUMENT_METHODS):
                # Even a failed lookup/removal can save its query through
                # hashing, or an existing key through equality. Bulk methods
                # can do the same with members of iterable operands. Effects
                # belong to members, not the builtin method's placeholder body.
                call.runtime_member_callbacks = True
            if (isinstance(receiver, Class) and receiver.container.scope.is_builtins
                    and target.name in {"__getitem__", "__contains__"} and call.args):
                stored = next(iter(receiver.generic_types.values()))
                query = analyzed_value_type(call.args[0])
                if is_tuple_query(stored, query):
                    # Lookup hashes the actual query and can format it on a miss;
                    # its member classes need not occur in any stored key.
                    # Other methods retain their declared key-argument contracts;
                    # assignable subclass queries are covered by stored protocols.
                    retain_key(call, query, missing_key=formats_missing_key(call))
    return node


def prepare(e, node):
    semantic = analyzed_value_type(node)
    if (isinstance(semantic, Class) and semantic.container.scope.is_builtins
            and semantic.generic_name in {"dict", "set", "frozenset"}):
        members = tuple(semantic.generic_types.values())
        e.module.uses_key_callbacks |= bool(members and uses_callbacks(members[0]))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and not getattr(getattr(node.func, "obj", None), "is_classmethod", False)
            and getattr(getattr(getattr(node.func, "obj", None), "cls", None), "generic_name", None)
                in {"dict", "set", "frozenset", "KeysView", "ItemsView"}):
        receiver = analyzed_value_type(node.func.value)
        if (isinstance(receiver, Class) and receiver.container.scope.is_builtins
                and receiver.generic_name in {"dict", "set", "frozenset", "KeysView", "ItemsView"}):
            # Receiver operations need mapping support even when no mapping
            # is constructed and their result is scalar or None (get/pop/add).
            e.module.uses_mappings = e.module.uses_collections = e.module.uses_strings = True
            key = next(iter(receiver.generic_types.values()))
            custom = uses_callbacks(key)
            if receiver.generic_name in {"KeysView", "ItemsView"}:
                custom |= any("__hash__" in names for _, names in getattr(node, "runtime_protocols", ()))
            e.module.uses_key_callbacks |= custom
            if tagged.members(key) and node.args and node.func.obj.name in KEY_ARGUMENT_METHODS:
                # Builtin argument binding can already pack the value by the
                # time find() runs. Validate its original tag before that step.
                from .collection_ops import require_matching_layout
                require_matching_layout(analyzed_value_type(node.args[0]), key, node.args[0])
            if formats_missing_key(node):
                e.module.uses_repr |= custom
                # Scalar bytes (including optional keys) bypass the buffered
                # callback formatter but still need their quoted byte repr.
                e.module.uses_text_extra |= nullable.contains(key, "bytes")
    # Generated key comparators can descend into tuples without an authored
    # comparison (e.g. get or issubset on declaration-only mapping receivers).
    e.module.uses_ordering |= e.module.uses_key_callbacks


def find(e, receiver, semantic, kind, key, node, *, known_hash=None, query_type=None):
    actual = e.value_semantics.get((kind, key), semantic)
    # Read-only callers can retain a separately validated query layout. The
    # comparator loads each side using its own type; no stored key is retyped.
    query = query_type if query_type is not None else semantic
    if query is semantic:
        from .collection_ops import require_matching_layout
        require_matching_layout(actual, semantic, node)
        kind, key = e.coerce_value(kind, key, e.value_type(semantic), node, semantic=semantic)
    # Hash and equality can collect or release the container through aliases.
    (owner, slot), frame = calls.value_slots(e, ["ptr", kind])
    e.emit_line(f"store ptr {receiver}, ptr {owner}")
    e.emit_line(f"store {kind} {key}, ptr {slot}")
    hashed = hashing.hash_value(e, query, kind, key, node) if known_hash is None else known_hash
    symbol = comparator(e, semantic, node, query=query)
    index = e.emit_value(
        f"call i64 @pyjs.dict.find.hashed(ptr {e.load_local('__arena')}, "
        f"ptr {e.load_local('__heap') if e.module.uses_gc else 'null'}, "
        f"ptr {e.load_local('__exception') if e.module.uses_exceptions else 'null'}, "
        f"ptr {receiver}, ptr {slot}, i64 {hashed}, ptr @{symbol}, i64 {e.llvm_size(kind)})")
    if e.module.uses_exceptions:
        e.check_active_exception(node)
    calls.pop_roots(e, frame)
    return index, slot, hashed


def comparator(e, semantic, node, *, query=None):
    return comparisons.callback(e, semantic, query if query is not None else semantic, node)


def update(e, receiver, source, semantic, value_size, node, *, keys_only=False, default_slot=None, copy_empty=True):
    suffix = "keys" if keys_only else "hashed"
    extra = ""
    if keys_only:
        if default_slot is None:
            default_slot = e.emit_value("alloca i1")
            e.emit_line(f"store i1 true, ptr {default_slot}")
        extra = f", ptr {default_slot}, i1 {str(copy_empty).lower()}"
    status = e.emit_value(
        f"call i64 @pyjs.dict.update.{suffix}(ptr {e.load_local('__arena')}, "
        f"ptr {e.load_local('__heap') if e.module.uses_gc else 'null'}, "
        f"ptr {e.load_local('__exception') if e.module.uses_exceptions else 'null'}, "
        f"ptr {receiver}, ptr {source}, i64 {value_size}, ptr @{comparator(e, semantic, node)}, "
        f"i64 {e.llvm_size(e.value_type(semantic))}{extra})")
    if e.module.uses_exceptions:
        e.check_active_exception(node)
    if not keys_only:
        unchanged = e.emit_value(f"icmp ne i64 {status}, -1")
        e.guard_exception(node, unchanged, "RuntimeError", "dict mutated during update")
    allocated = e.emit_value(f"icmp ne i64 {status}, 0")
    e.guard_exception(node, allocated, "MemoryError", "native mapping allocation failed")
    return "void", ""


def value_slot(e, receiver, index, value_size):
    address = e.emit_value(f"getelementptr %pyjs.dict, ptr {receiver}, i32 0, i32 3")
    values = e.emit_value(f"load ptr, ptr {address}")
    offset = e.emit_value(f"mul i64 {index}, {value_size}")
    return e.emit_value(f"getelementptr i8, ptr {values}, i64 {offset}")


def update_converted(e, target, target_type, source, source_type, node, *, source_node=None):
    """Merge different value layouts, preserving dict update's cached keys.

    The ordinary same-layout path remains the compiled runtime bulk operation.
    This typed loop converts each captured value before publication; converting
    a snapshot of the whole source would hide later callback mutations.
    """
    from .collection_ops import convert_item, storage

    key_type, expected = e.dictionary_types(target_type)
    source_key, actual = e.dictionary_types(source_type)
    representation = analyzed_representation(source_node if source_node is not None else node.args[0])
    value_representation = (representation.arguments[1]
                            if representation is not None and len(representation.arguments) > 1 else None)
    if not same_analyzer_type(source_key, key_type):
        raise LLVMUnsupported("LLVM dictionary update requires matching key layouts", node)
    key_kind, source_kind, kind = (e.value_type(member) for member in (key_type, actual, expected))
    size = e.llvm_size(kind)
    slots, frame = calls.value_slots(e, ["ptr", "ptr", key_kind, source_kind, kind])
    e.emit_line(f"store ptr {target}, ptr {slots[0]}")
    e.emit_line(f"store ptr {source}, ptr {slots[1]}")
    prepare, check, body, done = (e.new_label("dict.convert." + label)
                                 for label in ("prepare", "check", "body", "done"))
    length = e.emit_value(f"load i64, ptr {source}")
    nonempty = e.emit_value(f"icmp ne i64 {length}, 0")
    e.emit_line(f"br i1 {nonempty}, label %{prepare}, label %{done}")
    e.emit_line(f"{prepare}:")
    tracked = e.emit_value(f"call i1 @pyjs.dict.track.order(ptr {e.load_local('__arena')}, ptr {source})")
    e.guard_exception(node, tracked, "MemoryError", "native mapping allocation failed")
    custom = uses_callbacks(key_type)
    if custom:
        empty = e.emit_value(f"icmp eq i64 {e.emit_value(f'load i64, ptr {target}')}, 0")
    cursor = e.emit_value("alloca i64")
    e.emit_line(f"store i64 0, ptr {cursor}")
    e.emit_line(f"br label %{check}")
    e.emit_line(f"{check}:")
    position = e.emit_value(f"load i64, ptr {cursor}")
    index = e.emit_value(f"call i64 @pyjs.dict.repr.index(ptr {source}, i64 {position})")
    count = e.emit_value(f"load i64, ptr {source}")
    e.emit_line(f"br i1 {e.emit_value(f'icmp ult i64 {index}, {count}')}, label %{body}, label %{done}")
    e.emit_line(f"{body}:")
    captured = []
    for field, storage_kind, root in ((2, key_kind, slots[2]), (3, source_kind, slots[3])):
        address = e.emit_value(f"getelementptr {storage_kind}, ptr {storage(e, source, field)}, i64 {index}")
        value = e.emit_value(f"load {storage_kind}, ptr {address}")
        e.emit_line(f"store {storage_kind} {value}, ptr {root}")
        captured.append(value)
    key, item = captured
    ordinal = e.emit_value(f"getelementptr i64, ptr {storage(e, source, 6)}, i64 {index}")
    ordinal = e.emit_value(f"load i64, ptr {ordinal}")
    e.emit_line(f"store i64 {e.emit_value(f'add i64 {ordinal}, 1')}, ptr {cursor}")
    if custom:
        address = e.emit_value(f"getelementptr i64, ptr {storage(e, source, 8)}, i64 {index}")
        hashed = e.emit_value(f"load i64, ptr {address}")
    # A storage load has no expression node carrying its nested representation.
    # Boxing must retain it in the layout token, just like ordinary assignment.
    _, item = convert_item(e, actual, expected, item, node, representation=value_representation)
    e.emit_line(f"store {kind} {item}, ptr {slots[4]}")
    if custom:
        # An initially empty destination copies even keys that have become equal
        # since their insertion into the source. Never rehash stored keys.
        # Like the same-layout runtime path, this does not model CPython's
        # deletion-history-dependent choice between copying and comparing keys.
        append, merge, publish = (e.new_label("dict.convert." + label) for label in ("append", "merge", "publish"))
        output = e.emit_value("alloca ptr")
        e.emit_line(f"br i1 {empty}, label %{append}, label %{merge}")
        e.emit_line(f"{append}:")
        slot = e.allocated_value(f"call ptr @pyjs.dict.append.hashed(ptr {e.load_local('__arena')}, "
                                 f"ptr {target}, ptr {slots[2]}, i64 {e.llvm_size(key_kind)}, i64 {size}, i64 {hashed})")
        e.emit_line(f"store ptr {slot}, ptr {output}")
        e.emit_line(f"br label %{publish}")
        e.emit_line(f"{merge}:")
        slot = lookup(e, target, key_type, key_kind, key, size, node, insert=True, known_hash=hashed)
        e.emit_line(f"store ptr {slot}, ptr {output}")
        e.emit_line(f"br label %{publish}")
        e.emit_line(f"{publish}:")
        slot = e.emit_value(f"load ptr, ptr {output}")
    else:
        slot = e.dictionary_set_slot(target, key_type, key_kind, key, size, node)
    e.emit_line(f"store {kind} {item}, ptr {slot}")
    unchanged = e.emit_value(f"icmp eq i64 {e.emit_value(f'load i64, ptr {source}')}, {length}")
    e.guard_exception(node, unchanged, "RuntimeError", "dict mutated during update")
    e.emit_line(f"br label %{check}")
    e.emit_line(f"{done}:")
    calls.pop_roots(e, frame)


def compare_sets(e, operation, semantic, left, right, node):
    if operation in {"__gt__", "__ge__", "issuperset"}:
        left, right = right, left
    relation = 3 if operation == "isdisjoint" else 2 if operation in {"__eq__", "__ne__"} else (
        1 if operation in {"__lt__", "__gt__"} else 0)
    status = e.emit_value(
        f"call i64 @pyjs.set.relation.hashed(ptr {e.load_local('__arena')}, "
        f"ptr {e.load_local('__heap') if e.module.uses_gc else 'null'}, "
        f"ptr {e.load_local('__exception') if e.module.uses_exceptions else 'null'}, "
        f"ptr {left}, ptr {right}, ptr @{comparator(e, semantic, node)}, i8 {relation}, "
        f"i64 {e.llvm_size(e.value_type(semantic))})")
    if e.module.uses_exceptions:
        e.check_active_exception(node)
    allocated = e.emit_value(f"icmp ne i64 {status}, -3")
    e.guard_exception(node, allocated, "MemoryError", "native set comparison allocation failed")
    predicate = "eq" if operation == "__ne__" else "ne"
    return e.emit_value(f"icmp {predicate} i64 {status}, 0")


def set_operation(e, operation, semantic, left, right, node, *, result=None, matches=None):
    operands = f"ptr {left}, ptr {right}, " + (f"ptr {result}, " if result is not None else "")
    extra = f", i1 {str(matches).lower()}" if matches is not None else ""
    status = e.emit_value(
        f"call i64 @pyjs.set.{operation}.hashed(ptr {e.load_local('__arena')}, "
        f"ptr {e.load_local('__heap') if e.module.uses_gc else 'null'}, "
        f"ptr {e.load_local('__exception') if e.module.uses_exceptions else 'null'}, "
        f"{operands}ptr @{comparator(e, semantic, node)}, "
        f"i64 {e.llvm_size(e.value_type(semantic))}{extra})")
    if e.module.uses_exceptions:
        e.check_active_exception(node)
    allocated = e.emit_value(f"icmp ne i64 {status}, 0")
    e.guard_exception(node, allocated, "MemoryError", "native set allocation failed")


def lookup(e, receiver, semantic, kind, key, value_size, node, *, insert=False, default=None,
           known_hash=None, query_type=None):
    frame = None
    if default is not None:
        (slot,), frame = calls.value_slots(e, [default[0]])
        e.emit_line(f"store {default[0]} {default[1]}, ptr {slot}")
    index, key_slot, hashed = find(e, receiver, semantic, kind, key, node, known_hash=known_hash,
                                 query_type=query_type if not insert else None)
    result = e.emit_value("alloca ptr")
    e.emit_line(f"store ptr null, ptr {result}")
    found, absent, done = (e.new_label(name) for name in ("key.found", "key.absent", "key.done"))
    present = e.emit_value(f"icmp sge i64 {index}, 0")
    e.emit_line(f"br i1 {present}, label %{found}, label %{absent}")
    e.emit_line(f"{found}:")
    e.emit_line(f"store ptr {value_slot(e, receiver, index, value_size)}, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{absent}:")
    if insert:
        # Absence has already been established. Do not call __hash__/__eq__
        # again when growing or installing the insertion slot.
        value = e.allocated_value(
            f"call ptr @pyjs.dict.append.hashed(ptr {e.load_local('__arena')}, "
            f"ptr {receiver}, ptr {key_slot}, i64 {e.llvm_size(e.value_type(semantic))}, "
            f"i64 {value_size}, i64 {hashed})")
        e.emit_line(f"store ptr {value}, ptr {result}")
        if default is not None:
            e.emit_line(f"store {default[0]} {default[1]}, ptr {value}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    calls.pop_roots(e, frame)
    return e.emit_value(f"load ptr, ptr {result}")


def remove(e, receiver, semantic, arguments, value_kind, value_size, operation, node):
    result = frame = None
    if operation == "pop":
        (result,), frame = calls.value_slots(e, [value_kind])
    if result is not None and len(arguments) == 2:
        kind, fallback = arguments[1]
        e.emit_line(f"store {kind} {fallback}, ptr {result}")
    # The default may have just been boxed, independently of the call's input
    # roots. Hash/equality callbacks must not collect that fresh representation.
    if operation == "pop":
        # dict.pop skips hashing when empty, unlike get or indexed deletion.
        # Keep missing-key handling below shared with a populated lookup miss.
        selected = e.emit_value("alloca i64")
        e.emit_line(f"store i64 -1, ptr {selected}")
        length = e.emit_value(f"load i64, ptr {receiver}")
        nonempty = e.emit_value(f"icmp ne i64 {length}, 0")
        lookup, ready = e.new_label("key.pop.lookup"), e.new_label("key.pop.ready")
        e.emit_line(f"br i1 {nonempty}, label %{lookup}, label %{ready}")
        e.emit_line(f"{lookup}:")
        found, _, _ = find(e, receiver, semantic, *arguments[0], node)
        e.emit_line(f"store i64 {found}, ptr {selected}")
        e.emit_line(f"br label %{ready}")
        e.emit_line(f"{ready}:")
        index = e.emit_value(f"load i64, ptr {selected}")
    else:
        index, _, _ = find(e, receiver, semantic, *arguments[0], node)
    present = e.emit_value(f"icmp sge i64 {index}, 0")
    if operation != "discard" and not (operation == "pop" and len(arguments) == 2):
        e.guard_key(node, present, *arguments[0])
    removed, done = e.new_label("key.remove"), e.new_label("key.remove.done")
    e.emit_line(f"br i1 {present}, label %{removed}, label %{done}")
    e.emit_line(f"{removed}:")
    if result is not None:
        value = e.emit_value(f"load {value_kind}, ptr {value_slot(e, receiver, index, value_size)}")
        e.emit_line(f"store {value_kind} {value}, ptr {result}")
    e.emit_line(f"call void @pyjs.dict.remove.index(ptr {receiver}, i64 {index}, "
                f"i64 {e.llvm_size(e.value_type(semantic))}, i64 {value_size})")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    calls.pop_roots(e, frame)
    return (value_kind, e.emit_value(f"load {value_kind}, ptr {result}")) if result is not None else ("void", "")
