"""Unpack one sequence level before evaluating its assignment targets."""

import ast

from pyjs.analysis.analyzer import BUILTINS, analyzed_value_type, get_type_members
from pyjs.analysis.diagnostics import DiagnosticCode


def assign(visitor, target, value):
    """Emit ordinary typed operations; nested levels keep Python's store order."""
    if not isinstance(target, (ast.Tuple, ast.List)):
        source = value if isinstance(value, ast.List) else ast.Name(id=value.id, ctx=ast.Load())
        statement = ast.Assign(targets=[target], value=source)
        analyzed = visitor.visit(ast.fix_missing_locations(ast.copy_location(statement, target)))
        return analyzed if isinstance(analyzed, list) else [analyzed]
    empty = isinstance(value, ast.List) and not value.elts
    if isinstance(value, ast.List):
        value = visitor.lowering.visit(visitor.visit(ast.fix_missing_locations(ast.copy_location(value, target))))

    def visit(node):
        return visitor.visit(ast.fix_missing_locations(ast.copy_location(node, target)))

    def load():
        return ast.Name(id=value.id, ctx=ast.Load())

    def saved(node, context=None):
        node = ast.fix_missing_locations(ast.copy_location(node, target))
        analyzed = visitor.visit_contextual_expression(node, context)
        return visitor.lowering.save(visitor.lowering.visit(analyzed))

    # Internal aliases cannot collide with application bindings such as len or
    # ValueError. The normal analyzer still owns calls, types and reachability.
    for name in ("len", "ValueError", "TypeError"):
        visitor.scope.add(BUILTINS.search(name), name="$unpack_" + name)

    def error(name, message):
        return ast.Raise(exc=ast.Call(func=ast.Name(id="$unpack_" + name, ctx=ast.Load()),
                                     args=[message], keywords=[]), cause=None)

    value_type = analyzed_value_type(value)
    members = get_type_members(value_type)
    none = BUILTINS.search("NoneType")
    if none in members:
        others = [member for member in members if member is not none]
        if len(others) == 1:
            visit(ast.If(test=ast.Compare(left=load(), ops=[ast.Is()], comparators=[ast.Constant(value=None)]),
                         body=[error("TypeError", ast.Constant(value="cannot unpack non-iterable NoneType object"))],
                         orelse=[]))
            # Keep the proof on an internal copy, not a child visitor whose
            # assignment declarations would disappear from the enclosing scope.
            value = visitor.lowering.save(visitor.narrow(load(), others[0]).visit(load()))
            value_type = others[0]
    if getattr(value_type, "generic_name", None) not in {"list", "tuple"}:
        visitor.fail(target, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native unpacking requires a statically typed tuple or list")

    stars = [index for index, item in enumerate(target.elts) if isinstance(item, ast.Starred)]
    if len(stars) > 1:
        visitor.fail(target, DiagnosticCode.UNSUPPORTED_SYNTAX, "multiple starred expressions in assignment")
    star = stars[0] if stars else None
    required = len(target.elts) - bool(stars)
    fixed = value_type.generic_name == "tuple" and not value_type.tuple_variadic
    count = 0 if empty else len(value_type.generic_types) if fixed else None
    if fixed and (count < required or star is None and count != required):
        visitor.fail(target, DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                     f"cannot unpack {count} values into {len(target.elts)} targets")

    length = saved(ast.Call(func=ast.Name(id="$unpack_len", ctx=ast.Load()), args=[load()], keywords=[]))

    def arity_error(operator, prefix):
        message = ast.JoinedStr(values=[ast.Constant(value=prefix),
                                       ast.FormattedValue(value=ast.Name(id=length.id, ctx=ast.Load()), conversion=-1),
                                       ast.Constant(value=")")])
        visit(ast.If(test=ast.Compare(left=ast.Name(id=length.id, ctx=ast.Load()), ops=[operator],
                                     comparators=[ast.Constant(value=required)]),
                     body=[error("ValueError", message)], orelse=[]))

    arity_error(ast.Lt(), f"not enough values to unpack (expected {'at least ' if stars else ''}{required}, got ")
    if star is None:
        arity_error(ast.Gt(), f"too many values to unpack (expected {required}, got ")

    def subscript(index):
        return ast.Subscript(value=load(), slice=index, ctx=ast.Load())

    items = []
    for index, item in enumerate(target.elts):
        if index == star:
            after = len(target.elts) - index - 1
            if fixed or empty:
                # Each fixed field keeps its type until the rest list itself
                # requires one common item representation. A nested unpack of
                # a known-empty rest also creates a fresh contextual literal,
                # not a slice whose list[object] type would escape to the target.
                source = ast.List(elts=[subscript(ast.Constant(value=offset))
                                       for offset in range(index, count - after)], ctx=ast.Load())
                if not source.elts:
                    # Reserve the allocation before all target stores, but let
                    # ordinary assignment analysis supply the destination type.
                    # Resolving a target here could run callbacks/yields early.
                    source.native_unpack_allocation = ast.AnnAssign(
                        target=None, annotation=None, value=None, simple=True)
                    visitor.ir.emit(source.native_unpack_allocation)
                    items.append((item.value, source))
                    continue
                context = None
            else:
                end = ast.BinOp(left=ast.Name(id=length.id, ctx=ast.Load()), op=ast.Sub(), right=ast.Constant(value=after))
                source = subscript(ast.Slice(lower=ast.Constant(value=index), upper=end, step=None))
                if value_type.generic_name == "tuple":
                    visitor.scope.add(BUILTINS.search("list"), name="$unpack_list")
                    source = ast.Call(func=ast.Name(id="$unpack_list", ctx=ast.Load()), args=[source], keywords=[])
                context = None
            items.append((item.value, saved(source, context)))
        else:
            offset = index
            if star is not None and index > star:
                after = len(target.elts) - index
                offset = count - after if fixed else -after
            items.append((item, saved(subscript(ast.Constant(value=offset)))))
    # Snapshot this level before the first target can mutate the source. A
    # nested target unpacks its retained child only when that target is reached.
    statements = []
    for item, source in items:
        statements.extend(assign(visitor, item, source))
    return statements


def analyze(visitor, target, assignment_value):
    source = visitor.lowering.save(visitor.lowering.visit(assignment_value.node))
    result = ast.copy_location(ast.Pass(), target)
    # IR was emitted in store order above. Keep the analyzed writes visible
    # to branch/loop flow proofs without emitting or executing them twice.
    result.flow_statements = assign(visitor, target, source)
    return result
