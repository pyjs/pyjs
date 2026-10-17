"""Emit a statically checked WGSL subset from shared Python definitions.

Shared source prevents textual drift, not numeric differences between Python's
f64 arithmetic and WGSL's f32 arithmetic.
"""

import annotationlib
import ast
import dataclasses
import inspect
import math
import textwrap
import typing

from pyjs.analysis.objects import Class, Function, Instance, Module, UnionType
from pyjs.analysis.source import analyze_source
from pyjs.analysis.value_representation import (
    analyzed_array_format,
    analyzed_numeric_format,
)
from pyjs.decorators import get_wgsl_decoration
from pyjs.numeric import (
    NumericFormat,
    array_format,
    array_item,
    numeric_format,
)

from .analysis import WGSL_ENVIRONMENT

BINARY_OPS = {
    "__add__": "+",
    "__sub__": "-",
    "__mul__": "*",
    "__truediv__": "/",
    "__mod__": "%",
    "__lshift__": "<<",
    "__rshift__": ">>",
    "__and__": "&",
    "__or__": "|",
    "__xor__": "^",
    "__lt__": "<",
    "__le__": "<=",
    "__gt__": ">",
    "__ge__": ">=",
    "__eq__": "==",
    "__ne__": "!=",
}

UNARY_DUNDERS = {
    "__abs__": "abs({})",
    "__neg__": "-({})",
    "__pos__": "({})",
    "__invert__": "~({})",
}

REFLECTED_OPS = {
    "__radd__": "+",
    "__rsub__": "-",
    "__rmul__": "*",
    "__rtruediv__": "/",
}

COMPARE_OPS = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Eq: "==",
    ast.NotEq: "!=",
}
COMPARISON_SYMBOLS = frozenset(COMPARE_OPS.values())

AST_BINOPS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.BitAnd: "&",
    ast.BitOr: "|",
    ast.BitXor: "^",
}

GENERATED = "a helper this backend generates"

# Undo runtime calls for operations that are native WGSL syntax.
TEMPLATES = {
    "get_list_item": "{0}[{1}]",
    "fmod": "({0} % {1})",
}


def _runtime_name(name: str) -> str:
    """Recover a helper name from its collision-safe call-graph alias."""
    if name.startswith("$"):
        base = name[1:].rstrip("0123456789")
        if base in TEMPLATES:
            return base
    return name


BUILTINS = {
    "abs": "abs", "min": "min", "max": "max",
    "sqrt": "sqrt", "sin": "sin", "cos": "cos", "tan": "tan",
    "exp": "exp", "log": "log", "floor": "floor", "ceil": "ceil",
    "atan2": "atan2", "pow": "pow", "asin": "asin", "acos": "acos",
    "atan": "atan", "sign": "sign", "trunc": "trunc",
}

SCALARS = {"float": "f32", "int": "i32", "bool": "bool"}

WGSL_SCALARS = {"f32", "i32", "u32", "bool"}
INTEGERS = {"i32", "u32"}
VECTOR_TYPES = {"vec2f", "vec3f", "vec4f"}
INTEGER_RANGES = {
    "i32": (-(2**31), 2**31 - 1),
    "u32": (0, 2**32 - 1),
}

WGSL_NUMERIC_FORMATS = {
    NumericFormat("integer", 32, True, domain="wgsl"): "i32",
    NumericFormat("integer", 32, False, domain="wgsl"): "u32",
    NumericFormat("float", 32, domain="wgsl"): "f32",
}

# Emitting these names would shadow WGSL's conversions.
RESERVED_CASTS = {"u32", "i32", "f32", "bool"}


class WGSLUnsupported(Exception):
    def __init__(self, message: str, node: ast.AST | None = None) -> None:
        where = (
            f" (line {node.lineno})"
            if node is not None and hasattr(node, "lineno")
            else ""
        )
        super().__init__(f"{message}{where}")


class WGSLEmitter:
    """Emit WGSL from the analyzer's resolved types and call graph."""

    def __init__(self) -> None:
        self.structs: dict[str, type] = {}
        self.reached: list[object] = []
        self.names: dict[str, object] = {}
        self.validated_structs: set[type] = set()
        self.equality_structs: set[str] = set()
        self.hoisted: dict[str, str] = {}
        self.array_lengths: dict[str, int] = {}
        self.array_types: dict[str, str] = {}
        self.return_type = "void"
        self.parameter_names: set[str] = set()
        self.scope = None
        self.indent = 1
        self.temporary_index = 0
        self.local_identifiers: dict[str, str] = {}

    def function(self, root) -> str:
        node = root.node
        self.validate_function_shape(root, node)
        self.scope = root.scope
        self.reached = []
        self.array_lengths = {}
        self.array_types = {}
        self.indent = 1
        self.temporary_index = 0
        self.local_identifiers = {}
        name = self.claim(root.py_func, node)
        annotations = annotationlib.get_annotations(
            root.py_func,
            format=annotationlib.Format.VALUE,
        )
        params = []
        arguments = [*node.args.posonlyargs, *node.args.args]
        for arg, parameter in zip(arguments, root.params, strict=True):
            annotation = annotations.get(arg.arg)
            resolved = (
                self.resolve_annotation(annotation, node)
                if annotation is not None
                else self.resolve(
                    parameter.annotation.obj,
                    node,
                    numeric=analyzed_numeric_format(parameter),
                )
            )
            params.append((arg.arg, resolved))
            if resolved.startswith("array<"):
                self.array_lengths[arg.arg] = (
                    self.annotation_array_length(annotation)
                    if annotation is not None
                    else analyzed_array_format(parameter).length
                )
                self.array_types[arg.arg] = resolved
        self.parameter_names = {name for name, _ in params}
        returns = (
            "void"
            if root.return_type.name == "NoneType"
            else self.resolve_annotation(annotations["return"], node)
            if "return" in annotations
            else self.resolve(
                root.return_type,
                node,
                numeric=root.return_numeric_format,
            )
        )
        self.return_type = returns
        body = self.hoist(node.body) + self.block(node.body)
        signature = ", ".join(f"{name}: {type_}" for name, type_ in params)
        head = f"fn {name}({signature})"
        head += " {" if returns == "void" else f" -> {returns} {{"
        return "\n".join([head, *body, "}"])

    @staticmethod
    def validate_function_shape(root: Function, node: ast.FunctionDef) -> None:
        args = node.args
        if root.is_async:
            raise WGSLUnsupported("WGSL functions cannot be async", node)
        if args.vararg is not None or args.kwarg is not None:
            raise WGSLUnsupported("WGSL functions cannot use variadic parameters", node)
        if args.kwonlyargs:
            raise WGSLUnsupported("WGSL functions cannot use keyword-only parameters", node)
        if args.defaults:
            raise WGSLUnsupported("WGSL functions cannot use default arguments", node)

    def hoist(self, body: list[ast.stmt]) -> list[str]:
        """Hoist locals whose Python function scope exceeds a WGSL block."""
        found: dict[str, str] = {}
        tree = ast.Module(body=body, type_ignores=[])

        def walk(stmts: list[ast.stmt], nested: bool) -> None:
            for stmt in stmts:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if nested:
                        found.setdefault(stmt.target.id, self.local_type(stmt.target.id, stmt))
                if isinstance(stmt, ast.For):
                    target = stmt.target
                    name = (
                        target.arg if isinstance(target, ast.arg)
                        else target.id if isinstance(target, ast.Name)
                        else None
                    )
                    if name is not None and any(
                        isinstance(value, ast.Name)
                        and isinstance(value.ctx, ast.Load)
                        and value.id == name
                        and value.lineno > stmt.end_lineno
                        for value in ast.walk(tree)
                    ):
                        found.setdefault(name, self.local_type(name, stmt))
                for field_name in ("body", "orelse", "finalbody"):
                    inner = getattr(stmt, field_name, None)
                    if isinstance(inner, list):
                        walk(inner, True)

        walk(body, False)
        self.hoisted = found
        return [self.line(f"var {self.local_identifier(n)}: {t};") for n, t in found.items()]

    def local_type(self, name: str, node: ast.AST) -> str:
        value = self.scope.names[name]
        return self.resolve(value.cls, node, numeric=analyzed_numeric_format(value))

    def resolve(
        self,
        obj,
        node: ast.AST,
        metadata: tuple[int, ...] = (),
        numeric: NumericFormat | None = None,
    ) -> str:
        if numeric is not None:
            return self.resolve_numeric(numeric, node)
        if isinstance(obj, UnionType):
            raise WGSLUnsupported("WGSL has no union types", node)
        if obj.generic_types:
            if obj.generic_name != "list":
                raise WGSLUnsupported(f"no WGSL type for {obj.generic_name}", node)
            if not metadata:
                raise WGSLUnsupported(
                    "a WGSL array needs a length: annotate it Array[T, N]",
                    node,
                )
            if len(metadata) > 1:
                raise WGSLUnsupported(
                    f"an array has one length, not {len(metadata)}", node
                )
            (length,) = metadata
            if length <= 0:
                raise WGSLUnsupported(
                    f"array length {length}; a WGSL array needs a positive one", node
                )
            (item,) = obj.generic_types.values()
            return f"array<{self.resolve(item, node)}, {length}>"
        if obj.name == "bool":
            return "bool"
        if obj.name in {"int", "float"}:
            replacement = "i32" if obj.name == "int" else "f32"
            raise WGSLUnsupported(
                f"plain Python {obj.name} has no WGSL numeric contract; "
                f"use pyjs.shader.{replacement}",
                node,
            )
        return self.declared(obj.py_obj, node, obj.name)

    def resolve_annotation(self, annotation: object, node: ast.AST | None) -> str:
        while isinstance(annotation, typing.TypeAliasType):
            annotation = annotation.__value__
        if (layout := array_format(annotation)) is not None:
            if layout.domain != "wgsl":
                raise WGSLUnsupported(
                    f"{layout.domain} arrays cannot be used as WGSL arrays; "
                    "use pyjs.shader.Array",
                    node,
                )
            item = array_item(annotation)
            assert item is not None
            return f"array<{self.resolve_annotation(item, node)}, {layout.length}>"
        if typing.get_origin(annotation) is typing.Annotated:
            annotation = typing.get_args(annotation)[0]
        if typing.get_origin(annotation) is list:
            raise WGSLUnsupported(
                "a WGSL array uses pyjs.shader.Array[T, N]",
                node,
            )
        if (representation := numeric_format(annotation)) is not None:
            return self.resolve_numeric(representation, node)
        if annotation is bool:
            return "bool"
        if annotation in {int, float}:
            replacement = "i32" if annotation is int else "f32"
            raise WGSLUnsupported(
                f"plain Python {annotation.__name__} has no WGSL numeric "
                f"contract; use pyjs.shader.{replacement}",
                node,
            )
        return self.declared(annotation, node)

    @staticmethod
    def annotation_array_length(annotation: object) -> int:
        while isinstance(annotation, typing.TypeAliasType):
            annotation = annotation.__value__
        if (layout := array_format(annotation)) is not None:
            return layout.length
        raise AssertionError("a resolved WGSL array must carry its length")

    @staticmethod
    def resolve_numeric(value: NumericFormat, node: ast.AST | None) -> str:
        resolved = WGSL_NUMERIC_FORMATS.get(value)
        if resolved is not None:
            return resolved
        signed = "" if value.signed else "u"
        name = (
            f"{signed}int{value.bits}"
            if value.kind == "integer"
            else f"float{value.bits}"
        )
        if value.domain == "portable":
            replacement = {
                ("integer", 32, True): "i32",
                ("integer", 32, False): "u32",
                ("float", 32, None): "f32",
            }.get((value.kind, value.bits, value.signed))
            help_text = (
                f"use pyjs.shader.{replacement}"
                if replacement is not None
                else "use a WGSL-specific scalar type"
            )
            raise WGSLUnsupported(
                f"portable PyJS {name} cannot be used as a WGSL scalar; " + help_text,
                node,
            )
        raise WGSLUnsupported(
            f"WGSL has no scalar representation for {value.domain} {name}",
            node,
        )

    def claim(self, py: object, node: ast.AST | None, name: str | None = None) -> str:
        """Claim a name in WGSL's single namespace without renaming it."""
        name = name or py.__name__
        if name in RESERVED_CASTS:
            raise WGSLUnsupported(
                f"'{name}' names a WGSL conversion and cannot be emitted as a "
                f"function; mark it @wgsl.native so the backend calls the builtin",
                node,
            )
        holder = self.names.setdefault(name, py)
        if holder is not py:
            raise WGSLUnsupported(
                f"'{name}' is defined twice for one shader: "
                f"{self.describe(holder)} and {self.describe(py)}. "
                f"WGSL has one namespace",
                node,
            )
        return name

    @staticmethod
    def describe(owner: object) -> str:
        if isinstance(owner, str):
            return owner
        return f"{owner.__module__}.{owner.__qualname__}"

    def declared(self, py: object, node: ast.AST | None, shown: str | None = None) -> str:
        if (representation := numeric_format(py)) is not None:
            return self.resolve_numeric(representation, node)
        name = getattr(py, "__name__", str(py))
        if name in SCALARS:
            return SCALARS[name]
        decoration = get_wgsl_decoration(py) if inspect.isclass(py) else None
        if decoration is not None and decoration.kind == "native":
            return name
        if decoration is not None and decoration.kind == "emit":
            self.validate_struct(py, node)
            self.structs.setdefault(self.claim(py, node), py)
            return name
        raise WGSLUnsupported(
            f"no WGSL type for '{shown or name}': mark the class @wgsl to emit a "
            f"struct, or @wgsl.native for a type WGSL already has",
            node,
        )

    def validate_struct(self, cls: type, node: ast.AST | None) -> None:
        if cls in self.validated_structs:
            return
        fields = getattr(cls, "__pyjs_instance_annotations__", {})
        parameters = tuple(inspect.signature(cls).parameters.values())
        if tuple(parameter.name for parameter in parameters) != tuple(fields):
            raise WGSLUnsupported(
                f"@wgsl struct '{cls.__name__}' constructor parameters must "
                "match its annotated fields in order",
                node,
            )
        if any(
            parameter.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD
            or parameter.default is not inspect.Parameter.empty
            for parameter in parameters
        ):
            raise WGSLUnsupported(
                f"@wgsl struct '{cls.__name__}' constructor requires plain "
                "positional parameters without defaults",
                node,
            )
        generated_dataclass_init = (
            dataclasses.is_dataclass(cls)
            and getattr(getattr(cls.__init__, "__code__", None), "co_filename", None)
            == "<string>"
        )
        if generated_dataclass_init:
            if "__post_init__" in cls.__dict__:
                raise WGSLUnsupported(
                    f"@wgsl struct '{cls.__name__}' cannot use __post_init__; "
                    "WGSL construction only assigns its fields",
                    node,
                )
            self.validated_structs.add(cls)
            return
        source = textwrap.dedent(inspect.getsource(cls))
        definition = next(
            statement
            for statement in ast.parse(source).body
            if isinstance(statement, ast.ClassDef)
        )
        initializer = next(
            (
                statement
                for statement in definition.body
                if isinstance(statement, ast.FunctionDef)
                and statement.name == "__init__"
            ),
            None,
        )
        if initializer is None:
            raise WGSLUnsupported(
                f"@wgsl struct '{cls.__name__}' needs a direct field constructor",
                node,
            )
        assignments: list[tuple[str, str]] = []
        for statement in initializer.body:
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                continue
            target = None
            value = None
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                value = statement.value
            elif isinstance(statement, ast.AnnAssign):
                target = statement.target
                value = statement.value
            if not (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and isinstance(value, ast.Name)
            ):
                raise WGSLUnsupported(
                    f"@wgsl struct '{cls.__name__}' constructor must only assign "
                    "each parameter directly to its matching field",
                    node,
                )
            assignments.append((target.attr, value.id))
        if assignments != [(name, name) for name in fields]:
            raise WGSLUnsupported(
                f"@wgsl struct '{cls.__name__}' constructor must assign every "
                "parameter directly to its matching field",
                node,
            )
        self.validated_structs.add(cls)

    def struct_declarations(self) -> list[str]:
        """Declare field dependencies first and preserve positional field order."""
        out: list[str] = []
        declared: set[str] = set()
        active: set[str] = set()

        def declare(name: str) -> None:
            if name in declared:
                return
            if name in active:
                raise WGSLUnsupported(
                    f"@wgsl struct '{name}' is recursively defined; WGSL "
                    "structs cannot contain themselves"
                )
            active.add(name)
            cls = self.structs[name]
            fields: list[tuple[str, str]] = []
            for field_name, annotation in getattr(
                cls, "__pyjs_instance_annotations__", {}
            ).items():
                representation = numeric_format(annotation)
                field_type = (
                    self.resolve_numeric(representation, None)
                    if representation is not None
                    else self.declared(annotation, None)
                )
                fields.append((field_name, field_type))
                if getattr(annotation, "__name__", None) in self.structs:
                    declare(annotation.__name__)
            if not fields:
                raise WGSLUnsupported(
                    f"@wgsl struct '{name}' declares no annotated fields; WGSL has "
                    f"no way to infer them from an __init__ body"
                )
            body = "\n".join(f"  {f}: {t}," for f, t in fields)
            out.append(f"struct {name} {{\n{body}\n}}")
            active.remove(name)
            declared.add(name)

        for name in list(self.structs):
            declare(name)
        return out

    def require_struct_equality(
        self,
        name: str,
        node: ast.AST | None,
    ) -> str:
        cls = self.structs[name]
        params = getattr(cls, "__dataclass_params__", None)
        if params is None or not params.eq:
            raise WGSLUnsupported(
                f"@wgsl struct '{name}' uses Python identity equality; use "
                "@dataclass(eq=True) to opt into value equality",
                node,
            )
        helper = self.claim(GENERATED, node, f"_pyjs_equal_{name}")
        self.equality_structs.add(name)
        return helper

    def equality_value(
        self,
        type_name: str,
        left: str,
        right: str,
        py_class: type,
    ) -> str:
        if type_name in WGSL_SCALARS:
            return f"({left} == {right})"
        if type_name in VECTOR_TYPES:
            if py_class.__eq__ is object.__eq__:
                raise WGSLUnsupported(
                    f"{type_name} uses Python identity equality; define value "
                    "equality before using it in a comparable struct"
                )
            return f"all({left} == {right})"
        if type_name in self.structs:
            helper = self.require_struct_equality(type_name, None)
            return f"{helper}({left}, {right})"
        raise WGSLUnsupported(
            f"WGSL value equality is not implemented for {type_name}"
        )

    def equality_helpers(self) -> list[str]:
        out: list[str] = []
        emitted: set[str] = set()

        def emit(name: str) -> None:
            if name in emitted:
                return
            cls = self.structs[name]
            annotations = getattr(cls, "__pyjs_instance_annotations__", {})
            fields = [field for field in dataclasses.fields(cls) if field.compare]
            comparisons = []
            for field in fields:
                field_type = self.declared(annotations[field.name], None)
                if field_type in self.structs:
                    self.require_struct_equality(field_type, None)
                    emit(field_type)
                comparisons.append(
                    self.equality_value(
                        field_type,
                        f"left.{field.name}",
                        f"right.{field.name}",
                        annotations[field.name],
                    )
                )
            result = " && ".join(comparisons) or "true"
            helper = self.require_struct_equality(name, None)
            out.append(
                f"fn {helper}(left: {name}, right: {name}) -> bool {{\n"
                f"  return {result};\n"
                "}"
            )
            emitted.add(name)

        for name in sorted(self.equality_structs):
            emit(name)
        return out

    def expr(self, node: ast.expr) -> str:
        static = self.static_expression(node)
        if static is not None:
            return self.expr(static)
        if isinstance(node, ast.Constant):
            return self.constant(node)
        if isinstance(node, ast.Name):
            return self.local_identifier(node.id)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return f"-({self.expr(node.operand)})"
            if isinstance(node.op, ast.Not):
                return f"!({self.expr(node.operand)})"
            if isinstance(node.op, ast.Invert):
                if self.operand_type(node.operand) not in INTEGERS:
                    raise WGSLUnsupported("bitwise inversion requires an integer", node)
                return f"~({self.expr(node.operand)})"
            raise WGSLUnsupported("unsupported unary operator", node)
        if isinstance(node, ast.BinOp):
            op = AST_BINOPS.get(type(node.op))
            if op is None:
                raise WGSLUnsupported(
                    f"unsupported operator {type(node.op).__name__}", node
                )
            return self.binary(op, node.left, node.right, node)
        if isinstance(node, ast.BoolOp):
            if any(self.operand_type(value) != "bool" for value in node.values):
                raise WGSLUnsupported(
                    "WGSL boolean operators require bool operands; Python's "
                    "and/or return their operand values",
                    node,
                )
            joiner = " && " if isinstance(node.op, ast.And) else " || "
            return "(" + joiner.join(self.expr(v) for v in node.values) + ")"
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                raise WGSLUnsupported("chained comparisons have no WGSL form", node)
            op = COMPARE_OPS.get(type(node.ops[0]))
            if op is None:
                raise WGSLUnsupported("unsupported comparison", node)
            return self.binary(op, node.left, node.comparators[0], node)
        if isinstance(node, ast.IfExp):
            if not (
                self.eager_safe_conditional_value(node.body)
                and self.eager_safe_conditional_value(node.orelse)
            ):
                raise WGSLUnsupported(
                    "a conditional expression with evaluated branches has no "
                    "lazy WGSL equivalent; use an if statement",
                    node,
                )
            return (f"select({self.expr(node.orelse)}, {self.expr(node.body)}, "
                    f"{self.expr(node.test)})")
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Attribute):
            return f"{self.expr(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                raise WGSLUnsupported("WGSL has no slices", node)
            self.validate_array_index(node.value, node.slice, node)
            return f"{self.expr(node.value)}[{self.expr(node.slice)}]"
        raise WGSLUnsupported(f"unsupported expression {type(node).__name__}", node)

    @staticmethod
    def static_expression(node: ast.expr) -> ast.expr | None:
        obj = getattr(node, "obj", None)
        if not isinstance(obj, Instance) or not isinstance(obj.container, Module):
            return None
        return obj.static_value

    def validate_array_index(
        self,
        value: ast.expr,
        index: ast.expr,
        node: ast.AST,
    ) -> None:
        literal = self.integer_literal(index)
        if literal is None:
            return
        if literal < 0:
            raise WGSLUnsupported(
                "WGSL array indexes cannot use Python's negative-index semantics",
                node,
            )
        if isinstance(value, ast.Name):
            length = self.array_lengths.get(value.id)
            if length is not None and literal >= length:
                raise WGSLUnsupported(
                    f"array index {literal} is outside its length {length}",
                    node,
                )

    @staticmethod
    def eager_safe_conditional_value(node: ast.expr) -> bool:
        if isinstance(node, (ast.Constant, ast.Name)):
            return True
        return isinstance(node, ast.Attribute) and WGSLEmitter.eager_safe_conditional_value(
            node.value
        )

    @staticmethod
    def expression_type_name(node: ast.expr) -> str | None:
        obj = getattr(node, "obj", None)
        cls = getattr(obj, "cls", None)
        if cls is not None:
            return cls.name
        return getattr(obj, "name", None)

    def operand_type(self, node: ast.expr) -> str | None:
        """Return None for an AbstractInt, which adapts to its WGSL context."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, int):
                return None
            if isinstance(node.value, float):
                return "f32"
            return None
        if isinstance(node, ast.UnaryOp):
            return self.operand_type(node.operand)
        representation = analyzed_numeric_format(node)
        if representation is not None:
            return self.resolve_numeric(representation, node)
        name = self.expression_type_name(node)
        return SCALARS.get(name, name)

    @staticmethod
    def expression_python_class(node: ast.expr) -> type | None:
        obj = getattr(node, "obj", None)
        if isinstance(obj, Class):
            return obj.py_obj
        return getattr(getattr(obj, "cls", None), "py_obj", None)

    @staticmethod
    def integer_literal(node: ast.expr) -> int | None:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.UnaryOp):
            value = WGSLEmitter.integer_literal(node.operand)
            if value is not None:
                if isinstance(node.op, ast.USub):
                    return -value
                if isinstance(node.op, ast.UAdd):
                    return value
        return None

    def require_literal_type(
        self,
        literal: ast.expr,
        target: str,
        node: ast.AST,
    ) -> None:
        value = self.integer_literal(literal)
        if value is None:
            return
        if target == "bool":
            raise WGSLUnsupported(
                "an integer literal cannot be used as bool in WGSL", node
            )
        bounds = INTEGER_RANGES.get(target)
        if bounds is not None and not bounds[0] <= value <= bounds[1]:
            raise WGSLUnsupported(
                f"integer literal {value} cannot be represented as {target} in WGSL",
                node,
            )

    def require_value_type(
        self,
        value: ast.expr,
        target: str,
        node: ast.AST,
    ) -> None:
        if self.integer_literal(value) is not None:
            self.require_literal_type(value, target, node)
            return
        actual = self.operand_type(value)
        if actual is not None and actual != target:
            raise WGSLUnsupported(
                f"value is {actual}, but WGSL requires {target}; convert it explicitly",
                node,
            )

    def require_abs_representable(
        self,
        argument: ast.expr,
        operand: str,
        node: ast.AST,
    ) -> None:
        self.require_literal_type(argument, operand, node)
        if operand == "i32" and self.integer_literal(argument) == -(2**31):
            raise WGSLUnsupported(
                "abs(-2147483648) cannot be represented as i32 in WGSL",
                node,
            )

    def binary(self, op: str, left: ast.expr, right: ast.expr, node: ast.AST) -> str:
        lt = self.operand_type(left)
        rt = self.operand_type(right)
        if op in ("<<", ">>"):
            shift = self.integer_literal(right)
            if shift is not None:
                self.require_literal_type(right, "u32", node)
                if shift >= 32:
                    raise WGSLUnsupported(
                        f"shift count {shift}; a WGSL shift literal must be "
                        f"between 0 and 31",
                        node,
                    )
            elif rt != "u32":
                shown = rt or "an untyped expression"
                raise WGSLUnsupported(
                    f"a shift count is u32 in WGSL, not {shown}; write u32(n)",
                    node,
                )
        else:
            if self.integer_literal(left) is not None and rt in WGSL_SCALARS:
                self.require_literal_type(left, rt, node)
            if self.integer_literal(right) is not None and lt in WGSL_SCALARS:
                self.require_literal_type(right, lt, node)
        if lt in WGSL_SCALARS and rt in WGSL_SCALARS and lt != rt:
            raise WGSLUnsupported(
                f"WGSL does not mix {lt} and {rt} in one expression; convert "
                f"one operand explicitly",
                node,
            )
        if op in COMPARISON_SYMBOLS and any(
            value_type is not None and value_type not in WGSL_SCALARS
            for value_type in (lt, rt)
        ):
            return self.value_comparison(op, left, right, node)
        wgsl_result = "bool" if op in COMPARISON_SYMBOLS else lt or rt
        python_result = self.operand_type(node)
        if (
            wgsl_result is not None
            and python_result is not None
            and python_result != wgsl_result
        ):
            raise WGSLUnsupported(
                f"Python operator {op} returns {python_result}, but WGSL "
                f"produces {wgsl_result}; use an explicitly typed operation",
                node,
            )
        return f"({self.expr(left)} {op} {self.expr(right)})"

    def value_comparison(
        self,
        op: str,
        left: ast.expr,
        right: ast.expr,
        node: ast.AST,
    ) -> str:
        if op not in {"==", "!="}:
            raise WGSLUnsupported(
                f"WGSL value type comparisons do not support {op}",
                node,
            )
        left_type = self.operand_type(left)
        right_type = self.operand_type(right)
        if left_type != right_type or left_type is None:
            raise WGSLUnsupported(
                "WGSL value equality requires operands of the same type",
                node,
            )
        if left_type in VECTOR_TYPES:
            classes = (
                self.expression_python_class(left),
                self.expression_python_class(right),
            )
            if any(cls is None or cls.__eq__ is object.__eq__ for cls in classes):
                raise WGSLUnsupported(
                    f"{left_type} uses Python identity equality; define value "
                    "equality before using it in WGSL",
                    node,
                )
            comparison = f"{self.expr(left)} {op} {self.expr(right)}"
            reducer = "all" if op == "==" else "any"
            return f"{reducer}({comparison})"
        if left_type in self.structs:
            helper = self.require_struct_equality(left_type, node)
            comparison = f"{helper}({self.expr(left)}, {self.expr(right)})"
            return comparison if op == "==" else f"!({comparison})"
        raise WGSLUnsupported(
            f"WGSL value equality is not implemented for {left_type}",
            node,
        )

    def constant(self, node: ast.Constant) -> str:
        v = node.value
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            # AbstractInt adapts to i32 or u32 at its use site.
            return str(v)
        if isinstance(v, float):
            if not math.isfinite(v):
                raise WGSLUnsupported(
                    "WGSL has no non-finite floating-point literals",
                    node,
                )
            if abs(v) > 3.4028234663852886e38:
                raise WGSLUnsupported(
                    f"floating-point literal {v!r} cannot be represented as f32",
                    node,
                )
            # WGSL distinguishes `1` from `1.0` rather than promoting it.
            text = repr(v)
            return text if ("." in text or "e" in text or "E" in text) else text + ".0"
        raise WGSLUnsupported(f"cannot express constant {v!r} in WGSL", node)

    def call(self, node: ast.Call) -> str:
        func = node.func
        # Analyzer dunder rewrites retain the resolved operand types.
        if isinstance(func, ast.Attribute) and func.attr in BINARY_OPS:
            if len(node.args) != 1:
                raise WGSLUnsupported(
                    f"{func.attr} with {len(node.args)} arguments", node
                )
            return self.binary(BINARY_OPS[func.attr], func.value, node.args[0], node)
        if isinstance(func, ast.Attribute) and func.attr in REFLECTED_OPS:
            if len(node.args) != 1:
                raise WGSLUnsupported(
                    f"{func.attr} with {len(node.args)} arguments", node
                )
            return self.binary(REFLECTED_OPS[func.attr], node.args[0], func.value, node)
        if isinstance(func, ast.Attribute) and func.attr in UNARY_DUNDERS:
            if node.args:
                raise WGSLUnsupported(f"{func.attr} takes no arguments", node)
            operand = self.operand_type(func.value) or self.operand_type(node)
            if func.attr == "__abs__" and operand not in {"f32", "i32"}:
                raise WGSLUnsupported("abs() requires a signed numeric value", node)
            if func.attr == "__abs__":
                self.require_abs_representable(func.value, operand, node)
            if func.attr == "__invert__" and operand not in INTEGERS:
                raise WGSLUnsupported("bitwise inversion requires an integer", node)
            result = self.operand_type(node)
            if func.attr != "__abs__" and result != operand:
                raise WGSLUnsupported(
                    f"Python {func.attr} returns {result}, but WGSL keeps "
                    f"{operand}; use an explicitly typed operation",
                    node,
                )
            return UNARY_DUNDERS[func.attr].format(self.expr(func.value))
        if isinstance(func, ast.Attribute) and func.attr == "__getitem__":
            if len(node.args) != 1:
                raise WGSLUnsupported("array indexing requires one index", node)
            self.validate_array_index(func.value, node.args[0], node)
            return f"{self.expr(func.value)}[{self.expr(node.args[0])}]"
        if isinstance(func, ast.Attribute) and func.attr == "__bool__":
            if node.args:
                raise WGSLUnsupported("__bool__ takes no arguments", node)
            if self.operand_type(func.value) != "bool":
                raise WGSLUnsupported(
                    "WGSL has no Python truthiness; conditions require bool",
                    node,
                )
            return self.expr(func.value)
        self.validate_call_arguments(node, getattr(func, "obj", None))
        if isinstance(func, ast.Attribute):
            return self.builtin(func.attr, node)
        if not isinstance(func, ast.Name):
            raise WGSLUnsupported("unsupported call target", node)
        py = getattr(getattr(func, "obj", None), "py_obj", None)
        decoration = get_wgsl_decoration(py)
        if decoration is None:
            return self.builtin(_runtime_name(func.id), node)
        if decoration.kind == "inline":
            if node.keywords:
                raise WGSLUnsupported("WGSL has no keyword arguments", node)
            args = [self.expr(a) for a in node.args]
            params = tuple(inspect.signature(py).parameters)
            if len(args) != len(params):
                raise WGSLUnsupported(
                    f"'{py.__name__}' must receive every argument positionally in WGSL",
                    node,
                )
            return decoration.template.format(
                *args, **dict(zip(params, args, strict=True))
            )
        if inspect.isclass(py):
            name = self.declared(py, node)
            if name in RESERVED_CASTS:
                return self.conversion(name, node)
            return self.emit_call(name, node)
        if decoration.kind == "emit":
            self.reached.append(func.obj)
        return self.emit_call(py.__name__, node)

    def builtin(self, name: str, node: ast.Call) -> str:
        if name in TEMPLATES:
            if name == "get_list_item":
                self.validate_array_index(node.args[0], node.args[1], node)
            return TEMPLATES[name].format(*(self.expr(a) for a in node.args))
        if name == "abs":
            operand = self.operand_type(node.args[0]) or self.operand_type(node)
            if operand not in {"f32", "i32"}:
                raise WGSLUnsupported("abs() requires a signed numeric value", node)
            self.require_abs_representable(node.args[0], operand, node)
        if name in {"min", "max"}:
            if len(node.args) < 2:
                raise WGSLUnsupported(
                    f"{name}() requires two or more scalar arguments in WGSL",
                    node,
                )
            concrete = {
                value_type
                for argument in node.args
                if (value_type := self.operand_type(argument)) is not None
            }
            if len(concrete) > 1:
                shown = " and ".join(sorted(concrete))
                raise WGSLUnsupported(
                    f"{name}() cannot mix {shown} in WGSL; convert the operands",
                    node,
                )
            result = self.operand_type(node)
            if result == "bool":
                raise WGSLUnsupported(f"{name}() does not accept bool in WGSL", node)
            if result is not None:
                for argument in node.args:
                    self.require_literal_type(argument, result, node)
            values = [self.expr(argument) for argument in node.args]
            expression = f"{name}({values[0]}, {values[1]})"
            for value in values[2:]:
                expression = f"{name}({expression}, {value})"
            return expression
        if name in ("floor", "ceil", "trunc") and self.operand_type(node) == "i32":
            # Python returns int; WGSL returns an already-integral f32.
            return f"i32({self.emit_call(BUILTINS[name], node)})"
        if name == "float":
            return self.conversion("f32", node)
        if name == "int":
            representation = analyzed_numeric_format(node)
            target = (
                self.resolve_numeric(representation, node)
                if representation is not None
                else "i32"
            )
            return self.conversion(target, node)
        if name in RESERVED_CASTS:
            return self.conversion(name, node)
        if name in BUILTINS:
            return self.emit_call(BUILTINS[name], node)
        raise WGSLUnsupported(
            f"'{name}' is not a WGSL builtin and is not marked @wgsl", node
        )

    def conversion(self, name: str, node: ast.Call) -> str:
        if len(node.args) != 1:
            raise WGSLUnsupported(f"{name}() requires one argument", node)
        argument = node.args[0]
        actual = self.operand_type(argument)
        if actual is not None and actual not in WGSL_SCALARS:
            raise WGSLUnsupported(
                f"{name}() cannot convert {actual} in WGSL",
                node,
            )
        self.require_literal_type(argument, name, node)
        return self.emit_call(name, node)

    def validate_call_arguments(self, node: ast.Call, target: object) -> None:
        function: Function | None
        if isinstance(target, Function):
            function = target
        elif isinstance(target, Class):
            if target.name in RESERVED_CASTS or target.name in SCALARS:
                return
            constructor = target.find_attrs("__init__", search_bases=False)
            function = constructor if isinstance(constructor, Function) else None
        else:
            return
        if (
            function is None
            or function.name in {"min", "max", "abs"}
            or _runtime_name(function.name) in TEMPLATES
        ):
            return
        if len(node.args) != len(function.params):
            raise WGSLUnsupported(
                f"'{function.name}' must receive every argument positionally in WGSL",
                node,
            )
        decoration = get_wgsl_decoration(function.py_func)
        annotations = annotationlib.get_annotations(
            function.py_func,
            format=annotationlib.Format.VALUE,
        )
        for argument, parameter in zip(node.args, function.params, strict=True):
            annotation = annotations[parameter.arg]
            parameter_type = parameter.annotation.obj
            if (
                decoration is not None
                and decoration.kind in {"inline", "native"}
                and analyzed_numeric_format(parameter) is None
                and parameter_type.name in {"int", "float"}
            ):
                expected = SCALARS[parameter_type.name]
            else:
                expected = self.resolve_annotation(annotation, node)
            if expected.startswith("array<"):
                actual = self.array_type(argument)
                if actual is not None and actual != expected:
                    raise WGSLUnsupported(
                        f"argument {parameter.arg!r} is {actual}, but WGSL "
                        f"requires {expected}",
                        node,
                    )
                continue
            literal = self.integer_literal(argument)
            if literal is not None:
                self.require_literal_type(argument, expected, node)
                continue
            actual = self.operand_type(argument)
            if actual is not None and actual != expected:
                raise WGSLUnsupported(
                    f"argument {parameter.arg!r} is {actual}, but WGSL requires "
                    f"{expected}; convert it explicitly",
                    node,
                )

    def array_type(self, node: ast.expr) -> str | None:
        if not isinstance(node, ast.Name):
            return None
        length = self.array_lengths.get(node.id)
        if length is None:
            return None
        if node.id in self.array_types:
            return self.array_types[node.id]
        value = self.scope.names[node.id]
        return self.resolve(
            value.cls,
            node,
            (length,),
            analyzed_numeric_format(value),
        )

    def emit_call(self, name: str, node: ast.Call) -> str:
        if node.keywords:
            raise WGSLUnsupported("WGSL has no keyword arguments", node)
        return f"{name}({', '.join(self.expr(a) for a in node.args)})"

    def line(self, text: str) -> str:
        return "  " * self.indent + text

    def temporary(self, purpose: str) -> str:
        while True:
            name = f"_pyjs_{purpose}_{self.temporary_index}"
            self.temporary_index += 1
            if name not in self.scope.names:
                return name

    def local_identifier(self, name: str) -> str:
        # Shared analysis reserves '$' names, which are not WGSL identifiers.
        # Allocate from the emitter's namespace to avoid user-local collisions.
        if not name.startswith("$"):
            return name
        if name not in self.local_identifiers:
            self.local_identifiers[name] = self.temporary("local")
        return self.local_identifiers[name]

    def require_mutable(self, name: str, node: ast.AST) -> None:
        if name in self.parameter_names:
            raise WGSLUnsupported(
                f"WGSL function parameter '{name}' is immutable; copy it to "
                "a local before assigning",
                node,
            )

    def block(self, body: list[ast.stmt]) -> list[str]:
        out: list[str] = []
        for stmt in body:
            out.extend(self.statement(stmt))
        return out

    def statement(self, node: ast.stmt) -> list[str]:
        if isinstance(node, ast.Return):
            if node.value is None:
                return [self.line("return;")]
            self.require_value_type(node.value, self.return_type, node)
            return [self.line(f"return {self.expr(node.value)};")]
        if isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                raise WGSLUnsupported("only plain names can be declared", node)
            name = node.target.id
            self.require_mutable(name, node)
            ty = self.local_type(name, node)
            if node.value is None:
                return []
            self.require_value_type(node.value, ty, node)
            identifier = self.local_identifier(name)
            if name in self.hoisted:
                return [self.line(f"{identifier} = {self.expr(node.value)};")]
            return [self.line(f"var {identifier}: {ty} = {self.expr(node.value)};")]
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise WGSLUnsupported("only single-name assignment is supported", node)
            self.require_mutable(node.targets[0].id, node)
            self.require_value_type(
                node.value,
                self.local_type(node.targets[0].id, node),
                node,
            )
            return [self.line(f"{self.local_identifier(node.targets[0].id)} = {self.expr(node.value)};")]
        if isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                raise WGSLUnsupported("only plain names can be augmented", node)
            self.require_mutable(node.target.id, node)
            op = AST_BINOPS.get(type(node.op))
            if op is None:
                raise WGSLUnsupported("unsupported augmented operator", node)
            return [self.line(f"{node.target.id} {op}= {self.expr(node.value)};")]
        if isinstance(node, ast.If):
            out = [self.line(f"if ({self.expr(node.test)}) {{")]
            self.indent += 1
            out.extend(self.block(node.body))
            self.indent -= 1
            if node.orelse:
                out.append(self.line("} else {"))
                self.indent += 1
                out.extend(self.block(node.orelse))
                self.indent -= 1
            out.append(self.line("}"))
            return out
        if isinstance(node, ast.While):
            if node.orelse:
                raise WGSLUnsupported("while/else has no WGSL form", node)
            out = [self.line(f"while ({self.expr(node.test)}) {{")]
            self.indent += 1
            out.extend(self.block(node.body))
            self.indent -= 1
            out.append(self.line("}"))
            return out
        if isinstance(node, ast.For):
            return self.for_range(node)
        if isinstance(node, ast.Pass):
            return []
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant):
                return []
            raise WGSLUnsupported("expression statements have no WGSL form", node)
        raise WGSLUnsupported(f"unsupported statement {type(node).__name__}", node)

    def for_range(self, node: ast.For) -> list[str]:
        target = node.target
        if isinstance(target, ast.arg):
            name = target.arg
        elif isinstance(target, ast.Name):
            name = target.id
        else:
            raise WGSLUnsupported("loop variable must be a plain name", node)
        self.require_mutable(name, node)
        index_type = self.local_type(name, node)
        it = node.iter
        if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)
                and it.func.id == "range"):
            raise WGSLUnsupported("only 'for i in range(...)' is supported", node)
        if node.orelse:
            raise WGSLUnsupported("for/else has no WGSL form", node)
        args = [self.expr(a) for a in it.args]
        condition = "<"
        if len(args) == 1:
            start, stop, step = "0", args[0], "1"
        elif len(args) == 2:
            start, stop, step = args[0], args[1], "1"
        elif len(args) == 3:
            start, stop, step = args
            step_node = it.args[2]
            if isinstance(step_node, ast.Constant) and type(step_node.value) is int:
                if step_node.value == 0:
                    raise WGSLUnsupported("range() step cannot be zero", step_node)
                if step_node.value < 0:
                    condition = ">"
            elif (
                isinstance(step_node, ast.UnaryOp)
                and isinstance(step_node.op, ast.USub)
                and isinstance(step_node.operand, ast.Constant)
                and type(step_node.operand.value) is int
                and step_node.operand.value > 0
            ):
                condition = ">"
            else:
                raise WGSLUnsupported(
                    "range() step must be a non-zero integer literal",
                    step_node,
                )
        else:
            raise WGSLUnsupported("range() takes one to three arguments", node)
        for argument in it.args:
            literal = self.integer_literal(argument)
            if literal is not None:
                self.require_literal_type(argument, index_type, node)
                continue
            actual = self.operand_type(argument)
            if actual is not None and actual != index_type:
                raise WGSLUnsupported(
                    f"range() bound is {actual}, but its loop variable is "
                    f"{index_type}; convert the bound explicitly",
                    argument,
                )
        i = name
        out = []
        stop_node = it.args[0] if len(it.args) == 1 else it.args[1]
        static_stop = self.static_expression(stop_node)
        if self.integer_literal(static_stop or stop_node) is None:
            if len(it.args) > 1:
                start_node = it.args[0]
                static_start = self.static_expression(start_node)
                if self.integer_literal(static_start or start_node) is None:
                    stable_start = self.temporary("range_start")
                    out.append(self.line(f"let {stable_start}: {index_type} = {start};"))
                    start = stable_start
            stable_stop = self.temporary("range_stop")
            out.append(self.line(f"let {stable_stop}: {index_type} = {stop};"))
            stop = stable_stop
        initializer = (
            f"{i} = {start}" if i in self.hoisted else f"var {i}: {index_type} = {start}"
        )
        out.append(
            self.line(
                f"for ({initializer}; {i} {condition} {stop}; {i} = {i} + {step}) {{"
            )
        )
        self.indent += 1
        out.extend(self.block(node.body))
        self.indent -= 1
        out.append(self.line("}"))
        return out


def _wgsl_roots(module) -> tuple[typing.Callable, ...]:
    return tuple(
        obj
        for obj in vars(module).values()
        if inspect.isfunction(obj)
        and (decoration := get_wgsl_decoration(obj)) is not None
        and decoration.kind == "emit"
    )


def transpile_wgsl(
    source: str,
    *,
    filename: str = "_pyjs_wgsl_.py",
    module_name: str | None = None,
) -> str:
    """Analyze source and emit its reachable ``@wgsl`` functions."""
    with analyze_source(
        source,
        filename=filename,
        module_name=module_name,
        wrap=True,
        root_selector=_wgsl_roots,
        environment=WGSL_ENVIRONMENT,
    ) as analysis:
        roots = analysis.entry_point.compilation_entry_points[1:]
        if not roots:
            raise WGSLUnsupported("no functions are marked @wgsl")
        emitter = WGSLEmitter()
        texts: dict[object, str] = {}
        callees: dict[object, list[object]] = {}
        pending = list(roots)
        while pending:
            function = pending.pop(0)
            if function.py_func in texts:
                continue
            texts[function.py_func] = emitter.function(function)
            callees[function.py_func] = list(emitter.reached)
            pending.extend(emitter.reached)
        functions: list[str] = []
        placed: set[object] = set()
        active: set[object] = set()

        def place(function) -> None:
            if function.py_func in placed:
                return
            if function.py_func in active:
                raise WGSLUnsupported(
                    f"recursive call graph reaches '{function.name}'; WGSL "
                    "functions cannot be recursive",
                    function.node,
                )
            active.add(function.py_func)
            for callee in callees[function.py_func]:
                place(callee)
            active.remove(function.py_func)
            placed.add(function.py_func)
            functions.append(texts[function.py_func])

        for root in roots:
            place(root)
        structs = emitter.struct_declarations()
        equality_helpers = emitter.equality_helpers()
        out = [*structs, *equality_helpers, *functions]
        return "\n\n".join(out) + "\n"
