"""Comprehension scopes lowered to isolated function IR and ordinary loops."""

import ast

from pyjs.analysis.analyzer import BUILTINS, DependencyError, analyzed_value_type
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.ir import (
    Branch,
    CollectionNew,
    Comprehension,
    FunctionIR,
    IteratorCreate,
    IteratorNext,
    Jump,
    Lambda,
    Return,
    Suspend,
)
from pyjs.analysis.objects import Attribute, Call, CallableClass, Dict, List, Name, Set
from pyjs.analysis.type_relations import same_analyzer_type
from pyjs.analysis.value_representation import (
    analyzed_representation,
    apply_representation,
    compound_representation,
    representations_conflict,
    set_analyzed_representation,
)


def lower(visitor, analyzed, source, *, retain=None, unpack=None):
    lazy = isinstance(analyzed, ast.GeneratorExp)
    bindings = {}
    for generator in analyzed.generators:
        for target in ast.walk(generator.target):
            if isinstance(target, ast.Name):
                layout = analyzed_value_type(target), analyzed_representation(target)
                previous = bindings.get(target.id)
                if previous is not None and (not same_analyzer_type(previous[0], layout[0])
                                             or representations_conflict((previous, layout))):
                    visitor.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                 "native comprehension targets cannot change type or representation",
                                 help="Use distinct loop-variable names for different item types.")
                bindings[target.id] = layout
    ir = FunctionIR()
    ir.reserved_names.update(
        value.id if isinstance(value, ast.Name) else value.arg
        for value in ast.walk(source) if isinstance(value, (ast.Name, ast.arg))
    )
    ir.enter(ir.new_block("entry"))
    scope = analyzed.scope
    # Expansion snapshots and generated loops belong to this body, never the
    # enclosing frame. Share its inferred bindings but not its CFG or temps.
    body_visitor = type(visitor)(visitor.func, scope)
    body_visitor.ir = ir
    body_visitor.assignment_scope = scope
    lowering = body_visitor.lowering
    value_type = analyzed_value_type(analyzed)
    representation = analyzed_representation(analyzed)
    outer = analyzed.generators[0].iter
    source_type = analyzed_value_type(outer)
    source_representation = analyzed_representation(outer)
    if lazy:
        protocol = visitor.require_iterable(source.generators[0].iter, outer)
        source_type = BUILTINS.search("Iterator")(protocol.item_type)
        source_representation = compound_representation(arguments=(protocol.item_representation,))
    parameter = source_type(ir.new_name("__comprehension_source"), scope, visitor.func)
    apply_representation(parameter, source_representation)
    scope.add(parameter)
    value = None
    if not lazy:
        result = value_type(ir.new_name("__comprehension_result"), scope, visitor.func)
        apply_representation(result, representation)
        scope.add(result)
        value = Name(result, ctx=ast.Load())
    if lazy:
        action = analyzed.elt
    elif isinstance(analyzed, ast.DictComp):
        empty = Dict(value_type, keys=[], values=[])
        method, arguments = "__setitem__", [analyzed.key, analyzed.value]
    else:
        empty = (List(value_type, elts=[], ctx=ast.Load()) if isinstance(analyzed, ast.ListComp)
                 else Set(value_type, elts=[]))
        method, arguments = ("append" if isinstance(analyzed, ast.ListComp) else "add"), [analyzed.elt]
    if not lazy:
        if retain is not None:
            retain(empty, value_type)
        set_analyzed_representation(empty, representation)
        ir.emit(ast.AnnAssign(target=Name(result, ctx=ast.Store()), annotation=value_type.annotation,
                             value=CollectionNew(empty), simple=1))
        mutation = value_type.find(method)
        if not mutation.signature_analyzed:
            raise DependencyError(mutation)
        action = Call(BUILTINS.search("NoneType"), func=Attribute(mutation, value=value, attr=method, ctx=ast.Load()),
                      args=arguments, keywords=[])
    ast.copy_location(action, source)

    def loop(index):
        generator = analyzed.generators[index]
        iterable = Name(parameter, ctx=ast.Load()) if index == 0 else generator.iter
        iterator = ir.new_name("iterator")
        ir.emit(IteratorCreate(iterator, lowering.visit(iterable), generator.runtime_methods,
                               acquired=lazy and index == 0))
        check, body, done = (ir.new_block(name) for name in ("for_next", "for_body", "for_done"))
        ir.terminate(Jump(check.name))
        ir.enter(check)
        target, row = generator.target, None
        protocol = body_visitor.require_iterable(iterable, iterable)
        if (isinstance(target, (ast.Tuple, ast.List)) and protocol.item_type.generic_name == "tuple"
                and protocol.item_type.tuple_variadic):
            row = protocol.item_type(ir.new_name("__unpack_row"), scope, visitor.func)
            apply_representation(row, protocol.item_representation)
            scope.add(row)
            target = Name(row, ctx=ast.Store())
        ir.terminate(ast.copy_location(IteratorNext(iterator, target, body.name, done.name), source))
        ir.enter(body)
        if row is not None:
            # Match explicit loops: reject the row length before storing any
            # target or running filters, using ordinary unpacking semantics.
            if unpack is None:
                visitor.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                             "comprehension variadic tuple unpacking is not implemented")
            unpack(body_visitor, generator.target, Name(row, ctx=ast.Load()))
        for condition in generator.ifs:
            passed = ir.new_block("filter_passed")
            test = visitor.truth_test(condition, condition)
            ir.terminate(Branch(lowering.visit(test), passed.name, check.name))
            ir.enter(passed)
        if index + 1 < len(analyzed.generators):
            loop(index + 1)
        elif lazy:
            resume = ir.new_block("resume")
            ir.terminate(ast.copy_location(Suspend(lowering.visit(action), resume.name), source))
            ir.enter(resume)
        else:
            ir.emit(ast.Expr(value=lowering.visit(action)))
        ir.terminate(Jump(check.name))
        ir.enter(done)

    loop(0)
    ir.terminate(Return(value))
    args = ast.arguments(posonlyargs=[], args=[ast.arg(arg=parameter.name)],
                         vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[])
    function = Lambda(args, value, ir, scope)
    function.is_generator = lazy
    # Flow scopes after filters may hold only narrowed bindings. Every loop
    # target is still a local even when its binding lives in an earlier scope.
    function.local_names = {*scope.names, *bindings}
    function.obj = CallableClass((source_type,), value_type, BUILTINS.search("callable"),
                                 (source_representation,), representation)
    ast.copy_location(function, source)
    # The outer source belongs to the enclosing expression's evaluation order.
    # Defer its lowering so a nested yield cannot precede earlier call operands.
    result = Comprehension(outer, function)
    set_analyzed_representation(result, representation)
    return ast.copy_location(result, source)
