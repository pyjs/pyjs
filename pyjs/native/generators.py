"""Suspended ordinary function CFGs backed by managed, typed local slots."""

import ast
from dataclasses import dataclass, field

from pyjs.analysis.analyzer import (
    analyzed_value_object,
    analyzed_value_type,
    is_return_type_compatible,
)
from pyjs.analysis.ir import (
    Block,
    ExceptionCatch,
    ExceptionRaise,
    ObjectNew,
    Return,
    Suspend,
)
from pyjs.analysis.objects import Class
from pyjs.analysis.type_relations import is_subclass
from pyjs.analysis.value_representation import (
    analyzed_representation,
    representation_for_member,
)

from . import (
    calls,
    closures,
    collection_ops,
    exception_values,
    gc_layouts,
    iterator_ops,
    iterator_views,
    nullable,
    object_values,
)
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .runtime import iteration as runtime


@dataclass
class Frame:
    name: str
    states: dict[str, int]
    fields: dict[str, str] = field(default_factory=dict)
    flags: tuple[str, ...] = ()
    snapshots: tuple[int, ...] = ()
    suspensions: dict[str, tuple[Suspend, str | None]] = field(default_factory=dict)
    input_type: object = None

    @property
    def storage(self):
        return (*self.fields.values(), *(['i1'] * len(self.flags)),
                *(['%pyjs.exception'] * len(self.snapshots)))


class Create(ast.expr):
    _fields = ()

    def __init__(self, function):
        self.function = function
        self.obj = function.return_type


def prepare(emitter, functions):
    for function in functions:
        if not function.is_generator:
            continue
        if not iterator_ops.is_iterator(function.return_type):
            raise LLVMUnsupported("LLVM generators require an Iterator return type", function.original_node)
        states = {function.ir.blocks[0].name: 0}
        for block in function.ir.blocks:
            if isinstance(block.body[-1], Suspend):
                states.setdefault(block.body[-1].resume, len(states))
        frame = Frame(f"pyjs.generator.{len(emitter.module.generators)}", states)
        frame.input_type = (function.return_type.generic_types["S"]
                            if function.return_type.generic_name == "Generator"
                            else function.send_type or NATIVE_ENVIRONMENT.builtins.search("NoneType"))
        frame.suspensions = {block.body[-1].resume: (block.body[-1], block.exception_target)
                             for block in function.ir.blocks if isinstance(block.body[-1], Suspend)}
        emitter.module.generators[function] = frame
    if emitter.module.generators:
        emitter.module.uses_iterators = emitter.module.uses_collections = True
        emitter.module.uses_strings = emitter.module.uses_ranges = True


def factory_blocks(function):
    block = Block("entry")
    block.body = [ast.copy_location(Return(ast.copy_location(Create(function), function.original_node)),
                                    function.original_node)]
    return [block]


def layout(emitter):
    frame = emitter.module.generators[emitter.current_function]
    emitter.slot_types["__generator.input"] = emitter.value_type(frame.input_type)
    cells = closures.bindings(emitter)
    ephemeral = {"__arena", "__heap", "__exception", "__closure.context"}
    # Expression roots are added after layout and last only for one resume.
    # Lexical cells themselves, rather than copied values, survive suspension.
    frame.fields = {name: kind for name, kind in emitter.slot_types.items()
                    if kind != "void" and name not in cells and name not in ephemeral}
    frame.flags = tuple(name for name in frame.fields if "." not in name)
    # Handler bindings and pending finally reraises point at these snapshots.
    # They must survive the native resume call's stack, just like ordinary locals.
    frame.snapshots = tuple(id(node) for block in emitter.current_function.ir.blocks
                            for node in block.body if isinstance(node, ExceptionCatch))


def definition(frame):
    return f"%{frame.name} = type {{ {', '.join(frame.storage)} }}"


def address(emitter, frame, pointer, index):
    return emitter.emit_value(f"getelementptr %{frame.name}, ptr {pointer}, i32 0, i32 {index}")


def create(emitter, node):
    frame = emitter.module.generators[node.function]
    pointer = gc_layouts.allocate(emitter, frame.storage, layout=f"%{frame.name}")
    for index, (name, kind) in enumerate(frame.fields.items()):
        value = emitter.load_local(name)
        emitter.emit_line(f"store {kind} {value}, ptr {address(emitter, frame, pointer, index)}")
    parameters = {parameter.arg for parameter in calls.parameters(node.function)}
    if node.function.is_method and not node.function.is_static:
        parameters.add("self")
    for index, name in enumerate(frame.flags, len(frame.fields)):
        emitter.emit_line(f"store i1 {str(name in parameters).lower()}, ptr {address(emitter, frame, pointer, index)}")
    for index in range(len(frame.snapshots)):
        snapshot = address(emitter, frame, pointer, len(frame.fields) + len(frame.flags) + index)
        emitter.emit_line(f"store %pyjs.exception zeroinitializer, ptr {snapshot}")
    state = iterator_ops.new(emitter, runtime.GENERATOR, pointer)
    iterator_ops.store(emitter, state, runtime.ADVANCE, "ptr", "@" + emitter.function_name(node.function) + ".resume")
    # A stable interior pointer exposes the typed input slot without allocating
    # a per-send box or retaining a pointer to the caller's stack.
    incoming = address(emitter, frame, pointer, tuple(frame.fields).index("__generator.input"))
    iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", incoming)
    iterator_ops.store(emitter, state, runtime.STEP, "i64", "0")
    return "ptr", state


def enter(emitter):
    frame = emitter.generator_frame
    state = emitter.load_local("__generator.state")
    active = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.STRICT)}")
    reentrant, available = emitter.new_label("generator.reentrant"), emitter.new_label("generator.available")
    busy = emitter.emit_value(f"icmp ne i64 {active}, 0")
    emitter.emit_line(f"br i1 {busy}, label %{reentrant}, label %{available}")
    emitter.emit_line(f"{reentrant}:")
    # This invocation owns no frame yet. Do not close the generator that is
    # still executing in the caller; it may catch this reentrancy error.
    emitter.activate_error(emitter.current_function.original_node, NATIVE_ENVIRONMENT.builtins.search("ValueError"),
                           f"@{emitter.string_constant('generator already executing')}")
    emitter.emit_line(f"ret i64 {runtime.CALLBACK_ERROR}")
    emitter.emit_line(f"{available}:")
    pointer = emitter.emit_value(f"load ptr, ptr {iterator_ops.slot(emitter, state, runtime.SOURCE)}")
    for index, name in enumerate(frame.fields):
        emitter.slots[name] = address(emitter, frame, pointer, index)
    for index, name in enumerate(frame.flags, len(frame.fields)):
        emitter.cell_flags[name] = address(emitter, frame, pointer, index)
    for index, identity in enumerate(frame.snapshots, len(frame.fields) + len(frame.flags)):
        emitter.exception_snapshots[identity] = address(emitter, frame, pointer, index)
    closures.restore(emitter)
    iterator_ops.store(emitter, state, runtime.STRICT, "i64", "1")


def dispatch(emitter, entry):
    state = emitter.load_local("__generator.state")
    position = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.INDEX)}")
    # close/throw inject at the suspended yield, not at the next statement.
    # Its recorded exception edge already contains the right handler/cleanup
    # routing, including yields inside a handler or an exceptional finally.
    normal, injected = emitter.new_label("generator.normal"), emitter.new_label("generator.injected")
    active = emitter.emit_value(f"load i1, ptr {emitter.exception_field(0)}")
    emitter.emit_line(f"br i1 {active}, label %{injected}, label %{normal}")
    emitter.emit_line(f"{injected}:")
    edges = {name: emitter.new_label("generator.injected.yield") for name in emitter.generator_frame.suspensions}
    exceptional_cases = " ".join(f"i64 {emitter.generator_frame.states[name]}, label %{label}"
                                 for name, label in edges.items())
    emitter.emit_line(f"switch i64 {position}, label %pyjs.exception.return [ {exceptional_cases} ]")
    for name, label in edges.items():
        suspension, target = emitter.generator_frame.suspensions[name]
        emitter.emit_line(f"{label}:")
        emitter.prepend_exception_frame(suspension)
        destination = emitter.name(target, 'block') if target else "pyjs.exception.return"
        emitter.emit_line(f"br label %{destination}")
    emitter.emit_line(f"{normal}:")
    invalid = emitter.new_label("generator.invalid")
    cases = " ".join(f"i64 {index}, label %{emitter.name(name, 'block')}"
                     for name, index in emitter.generator_frame.states.items())
    emitter.emit_line(f"switch i64 {position}, label %{invalid} [ {cases} ]")
    emitter.emit_line(f"{invalid}:")
    emitter.emit_line("unreachable")
    emitter.emit_line(f"{emitter.name(entry, 'block')}:")


def complete(emitter, node):
    status = "0"
    empty = node.value is None or isinstance(node.value, ast.Constant) and node.value.value is None
    if empty:
        function = emitter.current_function
        result = (function.return_type.generic_types["R"]
                  if function.return_type.generic_name == "Generator" else function.inferred_return_type)
        none = NATIVE_ENVIRONMENT.builtins.search("NoneType")
        if result is not None and not is_return_type_compatible(result, none):
            source = node if hasattr(node, "lineno") else function.original_node
            emitter.raise_error(source, "TypeError",
                                f"{function.name} returned None through a non-optional completion contract")
            return
    else:
        stopped = ast.copy_location(ExceptionRaise(
            NATIVE_ENVIRONMENT.builtins.search("StopIteration"), node.value,
        ), node.value)
        retained, represented = exception_values.payload(emitter, stopped, completion=True)
        # Completion is not an escaping body exception (PEP 479). Reuse its
        # retained payload transport without entering handlers or converting it
        # into RuntimeError. Boxing can still fail at the return's cleanup edge.
        absent = emitter.emit_value(f"icmp eq ptr {retained}, null")
        message = emitter.emit_value(
            f"select i1 {absent}, ptr @{emitter.string_constant('')}, ptr null")
        emitter.activate_exception(stopped, (message, retained), include_frame=False)
        emitter.emit_line(f"store i1 {represented}, ptr {emitter.exception_field(6)}")
        status = str(runtime.CALLBACK_STOP)
    finish(emitter)
    emitter.pop_gc_frame()
    emitter.emit_line(f"ret i64 {status}")


def finish(emitter):
    state = emitter.load_local("__generator.state")
    iterator_ops.store(emitter, state, runtime.SOURCE, "ptr", "null")
    iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", "null")
    iterator_ops.store(emitter, state, runtime.EXHAUSTED, "i64", "1")
    iterator_ops.store(emitter, state, runtime.STRICT, "i64", "0")


def close(emitter, state, value_type, node, *, discard=False):
    state = iterator_views.control(emitter, state)
    completion = emitter.emit_value("alloca ptr")
    emitter.emit_line(f"store ptr null, ptr {completion}")
    busy = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.STRICT)}")
    emitter.guard_exception(node, emitter.emit_value(f"icmp eq i64 {busy}, 0"),
                            "ValueError", "generator already executing")
    done, available, unstarted, started = (emitter.new_label("close." + name)
                                          for name in ("done", "available", "unstarted", "started"))
    exhausted = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.EXHAUSTED)}")
    closed = emitter.emit_value(f"icmp ne i64 {exhausted}, 0")
    emitter.emit_line(f"br i1 {closed}, label %{done}, label %{available}")
    emitter.emit_line(f"{available}:")
    position = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.INDEX)}")
    fresh = emitter.emit_value(f"icmp eq i64 {position}, 0")
    emitter.emit_line(f"br i1 {fresh}, label %{unstarted}, label %{started}")
    emitter.emit_line(f"{unstarted}:")
    iterator_ops.store(emitter, state, runtime.SOURCE, "ptr", "null")
    iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", "null")
    iterator_ops.store(emitter, state, runtime.EXHAUSTED, "i64", "1")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{started}:")
    emitter.activate_error(node, NATIVE_ENVIRONMENT.builtins.search("GeneratorExit"),
                           f"@{emitter.string_constant('')}", include_frame=False)
    # close never exposes a yielded item. Resume the canonical frame directly,
    # avoiding conversion/allocation in views before reporting an ignored exit.
    callback = emitter.emit_value(f"load ptr, ptr {iterator_ops.slot(emitter, state, runtime.ADVANCE)}")
    status = emitter.emit_value(f"call i64 {callback}(ptr {emitter.load_local('__arena')}, "
                                f"ptr {emitter.load_local('__heap')}, ptr {emitter.load_local('__exception')}, "
                                f"ptr {state}, ptr null)")
    yielded = emitter.emit_value(f"icmp eq i64 {status}, 1")
    emitter.guard_exception(node, emitter.emit_value(f"xor i1 {yielded}, true"),
                            "RuntimeError", "generator ignored GeneratorExit")
    stopped = emitter.emit_value(f"icmp eq i64 {status}, {runtime.CALLBACK_STOP}")
    returned, check_exit = emitter.new_label("close.returned"), emitter.new_label("close.exit")
    emitter.emit_line(f"br i1 {stopped}, label %{returned}, label %{check_exit}")
    emitter.emit_line(f"{returned}:")
    payload = emitter.emit_value(f"load ptr, ptr {emitter.exception_field(5)}")
    emitter.emit_line(f"store ptr {payload}, ptr {completion}")
    emitter.emit_line(f"store %pyjs.exception zeroinitializer, ptr {emitter.load_local('__exception')}")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{check_exit}:")
    token = emitter.emit_value(f"load ptr, ptr {emitter.exception_field(1)}")
    exited = emitter.exception_matches(token, (NATIVE_ENVIRONMENT.builtins.search("GeneratorExit"),))
    cleared, checked = emitter.new_label("close.cleared"), emitter.new_label("close.checked")
    emitter.emit_line(f"br i1 {exited}, label %{cleared}, label %{checked}")
    emitter.emit_line(f"{cleared}:")
    emitter.emit_line(f"store %pyjs.exception zeroinitializer, ptr {emitter.load_local('__exception')}")
    emitter.emit_line(f"br label %{checked}")
    emitter.emit_line(f"{checked}:")
    emitter.check_active_exception(node)
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    if discard or getattr(value_type.generic_types["R"], "generic_name", None) == "NoneType":
        return "ptr", "null"
    value = emitter.emit_value(f"load ptr, ptr {completion}")
    # No allocation occurs while projecting: the exception record can release
    # ownership before the ordinary expression root takes over the result.
    return object_values.project(emitter, value, analyzed_value_type(node), node)


def thrown_exception(node):
    """Use the same borrowed exception/message boundary as ordinary raise."""
    if len(node.args) != 1 or node.keywords:
        raise LLVMUnsupported("LLVM generator throw() takes one positional exception", node)
    argument = node.args[0]
    value = analyzed_value_object(argument)
    call = argument.call if isinstance(argument, ObjectNew) else argument
    base = NATIVE_ENVIRONMENT.builtins.search("BaseException")
    if isinstance(value, Class) and is_subclass(value, base):
        return ast.copy_location(ExceptionRaise(value, None), argument)
    if isinstance(call, ast.Call) and isinstance(analyzed_value_object(call.func), Class):
        value_type = analyzed_value_type(argument)
        if not isinstance(value_type, Class) or not is_subclass(value_type, base):
            raise LLVMUnsupported("LLVM throw() requires an exception", argument)
        if len(call.args) > 1 or call.keywords:
            raise LLVMUnsupported("LLVM exception constructors take at most one positional message", argument)
        return ast.copy_location(ExceptionRaise(value_type, call.args[0] if call.args else None), argument)
    if isinstance(argument, ast.Name) and getattr(value, "native_exception_binding", False):
        return ast.copy_location(ExceptionRaise(None, None, reraised=True, exception=argument), argument)
    raise LLVMUnsupported("LLVM throw() requires a known exception class, constructor, or bound exception", argument)


def throw(emitter, state, value_type, node):
    view, state = state, iterator_views.control(emitter, state)
    raised = thrown_exception(node)
    # Argument evaluation/conversion can fail or collect before reentry checks,
    # but must not inject anything or alter the suspended generator on failure.
    payload = emitter.exception_payload(raised)
    busy = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.STRICT)}")
    emitter.guard_exception(node, emitter.emit_value(f"icmp eq i64 {busy}, 0"),
                            "ValueError", "generator already executing")
    emitter.activate_exception(raised, payload, include_frame=False)
    position = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.INDEX)}")
    exhausted = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.EXHAUSTED)}")
    fresh = emitter.emit_value(f"icmp eq i64 {position}, 0")
    closed = emitter.emit_value(f"icmp ne i64 {exhausted}, 0")
    inactive = emitter.emit_value(f"or i1 {fresh}, {closed}")
    direct, resume = emitter.new_label("throw.direct"), emitter.new_label("throw.resume")
    emitter.emit_line(f"br i1 {inactive}, label %{direct}, label %{resume}")
    emitter.emit_line(f"{direct}:")
    # No body has been entered here. In particular, StopIteration is not
    # transformed into RuntimeError, nor may a fresh try/finally execute.
    iterator_ops.store(emitter, state, runtime.SOURCE, "ptr", "null")
    iterator_ops.store(emitter, state, runtime.CALLBACK_VALUE, "ptr", "null")
    iterator_ops.store(emitter, state, runtime.EXHAUSTED, "i64", "1")
    emitter.prepend_exception_frame(node)
    emitter.branch_to_exception_target()
    emitter.emit_line(f"{resume}:")
    return iterator_ops.next_value(emitter, view, collection_ops.item_type(value_type), node)


def clear_input(emitter):
    kind = emitter.value_type(emitter.generator_frame.input_type)
    empty = "null" if kind == "ptr" else "zeroinitializer"
    emitter.emit_line(f"store {kind} {empty}, ptr {emitter.slots['__generator.input']}")
    iterator_ops.store(emitter, emitter.load_local("__generator.state"), runtime.STEP, "i64", "0")


def receive(emitter, node):
    if node.discard:
        clear_input(emitter)
        return "void", ""
    frame = emitter.generator_frame
    state = emitter.load_local("__generator.state")
    sent = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.STEP)}")
    present = emitter.emit_value(f"icmp ne i64 {sent}, 0")
    expected = analyzed_value_type(node)
    kind = emitter.value_type(expected)
    result = emitter.emit_value(f"alloca {kind}")
    yes, no, done = (emitter.new_label("receive." + name) for name in ("sent", "none", "ready"))
    emitter.emit_line(f"br i1 {present}, label %{yes}, label %{no}")
    emitter.emit_line(f"{no}:")
    if is_return_type_compatible(expected, NATIVE_ENVIRONMENT.builtins.search("NoneType")):
        _, value = emitter.coerce_value("void", "", kind, node, semantic=expected)
        emitter.emit_line(f"store {kind} {value}, ptr {result}")
        emitter.emit_line(f"br label %{done}")
    else:
        emitter.activate_error(node, NATIVE_ENVIRONMENT.builtins.search("TypeError"),
                               f"@{emitter.string_constant('generator received None for a nonnullable yield result')}")
        emitter.branch_to_exception_target()
    emitter.emit_line(f"{yes}:")
    wire_kind = emitter.value_type(frame.input_type)
    value = emitter.emit_value(f"load {wire_kind}, ptr {emitter.slots['__generator.input']}")
    emitter.value_semantics[wire_kind, value] = frame.input_type
    # A suspended frame stores the declared send layout, not the narrowed
    # receiver's view. Keep that source witness when adapting the loaded value.
    emitter.value_representations[wire_kind, value] = emitter.current_function.send_representation
    _, value = emitter.coerce_value(wire_kind, value, kind, node, semantic=expected,
                                    representation=analyzed_representation(node))
    emitter.emit_line(f"store {kind} {value}, ptr {result}")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    clear_input(emitter)
    return kind, emitter.emit_value(f"load {kind}, ptr {result}")


def send(emitter, state, value_type, node):
    kind, value = emitter.expression(node.args[0])
    view, state = state, iterator_views.control(emitter, state)
    busy = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.STRICT)}")
    emitter.guard_exception(node, emitter.emit_value(f"icmp eq i64 {busy}, 0"),
                            "ValueError", "generator already executing")
    exhausted = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.EXHAUSTED)}")
    emitter.guard_exception(node, emitter.emit_value(f"icmp eq i64 {exhausted}, 0"), "StopIteration", "")
    if kind == "void":
        iterator_ops.store(emitter, state, runtime.STEP, "i64", "0")
        return iterator_ops.next_value(emitter, view, collection_ops.item_type(value_type), node)
    present = nullable.present(emitter, kind, value)
    position = emitter.emit_value(f"load i64, ptr {iterator_ops.slot(emitter, state, runtime.INDEX)}")
    started = emitter.emit_value(f"icmp ne i64 {position}, 0")
    missing = emitter.emit_value(f"xor i1 {present}, true")
    valid = emitter.emit_value(f"or i1 {started}, {missing}")
    emitter.guard_exception(node, valid, "TypeError", "can't send non-None value to a just-started generator")
    yes, no, ready = (emitter.new_label("send." + name) for name in ("value", "none", "ready"))
    emitter.emit_line(f"br i1 {present}, label %{yes}, label %{no}")
    emitter.emit_line(f"{yes}:")
    expected = value_type.generic_types["S"]
    wire_kind = emitter.value_type(expected)
    representation = representation_for_member(analyzed_value_type(node.func.value),
                                               analyzed_representation(node.func.value), value_type)
    _, value = emitter.coerce_value(kind, value, wire_kind, node.args[0], semantic=expected,
                                    representation=representation.arguments[1] if representation else None)
    if emitter.module.uses_iterator_views:
        iterator_views.store_send(emitter, view, wire_kind, value, node)
    else:
        destination = emitter.emit_value(f"load ptr, ptr {iterator_ops.slot(emitter, state, runtime.CALLBACK_VALUE)}")
        emitter.emit_line(f"store {wire_kind} {value}, ptr {destination}")
        iterator_ops.store(emitter, state, runtime.STEP, "i64", "1")
    emitter.emit_line(f"br label %{ready}")
    emitter.emit_line(f"{no}:")
    iterator_ops.store(emitter, state, runtime.STEP, "i64", "0")
    emitter.emit_line(f"br label %{ready}")
    emitter.emit_line(f"{ready}:")
    return iterator_ops.next_value(emitter, view, collection_ops.item_type(value_type), node)


def suspend(emitter, node):
    member = collection_ops.item_type(emitter.current_function.return_type)
    kind, value = emitter.expression(node.value)
    collection_ops.require_matching_layout(analyzed_value_type(node.value), member, node)
    # Pointer storage alone cannot distinguish a concrete payload from an
    # erased object header. Supply both the yielded type and its representation:
    # a yielded generator handle can itself need a contravariant send adapter.
    representation = emitter.current_function.return_representation
    kind, value = emitter.coerce_value(kind, value, emitter.value_type(member), node, semantic=member,
                                       representation=representation.item_representation if representation else None)
    output = emitter.load_local("__generator.output")
    # A canonical close resume passes no output buffer: the item is discarded
    # and its source layout need not be known by a differently typed view.
    used = emitter.emit_value(f"icmp ne ptr {output}, null")
    store, done = emitter.new_label("yield.store"), emitter.new_label("yield.stored")
    emitter.emit_line(f"br i1 {used}, label %{store}, label %{done}")
    emitter.emit_line(f"{store}:")
    emitter.emit_line(f"store {kind} {value}, ptr {output}")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    clear_input(emitter)
    state = emitter.load_local("__generator.state")
    iterator_ops.store(emitter, state, runtime.INDEX, "i64", str(emitter.generator_frame.states[node.resume]))
    iterator_ops.store(emitter, state, runtime.STRICT, "i64", "0")
    emitter.pop_gc_frame()
    emitter.emit_line("ret i64 1")


def failed(emitter):
    finish(emitter)
    token = emitter.emit_value(f"load ptr, ptr {emitter.exception_field(1)}")
    stopped = emitter.exception_matches(token, (NATIVE_ENVIRONMENT.builtins.search("StopIteration"),))
    convert, done = emitter.new_label("generator.stop"), emitter.new_label("generator.failed")
    emitter.emit_line(f"br i1 {stopped}, label %{convert}, label %{done}")
    emitter.emit_line(f"{convert}:")
    emitter.activate_error(emitter.current_function.original_node, NATIVE_ENVIRONMENT.builtins.search("RuntimeError"),
                           f"@{emitter.string_constant('generator raised StopIteration')}")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
