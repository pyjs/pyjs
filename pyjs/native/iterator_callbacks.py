"""Managed iterator steps using the ordinary function and exception ABI."""

import ast

from pyjs.analysis.analyzer import analyzed_value_type, callable_value_type
from pyjs.analysis.ir import FunctionIR, Return
from pyjs.analysis.objects import Function, Module, UnionType, union_type_key
from pyjs.python import native as builtins

from . import callback_ops, calls, collection_ops, iterator_ops
from . import itertools as streams
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .runtime import iteration as runtime

BUILTINS = {builtins._map, builtins._filter, streams.filterfalse, streams.takewhile,
            streams.dropwhile, streams.compress, streams.chain, streams.chain_from_iterable,
            streams.starmap, streams.accumulate, streams.groupby, builtins._iter}


def _step(state: object, output: object) -> int:
    raise NotImplementedError


class Advance(ast.expr):
    # The creation call supplies static types, not expressions to execute or
    # capture again. Runtime arguments come from the iterator's owned state.
    _fields = ()

    def __init__(self, source, *, comparison=False):
        self.source = source
        self.comparison = comparison
        self.obj = NATIVE_ENVIRONMENT.builtins.search("int")


def prepare(emitter, functions):
    for owner in functions:
        for block in owner.ir.blocks:
            for node in ast.walk(block):
                if not isinstance(node, ast.Call) or getattr(getattr(node.func, "obj", None), "py_func", None) not in BUILTINS:
                    continue
                if node.func.obj.py_func is builtins._iter and len(node.args) != 2:
                    continue
                if node in emitter.module.iterator_steps:
                    continue
                if node.func.obj.py_func in {streams.chain, streams.chain_from_iterable}:
                    from .itertools_ops import chain_inputs
                    # A collection input may never appear as an Iterator in
                    # source annotations. Reserve its conversion ABI before
                    # runtime/GC selection, not when the lazy step is emitted.
                    for _, cursor in chain_inputs(node):
                        emitter.module.iterator_signatures[union_type_key(cursor)] = cursor
                if node.func.obj.py_func in {streams.groupby, builtins._iter}:
                    # Key/sentinel equality can descend into scalar sequences
                    # without a source comparison to request that runtime.
                    emitter.module.uses_ordering = True
                for comparison in (False, True) if node.func.obj.py_func is streams.groupby else (False,):
                    register(emitter, functions, owner, (node, "equal") if comparison else node,
                             ast.copy_location(Advance(node, comparison=comparison), node))


def register(emitter, functions, owner, key, expression):
    module = owner.container if isinstance(owner.container, Module) else owner.container.container
    function = Function(_step, module)
    function.name = f"iterator_step.{len(emitter.module.iterator_steps)}"
    function.lineno = owner.lineno
    # Step expressions keep the creation call's function-relative coordinates,
    # not those of the Python stub used to name the generated callback.
    function.source_fragment = owner.source_fragment
    function.return_type = NATIVE_ENVIRONMENT.builtins.search("int")
    pointer = NATIVE_ENVIRONMENT.builtins.search("object")
    function.params = [ast.arg(arg=name, annotation=pointer.annotation) for name in ("state", "output")]
    function.ir = FunctionIR()
    function.ir.enter(function.ir.new_block("entry"))
    function.ir.terminate(Return(expression))
    function.exception_result = str(runtime.CALLBACK_ERROR)
    emitter.module.iterator_steps[key] = function
    emitter.module.function_names[function] = f"pyjs.{function.name}"
    emitter.module.functions.add(function)
    functions.append(function)


def load(emitter, state, offset, kind="ptr"):
    return emitter.emit_value(f"load {kind}, ptr {iterator_ops.slot(emitter, state, offset)}")


def arguments(node):
    if node.func.obj.py_func is streams.compress:
        named = dict(zip(("data", "selectors"), node.args, strict=False)) | {value.arg: value.value for value in node.keywords}
        return [named["data"], named["selectors"]]
    if node.keywords or len(node.args) < 2:
        raise LLVMUnsupported("LLVM map/filter require positional callback and iterable arguments", node)
    return node.args


def create(emitter, node):
    inputs = arguments(node)
    compress = node.func.obj.py_func is streams.compress
    # Bind in source order even when compress receives reordered keywords.
    evaluated = {argument: emitter.expression(argument) for argument in [*node.args, *(value.value for value in node.keywords)]}
    sources, frame = iterator_ops.create_many(emitter, [
        (analyzed_value_type(argument), evaluated[argument][1]) for argument in (inputs if compress else inputs[1:])
    ], node)
    result = iterator_ops.new(emitter, runtime.CALLBACK, "null")
    iterator_ops.store(emitter, result, runtime.COUNT, "i64", str(len(sources)))
    iterator_ops.store(emitter, result, runtime.CHILDREN, "ptr",
                       iterator_ops.array(emitter, [("ptr", value) for value in sources]))
    callback = evaluated[inputs[0]][1] if not compress and evaluated[inputs[0]][0] != "void" else "null"
    iterator_ops.store(emitter, result, runtime.CALLBACK_VALUE, "ptr", callback)
    iterator_ops.store(emitter, result, runtime.ADVANCE, "ptr",
                       "@" + emitter.function_name(emitter.module.iterator_steps[node]))
    calls.pop_roots(emitter, frame)
    return "ptr", result


def advance(emitter, node):
    source = node.source
    operation = source.func.obj.py_func
    if operation is builtins._iter:
        from .sentinel import advance
        return advance(emitter, node)
    if operation in {streams.chain, streams.chain_from_iterable}:
        from . import itertools_ops
        return itertools_ops.advance_chain(emitter, node)
    if operation is streams.accumulate:
        from . import itertools_ops
        return itertools_ops.advance_accumulate(emitter, node)
    if operation is streams.groupby:
        from . import grouping_ops
        return grouping_ops.callback(emitter, node)
    inputs = arguments(source)
    compress = operation is streams.compress
    star = operation is streams.starmap
    predicate = operation not in {builtins._map, streams.starmap}
    predicate_type = analyzed_value_type(inputs[0])
    if not compress and isinstance(predicate_type, UnionType):
        raise LLVMUnsupported("LLVM iterator predicates require a concrete callable or None; narrow nullable predicates before use", source)
    identity = compress or predicate_type.generic_name == "NoneType"
    arity = len(callable_value_type(inputs[0]).parameter_types or ()) if star else len(inputs) - 1
    contract = None if identity else callback_ops.signature(inputs[0], arity)
    member_types = [collection_ops.item_type(analyzed_value_type(value)) for value in (inputs if compress else inputs[1:])]
    kinds = [emitter.value_type(value) for value in member_types]
    slots, frame = calls.value_slots(emitter, kinds)
    state, output = emitter.load_local("state"), emitter.load_local("output")
    children = load(emitter, state, runtime.CHILDREN)
    callback = load(emitter, state, runtime.CALLBACK_VALUE)
    outcome = emitter.emit_value("alloca i64")
    emitter.emit_line(f"store i64 0, ptr {outcome}")
    again, done, error = (emitter.new_label(label) for label in ("adapter.next", "adapter.done", "adapter.error"))
    emitter.emit_line(f"br label %{again}")
    emitter.emit_line(f"{again}:")
    # Clear previous items before fetching another row. The frame independently
    # roots each item if a later source/predicate mutates earlier containers.
    for kind, slot in zip(kinds, slots, strict=True):
        emitter.emit_line(f"store {kind} zeroinitializer, ptr {slot}")
    for index, slot in enumerate(slots):
        child = load(emitter, children, index * 8)
        available = iterator_ops.status(emitter, child, slot, source, preserve_stop=True)
        ready = emitter.new_label("adapter.argument")
        emitter.emit_line(f"br i1 {available}, label %{ready}, label %{done}")
        emitter.emit_line(f"{ready}:")
    values = [emitter.emit_value(f"load {kind}, ptr {slot}") for kind, slot in zip(kinds, slots, strict=True)]
    selected = emitter.new_label("filter.selected") if predicate else None
    if operation is streams.dropwhile:
        active = emitter.new_label("dropwhile.test")
        passed = load(emitter, state, runtime.INDEX, "i64")
        passed = emitter.emit_value(f"icmp ne i64 {passed}, 0")
        emitter.emit_line(f"br i1 {passed}, label %{selected}, label %{active}")
        emitter.emit_line(f"{active}:")
    outer = emitter.exception_target
    emitter.exception_target = error
    try:
        if identity:
            index = 1 if compress else 0
            kind, value = kinds[index], values[index]
            accepted = truth(emitter, member_types[index], kind, value, source)
        else:
            parameters = list(zip(member_types, values, strict=True))
            if star:
                row_type, row = parameters[0]
                if row_type.generic_name != "tuple":
                    raise LLVMUnsupported("LLVM starmap requires typed tuple rows", source)
                if row_type.tuple_variadic:
                    length = emitter.emit_value(f"load i64, ptr {row}")
                    emitter.guard_exception(source, emitter.emit_value(f"icmp eq i64 {length}, {arity}"),
                                            "TypeError", "starmap row does not match callback arity; defaults are not supplied")
                    member = collection_ops.item_type(row_type)
                    data = collection_ops.storage(emitter, row, 2)
                    parameters = []
                    for index in range(arity):
                        slot = emitter.emit_value(f"getelementptr {emitter.value_type(member)}, ptr {data}, i64 {index}")
                        parameters.append((member, emitter.emit_value(f"load {emitter.value_type(member)}, ptr {slot}")))
                else:
                    if len(row_type.generic_types) != arity:
                        raise LLVMUnsupported("LLVM starmap row does not match callback arity", source)
                    parameters = collection_ops.tuple_items(emitter, row_type, row)
            kind, value = callback_ops.invoke(emitter, callback, contract,
                                               parameters, source)
            accepted = value if predicate else None
    finally:
        emitter.exception_target = outer
    if predicate:
        rejected = again
        if operation in {streams.filterfalse, streams.dropwhile}:
            accepted = emitter.emit_value(f"xor i1 {accepted}, true")
        if operation is streams.takewhile:
            rejected = emitter.new_label("takewhile.stopped")
        emitter.emit_line(f"br i1 {accepted}, label %{selected}, label %{rejected}")
        if operation is streams.takewhile:
            emitter.emit_line(f"{rejected}:")
            iterator_ops.store(emitter, state, runtime.EXHAUSTED, "i64", "1")
            emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{selected}:")
        if operation is streams.dropwhile:
            iterator_ops.store(emitter, state, runtime.INDEX, "i64", "1")
        kind, value = kinds[0], values[0]
        # A predicate forwards its loaded item, not the enclosing iterator.
        emitter.value_semantics[kind, value] = member_types[0]
    expected = collection_ops.item_type(analyzed_value_type(source))
    kind, value = emitter.coerce_value(kind, value, emitter.value_type(expected), source, semantic=expected)
    emitter.emit_line(f"store {kind} {value}, ptr {output}")
    emitter.emit_line(f"store i64 1, ptr {outcome}")
    emitter.emit_line(f"br label %{done}")
    callback_failure(emitter, error, frame)
    emitter.emit_line(f"{done}:")
    result = emitter.emit_value(f"load i64, ptr {outcome}")
    calls.pop_roots(emitter, frame)
    return "i64", result


def callback_failure(emitter, error, frame):
    # The consumer decides whether to clear StopIteration. Forward the original
    # exception, including callback/equality errors, through the checked ABI.
    emitter.emit_line(f"{emitter.name(error, 'block')}:")
    calls.restore_roots(emitter, frame)
    calls.pop_roots(emitter, frame)
    emitter.branch_to_exception_target()


def failure_status(emitter):
    # Runtime adapters cannot inspect module-specific exception type tokens.
    # Carry the category alongside the untouched exception record instead.
    token = emitter.emit_value(f"load ptr, ptr {emitter.exception_field(1)}")
    stopped = emitter.exception_matches(token, (NATIVE_ENVIRONMENT.builtins.search("StopIteration"),))
    return emitter.emit_value(f"select i1 {stopped}, i64 {runtime.CALLBACK_STOP}, i64 {runtime.CALLBACK_ERROR}")


def truth(emitter, member, kind, value, node):
    # Use the same runtime protocol order as bool(), including a subclass-only
    # __bool__ ahead of an inherited __len__ and nullable/tagged item dispatch.
    item = ast.copy_location(ast.Name(id="item", ctx=ast.Load()), node)
    item.obj = member
    return emitter.truth_value(item, kind, value)
