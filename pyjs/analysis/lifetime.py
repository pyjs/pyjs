"""Conservative lifetime summaries for typed control-flow IR.

The final reachability pass combines constructor effects, reached virtual
overrides, and member-producing operations. Unknown members retain their
container as a conservative caller-side proxy.
"""

import ast
from collections import deque
from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum

from pyjs.decorators import ParameterLifetime, parameter_lifetimes

from .analyzer import analyzed_value_type
from .ir import (
    Block,
    BlockArgument,
    CollectionNew,
    ExceptionRaise,
    FieldLoad,
    FieldStore,
    FunctionIR,
    IteratorCreate,
    IteratorNext,
    Jump,
    ListAppend,
    ObjectNew,
    Return,
)
from .objects import (
    Attribute,
    Class,
    EvaluateOnce,
    Function,
    GenericClass,
    Instance,
    Module,
)
from .type_relations import get_type_members


def lambda_captures(node):
    """Free lexical bindings, including dependencies of nested lambdas."""
    bound = {parameter.arg for parameter in (
        *node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
    )}
    bound.update(getattr(node, "local_names", ()))
    captures = {}

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, value):
            target = getattr(value, "obj", None)
            if (isinstance(value.ctx, ast.Load) and value.id not in bound
                    and isinstance(target, Instance)
                    and (isinstance(target.container, Function)
                         or value.id == "self" and isinstance(target.container, Class))):
                captures.setdefault(value.id, value)

        def visit_Lambda(self, nested):
            for name, value in lambda_captures(nested).items():
                if name not in bound:
                    captures.setdefault(name, value)

    visitor = Visitor()
    for child in getattr(node, "blocks", (node.body,)):
        visitor.visit(child)
    return captures


class LifetimeBoundary(StrEnum):
    """Furthest scope in which a value may remain reachable."""

    LOCAL = "local"
    CALLER = "caller"
    EXTERNAL = "external"


@dataclass(frozen=True)
class ParameterOrigin:
    name: str


class OpaqueOwner(ast.expr):
    """Analysis-only intermediate owner; never inserted into executable IR."""


@dataclass
class AllocationLifetime:
    site: int
    operation: ObjectNew | CollectionNew
    boundary: LifetimeBoundary = LifetimeBoundary.LOCAL
    reasons: set[str] = field(default_factory=set)


@dataclass
class FunctionLifetime:
    allocations: list[AllocationLifetime]
    parameters: dict[str, LifetimeBoundary]
    parameter_reasons: dict[str, frozenset[str]]
    returned_parameters: frozenset[str]
    external_parameters: frozenset[str]
    parameter_containment: tuple[tuple[str, str], ...]
    call_dependencies: tuple[tuple[Function, tuple | None], ...]
    contained_return_parameters: frozenset[str] = frozenset()
    external_member_parameters: frozenset[str] = frozenset()
    returns_external: bool = False


class LifetimeConstraints(ast.NodeVisitor):
    def __init__(self, ir: FunctionIR):
        self.allocations: list[ObjectNew | CollectionNew] = []
        self.assignment_constraints: list[tuple[str, ast.expr]] = []
        self.containment_constraints: list[
            tuple[ast.expr, ast.expr, str]
        ] = []
        self.returned: list[ast.expr] = []
        self.external_operands: list[ast.expr] = []
        self.calls: list[ast.Call] = []
        self.constructor_calls: dict[ast.Call, tuple[Function, ObjectNew]] = {}
        self.iterators: dict[str, ast.expr] = {}
        self.block_arguments = {
            block.name: block.arguments
            for block in ir.blocks
            if isinstance(block, Block)
        }

    def collect(self, ir: FunctionIR) -> None:
        for block in ir.blocks:
            self.visit(block)

    def record_allocation(self, node: ObjectNew | CollectionNew) -> None:
        self.allocations.append(node)

    def visit_Lambda(self, node):
        # A closure may escape or run after rebinding its captured cell. Keep
        # every possible captured value alive; do not execute its body while
        # computing the enclosing function's allocation/call effects.
        self.external_operands.extend(lambda_captures(node).values())

    def visit_Comprehension(self, node):
        self.external_operands.append(node.source)
        self.visit(node.source)
        self.visit(node.function)

    def bind_target(self, target, value) -> None:
        if isinstance(target, (ast.Name, ast.arg)):
            name = target.id if isinstance(target, ast.Name) else target.arg
            self.assignment_constraints.append((name, value))
            return
        if isinstance(target, ast.Subscript):
            self.containment_constraints.append(
                (target.value, value, "subscript store")
            )
            return
        if not isinstance(target, (ast.List, ast.Tuple)):
            return
        source = value.source if isinstance(value, CollectionNew) else value
        if not isinstance(source, (ast.List, ast.Tuple)):
            # A destructured value from a parameter, call, index, or iterator
            # has no literal member correspondence in the IR. Every leaf may
            # therefore alias any member of the source.
            member = ast.Starred(value=value, ctx=ast.Load())
            for item_target in target.elts:
                self.bind_target(item_target, member)
            return
        if len(target.elts) != len(source.elts):
            return
        for item_target, item_value in zip(
            target.elts,
            source.elts,
            strict=True,
        ):
            self.bind_target(item_target, item_value)

    def visit_ObjectNew(self, node: ObjectNew):
        self.record_allocation(node)
        # A constructor may retain any argument. A later interprocedural pass
        # can remove these edges when its parameter summary proves otherwise.
        for argument in node.call.args:
            self.containment_constraints.append(
                (node, argument, "constructor argument")
            )
            self.visit(argument)
        for keyword in node.call.keywords:
            self.containment_constraints.append(
                (node, keyword.value, "constructor argument")
            )
            self.visit(keyword.value)
        constructor = node.value_type.find("__init__")
        if isinstance(constructor, Function):
            self.constructor_calls[node.call] = (constructor, node)

    def visit_CollectionNew(self, node: CollectionNew):
        self.record_allocation(node)
        if isinstance(node.source, ast.Dict):
            values = [
                *[key for key in node.source.keys if key is not None],
                *node.source.values,
            ]
        else:
            values = node.source.elts
        for value in values:
            self.containment_constraints.append(
                (node, value, "collection member")
            )
            self.visit(value)

    def visit_FieldLoad(self, node: FieldLoad):
        self.visit(node.attribute.value)

    def visit_Attribute(self, node: ast.Attribute):
        if getattr(node, "property_getters", ()):
            self.external_operands.append(node.value)
        self.generic_visit(node)

    def visit_FieldStore(self, node: FieldStore):
        self.containment_constraints.append(
            (node.target.value, node.value, "field store")
        )
        self.visit(node.target.value)
        self.visit(node.value)

    def visit_ListAppend(self, node: ListAppend):
        self.containment_constraints.append(
            (node.call.func.value, node.call.args[0], "list append")
        )
        self.visit(node.call.func.value)
        self.visit(node.call.args[0])

    def visit_IteratorCreate(self, node: IteratorCreate):
        self.iterators[node.name] = node.iterable
        self.visit(node.iterable)
        if any(not getattr(method.cls.py_obj, "__builtin__", False)
               for method in node.runtime_methods):
            # An application __iter__ can retain self through an aliased field
            # (self.saved.append(self)). Parameter-only call summaries cannot
            # express that field path yet, so do not infer local ownership.
            self.external_operands.append(node.iterable)

    def visit_IteratorNext(self, node: IteratorNext):
        iterable = self.iterators[node.iterator]
        member = ast.Starred(value=iterable, ctx=ast.Load())
        self.bind_target(node.target, member)

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            self.assign_target(target, node.value)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.value is not None:
            self.assign_target(node.target, node.value)
            self.visit(node.value)

    def assign_target(self, target, value):
        self.bind_target(target, value)
        setters = getattr(target, "property_setters", ())
        if setters:
            # Accessors obey ordinary call retention and virtual dispatch.
            # These analysis-only calls preserve setter/getter identity and
            # do not change the executable assignment's evaluation order.
            for setter in setters:
                self.calls.append(ast.Call(
                    func=Attribute(setter, value=target.value, attr=target.attr),
                    args=[value], keywords=[],
                ))
            self.visit(target.value)

    def visit_Jump(self, node: Jump):
        arguments = self.block_arguments[node.target]
        for target, value in zip(arguments, node.arguments, strict=True):
            self.assignment_constraints.append((target.name, value))
            self.visit(value)

    def visit_EvaluateOnce(self, node: EvaluateOnce):
        self.assignment_constraints.append((node.parameter, node.value))
        self.visit(node.value)
        self.visit(node.body)

    def visit_ChainedCompare(self, node):
        # The name-based solver can conservatively merge temporaries from
        # independent chains, but must not lose their operand origins.
        for temporary, operand in zip(node.temporaries, node.operands, strict=True):
            self.assignment_constraints.append((temporary.id, operand))
            self.visit(operand)
        for comparison in node.comparisons:
            self.visit(comparison)

    def visit_Return(self, node: Return):
        if node.value is not None:
            self.returned.append(node.value)
            self.visit(node.value)

    def visit_ExceptionRaise(self, node: ExceptionRaise):
        # A caller can catch and retain a payload independently of the failed
        # call. Until summaries model exceptional results, treat it as escaped.
        if node.message is not None:
            self.external_operands.append(node.message)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        function = getattr(node.func, "obj", None)
        if (
            isinstance(function, Function)
            and function.name == "__setitem__"
            and function.cls is not None
            and getattr(function.cls.py_obj, "__builtin__", False)
            and isinstance(node.func, ast.Attribute)
            and len(node.args) >= 2
        ):
            # Inference rewrites indexed assignment to a builtin
            # ``__setitem__`` call before IR lifetime collection.
            self.containment_constraints.append(
                (node.func.value, node.args[1], "subscript store")
            )
            if function.cls.generic_name == "dict":
                # A mapping owns both sides of the entry. Unlike a sequence
                # index, its stored key must survive when the container escapes.
                self.containment_constraints.append(
                    (node.func.value, node.args[0], "dictionary key store")
                )
        self.calls.append(node)
        self.generic_visit(node)


class LifetimeInference:
    def __init__(
        self,
        function: Function,
        ir: FunctionIR,
        reached_functions: set[Function] | None = None,
    ):
        self.function = function
        self.ir = ir
        self.constraints = LifetimeConstraints(ir)
        self.parameters = {
            name: ParameterOrigin(name)
            for name in self.parameter_names(function)
        }
        self.names: dict[
            str,
            set[ObjectNew | CollectionNew | ParameterOrigin | ast.Call | OpaqueOwner],
        ] = {
            name: {origin}
            for name, origin in self.parameters.items()
        }
        self.contents: dict[
            ObjectNew | CollectionNew | ParameterOrigin | ast.Call | OpaqueOwner,
            set[ObjectNew | CollectionNew | ParameterOrigin | ast.Call | OpaqueOwner],
        ] = {}
        self.states: dict[
            ObjectNew | CollectionNew | ParameterOrigin | ast.Call | OpaqueOwner,
            tuple[LifetimeBoundary, set[str]],
        ] = {}
        self.call_returns: dict[ast.Call, list[ast.expr]] = {}
        self.container_results: set[ast.Call | OpaqueOwner] = set()
        self.call_dependencies: dict[Function, tuple | None] = {}
        self.reached_functions = reached_functions
        # Persistent storage must remain an origin when copied into a local
        # field/pack. An empty origin set previously lost that path, so writes
        # through the local alias could retain request-arena allocations.
        self.external_owner = OpaqueOwner()
        self.opaque_owner(self.external_owner, ())
        self.constraints.external_operands.append(self.external_owner)

    @staticmethod
    def parameter_names(function: Function) -> list[str]:
        names = [parameter.arg for parameter in function.params]
        names.extend(parameter.arg for parameter in function.kwonlyargs)
        if function.vararg is not None:
            names.append(function.vararg.arg)
        if function.kwarg is not None:
            names.append(function.kwarg.arg)
        if function.is_method and not function.is_static:
            names.append("self")
        return list(dict.fromkeys(names))

    def call_arguments(
        self,
        call: ast.Call,
        function: Function,
        receiver: ast.expr | None = None,
    ) -> dict[str, list[ast.expr]]:
        arguments: dict[str, list[ast.expr]] = {}
        if (
            function.is_method
            and not function.is_static
            and (receiver is not None or isinstance(call.func, ast.Attribute))
        ):
            arguments["self"] = [
                receiver if receiver is not None else call.func.value
            ]

        positional_names = [parameter.arg for parameter in function.params]
        positional_index = 0
        uncertain_position = False
        definite_names = set()
        pending = list(reversed(call.args))
        while pending:
            value = pending.pop()
            source = value.value if isinstance(value, ast.Starred) else None
            source = source.source if isinstance(source, CollectionNew) else source
            if isinstance(value, ast.Starred) and isinstance(source, (ast.Tuple, ast.List)):
                # Literal packs supply definite positions, including nested
                # literal packs. Unknown expansions still use the conservative
                # binding below; this is analysis only, not runtime evaluation.
                pending.extend(reversed(source.elts))
                continue
            if isinstance(value, ast.Starred):
                uncertain_position = True
            if uncertain_position:
                # Once an expansion is encountered, its length determines the
                # destination of every later positional value. Associate each
                # with every remaining destination rather than guess a length.
                for name in positional_names[positional_index:]:
                    arguments.setdefault(name, []).append(value)
                if function.vararg is not None:
                    arguments.setdefault(function.vararg.arg, []).append(value)
            elif positional_index < len(positional_names):
                name = positional_names[positional_index]
                arguments.setdefault(name, []).append(value)
                definite_names.add(name)
                positional_index += 1
            elif function.vararg is not None:
                arguments.setdefault(function.vararg.arg, []).append(value)
        keyword_names = {
            parameter.arg for parameter in function.kwonlyargs
        } | set(positional_names[function.posonly_count:])
        keywords = []
        for keyword in call.keywords:
            value = keyword.value
            source = value.source if isinstance(value, CollectionNew) else value
            if (keyword.arg is None and isinstance(source, ast.Dict)
                    and all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in source.keys)):
                keywords.extend((key.value, item) for key, item in zip(source.keys, source.values, strict=True))
            else:
                keywords.append((keyword.arg, value))
        for name, value in keywords:
            if name is not None:
                if name not in keyword_names and function.kwarg is not None:
                    name = function.kwarg.arg
                arguments.setdefault(name, []).append(value)
                definite_names.add(name)
            else:
                member = ast.Starred(value=value, ctx=ast.Load())
                for name in keyword_names:
                    arguments.setdefault(name, []).append(member)
                if function.kwarg is not None:
                    arguments.setdefault(function.kwarg.arg, []).append(member)
        # Omitted defaults belong to the function, not this invocation. An
        # expansion may also leave a default in effect, even when it supplies
        # a possible binding above. Give that persistent source its own origin
        # so returned-member writes and callee stores share the same rule.
        defaults = [*zip(function.params[len(function.params) - len(function.defaults):], function.defaults, strict=True),
                    *zip(function.kwonlyargs, function.kw_defaults, strict=True)]
        fresh_defaults = set()
        if (defaults and function.name == "__init__" and function.has_synthetic_source
                and function.cls is not None and is_dataclass(function.cls.py_obj)):
            # Synthetic factory parameters use a MISSING sentinel, not a
            # persistent collection. Only builtin identity proves fresh storage;
            # a user factory (even named list) can return a shared global.
            fresh_defaults = {item.name for item in fields(function.cls.py_obj)
                              if any(item.default_factory is factory for factory in (list, dict, set, tuple))}
        for parameter, default in defaults:
            if default is None or parameter.arg in definite_names:
                continue
            if isinstance(default, ast.Constant):
                # Match explicit scalar arguments: no mutable origin. An
                # optional getter may select global storage when given None,
                # so keep the binding rather than creating an orphan result.
                arguments.setdefault(parameter.arg, []).append(default)
                continue
            owner = OpaqueOwner()
            self.opaque_owner(owner, ())
            if parameter.arg not in fresh_defaults:
                self.constraints.external_operands.append(owner)
            arguments.setdefault(parameter.arg, []).append(owner)
        return arguments

    @staticmethod
    def unknown_call_operands(call: ast.Call) -> list[ast.expr]:
        operands = list(call.args)
        operands.extend(
            keyword.value
            if keyword.arg is not None
            else ast.Starred(value=keyword.value, ctx=ast.Load())
            for keyword in call.keywords
        )
        if isinstance(call.func, ast.Attribute):
            operands.append(call.func.value)
        return operands

    @staticmethod
    def is_subclass(value_type: Class, base: Class) -> bool:
        current = value_type
        while current is not None:
            if current is base:
                return True
            current = current.super
        return False

    def dispatch_targets(
        self,
        call: ast.Call,
        function: Function,
    ) -> tuple[Function, ...]:
        receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
        super_call = (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "super"
        )
        # A call's obj is its result type; value_obj is the actual instance.
        # identity(value).method() must still include reached overrides.
        class_access = isinstance(getattr(receiver, "value_obj", getattr(receiver, "obj", None)), Class)
        if (
            self.reached_functions is None
            or not function.is_method
            or function.is_static
            or not isinstance(call.func, ast.Attribute)
            or super_call
            or class_access
        ):
            return (function,)
        return self.virtual_targets(function)

    def virtual_targets(self, function: Function) -> tuple[Function, ...]:
        targets = {
            candidate
            for candidate in self.reached_functions or ()
            if candidate.name == function.name
            and candidate.is_property_setter == function.is_property_setter
            and candidate.is_property == function.is_property
            and candidate.cls is not None
            and function.cls is not None
            and self.is_subclass(candidate.cls, function.cls)
        }
        targets.add(function)
        return tuple(
            sorted(
                targets,
                key=lambda target: (target.cls.name, target.name),
            )
        )

    def runtime_targets(self, call: ast.expr) -> tuple[Function, ...]:
        targets = dict.fromkeys(
            target for method in getattr(call, "runtime_methods", ())
            for target in self.virtual_targets(method)
        )
        # Protocol dependencies can name methods introduced only by a reached
        # subclass. Reachability includes them, but there need not be a static
        # runtime_methods entry from which virtual_targets could discover them.
        for receiver, names in getattr(call, "runtime_protocols", ()):
            members = get_type_members(receiver) if receiver is not None else ()
            for member in members:
                for name in names:
                    method = member.find_attrs(name)
                    if isinstance(method, Function):
                        targets[method] = None
            for candidate in self.reached_functions or ():
                if (candidate.cls is not None and candidate.name in names
                        and (receiver is None or any(
                            self.is_subclass(candidate.cls, member) for member in members
                        ))):
                    targets[candidate] = None
        return tuple(targets)

    def prepare_indirect_callbacks(self, call: ast.expr, names: set[str], *, operands=None) -> None:
        if operands is None:
            operands = getattr(call, "runtime_callback_operands", None)
        for target in self.runtime_targets(call):
            if target.name not in names or target.cls is None:
                continue
            # An implicit callback's self may be a contained object, not the
            # container passed to comparison or formatting machinery.
            # Its syntax (including a literal or a view-producing call) must
            # not suppress virtual dispatch of the contained objects.
            if getattr(target.cls.py_obj, "__builtin__", False):
                continue
            summary = target.ir.lifetime if target.ir is not None else None
            if target.ir is not None:
                self.call_dependencies[target] = (
                    outward_summary_key(summary) if summary is not None else None
                )
            if summary is None or summary.external_parameters or summary.parameter_containment:
                # Collection members can alias caller-owned objects through
                # nested containers and views. Until those member bindings
                # are explicit, retaining callbacks escape the call's operands.
                # Pure callbacks keep their normal local allocation policy.
                self.constraints.external_operands.extend(
                    self.unknown_call_operands(call) if operands is None else operands)

    @staticmethod
    def builtin_operand(value, names) -> bool:
        return hasattr(value, "obj") and all(
            isinstance(member, Class) and member.container.scope.is_builtins
            and member.generic_name in names
            for member in get_type_members(analyzed_value_type(value))
        )

    def retain_external_operands(self, values) -> None:
        # Unboxed scalar reads do not borrow their field/container storage.
        # Do not include str/bytes: their data can still require an owner.
        self.constraints.external_operands.extend(
            value for value in values
            if not self.builtin_operand(value, {"bool", "int", "float", "NoneType"})
        )

    def prepare_known_call(
        self,
        call: ast.Call,
        functions: tuple[Function, ...],
        receiver: ast.expr | None = None,
        *,
        reflected: bool = False,
    ) -> None:
        for function in functions:
            arguments = self.call_arguments(call, function, receiver)
            if reflected:
                arguments["self"] = [call.args[0]]
                arguments[function.params[0].arg] = [call.func.value]
            self.prepare_container_effects(call, function, arguments)
            if (
                function.name == "__getitem__"
                and function.cls is not None
                and getattr(function.cls.py_obj, "__builtin__", False)
                and isinstance(call.func, ast.Attribute)
            ):
                # A scalar subscription returns a member, not the container.
                # A slice may alias its source (notably a full tuple slice),
                # so keep the source alive for that path and unknown domains.
                keys = [*call.args, *(keyword.value for keyword in call.keywords)]
                primitive_key = bool(keys) and all(
                    self.builtin_operand(value, {"bool", "int", "float", "str", "bytes", "NoneType"})
                    for value in keys
                )
                source = call.func.value
                if primitive_key and function.cls.generic_name in {"tuple", "list", "dict"}:
                    source = ast.Starred(value=source, ctx=ast.Load())
                if not primitive_key:
                    sequence = function.cls.generic_name in {"tuple", "list", "str", "bytes", "range"}
                    # Sequence __index__ callbacks see the key, not the source.
                    # The builtin slice model has scalar-only bounds; it invokes
                    # no callback and must not escape its field/container owner.
                    self.retain_external_operands(
                        value for value in keys
                        if not (sequence and self.builtin_operand(value, {"slice"}))
                    )
                    if not sequence:
                        # Dictionary equality can retain stored keys as well as
                        # the query. Unknown builtin receivers stay conservative.
                        self.constraints.external_operands.append(call.func.value)
                self.call_returns.setdefault(call, []).append(source)
                continue
            summary = function.ir.lifetime if function.ir is not None else None
            contracts = parameter_lifetimes(function.py_func)
            declared_returned = frozenset(name for name, lifetime in contracts.items()
                                          if lifetime is ParameterLifetime.RETURNED)
            declared_external = frozenset(name for name, lifetime in contracts.items()
                                          if lifetime is ParameterLifetime.EXTERNAL)
            if summary is not None:
                self.call_dependencies[function] = outward_summary_key(summary)
                # Native model methods can have analyzed placeholder bodies.
                # Explicit runtime effects supplement, never erase, inference.
                returned = summary.returned_parameters | declared_returned
                external = summary.external_parameters | declared_external
                containment = summary.parameter_containment
                if (function.is_property_setter and function.cls is not None
                        and vars(function.cls.py_obj).get("__builtin__", False)):
                    # A builtin accessor's ellipsis body is not proof that its
                    # runtime borrows arguments. Only explicit contracts can
                    # exempt them from the opaque setter boundary.
                    self.constraints.external_operands.extend(
                        value for name, values in arguments.items() if name not in contracts
                        for value in values
                    )
            else:
                if function.ir is not None:
                    self.call_dependencies[function] = None
                if not contracts:
                    self.constraints.external_operands.extend(
                        self.unknown_call_operands(call)
                    )
                    continue
                returned = declared_returned
                external = declared_external
                containment = ()
                contracted = contracts.keys()
                for name, values in arguments.items():
                    if name not in contracted:
                        self.constraints.external_operands.extend(values)

            call_returns = self.call_returns.setdefault(call, [])
            if summary is not None:
                if summary.returns_external:
                    call_returns.append(self.external_owner)
                for name in summary.external_member_parameters:
                    self.constraints.containment_constraints.extend(
                        (value, self.external_owner, "callee persistent storage member")
                        for value in arguments.get(name, ())
                    )
            for name in returned:
                call_returns.extend(arguments.get(name, ()))
                # Inferred and declared returned-parameter effects can describe
                # an entry member (e.g. self.items). Keep that writable path
                # reachable from its source, not just as a flattened alias.
                owner = OpaqueOwner()
                self.opaque_owner(owner, ())
                self.constraints.containment_constraints.extend(
                    (value, owner, "returned parameter member")
                    for value in arguments.get(name, ())
                )
                call_returns.append(owner)
            if summary is not None and summary.contained_return_parameters:
                # A parameter retained inside a returned object is not the
                # result itself. The summary does not encode its nesting depth:
                # keep an opaque owner reachable through any member projection.
                # The self edge is analysis-only, not a runtime reference cycle.
                self.opaque_owner(call, (
                    value
                    for name in summary.contained_return_parameters
                    for value in arguments.get(name, ())
                ))
            for name in external:
                self.retain_external_operands(arguments.get(name, ()))
            for container_name, value_name in containment:
                # A pair describes reachability, not storage depth. Parameter
                # origins also proxy fields/items present on entry, so even a
                # seemingly direct edge can mean self.items.append(value).
                # Preserve direct aliases AND an opaque path through arbitrary
                # intermediate owners, independently for each destination.
                owner = OpaqueOwner()
                self.opaque_owner(owner, arguments.get(value_name, ()))
                for container in arguments.get(container_name, ()):
                    self.constraints.containment_constraints.append(
                        (container, owner, "callee parameter member retention")
                    )
                    for value in arguments.get(value_name, ()):
                        self.constraints.containment_constraints.append(
                            (container, value, "callee parameter retention")
                        )

    def opaque_owner(self, owner: ast.Call | OpaqueOwner, values) -> None:
        """Retain members at unknown nesting depth without a runtime allocation."""
        self.container_results.add(owner)
        self.constraints.containment_constraints.append((owner, owner, "opaque owner"))
        self.constraints.containment_constraints.extend(
            (owner, value, "opaque owner member") for value in values
        )

    def prepare_container_effects(self, call, function, arguments) -> None:
        """Supplement opaque builtin bodies with ownership, not escape flags.

        Reuse the ordinary bound arguments and containment solver so a local
        collection remains local, while wrappers propagate retention to callers.
        Member projections also model shallow copies: the new container owns
        the old members without necessarily retaining the old container itself.
        Indexed stores and ListAppend already contribute edges during collection.
        """
        cls = function.cls
        if not (getattr(cls.py_obj, "__builtin__", False) if cls is not None
                else function.container.scope.is_builtins):
            return
        family, method = cls.generic_name if cls is not None else None, function.name
        owners = arguments.get("self", ())
        positional = [arguments.get(parameter.arg, ()) for parameter in function.params]

        def argument(index):
            # Use declaration positions, not backend-specific parameter names.
            return positional[index] if index < len(positional) else ()

        def members(values):
            return [ast.Starred(value=value, ctx=ast.Load()) for value in values]

        stored = []
        returned = []
        result_members = []
        opaque = False
        if family is None:
            if method in {"iter", "reversed", "zip", "enumerate"}:
                # Iterators own their sources, and zip/enumerate introduce an
                # extra yielded tuple. Keep the opaque cursor reachable through
                # projections rather than confuse its source with a yielded item.
                result_members = [value for values in arguments.values() for value in values]
                opaque = True
            elif method == "sorted":
                result_members = members(argument(0))
            elif method == "next":
                returned = [*members(argument(0)), *argument(1)]
            elif method in {"min", "max"}:
                # Single-iterable and variadic forms return items and arguments
                # respectively. Unknown expansion lengths conservatively include
                # both levels; key callbacks are not candidate return values.
                returned = members(call.args) if len(call.args) == 1 else list(call.args)
                if any(isinstance(value, ast.Starred) for value in call.args):
                    returned.extend(call.args)
                returned.extend(arguments.get("default", ()))
        elif method == "__iter__" or family == "dict" and method in {"keys", "values", "items"}:
            result_members = list(owners)
            opaque = True
        elif method == "__next__" and family in {"Iterator", "Generator"}:
            returned = members(owners)
        elif family == "dict":
            if method == "setdefault":
                stored = [*argument(0), *argument(1)]
                returned = [*members(owners), *argument(1)]
            elif method in {"update", "__ior__"}:
                # The graph deliberately does not distinguish mapping keys
                # from values, nor fields of a yielded (key, value) pair.
                stored = members(argument(0))
                if method == "__ior__":
                    returned = list(owners)
            elif method == "fromkeys":
                result_members = [*members(argument(0)), *argument(1)]
            elif method in {"__or__", "__ror__"}:
                result_members = members([*owners, *argument(0)])
            elif method in {"get", "pop"}:
                returned = [*members(owners), *argument(1)]
            elif method == "popitem":
                result_members = members(owners)
        elif family == "list":
            if method == "insert":
                stored = list(argument(1))
            elif method in {"extend", "__iadd__", "__setslice__"}:
                stored = members(argument(0))
                if method == "__iadd__":
                    returned = list(owners)
            elif method == "__add__":
                result_members = members([*owners, *argument(0)])
            elif method in {"__mul__", "__rmul__"}:
                result_members = members(owners)
            elif method == "__imul__":
                returned = list(owners)
            elif method == "pop":
                returned = members(owners)
            elif method == "__slice__":
                result_members = members(owners)
        elif family in {"set", "frozenset"}:
            others = [*argument(0), *arguments.get(function.vararg.arg, ())] if function.vararg else list(argument(0))
            if method == "add":
                stored = list(argument(0))
            elif method in {"update", "intersection_update", "symmetric_difference_update",
                            "__ior__", "__iand__", "__ixor__"}:
                # Intersection can select the equal object from either set.
                stored = members(others)
            if method in {"__ior__", "__iand__", "__ixor__", "__isub__"}:
                returned = list(owners)
            elif method in {"union", "intersection", "symmetric_difference",
                            "__or__", "__and__", "__xor__"}:
                result_members = members([*owners, *others])
            elif method in {"difference", "__sub__"}:
                result_members = members(owners)
            elif method == "pop":
                returned = members(owners)
        if method == "copy" and family in {"dict", "list", "set", "frozenset"}:
            # frozenset.copy() may return self, not a fresh shallow copy.
            if family == "frozenset":
                returned = list(owners)
            else:
                result_members = members(owners)
        for owner in owners:
            for value in stored:
                self.constraints.containment_constraints.append(
                    (owner, value, "builtin stored member")
                )
        if returned:
            self.call_returns.setdefault(call, []).extend(returned)
        if result_members:
            # A result container is not an alias of its members. Preserve this
            # extra graph level so copy()[0] yields the original item, not that
            # item's fields. This is ownership provenance, not a new IR allocation.
            self.container_results.add(call)
            self.constraints.containment_constraints.extend(
                (call, value, "builtin result member") for value in result_members
            )
            if opaque:
                self.constraints.containment_constraints.append((call, call, "opaque iterator owner"))
                # Views/cursors expose existing source members, not copies.
                # Keep source aliases as well as ownership: otherwise nested
                # iter(view) projections can record writes only on the cursor,
                # losing their parameter destination in the callee summary.
                self.call_returns.setdefault(call, []).extend(result_members)

    def prepare_call_constraints(self) -> None:
        for allocation in self.constraints.allocations:
            if not isinstance(allocation, CollectionNew):
                continue
            source = allocation.source
            if isinstance(source, ast.Dict):
                # Only keys participate in construction callbacks. An unpacked
                # mapping can supply collision candidates from its own keys.
                operands = [key if key is not None else value
                            for key, value in zip(source.keys, source.values, strict=True)]
            elif isinstance(source, ast.Set):
                operands = source.elts
            else:
                continue
            # Literal construction is an allocation, not a Call, but hashing
            # and collision equality can still save members outside a request.
            # Reuse reached callback summaries so pure keys remain arena-local.
            # Lowering may split a literal into allocation plus insertions;
            # those nodes expose saved key bindings, not executable operands.
            operands = getattr(source, "runtime_callback_operands", operands)
            self.prepare_indirect_callbacks(source, {"__hash__", "__eq__"}, operands=operands)
        for call in self.constraints.calls:
            function = getattr(call.func, "obj", None)
            if not isinstance(function, Function):
                self.constraints.external_operands.extend(
                    self.unknown_call_operands(call)
                )
                # An unknown callable can return existing persistent storage.
                # Known builtin conversions with immutable result contents
                # cannot expose a writable alias. Keep operand retention (a
                # conversion may invoke user code), but do not let str(n), for
                # example, contaminate unrelated fields of its local receiver.
                if not (isinstance(function, Class) and function.container.scope.is_builtins
                        and self.immutable_builtin_type(analyzed_value_type(call))):
                    self.call_returns.setdefault(call, []).append(self.external_owner)
                continue
            targets = tuple(dict.fromkeys(
                target for member in (getattr(call.func, "union_functions", ()) or (function,))
                for target in self.dispatch_targets(call, member)
            ))
            formatting = {"__str__", "__repr__", "__format__"}
            if (any(method.name in formatting for method in getattr(call, "runtime_methods", ()))
                    or any(formatting.intersection(names) for _, names in getattr(call, "runtime_protocols", ()))):
                self.prepare_indirect_callbacks(call, formatting)
            if binary := getattr(call, "binary_methods", None):
                # Native binary selection can change which source operand is
                # self. Bind forward/reflected protocol effects independently
                # of the statically selected call's operand order.
                for index, name in enumerate(binary):
                    methods = tuple(method for method in self.runtime_targets(call)
                                    if method.name == name and len(method.params) == 1)
                    self.prepare_known_call(call, methods,
                                            reflected=bool(index) != getattr(call, "reverse", False))
            if inplace := getattr(call, "inplace_method", None):
                # A subtype may introduce an in-place method where the static
                # type uses binary fallback. Its self is always the source
                # left operand, even when that fallback is a reflected call.
                methods = tuple(method for method in self.runtime_targets(call)
                                if method.name == inplace and len(method.params) == 1)
                self.prepare_known_call(call, methods, reflected=getattr(call, "reverse", False))
            if (any(method.name in {"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"}
                    for method in getattr(call, "runtime_methods", ()))
                    and (function.cls is None or function.name == "sort")
                    or function.runtime_dunders is not None and set(function.runtime_dunders[1]) <= {
                    "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"}
                    or getattr(call, "runtime_member_callbacks", False)
                    or isinstance(getattr(call, "operator", None), (ast.In, ast.NotIn))):
                self.prepare_indirect_callbacks(call, {"__hash__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"})
            elif (isinstance(getattr(call, "operator", None), (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE))
                    and isinstance(call.func, ast.Attribute) and len(call.args) == 1):
                # Runtime rich comparison may invoke either operand's override,
                # including __eq__ through inherited __ne__. Reachability alone
                # does not describe which object is self in those callbacks.
                methods = tuple(dict.fromkeys(
                    target for target in (*targets, *self.runtime_targets(call))
                    if target.name in {"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"}
                    if target.is_method and not target.is_static and len(target.params) == 1
                ))
                self.prepare_known_call(call, methods, reflected=True)
                targets = tuple(dict.fromkeys((*targets, *methods)))
            self.prepare_known_call(call, targets)
        for call, (constructor, receiver) in self.constraints.constructor_calls.items():
            self.prepare_known_call(call, (constructor,), receiver)

    def member_origins(self, container) -> set:
        if isinstance(container, ParameterOrigin):
            # Stores discovered in this body do not describe members already
            # present on entry. Keep the parameter as their caller-side proxy,
            # even after adding known contents (for example via setdefault).
            return {container, *self.contents.get(container, ())}
        if (isinstance(container, CollectionNew)
                and isinstance(container.source, ast.Tuple)
                and all(isinstance(item, ast.Constant) for item in container.source.elts)):
            # Immutable constants cannot acquire references later. Unlike an
            # unknown or mutable container, an empty origin set is conclusive.
            return set()
        return self.contents.get(container) or {container}

    def origins(self, value) -> set:
        if isinstance(value, (ObjectNew, CollectionNew, ParameterOrigin, OpaqueOwner)):
            return {value}
        if isinstance(value, BlockArgument):
            return self.names.get(value.name, set())
        if isinstance(value, (ast.Name, ast.Attribute)) and isinstance(getattr(value, "obj", None), (Class, GenericClass)):
            # Static class references (including classmethod receivers) own no
            # request storage. Do not instantiate type[Class] while refining
            # an already analyzed graph merely to discover that fact.
            return set()
        # Unboxed results are copied values, not aliases of the storage they
        # were read from. Propagating that storage into a receiving object's
        # contents would also promote unrelated members written later.
        if self.builtin_operand(value, {"bool", "int", "float", "NoneType"}):
            return set()
        if isinstance(value, ast.Name):
            if value.id in self.names:
                return self.names[value.id]
        instance = getattr(value, "obj", None)
        if isinstance(instance, Instance) and isinstance(instance.container, Module):
            if self.immutable_literal(instance.static_value):
                return set()
            return {self.external_owner}
        if isinstance(value, ast.Attribute) and isinstance(getattr(value, "obj", None), Function):
            # A saved bound method retains its receiver just as an object field
            # does. Returning the method must not strand an arena-local receiver.
            # A statically selected staticmethod may be overridden by an
            # instance method. Extraction can therefore retain the receiver.
            if (not value.obj.is_static or value.obj.cls is not None
                    and any(not target.is_static for target in self.virtual_targets(value.obj))):
                return self.origins(value.value)
            return set()
        if isinstance(value, FieldLoad):
            result = set()
            for receiver in self.origins(value.attribute.value):
                result.update(self.member_origins(receiver))
            return result
        if isinstance(value, ast.Subscript):
            result = set()
            for container in self.origins(value.value):
                result.update(self.member_origins(container))
            return result
        if isinstance(value, (ast.BoolOp, ast.IfExp)):
            values = value.values if isinstance(value, ast.BoolOp) else (
                value.body,
                value.orelse,
            )
            result = set()
            for item in values:
                result.update(self.origins(item))
            return result
        if isinstance(value, EvaluateOnce):
            return self.origins(value.body)
        if isinstance(value, ast.Call):
            if (isinstance(value.func, ast.Name) and value.func.id == "super"
                    and isinstance(getattr(value.func, "obj", None), Class)):
                return self.names.get("self", set())
            result = {value} if value in self.container_results else set()
            for argument in self.call_returns.get(value, ()):
                result.update(self.origins(argument))
            return result
        if isinstance(value, ast.NamedExpr):
            return self.origins(value.value)
        if isinstance(value, ast.Starred):
            # A known local collection contributes its members. A parameter
            # stands in for unknown members so its caller retains them too.
            result = set()
            for container in self.origins(value.value):
                result.update(self.member_origins(container))
            return result
        return set()

    @staticmethod
    def immutable_builtin_type(value_type, parents=frozenset()) -> bool:
        if value_type in parents:
            return False  # Recursive aliases need an explicit finite proof.
        parents = parents | {value_type}
        return all(isinstance(member, Class) and member.container.scope.is_builtins
                   and (member.generic_name in {"bool", "int", "float", "str", "bytes", "range", "NoneType"}
                        or member.generic_name == "tuple" and all(
                            LifetimeInference.immutable_builtin_type(item, parents) for item in member.generic_types.values()))
                   for member in get_type_members(value_type))

    @staticmethod
    def immutable_literal(value) -> bool:
        # Only module-owned constants use this proof: they need no owner and
        # cannot receive writes. Tuples containing mutable members still do.
        return (isinstance(value, ast.Constant)
                and type(value.value) in {bool, int, float, str, bytes, type(None)}
                or isinstance(value, ast.Tuple)
                and all(LifetimeInference.immutable_literal(item) for item in value.elts))

    def solve_aliases_and_containment(self) -> None:
        changed = True
        while changed:
            changed = False
            for name, value in self.constraints.assignment_constraints:
                known = self.names.setdefault(name, set())
                before = len(known)
                known.update(self.origins(value))
                changed = changed or len(known) != before
            for container, value, _reason in self.constraints.containment_constraints:
                values = self.origins(value)
                for origin in self.origins(container):
                    known = self.contents.setdefault(origin, set())
                    before = len(known)
                    known.update(values)
                    changed = changed or len(known) != before

    @staticmethod
    def rank(boundary: LifetimeBoundary) -> int:
        return {
            LifetimeBoundary.LOCAL: 0,
            LifetimeBoundary.CALLER: 1,
            LifetimeBoundary.EXTERNAL: 2,
        }[boundary]

    def mark(self, origin, boundary: LifetimeBoundary, reason: str) -> bool:
        current, reasons = self.states[origin]
        changed = False
        if self.rank(boundary) > self.rank(current):
            current = boundary
            changed = True
        if reason not in reasons:
            reasons.add(reason)
        self.states[origin] = current, reasons
        return changed

    def solve_boundaries(self) -> None:
        origins = [*self.constraints.allocations, *self.parameters.values(), *self.container_results]
        self.states = {
            origin: (LifetimeBoundary.LOCAL, set())
            for origin in origins
        }
        if self.function.is_generator:
            # A suspended frame retains parameters and locals past this call.
            for origin in origins:
                self.mark(origin, LifetimeBoundary.EXTERNAL, "retained by generator frame")
        for value in self.constraints.returned:
            for origin in self.origins(value):
                self.mark(origin, LifetimeBoundary.CALLER, "returned")
        for operand in self.constraints.external_operands:
            for origin in self.origins(operand):
                self.mark(
                    origin,
                    LifetimeBoundary.EXTERNAL,
                    "potentially retained outside the function",
                )
        for container, value, reason in self.constraints.containment_constraints:
            containers = self.origins(container)
            if containers:
                if any(isinstance(item, ParameterOrigin) for item in containers):
                    for origin in self.origins(value):
                        self.mark(origin, LifetimeBoundary.CALLER, reason)
            else:
                for origin in self.origins(value):
                    self.mark(
                        origin,
                        LifetimeBoundary.EXTERNAL,
                        f"{reason} into unknown receiver",
                    )

        changed = True
        while changed:
            changed = False
            for container, values in self.contents.items():
                boundary, _reasons = self.states[container]
                if boundary is LifetimeBoundary.LOCAL:
                    continue
                for value in values:
                    changed = self.mark(
                        value,
                        boundary,
                        "contained by escaping value",
                    ) or changed

    def reachable_contents(self, origins: set) -> set:
        reachable = set(origins)
        pending = list(origins)
        while pending:
            origin = pending.pop()
            for value in self.contents.get(origin, ()):
                if value not in reachable:
                    reachable.add(value)
                    pending.append(value)
        return reachable

    def returned_parameters(self) -> frozenset[str]:
        if self.function.is_generator:
            return frozenset(self.parameters)
        origins = set()
        for value in self.constraints.returned:
            origins.update(self.origins(value))
        return frozenset(
            origin.name
            for origin in self.reachable_contents(origins)
            if isinstance(origin, ParameterOrigin)
        )

    def parameter_containment(self) -> tuple[tuple[str, str], ...]:
        retained = set()
        for container in self.parameters.values():
            reachable = self.reachable_contents({container})
            for value in reachable:
                if isinstance(value, ParameterOrigin) and value is not container:
                    retained.add((container.name, value.name))
        return tuple(sorted(retained))

    def infer(self) -> FunctionLifetime:
        self.constraints.collect(self.ir)
        self.prepare_call_constraints()
        self.solve_aliases_and_containment()
        self.solve_boundaries()
        allocations = []
        for site, operation in enumerate(self.constraints.allocations, 1):
            boundary, reasons = self.states[operation]
            lifetime = AllocationLifetime(site, operation, boundary, reasons)
            operation.lifetime = lifetime
            allocations.append(lifetime)
        returned_owners = {
            origin for value in self.constraints.returned for origin in self.origins(value)
            if not isinstance(origin, ParameterOrigin)
        }
        return FunctionLifetime(
            allocations=allocations,
            parameters={
                name: self.states[origin][0]
                for name, origin in self.parameters.items()
            },
            parameter_reasons={
                name: frozenset(self.states[origin][1])
                for name, origin in self.parameters.items()
            },
            returned_parameters=self.returned_parameters(),
            external_parameters=frozenset(
                name
                for name, origin in self.parameters.items()
                if self.states[origin][0] is LifetimeBoundary.EXTERNAL
            ),
            parameter_containment=self.parameter_containment(),
            call_dependencies=tuple(self.call_dependencies.items()),
            contained_return_parameters=frozenset(
                origin.name for origin in self.reachable_contents(returned_owners)
                if isinstance(origin, ParameterOrigin)
            ),
            external_member_parameters=frozenset(
                name for name, origin in self.parameters.items()
                if self.external_owner in self.reachable_contents({origin})
            ),
            returns_external=any(
                self.external_owner in self.reachable_contents(self.origins(value))
                for value in self.constraints.returned
            ),
        )


def infer_lifetimes(
    function: Function,
    ir: FunctionIR,
    reached_functions: set[Function] | None = None,
) -> FunctionLifetime:
    return LifetimeInference(function, ir, reached_functions).infer()


def outward_summary_key(summary: FunctionLifetime) -> tuple:
    """Return only the facts that can change a caller's summary."""
    return (
        summary.returned_parameters,
        summary.external_parameters,
        summary.parameter_containment,
        summary.contained_return_parameters,
        summary.external_member_parameters,
        summary.returns_external,
    )


def refine_lifetimes(entry_point: Function) -> None:
    """Resolve dispatch and call summaries after reachability is complete."""
    def function_key(function: Function) -> tuple[str, str, str]:
        return (
            function.container.name,
            function.cls.name if function.cls is not None else "",
            function.name,
        )

    # External declarations can be virtual/protocol targets too. They supply
    # immutable lifetime contracts instead of summaries to refine.
    reached = {value for value in entry_point.compilation_objects if isinstance(value, Function)}
    functions = sorted(
        (
            value for value in reached
            if value.ir is not None
            and value.ir.lifetime is not None
        ),
        key=function_key,
    )
    changed = set()
    for function in functions:
        previous = outward_summary_key(function.ir.lifetime)
        function.ir.lifetime = infer_lifetimes(function, function.ir, reached)
        if outward_summary_key(function.ir.lifetime) != previous:
            changed.add(function)

    callers = {function: set() for function in functions}
    for caller in functions:
        for callee, _consumed in caller.ir.lifetime.call_dependencies:
            if callee in callers:
                callers[callee].add(caller)

    stale = {
        function
        for function in functions
        if any(
            callee in callers
            and consumed != outward_summary_key(callee.ir.lifetime)
            for callee, consumed in function.ir.lifetime.call_dependencies
        )
    }
    stale.update(
        caller
        for callee in changed
        for caller in callers[callee]
    )
    pending = deque(sorted(stale, key=function_key))
    queued = set(stale)
    while pending:
        function = pending.popleft()
        queued.remove(function)
        previous = outward_summary_key(function.ir.lifetime)
        function.ir.lifetime = infer_lifetimes(function, function.ir, reached)
        if outward_summary_key(function.ir.lifetime) == previous:
            continue
        for caller in sorted(callers[function], key=function_key):
            if caller not in queued:
                queued.add(caller)
                pending.append(caller)
