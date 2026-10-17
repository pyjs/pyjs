"""Ordered expression expansion and suspension through ordinary typed IR."""

import ast

from pyjs.analysis.analyzer import BUILTINS, analyzed_value_object, analyzed_value_type
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.ir import (
    BlockArgument,
    Branch,
    CollectionNew,
    Comprehension,
    GeneratorInput,
    IRLoweringTransformer,
    Jump,
    Suspend,
)
from pyjs.analysis.objects import (
    Call,
    Class,
    Constant,
    Dict,
    EvaluateOnce,
    Function,
    JoinedStr,
    List,
    Module,
    ModuleAlias,
    Name,
    Set,
    same_analyzer_type,
)
from pyjs.analysis.value_representation import (
    analyzed_representation,
    compound_representation,
    set_analyzed_representation,
)

# CPython 3.14 evaluates small groups before hashing, but inserts large
# literals incrementally. Dictionary groups of 16+ insert one pair at a time;
# full chunks end at 17 pairs. These callback boundaries are observable at yield.
COLLECTION_STACK_ITEMS = 30
DICTIONARY_STACK_ITEMS = COLLECTION_STACK_ITEMS // 2


def set_literal_prefix(elements):
    if len(elements) > COLLECTION_STACK_ITEMS:
        return 0
    return next((index for index, value in enumerate(elements) if isinstance(value, ast.Starred)), len(elements))


def dictionary_literal_groups(node):
    pending = []
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:
            if pending:
                yield pending
                pending = []
            yield [(key, value)]
        else:
            pending.append((key, value))
            if len(pending) == DICTIONARY_STACK_ITEMS + 2:
                yield pending
                pending = []
    if pending:
        yield pending


class NativeExpressionLowering(IRLoweringTransformer):
    def __init__(self, visitor):
        self.visitor = visitor
        self.bindings = {}

    def has_suspension(self, node):
        return self.has_effect(node, expansions=False)

    def has_control_flow(self, node):
        return self.has_effect(node, expansions=True)

    @staticmethod
    def expanded_method(node):
        target = getattr(getattr(node, "func", None), "obj", None)
        return (isinstance(node, ast.Call) and isinstance(target, Function)
                and target.cls is not None and not getattr(target.cls.py_obj, "__builtin__", False)
                and (any(isinstance(item, ast.Starred) for item in node.args)
                     or any(item.arg is None for item in node.keywords)))

    def has_effect(self, node, *, expansions):
        # Expansions emit statements even without a yield. Enclosing operands
        # must be saved, and branches must remain lazy, before lowering them.
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        if isinstance(node, Comprehension):
            return self.has_effect(node.source, expansions=expansions)
        if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            return self.has_effect(node.generators[0].iter, expansions=expansions)
        attribute = "native_expression_control" if expansions else "native_expression_suspends"
        cached = getattr(node, attribute, None)
        if cached is None:
            # Conditionals and lexical lets emit statements even without yield
            # or unpacking. Parents must save preceding operands before them.
            expanded = expansions and (
                isinstance(node, (ast.IfExp, EvaluateOnce))
                or isinstance(node, ast.Call) and getattr(node.func, "class_lookup", False)
                or self.expanded_method(node)
                or isinstance(node, (ast.List, ast.Tuple)) and any(isinstance(item, ast.Starred) for item in node.elts)
                or isinstance(node, ast.Set) and set_literal_prefix(node.elts) < len(node.elts)
                or isinstance(node, ast.Dict) and (
                    len(node.keys) > DICTIONARY_STACK_ITEMS or any(key is None for key in node.keys)))
            cached = isinstance(node, (ast.Yield, ast.YieldFrom)) or expanded or any(
                self.has_effect(child, expansions=expansions) for child in ast.iter_child_nodes(node))
            setattr(node, attribute, cached)
        return cached

    def visit(self, node):
        if getattr(node, "native_expression_lowered", False):
            return node
        result = super().visit(node)
        if isinstance(result, ast.AST):
            result.native_expression_lowered = True
        return result

    def save(self, value):
        # Imported namespaces are static lookup anchors, not runtime operands.
        # A later conditional/expansion must not spill `math` or `json` to a
        # local slot. Instance receivers still need their ordinary saved value.
        if isinstance(value, (ast.Name, ast.Attribute)) and isinstance(
                analyzed_value_object(value), (Module, ModuleAlias)):
            return value
        if (isinstance(value, ast.Attribute) and isinstance(analyzed_value_object(value), Class)
                and isinstance(value.value, (ast.Name, ast.Attribute))
                and isinstance(analyzed_value_object(value.value), (Module, ModuleAlias, Class))):
            # A qualified class is another static anchor. Do not generalize
            # this to functions: an instance's method still captures a receiver.
            return value
        if isinstance(value, ast.Constant) or (
                isinstance(value, ast.Name) and isinstance(analyzed_value_object(value), (Class, Function))):
            return value
        formatted = isinstance(value, ast.FormattedValue)
        if formatted:
            value = ast.copy_location(JoinedStr(BUILTINS.search("str"), values=[value]), value)
        if isinstance(value, CollectionNew):
            set_analyzed_representation(value, analyzed_representation(value.source))
        assignment, loaded = self.visitor.capture_assignment_value(value)
        self.visitor.ir.emit(assignment)
        loaded.native_expression_lowered = True
        if formatted:
            return ast.copy_location(ast.FormattedValue(value=loaded, conversion=-1, format_spec=None), value)
        return loaded

    def ordered(self, values, *, defer_star=False, trailing_control=False):
        # Only operands preceding emitted statements need storage. Reloading an
        # earlier name afterward is wrong when a callback/caller mutates it.
        last = max((index for index, value in enumerate(values) if self.has_control_flow(value)), default=-1)
        if trailing_control:
            last = len(values)
        result = []
        for index, value in enumerate(values):
            if isinstance(value, ast.Starred):
                source = self.visit(value.value)
                # An empty literal contributes no items and can remain
                # untyped. Saving it would require an invented allocation type.
                empty = (isinstance(source, CollectionNew) and isinstance(source.source, (ast.List, ast.Tuple))
                         and not source.source.elts)
                if index < last and not empty:
                    source = self.save(source if defer_star else self.materialize(source))
                value.value = source
                value.native_expression_lowered = True
            else:
                value = self.visit(value)
                if index < last:
                    value = self.save(value)
            result.append(value)
        return result

    def materialize(self, source):
        value_type = analyzed_value_type(source)
        if getattr(value_type, "generic_name", None) == "tuple" and not value_type.tuple_variadic:
            return source  # Immutable fields keep their heterogeneous representations.
        protocol = self.visitor.require_iterable(source, source)
        value_type = BUILTINS.search("list")(protocol.item_type)
        call = ast.copy_location(Call(
            value_type, func=Name(value_type, ctx=ast.Load()), args=[source], keywords=[],
            runtime_methods=protocol.methods,
        ), source)
        set_analyzed_representation(call, compound_representation(arguments=(protocol.item_representation,)))
        return call

    def visit_Name(self, node):
        value = self.bindings.get(node.id)
        if value is None:
            return node
        if same_analyzer_type(analyzed_value_type(value), analyzed_value_type(node)):
            return value
        # A lexical let owns storage, not every use's flow type. Preserve a
        # branch's narrowing while redirecting its read to the captured slot.
        result = ast.copy_location(Name(node.obj, id=value.id, ctx=ast.Load()), node)
        set_analyzed_representation(result, analyzed_representation(node))
        return result

    def visit_ListComp(self, node):
        from .comprehensions import lower
        # Field/setter destination types arrive after RHS analysis. Lower only
        # at its evaluation point, once fresh-list allocation typing is final.
        return self.visit_Comprehension(lower(self.visitor, node, node))

    def visit_GeneratorExp(self, node):
        from .comprehensions import lower
        # A consuming list() may contextualize fresh yielded containers after
        # RHS analysis. Capture the outer iterator at the evaluation point.
        return self.visit_Comprehension(lower(self.visitor, node, node))

    def visit_Yield(self, node):
        value = self.visit(node.value)
        ir = self.visitor.ir
        resume = ir.new_block("resume")
        ir.terminate(ast.copy_location(Suspend(value, resume.name), node))
        ir.enter(resume)
        return self.save(GeneratorInput(node))

    def visit_YieldFrom(self, node):
        from .delegation import lower_statement
        source = self.save(self.visit(node.value))
        statement = ast.copy_location(ast.Expr(value=ast.YieldFrom(
            value=source if isinstance(source, ast.Constant) else ast.Name(id=source.id, ctx=ast.Load()),
        )), node)
        return lower_statement(self.visitor, ast.fix_missing_locations(statement),
                               capture=(analyzed_value_type(node), analyzed_representation(node)))

    def visit_Assign(self, node):
        if any(self.has_control_flow(target) for target in node.targets):
            node.value = self.save(self.visit(node.value))
        return super().visit_Assign(node)

    def visit_AnnAssign(self, node):
        if node.value is not None and self.has_control_flow(node.target):
            node.value = self.save(self.visit(node.value))
        return super().visit_AnnAssign(node)

    def visit_Call(self, node):
        if not self.has_control_flow(node):
            return super().visit_Call(node)
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else node.func
        # A lone *source is consumed after keyword merging; mixed positional
        # operands consume each expansion before evaluating the next operand.
        defer_star = len(node.args) == 1 and isinstance(node.args[0], ast.Starred)
        if any(keyword.arg is None for keyword in node.keywords):
            receiver, *node.args = self.ordered([receiver, *node.args], defer_star=defer_star, trailing_control=True)
            node.keywords = self.keyword_snapshots(node)
            if isinstance(node.func, ast.Attribute):
                node.func.value = receiver
            else:
                node.func = receiver
            return super().visit_Call(node)
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        if isinstance(getattr(node, "operator", None), (ast.In, ast.NotIn)) or getattr(node, "reverse", False):
            argument, receiver = self.ordered([arguments[0], receiver])
            arguments = [argument]
        else:
            # Implicit lookup may reject a disabled runtime protocol. Python
            # evaluates the operands first, including those with no nested
            # control flow; save them before emission selects the class method.
            receiver, *arguments = self.ordered([receiver, *arguments], defer_star=defer_star,
                trailing_control=getattr(node.func, "class_lookup", False) or self.expanded_method(node))
        if isinstance(node.func, ast.Attribute):
            node.func.value = receiver
        else:
            node.func = receiver
        node.args = arguments[:len(node.args)]
        for keyword, value in zip(node.keywords, arguments[len(node.args):], strict=True):
            keyword.value = value
        return super().visit_Call(node)

    @staticmethod
    def source_name(value):
        return ast.Name(id=value.id, ctx=ast.Load()) if isinstance(value, ast.Name) else value

    def generated_statement(self, statement, source):
        self.visitor.visit(ast.fix_missing_locations(ast.copy_location(statement, source)))

    def mutate(self, pack, method, values, source):
        call = ast.Call(
            func=ast.Attribute(value=self.source_name(pack), attr=method, ctx=ast.Load()),
            args=[self.source_name(value) for value in values], keywords=[],
        )
        # The literal allocation summarizes all its key callbacks once. These
        # generated insertions must not also escape the whole temporary mapping
        # (including values) as an independently authored mutation would.
        call.runtime_callback_operands = ()
        self.generated_statement(ast.Expr(value=call), source)

    def extend(self, pack, value, method):
        saved = self.save(self.visit(value))
        self.mutate(pack, method, [saved], value)
        return saved

    def keyword_snapshots(self, node):
        # Keep packs separate: merging them into one dict would erase distinct
        # parameter types/portable widths. Snapshots prevent later mutations from
        # changing already evaluated **values. A string set handles early errors;
        # the ordinary call binder still owns defaults and parameter matching.
        seen_type = BUILTINS.search("set")(BUILTINS.search("str"))
        seen = self.save(ast.copy_location(CollectionNew(Set(seen_type, elts=[])), node))
        error_name = "$keyword_error"
        self.visitor.scope.add(BUILTINS.search("TypeError"), name=error_name)

        def check(key):
            return [
                ast.If(test=ast.Compare(left=key, ops=[ast.In()], comparators=[self.source_name(seen)]),
                       body=[ast.Raise(exc=ast.Call(func=ast.Name(id=error_name, ctx=ast.Load()),
                                                  args=[ast.Constant(value="multiple values for keyword argument")],
                                                  keywords=[]), cause=None)], orelse=[]),
                ast.Expr(value=ast.Call(func=ast.Attribute(value=self.source_name(seen), attr="add", ctx=ast.Load()),
                                       args=[key], keywords=[])),
            ]

        result, pending = [], []

        def flush():
            # A consecutive named group evaluates every value before its first
            # duplicate check, including values following the duplicated name.
            for keyword in pending:
                for statement in check(ast.Constant(value=keyword.arg)):
                    self.generated_statement(statement, keyword.value)
            pending.clear()

        for keyword in node.keywords:
            if keyword.arg is not None:
                saved = ast.keyword(arg=keyword.arg, value=self.save(self.visit(keyword.value)))
                result.append(saved)
                pending.append(saved)
                continue
            flush()
            source = self.visit(keyword.value)
            literal = source.source if isinstance(source, CollectionNew) else None
            if isinstance(literal, ast.Dict) and all(
                    isinstance(key, ast.Constant) and isinstance(key.value, str) for key in literal.keys):
                # Preserve statically named packs for the ordinary binder. It
                # can bind heterogeneous fixed parameters without interpreting
                # every value as a candidate for every dynamic destination.
                literal.values = [self.save(self.visit(value)) for value in literal.values]
                for name in dict.fromkeys(key.value for key in literal.keys):
                    for statement in check(ast.Constant(value=name)):
                        self.generated_statement(statement, source)
                result.append(ast.keyword(arg=None, value=source))
                continue
            value_type = analyzed_value_type(source)
            if (getattr(value_type, "generic_name", None) != "dict"
                    or value_type.generic_types["K"].generic_name != "str"):
                self.visitor.fail(keyword.value, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                  "native ** expansion requires a concrete string-keyed dict")
            copied = ast.copy_location(Call(value_type, func=Name(value_type, ctx=ast.Load()),
                                            args=[source], keywords=[]), source)
            set_analyzed_representation(copied, analyzed_representation(source))
            saved = self.save(copied)
            key = self.visitor.ir.new_name("$keyword")
            loop = ast.For(target=ast.Name(id=key, ctx=ast.Store()), iter=self.source_name(saved),
                           body=check(ast.Name(id=key, ctx=ast.Load())), orelse=[])
            self.generated_statement(loop, source)
            result.append(ast.keyword(arg=None, value=saved))
        flush()
        return result

    def visit_Subscript(self, node):
        if self.has_control_flow(node):
            node.value, node.slice = self.ordered([node.value, node.slice])
        return self.generic_visit(node)

    def visit_Slice(self, node):
        names = [name for name in ("lower", "upper", "step") if getattr(node, name) is not None]
        for name, value in zip(names, self.ordered([getattr(node, name) for name in names]), strict=True):
            setattr(node, name, value)
        return node

    def visit_List(self, node):
        if self.has_control_flow(node):
            if any(isinstance(value, ast.Starred) for value in node.elts):
                return self.expanded_collection(node)
            node.elts = self.ordered(node.elts)
        value = super().visit_List(node)
        allocation = getattr(node, "native_unpack_allocation", None)
        if allocation is not None:
            # The empty literal has now acquired its target type/representation.
            # Fill the reserved instruction, keeping allocation failure before
            # every store while evaluating the target only at its own turn.
            assignment, loaded = self.visitor.capture_assignment_value(value)
            allocation.__dict__.update(assignment.__dict__)
            return loaded
        return value

    def visit_Tuple(self, node):
        if self.has_control_flow(node):
            if any(isinstance(value, ast.Starred) for value in node.elts):
                if node.obj.tuple_variadic:
                    item_type = next(iter(node.obj.generic_types.values()))
                    source = ast.copy_location(List(BUILTINS.search("list")(item_type), elts=node.elts, ctx=ast.Load()), node)
                    representation = analyzed_representation(node)
                    set_analyzed_representation(source, compound_representation(
                        arguments=representation.arguments if representation else (None,)))
                    pack = self.expanded_collection(source)
                    result = ast.copy_location(Call(node.obj, func=Name(node.obj, ctx=ast.Load()), args=[pack], keywords=[]), node)
                    set_analyzed_representation(result, representation)
                    return result
                values = self.ordered(node.elts, trailing_control=True, defer_star=True)
                node.elts = []
                for value in values:
                    if isinstance(value, ast.Starred):
                        for index in range(len(analyzed_value_type(value.value).generic_types)):
                            access = ast.Subscript(value=self.source_name(value.value),
                                                   slice=ast.Constant(value=index), ctx=ast.Load())
                            access = ast.fix_missing_locations(ast.copy_location(access, value))
                            node.elts.append(self.visit(self.visitor.visit(access)))
                    else:
                        node.elts.append(value)
                return super().visit_Tuple(node)
            node.elts = self.ordered(node.elts)
        return super().visit_Tuple(node)

    def expanded_collection(self, node):
        from .mapping_keys import retain

        is_set = isinstance(node, ast.Set)
        first = set_literal_prefix(node.elts) if is_set else next(
            index for index, value in enumerate(node.elts) if isinstance(value, ast.Starred))
        prefix = self.ordered(node.elts[:first])
        source = Set(node.obj, elts=prefix) if is_set else List(node.obj, elts=prefix, ctx=ast.Load())
        ast.copy_location(source, node)
        set_analyzed_representation(source, analyzed_representation(node))
        if is_set:
            retain(source, analyzed_value_type(node))
            # The executable literal holds only the prefix. Lifetime analysis
            # must also see operands consumed by the generated insertions.
            # Record their saved bindings, not expressions to evaluate again.
            source.runtime_callback_operands = list(prefix)
        pack = self.save(ast.copy_location(CollectionNew(source), node))
        for value in node.elts[first:]:
            if isinstance(value, ast.Starred):
                saved = self.extend(pack, value.value, "update" if is_set else "extend")
            else:
                saved = self.save(self.visit(value))
                self.mutate(pack, "add" if is_set else "append", [saved], value)
            if is_set:
                source.runtime_callback_operands.append(saved)
        return pack

    def visit_Set(self, node):
        if self.has_control_flow(node):
            if set_literal_prefix(node.elts) < len(node.elts):
                return self.expanded_collection(node)
            node.elts = self.ordered(node.elts)
        return super().visit_Set(node)

    def dictionary(self, prototype, keys=(), values=(), *, callback_operands=None):
        from .mapping_keys import retain

        source = ast.copy_location(Dict(analyzed_value_type(prototype), keys=list(keys), values=list(values)), prototype)
        set_analyzed_representation(source, analyzed_representation(prototype))
        if callback_operands is not None:
            retain(source, analyzed_value_type(prototype))
            # The first allocation summarizes callbacks for the whole literal,
            # including keys present when a later **pack is merged. Recording
            # all bindings once avoids quadratic metadata for many groups and
            # keeps unrelated explicit values out of the escape constraints.
            source.runtime_callback_operands = callback_operands
        return self.save(ast.copy_location(CollectionNew(source), prototype))

    def visit_Dict(self, node):
        if self.has_control_flow(node):
            if len(node.keys) > DICTIONARY_STACK_ITEMS or any(key is None for key in node.keys):
                pack = None
                callback_operands = []
                for group in dictionary_literal_groups(node):
                    if group[0][0] is None:
                        if pack is None:
                            pack = self.dictionary(node, callback_operands=callback_operands)
                        callback_operands.append(self.extend(pack, group[0][1], "update"))
                        continue
                    if len(group) > DICTIONARY_STACK_ITEMS:
                        part = self.dictionary(node, callback_operands=callback_operands if pack is None else None)
                        for key, value in group:
                            key = self.save(self.visit(key))
                            value = self.save(self.visit(value))
                            callback_operands.append(key)
                            self.mutate(part, "__setitem__", [key, value], node)
                    else:
                        keys, values = [], []
                        for key, value in group:
                            keys.append(self.save(self.visit(key)))
                            values.append(self.save(self.visit(value)))
                        callback_operands.extend(keys)
                        part = self.dictionary(node, keys, values,
                                               callback_operands=callback_operands if pack is None else None)
                    if pack is None:
                        pack = part
                    else:
                        self.extend(pack, part, "update")
                return pack
            # Small dictionary literals evaluate all operands before insertion.
            values = self.ordered([part for pair in zip(node.keys, node.values, strict=True) for part in pair])
            node.keys, node.values = values[::2], values[1::2]
        return super().visit_Dict(node)

    def join(self, node, name):
        ir = self.visitor.ir
        done = ir.new_block(name)
        value_type = analyzed_value_type(node)
        variable = value_type(ir.new_name(name + "_value"), self.visitor.scope, self.visitor.func)
        result = BlockArgument(variable.name, value_type, variable)
        set_analyzed_representation(result, analyzed_representation(node))
        done.arguments.append(result)
        return done, result

    def visit_IfExp(self, node):
        ir = self.visitor.ir
        test = self.visit(self.visitor.truth_test(node.test, node.test))
        body, otherwise = ir.new_block("conditional_true"), ir.new_block("conditional_false")
        done, result = self.join(node, "conditional_done")
        ir.terminate(Branch(test, body.name, otherwise.name))
        for block, value in ((body, node.body), (otherwise, node.orelse)):
            ir.enter(block)
            ir.terminate(Jump(done.name, [self.visit(value)]))
        ir.enter(done)
        return result

    def visit_BoolOp(self, node):
        if not self.has_control_flow(node):
            return self.generic_visit(node)
        ir = self.visitor.ir
        done, result = self.join(node, "boolean_done")
        for value in node.values[:-1]:
            value = self.save(self.visit(value))
            following, short = ir.new_block("boolean_next"), ir.new_block("boolean_short")
            test = self.visit(self.visitor.truth_test(value, value))
            targets = (following, short) if isinstance(node.op, ast.And) else (short, following)
            ir.terminate(Branch(test, *(target.name for target in targets)))
            ir.enter(short)
            ir.terminate(Jump(done.name, [value]))
            ir.enter(following)
        ir.terminate(Jump(done.name, [self.visit(node.values[-1])]))
        ir.enter(done)
        return result

    def visit_EvaluateOnce(self, node):
        # Always lower the lexical binding, including straight-line bodies.
        # Otherwise an outer substitution can capture a shadowing name, and
        # closure discovery mistakes the retained synthetic name for a free
        # variable. Ordinary IR temporaries already handle both scopes.
        previous = self.bindings.get(node.parameter)
        self.bindings[node.parameter] = self.save(self.visit(node.value))
        try:
            return self.visit(node.body)
        finally:
            if previous is None:
                self.bindings.pop(node.parameter)
            else:
                self.bindings[node.parameter] = previous

    def visit_ChainedCompare(self, node):
        if not self.has_control_flow(node):
            return self.generic_visit(node)
        ir = self.visitor.ir
        done, result = self.join(node, "comparison_done")
        previous = {value.id: self.bindings.get(value.id) for value in node.temporaries}
        try:
            self.bindings[node.temporaries[0].id] = self.save(self.visit(node.operands[0]))
            for index, comparison in enumerate(node.comparisons):
                self.bindings[node.temporaries[index + 1].id] = self.save(self.visit(node.operands[index + 1]))
                comparison = self.visit(comparison)
                if index + 1 == len(node.comparisons):
                    ir.terminate(Jump(done.name, [comparison]))
                else:
                    following, short = ir.new_block("comparison_next"), ir.new_block("comparison_short")
                    ir.terminate(Branch(comparison, following.name, short.name))
                    ir.enter(short)
                    ir.terminate(Jump(done.name, [Constant(BUILTINS.search("bool"), value=False)]))
                    ir.enter(following)
        finally:
            for name, value in previous.items():
                if value is None:
                    self.bindings.pop(name, None)
                else:
                    self.bindings[name] = value
        ir.enter(done)
        return result

    def visit_JoinedStr(self, node):
        node.values = self.ordered(node.values)
        return node

    def visit_FormattedValue(self, node):
        if node.format_spec is not None:
            node.value, node.format_spec = self.ordered([node.value, node.format_spec])
        else:
            node.value = self.visit(node.value)
        return node
