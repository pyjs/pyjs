"""Typed cursor views share advancement and generator control with their source.

Only yield/send conversion belongs to a view. It never owns a second resume
position, exception state or input slot. Synthetic steps use the ordinary
checked function ABI, including roots and the caller's exception record.
"""

import ast

from pyjs.analysis.ir import FunctionIR, Return
from pyjs.analysis.objects import Function, same_analyzer_type, union_type_key
from pyjs.analysis.type_relations import get_type_members, is_return_type_compatible
from pyjs.analysis.value_representation import (
    analyzed_representation,
    representation_for_member,
)

from . import calls, collection_ops, iterator_callbacks, iterator_ops, nullable
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .runtime import iteration as runtime


def needed(source, target):
    return (not same_analyzer_type(collection_ops.item_type(source), collection_ops.item_type(target))
            or target.generic_name == 'Generator' and (source.generic_name != 'Generator'
                or not same_analyzer_type(source.generic_types['S'], target.generic_types['S'])))


def check(source, target, node, *, adapt=True):
    if target.generic_name == 'Generator' and source.generic_name != 'Generator':
        raise LLVMUnsupported('LLVM Generator views require a Generator source', node)
    if not is_return_type_compatible(target, source):
        raise LLVMUnsupported('LLVM iterator views require covariant yields/results and contravariant sends', node)
    if not adapt and needed(source, target):
        raise LLVMUnsupported('LLVM stored iterator views require matching item and send layouts', node)
    pairs = [(collection_ops.item_type(source), collection_ops.item_type(target), True)]
    if target.generic_name == 'Generator':
        pairs.append((target.generic_types['S'], source.generic_types['S'], True))
        # Completion travels as the original boxed StopIteration payload, not
        # through a per-item adapter. Its enclosing mutable/aggregate storage
        # cannot be reinterpreted merely because the annotations are covariant.
        pairs.append((source.generic_types['R'], target.generic_types['R'], False))
    for actual, expected, adapt_value in pairs:
        from .callable_adapters import plain_builtin
        # Every possible source kind must survive an unconverted completion.
        # Optional transport does not change that domain. Tagged destinations
        # are checked below: int -> int | float preserves the original tag.
        right = nullable.member(expected) or expected
        for left in get_type_members(actual):
            if (collection_ops.builtin_name(left) != 'NoneType' and not same_analyzer_type(left, right)
                    and plain_builtin(left) and plain_builtin(right)):
                raise LLVMUnsupported('LLVM iterator views require an explicit numeric conversion', node)
        collection_ops.require_matching_layout(actual, expected, node, adapt_value=adapt_value)


def reserve(e):
    types = tuple(e.module.iterator_signatures.values())
    for source in types:
        for target in types:
            if source is target or not is_return_type_compatible(target, source) or not needed(source, target):
                continue
            try:
                check(source, target, None)
            except LLVMUnsupported:
                continue
            e.module.uses_iterator_views = True
            e.module.uses_iterators = e.module.uses_collections = True
            e.module.uses_strings = e.module.uses_ranges = True
            return


def _adapter():
    raise NotImplementedError


class Operation(ast.expr):
    _fields = ()

    def __init__(self, source, target, operation, representation, target_representation):
        self.source, self.target, self.operation = source, target, operation
        self.source_representation = representation
        self.target_representation = target_representation
        self.obj = NATIVE_ENVIRONMENT.builtins.search('int')


def register(e, source, target, node, *, operation='next', representation=None, target_representation=None):
    key = union_type_key(source), union_type_key(target), operation, representation, target_representation
    if key not in e.module.iterator_views:
        function = Function(_adapter, e.module.entry_module)
        function.name = f'iterator.view.{len(e.module.iterator_views)}'
        function.source_fragment = e.current_function.source_fragment
        function.return_type = NATIVE_ENVIRONMENT.builtins.search('int')
        pointer = NATIVE_ENVIRONMENT.builtins.search('object')
        function.params = [ast.arg(arg=name, annotation=pointer.annotation) for name in ('state', 'output')]
        function.exception_result = str(runtime.CALLBACK_ERROR)
        function.ir = FunctionIR()
        function.ir.enter(function.ir.new_block('entry'))
        function.ir.terminate(Return(ast.copy_location(
            Operation(source, target, operation, representation, target_representation), node)))
        e.module.function_names[function] = f'pyjs.{function.name}'
        e.module.functions.add(function)
        e.module.iterator_views[key] = function
    return e.module.iterator_views[key]


def symbol(e, source, target, node, *, operation='next', representation=None, target_representation=None):
    return '@' + e.function_name(register(e, source, target, node, operation=operation,
                                         representation=representation, target_representation=target_representation))


def wrap(e, source, target, value, node, *, representation=None, target_representation=None, kind=runtime.ADAPTER):
    roots = calls.root_values(e, value)
    result = iterator_ops.new(e, kind, value)
    iterator_ops.store(e, result, runtime.ADVANCE, 'ptr', symbol(e, source, target, node,
                       representation=representation, target_representation=target_representation))
    if target.generic_name == 'Generator':
        iterator_ops.store(e, result, runtime.CALLBACK_VALUE, 'ptr',
                           symbol(e, source, target, node, operation='send', representation=representation,
                                  target_representation=target_representation))
    if e.module.application_iterators:
        iterator_ops.store(e, result, runtime.OFFSETS, 'ptr',
                           symbol(e, source, target, node, operation='iter', representation=representation,
                                  target_representation=target_representation))
    calls.pop_roots(e, roots)
    if root := e.expression_roots.get(id(node)):
        e.emit_line(f'store ptr {result}, ptr {root}')
    return result


def convert(e, kind, value, expected, node, *, representation=None):
    actual = e.value_semantics.get((kind, value))
    source, target = nullable.member(actual) or actual, nullable.member(expected) or expected
    if not iterator_ops.is_iterator(source) or not iterator_ops.is_iterator(target):
        return None
    check(source, target, node)
    if not needed(source, target):
        return kind, value
    represented = representation_for_member(actual, e.value_representations.get((kind, value)), source)
    target_representation = representation_for_member(expected, representation, target)
    if nullable.member(actual):
        result = nullable.dispatch(e, actual, kind, value, 'ptr', 'null',
            lambda member, storage, payload: wrap(e, source, target, payload, node, representation=represented,
                                                 target_representation=target_representation))
    else:
        result = wrap(e, source, target, value, node, representation=represented,
                      target_representation=target_representation)
    e.value_semantics['ptr', result] = expected
    e.value_representations['ptr', result] = representation
    return 'ptr', result


def read(e, declared, narrowed, kind, value, node, *, representation=None):
    source, target = nullable.member(declared) or declared, nullable.member(narrowed) or narrowed
    represented = representation_for_member(declared, representation, source)
    if iterator_ops.is_iterator(source) and target in e.module.classes:
        from . import protocols
        if nullable.member(declared) and nullable.member(narrowed):
            return 'ptr', nullable.dispatch(e, declared, kind, value, 'ptr', 'null',
                lambda member, storage, payload: read(e, member, target, storage, payload, node,
                                                      representation=represented)[1])
        if nullable.member(declared):
            nullable.check_narrowing(e, kind, value, target, node, 'application cursor')
        # A captured local or field may have changed since the flow proof.
        # Validate the live handle before recovering its application pointer.
        valid = protocols.instancecheck(e, value, target, node)
        e.guard_exception(node, valid, 'TypeError', 'iterator view has a different source class')
        return 'ptr', e.emit_value(f'call ptr @pyjs.iterator.identity(ptr {value})')
    if (not iterator_ops.is_iterator(source) or not iterator_ops.is_iterator(target)
            or same_analyzer_type(source, target) or not needed(target, source)):
        return None
    # A flow-narrowed local still holds its declared output ABI. Recover only
    # the exact inverse view, not an unchecked pointer reinterpretation. This
    # also avoids accumulating views in repeated narrow/store loops.
    if nullable.member(declared) and nullable.member(narrowed):
        return 'ptr', nullable.dispatch(e, declared, kind, value, 'ptr', 'null',
            lambda member, storage, payload: read(e, member, target, storage, payload, node,
                                                  representation=represented)[1])
    if nullable.member(declared):
        nullable.check_narrowing(e, kind, value, target, node, 'iterator view')
    check(target, source, node)
    actual = iterator_callbacks.load(e, value, runtime.ADVANCE)
    expected = symbol(e, target, source, node, representation=analyzed_representation(node),
                      target_representation=represented)
    valid = e.emit_value(f'icmp eq ptr {actual}, {expected}')
    e.guard_exception(node, valid, 'TypeError', 'iterator view has a different source layout')
    return 'ptr', iterator_callbacks.load(e, value, runtime.SOURCE)


def control(e, state):
    return e.emit_value(f'call ptr @pyjs.iterator.control(ptr {state})') if e.module.uses_iterator_views else state


def store_send(e, state, kind, value, node):
    """Convert through every view before writing the original frame once.

    Inputs are passed by a rooted stack slot, never staged in a view. Failure
    at any depth leaves the suspended frame unchanged and retryable.
    """
    direct, adapted, done = (e.new_label('send.' + name) for name in ('direct', 'adapted', 'stored'))
    tag = e.emit_value(f'load i64, ptr {state}')
    wrapped = e.emit_value(f'icmp eq i64 {tag}, {runtime.ADAPTER}')
    awaited = e.emit_value(f'icmp eq i64 {tag}, {runtime.AWAIT_ITERATOR}')
    wrapped = e.emit_value(f'or i1 {wrapped}, {awaited}')
    e.emit_line(f'br i1 {wrapped}, label %{adapted}, label %{direct}')
    e.emit_line(f'{direct}:')
    destination = iterator_callbacks.load(e, state, runtime.CALLBACK_VALUE)
    e.emit_line(f'store {kind} {value}, ptr {destination}')
    iterator_ops.store(e, state, runtime.STEP, 'i64', '1')
    e.emit_line(f'br label %{done}')
    e.emit_line(f'{adapted}:')
    slots, frame = calls.value_slots(e, [kind])
    e.emit_line(f'store {kind} {value}, ptr {slots[0]}')
    callback = iterator_callbacks.load(e, state, runtime.CALLBACK_VALUE)
    args = ', '.join(f'{stored} {operand}' for stored, operand in
                     (*e.context_arguments(), ('ptr', state), ('ptr', slots[0])))
    e.emit_value(f'call i64 {callback}({args})')
    e.check_active_exception(node)
    calls.pop_roots(e, frame)
    e.emit_line(f'br label %{done}')
    e.emit_line(f'{done}:')


def operation(e, node):
    state, output = e.load_local('state'), e.load_local('output')
    source = iterator_callbacks.load(e, state, runtime.SOURCE)
    if node.operation == 'iter':
        from .protocols import reiterate
        cursor = reiterate(e, source, node)
        same = e.emit_value(f'icmp eq ptr {cursor}, {source}')
        reuse, replace, done = (e.new_label('view.' + name) for name in ('reuse', 'replace', 'iterated'))
        e.emit_line(f'br i1 {same}, label %{reuse}, label %{replace}')
        e.emit_line(f'{reuse}:')
        e.emit_line(f'store ptr {state}, ptr {output}')
        e.emit_line(f'br label %{done}')
        e.emit_line(f'{replace}:')
        result = wrap(e, node.source, node.target, cursor, node, representation=node.source_representation,
                      target_representation=node.target_representation)
        e.emit_line(f'store ptr {result}, ptr {output}')
        e.emit_line(f'br label %{done}')
        e.emit_line(f'{done}:')
        return 'i64', '1'
    if node.operation == 'send':
        actual, expected = node.target.generic_types['S'], node.source.generic_types['S']
        kind = e.value_type(actual)
        value = e.emit_value(f'load {kind}, ptr {output}')
        e.value_semantics[kind, value] = actual
        # Sends travel from the view's target signature into the source frame.
        # The type alone erases list[int8] to list[int]; boxing must retain the
        # incoming layout witness independently of yielded-item metadata.
        incoming, receiving = node.target_representation, node.source_representation
        e.value_representations[kind, value] = incoming.arguments[1] if incoming else None
        kind, value = e.coerce_value(kind, value, e.value_type(expected), node, semantic=expected,
                                     representation=receiving.arguments[1] if receiving else None)
        store_send(e, source, kind, value, node)
        return 'i64', '0'
    actual, expected = collection_ops.item_type(node.source), collection_ops.item_type(node.target)
    kind = e.value_type(actual)
    slots, frame = calls.value_slots(e, [kind])
    context = iterator_ops.context(e)
    status = e.emit_value(f'call i64 @pyjs.iterator.next.context(ptr {source}, ptr {slots[0]}, ptr {context})')
    ready = e.emit_value(f'icmp eq i64 {status}, 1')
    convert, done = e.new_label('view.item'), e.new_label('view.done')
    e.emit_line(f'br i1 {ready}, label %{convert}, label %{done}')
    e.emit_line(f'{convert}:')
    # Non-value statuses (including completion payloads and injected errors)
    # pass untouched. Conversion runs only after a successful source advance.
    value = e.emit_value(f'load {kind}, ptr {slots[0]}')
    e.value_semantics[kind, value] = actual
    # Generic item types alone cannot distinguish list[int8] from list[int].
    # A view must preserve that layout witness when it boxes a yielded object.
    represented = node.source_representation
    e.value_representations[kind, value] = represented.item_representation if represented is not None else None
    target = node.target_representation
    kind, value = e.coerce_value(kind, value, e.value_type(expected), node, semantic=expected,
                                 representation=target.item_representation if target else None)
    e.emit_line(f'store {kind} {value}, ptr {output}')
    e.emit_line(f'br label %{done}')
    e.emit_line(f'{done}:')
    calls.pop_roots(e, frame)
    return 'i64', status
