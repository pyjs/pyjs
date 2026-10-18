"""Typed control-flow IR constructed during closed-world inference."""

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pyjs.numeric import ArrayFormat, NumericFormat

from .analyzer import (
    BUILTINS,
    DependencyError,
    InferenceVisitor,
    LocalScope,
    analyzed_value_type,
    body_can_fall_through,
    conditional_value_type,
    context_exit_can_suppress,
    literal_iterable_is_nonempty,
    runtime_class_dependency,
    should_analyze_target_body,
)
from .diagnostics import DiagnosticCode
from .objects import Attribute as AnalyzedAttribute
from .objects import Call as AnalyzedCall
from .objects import (
    CallableClass,
    Class,
    Function,
    Instance,
    TypedDictClass,
    UnionType,
)
from .objects import Dict as AnalyzedDict
from .objects import List as AnalyzedList
from .objects import Name as AnalyzedName
from .objects import Set as AnalyzedSet
from .objects import Tuple as AnalyzedTuple
from .representation import ValueRepresentation
from .type_relations import is_builtin_class, merge_conditional_types
from .value_representation import (
    analyzed_representation,
    analyzed_value_object,
    merged_representation,
    mixed_array_formats,
    mixed_numeric_formats,
    representations_conflict,
    set_analyzed_representation,
)

if TYPE_CHECKING:
    from .lifetime import FunctionLifetime


class Block(ast.stmt):
    _fields = ("arguments", "body")

    def __init__(self, name: str, arguments=(), exception_target=None):
        self.name = name
        self.arguments = list(arguments)
        self.body = []
        self.exception_target = exception_target

    @property
    def terminated(self) -> bool:
        return bool(self.body) and isinstance(self.body[-1], Terminator)


class BlockArgument(ast.expr):
    _fields = ()

    def __init__(self, name: str, value_type, obj):
        self.name = name
        self.value_type = value_type
        self.obj = obj


class Lambda(ast.Lambda):
    # The result expression is already in the return block. Traversals must
    # see its dependencies once, without treating its CFG as the outer body.
    _fields = ("args", "blocks")

    def __init__(self, args, body, ir, scope):
        self.args = args
        self.body = body
        self.ir = ir
        self.blocks = ir.blocks
        self.scope = scope


class Comprehension(ast.expr):
    """Bind source once; a generator body receives its eagerly made iterator."""

    _fields = ("source", "function")

    def __init__(self, source, function):
        self.source = source
        self.function = function
        self.obj = function.obj.return_type


class Terminator(ast.stmt):
    pass


class External(ast.stmt):
    _fields = ()


class Branch(Terminator):
    _fields = ("test",)

    def __init__(self, test, true: str, false: str):
        self.test = test
        self.true = true
        self.false = false


class Jump(Terminator):
    _fields = ("arguments",)

    def __init__(self, target: str, arguments=()):
        self.target = target
        self.arguments = list(arguments)


class Return(Terminator):
    _fields = ("value",)

    def __init__(self, value):
        self.value = value


class Suspend(Terminator):
    _fields = ("value",)

    def __init__(self, value, resume: str):
        self.value = value
        self.resume = resume


class GeneratorInput(ast.expr):
    """The value received after suspension; ordinary advancement supplies None."""

    _fields = ()

    def __init__(self, source, *, discard=False):
        self.obj = analyzed_value_type(source)
        self.representation = analyzed_representation(source)
        self.discard = discard
        ast.copy_location(self, source)
        # Receiving conversions can retain protocols and source/view relations.
        # Keep them on the resumed input, not the outgoing value or a discarded
        # Yield node, for both statement and nested-expression suspension.
        for name in ("conversion_methods", "conversion_protocols", "conversion_views"):
            if hasattr(source, name):
                setattr(self, name, getattr(source, name))


class Raise(Terminator):
    _fields = ("exception",)

    def __init__(self, exception):
        self.exception = exception


class IteratorCreate(ast.stmt):
    _fields = ("iterable",)

    def __init__(self, name: str, iterable, runtime_methods=(), *, acquired=False):
        self.name = name
        self.iterable = iterable
        self.runtime_methods = runtime_methods
        # Generator expressions acquire their outer source in the caller;
        # their suspended body binds that handle without calling __iter__ again.
        self.acquired = acquired


class IteratorNext(Terminator):
    _fields = ("target",)

    def __init__(
        self,
        iterator: str,
        target,
        body: str,
        exhausted: str,
    ):
        self.iterator = iterator
        self.target = target
        self.body = body
        self.exhausted = exhausted


class ExceptionRaise(Terminator):
    """Raise one statically known exception through the active error edge."""

    _fields = ("message", "exception", "cause")

    def __init__(self, value_type: Class | None, message, *, reraised=False,
                 exception=None, append_trace=False, cause=None):
        self.value_type = value_type
        self.message = message
        self.reraised = reraised
        self.exception = exception
        self.append_trace = append_trace
        self.cause = cause


class ExceptionDispatch(Terminator):
    """Route the active exception to the first compatible handler."""

    _fields = ()

    def __init__(self, handlers, unmatched: str | None):
        self.handlers = tuple(handlers)
        self.unmatched = unmatched


class ExceptionCatch(ast.stmt):
    """Save the dispatched exception independently, then mark it handled."""

    _fields = ("target",)

    def __init__(self, target=None):
        self.target = target


class ContextExitCall(AnalyzedCall):
    """Invoke ``__exit__`` with either empty or active exception details."""

    _fields = (*AnalyzedCall._fields, "exception")
    _field_types = {**AnalyzedCall._field_types, "exception": ast.expr | None}

    def __init__(self, method: Function, receiver: ast.expr, *, exceptional: bool):
        super().__init__(
            method.return_type,
            func=AnalyzedAttribute(
                method,
                value=receiver,
                attr=method.name,
                ctx=ast.Load(),
            ),
            args=[],
            keywords=[],
        )
        self.exceptional = exceptional
        self.exception = None


class ObjectNew(ast.expr):
    """Allocate and initialize one application or native-declared object."""

    _fields = ("call",)

    def __init__(self, call: AnalyzedCall, value_type: Class):
        self.call = call
        self.value_type = value_type
        self.obj = analyzed_value_object(call)
        self.representation = analyzed_representation(call)
        self.lifetime = None


class CollectionNew(ast.expr):
    """Allocate a builtin collection without choosing its runtime layout."""

    _fields = ("source",)

    def __init__(
        self,
        source: AnalyzedList | AnalyzedTuple | AnalyzedDict | AnalyzedSet,
    ):
        self.source = source
        self.value_type = source.obj
        self.obj = source.obj
        self.representation = analyzed_representation(source)
        self.lifetime = None


class FieldLoad(ast.expr):
    """Read a typed object field without choosing an address representation."""

    _fields = ("attribute",)

    def __init__(self, attribute: AnalyzedAttribute):
        self.attribute = attribute
        self.obj = attribute.obj


class FieldStore(ast.stmt):
    """Write a typed object field without choosing a write-barrier strategy."""

    _fields = ("target", "value")

    def __init__(self, target: AnalyzedAttribute, value: ast.expr):
        self.target = target
        self.value = value


class ListAppend(ast.expr):
    """Append to a typed list without choosing its storage implementation."""

    _fields = ("call",)

    def __init__(self, call: AnalyzedCall):
        self.call = call
        self.obj = analyzed_value_object(call)


class IRLoweringTransformer(ast.NodeTransformer):
    """Replace analyzed expressions with target-neutral memory operations."""

    def visit_Lambda(self, node):
        # Its independent CFG was lowered during lambda-body analysis.
        return node

    def visit_Comprehension(self, node):
        # The outer source executes in this expression; only the independent
        # loop CFG is already lowered. Never revisit that deferred body here.
        node.source = self.visit(node.source)
        return node

    @staticmethod
    def is_instance_field(attribute: AnalyzedAttribute) -> bool:
        receiver = analyzed_value_object(attribute.value)
        # A value-producing expression can carry its result type directly,
        # unlike a local Instance binding. A returned type[T] still denotes a
        # class object, not an instance with that class's field layout.
        receiver_type = receiver.cls if isinstance(receiver, Instance) else receiver
        if isinstance(receiver_type, (Class, UnionType)) and any(
            is_builtin_class(member, "type") for member in (
                receiver_type.types if isinstance(receiver_type, UnionType) else (receiver_type,)
            )
        ):
            return False
        instance_result = isinstance(attribute.value, ObjectNew) or (
            isinstance(attribute.value, (AnalyzedCall, ast.IfExp, ast.Subscript))
            and isinstance(receiver, (Class, UnionType))
        )
        return (
            isinstance(attribute.obj, Instance)
            and (isinstance(receiver, Instance) or instance_result)
            and not getattr(attribute, "property_getters", ())
            and not getattr(attribute, "property_setters", ())
        )

    def visit_Call(self, node):
        call = self.generic_visit(node)
        if not isinstance(call, AnalyzedCall):
            return call
        target = analyzed_value_object(call.func)
        if isinstance(target, Class) and not getattr(
            target.py_obj,
            "__dict__",
            {},
        ).get("__builtin__", False):
            # super() selects an inherited implementation for the existing
            # receiver; it does not construct an instance of the base class.
            if isinstance(call.func, ast.Name) and call.func.id == "super":
                return call
            return ObjectNew(call, target)
        if (
            isinstance(target, Function)
            and target.name == "append"
            and target.cls is not None
            and target.cls.container.scope.is_builtins
            and target.cls.generic_name == "list"
        ):
            return ListAppend(call)
        return call

    def visit_List(self, node):
        value = self.generic_visit(node)
        if isinstance(value, AnalyzedList) and isinstance(value.ctx, ast.Load):
            return CollectionNew(value)
        return value

    def visit_Tuple(self, node):
        value = self.generic_visit(node)
        if isinstance(value, AnalyzedTuple) and isinstance(value.ctx, ast.Load):
            return CollectionNew(value)
        return value

    def visit_Dict(self, node):
        value = self.generic_visit(node)
        return CollectionNew(value) if isinstance(value, AnalyzedDict) else value

    def visit_Set(self, node):
        value = self.generic_visit(node)
        return CollectionNew(value) if isinstance(value, AnalyzedSet) else value

    def visit_Attribute(self, node):
        attribute = self.generic_visit(node)
        if (
            isinstance(attribute, AnalyzedAttribute)
            and isinstance(attribute.ctx, ast.Load)
            and self.is_instance_field(attribute)
        ):
            return FieldLoad(attribute)
        return attribute

    def visit_Assign(self, node):
        node.value = self.visit(node.value)
        for index, target in enumerate(node.targets):
            if isinstance(target, AnalyzedAttribute):
                target.value = self.visit(target.value)
            else:
                node.targets[index] = self.visit(target)
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], AnalyzedAttribute)
            and self.is_instance_field(node.targets[0])
        ):
            return FieldStore(node.targets[0], node.value)
        return node

    def visit_AnnAssign(self, node):
        if node.value is not None:
            node.value = self.visit(node.value)
        if isinstance(node.target, AnalyzedAttribute):
            node.target.value = self.visit(node.target.value)
        else:
            node.target = self.visit(node.target)
        if (
            node.value is not None
            and isinstance(node.target, AnalyzedAttribute)
            and self.is_instance_field(node.target)
        ):
            return FieldStore(node.target, node.value)
        return node


@dataclass
class LoopTargets:
    continue_: str
    break_: str


@dataclass(frozen=True)
class CleanupRegion:
    body: tuple[ast.stmt, ...]
    exception_target: str | None
    loop_depth: int


@dataclass
class FunctionIR:
    blocks: list[Block | External] = field(default_factory=list)
    current: Block | None = None
    loops: list[LoopTargets] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    cleanups: list[CleanupRegion] = field(default_factory=list)
    names: dict[str, int] = field(default_factory=dict)
    reserved_names: set[str] = field(default_factory=set)
    lifetime: FunctionLifetime | None = None

    def new_block(self, base: str) -> Block:
        count = self.names.get(base, 0) + 1
        self.names[base] = count
        name = base if count == 1 else f"{base}_{count}"
        exception_target = self.exceptions[-1] if self.exceptions else None
        return Block(name, exception_target=exception_target)

    def new_name(self, base: str) -> str:
        count = self.names.get(base, 0) + 1
        name = base if count == 1 else f"{base}_{count}"
        while name in self.reserved_names:
            count += 1
            name = f"{base}_{count}"
        self.names[base] = count
        self.reserved_names.add(name)
        return name

    def enter(self, block: Block) -> None:
        if block not in self.blocks:
            self.blocks.append(block)
        self.current = block

    def emit(self, instruction: ast.stmt) -> None:
        if self.current is not None and not self.current.terminated:
            self.current.body.append(instruction)

    def terminate(self, terminator: Terminator) -> None:
        if self.current is not None and not self.current.terminated:
            self.current.body.append(terminator)


@dataclass(frozen=True)
class FieldIR:
    """One instance field without a target-specific offset or descriptor."""

    name: str
    value_type: Class | UnionType
    representation: ValueRepresentation | None = None

    @property
    def numeric_format(self):
        return self.representation.numeric if self.representation is not None else None

    @property
    def array_format(self):
        return self.representation.array if self.representation is not None else None


@dataclass(frozen=True)
class ClassIR:
    """A reachable Python class before a backend chooses its object layout."""

    value_type: Class
    base: Class | None
    fields: tuple[FieldIR, ...]
    constructor: Function | None
    frozen: bool


@dataclass(frozen=True)
class ProgramIR:
    """The deterministic reachable type and function graph for one root."""

    entry_point: Function
    classes: tuple[ClassIR, ...]
    functions: tuple[Function, ...]


class IRValidationError(ValueError):
    """A typed IR graph violates the shared backend contract."""


def validate_program_ir(program: ProgramIR) -> None:
    """Validate target-neutral structure before a backend chooses lowering."""

    def validate_storage(
        owner: str,
        value_type: Class | UnionType,
        numeric: NumericFormat | None,
        array: ArrayFormat | None,
    ) -> None:
        if numeric is not None and array is not None:
            raise IRValidationError(f"{owner} has two storage formats")
        if numeric is not None:
            expected = "int" if numeric.kind == "integer" else "float"
            if not isinstance(value_type, Class) or value_type.generic_name != expected:
                raise IRValidationError(
                    f"{owner} has {numeric.kind} storage for "
                    f"{value_type.to_annotation_str()}"
                )
        if array is None:
            return
        if not isinstance(value_type, Class) or value_type.generic_name != "list":
            raise IRValidationError(
                f"{owner} has static-array storage for {value_type.to_annotation_str()}"
            )
        item_type = value_type.generic_types["V"]
        validate_storage(
            f"{owner} item",
            item_type,
            array.item_numeric,
            array.item_array,
        )

    def validate_representation(
        owner: str,
        value_type: Class | UnionType,
        representation: ValueRepresentation | None,
    ) -> None:
        if representation is None:
            return
        validate_storage(
            owner,
            value_type,
            representation.numeric,
            representation.array,
        )
        if representation.numeric is not None:
            return
        if representation.array is not None:
            if representation.arguments:
                assert isinstance(value_type, Class)
                validate_representation(
                    f"{owner} item",
                    value_type.generic_types["V"],
                    representation.arguments[0],
                )
            return
        if representation.kind == "record":
            if not isinstance(value_type, TypedDictClass):
                raise IRValidationError(
                    f"{owner} has a record representation for a non-record type"
                )
            fields = dict(representation.fields)
            if fields.keys() != value_type.annotations.keys():
                raise IRValidationError(
                    f"{owner} record representation has different fields"
                )
            for name in value_type.annotations:
                validate_representation(
                    f"{owner} field {name}",
                    value_type.field_type(name),
                    fields[name],
                )
            return
        if isinstance(value_type, UnionType):
            if representation.kind != "union":
                raise IRValidationError(f"{owner} union has a non-union representation")
            members = tuple(value_type.types)
            if len(representation.arguments) != len(members):
                raise IRValidationError(
                    f"{owner} representation has the wrong number of members"
                )
            if representations_conflict(
                zip(members, representation.arguments, strict=True)
            ):
                raise IRValidationError(
                    f"{owner} union has indistinguishable represented members"
                )
        elif isinstance(value_type, Class):
            if representation.kind == "union":
                raise IRValidationError(
                    f"{owner} has a union representation for a non-union type"
                )
            members = tuple((value_type.generic_types or {}).values())
        else:
            members = ()
        if representation.arguments:
            if len(representation.arguments) != len(members):
                raise IRValidationError(
                    f"{owner} representation has the wrong number of members"
                )
            for index, (member, child) in enumerate(
                zip(members, representation.arguments, strict=True)
            ):
                validate_representation(f"{owner} member {index}", member, child)
        if representation.parameters is not None:
            if not isinstance(value_type, CallableClass):
                raise IRValidationError(
                    f"{owner} has callable parameter representation on a non-callable"
                )
            parameter_types = value_type.parameter_types or ()
            if len(representation.parameters) != len(parameter_types):
                raise IRValidationError(
                    f"{owner} callable representation has the wrong arity"
                )
            for index, (parameter_type, parameter_representation) in enumerate(
                zip(
                    parameter_types,
                    representation.parameters,
                    strict=True,
                )
            ):
                validate_representation(
                    f"{owner} parameter {index}",
                    parameter_type,
                    parameter_representation,
                )
        if representation.result is not None:
            if not isinstance(value_type, CallableClass):
                raise IRValidationError(
                    f"{owner} has callable result representation on a non-callable"
                )
            validate_representation(
                f"{owner} result",
                value_type.return_type,
                representation.result,
            )

    functions = set(program.functions)
    classes = {layout.value_type: layout for layout in program.classes}
    if program.entry_point not in functions:
        raise IRValidationError("the entry point is absent from ProgramIR")

    for layout in program.classes:
        for layout_field in layout.fields:
            validate_representation(
                f"{layout.value_type.name}.{layout_field.name}",
                layout_field.value_type,
                layout_field.representation,
            )

    bodies = []
    for function in program.functions:
        parameters = [*function.params, *function.kwonlyargs]
        if function.vararg is not None:
            parameters.append(function.vararg)
        if function.kwarg is not None:
            parameters.append(function.kwarg)
        for parameter in parameters:
            validate_representation(
                f"{function.name} parameter {parameter.arg}",
                parameter.annotation.obj,
                getattr(parameter, "representation", None),
            )
        validate_representation(
            f"{function.name} return",
            function.return_type,
            function.return_representation,
        )
        for name, value in function.scope.names.items():
            if isinstance(value, Instance) and value.container is function:
                validate_representation(
                    f"{function.name} local {name}",
                    value.cls,
                    value.representation,
                )
        bodies.append((function.name, function.ir))
        if function.ir is not None:
            for block in function.ir.blocks:
                for node in ast.walk(block):
                    if not isinstance(node, Lambda):
                        continue
                    owner = f"{function.name}.lambda"
                    for value_type, representation in zip(
                        node.obj.parameter_types, node.obj.parameter_representations, strict=True,
                    ):
                        validate_representation(f"{owner} parameter", value_type, representation)
                    validate_representation(f"{owner} return", node.obj.return_type, node.obj.return_representation)
                    bodies.append((owner, node.ir))

    for owner, ir in bodies:
        if ir is None:
            raise IRValidationError(f"{owner} has no FunctionIR")
        external = [block for block in ir.blocks if isinstance(block, External)]
        blocks = [block for block in ir.blocks if isinstance(block, Block)]
        if external:
            if len(external) != 1 or len(ir.blocks) != 1:
                raise IRValidationError(
                    f"external function {owner} has ordinary blocks"
                )
            continue
        if len(blocks) != len(ir.blocks) or not blocks:
            raise IRValidationError(f"function {owner} has invalid blocks")
        block_map = {block.name: block for block in blocks}
        if len(block_map) != len(blocks):
            raise IRValidationError(f"function {owner} repeats a block name")

        for block in blocks:
            terminators = [
                index
                for index, statement in enumerate(block.body)
                if isinstance(statement, Terminator)
            ]
            if terminators != [len(block.body) - 1]:
                raise IRValidationError(
                    f"block {owner}.{block.name} must end once"
                )
            terminator = block.body[-1]
            targets = (
                (terminator.true, terminator.false)
                if isinstance(terminator, Branch)
                else (terminator.target,)
                if isinstance(terminator, Jump)
                else (terminator.body, terminator.exhausted)
                if isinstance(terminator, IteratorNext)
                else (terminator.resume,)
                if isinstance(terminator, Suspend)
                else tuple(target for _types, target in terminator.handlers)
                + ((terminator.unmatched,) if terminator.unmatched else ())
                if isinstance(terminator, ExceptionDispatch)
                else ()
            )
            if block.exception_target is not None:
                target = block_map.get(block.exception_target)
                if target is None or target.arguments:
                    raise IRValidationError(
                        f"block {owner}.{block.name} has an invalid exception target"
                    )
            missing = [target for target in targets if target not in block_map]
            if missing:
                raise IRValidationError(
                    f"block {owner}.{block.name} targets missing "
                    f"block {missing[0]}"
                )
            if isinstance(terminator, Jump):
                expected = len(block_map[terminator.target].arguments)
                if len(terminator.arguments) != expected:
                    raise IRValidationError(
                        f"jump to {owner}.{terminator.target} passes "
                        f"{len(terminator.arguments)} arguments; expected {expected}"
                    )
            elif isinstance(terminator, (Branch, IteratorNext, ExceptionDispatch, Suspend)):
                for target in targets:
                    expected = len(block_map[target].arguments)
                    if expected:
                        raise IRValidationError(
                            f"{type(terminator).__name__} edge to "
                            f"{owner}.{target} cannot provide "
                            f"{expected} arguments"
                        )

            for statement in block.body:
                for node in ast.walk(statement):
                    if isinstance(node, ObjectNew):
                        if node.value_type not in classes:
                            raise IRValidationError(
                                f"{owner} constructs an absent class "
                                f"{node.value_type.name}"
                            )
                        constructor = classes[node.value_type].constructor
                        if (
                            isinstance(constructor, Function)
                            and constructor.ir is not None
                            and constructor not in functions
                        ):
                            raise IRValidationError(
                                f"{owner} references absent constructor "
                                f"{node.value_type.name}.__init__"
                            )
                    if isinstance(node, ast.Call):
                        target = analyzed_value_object(node.func)
                        if (
                            isinstance(target, Function)
                            and target.ir is not None
                            and target not in functions
                        ):
                            raise IRValidationError(
                                f"{owner} calls absent function {target.name}"
                            )


def build_program_ir(entry_point: Function) -> ProgramIR:
    """Preserve reachable layouts after inference and tree shaking finish."""

    def object_key(value) -> tuple[str, str, str, int]:
        py_obj = getattr(value.py_obj, "__func__", value.py_obj)
        return (
            getattr(py_obj, "__module__", ""),
            getattr(py_obj, "__qualname__", value.name),
            value.name,
            getattr(value, "lineno", 0) or 0,
        )

    reached = entry_point.compilation_objects
    value_types = set()

    def retain_layout(value_type):
        if isinstance(value_type, UnionType):
            for member in value_type.types:
                retain_layout(member)
        elif isinstance(value_type, Class) and value_type not in value_types:
            value_types.add(value_type)
            retain_layout(value_type.super)
            for member in (value_type.generic_types or {}).values():
                retain_layout(member)
            for field_value in value_type._self.attrs.values():
                if isinstance(field_value, Instance):
                    retain_layout(field_value.type)

    for value in reached:
        if isinstance(value, Class):
            retain_layout(value)
        elif isinstance(value, Function):
            # Host-provided records need layouts even when compiled code never
            # constructs them. Type dependencies do not retain constructor bodies.
            for parameter in (*value.params, *value.kwonlyargs):
                retain_layout(parameter.annotation.obj)
            for parameter in (value.vararg, value.kwarg):
                if parameter is not None:
                    retain_layout(parameter.annotation.obj)
            retain_layout(value.return_type)
            # Empty local containers can still require element layouts in
            # outlined helpers, without reaching a constructor or method body.
            for local in value.scope.names.values():
                if isinstance(local, Instance):
                    retain_layout(local.type)
    classes = []
    for value_type in sorted(
        value_types,
        key=object_key,
    ):
        constructor = value_type.find_attrs("__init__")
        fields = tuple(
            FieldIR(
                name,
                field.type,
                field.representation,
            )
            for name, field in value_type._self.attrs.items()
            if isinstance(field, Instance)
        )
        classes.append(
            ClassIR(
                value_type=value_type,
                base=value_type.super,
                fields=fields,
                constructor=(
                    constructor if isinstance(constructor, Function) else None
                ),
                frozen=getattr(value_type, "is_frozen_dataclass", False),
            )
        )
    functions = tuple(
        sorted(
            (
                value
                for value in reached
                if isinstance(value, Function) and value.ir is not None
            ),
            key=object_key,
        )
    )
    return ProgramIR(entry_point, tuple(classes), functions)


class IRInferenceVisitor(InferenceVisitor):
    """Run ordinary inference while constructing a typed control-flow graph."""

    lower_exception_regions = False
    lower_exception_objects = False
    lower_generator_suspensions = False

    def visit_Attribute(self, node):
        result = super().visit_Attribute(node)
        if not self.supports_exception_causes and node.attr in {
                "__cause__", "__suppress_context__"}:
            if any(getter.cls is self.exception_base_class()
                   for getter in getattr(result, "property_getters", ())):
                self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "exception chaining state is not implemented by this backend")
        return result

    def analyze_isinstance(self, call):
        # Native builtin declarations are shared by LLVM, JVM and WASM. Keep
        # the ordinary single-target contract unless a backend opts into more.
        return call.standard()

    def analyze_issubclass(self, call):
        self.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                  "issubclass is not implemented by this backend")

    def analyze_tuple_concat(self, call):
        self.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                  "tuple concatenation is not implemented by this backend")

    def analyze_binary_operation(self, node, left, right):
        # A shared builtin declaration must not advertise an object-erased
        # result to backends which have not implemented tuple concatenation.
        if isinstance(node.op, ast.Add) and all(
                is_builtin_class(analyzed_value_type(value), "tuple") for value in (left, right)):
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "tuple concatenation is not implemented by this backend")
        return super().analyze_binary_operation(node, left, right)

    def __init__(self, func, scope=None):
        super().__init__(func, scope)
        self.ir = func.ir
        self.caught_exception = None
        self.lowering = IRLoweringTransformer()
        self.expression_depth = 0

    def narrow(self, value_node, value_type):
        narrowed = super().narrow(value_node, value_type)
        if isinstance(value_node, ast.Name):
            value = narrowed.scope.lookup(value_node.id)
            if getattr(getattr(value, "narrowed_from", None), "native_exception_binding", False):
                value.native_exception_binding = True
        return narrowed

    def visit(self, node):
        expression = isinstance(node, ast.expr)
        self.expression_depth += expression
        try:
            analyzed = super().visit(node)
        finally:
            self.expression_depth -= expression
        if (
            self.ir is not None
            and isinstance(node, ast.stmt)
            and not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.If,
                    ast.For,
                    ast.While,
                    ast.Try,
                    ast.With,
                    ast.Assert,
                ),
            )
        ):
            self.emit_statement(analyzed)
        return analyzed

    def child_visitor(self, scope):
        visitor = super().child_visitor(scope)
        visitor.caught_exception = self.caught_exception
        visitor.in_exception_handler = self.in_exception_handler
        visitor.ir = self.ir
        visitor.expression_depth = self.expression_depth
        return visitor

    def comprehension_visitor(self):
        visitor = super().comprehension_visitor()
        # Operands run in the comprehension loop, never during its creation.
        # Keep conditional operands expression-shaped until loop lowering.
        visitor.expression_depth = 1
        return visitor

    def analyze_lambda_body(self, node):
        self.assignment_scope = self.scope
        self.ir = FunctionIR()
        self.ir.reserved_names.update(
            value.id if isinstance(value, ast.Name) else value.arg
            for value in ast.walk(node) if isinstance(value, (ast.Name, ast.arg))
        )
        self.ir.enter(self.ir.new_block("entry"))
        body = self.visit(node.body)
        self.ir.terminate(Return(self.lowering.visit(body)))
        result = Lambda(node.args, body, self.ir, self.scope)
        result.local_names = set(self.assignment_scope.names)
        return result

    def capture_exception(self, node, target=None):
        # The hidden binding survives reassignment of an authored `except as`
        # name so nested handlers cannot overwrite a pending bare reraise.
        name = self.ir.new_name("__caught_exception")
        value_type = self.exception_base_class() if target is None else target.obj.cls
        value = value_type(name, self.scope, self.func)
        value.native_exception_binding = True
        self.scope.add(value)
        saved = AnalyzedName(value, ctx=ast.Load())
        catch = ExceptionCatch(AnalyzedName(value, ctx=ast.Store()))
        ast.copy_location(catch, node)
        self.ir.emit(catch)
        if target is not None:
            self.ir.emit(ast.copy_location(ast.Assign(targets=[target], value=saved), node))
        return saved

    def visit_Try(self, node):
        if not self.lower_exception_regions:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "native IR exception handlers are not implemented",
                help=(
                    "Move exception handling outside this backend until it "
                    "implements shared IR exception regions."
                ),
            )
        analyzed_handlers = []
        handler_types = []
        handler_visitors = []
        handler_blocks = []
        for handler in node.handlers:
            handler_type, exception_type = self.analyze_exception_handler_type(handler)
            types = tuple(
                value.obj
                for value in (
                    handler_type.elts
                    if isinstance(handler_type, ast.Tuple)
                    else (handler_type,)
                )
                if value is not None
            )
            handler_types.append(types)
            visitor = self.child_visitor(LocalScope(self.scope))
            target = None
            if handler.name is not None:
                try:
                    self.scope.lookup(handler.name)
                except NameError:
                    pass
                else:
                    self.fail(handler, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "native exception bindings cannot shadow an existing local",
                              help="Use a fresh handler name until native unbound-local tracking is supported.")
                value = exception_type(
                    handler.name,
                    visitor.scope,
                    self.func,
                )
                value.native_exception_binding = True
                visitor.scope.add(value)
                target = AnalyzedName(value, ctx=ast.Store())
                ast.copy_location(target, handler)
            handler_visitors.append(visitor)
            handler_blocks.append(self.ir.new_block("except"))
            analyzed_handlers.append((handler_type, exception_type, handler, target))

        done_block = self.ir.new_block("try_done")
        final_done_block = (
            self.ir.new_block("finally_done") if node.finalbody else done_block
        )
        exceptional_final_block = (
            self.ir.new_block("finally_exception") if node.finalbody else None
        )
        orelse_block = self.ir.new_block("try_else") if node.orelse else done_block
        dispatch_block = self.ir.new_block("exception_dispatch")
        outer_exception = dispatch_block.exception_target
        cleanup = (
            CleanupRegion(
                tuple(node.finalbody),
                outer_exception,
                len(self.ir.loops),
            )
            if node.finalbody
            else None
        )
        if exceptional_final_block is not None:
            for block in handler_blocks:
                block.exception_target = exceptional_final_block.name
            if orelse_block is not done_block:
                orelse_block.exception_target = exceptional_final_block.name
        self.ir.exceptions.append(dispatch_block.name)
        body_block = self.ir.new_block("try_body")
        self.ir.exceptions.pop()
        self.ir.terminate(Jump(body_block.name))

        self.ir.enter(dispatch_block)
        self.ir.terminate(
            ExceptionDispatch(
                zip(
                    handler_types,
                    (block.name for block in handler_blocks),
                    strict=True,
                ),
                (
                    exceptional_final_block.name
                    if exceptional_final_block is not None
                    else outer_exception
                ),
            )
        )

        body_visitor = self.child_visitor(LocalScope(self.scope))
        self.ir.exceptions.append(dispatch_block.name)
        if cleanup is not None:
            self.ir.cleanups.append(cleanup)
        self.ir.enter(body_block)
        analyzed_body = body_visitor.visit_body(node.body)
        handler_entry = self.exception_entry(node.body, analyzed_body)
        for visitor in handler_visitors:
            # Handler bindings were allocated with the dispatch blocks, before
            # the body was typed. Only their outer flow state changes here.
            visitor.scope.parent = handler_entry.scope
        body_falls_through = not self.ir.current.terminated
        self.ir.terminate(Jump(orelse_block.name))
        if cleanup is not None:
            self.ir.cleanups.pop()
        self.ir.exceptions.pop()

        if node.orelse:
            self.ir.enter(orelse_block)
            orelse_entry = body_visitor.exception_entry(node.body, analyzed_body)
            orelse_visitor = self.child_visitor(LocalScope(orelse_entry.scope))
            if exceptional_final_block is not None:
                self.ir.exceptions.append(exceptional_final_block.name)
            if cleanup is not None:
                self.ir.cleanups.append(cleanup)
            analyzed_orelse = orelse_visitor.visit_body(node.orelse)
            if cleanup is not None:
                self.ir.cleanups.pop()
            if exceptional_final_block is not None:
                self.ir.exceptions.pop()
            orelse_falls_through = not self.ir.current.terminated
            self.ir.terminate(Jump(done_block.name))
            successful_visitor = orelse_visitor
        else:
            analyzed_orelse = []
            orelse_falls_through = body_falls_through
            successful_visitor = body_visitor

        completed_visitors = []
        if body_falls_through and orelse_falls_through:
            completed_visitors.append(successful_visitor)
        handlers = []
        for block, visitor, (
            handler_type,
            _exception_type,
            handler,
            target,
        ) in zip(
            handler_blocks,
            handler_visitors,
            analyzed_handlers,
            strict=True,
        ):
            visitor.in_exception_handler = True
            self.ir.enter(block)
            visitor.caught_exception = visitor.capture_exception(handler, target)
            if exceptional_final_block is not None:
                self.ir.exceptions.append(exceptional_final_block.name)
            if cleanup is not None:
                self.ir.cleanups.append(cleanup)
            body = visitor.visit_body(handler.body)
            if cleanup is not None:
                self.ir.cleanups.pop()
            if exceptional_final_block is not None:
                self.ir.exceptions.pop()
            if handler.name is not None:
                # Python deletes the handler binding on exit; it must not be
                # treated as a definitely assigned local after branch merging.
                visitor.scope.names.pop(handler.name, None)
            if not self.ir.current.terminated:
                completed_visitors.append(visitor)
            self.ir.terminate(Jump(done_block.name))
            handlers.append(
                ast.ExceptHandler(
                    type=handler_type,
                    name=handler.name,
                    body=body,
                )
            )

        exceptional_entry = self.exception_entry(
            [*node.body, *node.orelse, *node.handlers],
            [*analyzed_body, *analyzed_orelse, *handlers],
        ) if node.finalbody else None
        if completed_visitors:
            self.ir.enter(done_block)
            self.merge_branch_declarations(node, *completed_visitors)
        analyzed_finalbody = []
        if node.finalbody:
            final_visitor = None
            final_falls_through = False
            if completed_visitors:
                self.ir.enter(done_block)
                normal_final = self.ir.new_block("finally_body")
                self.ir.terminate(Jump(normal_final.name))
                self.ir.enter(normal_final)
                # Normal completion can include the same body/else/handler
                # writes as exception completion. Direct scope-name merging
                # does not include every nested flow proof from those writes.
                final_visitor = self.child_visitor(LocalScope(exceptional_entry.scope))
                analyzed_finalbody = final_visitor.visit_body(node.finalbody)
                final_falls_through = not self.ir.current.terminated
                self.ir.terminate(Jump(final_done_block.name))

            assert exceptional_final_block is not None
            self.ir.enter(exceptional_final_block)
            exceptional_visitor = self.child_visitor(LocalScope(exceptional_entry.scope))
            exceptional_visitor.caught_exception = exceptional_visitor.capture_exception(node)
            exceptional_visitor.in_exception_handler = True
            exceptional_finalbody = exceptional_visitor.visit_body(node.finalbody)
            if not analyzed_finalbody:
                analyzed_finalbody = exceptional_finalbody
            reraised = ExceptionRaise(
                None, None, reraised=True,
                exception=exceptional_visitor.caught_exception,
            )
            ast.copy_location(reraised, node)
            self.ir.terminate(reraised)

            if final_falls_through:
                assert final_visitor is not None
                self.ir.enter(final_done_block)
                self.merge_branch_declarations(node, final_visitor)
        return ast.Try(
            body=analyzed_body,
            handlers=handlers,
            orelse=analyzed_orelse,
            finalbody=analyzed_finalbody,
            lineno=node.lineno,
        )

    def visit_With(self, node):
        if not self.lower_exception_regions:
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "context-manager regions are not implemented for this backend")
        item = node.items[0]
        context, target, enter, exit_, declares_target = self.analyze_with_item(
            item
        )
        for method in (enter, exit_):
            if not method.is_analyzed:
                raise DependencyError(method)
        context_type = analyzed_value_type(context)
        assert isinstance(context_type, Class)

        manager_name = self.ir.new_name("__with_manager")
        manager_obj = context_type(manager_name, self.scope, self.func)
        manager_obj.representation = analyzed_representation(context)
        self.scope.add(manager_obj)
        manager_load = AnalyzedName(manager_obj, ctx=ast.Load())
        manager_store = AnalyzedName(manager_obj, ctx=ast.Store())
        self.emit_statement(ast.copy_location(ast.Assign(targets=[manager_store], value=context), node))

        enter_call = self.call_node(
            item.context_expr,
            enter.return_type,
            func=AnalyzedAttribute(
                enter,
                value=manager_load,
                attr=enter.name,
                ctx=ast.Load(),
            ),
            args=[],
            keywords=[],
        )
        set_analyzed_representation(enter_call, enter.return_representation)
        if target is None or (
            isinstance(enter.return_type, Class)
            and enter.return_type.generic_name == "NoneType"
        ):
            self.emit_statement(ast.Expr(value=enter_call))
            entered_value = ast.Constant(value=None)
        else:
            entered_name = self.ir.new_name("__with_entered")
            entered = enter.return_type(entered_name, self.scope, self.func)
            entered.representation = enter.return_representation
            self.scope.add(entered)
            self.emit_statement(ast.copy_location(ast.Assign(
                targets=[AnalyzedName(entered, ctx=ast.Store())], value=enter_call,
            ), node))
            entered_value = ast.Name(id=entered_name, ctx=ast.Load())

        normal_exit = ast.Expr(
            value=ContextExitCall(exit_, manager_load, exceptional=False)
        )
        ast.copy_location(normal_exit, item.context_expr)
        exceptional_exit = ContextExitCall(
            exit_,
            manager_load,
            exceptional=True,
        )
        ast.copy_location(exceptional_exit, item.context_expr)

        exception_block = self.ir.new_block("with_exception")
        outer_exception = exception_block.exception_target
        done_block = self.ir.new_block("with_done")
        normal_exit_block = self.ir.new_block("with_exit")
        can_suppress = context_exit_can_suppress(exit_)
        suppressed_block = self.ir.new_block("with_suppressed") if can_suppress else None
        reraise_block = self.ir.new_block("with_reraise")
        self.ir.exceptions.append(exception_block.name)
        body_block = self.ir.new_block("with_body")
        self.ir.exceptions.pop()
        cleanup = CleanupRegion(
            (normal_exit,),
            outer_exception,
            len(self.ir.loops),
        )
        self.ir.terminate(Jump(body_block.name))

        self.ir.enter(body_block)
        self.ir.exceptions.append(exception_block.name)
        self.ir.cleanups.append(cleanup)
        if target is not None:
            # __enter__ must succeed before installing cleanup, but assignment
            # to the as-target belongs inside the protected region: an index
            # or property setter can itself fail and still requires __exit__.
            assignment = ast.Assign(targets=[item.optional_vars], value=entered_value)
            ast.copy_location(assignment, item.context_expr)
            ast.fix_missing_locations(assignment)
            self.visit(assignment)
        if len(node.items) > 1:
            nested = ast.With(
                items=node.items[1:],
                body=node.body,
                type_comment=node.type_comment,
            )
            ast.copy_location(nested, node)
            analyzed_body = [self.visit(nested)]
        else:
            analyzed_body = self.visit_body(node.body)
        self.ir.cleanups.pop()
        self.ir.exceptions.pop()
        body_falls_through = not self.ir.current.terminated
        self.ir.terminate(Jump(normal_exit_block.name))

        if body_falls_through:
            self.ir.enter(normal_exit_block)
            self.visit(normal_exit)
            self.ir.terminate(Jump(done_block.name))

        self.ir.enter(exception_block)
        exceptional_exit.exception = self.capture_exception(node)
        if not can_suppress:
            self.ir.emit(ast.Expr(value=exceptional_exit))
            self.ir.terminate(Jump(reraise_block.name))
        else:
            assert suppressed_block is not None
            self.ir.terminate(
                Branch(
                    self.lowering.visit(self.truth_test(node, exceptional_exit)),
                    suppressed_block.name,
                    reraise_block.name,
                )
            )

        if suppressed_block is not None:
            self.ir.enter(suppressed_block)
            self.ir.terminate(Jump(done_block.name))
        self.ir.enter(reraise_block)
        reraised = ExceptionRaise(
            None, None, reraised=True, exception=exceptional_exit.exception,
        )
        ast.copy_location(reraised, node)
        self.ir.terminate(reraised)
        if body_falls_through or can_suppress:
            self.ir.enter(done_block)

        analyzed = ast.With(
            items=[ast.withitem(context_expr=context, optional_vars=target)],
            body=analyzed_body,
            type_comment=None,
            lineno=item.context_expr.lineno,
        )
        analyzed.enter_method = enter
        analyzed.exit_method = exit_
        analyzed.declares_target = declares_target
        return analyzed

    def visit_ContextExitCall(self, node):
        return node

    def visit_Break(self, node):
        # Unlike tree inference, IR executes pending cleanup here. Capture its
        # exit proof only when terminate_abrupt reaches the actual loop jump.
        return node

    def terminate_abrupt(
        self,
        terminator: Return | Jump,
        *,
        loop_depth: int | None = None,
    ) -> None:
        """Route a return or loop exit through every enclosing cleanup."""
        if not self.ir.cleanups or (
            loop_depth is not None
            and self.ir.cleanups[-1].loop_depth < loop_depth
        ):
            if (loop_depth is not None and isinstance(terminator, Jump)
                    and terminator.target == self.ir.loops[loop_depth - 1].break_):
                InferenceVisitor.visit_Break(self, ast.Break())
            self.ir.terminate(terminator)
            return

        cleanup = self.ir.cleanups.pop()
        block = self.ir.new_block("finally_abrupt")
        block.exception_target = cleanup.exception_target
        continuation = terminator
        arguments = []
        if isinstance(terminator, Return) and terminator.value is not None:
            value_type = analyzed_value_type(terminator.value)
            if isinstance(value_type, Class) and value_type.generic_name == "NoneType":
                # A None-returning call still runs before cleanup, but has no
                # value to transport through a block argument or native slot.
                self.ir.emit(ast.Expr(value=terminator.value))
                continuation = Return(None)
            else:
                name = self.ir.new_name("finally_return")
                value_obj = value_type(name, self.scope, self.func)
                argument = BlockArgument(name, value_type, value_obj)
                set_analyzed_representation(
                    argument,
                    analyzed_representation(terminator.value),
                )
                block.arguments.append(argument)
                arguments.append(terminator.value)
                continuation = Return(argument)
            continuation.runtime_methods = getattr(terminator, "runtime_methods", ())
            continuation.runtime_protocols = getattr(terminator, "runtime_protocols", ())

        self.ir.terminate(Jump(block.name, arguments))
        self.ir.enter(block)
        visitor = self.child_visitor(LocalScope(self.scope))
        protected_exceptions = self.ir.exceptions
        # A return may cross additional try/except regions with no finally.
        # New blocks inside cleanup must inherit its enclosing handler, not
        # whichever protected region happened to be innermost at the return.
        self.ir.exceptions = [cleanup.exception_target] if cleanup.exception_target else []
        try:
            analyzed_cleanup = visitor.visit_body(cleanup.body)
            if not self.ir.current.terminated:
                if loop_depth is not None:
                    visitor = visitor.exception_entry(cleanup.body, analyzed_cleanup)
                visitor.terminate_abrupt(continuation, loop_depth=loop_depth)
        finally:
            self.ir.exceptions = protected_exceptions
            self.ir.cleanups.append(cleanup)

    def emit_statement(self, statement) -> None:
        statements = statement if isinstance(statement, list) else [statement]
        for item in statements:
            item = self.lowering.visit(item)
            if isinstance(item, ast.Return):
                result = Return(item.value)
                result.runtime_methods = getattr(item, "runtime_methods", ())
                result.runtime_protocols = getattr(item, "runtime_protocols", ())
                self.terminate_abrupt(result)
            elif isinstance(item, ast.Raise):
                if not self.lower_exception_regions:
                    self.ir.terminate(Raise(item.exc))
                    continue
                if item.exc is None or (
                    isinstance(item.exc, AnalyzedName)
                    and getattr(item.exc.obj, "native_exception_binding", False)
                ):
                    raised = ExceptionRaise(
                        None, None, reraised=True,
                        exception=item.exc if item.exc is not None else self.caught_exception,
                        append_trace=item.exc is not None,
                        cause=item.cause,
                    )
                    ast.copy_location(raised, item)
                    self.ir.terminate(raised)
                    continue
                value_type = analyzed_value_type(item.exc)
                if not isinstance(value_type, Class):
                    self.fail(
                        item,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        "native IR raise requires one concrete exception type",
                    )
                if self.lower_exception_objects and not (
                    isinstance(item.exc, AnalyzedName) and isinstance(item.exc.obj, Class)
                ):
                    raised = ExceptionRaise(value_type, None, exception=item.exc,
                                            cause=item.cause)
                    self.ir.terminate(ast.copy_location(raised, item))
                    continue
                message = None
                exception_call = (
                    item.exc.call if isinstance(item.exc, ObjectNew) else item.exc
                )
                if isinstance(exception_call, AnalyzedCall):
                    if not isinstance(exception_call.func.obj, Class):
                        self.fail(item, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                  "native raise requires a constructor or a caught exception")
                    if exception_call.keywords:
                        self.fail(item, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                  "native exceptions require a positional message")
                    if len(exception_call.args) > 1:
                        self.fail(
                            item,
                            DiagnosticCode.UNSUPPORTED_SYNTAX,
                            "native exceptions take at most one message argument",
                        )
                    if exception_call.args:
                        # The enclosing raise statement has already passed
                        # through the lowering transformer. Visiting the
                        # argument again would wrap collection literals in a
                        # second CollectionNew allocation.
                        message = exception_call.args[0]
                elif not isinstance(item.exc.obj, Class):
                    self.fail(item, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "native raise requires a constructor or a caught exception")
                raised = self.make_exception_raise(value_type, message, source=exception_call)
                ast.copy_location(raised, item)
                self.ir.terminate(raised)
            elif isinstance(item, ast.Break):
                self.terminate_abrupt(
                    Jump(self.ir.loops[-1].break_),
                    loop_depth=len(self.ir.loops),
                )
            elif isinstance(item, ast.Continue):
                self.terminate_abrupt(
                    Jump(self.ir.loops[-1].continue_),
                    loop_depth=len(self.ir.loops),
                )
            elif not isinstance(item, ast.Pass):
                self.ir.emit(item)

    def make_exception_raise(self, value_type, message, *, source=None):
        """Let backends retain implicit payload consumers before reachability."""
        raised = ExceptionRaise(value_type, message)
        raised.runtime_methods = getattr(source, "runtime_methods", ())
        raised.runtime_protocols = getattr(source, "runtime_protocols", ())
        return raised

    def visit_Assert(self, node):
        if not self.lower_exception_regions:
            assertion = super().visit_Assert(node)
            self.emit_statement(assertion)
            return assertion
        test = self.visit(node.test)
        passed = self.ir.new_block("assert_passed")
        failed = self.ir.new_block("assert_failed")
        self.ir.terminate(Branch(
            self.lowering.visit(self.truth_test(node.test, test)),
            passed.name, failed.name,
        ))
        # Visiting an expression can emit control flow, so even analysis of
        # the message must occur on the failure edge, not before the assert.
        self.ir.enter(failed)
        message = self.visit(node.msg) if node.msg is not None else None
        assertion_type = BUILTINS.search("AssertionError")
        assert isinstance(assertion_type, Class)
        raised = self.make_exception_raise(assertion_type, self.lowering.visit(message) if message is not None else None)
        self.ir.terminate(ast.copy_location(raised, node))
        self.ir.enter(passed)
        assertion = ast.Assert(test=test, msg=message)
        assertion.runtime_dependency = runtime_class_dependency(assertion_type, self.module)
        return assertion

    def visit_FunctionDef(self, node):
        if not should_analyze_target_body(self.func):
            result = super().visit_FunctionDef(node)
            self.func.ir = FunctionIR(blocks=[External()])
            self.ir = self.func.ir
            return result
        if self.func.is_generator and not self.lower_generator_suspensions:
            # Reject before resolving Iterator/Generator annotations: a backend
            # without suspension lowering may not model those runtime types.
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "generator suspension is not implemented by this backend")
        self.func.ir = FunctionIR()
        self.ir = self.func.ir
        self.ir.reserved_names.update(
            item.id if isinstance(item, ast.Name) else item.arg
            for item in ast.walk(node) if isinstance(item, (ast.Name, ast.arg))
        )
        self.ir.enter(self.ir.new_block("entry"))
        result = super().visit_FunctionDef(node)
        if self.ir.current is not None and not self.ir.current.terminated:
            self.ir.terminate(Return(ast.Constant(value=None)))
        # Lifetime inference imports these IR node types and requires the
        # completed graph, so load it only at this finalization boundary.
        from .lifetime import infer_lifetimes

        self.ir.lifetime = infer_lifetimes(self.func, self.ir)
        return result

    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)

    def visit_If(self, node):
        test = self.truth_test(node.test, self.visit(node.test))
        body_visitor = self.branch_visitor(node.test, True)
        orelse_visitor = self.branch_visitor(node.test, False)
        body_block = self.ir.new_block("if_true")
        done_block = self.ir.new_block("if_done")
        orelse_block = self.ir.new_block("if_false") if node.orelse else done_block
        self.ir.terminate(
            Branch(
                self.lowering.visit(test),
                body_block.name,
                orelse_block.name,
            )
        )

        self.ir.enter(body_block)
        body = body_visitor.visit_body(node.body)
        self.ir.terminate(Jump(done_block.name))

        if node.orelse:
            self.ir.enter(orelse_block)
            orelse = orelse_visitor.visit_body(node.orelse)
            self.ir.terminate(Jump(done_block.name))
        else:
            orelse = []

        self.ir.enter(done_block)
        self.merge_branch_declarations(node, body_visitor, orelse_visitor)
        return ast.If(test=test, body=body, orelse=orelse)

    def visit_IfExp(self, node):
        # A nested conditional must stay at its operand's evaluation point.
        # Hoisting its blocks here runs it ahead of earlier call arguments or
        # out of a short-circuit expression. Backends lower this expression
        # locally, as they already do for boolean operators.
        if self.expression_depth > 1:
            return super().visit_IfExp(node)
        test = self.truth_test(node.test, self.visit(node.test))
        body_visitor = self.narrow_for_condition(node.test, True)
        orelse_visitor = self.narrow_for_condition(node.test, False)
        body_block = self.ir.new_block("conditional_true")
        orelse_block = self.ir.new_block("conditional_false")
        done_block = self.ir.new_block("conditional_done")
        self.ir.terminate(
            Branch(
                self.lowering.visit(test),
                body_block.name,
                orelse_block.name,
            )
        )

        self.ir.enter(body_block)
        body = body_visitor.visit_contextual_expression(
            node.body, self.contextual_types.get(node),
            expected_representation=self.contextual_representations.get(node),
        )
        body_exit = self.ir.current

        self.ir.enter(orelse_block)
        orelse = orelse_visitor.visit_contextual_expression(
            node.orelse, self.contextual_types.get(node),
            expected_representation=self.contextual_representations.get(node),
        )
        orelse_exit = self.ir.current

        self.prepare_conditional_values(body, orelse)
        body_type = analyzed_value_type(body)
        orelse_type = conditional_value_type(orelse, body_type)
        body_type = conditional_value_type(body, orelse_type)
        branch_representations = (
            (body_type, analyzed_representation(body)),
            (orelse_type, analyzed_representation(orelse)),
        )
        if (
            representations_conflict(branch_representations)
            and not mixed_numeric_formats((body, orelse))
            and not mixed_array_formats((body, orelse))
        ):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "Conditional branches use incompatible nested representations",
                help=(
                    "Use one represented type for each runtime value type, or "
                    "add an explicit conversion."
                ),
            )
        result_type = merge_conditional_types(body_type, orelse_type)
        result_format = self.conditional_numeric_format(node, body, orelse)
        self.validate_conditional_array_formats(node, body, orelse)
        if result_format is not None:
            body = self.normalize_numeric_value(body, result_format)
            orelse = self.normalize_numeric_value(orelse, result_format)
        representation = merged_representation(
            result_type,
            branch_representations,
        )
        self.ir.enter(body_exit)
        self.ir.terminate(Jump(done_block.name, [self.lowering.visit(body)]))
        self.ir.enter(orelse_exit)
        self.ir.terminate(Jump(done_block.name, [self.lowering.visit(orelse)]))
        name = self.ir.new_name("conditional")
        value_obj = result_type(name, self.scope, self.func)
        argument = BlockArgument(name, result_type, value_obj)
        set_analyzed_representation(argument, representation)
        done_block.arguments.append(argument)
        self.ir.enter(done_block)
        return argument

    def loop_entry(self, node):
        """Inference view valid before iterations and after any backedges."""
        return self

    def visit_While(self, node):
        test_block = self.ir.new_block("while_test")
        body_block = self.ir.new_block("while_body")
        done_block = self.ir.new_block("while_done")
        orelse_block = self.ir.new_block("while_else") if node.orelse else done_block
        self.ir.terminate(Jump(test_block.name))

        self.ir.enter(test_block)
        entry = self.loop_entry(node)
        test = entry.truth_test(node.test, entry.visit(node.test))
        body_visitor = entry.branch_visitor(node.test, True)
        zero_visitor = entry.branch_visitor(node.test, False)
        break_exits = []
        body_visitor.loop_break_collectors = [
            *self.loop_break_collectors,
            (body_visitor.scope, break_exits),
        ]
        self.ir.terminate(
            Branch(
                self.lowering.visit(test),
                body_block.name,
                orelse_block.name,
            )
        )

        self.ir.loops.append(LoopTargets(test_block.name, done_block.name))
        self.ir.enter(body_block)
        body = body_visitor.visit_body(node.body)
        self.ir.terminate(Jump(test_block.name))
        self.ir.loops.pop()

        normal_visitors = []
        if body_can_fall_through(body, break_exits=True):
            normal_visitors.append(body_visitor)
        if not isinstance(node.test, ast.Constant) or not node.test.value:
            normal_visitors.append(zero_visitor)
        # Exhaustion may follow continue paths whose weakened observations live
        # only in inherited scopes, outside the declaration merge below. Seed
        # the join with the backedge-safe view so they cannot reappear afterward.
        normal_visitor = self.child_visitor(LocalScope(self.scope)).loop_entry(node)
        if normal_visitors:
            normal_visitor.merge_branch_declarations(node, *normal_visitors)
        if node.orelse:
            self.ir.enter(orelse_block)
            # Else continues the exhaustion state; another child scope would
            # hide inherited declarations from the final scope-name merge.
            orelse = normal_visitor.visit_body(node.orelse)
            self.ir.terminate(Jump(done_block.name))
        else:
            orelse = []
        self.ir.enter(done_block)
        final_visitors = [*break_exits]
        if normal_visitors and body_can_fall_through(orelse, loop_control_exits=True):
            final_visitors.insert(0, normal_visitor)
        if final_visitors:
            self.merge_branch_declarations(node, *final_visitors)
        return ast.While(test=test, body=body, orelse=orelse, lineno=node.lineno)

    def visit_For(self, node):
        iterable = self.mapping_keys_iterable(self.visit(node.iter))
        protocol = self.require_iterable(node.iter, iterable)
        # Match ordinary inference: a yielded item is a body-only proof, not
        # evidence that the loop executes. Preserve the entry and break paths.
        # The iterable runs once in the original scope, before any backedge.
        entry = self.loop_entry(node)
        body_visitor = entry.child_visitor(LocalScope(entry.scope))
        zero_visitor = self.child_visitor(LocalScope(self.scope))
        break_exits = []
        body_visitor.loop_break_collectors = [
            *self.loop_break_collectors,
            (body_visitor.scope, break_exits),
        ]
        target = body_visitor.bind_loop_target(
            node.target,
            protocol.item_type,
            protocol.item_representation,
        )
        iterator = self.ir.new_name("iterator")
        self.ir.emit(IteratorCreate(iterator, self.lowering.visit(iterable), protocol.methods))

        next_block = self.ir.new_block("for_next")
        body_block = self.ir.new_block("for_body")
        done_block = self.ir.new_block("for_done")
        orelse_block = self.ir.new_block("for_else") if node.orelse else done_block
        self.ir.terminate(Jump(next_block.name))

        self.ir.enter(next_block)
        self.ir.terminate(
            ast.copy_location(IteratorNext(
                iterator,
                target,
                body_block.name,
                orelse_block.name,
            ), node)
        )

        self.ir.loops.append(LoopTargets(next_block.name, done_block.name))
        self.ir.enter(body_block)
        body = body_visitor.visit_body(node.body)
        self.ir.terminate(Jump(next_block.name))
        self.ir.loops.pop()

        normal_visitors = []
        if body_can_fall_through(body, break_exits=True):
            normal_visitors.append(body_visitor)
        if not literal_iterable_is_nonempty(node.iter):
            normal_visitors.append(zero_visitor)
        # As for while: exhaustion must retain weakened backedge observations
        # even when a nested else/continue leaves no directly merged declaration.
        normal_visitor = self.child_visitor(LocalScope(self.scope)).loop_entry(node)
        if normal_visitors:
            normal_visitor.merge_branch_declarations(node, *normal_visitors)
        if node.orelse:
            self.ir.enter(orelse_block)
            # Keep target/body declarations alongside writes made by else.
            orelse = normal_visitor.visit_body(node.orelse)
            self.ir.terminate(Jump(done_block.name))
        else:
            orelse = []
        self.ir.enter(done_block)
        final_visitors = [*break_exits]
        if normal_visitors and body_can_fall_through(orelse, loop_control_exits=True):
            final_visitors.insert(0, normal_visitor)
        if final_visitors:
            self.merge_branch_declarations(node, *final_visitors)
        result = ast.For(
            target=target,
            iter=iterable,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )
        result.runtime_methods = protocol.methods
        return result
