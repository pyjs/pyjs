"""Construction layouts for Python-authored lazy stream operations."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.iterable_protocol import resolve_iterable_protocol
from pyjs.analysis.objects import Class, UnionType, union_type_key
from pyjs.analysis.value_representation import (
    analyzed_representation,
    set_analyzed_representation,
)

from . import (
    callback_ops,
    calls,
    collection_ops,
    gc_layouts,
    indexing,
    iterator_callbacks,
    iterator_ops,
    iterator_views,
    nullable,
    tagged,
)
from . import itertools as streams
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .runtime import iteration as runtime
from .runtime.combinatorics import COMBINATIONS, PERMUTATIONS, PRODUCT, REPLACEMENT


def call(emitter, operation, node):
    name = operation.removeprefix("itertools.")
    if name == "groupby":
        from . import grouping_ops
        return grouping_ops.create(emitter, node)
    if name == "tee":
        values = [emitter.expression(argument) for argument in node.args]
        kind, count = values[1] if len(values) > 1 else ("i64", "2")
        if kind == "i1":
            count = emitter.emit_value(f"zext i1 {count} to i64")
        emitter.guard_exception(node, emitter.emit_value(f"icmp sge i64 {count}, 0"), "ValueError", "n must be >= 0")
        emitter.guard_exception(node, emitter.emit_value(f"icmp sle i64 {count}, 1152921504606846975"),
                                "MemoryError", "native tee result exceeds address space")
        result_type = analyzed_value_type(node)
        member = collection_ops.item_type(collection_ops.item_type(result_type)) if result_type.generic_types else None
        source = iterator_ops.create(emitter, analyzed_value_type(node.args[0]), values[0][1], node)
        kind = emitter.value_type(member) if member is not None else "i64"
        block_allocator = "null"
        if emitter.module.uses_gc:
            # History is a header plus fixed-width item slots. Counters and
            # numeric saved values must not act as references to unrelated data.
            # Keep the descriptor's field indices aligned with the runtime's
            # byte-offset header; a new field must update both sides together.
            assert (runtime.TEE_SOURCE, runtime.TEE_NEXT, runtime.TEE_COUNT,
                    runtime.TEE_RUNNING, runtime.TEE_DATA) == (0, 8, 16, 24, 32)
            references = ((0,), (1,), *(
                (4, index, *path[1:])
                for index in range(runtime.TEE_CAPACITY) for path in gc_layouts.reference_paths((kind,))))
            block_allocator = gc_layouts.allocator(
                emitter, f"{{ ptr, ptr, i64, i64, [{runtime.TEE_CAPACITY} x {kind}] }}", references)
        return "ptr", emitter.allocated_value(
            f"call ptr @pyjs.iterator.tee.typed({collection_ops.owner(emitter)}, ptr {source}, "
            f"i64 {count}, i64 {emitter.llvm_size(kind)}, ptr {block_allocator})")
    if name in {"chain", "chain.from_iterable"}:
        return create_chain(emitter, node)
    if name in {"filterfalse", "takewhile", "dropwhile", "compress", "starmap"}:
        return iterator_callbacks.create(emitter, node)
    if name in {"product", "combinations", "combinations_with_replacement", "permutations"}:
        return create_pool(emitter, node, name)
    if name in {"count", "cycle", "zip_longest", "accumulate"}:
        return create_stream(emitter, node, name)
    arguments = [emitter.expression(argument) for argument in node.args]
    keywords = {keyword.arg: emitter.expression(keyword.value) for keyword in node.keywords}
    parameters = ("object", "times") if name == "repeat" else ("iterable", "n")
    values = dict(zip(parameters, arguments, strict=False)) | keywords
    inputs = dict(zip(parameters, node.args, strict=False)) | {keyword.arg: keyword.value for keyword in node.keywords}
    member = collection_ops.item_type(analyzed_value_type(node))

    if name == "repeat":
        size = emitter.llvm_size(emitter.value_type(member))
        value = emitter.coerce_value(*values["object"], emitter.value_type(member), node, semantic=member)
        limit = (indexing.integer(emitter, analyzed_value_type(inputs["times"]), *values["times"], node)
                 if "times" in values else "-1")
        if "times" in values:
            negative = emitter.emit_value(f"icmp slt i64 {limit}, 0")
            limit = emitter.emit_value(f"select i1 {negative}, i64 0, i64 {limit}")
        storage = iterator_ops.allocate(emitter, size, kind=emitter.value_type(member))
        emitter.emit_line(f"store {value[0]} {value[1]}, ptr {storage}")
        return "ptr", iterator_ops.new(emitter, runtime.REPEAT, storage, limit=limit, size=size)

    iterable_node = inputs["iterable"]
    source_type = analyzed_value_type(iterable_node)
    source_member = collection_ops.item_type(source_type)
    size = emitter.llvm_size(emitter.value_type(source_member))
    if name == "islice":
        bounds = arguments[1:]
        if keywords or not 1 <= len(bounds) <= 3:
            raise LLVMUnsupported("LLVM islice requires an iterable and one to three positional bounds", node)
        start = "0" if len(bounds) == 1 else islice_index(emitter, node.args[1], bounds[0], node, 0)
        stop_position = 0 if len(bounds) == 1 else 1
        stop = islice_index(emitter, node.args[stop_position + 1], bounds[stop_position], node, -1)
        stop_node = node.args[1 if len(bounds) == 1 else 2]
        if getattr(analyzed_value_type(stop_node), "generic_name", None) != "NoneType":
            # Explicit -1 is a parsing error, before validating either index.
            present = nullable.present(emitter, *bounds[stop_position])
            absent = emitter.emit_value(f"xor i1 {present}, true")
            valid = emitter.emit_value(f"icmp ne i64 {stop}, -1")
            emitter.guard_exception(node, emitter.emit_value(f"or i1 {valid}, {absent}"), "ValueError",
                                    "Stop argument for islice() must be None or an integer: 0 <= x <= sys.maxsize.")
            emitter.guard_exception(node, emitter.emit_value(f"icmp sge i64 {stop}, -1"), "ValueError",
                                    "Indices for islice() must be None or an integer: 0 <= x <= sys.maxsize.")
        emitter.guard_exception(node, emitter.emit_value(f"icmp sge i64 {start}, 0"), "ValueError",
                                "Indices for islice() must be None or an integer: 0 <= x <= sys.maxsize.")
        # Invalid start/stop prevents step conversion, but a failing start
        # still permits the stop callback, matching CPython's parse order.
        step = islice_index(emitter, node.args[3], bounds[2], node, 1) if len(bounds) == 3 else "1"
        emitter.guard_exception(node, emitter.emit_value(f"icmp sgt i64 {step}, 0"), "ValueError",
                                "Step for islice() must be a positive integer or None.")
        source = iterator_ops.create(emitter, source_type, values["iterable"][1], node)
        state = iterator_ops.new(emitter, runtime.ISLICE, source, index=start, limit=stop, step=step, size=size)
        iterator_ops.store(emitter, state, runtime.COUNT, "i64", start)
        return "ptr", state
    if name == "batched":
        count = indexing.integer(emitter, analyzed_value_type(inputs["n"]), *values["n"], node)
        emitter.guard_exception(node, emitter.emit_value(f"icmp sgt i64 {count}, 0"), "ValueError", "n must be at least one")
    source = iterator_ops.create(emitter, source_type, values["iterable"][1], node)
    state = iterator_ops.new(emitter, runtime.PAIRWISE if name == "pairwise" else runtime.BATCHED, source, size=size)
    if name == "pairwise":
        offsets = iterator_ops.row_layout(emitter, state, member)
        iterator_ops.store(emitter, state, runtime.OFFSETS, "ptr", iterator_ops.array(emitter, [("i64", offsets[1])]))
        previous = iterator_ops.allocate(emitter, size, kind=emitter.value_type(source_member))
        emitter.emit_line(f"store {emitter.value_type(source_member)} zeroinitializer, ptr {previous}")
        iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", previous)
    else:
        iterator_ops.store(emitter, state, runtime.COUNT, "i64", count)
        if emitter.module.uses_gc:
            iterator_ops.store(emitter, state, runtime.ROW_ALLOCATOR, "ptr",
                               gc_layouts.item_allocator(emitter.value_type(source_member)))
        strict = values.get("strict", ("i1", "false"))
        iterator_ops.store(emitter, state, runtime.STRICT, "i64",
                           emitter.index_integer(*strict, node, "LLVM batched strict requires bool"))
    return "ptr", state


def islice_index(e, source, value, node, default):
    """CPython islice clears conversion exceptions and validates a -1 sentinel.

    Keep a local root-frame anchor: unwinding a failed index callback must not
    discard enclosing call-binding roots before the next bound callback runs.
    """
    def convert():
        return indexing.optional(e, analyzed_value_type(source), *value, default, node,
                                 error="object cannot be interpreted as an integer")

    # Unboxed integer/bool/None values cannot raise or invoke a callback. Keep
    # ordinary scalar construction free of an otherwise unused recovery region.
    if value[0] in {"i64", "i1", "void"}:
        return convert()
    result = e.emit_value("alloca i64")
    e.emit_line(f"store i64 -1, ptr {result}")
    frame = calls.root_values(e)
    outer = e.exception_target
    failed, done = e.new_label("islice.index.failed"), e.new_label("islice.index.done")
    e.exception_target = failed
    try:
        converted = convert()
    finally:
        e.exception_target = outer
    e.emit_line(f"store i64 {converted}, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{e.name(failed, 'block')}:")
    calls.restore_roots(e, frame)
    e.emit_line(f"store %pyjs.exception zeroinitializer, ptr {e.load_local('__exception')}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    calls.pop_roots(e, frame)
    return e.emit_value(f"load i64, ptr {result}")


def create_stream(emitter, node, name):
    values = {value: emitter.expression(value) for value in [*node.args, *(value.value for value in node.keywords)]}
    parameters = ("start", "step") if name == "count" else ("iterable", "func")
    named = dict(zip(parameters, node.args, strict=False)) | {value.arg: value.value for value in node.keywords}
    member = collection_ops.item_type(analyzed_value_type(node))
    if name == "count":
        start = values[named["start"]] if "start" in named else ("i64", "0")
        step = values[named["step"]] if "step" in named else ("i64", "1")
        mixed = bool(tagged.members(member))
        start_tag = None
        if start[0] == tagged.STORAGE:
            if not mixed:
                raise LLVMUnsupported(tagged.INTEGER_BOUNDARY, node)
            # An isinstance(int) proof still permits bool. Preserve the
            # runtime tag for the first yield; only addition reads its bits.
            start_tag, payload = tagged.parts(emitter, start[1])
            start = "i64", payload
        if step[0] == tagged.STORAGE:
            raise LLVMUnsupported(tagged.INTEGER_BOUNDARY, node)
        start, step = [("i64", emitter.emit_value(f"zext i1 {value} to i64")) if kind == "i1" else (kind, value)
                       for kind, value in (start, step)]
        if collection_ops.builtin_name(member) == "int":
            return "ptr", iterator_ops.new(emitter, runtime.COUNT_INT, "null", index=start[1], step=step[1])
        converted = [("double", value if kind == "double" else emitter.emit_value(f"sitofp i64 {value} to double"))
                     for kind, value in (start, step)]
        state = iterator_ops.new(emitter, runtime.COUNT_MIXED if mixed else runtime.COUNT_FLOAT,
                                 iterator_ops.array(emitter, converted))
        if mixed:
            # Preserve the first scalar's kind and exact bits; float conversion
            # supplies only subsequent additions, never the initial yield.
            start_type = analyzed_value_type(named["start"]) if "start" in named else NATIVE_ENVIRONMENT.builtins.search("int")
            iterator_ops.store(emitter, state, runtime.INDEX, "i64", start[1])
            iterator_ops.store(emitter, state, runtime.STEP, "i64",
                               start_tag if start_tag is not None else str(tagged.tag(emitter, start_type)))
            iterator_ops.store(emitter, state, runtime.COUNT, "i64", str(tagged.TAGS["float"]))
        return "ptr", state
    if name == "zip_longest":
        return create_longest(emitter, node, values)
    source = iterator_ops.create(emitter, analyzed_value_type(named["iterable"]), values[named["iterable"]][1], node)
    kind = emitter.value_type(member)
    state = iterator_ops.new(emitter, runtime.CYCLE if name == "cycle" else runtime.CALLBACK, source,
                             size=emitter.llvm_size(kind))
    if name == "cycle":
        saved = collection_ops.new_list(emitter, member)
        iterator_ops.store(emitter, state, runtime.CHILDREN, "ptr", saved)
    else:
        initial = values[named["initial"]] if "initial" in named else ("void", "")
        callback = values[named["func"]] if "func" in named else ("void", "")
        saved = iterator_ops.array(emitter, [(kind, initial[1] if initial[0] != "void" else "zeroinitializer")])
        iterator_ops.store(emitter, state, runtime.CHILDREN, "ptr", saved)
        # INDEX distinguishes no total, a pending initial value, and a total.
        iterator_ops.store(emitter, state, runtime.INDEX, "i64", "1" if initial[0] != "void" else "0")
        iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", callback[1] if callback[0] != "void" else "null")
        iterator_ops.store(emitter, state, runtime.ADVANCE, "ptr",
                           "@" + emitter.function_name(emitter.module.iterator_steps[node]))
    return "ptr", state


def longest_inputs(node):
    row = collection_ops.item_type(analyzed_value_type(node), node)
    iterator = NATIVE_ENVIRONMENT.builtins.search("Iterator")
    for argument, member in zip(node.args, row.generic_types.values(), strict=True):
        source = analyzed_value_type(argument)
        target = iterator(member)
        empty = getattr(source, "generic_name", None) == "tuple" and not source.generic_types
        cursor = target if empty else iterator(collection_ops.item_type(source, argument))
        yield source, cursor, target


def create_longest(emitter, node, values):
    inputs = list(longest_inputs(node))
    for argument, (_, cursor, target) in zip(node.args, inputs, strict=True):
        iterator_views.check(cursor, target, argument)
    sources, frame = iterator_ops.create_many(emitter, [
        (source, values[argument][1]) for argument, (source, _, _) in zip(node.args, inputs, strict=True)
    ], node)
    for index, (_, cursor, target) in enumerate(inputs):
        if iterator_views.needed(cursor, target):
            sources[index] = iterator_views.wrap(emitter, cursor, target, sources[index], node)
    state = iterator_ops.new(emitter, runtime.ZIP_LONGEST, "null", limit=str(len(sources)))
    row = collection_ops.item_type(analyzed_value_type(node))
    offsets = iterator_ops.row_layout(emitter, state, row)
    size = emitter.llvm_size(f"%{emitter.tuple_type(row)}")
    fill = next((values[value.value] for value in node.keywords if value.arg == "fillvalue"), ("void", ""))
    # One typed template row preserves the fill's identity in every column.
    # Offsets include a final size sentinel so runtime copies each whole slot,
    # including alignment padding, without assuming a uniform item width.
    fields = tuple(emitter.value_type(member) for member in row.generic_types.values())
    saved = gc_layouts.allocate(emitter, fields, layout=f"%{emitter.tuple_type(row)}", size=size)
    fills = {}
    for member, offset in zip(row.generic_types.values(), offsets, strict=True):
        # Boxing a scalar independently per object column would lose fill
        # identity. Redundant object unions all use the same erased box ABI.
        key = None if nullable.is_object(member) else union_type_key(member)
        if key not in fills:
            fills[key] = emitter.coerce_value(*fill, emitter.value_type(member), node, semantic=member)
        converted = fills[key]
        emitter.emit_line(f"store {converted[0]} {converted[1]}, ptr {iterator_ops.slot(emitter, saved, offset)}")
    iterator_ops.store(emitter, state, runtime.COUNT, "i64", str(len(sources)))
    iterator_ops.store(emitter, state, runtime.CHILDREN, "ptr",
                       iterator_ops.array(emitter, [("ptr", value) for value in sources]))
    iterator_ops.store(emitter, state, runtime.OFFSETS, "ptr",
                       iterator_ops.array(emitter, [("i64", value) for value in (*offsets, size)]))
    iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", saved)
    calls.pop_roots(emitter, frame)
    return "ptr", state


def advance_accumulate(emitter, node):
    source = node.source
    named = dict(zip(("iterable", "func"), source.args, strict=False)) | {value.arg: value.value for value in source.keywords}
    member = collection_ops.item_type(analyzed_value_type(source))
    kind = emitter.value_type(member)
    callback_node = named.get("func")
    contract = (callback_ops.signature(callback_node, 2) if callback_node is not None
                and analyzed_value_type(callback_node).generic_name != "NoneType" else None)
    state, output = emitter.load_local("state"), emitter.load_local("output")
    saved = iterator_callbacks.load(emitter, state, runtime.CHILDREN)
    (current, previous), frame = calls.value_slots(emitter, [kind, kind])
    outcome = emitter.emit_value("alloca i64")
    emitter.emit_line(f"store i64 0, ptr {outcome}")
    initial, fetch, combine, first, publish, done, error = (
        emitter.new_label("accumulate." + label) for label in
        ("initial", "fetch", "combine", "first", "publish", "done", "error"))
    phase = iterator_callbacks.load(emitter, state, runtime.INDEX, "i64")
    pending = emitter.emit_value(f"icmp eq i64 {phase}, 1")
    emitter.emit_line(f"br i1 {pending}, label %{initial}, label %{fetch}")
    emitter.emit_line(f"{initial}:")
    value = emitter.emit_value(f"load {kind}, ptr {saved}")
    emitter.emit_line(f"store {kind} {value}, ptr {current}")
    emitter.emit_line(f"br label %{publish}")
    emitter.emit_line(f"{fetch}:")
    child = iterator_callbacks.load(emitter, state, runtime.SOURCE)
    available = iterator_ops.status(emitter, child, current, source, preserve_stop=True)
    received = emitter.new_label("accumulate.received")
    emitter.emit_line(f"br i1 {available}, label %{received}, label %{done}")
    emitter.emit_line(f"{received}:")
    # Fetching an item can recursively establish or replace the total.
    phase = iterator_callbacks.load(emitter, state, runtime.INDEX, "i64")
    missing = emitter.emit_value(f"icmp eq i64 {phase}, 0")
    emitter.emit_line(f"br i1 {missing}, label %{first}, label %{combine}")
    emitter.emit_line(f"{first}:")
    emitter.emit_line(f"br label %{publish}")
    emitter.emit_line(f"{combine}:")
    left = emitter.emit_value(f"load {kind}, ptr {saved}")
    right = emitter.emit_value(f"load {kind}, ptr {current}")
    emitter.emit_line(f"store {kind} {left}, ptr {previous}")
    outer = emitter.exception_target
    emitter.exception_target = error
    try:
        if contract is not None:
            callback = iterator_callbacks.load(emitter, state, runtime.CALLBACK_VALUE)
            result_kind, result = callback_ops.invoke(emitter, callback, contract, [(member, left), (member, right)], source)
            if result_kind != kind:
                raise LLVMUnsupported("LLVM accumulate callback result must match its item storage", source)
        elif member.generic_name in {"str", "bytes"}:
            result = emitter.string_concat(left, right)
        else:
            result = emitter.emit_value(f"{'fadd' if kind == 'double' else 'add'} {kind} {left}, {right}")
            represented = ast.copy_location(ast.Name(id="total", ctx=ast.Load()), source)
            represented.obj = member
            representation = analyzed_representation(source)
            set_analyzed_representation(represented, representation.arguments[0] if representation else None)
            _, result = (emitter.normalize_float_result(result, represented) if kind == "double"
                         else emitter.normalize_integer_result(result, represented))
    finally:
        emitter.exception_target = outer
    emitter.emit_line(f"store {kind} {result}, ptr {current}")
    emitter.emit_line(f"br label %{publish}")
    emitter.emit_line(f"{publish}:")
    value = emitter.emit_value(f"load {kind}, ptr {current}")
    emitter.emit_line(f"store {kind} {value}, ptr {saved}")
    emitter.emit_line(f"store {kind} {value}, ptr {output}")
    iterator_ops.store(emitter, state, runtime.INDEX, "i64", "2")
    emitter.emit_line(f"store i64 1, ptr {outcome}")
    emitter.emit_line(f"br label %{done}")
    iterator_callbacks.callback_failure(emitter, error, frame)
    emitter.emit_line(f"{done}:")
    calls.pop_roots(emitter, frame)
    return "i64", emitter.emit_value(f"load i64, ptr {outcome}")


def create_pool(emitter, node, name):
    arguments = {value: emitter.expression(value) for value in [*node.args, *(value.value for value in node.keywords)]}
    named = dict(zip(("iterable", "r"), node.args, strict=False)) | {value.arg: value.value for value in node.keywords}
    sources = node.args if name == "product" else [named["iterable"]]
    row_type = collection_ops.item_type(analyzed_value_type(node))
    # Pools keep their own concrete item storage. A fixed product row can mix
    # those layouts without coercing any input collection or boxing its items.
    members = []
    for source in sources:
        source_type = analyzed_value_type(source)
        empty = source_type.generic_name == "tuple" and not source_type.generic_types
        protocol = resolve_iterable_protocol(source_type, analyzed_representation(source), NATIVE_ENVIRONMENT.builtins)
        members.append(None if empty else protocol.item_type)
    mode = {"product": PRODUCT, "combinations": COMBINATIONS,
            "combinations_with_replacement": REPLACEMENT, "permutations": PERMUTATIONS}[name]

    def integer(node):
        kind, value = arguments[node]
        if kind == "i1":
            return emitter.emit_value(f"zext i1 {value} to i64")
        if kind != "i64":
            raise LLVMUnsupported(f"LLVM {name} requires concrete int sizes or literal None", node)
        return value

    sizes = [emitter.llvm_size(emitter.value_type(member)) if member is not None else "1" for member in members]
    fixed_product = name == "product" and not row_type.tuple_variadic
    size = "1" if fixed_product or not sizes else sizes[0]
    pools = iterator_ops.array(emitter, [("ptr", "null")] * len(sources))
    frame = calls.root_values(emitter, pools, *(value for kind, value in arguments.values() if kind == "ptr"))
    if name == "product":
        repeat = integer(named["repeat"]) if "repeat" in named else "1"
        emitter.guard_exception(node, emitter.emit_value(f"icmp sge i64 {repeat}, 0"),
                                "ValueError", "repeat argument cannot be negative")
        maximum = str(9223372036854775807 // max(len(sources), 1))
        emitter.guard_exception(node, emitter.emit_value(f"icmp sle i64 {repeat}, {maximum}"),
                                "OverflowError", "repeat argument too large")
        width = emitter.emit_value(f"mul i64 {repeat}, {len(sources)}")
        empty = emitter.emit_value(f"icmp eq i64 {width}, 0")
        consume, ready = emitter.new_label("product.pool"), emitter.new_label("product.ready")
        emitter.emit_line(f"br i1 {empty}, label %{ready}, label %{consume}")
        emitter.emit_line(f"{consume}:")
    for index, source in enumerate(sources):
        member = members[index]
        if member is None:
            # An empty tuple has no item domain, but still contributes an empty
            # pool. No item can be copied from its harmless one-byte storage.
            pool = emitter.allocated_value(f"call ptr @pyjs.list.new.owned({collection_ops.owner(emitter)}, i64 1, i64 0)")
            iterator_ops.store(emitter, pools, index * 8, "ptr", pool)
            continue
        pool = collection_ops.new_list(emitter, member)
        iterator_ops.store(emitter, pools, index * 8, "ptr", pool)

        def append(actual, value, pool=pool, source=source, member=member):
            collection_ops.append(emitter, pool, member, actual, value, source)

        collection_ops.loop(emitter, analyzed_value_type(source), arguments[source][1], append, source)
    if name == "product":
        emitter.emit_line(f"br label %{ready}")
        emitter.emit_line(f"{ready}:")
        # No pools are consulted for the single empty tuple from repeat=0.
        pool_count = emitter.emit_value(f"select i1 {empty}, i64 0, i64 {len(sources)}")
    else:
        bound = named.get("r")
        if bound is None or analyzed_value_type(bound).generic_name == "NoneType":
            width = emitter.emit_value(f"load i64, ptr {pool}")
        else:
            width = integer(bound)
        emitter.guard_exception(node, emitter.emit_value(f"icmp sge i64 {width}, 0"),
                                "ValueError", "r must be non-negative")
        pool_count = "1"
    state = emitter.allocated_value(
        f"call ptr @pyjs.iterator.pooled({collection_ops.owner(emitter)}, i64 {mode}, ptr {pools}, "
        f"i64 {pool_count}, i64 {width}, i64 {size})")
    if fixed_product:
        state_root = calls.root_values(emitter, state)
        offsets = iterator_ops.row_layout(emitter, state, row_type)
        # One descriptor contains per-pool strides followed by per-row field
        # offsets. Runtime index transitions stay independent of field types.
        layout = iterator_ops.array(emitter, [("i64", value) for value in (*sizes, *offsets)])
        iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", layout)
        calls.pop_roots(emitter, state_root)
    elif emitter.module.uses_gc:
        iterator_ops.store(emitter, state, runtime.ROW_ALLOCATOR, "ptr",
                           gc_layouts.item_allocator(emitter.value_type(collection_ops.item_type(row_type))))
    calls.pop_roots(emitter, frame)
    return "ptr", state


def chain_inputs(node):
    """Concrete iterable/cursor pairs for preparation and lazy acquisition."""
    nested = node.func.obj.py_func is streams.chain_from_iterable
    target = analyzed_value_type(node)
    for argument in node.args:
        source = analyzed_value_type(argument)
        if nested:
            source = collection_ops.item_type(source, argument)
        if not isinstance(source, Class):
            raise LLVMUnsupported("LLVM chain requires concrete iterable types; narrow unions before use", argument)
        empty = source.generic_name == "tuple" and not source.generic_types
        cursor = target if empty else NATIVE_ENVIRONMENT.builtins.search("Iterator")(collection_ops.item_type(source, argument))
        yield source, cursor


def create_chain(emitter, node):
    if node.keywords or not node.args:
        raise LLVMUnsupported("LLVM chain requires positional typed iterables", node)
    values = [emitter.expression(value) for value in node.args]
    nested = node.func.obj.py_func is streams.chain_from_iterable
    target = analyzed_value_type(node)
    # Validate union storage at the source call, preserving its coordinates
    # and canonical pointer-backed cases. Opaque T needs no concrete layout:
    # chain forwards its consumer's output buffer without reading an item.
    member = collection_ops.item_type(target)
    if isinstance(member, UnionType):
        emitter.value_type(member, node)
    for value, (_, cursor) in zip(node.args, chain_inputs(node), strict=True):
        iterator_views.check(cursor, target, value)
    # Acquiring the outer application iterator can collect; do it before the
    # unpublished chain state exists, then retain its result while allocating.
    children = (iterator_ops.create(emitter, analyzed_value_type(node.args[0]), values[0][1], node) if nested
                else iterator_ops.array(emitter, values))
    frame = calls.root_values(emitter, children)
    state = iterator_ops.new(emitter, runtime.CALLBACK, "null")
    iterator_ops.store(emitter, state, runtime.CHILDREN, "ptr", children)
    iterator_ops.store(emitter, state, runtime.ADVANCE, "ptr",
                       "@" + emitter.function_name(emitter.module.iterator_steps[node]))
    calls.pop_roots(emitter, frame)
    return "ptr", state


def advance_chain(emitter, node):
    source = node.source
    state, output = emitter.load_local("state"), emitter.load_local("output")
    children = iterator_callbacks.load(emitter, state, runtime.CHILDREN)
    (saved,), frame = calls.value_slots(emitter, ["ptr"])
    emitter.emit_line(f"store ptr {children}, ptr {saved}")
    check, done, stopped = (emitter.new_label("chain." + name) for name in ("next", "done", "stopped"))
    failed = emitter.new_label("chain.acquire.error")
    outcome = emitter.emit_value("alloca i64")
    emitter.emit_line(f"store i64 0, ptr {outcome}")
    emitter.emit_line(f"br label %{check}")
    emitter.emit_line(f"{check}:")
    nested = source.func.obj.py_func is streams.chain_from_iterable
    current = iterator_callbacks.load(emitter, state, runtime.SOURCE)
    absent = emitter.emit_value(f"icmp eq ptr {current}, null")
    initialize, advance = emitter.new_label("chain.enter"), emitter.new_label("chain.advance")
    emitter.emit_line(f"br i1 {absent}, label %{initialize}, label %{advance}")
    emitter.emit_line(f"{initialize}:")
    index = iterator_callbacks.load(emitter, state, runtime.INDEX, "i64")
    labels = [emitter.new_label("chain.source") for _ in source.args]
    emitter.emit_line(f"switch i64 {index}, label %{stopped} [" + " ".join(
        f"i64 {position}, label %{label}" for position, label in enumerate(labels)) + "]")
    for position, (label, (source_type, cursor_type)) in enumerate(zip(labels, chain_inputs(source), strict=True)):
        emitter.emit_line(f"{label}:")
        # Do not create later iterators eagerly: a dictionary can change size
        # before chain reaches it, and its size snapshot belongs to that moment.
        outer = emitter.exception_target
        emitter.exception_target = failed
        try:
            if nested:
                value_slot = emitter.emit_value("alloca ptr")
                available = iterator_ops.status(emitter, children, value_slot, source)
                entered = emitter.new_label("chain.inner")
                emitter.emit_line(f"br i1 {available}, label %{entered}, label %{stopped}")
                emitter.emit_line(f"{entered}:")
                value = emitter.emit_value(f"load ptr, ptr {value_slot}")
            else:
                value = iterator_callbacks.load(emitter, children, position * 8)
                # Select the input before calling user code: reentrant next()
                # must acquire the following input, not this same one again.
                iterator_ops.store(emitter, state, runtime.INDEX, "i64", str(position + 1))
            current = iterator_ops.create(emitter, source_type, value, source)
            target = analyzed_value_type(source)
            if iterator_views.needed(cursor_type, target):
                # Convert each successful yield, never reinterpret an aliased
                # input buffer or acquire a later application cursor early.
                current = iterator_views.wrap(emitter, cursor_type, target, current, source)
        finally:
            emitter.exception_target = outer
        iterator_ops.store(emitter, state, runtime.SOURCE, "ptr", current)
        # Do not revive EXHAUSTED after reentry drained the source. This call
        # can still yield from the just-acquired cursor, but cannot select any
        # further inputs after that cursor ends; later pulls stop too.
        emitter.emit_line(f"br label %{advance}")
    emitter.emit_line(f"{advance}:")
    current = iterator_callbacks.load(emitter, state, runtime.SOURCE)
    available = iterator_ops.status(emitter, current, output, source)
    yielded, exhausted = emitter.new_label("chain.yield"), emitter.new_label("chain.exhausted")
    emitter.emit_line(f"br i1 {available}, label %{yielded}, label %{exhausted}")
    emitter.emit_line(f"{yielded}:")
    emitter.emit_line(f"store i64 1, ptr {outcome}")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{exhausted}:")
    iterator_ops.store(emitter, state, runtime.SOURCE, "ptr", "null")
    # A reentrant acquisition can finish the chain while the outer __iter__
    # is in flight. An empty cursor must not resume selection from stale inputs.
    finished = iterator_callbacks.load(emitter, state, runtime.EXHAUSTED, "i64")
    finished = emitter.emit_value(f"icmp ne i64 {finished}, 0")
    emitter.emit_line(f"br i1 {finished}, label %{done}, label %{check}")
    # Failure acquiring an inner cursor permanently stops chain; errors from
    # advancing an already-active cursor keep their existing retry semantics.
    emitter.emit_line(f"{emitter.name(failed, 'block')}:")
    calls.restore_roots(emitter, frame)
    emitter.emit_line(f"call i64 @pyjs.iterator.finish(ptr {state})")
    calls.pop_roots(emitter, frame)
    emitter.branch_to_exception_target()
    emitter.emit_line(f"{stopped}:")
    emitter.emit_line(f"call i64 @pyjs.iterator.finish(ptr {state})")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    calls.pop_roots(emitter, frame)
    return "i64", emitter.emit_value(f"load i64, ptr {outcome}")
