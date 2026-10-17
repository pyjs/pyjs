"""Eager callback consumers using the ordinary checked native call ABI."""

from pyjs.analysis.analyzer import analyzed_value_type, callable_value_type
from pyjs.analysis.objects import CallableClass, UnionType
from pyjs.analysis.type_relations import same_analyzer_type
from pyjs.analysis.value_representation import analyzed_representation

from . import callables, calls, comparisons, tagged
from . import collection_ops as collections
from .errors import LLVMUnsupported
from .runtime.sequences import SIZE


def sort_in_place(emitter, value_type, receiver, callback, key_node, reverse, node):
    if key_node is None and collections.builtin_name(collections.item_type(value_type)) in {"int", "bool", "float", "str", "bytes"}:
        collections.sort(emitter, value_type, receiver, reverse, node)
        return
    (saved_slot,), frame = calls.value_slots(emitter, ["ptr"])
    saved = emitter.allocated_value(f"call ptr @pyjs.collection.try.alloc({collections.owner(emitter)}, i64 {SIZE})")
    emitter.emit_line(f"store ptr {saved}, ptr {saved_slot}")
    emitter.emit_line(f"call void @pyjs.list.sort.detach(ptr {receiver}, ptr {saved})")
    outer = emitter.exception_target
    cleanup = emitter.new_label("sort.cleanup")
    done = emitter.new_label("sort.restored")
    emitter.exception_target = cleanup
    try:
        if key_node is None:
            collections.sort(emitter, value_type, saved, reverse, node)
        else:
            collections.sort_keyed(emitter, value_type, saved, callback, key_node, reverse, node)
    finally:
        emitter.exception_target = outer
    unchanged = emitter.emit_value(f"call i1 @pyjs.list.sort.restore(ptr {receiver}, ptr {saved})")
    calls.pop_roots(emitter, frame)
    emitter.guard_exception(node, unchanged, "ValueError", "list modified during sort")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{emitter.name(cleanup, 'block')}:")
    emitter.emit_line(f"call i1 @pyjs.list.sort.restore(ptr {receiver}, ptr {saved})")
    # Discard any inner keyed-sort frame bypassed by the error edge before
    # performing the checked pop of this scope's frame.
    calls.restore_roots(emitter, frame)
    calls.pop_roots(emitter, frame)
    emitter.branch_to_exception_target()
    emitter.emit_line(f"{done}:")


def signature(node, count):
    result = callable_value_type(node)
    if not isinstance(result, CallableClass) or result.parameter_types is None or not result.accepts_arity(count):
        raise LLVMUnsupported(f"LLVM callback requires a concrete {count}-argument signature", node)
    return result


def sort_structural(emitter, values, member, reverse, node, *, keys=None, key_type=None, less=None):
    """Stable merge passes; a failed callback leaves the last full permutation."""
    keys = values if keys is None else keys
    key_type = member if key_type is None else key_type
    inputs = [(values, member)] if keys == values else [(values, member), (keys, key_type)]
    slots, frame = calls.value_slots(emitter, ["ptr"] * (len(inputs) * 2))
    for slot, (value, _) in zip(slots[:len(inputs)], inputs, strict=True):
        emitter.emit_line(f"store ptr {value}, ptr {slot}")
    length = emitter.emit_value(f"load i64, ptr {values}")
    buffers = []
    for slot, (value, value_type) in zip(slots[len(inputs):], inputs, strict=True):
        kind = emitter.value_type(value_type)
        size = emitter.llvm_size(kind)
        scratch = emitter.allocated_value(f"call ptr @pyjs.list.new.owned({collections.owner(emitter)}, i64 {size}, i64 {length})")
        emitter.emit_line(f"store ptr {scratch}, ptr {slot}")
        buffers.append((collections.storage(emitter, value, 2), collections.storage(emitter, scratch, 2), kind, size))
    key_data, _, key_kind, _ = buffers[-1]
    width_slot, base_slot, a_slot, b_slot, output_slot, picked_slot = [emitter.emit_value("alloca i64") for _ in range(6)]
    emitter.emit_line(f"store i64 1, ptr {width_slot}")
    passes, start, runs, run, merge, choose, take_left, take_right, copy, commit, done = (
        emitter.new_label("sort." + label) for label in
        ("passes", "start", "runs", "run", "merge", "choose", "left", "right", "copy", "commit", "done"))
    emitter.emit_line(f"br label %{passes}")
    emitter.emit_line(f"{passes}:")
    width = emitter.emit_value(f"load i64, ptr {width_slot}")
    more = emitter.emit_value(f"icmp ult i64 {width}, {length}")
    emitter.emit_line(f"br i1 {more}, label %{start}, label %{done}")
    emitter.emit_line(f"{start}:")
    emitter.emit_line(f"store i64 0, ptr {base_slot}")
    emitter.emit_line(f"br label %{runs}")
    emitter.emit_line(f"{runs}:")
    base = emitter.emit_value(f"load i64, ptr {base_slot}")
    more = emitter.emit_value(f"icmp ult i64 {base}, {length}")
    emitter.emit_line(f"br i1 {more}, label %{run}, label %{commit}")
    emitter.emit_line(f"{run}:")
    middle = emitter.emit_value(f"add i64 {base}, {width}")
    end = emitter.emit_value(f"add i64 {middle}, {width}")
    bounds = []
    for bound in (middle, end):
        valid = emitter.emit_value(f"icmp ult i64 {bound}, {length}")
        bounds.append(emitter.emit_value(f"select i1 {valid}, i64 {bound}, i64 {length}"))
    middle, end = bounds
    for slot, initial in ((a_slot, base), (b_slot, middle), (output_slot, base)):
        emitter.emit_line(f"store i64 {initial}, ptr {slot}")
    emitter.emit_line(f"store i64 {end}, ptr {base_slot}")
    emitter.emit_line(f"br label %{merge}")
    emitter.emit_line(f"{merge}:")
    output = emitter.emit_value(f"load i64, ptr {output_slot}")
    more = emitter.emit_value(f"icmp ult i64 {output}, {end}")
    check = emitter.new_label("sort.available")
    emitter.emit_line(f"br i1 {more}, label %{check}, label %{runs}")
    emitter.emit_line(f"{check}:")
    a = emitter.emit_value(f"load i64, ptr {a_slot}")
    b = emitter.emit_value(f"load i64, ptr {b_slot}")
    a_valid = emitter.emit_value(f"icmp ult i64 {a}, {middle}")
    b_valid = emitter.emit_value(f"icmp ult i64 {b}, {end}")
    check_right = emitter.new_label("sort.available.right")
    emitter.emit_line(f"br i1 {a_valid}, label %{check_right}, label %{take_right}")
    emitter.emit_line(f"{check_right}:")
    emitter.emit_line(f"br i1 {b_valid}, label %{choose}, label %{take_left}")
    emitter.emit_line(f"{choose}:")
    # Reverse changes comparison direction, not tie preference. Keep the left
    # run first when neither key precedes the other, preserving stability.
    first = emitter.emit_value(f"select i1 {reverse}, i64 {a}, i64 {b}")
    second = emitter.emit_value(f"select i1 {reverse}, i64 {b}, i64 {a}")
    operands = []
    for index in (first, second):
        slot = emitter.emit_value(f"getelementptr {key_kind}, ptr {key_data}, i64 {index}")
        operands.append(emitter.emit_value(f"load {key_kind}, ptr {slot}"))
    before = (less(*operands) if less is not None else
              comparisons.order_value(emitter, "__lt__", key_type, operands[0], key_type, operands[1], node))
    emitter.emit_line(f"br i1 {before}, label %{take_right}, label %{take_left}")
    for label, position, slot in ((take_left, a, a_slot), (take_right, b, b_slot)):
        emitter.emit_line(f"{label}:")
        emitter.emit_line(f"store i64 {position}, ptr {picked_slot}")
        following = emitter.emit_value(f"add i64 {position}, 1")
        emitter.emit_line(f"store i64 {following}, ptr {slot}")
        emitter.emit_line(f"br label %{copy}")
    emitter.emit_line(f"{copy}:")
    picked = emitter.emit_value(f"load i64, ptr {picked_slot}")
    for source, destination, kind, _ in buffers:
        slot = emitter.emit_value(f"getelementptr {kind}, ptr {source}, i64 {picked}")
        value = emitter.emit_value(f"load {kind}, ptr {slot}")
        slot = emitter.emit_value(f"getelementptr {kind}, ptr {destination}, i64 {output}")
        emitter.emit_line(f"store {kind} {value}, ptr {slot}")
    following = emitter.emit_value(f"add i64 {output}, 1")
    emitter.emit_line(f"store i64 {following}, ptr {output_slot}")
    emitter.emit_line(f"br label %{merge}")
    emitter.emit_line(f"{commit}:")
    for source, destination, _, size in buffers:
        byte_count = emitter.emit_value(f"mul i64 {length}, {size}")
        emitter.emit_line(f"call void @llvm.memcpy.p0.p0.i64(ptr {source}, ptr {destination}, i64 {byte_count}, i1 false)")
    width = emitter.emit_value(f"mul i64 {width}, 2")
    emitter.emit_line(f"store i64 {width}, ptr {width_slot}")
    emitter.emit_line(f"br label %{passes}")
    emitter.emit_line(f"{done}:")
    calls.pop_roots(emitter, frame)


def invoke(emitter, callback, contract, arguments, node):
    values, sources = [], []
    for (actual, value), expected in zip(arguments, contract.parameter_types[:len(arguments)], strict=True):
        collections.require_matching_layout(actual, expected, node)
        kind = emitter.value_type(actual)
        emitter.value_semantics[kind, value] = actual
        values.append((kind, value))
        sources.append(tagged.Value(node, actual, kind, value))
    return callables.invoke_values(emitter, callback, contract, calls.BoundCall(values, sources), node)


def extreme(emitter, name, node, arguments, keywords):
    if set(keywords) - {"default", "key"} or len(arguments) > 1 and "default" in keywords:
        raise LLVMUnsupported(f"LLVM {name} accepts an iterable/default or positional values, with an optional key", node)
    result_type = analyzed_value_type(node)
    result_kind = emitter.value_type(result_type)
    if len(arguments) > 1 and any(kind != result_kind for kind, _ in arguments):
        if result_kind == "i64" and any(kind == tagged.STORAGE for kind, _ in arguments):
            raise LLVMUnsupported(tagged.INTEGER_BOUNDARY, node)
        raise LLVMUnsupported("LLVM extrema arguments require matching result storage", node)
    key_node = collections.sort_key(node)
    contract = signature(key_node, 1) if key_node is not None else None
    key_type = contract.return_type if contract is not None else result_type
    key_kind = emitter.value_type(key_type)
    (result, best_key, current, current_key), frame = calls.value_slots(emitter, [result_kind, key_kind, result_kind, key_kind])
    found = emitter.emit_value("alloca i1")
    emitter.emit_line(f"store i1 false, ptr {found}")

    def consume(actual, value):
        collections.require_matching_layout(actual, result_type, node)
        if not same_analyzer_type(actual, result_type):
            raise LLVMUnsupported("LLVM extrema require matching result types", node)
        # The source can be cleared by the key. Retain the current item and
        # the previous winning item/key independently of the source storage.
        emitter.emit_line(f"store {result_kind} {value}, ptr {current}")
        key = invoke(emitter, keywords["key"][1], contract, [(actual, value)], key_node)[1] if contract else value
        emitter.emit_line(f"store {key_kind} {key}, ptr {current_key}")
        available = emitter.emit_value(f"load i1, ptr {found}")
        compare, replace, following = (emitter.new_label(label) for label in ("extreme.compare", "extreme.replace", "extreme.next"))
        emitter.emit_line(f"br i1 {available}, label %{compare}, label %{replace}")
        emitter.emit_line(f"{compare}:")
        previous = emitter.emit_value(f"load {key_kind}, ptr {best_key}")
        better = comparisons.order_value(emitter, "__lt__" if name == "min" else "__gt__",
                                          key_type, key, key_type, previous, node)
        emitter.emit_line(f"br i1 {better}, label %{replace}, label %{following}")
        emitter.emit_line(f"{replace}:")
        emitter.emit_line(f"store {result_kind} {value}, ptr {result}")
        emitter.emit_line(f"store {key_kind} {key}, ptr {best_key}")
        emitter.emit_line(f"store i1 true, ptr {found}")
        emitter.emit_line(f"br label %{following}")
        emitter.emit_line(f"{following}:")

    if len(arguments) > 1:
        for source, (_kind, value) in zip(node.args, arguments, strict=True):
            consume(analyzed_value_type(source), value)
    else:
        collections.loop(emitter, analyzed_value_type(node.args[0]), arguments[0][1], consume, node)
    available = emitter.emit_value(f"load i1, ptr {found}")
    if "default" in keywords:
        fallback = next(keyword.value for keyword in node.keywords if keyword.arg == "default")
        collections.require_matching_layout(analyzed_value_type(fallback), result_type, fallback)
        if keywords["default"][0] != result_kind:
            if not isinstance(result_type, UnionType):
                raise LLVMUnsupported("LLVM extrema default must match the item type", node)
            fallback_kind, fallback_value = collections.convert_item(emitter, analyzed_value_type(fallback),
                result_type, keywords["default"][1], fallback, representation=analyzed_representation(fallback))
        else:
            fallback_kind, fallback_value = keywords["default"]
        missing, ready = emitter.new_label("extreme.empty"), emitter.new_label("extreme.ready")
        emitter.emit_line(f"br i1 {available}, label %{ready}, label %{missing}")
        emitter.emit_line(f"{missing}:")
        emitter.emit_line(f"store {fallback_kind} {fallback_value}, ptr {result}")
        emitter.emit_line(f"br label %{ready}")
        emitter.emit_line(f"{ready}:")
    elif len(arguments) == 1:
        emitter.guard_exception(node, available, "ValueError", f"{name}() iterable argument is empty")
    value = emitter.emit_value(f"load {result_kind}, ptr {result}")
    calls.pop_roots(emitter, frame)
    return result_kind, value


def reduce(emitter, node):
    if not 2 <= len(node.args) <= 3 or any(keyword.arg != "initial" for keyword in node.keywords) or len(node.args) == 3 and node.keywords:
        raise LLVMUnsupported("LLVM reduce requires a callback, iterable and optional initial value", node)
    arguments = [emitter.expression(argument) for argument in node.args]
    keywords = {keyword.arg: emitter.expression(keyword.value) for keyword in node.keywords}
    initial = arguments[2] if len(arguments) == 3 else keywords.get("initial")
    contract = signature(node.args[0], 2)
    result_type = analyzed_value_type(node)
    collections.require_matching_layout(contract.return_type, result_type, node)
    collections.require_matching_layout(result_type, contract.parameter_types[0], node)
    result_kind = emitter.value_type(result_type)
    source_type = analyzed_value_type(node.args[1])
    item_type = contract.parameter_types[1]
    item_kind = emitter.value_type(item_type)
    (result, current), frame = calls.value_slots(emitter, [result_kind, item_kind])
    found = emitter.emit_value("alloca i1")
    emitter.emit_line(f"store i1 {str(initial is not None).lower()}, ptr {found}")
    if initial is not None:
        initial_node = node.args[2] if len(node.args) == 3 else node.keywords[0].value
        collections.require_matching_layout(analyzed_value_type(initial_node), result_type, initial_node)
        if isinstance(result_type, UnionType) or result_type.generic_name == "NoneType":
            # A concrete initial arm still occupies the accumulator's union
            # layout. Reuse ordinary value conversion, including managed tags.
            initial = emitter.coerce_value(*initial, result_kind, node, semantic=result_type)
        if initial[0] != result_kind:
            raise LLVMUnsupported("LLVM reduce initial must match the result type", node)
        emitter.emit_line(f"store {result_kind} {initial[1]}, ptr {result}")

    def consume(actual, value):
        collections.require_matching_layout(actual, item_type, node)
        actual_kind = emitter.value_type(actual)
        emitter.value_semantics[actual_kind, value] = actual
        _, current_value = emitter.coerce_value(actual_kind, value, item_kind, node, semantic=item_type)
        # Root the callback's storage, not the source's narrower representation.
        # A concrete item can widen to a tagged union before callback entry.
        emitter.emit_line(f"store {item_kind} {current_value}, ptr {current}")
        ready = emitter.new_label("reduce.ready")
        if initial is None:
            collections.require_matching_layout(actual, result_type, node)
            available = emitter.emit_value(f"load i1, ptr {found}")
            combine, first = emitter.new_label("reduce.combine"), emitter.new_label("reduce.first")
            emitter.emit_line(f"br i1 {available}, label %{combine}, label %{first}")
            emitter.emit_line(f"{first}:")
            first_kind, first_value = actual_kind, value
            if isinstance(result_type, UnionType) or result_type.generic_name == "NoneType":
                first_kind, first_value = emitter.coerce_value(
                    actual_kind, value, result_kind, node, semantic=result_type)
            if first_kind != result_kind:
                # Without an initializer, a singleton returns the original
                # item. Numeric promotion here would change that result.
                raise LLVMUnsupported("LLVM reduce without initial requires matching items and result", node)
            emitter.emit_line(f"store {result_kind} {first_value}, ptr {result}")
            emitter.emit_line(f"store i1 true, ptr {found}")
            emitter.emit_line(f"br label %{ready}")
            emitter.emit_line(f"{combine}:")
        previous = emitter.emit_value(f"load {result_kind}, ptr {result}")
        kind, following = invoke(emitter, arguments[0][1], contract,
                                 [(result_type, previous), (item_type, current_value)], node)
        _, following = calls.join_result(emitter, contract, kind, following, node)
        emitter.emit_line(f"store {result_kind} {following}, ptr {result}")
        emitter.emit_line(f"br label %{ready}")
        emitter.emit_line(f"{ready}:")

    collections.loop(emitter, source_type, arguments[1][1], consume, node)
    emitter.guard_exception(node, emitter.emit_value(f"load i1, ptr {found}"),
                            "TypeError", "reduce() of empty iterable with no initial value")
    value = emitter.emit_value(f"load {result_kind}, ptr {result}")
    calls.pop_roots(emitter, frame)
    return result_kind, value
