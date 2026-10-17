"""Set-like view operations over the existing mapping and iterable layouts."""

from pyjs.analysis.analyzer import (
    analyzed_iterable_protocol,
    analyzed_value_type,
    iterable_item_type,
    runtime_dunder_methods,
)
from pyjs.analysis.objects import Function, List, UnionType
from pyjs.analysis.type_relations import get_type_members, same_analyzer_type

from . import calls, comparisons, mapping_keys, protocols
from . import collection_ops as collections
from .errors import LLVMUnsupported

VIEWS = {"KeysView", "ItemsView"}
SETLIKE = {*VIEWS, "set", "frozenset"}
RELATIONS = {*collections.COMPARISONS, "__dynamic_eq__", "__dynamic_ne__"}


def retain(node):
    target = getattr(node.func, "obj", None)
    if (not isinstance(target, Function) or target.cls is None or not target.cls.container.scope.is_builtins
            or target.name not in {"isdisjoint", "__contains__", "count", "index", "remove", *RELATIONS}):
        return
    argument = node.args[0] if node.args else next(
        (keyword.value for keyword in node.keywords if target.params and keyword.arg == target.params[0].arg), None)
    if argument is None:
        return
    receiver = analyzed_value_type(node.func.value)
    other = analyzed_value_type(argument)
    if target.name in RELATIONS:
        retain_nested(node, receiver, other)
        return
    if target.name in {"__contains__", "count", "index", "remove"} and receiver.generic_name in {
            "list", "tuple", "ValuesView", "Iterable", "Iterator", "Generator"}:
        retain_nested(node, iterable_item_type(receiver), other)
    if target.cls.generic_name not in SETLIKE or target.name not in {"isdisjoint", "__contains__"}:
        return
    if receiver.generic_name not in VIEWS and collections.builtin_name(other) not in VIEWS:
        return
    key = next(iter(receiver.generic_types.values()))
    mapping_keys.retain_key(node, key)
    if isinstance(argument, List) and not argument.elts:
        return  # No query value or query-only callback can be consumed.
    item = other if target.name == "__contains__" else analyzed_iterable_protocol(argument).item_type
    retain_nested(node, iterable_item_type(receiver), item)
    if collections.builtin_name(other) in {"set", "frozenset", "KeysView"}:
        # Size-based lookup can hash either whole item tuple against set/key-view
        # storage, including its value's hash.
        mapping_keys.retain_key(node, item)
        if target.name != "__contains__":
            # Forward lookup hashes the receiver's tuple, not the peer's.
            # Their value classes can differ (a base class and its subtype).
            mapping_keys.retain_key(node, analyzed_iterable_protocol(node.func.value).item_type)
    # isdisjoint may scan either set-like operand. Keep query-only protocols as
    # well as the stored key's callbacks, including reached virtual overrides.
    if receiver.generic_name == "KeysView":
        mapping_keys.retain_key(node, item)
    elif receiver.generic_name == "ItemsView" and collections.builtin_name(item) == "tuple" and item.generic_types:
        fields = tuple(item.generic_types.values())
        mapping_keys.retain_key(node, fields[0])
        node.runtime_protocols = (*getattr(node, "runtime_protocols", ()),
                                  (tuple(receiver.generic_types.values())[1], ("__eq__",)),
                                  (fields[-1], ("__eq__",)))


def retain_nested(node, left, right):
    """Follow paired container slots to the view comparisons emission consumes.

    A single view type cannot say whether its values will be hashed: item-view
    peers only compare values, while key-view/set peers hash the entire tuple.
    Keep both operand types, including when views occur inside other containers.
    """
    pending, seen = [(left, right, False)], set()
    while pending:
        left, right, within_view = pending.pop()
        if (left, right, within_view) in seen:
            continue
        seen.add((left, right, within_view))
        a_members, b_members = get_type_members(left), get_type_members(right)
        if len(a_members) > 1 or len(b_members) > 1:
            pending.extend((a, b, within_view) for a in a_members for b in b_members)
            continue
        a_name, b_name = collections.builtin_name(left), collections.builtin_name(right)
        if {a_name, b_name} <= SETLIKE and {a_name, b_name} & VIEWS:
            # Dynamic/union comparison calls have no builtin runtime_dunders
            # declaration. Their implicit callbacks still receive members,
            # not the view/container passed to the source-level operation.
            node.runtime_member_callbacks = True
            a_item, b_item = (iterable_item_type(value) for value in (left, right))
            # ItemsView-to-ItemsView lookup hashes keys, not unhashable values.
            hashed = ((next(iter(value.generic_types.values())) for value in (left, right))
                      if a_name == b_name == "ItemsView" else (a_item, b_item))
            for key in hashed:
                mapping_keys.retain_key(node, key)
            pending.append((a_item, b_item, True))
        elif a_name == b_name and a_name in {"list", "tuple", "dict"}:
            a_items, b_items = (tuple(value.generic_types.values()) for value in (left, right))
            if a_name == "tuple":
                if left.tuple_variadic:
                    a_items *= len(b_items)
                elif right.tuple_variadic:
                    b_items *= len(a_items)
            pending.extend((a, b, within_view) for a, b in zip(a_items, b_items, strict=False))
        elif within_view:
            # Include declaration-only and subclass-introduced value equality,
            # without inventing a hash requirement for these contained values.
            required = tuple(protocol for value in (left, right)
                             for protocol in mapping_keys.protocols(value, ("__eq__",)))
            node.runtime_protocols = tuple(dict.fromkeys((*getattr(node, "runtime_protocols", ()), *required)))
            methods = (method for value, names in required for method in runtime_dunder_methods(value, *names))
            node.runtime_methods = tuple(dict.fromkeys((*getattr(node, "runtime_methods", ()), *methods)))


def contains(e, view_type, view, item_type, item, node):
    if view_type.generic_name == "KeysView":
        # A key view does not know its mapping's value layout. Presence must
        # come from the key index, never a fabricated value-slot stride.
        source = e.emit_value(f"load ptr, ptr {view}")
        index = lookup_index(e, source, view_type, item_type, item, node)
        return e.emit_value(f"icmp sge i64 {index}, 0")
    if isinstance(item_type, UnionType) or collections.builtin_name(item_type) == "object":
        raise LLVMUnsupported("LLVM item view membership needs a concrete item type", node)
    fields = tuple(item_type.generic_types.values()) if collections.builtin_name(item_type) == "tuple" else ()
    if not fields or not item_type.tuple_variadic and len(fields) != 2:
        return "false"
    source = e.emit_value(f"load ptr, ptr {view}")
    root = calls.root_values(e, view, item)
    result = e.emit_value("alloca i1")
    e.emit_line(f"store i1 false, ptr {result}")
    compare, done = e.new_label("view.item.compare"), e.new_label("view.item.done")
    if item_type.tuple_variadic:
        length = e.emit_value(f"load i64, ptr {item}")
        pair = e.emit_value(f"icmp eq i64 {length}, 2")
        unpack = e.new_label("view.item.unpack")
        e.emit_line(f"br i1 {pair}, label %{unpack}, label %{done}")
        e.emit_line(f"{unpack}:")
        query_type = expected = fields[0]
        key, expected_value = (collections.read_item(e, "tuple", query_type, item, str(index))[0]
                               for index in range(2))
    else:
        (query_type, key), (expected, expected_value) = collections.tuple_items(e, item_type, item)
    index = lookup_index(e, source, view_type, query_type, key, node)
    present = e.emit_value(f"icmp sge i64 {index}, 0")
    e.emit_line(f"br i1 {present}, label %{compare}, label %{done}")
    e.emit_line(f"{compare}:")
    value_type = tuple(view_type.generic_types.values())[1]
    storage = e.value_type(value_type)
    slot = mapping_keys.value_slot(e, source, index, e.llvm_size(storage))
    value = e.emit_value(f"load {storage}, ptr {slot}")
    equal = comparisons.equal_value(e, value_type, value, expected, expected_value, node)
    e.emit_line(f"store i1 {equal}, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    present = e.emit_value(f"load i1, ptr {result}")
    calls.pop_roots(e, root)
    return present


def lookup_index(e, source, mapping_type, query_type, query, node):
    key_type = next(iter(mapping_type.generic_types.values()))
    if not same_analyzer_type(key_type, query_type):
        names = {collections.builtin_name(member) for semantic in (key_type, query_type)
                 for member in get_type_members(semantic)}
        if names <= {"int", "float", "bool", "NoneType", "str", "bytes"}:
            # Read-only numeric lookup compares each domain exactly. Coercing
            # into the stored domain would truncate fractions or round wide ints.
            kind = e.value_type(key_type)
            index, result = e.emit_value("alloca i64"), e.emit_value("alloca i64")
            e.emit_line(f"store i64 0, ptr {index}")
            e.emit_line(f"store i64 -1, ptr {result}")
            check, body, found, advance, done = (e.new_label("view.lookup." + label)
                                                for label in ("check", "body", "found", "advance", "done"))
            e.emit_line(f"br label %{check}")
            e.emit_line(f"{check}:")
            position = e.emit_value(f"load i64, ptr {index}")
            length = e.emit_value(f"load i64, ptr {source}")
            more = e.emit_value(f"icmp ult i64 {position}, {length}")
            e.emit_line(f"br i1 {more}, label %{body}, label %{done}")
            e.emit_line(f"{body}:")
            slot = e.emit_value(f"getelementptr {kind}, ptr {collections.storage(e, source, 2)}, i64 {position}")
            key = e.emit_value(f"load {kind}, ptr {slot}")
            equal = comparisons.equal_value(e, key_type, key, query_type, query, node)
            e.emit_line(f"br i1 {equal}, label %{found}, label %{advance}")
            e.emit_line(f"{found}:")
            e.emit_line(f"store i64 {position}, ptr {result}")
            e.emit_line(f"br label %{done}")
            e.emit_line(f"{advance}:")
            following = e.emit_value(f"add i64 {position}, 1")
            e.emit_line(f"store i64 {following}, ptr {index}")
            e.emit_line(f"br label %{check}")
            e.emit_line(f"{done}:")
            return e.emit_value(f"load i64, ptr {result}")
    return e.dictionary_index(source, key_type, e.value_type(query_type), query, node, source_type=query_type)


def scan(e, source_type, source, target_type, target, node, *, disjoint=True):
    roots = calls.root_values(e, source, target)
    source_type, source, cursor = protocols.consumer(e, source_type, source, node)
    kind = e.value_type(collections.item_type(source_type))
    (item_slot,), frame = calls.value_slots(e, [kind])
    result = e.emit_value("alloca i1")
    e.emit_line(f"store i1 true, ptr {result}")
    done = e.new_label("view.disjoint.done")

    def consume(actual, value):
        # A comparison may clear the source mapping. Retain its current item
        # independently; the common exit also handles a short-circuit match.
        e.emit_line(f"store {kind} {value}, ptr {item_slot}")
        if target_type.generic_name in VIEWS:
            matched = contains(e, target_type, target, actual, value, node)
        else:
            index = lookup_index(e, target, target_type, actual, value, node)
            matched = e.emit_value(f"icmp sge i64 {index}, 0")
        accepted = e.emit_value(f"xor i1 {matched}, true") if disjoint else matched
        e.emit_line(f"store i1 {accepted}, ptr {result}")
        following = e.new_label("view.disjoint.next")
        e.emit_line(f"br i1 {accepted}, label %{following}, label %{done}")
        e.emit_line(f"{following}:")

    collections.loop(e, source_type, source, consume, node, acquired=True)
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    calls.pop_roots(e, frame)
    calls.pop_roots(e, cursor)
    calls.pop_roots(e, roots)
    return e.emit_value(f"load i1, ptr {result}")


def compare(e, operation, left_type, left, right_type, right, node, *, identity=False):
    if any(collections.builtin_name(semantic) not in SETLIKE for semantic in (left_type, right_type)):
        if operation in {"__eq__", "__ne__"}:
            return str(operation == "__ne__").lower()
        raise LLVMUnsupported("LLVM view ordering requires concrete set-like operands", node)
    # Sets defer equality to views. Unlike disjointness, relational alias
    # comparisons still visit/hash members; there is no identity shortcut.
    if operation in {"__gt__", "__ge__"} or (
            operation in {"__eq__", "__ne__"} and left_type.generic_name not in VIEWS):
        left_type, right_type, left, right = right_type, left_type, right, left
    sources = [e.emit_value(f"load ptr, ptr {value}") if semantic.generic_name in VIEWS else value
               for semantic, value in ((left_type, left), (right_type, right))]
    length, other_length = (e.emit_value(f"load i64, ptr {value}") for value in sources)
    predicate = "eq" if operation in {"__eq__", "__ne__"} else (
        "ult" if operation in {"__lt__", "__gt__"} else "ule")
    fits = e.emit_value(f"icmp {predicate} i64 {length}, {other_length}")
    result = e.emit_value("alloca i1")
    same = e.emit_value(f"icmp eq ptr {left}, {right}") if identity else "false"
    e.emit_line(f"store i1 {same}, ptr {result}")
    if identity:
        # Container member equality has an identity shortcut even though a
        # direct `view == view` must still perform its observable key lookups.
        different = e.emit_value(f"xor i1 {same}, true")
        fits = e.emit_value(f"and i1 {fits}, {different}")
    check, done = e.new_label("view.compare.items"), e.new_label("view.compare.done")
    e.emit_line(f"br i1 {fits}, label %{check}, label %{done}")
    e.emit_line(f"{check}:")
    matched = scan(e, left_type, left, right_type, right, node, disjoint=False)
    e.emit_line(f"store i1 {matched}, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    result = e.emit_value(f"load i1, ptr {result}")
    return e.emit_value(f"xor i1 {result}, true") if operation == "__ne__" else result


def disjoint(e, left_type, left, right_type, right, node):
    if collections.builtin_name(right_type) not in {*VIEWS, "set", "frozenset"}:
        return scan(e, right_type, right, left_type, left, node)
    source = e.emit_value(f"load ptr, ptr {left}")
    other = e.emit_value(f"load ptr, ptr {right}") if right_type.generic_name in VIEWS else right
    length, other_length = (e.emit_value(f"load i64, ptr {value}") for value in (source, other))
    result = e.emit_value("alloca i1")
    identical, choose, forward, reverse, done = (e.new_label("view.disjoint." + part)
                                                for part in ("same", "choose", "forward", "reverse", "done"))
    same = e.emit_value(f"icmp eq ptr {left}, {right}")
    e.emit_line(f"br i1 {same}, label %{identical}, label %{choose}")
    e.emit_line(f"{identical}:")
    empty = e.emit_value(f"icmp eq i64 {length}, 0")
    e.emit_line(f"store i1 {empty}, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{choose}:")
    smaller = e.emit_value(f"icmp ult i64 {length}, {other_length}")
    e.emit_line(f"br i1 {smaller}, label %{forward}, label %{reverse}")
    for label, first_type, first, second_type, second in (
        (forward, left_type, left, right_type, right),
        (reverse, right_type, right, left_type, left),
    ):
        e.emit_line(f"{label}:")
        value = scan(e, first_type, first, second_type, second, node)
        e.emit_line(f"store i1 {value}, ptr {result}")
        e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return e.emit_value(f"load i1, ptr {result}")
