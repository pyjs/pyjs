"""Typed declarations for native lazy stream adapters."""

import ast
import itertools
from builtins import object as _Object
from collections.abc import Callable, Iterable, Iterator
from typing import overload

from pyjs.analysis.representation import compound_representation, tuple_representation
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.decorators import ParameterLifetime, configure_js, native_operation


def _argument(result, index, name):
    if index < len(result.args):
        return result.args[index]
    return next(keyword.value for keyword in result.keywords if keyword.arg == name)


def _indexed(result, keyword=None):
    from pyjs.analysis.analyzer import analyzed_value_type
    values = [*result.args[1:], *(kw.value for kw in result.keywords if kw.arg == keyword)]
    result.runtime_protocols = (*getattr(result, "runtime_protocols", ()),
                               *((analyzed_value_type(value), ("__index__",)) for value in values))
    return result


def _rows(call, *, variadic):
    result = call.standard()
    value = _argument(result, 0, "iterable")
    protocol = call.visitor.require_iterable(call.node, value)
    row = (compound_representation(arguments=(protocol.item_representation,)) if variadic
           else tuple_representation((protocol.item_representation,) * 2))
    return call.set_result_representation(result, compound_representation(arguments=(row,)))


@native_operation("itertools.pairwise", iterable=ParameterLifetime.RETURNED)
def pairwise[T](iterable: Iterable[T], /) -> Iterator[tuple[T, T]]:
    return itertools.pairwise(iterable)


configure_js(pairwise, analysis=lambda call: _rows(call, variadic=False))


@native_operation("itertools.batched", iterable=ParameterLifetime.RETURNED)
def batched[T](iterable: Iterable[T], n: object, *, strict: bool = False) -> Iterator[tuple[T, ...]]:
    return itertools.batched(iterable, n, strict=strict)


configure_js(batched, analysis=lambda call: _indexed(_rows(call, variadic=True), "n"))


@overload
def islice[T](iterable: Iterable[T], stop: object, /) -> Iterator[T]: ...


@overload
def islice[T](iterable: Iterable[T], start: object, stop: object,
              step: object = None, /) -> Iterator[T]: ...


@native_operation("itertools.islice", iterable=ParameterLifetime.RETURNED)
def islice(iterable: Iterable[object], *bounds: object) -> Iterator[object]:
    return itertools.islice(iterable, *bounds)


configure_js(islice, analysis=lambda call: _indexed(call.preserving_iterator("islice()", 0)))


@overload
def repeat[T](object: T) -> Iterator[T]: ...


# Keep the keyword-compatible parameter name without shadowing its type.
@overload
def repeat[T](object: T, times: _Object) -> Iterator[T]: ...


@native_operation("itertools.repeat", object=ParameterLifetime.RETURNED)
def repeat(object: _Object, *args: _Object, **kwargs: _Object) -> Iterator[_Object]:
    return itertools.repeat(object, *args, **kwargs)


def _repeat(call):
    result = call.standard()
    value = _argument(result, 0, "object")
    return _indexed(call.set_result_representation(result,
        compound_representation(arguments=(analyzed_representation(value),))), "times")


configure_js(repeat, analysis=_repeat)


@native_operation("itertools.cycle", iterable=ParameterLifetime.RETURNED)
def cycle[T](iterable: Iterable[T], /) -> Iterator[T]:
    return itertools.cycle(iterable)


configure_js(cycle, analysis=lambda call: call.preserving_iterator("cycle()", 0))


@native_operation("itertools.tee", iterable=ParameterLifetime.RETURNED)
def tee[T](iterable: Iterable[T], n: int = 2, /) -> tuple[Iterator[T], ...]:
    return itertools.tee(iterable, n)


def _tee(call):
    from pyjs.analysis.analyzer import BUILTINS
    from pyjs.numeric import integer_literal

    result = call.standard()
    protocol = call.visitor.require_iterable(call.node, result.args[0])
    count = 2 if len(result.args) == 1 else integer_literal(result.args[1], allow_bool=True)
    iterator = BUILTINS.search("Iterator")(protocol.item_type)
    # Literal arities support ordinary tuple unpacking; dynamic arities remain
    # homogeneous tuples and must be indexed or iterated by their consumers.
    # Bound expansion so a large runtime count cannot inflate the type graph.
    fixed = count is not None and 0 <= count <= 256
    members = (iterator,) * count if fixed else (iterator,)
    result = call.with_result_type(BUILTINS.search("tuple")(*members, tuple_variadic=not fixed))
    representation = compound_representation(arguments=(protocol.item_representation,))
    row = tuple_representation((representation,) * count) if fixed else compound_representation(arguments=(representation,))
    return call.set_result_representation(result, row)


configure_js(tee, analysis=_tee)


@overload
def groupby[T](iterable: Iterable[T], key: None = None) -> Iterator[tuple[T, Iterator[T]]]: ...


@overload
def groupby[T, K](iterable: Iterable[T], key: Callable[[T], K]) -> Iterator[tuple[K, Iterator[T]]]: ...


@native_operation("itertools.groupby")
def groupby[T, K](iterable: Iterable[T], key: Callable[[T], K] | None = None) -> Iterator[object]:
    return itertools.groupby(iterable, key)


def _groupby(call):
    from pyjs.analysis.analyzer import (
        BUILTINS,
        analyzed_value_type,
        callable_value_type,
        equality_methods,
    )

    result = call.standard()
    values = dict(zip(("iterable", "key"), result.args, strict=False)) | {k.arg: k.value for k in result.keywords}
    protocol = call.visitor.require_iterable(call.node, values["iterable"])
    key = values.get("key")
    identity = key is None or analyzed_value_type(key).generic_name == "NoneType"
    callback = None if identity else callable_value_type(key)
    key_type = protocol.item_type if identity else callback.return_type
    key_representation = protocol.item_representation if identity else callback.return_representation
    iterator = BUILTINS.search("Iterator")
    row = BUILTINS.search("tuple")(key_type, iterator(protocol.item_type))
    result = call.with_result_type(iterator(row))
    result.runtime_methods = tuple(dict.fromkeys((*result.runtime_methods, *equality_methods(key_type))))
    from .comparisons import retain_erased
    retain_erased(result, key_type)
    return call.set_result_representation(result, compound_representation(arguments=(
        tuple_representation((key_representation, compound_representation(arguments=(protocol.item_representation,)))),)))


configure_js(groupby, analysis=_groupby)


@native_operation("itertools.count")
def count(start: int | float = 0, step: int | float = 1) -> Iterator[object]:
    return itertools.count(start, step)


def _count(call):
    from pyjs.analysis.analyzer import BUILTINS, analyzed_value_type
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.objects import UnionType

    result = call.standard()
    values = dict(zip(("start", "step"), result.args, strict=False)) | {k.arg: k.value for k in result.keywords}
    types = {name: getattr(analyzed_value_type(value), "generic_name", None) for name, value in values.items()}
    start, step = types.get("start", "int"), types.get("step", "int")
    representations = [analyzed_representation(value) for value in values.values()]
    mixed = start in {"bool", "int"} and step == "float"
    if (start not in {"bool", "int", "float"} or step not in {"bool", "int", "float"}
            or mixed and any(value is not None for value in representations)
            or any(value is not None and (value.numeric is None or value.numeric.kind != "integer")
                   for value in representations)):
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native count requires ordinary int/float operands for mixed counting or supported integral operands")
    # CPython's unit-step fast path erases integer subclasses. Otherwise a
    # portable operand can change the representation, and a bool start can
    # yield bool then int. Neither fits the ordinary integral counting path.
    unit_step = "step" not in values or isinstance(values["step"], ast.Constant) and values["step"].value == 1
    if not mixed and start != "float" and not unit_step and (
            start == "bool" or any(value is not None for value in representations)):
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native count with bool or portable integer operands requires an omitted step or literal 1/True; "
                          "convert operands to int explicitly for ordinary integer counting")
    member = (UnionType(types=(BUILTINS.search(start), BUILTINS.search("float"))).type if mixed
              else BUILTINS.search("float" if start == "float" else "int"))
    result = call.with_result_type(BUILTINS.search("Iterator")(member))
    return call.set_result_representation(result, None)


configure_js(count, analysis=_count)


@native_operation("itertools.zip_longest", iterables=ParameterLifetime.RETURNED,
                  fillvalue=ParameterLifetime.RETURNED)
def zip_longest(*iterables: Iterable[object], fillvalue: object = None) -> Iterator[tuple[object, ...]]:
    return itertools.zip_longest(*iterables, fillvalue=fillvalue)


def _zip_longest(call):
    from pyjs.analysis.analyzer import BUILTINS, analyzed_value_type
    from pyjs.analysis.objects import UnionType

    result = call.standard()
    protocols = [call.visitor.require_iterable(call.node, value) for value in result.args]
    fill = next((value.value for value in result.keywords if value.arg == "fillvalue"), None)
    fill_type = analyzed_value_type(fill) if fill is not None else BUILTINS.search("NoneType")
    fill_representation = analyzed_representation(fill) if fill is not None else None
    members, representations = [], []
    iterator = BUILTINS.search("Iterator")
    for value, protocol in zip(result.args, protocols, strict=True):
        source = analyzed_value_type(value)
        empty = (isinstance(value, ast.List) and not value.elts
                 or getattr(source, "generic_name", None) == "tuple" and not source.generic_types)
        if isinstance(value, ast.List) and not value.elts:
            call.visitor.normalize_stored_iterable(value, value, fill_representation, fill_type)
        choices = [(fill_type, fill_representation)]
        if not empty:
            choices.insert(0, (protocol.item_type, protocol.item_representation))
            # Source cursors may be implicit (notably tuples). Build both
            # sides of each column's view while analysis can retry dependencies.
            iterator(protocol.item_type)
        member = UnionType(types=(value_type for value_type, _ in choices)).type
        representations.append(call.visitor.merge_typed_representations(
            value, member, choices, "zip_longest item and fill value"))
        members.append(member)
        iterator(member)
    row = BUILTINS.search("tuple")(*members)
    result = call.with_result_type(BUILTINS.search("Iterator")(row))
    return call.set_result_representation(result, compound_representation(arguments=(
        tuple_representation(tuple(representations)),)))


configure_js(zip_longest, analysis=_zip_longest)


@native_operation("itertools.accumulate")
def accumulate[T](iterable: Iterable[T], func: Callable[[T, T], T] | None = None,
                  *, initial: T | None = None) -> Iterator[T]:
    return itertools.accumulate(iterable, func, initial=initial)


def _default_accumulate_callback(call, protocol, previous):
    from dataclasses import replace

    from pyjs.analysis.analyzer import analyzed_value_object
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.analysis.objects import EvaluateOnce

    left, right = "$accumulate_left", "$accumulate_right"
    source = ast.fix_missing_locations(ast.copy_location(ast.Lambda(
        args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=left), ast.arg(arg=right)],
                           vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
        body=ast.BinOp(left=ast.Name(id=left, ctx=ast.Load()), op=ast.Add(),
                      right=ast.Name(id=right, ctx=ast.Load())),
    ), call.node))
    try:
        callback = call.visitor.visit_contextual_lambda(
            source, (protocol.item_type,) * 2, (protocol.item_representation,) * 2,
        )
    except CompilationError as error:
        # Keep the original cause and source location (possibly inside an
        # authored __add__), but explain how to replace the generated operands.
        raise CompilationError(replace(
            error.diagnostic,
            notes=(*error.diagnostic.notes, "While analyzing default accumulate addition (left + right)."),
            help=(*error.diagnostic.help,
                  "Pass an explicit typed func accepting and returning the item type; "
                  "narrow operands inside that function if needed."),
        )) from error
    if previous is not None:
        # An explicitly supplied None can be an effectful call, not only a
        # literal. Run it in its original argument position before constructing
        # the default callback, and retain normal exception ordering.
        callback = call.set_result_representation(EvaluateOnce(
            analyzed_value_object(callback), previous, callback, "$accumulate_default",
            lineno=call.node.lineno,
        ), analyzed_representation(callback))
    return callback


def _accumulate(call):
    from pyjs.analysis.analyzer import BUILTINS, analyzed_value_type, callable_value_type
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.objects import CallableClass, same_analyzer_type

    result = call.standard()
    values = dict(zip(("iterable", "func"), result.args, strict=False)) | {k.arg: k.value for k in result.keywords}
    protocol = call.visitor.require_iterable(call.node, values["iterable"])
    initial = values.get("initial")
    if (initial is not None and getattr(analyzed_value_type(initial), "generic_name", None) != "NoneType"
            and (not same_analyzer_type(analyzed_value_type(initial), protocol.item_type)
                 or analyzed_representation(initial) != protocol.item_representation)):
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native accumulate initial must match the item type and representation")
    func = values.get("func")
    if func is None or getattr(analyzed_value_type(func), "generic_name", None) == "NoneType":
        # Application namesakes must use their authored addition, not the
        # unboxed primitive runtime selected for canonical builtin classes.
        if not any(protocol.item_type is BUILTINS.search(name) for name in ("int", "float", "str", "bytes")):
            func = _default_accumulate_callback(call, protocol, func)
            if len(result.args) > 1:
                result.args[1] = func
            elif option := next((keyword for keyword in result.keywords if keyword.arg == "func"), None):
                option.value = func
            else:
                result.keywords.append(ast.keyword(arg="func", value=func))
    if func is not None and getattr(analyzed_value_type(func), "generic_name", None) != "NoneType":
        callback = callable_value_type(func)
        if (not isinstance(callback, CallableClass) or callback.parameter_types is None
                or not callback.accepts_arity(2)
                or any(not same_analyzer_type(value, protocol.item_type)
                       for value in (*callback.parameter_types[:2], callback.return_type))
                or (callback.parameter_representations or (None, None))[:2] != (protocol.item_representation,) * 2
                or callback.return_representation != protocol.item_representation):
            call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "native accumulate requires a matching two-argument callback and result representation",
                              help="Both default addition and an explicit func must accept and return the iterable's "
                              "item type and representation. Supply a matching typed func or convert the input items.")
    result = call.with_result_type(BUILTINS.search("Iterator")(protocol.item_type))
    return call.set_result_representation(result, compound_representation(arguments=(protocol.item_representation,)))


configure_js(accumulate, analysis=_accumulate)


@native_operation("itertools.filterfalse")
def filterfalse[T](predicate: Callable[[T], bool] | None, iterable: Iterable[T], /) -> Iterator[T]:
    return itertools.filterfalse(predicate, iterable)


@native_operation("itertools.takewhile")
def takewhile[T](predicate: Callable[[T], bool], iterable: Iterable[T], /) -> Iterator[T]:
    return itertools.takewhile(predicate, iterable)


@native_operation("itertools.dropwhile")
def dropwhile[T](predicate: Callable[[T], bool], iterable: Iterable[T], /) -> Iterator[T]:
    return itertools.dropwhile(predicate, iterable)


for _predicate in (filterfalse, takewhile, dropwhile):
    configure_js(_predicate, analysis=lambda call: call.preserving_iterator("predicate iterator", 1),
                 runtime_dunders=(1, ("__bool__", "__len__")))


@native_operation("itertools.compress")
def compress[T, S](data: Iterable[T], selectors: Iterable[S]) -> Iterator[T]:
    return itertools.compress(data, selectors)


def _compress(call):
    from pyjs.analysis.analyzer import truthiness_methods

    result = call.standard()
    value = _argument(result, 0, "data")
    protocol = call.visitor.require_iterable(call.node, value)
    selectors = _argument(result, 1, "selectors")
    selected = call.visitor.require_iterable(call.node, selectors)
    result.runtime_methods = tuple(dict.fromkeys((*result.runtime_methods, *truthiness_methods(selected.item_type))))
    result.runtime_protocols = (*result.runtime_protocols, (selected.item_type, ("__bool__", "__len__")))
    return call.set_result_representation(result, compound_representation(arguments=(protocol.item_representation,)))


configure_js(compress, analysis=_compress)


@native_operation("itertools.chain", iterables=ParameterLifetime.RETURNED)
def chain[T](*iterables: Iterable[T]) -> Iterator[T]:
    return itertools.chain(*iterables)


def _chain(call):
    from pyjs.analysis.analyzer import BUILTINS, analyzed_value_type
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.objects import Class

    if not call.node.args:
        call.visitor.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native chain requires at least one typed iterable")
    result = call.standard()
    representations = []
    for value in result.args:
        value_type = analyzed_value_type(value)
        if isinstance(value_type, Class) and value_type.generic_name == "tuple" and not value_type.generic_types:
            continue
        protocol = call.visitor.require_iterable(call.node, value)
        representations.append(protocol.item_representation)
        if isinstance(value_type, Class):
            # Tuples need not analyze __iter__, so their source cursor type
            # may not exist yet. Request it while dependency retries are legal;
            # lowering reserves the same type for the per-source view ABI.
            BUILTINS.search("Iterator")(protocol.item_type)
    representation = representations[0] if representations else None
    if any(value != representation for value in representations):
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native chain requires matching item representations")
    return call.set_result_representation(result, compound_representation(arguments=(representation,)))


configure_js(chain, analysis=_chain)


@native_operation("itertools.chain.from_iterable", iterable=ParameterLifetime.RETURNED)
def chain_from_iterable(iterable: Iterable[object], /) -> Iterator[object]:
    return itertools.chain.from_iterable(iterable)


def _chain_iterable(call):
    from pyjs.analysis.analyzer import BUILTINS
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.iterable_protocol import resolve_iterable_protocol

    result = call.standard()
    protocol = call.visitor.require_iterable(call.node, result.args[0])
    inner = resolve_iterable_protocol(protocol.item_type, protocol.item_representation, BUILTINS)
    if inner is None:
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native chain.from_iterable requires a concrete inner iterable type")
    result = call.with_result_type(BUILTINS.search("Iterator")(inner.item_type))
    result.runtime_methods = tuple(dict.fromkeys((*result.runtime_methods, *inner.methods)))
    return call.set_result_representation(result, compound_representation(arguments=(inner.item_representation,)))


configure_js(chain_from_iterable, analysis=_chain_iterable)
chain.from_iterable = chain_from_iterable


@native_operation("itertools.combinations", iterable=ParameterLifetime.RETURNED)
def combinations[T](iterable: Iterable[T], r: int) -> Iterator[tuple[T, ...]]:
    return itertools.combinations(iterable, r)


@native_operation("itertools.combinations_with_replacement", iterable=ParameterLifetime.RETURNED)
def combinations_with_replacement[T](iterable: Iterable[T], r: int) -> Iterator[tuple[T, ...]]:
    return itertools.combinations_with_replacement(iterable, r)


@native_operation("itertools.permutations", iterable=ParameterLifetime.RETURNED)
def permutations[T](iterable: Iterable[T], r: int | None = None) -> Iterator[tuple[T, ...]]:
    return itertools.permutations(iterable, r)


def _pool_result(call, members, representations, *, fixed):
    from pyjs.analysis.analyzer import BUILTINS

    row = BUILTINS.search("tuple")(*members, tuple_variadic=not fixed)
    result = call.with_result_type(BUILTINS.search("Iterator")(row))
    representation = (tuple_representation(representations) if fixed
                      else compound_representation(arguments=representations))
    return call.set_result_representation(result, compound_representation(arguments=(representation,)))


def _pool_protocol(call, value):
    from pyjs.analysis.analyzer import BUILTINS

    if isinstance(value, ast.List) and not value.elts:
        # A fresh empty pool has no observable item, but still needs an
        # allocation type. This never changes a named collection's storage.
        call.visitor.normalize_stored_iterable(value, value, None, BUILTINS.search("object"))
    return call.visitor.require_iterable(call.node, value)


def _combinations(call):
    result = call.standard()
    protocol = _pool_protocol(call, _argument(result, 0, "iterable"))
    # Homogeneous rows retain one type across literal/dynamic widths, branches
    # and reassignments. Destructuring checks their length at runtime.
    return _pool_result(call, (protocol.item_type,), (protocol.item_representation,), fixed=False)


for _pooled in (combinations, combinations_with_replacement, permutations):
    configure_js(_pooled, analysis=_combinations)


@native_operation("itertools.product", iterables=ParameterLifetime.RETURNED)
def product(*iterables: Iterable[object], repeat: int = 1) -> Iterator[tuple[object, ...]]:
    return itertools.product(*iterables, repeat=repeat)


def _product(call):
    from pyjs.analysis.analyzer import BUILTINS, analyzed_value_type
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.numeric import integer_literal

    result = call.standard()
    protocols = [_pool_protocol(call, value) for value in result.args]
    # Fresh empty literals have no item type and should not constrain other pools.
    known = [protocol for value, protocol in zip(result.args, protocols, strict=True)
             if not (isinstance(value, ast.List) and not value.elts
                     or analyzed_value_type(value).generic_name == "tuple"
                     and not analyzed_value_type(value).generic_types)]
    member = known[0].item_type if known else BUILTINS.search("object")
    representation = known[0].item_representation if known else None
    mixed = any(value.item_type is not member or value.item_representation != representation for value in known)
    if mixed:
        repeat = next((keyword.value for keyword in result.keywords if keyword.arg == "repeat"), None)
        count = integer_literal(repeat, allow_bool=True) if repeat is not None else 1
        if count is not None and 0 <= count * len(protocols) <= 256:
            # Only heterogeneous columns need fixed positions. In particular
            # int8/int16 must not merge into one ordinary integer item domain.
            return _pool_result(call, tuple(p.item_type for p in protocols) * count,
                                tuple(p.item_representation for p in protocols) * count, fixed=True)
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native product with dynamic or large repeat requires matching pool item types and representations",
                          help="Use a nonnegative literal repeat with at most 256 output positions for heterogeneous rows.")
    for value in result.args:
        if isinstance(value, ast.List) and not value.elts:
            call.visitor.normalize_stored_iterable(value, value, representation, member)
    return _pool_result(call, (member,), (representation,), fixed=False)


configure_js(product, analysis=_product)


@native_operation("itertools.starmap")
def starmap[R](function: Callable[..., R], iterable: Iterable[object], /) -> Iterator[R]:
    return itertools.starmap(function, iterable)


def _row_parameters(visitor, node, protocol, arity):
    from pyjs.analysis.diagnostics import DiagnosticCode

    row = protocol.item_type
    if getattr(row, "generic_name", None) != "tuple":
        visitor.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                     "native starmap requires typed tuple rows")
    items = tuple(row.generic_types.values())
    representations = protocol.item_representation.arguments if protocol.item_representation else (None,) * len(items)
    if row.tuple_variadic:
        items *= arity
        representations *= arity
    if len(items) != arity:
        visitor.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                     "native starmap row does not match callback arity; defaults are not supplied")
    return items, representations


def starmap_arguments(visitor, node, signature):
    from pyjs.analysis.analyzer import infer_type_variables

    # Unlike map, a starmap lambda gets its parameters from inside each row.
    # Analyze the iterable first but retain the original runtime operand order.
    source = visitor.visit(node.args[1])
    protocol = visitor.require_iterable(node, source)
    callback = node.args[0]
    arity = len(callback.args.posonlyargs) + len(callback.args.args)
    parameters, representations = _row_parameters(visitor, node, protocol, arity)
    callback = visitor.visit_contextual_lambda(callback, parameters, representations)
    ast.copy_location(callback, node.args[0])
    callback.python_node = node.args[0]
    arguments = [callback, source]
    types, formats = {}, {}
    infer_type_variables(visitor.call_argument_pattern(signature, 0), callback.obj, types)
    visitor.infer_call_representation_bindings(node, signature, arguments, [], formats)
    return arguments, [], types, formats


def _starmap(call):
    from pyjs.analysis.analyzer import callable_value_type, is_return_type_compatible
    from pyjs.analysis.diagnostics import DiagnosticCode
    from pyjs.analysis.objects import CallableClass

    result = call.mapped(max_iterables=1)
    callback = callable_value_type(result.args[0])
    protocol = call.visitor.require_iterable(call.node, result.args[1])
    if not isinstance(callback, CallableClass) or callback.parameter_types is None:
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native starmap requires a concrete callback signature")
    items, representations = _row_parameters(call.visitor, call.node, protocol, len(callback.parameter_types))
    expected = callback.parameter_representations or (None,) * len(items)
    # The checked callback ABI adapts each item, as for an ordinary call;
    # a callback accepting object can consume integer rows. Representation
    # changes still need explicit conversion, not implicit scalar erasure.
    if (any(not is_return_type_compatible(parameter, actual)
            for actual, parameter in zip(items, callback.parameter_types, strict=True))
            or representations != expected):
        call.visitor.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "native starmap requires matching callback argument types and representations")
    return result


configure_js(starmap, analysis=_starmap)
