"""Typed adapters to the Python-authored lazy iterator runtime."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.ir import (
    Branch,
    ExceptionDispatch,
    ExceptionRaise,
    IteratorCreate,
    IteratorNext,
    Jump,
    Return,
    Suspend,
)
from pyjs.analysis.iterable_protocol import is_abstract_iterator as is_iterator
from pyjs.analysis.iterable_protocol import resolve_iterable_protocol
from pyjs.analysis.objects import Function, StaticCast, union_type_key
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.python import contains_equal_sequence_item
from pyjs.python import native as builtins

from . import calls, collection_ops, comparisons, gc_layouts, nullable, tagged
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .itertools import tee, zip_longest
from .runtime import iteration as runtime

BUILTINS = {builtins._iter, builtins._next, builtins._enumerate, builtins._zip, builtins._reversed,
            builtins._map, builtins._filter, contains_equal_sequence_item}


def dead_roots(blocks):
    """Function-local cursor liveness; authored aliases keep normal lifetimes."""
    names = {node.name for block in blocks for node in block.body if isinstance(node, IteratorCreate)}
    if not names:
        return {}
    constraints = {}
    predecessors = {block.name: set() for block in blocks}
    for block in blocks:
        used, defined = set(), set()
        for statement in block.body:
            references = {node.id for node in ast.walk(statement) if isinstance(node, ast.Name) and node.id in names}
            if isinstance(statement, IteratorNext):
                references.add(statement.iterator)
            used.update(references - defined)
            if isinstance(statement, IteratorCreate):
                defined.add(statement.name)
        terminal = block.body[-1] if block.body else None
        if isinstance(terminal, Jump):
            edges = {terminal.target}
        elif isinstance(terminal, Branch):
            edges = {terminal.true, terminal.false}
        elif isinstance(terminal, IteratorNext):
            edges = {terminal.body, terminal.exhausted}
        elif isinstance(terminal, Suspend):
            edges = {terminal.resume}
        elif isinstance(terminal, ExceptionDispatch):
            edges = {target for _, target in terminal.handlers}
            if terminal.unmatched is not None:
                edges.add(terminal.unmatched)
        elif isinstance(terminal, (Return, ExceptionRaise)):
            edges = set()
        else:
            return {}  # Unknown control flow cannot prove any root dead.
        exceptional = block.exception_target
        constraints[block.name] = used, defined, edges, exceptional
        for target in edges | ({exceptional} if exceptional is not None else set()):
            predecessors[target].add(block.name)
    live = {name: set() for name in predecessors}
    work, pending = list(predecessors), set(predecessors)
    while work:
        name = work.pop()
        pending.remove(name)
        used, defined, edges, exceptional = constraints[name]
        before = used | (set().union(*(live[target] for target in edges)) - defined)
        if exceptional is not None:
            # A failed creation has not replaced its old destination yet.
            before.update(live[exceptional])
        if before != live[name]:
            live[name] = before
            for predecessor in predecessors[name] - pending:
                work.append(predecessor)
                pending.add(predecessor)
    result = {}
    for name, parents in predecessors.items():
        # Only a predecessor that used or created a cursor can leave a new
        # dead root here. Clearing every other cursor in every block produces
        # quadratic IR for sequential loops; never-created/already-dead slots
        # are null. Joins may conservatively repeat a clear on another path.
        possible = set().union(*(live[parent] | constraints[parent][1] for parent in parents))
        result[name] = tuple(sorted(possible - live[name]))
    return result


def prepare(emitter, node):
    if isinstance(node, StaticCast):
        value_type = analyzed_value_type(node)
        value_type = nullable.member(value_type) or value_type
        if not is_iterator(value_type):
            return
    elif isinstance(node, IteratorCreate):
        value_type = analyzed_value_type(node.iterable)
        if (not is_iterator(value_type) and not getattr(value_type, "tuple_variadic", False)
                and value_type not in emitter.module.classes):
            return
    elif isinstance(node, ast.Call):
        target = getattr(node.func, "obj", None)
        if not isinstance(target, Function) or not (
            target.py_func in BUILTINS or target.py_func is tee or is_iterator(analyzed_value_type(node)) or is_iterator(target.cls)
        ):
            return
        if target.py_func is zip_longest:
            from .itertools_ops import longest_inputs
            for _, cursor, adapted in longest_inputs(node):
                for signature in (cursor, adapted):
                    emitter.module.iterator_signatures[union_type_key(signature)] = signature
    else:
        return
    emitter.module.uses_iterators = True
    emitter.module.uses_collections = True
    emitter.module.uses_strings = True
    emitter.module.uses_ranges = True
    if isinstance(node, (ast.Call, StaticCast)):
        value_type = analyzed_value_type(node)
        value_type = nullable.member(value_type) or value_type
        if is_iterator(value_type):
            # Include anonymous sources and casts, not only named locals or
            # signatures, while walking the existing collection-preparation pass.
            emitter.module.iterator_signatures[union_type_key(value_type)] = value_type
            member = collection_ops.item_type(value_type)
            if collection_ops.builtin_name(member) == "tuple" and not member.tuple_variadic:
                emitter.tuple_type(member, node)


def slot(emitter, value, offset):
    return emitter.emit_value(f"getelementptr i8, ptr {value}, i64 {offset}")


def store(emitter, state, offset, kind, value):
    emitter.emit_line(f"store {kind} {value}, ptr {slot(emitter, state, offset)}")


def allocate(emitter, size, *, kind=None):
    allocator = gc_layouts.item_allocator(kind) if kind is not None else "@pyjs.gc.alloc.adapter"
    return emitter.allocated_value(
        f"call ptr @pyjs.collection.try.alloc({collection_ops.owner(emitter, allocator=allocator)}, i64 {size})")


def array(emitter, values):
    # Narrow scalars retain word-spaced slots used by runtime metadata readers.
    # Aggregate values need their full layout (e.g. a tagged sentinel/total is
    # two words). Use that same layout for allocation, stores and GC tracing.
    scalars = {"double", "float", "i1", "i8", "i16", "i32", "i64"}
    fields = tuple("i64" if kind in scalars else kind for kind, _ in values)
    layout = "{ " + ", ".join(fields) + " }"
    result = gc_layouts.allocate(emitter, fields, layout=layout, size="1" if not fields else None)
    for index, (kind, value) in enumerate(values):
        field = emitter.emit_value(f"getelementptr {layout}, ptr {result}, i32 0, i32 {index}")
        emitter.emit_line(f"store {kind} {value}, ptr {field}")
    return result


def row_layout(emitter, state, value_type):
    layout = emitter.tuple_type(value_type)
    size = emitter.llvm_size(f"%{layout}")
    offsets = [emitter.emit_value(f"ptrtoint ptr getelementptr (%{layout}, ptr null, i32 0, i32 {index}) to i64")
               for index in range(len(value_type.generic_types))]
    store(emitter, state, runtime.ROW_SIZE, "i64", size)
    if emitter.module.uses_gc:
        store(emitter, state, runtime.ROW_ALLOCATOR, "ptr", collection_ops.tuple_allocator(emitter, value_type))
    return offsets


def create(emitter, value_type, source, node, *, reverse=False):
    from . import iterable_views
    if iterable_views.is_view(value_type) and not reverse:
        return iterable_views.invoke(emitter, source, node)
    if is_iterator(value_type) and not reverse:
        from .protocols import reiterate
        return reiterate(emitter, source, node)
    if value_type in emitter.module.classes and not reverse:
        from .protocols import create as application_iterator
        return application_iterator(emitter, value_type, source, node)
    name = collection_ops.sequence_name(value_type)
    if reverse and name not in {"list", "tuple", "dict", "str", "bytes", "range", *collection_ops.VIEWS}:
        raise LLVMUnsupported("LLVM reversed needs a concrete reversible collection", node)
    kinds = {"list": runtime.LIST, "tuple": runtime.TUPLE, "dict": runtime.KEYS,
             "set": runtime.SET_KEYS, "frozenset": runtime.SET_KEYS, "KeysView": runtime.KEYS, "ValuesView": runtime.VALUES,
             "ItemsView": runtime.ITEMS, "range": runtime.RANGE, "str": runtime.TEXT, "bytes": runtime.BYTES}
    if name not in kinds:
        raise LLVMUnsupported("LLVM iter requires a concrete builtin iterable or Iterator", node)
    empty = name == "tuple" and not value_type.generic_types
    member = None if empty else collection_ops.item_type(value_type)
    size = "1" if empty else emitter.llvm_size(emitter.value_type(member))
    if name in collection_ops.VIEWS:
        source = emitter.emit_value(f"load ptr, ptr {source}")
    step, index = ("-1" if reverse else "1"), "0"
    if name == "range":
        index, limit, step = emitter.range_values(source)
    elif name == "tuple":
        emitter.tuple_type(value_type, node)
        limit = str(len(value_type.generic_types))
    else:
        limit = emitter.emit_value(f"load i64, ptr {source}")
    if reverse and name != "range":
        index = emitter.emit_value(f"sub i64 {limit}, 1")
    kind = runtime.REVERSE_RANGE if name == "range" and reverse else kinds[name]
    result = new(emitter, kind, source, index, limit, step, size)
    if name == "ItemsView":
        offsets = row_layout(emitter, result, member)
        sizes = [emitter.llvm_size(emitter.value_type(component)) for component in member.generic_types.values()]
        metadata = array(emitter, [("i64", sizes[0]), ("i64", sizes[1]), ("i64", offsets[1])])
        store(emitter, result, runtime.OFFSETS, "ptr", metadata)
    return result


def create_many(emitter, inputs, node):
    """Root earlier cursors while a later application's __iter__ executes."""
    from .iterable_views import is_view
    if not any(value_type in emitter.module.classes or is_view(value_type)
               or emitter.module.application_iterators and is_iterator(value_type)
               for value_type, _ in inputs):
        return [create(emitter, value_type, value, node) for value_type, value in inputs], None
    slots, frame = calls.value_slots(emitter, ["ptr"] * len(inputs))
    sources = []
    for slot, (value_type, value) in zip(slots, inputs, strict=True):
        source = create(emitter, value_type, value, node)
        emitter.emit_line(f"store ptr {source}, ptr {slot}")
        sources.append(source)
    return sources, frame


def new(emitter, kind, source, index="0", limit="0", step="1", size="8"):
    return emitter.allocated_value(
        f"call ptr @pyjs.iterator.new({collection_ops.owner(emitter)}, i64 {kind}, ptr {source}, "
        f"i64 {index}, i64 {limit}, i64 {step}, i64 {size})")


def context(emitter):
    result = emitter.emit_value("alloca [3 x ptr]")
    for index, name in enumerate(("__arena", "__heap", "__exception")):
        store(emitter, result, index * 8, "ptr", emitter.load_local(name))
    return result


def status(emitter, iterator, output, node, *, preserve_stop=False):
    if emitter.module.iterator_steps or emitter.module.generators or emitter.module.uses_iterator_views:
        current = context(emitter)
        result = emitter.emit_value(f"call i64 @pyjs.iterator.next.context(ptr {iterator}, ptr {output}, ptr {current})")
        if not preserve_stop and emitter.module.uses_exceptions:
            # PyIter_Next-style consumers clear StopIteration; bare next() uses
            # tp_iternext semantics and must retain its subclass and payload.
            result = emitter.emit_value(f"call i64 @pyjs.iterator.consume.stop(i64 {result}, ptr {current})")
        emitter.check_active_exception(node)
    else:
        result = emitter.emit_value(f"call i64 @pyjs.iterator.next(ptr {iterator}, ptr {output})")
    for code, exception, message in (
        (-1, "MemoryError", "native iterator allocation failed"),
        (-2, "RuntimeError", "dictionary changed size during iteration"),
        (-3, "OverflowError", "enumerate index exceeds native i64 limits"),
        (-4, "RuntimeError", "Set changed size during iteration"),
        (runtime.INCOMPLETE_BATCH, "ValueError", "batched(): incomplete batch"),
        (runtime.TEE_REENTRY, "RuntimeError", "cannot re-enter the tee iterator"),
        (runtime.COROUTINE_REUSED, "RuntimeError", "cannot reuse already awaited coroutine"),
    ):
        emitter.guard_exception(node, emitter.emit_value(f"icmp ne i64 {result}, {code}"), exception, message)
    failed, ready = emitter.new_label("zip.mismatch"), emitter.new_label("iterator.ready")
    valid = emitter.emit_value(f"icmp sge i64 {result}, 0")
    emitter.emit_line(f"br i1 {valid}, label %{ready}, label %{failed}")
    emitter.emit_line(f"{failed}:")
    # Encode the offending position and comparison in the status, so nested
    # adapters can propagate the original zip error without knowing its arity.
    encoded = emitter.emit_value(f"sub i64 -5, {result}")
    position = emitter.emit_value(f"lshr i64 {encoded}, 1")
    argument = emitter.emit_value(f"add i64 {position}, 1")
    longer = emitter.emit_value(f"trunc i64 {encoded} to i1")
    comparison = emitter.emit_value(
        f"select i1 {longer}, ptr @{emitter.string_constant(' is longer than ')}, "
        f"ptr @{emitter.string_constant(' is shorter than ')}")
    single = emitter.emit_value(f"icmp eq i64 {position}, 1")
    previous = emitter.emit_value(
        f"select i1 {single}, ptr @{emitter.string_constant('argument ')}, "
        f"ptr @{emitter.string_constant('arguments 1-')}")
    message = emitter.string_concat(f"@{emitter.string_constant('zip() argument ')}", emitter.string_from_int(argument))
    message = emitter.string_concat(message, comparison)
    message = emitter.string_concat(message, previous)
    message = emitter.string_concat(message, emitter.string_from_int(position))
    emitter.activate_error(node, NATIVE_ENVIRONMENT.builtins.search("ValueError"), message)
    emitter.branch_to_exception_target()
    emitter.emit_line(f"{ready}:")
    return emitter.emit_value(f"icmp ne i64 {result}, 0")


def next_value(emitter, iterator, member, node, fallback=None):
    kind = emitter.value_type(member)
    if fallback is None:
        output = emitter.emit_value(f"alloca {kind}")
        available = status(emitter, iterator, output, node, preserve_stop=True)
        emitter.guard_exception(node, available, "StopIteration", "")
        return kind, emitter.emit_value(f"load {kind}, ptr {output}")

    result_type = analyzed_value_type(node)
    result_kind = emitter.value_type(result_type)
    collection_ops.require_matching_layout(analyzed_value_type(node.args[1]), result_type, node)
    # The fallback was evaluated before resuming. Both it and the yielded item
    # must survive allocations while adapting either branch to the result type.
    kinds = [kind, result_kind, "ptr"] + ([] if fallback[0] == "void" else [fallback[0]])
    slots, frame = calls.value_slots(emitter, kinds)
    output, result, cursor = slots[:3]
    emitter.emit_line(f"store ptr {iterator}, ptr {cursor}")
    if fallback[0] != "void":
        emitter.emit_line(f"store {fallback[0]} {fallback[1]}, ptr {slots[3]}")
    available = status(emitter, iterator, output, node)
    present, missing, ready = (emitter.new_label(name) for name in ("next.present", "next.empty", "next.ready"))
    emitter.emit_line(f"br i1 {available}, label %{present}, label %{missing}")
    emitter.emit_line(f"{present}:")
    value = emitter.emit_value(f"load {kind}, ptr {output}")
    protocol = resolve_iterable_protocol(analyzed_value_type(node.args[0]),
                                        analyzed_representation(node.args[0]),
                                        NATIVE_ENVIRONMENT.builtins, iterator=True)
    _, value = collection_ops.convert_item(emitter, member, result_type, value, node,
                                          representation=protocol.item_representation)
    emitter.emit_line(f"store {result_kind} {value}, ptr {result}")
    emitter.emit_line(f"br label %{ready}")
    emitter.emit_line(f"{missing}:")
    # Adapt the default with its own source representation, not the joined
    # call result, which can hide a portable scalar behind an opaque object.
    _, value = collection_ops.convert_item(
        emitter, analyzed_value_type(node.args[1]), result_type, fallback[1], node.args[1],
        representation=analyzed_representation(node.args[1]),
    )
    emitter.emit_line(f"store {result_kind} {value}, ptr {result}")
    emitter.emit_line(f"br label %{ready}")
    emitter.emit_line(f"{ready}:")
    value = emitter.emit_value(f"load {result_kind}, ptr {result}")
    calls.pop_roots(emitter, frame)
    return result_kind, value


def membership(emitter, node):
    # The analyzer helper's parameters are (iterable, item), whereas Python's
    # membership expression evaluates the item before the iterable.
    if isinstance(getattr(node, "operator", None), (ast.In, ast.NotIn)):
        item_kind, item = emitter.expression(node.args[1])
        _, source = emitter.expression(node.args[0])
    else:
        _, source = emitter.expression(node.args[0])
        item_kind, item = emitter.expression(node.args[1])
    item_type = tagged.effective_type(analyzed_value_type(node.args[1]), item_kind)
    result = emitter.emit_value("alloca i1")
    emitter.emit_line(f"store i1 false, ptr {result}")
    done = emitter.new_label("membership.done")

    def compare(member, value):
        match = comparisons.equal_value(emitter, member, value, item_type, item, node)
        emitter.emit_line(f"store i1 {match}, ptr {result}")
        following = emitter.new_label("membership.next")
        emitter.emit_line(f"br i1 {match}, label %{done}, label %{following}")
        emitter.emit_line(f"{following}:")

    from .protocols import consumer
    source_type, source, frame = consumer(emitter, analyzed_value_type(node.args[0]), source, node)
    collection_ops.loop(emitter, source_type, source, compare, node, acquired=True)
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    calls.pop_roots(emitter, frame)
    return "i1", emitter.emit_value(f"load i1, ptr {result}")


def builtin(emitter, target, node):
    if target.py_func is builtins._iter and len(node.args) == 2:
        from .sentinel import create as sentinel_iterator
        return sentinel_iterator(emitter, node)
    if target.py_func in {builtins._map, builtins._filter}:
        from . import iterator_callbacks
        return iterator_callbacks.create(emitter, node)
    if target.py_func is contains_equal_sequence_item:
        return membership(emitter, node)
    name = target.name.removeprefix("_")
    arguments = [emitter.expression(argument) for argument in node.args]
    keywords = {keyword.arg: emitter.expression(keyword.value) for keyword in node.keywords}
    if name == "next":
        if not 1 <= len(arguments) <= 2 or keywords:
            raise LLVMUnsupported("LLVM next requires an iterator and optional positional default", node)
        source_type = analyzed_value_type(node.args[0])
        source = arguments[0][1]
        if source_type in emitter.module.application_iterators:
            from .protocols import wrap
            source = wrap(emitter, source_type, source, node)
        elif not is_iterator(source_type):
            raise LLVMUnsupported("LLVM next requires an Iterator value", node)
        return next_value(emitter, source, collection_ops.item_type(source_type), node,
                          arguments[1] if len(arguments) == 2 else None)
    if name in {"iter", "reversed"}:
        if len(arguments) != 1 or keywords:
            raise LLVMUnsupported(f"LLVM {name} requires one positional iterable", node)
        return "ptr", create(emitter, analyzed_value_type(node.args[0]), arguments[0][1], node, reverse=name == "reversed")
    if name == "enumerate":
        if (len(arguments) > 2 or set(keywords) - {"start", "iterable"}
                or arguments and "iterable" in keywords or len(arguments) == 2 and "start" in keywords):
            raise LLVMUnsupported("LLVM enumerate requires an iterable and optional start", node)
        start_node = node.args[1] if len(node.args) == 2 else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "start"), None)
        start = "0"
        if start_node is not None:
            from .indexing import integer
            argument = arguments[1] if len(arguments) == 2 else keywords["start"]
            start = integer(emitter, analyzed_value_type(start_node), *argument, node)
        iterable_node = node.args[0] if node.args else next(keyword.value for keyword in node.keywords if keyword.arg == "iterable")
        iterable = arguments[0] if arguments else keywords["iterable"]
        source = create(emitter, analyzed_value_type(iterable_node), iterable[1], node)
        result = new(emitter, runtime.ENUMERATE, source, index=start)
        offsets = row_layout(emitter, result, collection_ops.item_type(analyzed_value_type(node)))
        store(emitter, result, runtime.OFFSETS, "ptr", array(emitter, [("i64", offsets[1])]))
        return "ptr", result
    if set(keywords) - {"strict"}:
        raise LLVMUnsupported("LLVM zip only accepts the strict keyword", node)
    strict = keywords.get("strict", ("i1", "false"))
    if strict[0] != "i1":
        raise LLVMUnsupported("LLVM zip strict must be bool", node)
    sources, frame = create_many(emitter, [(analyzed_value_type(argument), value)
                                          for argument, (_, value) in zip(node.args, arguments, strict=True)], node)
    result = new(emitter, runtime.ZIP, "null")
    offsets = row_layout(emitter, result, collection_ops.item_type(analyzed_value_type(node)))
    store(emitter, result, runtime.COUNT, "i64", str(len(sources)))
    store(emitter, result, runtime.STRICT, "i64", emitter.emit_value(f"zext i1 {strict[1]} to i64"))
    store(emitter, result, runtime.CHILDREN, "ptr", array(emitter, [("ptr", source) for source in sources]))
    store(emitter, result, runtime.OFFSETS, "ptr", array(emitter, [("i64", offset) for offset in offsets]))
    calls.pop_roots(emitter, frame)
    return "ptr", result


def consume(emitter, value_type, iterator, visit, node):
    member = collection_ops.item_type(value_type)
    kind = emitter.value_type(member)
    output = emitter.emit_value(f"alloca {kind}")
    check, body, done = (emitter.new_label(label) for label in ("lazy.next", "lazy.item", "lazy.done"))
    emitter.emit_line(f"br label %{check}")
    emitter.emit_line(f"{check}:")
    available = status(emitter, iterator, output, node)
    emitter.emit_line(f"br i1 {available}, label %{body}, label %{done}")
    emitter.emit_line(f"{body}:")
    visit(member, emitter.emit_value(f"load {kind}, ptr {output}"))
    emitter.emit_line(f"br label %{check}")
    emitter.emit_line(f"{done}:")


def advance_loop(emitter, node, iterator, member):
    kind = emitter.value_type(member)
    output = emitter.emit_value(f"alloca {kind}")
    available = status(emitter, iterator, output, node)
    body = emitter.new_label("lazy.item")
    emitter.emit_line(f"br i1 {available}, label %{body}, label %{emitter.name(node.exhausted, 'block')}")
    emitter.emit_line(f"{body}:")
    emitter.assign_iterator_target(node.target, member, emitter.emit_value(f"load {kind}, ptr {output}"))
    emitter.emit_line(f"br label %{emitter.name(node.body, 'block')}")
