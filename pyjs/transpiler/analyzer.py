from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from graphlib import TopologicalSorter

from .diagnostics import CompilationContext, CompilationError, DiagnosticCode, Label
from .objects import *

TYPING_TYPE_ALIASES = {
    "Any": "object",
    "Dict": "dict",
    "List": "list",
    "Set": "set",
    "Tuple": "tuple",
}


def typing_alias_name(node: ast.expr, scope: Scope) -> str | None:
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name):
            try:
                module = scope.search(node.value.id)
            except NameError:
                return None
            if (
                isinstance(module, ModuleAlias)
                and module.target.py_obj.__name__ == "pyjs.stdlib.typing"
            ):
                return node.attr
        return None
    if not isinstance(node, ast.Name):
        return None
    try:
        scope.search(node.id)
    except NameError:
        return node.id
    return None


@dataclass
class AssignmentValue:
    node: ast.expr
    declared_type: Class | UnionType | None
    inferred_type: Class | UnionType | None

    @property
    def storage_type(self):
        return self.declared_type or self.inferred_type


@dataclass(frozen=True)
class UnionFieldResolution:
    fields: tuple[Instance, ...]
    value_type: Class | UnionType


@dataclass(frozen=True)
class UnionMethodResolution:
    methods: tuple[Function, ...]
    return_type: Class | UnionType | None


def analyzed_annotation(value_type: Class | UnionType) -> ast.expr:
    if isinstance(value_type, Class) and not isinstance(
        value_type,
        (CallableClass, LiteralClass),
    ):
        return Name(value_type)
    annotation = value_type.annotation
    annotation.obj = value_type
    return annotation


def get_none_type():
    none_type = BUILTINS.search("NoneType")
    assert isinstance(none_type, Class)
    return none_type


def get_type_members(type_):
    if isinstance(type_, UnionType):
        return list(type_.types)
    return [type_]


def callable_member(value_type):
    members = [
        member
        for member in get_type_members(value_type)
        if isinstance(member, CallableClass)
    ]
    return members[0] if len(members) == 1 else None


def literal_member_for_value(value_type, value):
    if not isinstance(value, str):
        return None
    for member in get_type_members(value_type):
        if isinstance(member, LiteralClass) and value in member.values:
            return literal_type((value,), member.scope)
    return None


def contextual_collection_type(value_type, generic_name):
    matches = [
        member
        for member in get_type_members(value_type)
        if isinstance(member, Class)
        and (
            member.generic_name == generic_name
            or (generic_name == "dict" and isinstance(member, TypedDictClass))
        )
    ]
    return matches[0] if len(matches) == 1 else None


def is_return_type_compatible(expected, actual):
    if expected is None:
        return True
    if expected == actual:
        return True
    expected_types = get_type_members(expected)
    return all(
        any(is_subclass(actual_type, expected_type) for expected_type in expected_types)
        for actual_type in get_type_members(actual)
    )


def is_iterable_argument_compatible(expected, actual):
    iterable_types = {
        "Iterable",
        "Iterator",
        "dict",
        "list",
        "set",
        "str",
        "tuple",
        "typed_dict",
    }
    if any(
        not isinstance(member, TypedDictClass)
        and (member.generic_name or member.name) not in iterable_types
        for member in get_type_members(actual)
    ):
        return False
    actual_item_type = iterable_item_type(actual)
    return any(
        expected_type.generic_name in {"Iterable", "Iterator"}
        and is_return_type_compatible(
            expected_type.generic_types["V"], actual_item_type
        )
        for expected_type in get_type_members(expected)
    )


def is_call_argument_compatible(expected, value):
    actual = analyzed_value_type(value)
    if is_return_type_compatible(expected, actual):
        return True
    expected_members = get_type_members(expected)
    if is_iterable_argument_compatible(expected, actual):
        return True
    if any(type_.name == "callable" for type_ in expected_members):
        if isinstance(value.obj, Function) or (
            isinstance(value, (Name, Attribute))
            and isinstance(value.obj, (Class, GenericClass))
        ):
            return True
    if not isinstance(value.obj, GenericClass):
        return False
    if any(type_.generic_name == value.obj.name for type_ in expected_members):
        return True
    return value.obj.name in {"dict", "list", "set", "tuple"} and any(
        type_.generic_name == "Iterable" for type_ in expected_members
    )


def is_subclass(actual, expected):
    if same_analyzer_type(actual, expected):
        return True
    if (
        isinstance(actual, Class)
        and isinstance(expected, Class)
        and actual.generic_name == expected.generic_name == "type"
    ):
        actual_type = actual.generic_types["T"]
        expected_type = expected.generic_types["T"]
        return is_return_type_compatible(expected_type, actual_type)
    if isinstance(actual, TypedDictClass) and isinstance(expected, TypedDictClass):
        pending = list(getattr(actual.py_cls, "__orig_bases__", ()))
        seen = set()
        while pending:
            base = pending.pop()
            if base in seen:
                continue
            seen.add(base)
            if base is expected.py_cls:
                return True
            if typing.is_typeddict(base):
                pending.extend(getattr(base, "__orig_bases__", ()))
        return False
    if (
        isinstance(actual, Class)
        and isinstance(expected, Class)
        and actual.generic_name == expected.generic_name
        and actual.generic_types
        and expected.generic_types
        and actual.generic_types.keys() == expected.generic_types.keys()
    ):
        return all(
            is_return_type_compatible(
                expected.generic_types[name],
                actual.generic_types[name],
            )
            for name in expected.generic_types
        )
    if isinstance(expected, CallableClass):
        if not isinstance(actual, CallableClass):
            return False
        parameters_match = (
            expected.parameter_types is None
            or actual.parameter_types is None
            or (
                len(expected.parameter_types) == len(actual.parameter_types)
                and all(
                    is_return_type_compatible(actual_parameter, expected_parameter)
                    for actual_parameter, expected_parameter in zip(
                        actual.parameter_types,
                        expected.parameter_types,
                        strict=True,
                    )
                )
            )
        )
        return parameters_match and is_return_type_compatible(
            expected.return_type,
            actual.return_type,
        )
    if isinstance(expected, LiteralClass):
        return isinstance(actual, LiteralClass) and set(actual.values) <= set(
            expected.values
        )
    if expected.name == "float" and actual.name in {"bool", "int"}:
        return True
    if getattr(expected.py_cls, "__pyjs_structural__", False):
        methods = (
            name
            for name, value in expected.internal_scope.names.items()
            if isinstance(value, Function) and not name.startswith("_")
        )
        try:
            if all(isinstance(actual.find(name), Function) for name in methods):
                return True
        except NameError:
            pass
    while actual is not None:
        if actual.name == expected.name:
            return True
        actual = actual.super
    return False


def merge_return_types(left, right):
    if left is None:
        return right
    if left == right:
        return left
    merged = UnionType()
    for type_ in get_type_members(left):
        merged.add(type_)
    for type_ in get_type_members(right):
        merged.add(type_)
    return merged.type


def contains_type_variable(value_type, target=None):
    if isinstance(value_type, TypeVariableClass):
        return target is None or value_type is target
    if isinstance(value_type, UnionType):
        return any(
            contains_type_variable(member, target) for member in value_type.types
        )
    if isinstance(value_type, CallableClass):
        return (
            value_type.parameter_types is not None
            and any(
                contains_type_variable(parameter, target)
                for parameter in value_type.parameter_types
            )
        ) or contains_type_variable(value_type.return_type, target)
    return isinstance(value_type, Class) and any(
        contains_type_variable(member, target)
        for member in (value_type.generic_types or {}).values()
    )


def contains_json_object_schema(value_type):
    if isinstance(value_type, UnionType):
        return any(contains_json_object_schema(member) for member in value_type.types)
    if not isinstance(value_type, Class):
        return False
    if (
        isinstance(value_type, TypedDictClass)
        and value_type.py_cls.__module__ == "pyjs.javascript"
        and value_type.py_cls.__qualname__ == "JSONObject"
    ):
        return True
    return any(
        contains_json_object_schema(member)
        for member in (value_type.generic_types or {}).values()
    )


def substitute_type_variables(value_type, bindings):
    if isinstance(value_type, TypeVariableClass):
        return bindings.get(value_type, value_type)
    if isinstance(value_type, UnionType):
        return UnionType(
            types=[
                substitute_type_variables(member, bindings)
                for member in value_type.types
            ]
        ).type
    if isinstance(value_type, CallableClass):
        parameters = None
        if value_type.parameter_types is not None:
            parameters = tuple(
                substitute_type_variables(parameter, bindings)
                for parameter in value_type.parameter_types
            )
        return CallableClass(
            parameters,
            substitute_type_variables(value_type.return_type, bindings),
            value_type.super,
        )
    if not isinstance(value_type, Class) or not value_type.generic_types:
        return value_type
    members = tuple(
        substitute_type_variables(member, bindings)
        for member in value_type.generic_types.values()
    )
    if all(
        same_analyzer_type(original, replacement)
        for original, replacement in zip(
            value_type.generic_types.values(),
            members,
            strict=True,
        )
    ):
        return value_type
    generic = value_type.container.search(value_type.generic_name)
    assert isinstance(generic, GenericClass)
    return generic(*members)


def infer_type_variables(pattern, actual, bindings):
    if isinstance(pattern, TypeVariableClass):
        current = bindings.get(pattern)
        bindings[pattern] = merge_return_types(current, actual)
        return
    if isinstance(pattern, UnionType):
        candidates = [
            member
            for member in pattern.types
            if contains_type_variable(member)
        ]
        concrete = [
            member
            for member in pattern.types
            if not contains_type_variable(member)
        ]
        if any(is_return_type_compatible(member, actual) for member in concrete):
            return
        if len(candidates) == 1:
            infer_type_variables(candidates[0], actual, bindings)
        return
    if isinstance(pattern, CallableClass) and isinstance(actual, CallableClass):
        if pattern.parameter_types is not None and actual.parameter_types is not None:
            for pattern_parameter, actual_parameter in zip(
                pattern.parameter_types,
                actual.parameter_types,
                strict=False,
            ):
                parameter_bindings = {}
                infer_type_variables(
                    pattern_parameter,
                    actual_parameter,
                    parameter_bindings,
                )
                for parameter, value_type in parameter_bindings.items():
                    bindings.setdefault(parameter, value_type)
        infer_type_variables(pattern.return_type, actual.return_type, bindings)
        return
    if not isinstance(pattern, Class) or not pattern.generic_types:
        return
    if pattern.generic_name in {"Iterable", "Iterator"}:
        pattern_item = next(iter(pattern.generic_types.values()))
        infer_type_variables(pattern_item, iterable_item_type(actual), bindings)
        return
    if not isinstance(actual, Class) or pattern.generic_name != actual.generic_name:
        return
    for pattern_member, actual_member in zip(
        pattern.generic_types.values(),
        actual.generic_types.values(),
        strict=False,
    ):
        infer_type_variables(pattern_member, actual_member, bindings)


def analyzed_value_object(value):
    return value.value_obj if isinstance(value, (Call, Subscript)) else value.obj


def analyzed_value_type(value):
    value_type = analyzed_value_object(value)
    if isinstance(value, (Name, Attribute)) and isinstance(value_type, Class):
        type_class = BUILTINS.search("type")
        assert isinstance(type_class, GenericClass)
        return type_class(value_type)
    if isinstance(value, (Name, Attribute)) and isinstance(value_type, GenericClass):
        type_class = BUILTINS.search("type")
        object_class = BUILTINS.search("object")
        assert isinstance(type_class, GenericClass)
        assert isinstance(object_class, Class)
        return type_class(object_class)
    if isinstance(value_type, Instance):
        return value_type.cls
    if isinstance(value_type, GenericClass):
        return BUILTINS.search("object")
    if isinstance(value_type, (Class, UnionType)):
        return value_type
    return BUILTINS.search("object")


def callable_value_type(value):
    value_obj = analyzed_value_object(value)
    if isinstance(value_obj, CallableClass):
        return value_obj
    if not isinstance(value_obj, Function):
        return analyzed_value_type(value)
    return_type = value_obj.return_type or value_obj.declared_return_type
    if return_type is None:
        return analyzed_value_type(value)
    base = BUILTINS.search("callable")
    assert isinstance(base, Class)
    return CallableClass(
        tuple(parameter.annotation.obj for parameter in value_obj.params),
        return_type,
        base,
    )


def conditional_value_type(value, other_type):
    value_type = value.obj
    if (
        isinstance(value_type, GenericClass)
        and isinstance(other_type, Class)
        and other_type.generic_name == value_type.name
    ):
        return other_type
    return analyzed_value_type(value)


def iterable_item_type(value_type):
    item_type = None
    for member in get_type_members(value_type):
        if isinstance(member, TypedDictClass):
            member_type = BUILTINS.search("str")
        elif member.generic_name == "dict":
            member_type = member.generic_types["K"]
        elif member.generic_name == "tuple":
            member_type = None
            for tuple_type in member.generic_types.values():
                member_type = merge_return_types(member_type, tuple_type)
        elif member.generic_types and len(member.generic_types) == 1:
            member_type = next(iter(member.generic_types.values()))
        else:
            member_type = member
        item_type = merge_return_types(item_type, member_type)
    return item_type


def extreme_values_type(args):
    if not args:
        return None
    if len(args) > 1:
        value_type = None
        for argument in args:
            value_type = merge_return_types(
                value_type,
                analyzed_value_type(argument),
            )
        return value_type
    if isinstance(args[0], (List, Tuple)) and not args[0].elts:
        return None
    return iterable_item_type(analyzed_value_type(args[0]))


def extreme_comparison_type(args, keywords):
    return keyed_comparison_type(extreme_values_type(args), keywords)


def keyed_comparison_type(value_type, keywords):
    key = next((keyword.value for keyword in keywords if keyword.arg == "key"), None)
    if key is not None and getattr(key.obj, "name", None) != "NoneType":
        if isinstance(key, ast.Lambda):
            return key.return_type
        if isinstance(key.obj, Function):
            return key.obj.return_type or key.obj.declared_return_type
        return BUILTINS.search("object")

    return value_type


def supports_order_comparison(value_type):
    if value_type is None:
        return True
    members = get_type_members(value_type)
    names = {member.name for member in members}
    if names <= {"bool", "float", "int"} or names == {"str"}:
        return True
    if not members:
        return False
    sequence_types = {member.generic_name for member in members}
    if len(sequence_types) == 1 and sequence_types <= {"list", "tuple"}:
        return all(
            all(
                supports_order_comparison(item_type)
                for item_type in member.generic_types.values()
            )
            for member in members
        )
    return all(
        not getattr(member.py_obj, "__builtin__", False)
        and supports_dunder(member, "__lt__")
        for member in members
    )


def ordering_methods(value_type):
    if value_type is None:
        return ()
    methods = []
    for member in get_type_members(value_type):
        if member.generic_name in {"list", "tuple"}:
            for item_type in member.generic_types.values():
                methods.extend(ordering_methods(item_type))
            continue
        methods.extend(runtime_dunder_methods(member, "__lt__"))
    return tuple(dict.fromkeys(methods))


def supports_reversed(value_type):
    return all(
        member.name == "str"
        or member.generic_name in {"dict", "list", "tuple"}
        or isinstance(member, TypedDictClass)
        for member in get_type_members(value_type)
    )


def truthiness_methods(value_type):
    methods = []
    for member in get_type_members(value_type):
        if getattr(member.py_obj, "__builtin__", False):
            continue
        for method_name in ("__bool__", "__len__"):
            method = member.find_attrs(method_name)
            if isinstance(method, Function):
                methods.append(method)
                break
    return tuple(dict.fromkeys(methods))


def runtime_dunder_methods(value_type, *method_names):
    methods = []
    for member in get_type_members(value_type):
        if getattr(member.py_obj, "__builtin__", False):
            continue
        for method_name in method_names:
            method = member.find_attrs(method_name)
            if isinstance(method, Function):
                methods.append(method)
    return tuple(dict.fromkeys(methods))


def equality_methods(value_type):
    return runtime_dunder_methods(value_type, "__eq__")


def inequality_methods(value_type):
    return runtime_dunder_methods(value_type, "__eq__", "__ne__")


def inherits_object_comparison(value_type, method_name):
    for member in get_type_members(value_type):
        try:
            method = member.find(method_name)
        except NameError:
            return False
        if not isinstance(method, Function) or method.cls.name != "object":
            return False
    return True


def runtime_class_dependency(value: Class, module: Module) -> Class | None:
    runtime_type = getattr(value.py_obj, "__js_runtime__", None)
    if runtime_type is None:
        return None
    runtime_dependency = resolve_imported(runtime_type, module)
    assert isinstance(runtime_dependency, Class)
    return runtime_dependency


def supports_dunder(value_type, method_name):
    for member in get_type_members(value_type):
        try:
            method = member.find(method_name)
        except NameError:
            return False
        if not isinstance(method, Function):
            return False
    return True


def validate_json_result_type(result_type, path, seen=None):
    if seen is None:
        seen = set()
    if id(result_type) in seen:
        return
    seen.add(id(result_type))
    if isinstance(result_type, UnionType):
        for member in result_type.types:
            validate_json_result_type(member, path, seen)
        return
    if isinstance(result_type, TypedDictClass):
        for key in result_type.annotations:
            validate_json_result_type(
                result_type.field_type(key),
                f"{path}.{key}",
                seen,
            )
        return
    if isinstance(result_type, Class):
        if result_type.generic_name == "dict":
            raise TypeError(
                f"JSON schema field {path!r} uses dict, whose JavaScript "
                "representation is Map"
            )
        if result_type.generic_name == "list":
            validate_json_result_type(
                result_type.generic_types["V"],
                f"{path}[]",
                seen,
            )
            return
        if result_type.name in {"bool", "float", "int", "NoneType", "str"}:
            return
    raise TypeError(
        f"JSON schema field {path!r} has unsupported type "
        f"{result_type.to_annotation_str()}"
    )


def apply_typed_dict_literal(value, expected_type):
    if isinstance(expected_type, TypedDictClass) and isinstance(value, Dict):
        value.obj = expected_type
        for key, item in zip(value.keys, value.values, strict=True):
            if not isinstance(key, Constant) or not isinstance(key.value, str):
                raise TypeError("TypedDict literal keys must be strings.")
            apply_typed_dict_literal(item, expected_type.field_type(key.value))
    elif (
        isinstance(expected_type, Class)
        and expected_type.generic_name == "list"
        and isinstance(value, List)
    ):
        item_type = expected_type.generic_types["V"]
        for item in value.elts:
            apply_typed_dict_literal(item, item_type)


def body_can_fall_through(
    statements: list[ast.stmt],
    *,
    loop_control_exits: bool = False,
):
    for statement in statements:
        if statement_always_exits(
            statement,
            loop_control_exits=loop_control_exits,
        ):
            return False
    return True


def body_always_returns(statements: list[ast.stmt]):
    for statement in statements:
        if statement_always_returns(statement):
            return True
        if statement_always_exits(statement):
            return False
    return False


class LoopBreakFinder(ast.NodeVisitor):
    def __init__(self):
        self.found = False

    def visit_Break(self, node):
        self.found = True

    def visit_For(self, node):
        pass

    def visit_AsyncFor(self, node):
        pass

    def visit_While(self, node):
        pass


class _CallAnalysis:
    """Compiler-private escape hatch for syntax-dependent call semantics."""

    def __init__(self, visitor, node, function):
        self.visitor = visitor
        self.node = node
        self.function = function
        self._result = None

    def standard(self):
        if self._result is None:
            self.visitor.active_call_analysis.add(self.node)
            try:
                self._result = self.visitor.visit_Call(self.node)
            finally:
                self.visitor.active_call_analysis.remove(self.node)
        return self._result

    def with_result_type(self, result_type):
        result = self.standard()
        result.obj = result_type
        result.value_obj = result_type
        if isinstance(result_type, Class):
            result.value_obj = result_type(
                "__call_result__",
                self.visitor.scope,
                self.visitor.func,
            )
        return result

    def static_cast(self):
        if len(self.node.args) != 2 or self.node.keywords:
            self.visitor.fail(
                self.node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "typing.cast() requires a type and one value",
                help="Call cast(ExpectedType, value) with positional arguments.",
            )
        try:
            target_type = self.visitor.visit_type_annotation(self.node.args[0]).obj
        except (AssertionError, NotImplementedError):
            target_type = None
        if not isinstance(target_type, (Class, UnionType)):
            self.visitor.fail(
                self.node.args[0],
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "typing.cast() requires a statically known type",
                help="Pass a type annotation as the first argument to cast().",
            )
        value = self.visitor.visit(self.node.args[1])
        value_obj = target_type
        if isinstance(target_type, Class):
            value_obj = target_type(
                "__cast_result__",
                self.visitor.scope,
                self.visitor.func,
            )
        return StaticCast(value_obj, value, lineno=self.node.lineno)

    def literal_attribute(self):
        result = self.standard()
        return self.visitor.analyze_getattr(
            self.node,
            result.func.obj,
            result.args,
        )

    def preserve_reference(self):
        result = self.standard()
        assert len(result.args) == 1 and not result.keywords
        result.is_ref = True
        return result

    def zipped(self):
        result = self.standard()
        iterator = BUILTINS.search("Iterator")
        tuple_type = BUILTINS.search("tuple")
        assert isinstance(iterator, GenericClass)
        assert isinstance(tuple_type, GenericClass)
        item_types = [
            iterable_item_type(analyzed_value_type(argument))
            for argument in result.args
        ]
        return self.with_result_type(iterator(tuple_type(*item_types)))

    def dataclass(self, *, replace=False):
        result = self.standard()
        utility = "replace" if replace else "asdict"
        self.visitor.validate_dataclass_utility(
            self.node,
            utility,
            result.args,
            result.keywords,
        )
        return result

    def typed_dict_get(self):
        result = self.standard()
        if not result.args:
            return result
        receiver = result.func.value.obj
        receiver_type = receiver.cls if isinstance(receiver, Instance) else receiver
        if not isinstance(receiver_type, TypedDictClass):
            return result
        key = result.args[0]
        if not isinstance(key, Constant) or not isinstance(key.value, str):
            return result
        result_type = receiver_type.field_type(key.value)
        if key.value not in receiver_type.required_keys:
            default_type = (
                analyzed_value_type(result.args[1])
                if len(result.args) > 1
                else get_none_type()
            )
            result_type = merge_return_types(result_type, default_type)
        return self.with_result_type(result_type)

    def extreme(self):
        result = self.standard()
        operation = self.function.name
        comparison_type = extreme_comparison_type(result.args, result.keywords)
        if not supports_order_comparison(comparison_type):
            type_names = ", ".join(
                sorted(
                    type_.generic_name or type_.name
                    for type_ in get_type_members(comparison_type)
                )
            )
            self.visitor.fail(
                self.node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"{operation}() cannot order values of type {type_names}",
                help=(
                    "Use numeric or string values, or pass a key function "
                    "that returns one of those types."
                ),
            )
        result.runtime_methods = tuple(
            dict.fromkeys((*result.runtime_methods, *ordering_methods(comparison_type)))
        )
        return result

    def sortable(self, *, method=False):
        result = self.standard()
        operation = "list.sort" if method else "sorted"
        if not method:
            value_type = iterable_item_type(analyzed_value_type(result.args[0]))
        else:
            receiver = result.func.value.obj
            receiver_type = (
                receiver.cls if isinstance(receiver, Instance) else receiver
            )
            value_type = receiver_type.generic_types["V"]
        self.visitor.validate_sort_order(
            self.node,
            value_type,
            result.keywords,
            operation,
        )
        comparison_type = keyed_comparison_type(value_type, result.keywords)
        result.runtime_methods = tuple(
            dict.fromkeys((*result.runtime_methods, *ordering_methods(comparison_type)))
        )
        return result

    def reversible(self):
        result = self.standard()
        value_type = analyzed_value_type(result.args[0])
        if supports_reversed(value_type):
            return result
        type_names = ", ".join(
            sorted(
                type_.generic_name or type_.name
                for type_ in get_type_members(value_type)
            )
        )
        self.visitor.fail(
            self.node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "reversed() requires a reversible sequence, got " + type_names,
            help="Use a list, tuple, string, or dictionary.",
        )


def body_breaks_current_loop(statements: list[ast.stmt]) -> bool:
    finder = LoopBreakFinder()
    for statement in statements:
        finder.visit(statement)
    return finder.found


def statement_always_returns(statement: ast.stmt):
    if isinstance(statement, ast.Return):
        return True
    if isinstance(statement, ast.If):
        return (
            bool(statement.orelse)
            and body_always_returns(statement.body)
            and body_always_returns(statement.orelse)
        )
    if isinstance(statement, ast.Match):
        return bool(statement.cases) and all(
            body_always_returns(case.body) for case in statement.cases
        )
    if isinstance(statement, ast.With):
        return body_always_returns(statement.body)
    return False


def statement_always_exits(
    statement: ast.stmt,
    *,
    loop_control_exits: bool = False,
):
    if isinstance(statement, (ast.Return, ast.Raise)):
        return True
    if loop_control_exits and isinstance(statement, (ast.Break, ast.Continue)):
        return True
    if isinstance(statement, ast.If):
        return (
            bool(statement.orelse)
            and not body_can_fall_through(
                statement.body,
                loop_control_exits=loop_control_exits,
            )
            and not body_can_fall_through(
                statement.orelse,
                loop_control_exits=loop_control_exits,
            )
        )
    if isinstance(statement, ast.Match):
        return bool(statement.cases) and all(
            not body_can_fall_through(
                case.body,
                loop_control_exits=loop_control_exits,
            )
            for case in statement.cases
        )
    if isinstance(statement, ast.While):
        if (
            statement.orelse
            and not body_can_fall_through(statement.body)
            and not body_can_fall_through(statement.orelse)
        ):
            return True
        return (
            isinstance(statement.test, ast.Constant)
            and bool(statement.test.value)
            and not statement.orelse
            and not body_breaks_current_loop(statement.body)
        )
    if isinstance(statement, ast.Try):
        if statement.finalbody and not body_can_fall_through(
            statement.finalbody,
            loop_control_exits=loop_control_exits,
        ):
            return True
        return (
            bool(statement.handlers)
            and not body_can_fall_through(
                statement.body,
                loop_control_exits=loop_control_exits,
            )
            and all(
                not body_can_fall_through(
                    handler.body,
                    loop_control_exits=loop_control_exits,
                )
                for handler in statement.handlers
            )
        )
    if isinstance(statement, ast.With):
        return not body_can_fall_through(
            statement.body,
            loop_control_exits=loop_control_exits,
        )
    return False


def is_interface_stub_body(statements: list[ast.stmt]):
    if len(statements) != 1:
        return False
    statement = statements[0]
    if isinstance(statement, ast.Raise):
        return True
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


class InferenceVisitor(ast.NodeVisitor):
    def __init__(self, func: Function, scope: LocalScope = None):
        self.func = func
        self.scope = scope or func.scope
        self.assignment_target: ast.AST | None = None
        self.contextual_types: dict[ast.AST, Class | UnionType] = {}
        self.direct_call_target: ast.AST | None = None
        self.active_call_analysis: set[ast.Call] = set()

    @property
    def module(self) -> Module:
        return self.func.cls.container if self.func.is_method else self.func.container

    def fail(
        self,
        node: ast.AST,
        code: DiagnosticCode,
        message: str,
        *,
        label: str | None = None,
        help: str | None = None,
        secondary: tuple[Label, ...] = (),
    ):
        self.module.context.error(
            self.func.source_fragment,
            node,
            code,
            message,
            label=label,
            help=help,
            secondary=secondary,
        )

    def visit_contextual_expression(self, node, expected_type):
        if expected_type is not None:
            self.contextual_types[node] = expected_type
        try:
            return self.visit(node)
        finally:
            self.contextual_types.pop(node, None)

    def visible_names(self) -> set[str]:
        names = set()
        scope = self.scope
        while scope is not None:
            names.update(scope.names)
            scope = scope.parent
        names.update(self.module.scope.names)
        return names

    @staticmethod
    def attribute_names(value: Instance) -> set[str]:
        names = set(value.attrs)
        cls = value.cls
        while cls is not None:
            names.update(cls.internal_scope.names)
            names.update(cls._self.attrs)
            cls = cls.super
        return names

    @staticmethod
    def receiver_union(value: Object | UnionType) -> UnionType | None:
        if isinstance(value, UnionType):
            return value
        if isinstance(value, Instance) and isinstance(value.cls, UnionType):
            return value.cls
        return None

    def resolve_union_attribute(
        self,
        node: ast.Attribute,
        value_type: UnionType,
        *,
        for_assignment: bool = False,
    ) -> UnionFieldResolution | UnionMethodResolution:
        fields = []
        methods = []
        missing = []
        incompatible = []
        for member_type in value_type.types:
            try:
                attribute = member_type._self.find(node.attr)
            except NameError:
                initializer = member_type.init
                if (
                    initializer is not None
                    and initializer is not self.func
                    and not initializer.is_analyzed
                ):
                    raise DependencyError(initializer) from None
                missing.append(member_type.name)
                continue
            if isinstance(attribute, Instance):
                fields.append(attribute)
            elif isinstance(attribute, Function):
                methods.append(attribute)
            else:
                incompatible.append(member_type.name)

        union_name = value_type.to_annotation_str(" | ")
        if missing:
            self.fail(
                node,
                DiagnosticCode.UNDEFINED_ATTRIBUTE,
                f"Attribute {node.attr!r} is not defined on every member of "
                f"{union_name}",
                help=(
                    f"Missing from {', '.join(missing)}. Narrow the value with "
                    f"isinstance() before accessing {node.attr!r}."
                ),
            )
        if incompatible or (fields and methods):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Attribute {node.attr!r} has incompatible definitions on {union_name}",
                help=(
                    "Narrow the value with isinstance() before accessing "
                    f"{node.attr!r}."
                ),
            )

        if methods:
            if for_assignment:
                return UnionMethodResolution(tuple(methods), None)
            return self.resolve_union_method(node, value_type, tuple(methods))

        result_type = None
        for field in fields:
            result_type = merge_return_types(result_type, field.cls)
        assert isinstance(result_type, (Class, UnionType))
        return UnionFieldResolution(tuple(fields), result_type)

    def resolve_union_method(
        self,
        node: ast.Attribute,
        value_type: UnionType,
        methods: tuple[Function, ...],
    ) -> UnionMethodResolution:
        for method in methods:
            if method is not self.func and not method.is_analyzed:
                raise DependencyError(method)

        first = methods[0]
        incompatible = [
            member_type.name
            for member_type, method in zip(value_type.types, methods, strict=True)
            if method.inline_decorator is not first.inline_decorator
            or method.is_async != first.is_async
        ]
        if incompatible:
            union_name = value_type.to_annotation_str(" | ")
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Method {node.attr!r} has incompatible client lowering on "
                f"{union_name}",
                help=(
                    "Narrow the receiver with isinstance() before calling the "
                    f"definition on {', '.join(incompatible)}."
                ),
            )

        result_type = None
        for method in methods:
            return_type = method.return_type or method.declared_return_type
            result_type = merge_return_types(result_type, return_type)
        assert isinstance(result_type, (Class, UnionType))
        return UnionMethodResolution(methods, result_type)

    def property_setter_type(
        self,
        node: ast.Attribute,
        setter: Function,
    ) -> Class | UnionType:
        if not setter.is_analyzed:
            raise DependencyError(setter)
        if (
            setter.is_async
            or setter.is_generator
            or len(setter.params) != 1
            or setter.defaults
            or setter.vararg is not None
            or setter.kwonlyargs
            or setter.kwarg is not None
        ):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Property setter {setter.name!r} has an unsupported signature",
                help="Define a synchronous setter as def name(self, value): ...",
            )
        value_type = setter.params[0].annotation.obj
        assert isinstance(value_type, (Class, UnionType))
        return value_type

    def fail_name_lookup(self, node: ast.Name):
        self.module.context.name_lookup_error(
            self.func.source_fragment,
            node,
            self.module.py_module,
            self.visible_names(),
        )

    def narrow(self, value_node, value_type):
        narrowed = type(self)(self.func, LocalScope(self.scope))
        value_name = ast.unparse(value_node)
        narrowed.scope.add(value_type(value_name, narrowed.scope, self.func))
        return narrowed

    def get_none_identity_narrowing(self, test):
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or not isinstance(test.ops[0], (ast.Is, ast.IsNot))
        ):
            return None
        left = test.left
        right = test.comparators[0]
        if isinstance(left, ast.Constant) and left.value is None:
            value_node = right
        elif isinstance(right, ast.Constant) and right.value is None:
            value_node = left
        else:
            return None
        if not isinstance(value_node, (ast.Name, ast.Attribute)):
            return None
        value = self.visit(value_node)
        if not isinstance(value.obj, Instance):
            return None
        value_types = get_type_members(value.obj.cls)
        if len(value_types) != 2:
            return None
        non_none_types = [type_ for type_ in value_types if type_.name != "NoneType"]
        if len(non_none_types) != 1:
            return None
        return value_node, non_none_types[0], isinstance(test.ops[0], ast.IsNot)

    def inline_dependencies(self, function: Function, node: ast.AST):
        objects = {}
        dependencies = function.decoration("__js_inline_dependencies__") or {}
        for name, dependency in dependencies.items():
            if not getattr(dependency, "__js__", False):
                definition = self.module.context.sources.definition_span(dependency)
                secondary = (
                    (
                        Label(
                            definition,
                            "defined here without client compilation enabled",
                        ),
                    )
                    if definition is not None
                    else ()
                )
                if getattr(dependency, "__js__", None) is False:
                    help_text = (
                        f"Remove @nojs from {dependency.__name__!r} if it should "
                        "run on the client."
                    )
                else:
                    help_text = f"Decorate {dependency.__name__!r} with @js."
                self.fail(
                    node,
                    DiagnosticCode.MISSING_JS_DECORATOR,
                    f"Inline dependency {name!r} of {function.name!r} is not "
                    "available to client code",
                    help=help_text,
                    secondary=secondary,
                )
            dependency_obj = resolve_imported(dependency, self.module)
            if not isinstance(dependency_obj, Function):
                self.fail(
                    node,
                    DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                    f"Inline dependency {name!r} of {function.name!r} must be a "
                    "function",
                )
            if dependency_obj.inline_decorator:
                definition = self.module.context.sources.definition_span(dependency)
                secondary = (
                    (Label(definition, "inline dependency defined here"),)
                    if definition is not None
                    else ()
                )
                self.fail(
                    node,
                    DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                    f"Inline dependency {name!r} of {function.name!r} does not "
                    "emit a runtime function",
                    help=(
                        f"Remove inline= from @js on {dependency.__name__!r}, or "
                        "reference a runtime function."
                    ),
                    secondary=secondary,
                )
            objects[name] = dependency_obj
        return objects

    def lower_inline_call(
        self,
        node: ast.AST,
        interface: Function,
        func: Name | Attribute,
        args: list[ast.expr],
        keywords: list[ast.keyword],
        return_type: Class | UnionType,
    ) -> Call:
        target = interface.inline_call
        assert target is not None
        target_obj = resolve_imported(target, self.module)
        if not isinstance(target_obj, Function) or target_obj.is_method:
            self.fail(
                node,
                DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                f"@js.inline call target for {interface.name!r} must be a "
                "module function",
            )
        if not target_obj.is_analyzed:
            raise DependencyError(target_obj)
        if target_obj.inline_decorator:
            self.fail(
                node,
                DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                f"@js.inline call target {target_obj.name!r} does not emit a "
                "runtime function",
            )

        receiver = None
        if (
            isinstance(func, Attribute)
            and interface.is_method
            and not interface.is_staticmethod
        ):
            receiver = func.value
        receiver_count = int(receiver is not None)
        compatible = (
            len(target_obj.params) == len(interface.params) + receiver_count
            and len(target_obj.defaults) == len(interface.defaults)
            and len(target_obj.kwonlyargs) == len(interface.kwonlyargs)
            and [default is None for default in target_obj.kw_defaults]
            == [default is None for default in interface.kw_defaults]
            and (target_obj.vararg is None) == (interface.vararg is None)
            and (target_obj.kwarg is None) == (interface.kwarg is None)
            and target_obj.is_async == interface.is_async
        )
        if not compatible:
            self.fail(
                node,
                DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                f"@js.inline call target {target_obj.name!r} is incompatible "
                f"with {interface.name!r}",
                help=(
                    "Use matching parameters, defaults, and async behavior, or "
                    "use an inline source generator for a custom transformation."
                ),
            )

        positional_names = {
            interface_param.arg: target_param.arg
            for interface_param, target_param in zip(
                interface.params,
                target_obj.params[receiver_count:],
                strict=True,
            )
        }
        keyword_names = {
            interface_param.arg: target_param.arg
            for interface_param, target_param in zip(
                interface.kwonlyargs,
                target_obj.kwonlyargs,
                strict=True,
            )
        }
        forwarded_keywords = [
            ast.keyword(
                arg=(positional_names | keyword_names).get(keyword.arg, keyword.arg),
                value=keyword.value,
            )
            for keyword in keywords
        ]
        forwarded_args = [receiver, *args] if receiver is not None else args

        if interface.returns_self and receiver is not None:
            receiver_obj = receiver.obj
            return_type = (
                receiver_obj.cls
                if isinstance(receiver_obj, Instance)
                else receiver_obj
            )
        if interface.is_async:
            awaitable = BUILTINS.search("Awaitable")
            assert isinstance(awaitable, GenericClass)
            return_type = awaitable(return_type)
        value_obj = return_type
        if isinstance(return_type, Class):
            value_obj = return_type("__call_result__", self.scope, self.func)
        call = Call(
            return_type,
            value_obj=value_obj,
            func=Name(target_obj, runtime_dependency=target_obj),
            args=forwarded_args,
            keywords=forwarded_keywords,
        )
        call.forwarded_func = func
        return call

    def call_node(
        self,
        node: ast.AST,
        return_type: Class | UnionType,
        *,
        func: Name | Attribute,
        args: list[ast.expr],
        keywords: list[ast.keyword],
        **attributes,
    ) -> Call:
        interface = func.obj
        if isinstance(interface, Function) and interface.inline_call is not None:
            return self.lower_inline_call(
                node,
                interface,
                func,
                args,
                keywords,
                return_type,
            )
        return Call(
            return_type,
            func=func,
            args=args,
            keywords=keywords,
            **attributes,
        )

    def function_reference(self, function: Function, node: ast.AST):
        if node is self.direct_call_target:
            return None
        if not function.inline_decorator and not getattr(
            function.py_obj,
            "__builtin__",
            False,
        ):
            return None

        replacement = getattr(function.py_obj, "__js_value__", None)
        value_source = getattr(function.py_obj, "__js_value_source__", None)
        if replacement is None and value_source is None:
            definition = self.module.context.sources.definition_span(function.py_obj)
            secondary = (
                (Label(definition, "inline function defined here"),)
                if definition is not None
                else ()
            )
            self.fail(
                node,
                DiagnosticCode.INLINE_FUNCTION_VALUE,
                f"Inline function {function.name!r} cannot be used as a value",
                help=(
                    f"Attach a value implementation with "
                    f"@{function.name}.value or {function.name}.value.source(...)."
                ),
                secondary=secondary,
            )

        if replacement is not None and not getattr(replacement, "__js__", False):
            definition = self.module.context.sources.definition_span(replacement)
            secondary = (
                (Label(definition, "defined here without client compilation enabled"),)
                if definition is not None
                else ()
            )
            self.fail(
                node,
                DiagnosticCode.MISSING_JS_DECORATOR,
                f"Value implementation for {function.name!r} is not available "
                "to client code",
                help=f"Decorate {replacement.__name__!r} with @js.",
                secondary=secondary,
            )

        module_name = function.py_obj.__module__
        package = self.module.container
        if module_name not in package:
            package[module_name] = Module(
                inspect.getmodule(function.py_obj),
                package,
                extensions=self.module.extensions,
                context=self.module.context,
            ).build()
        replacement_obj = package[module_name].value_implementation(function)
        if not replacement_obj.is_analyzed:
            annotate_types(replacement_obj)
        if replacement_obj.inline_decorator:
            definition = self.module.context.sources.definition_span(replacement)
            secondary = (
                (Label(definition, "value implementation defined here"),)
                if definition is not None
                else ()
            )
            self.fail(
                node,
                DiagnosticCode.INLINE_FUNCTION_VALUE,
                f"Value implementation for {function.name!r} does not emit a "
                "runtime function",
                help=(
                    f"Remove the inline implementation from "
                    f"{replacement.__name__!r}, or attach another value "
                    "implementation."
                ),
                secondary=secondary,
            )
        return replacement_obj

    def validate_sort_order(self, call, value_type, keywords, operation):
        comparison_type = keyed_comparison_type(value_type, keywords)
        if supports_order_comparison(comparison_type):
            return
        type_names = ", ".join(
            sorted(
                type_.generic_name or type_.name
                for type_ in get_type_members(comparison_type)
            )
        )
        self.fail(
            call,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            f"{operation}() cannot order values of type {type_names}",
            help=(
                "Use numeric, string, or sequence values, or pass a key "
                "function that returns those types."
            ),
        )

    def validate_call_argument_types(
        self,
        node: ast.Call,
        function: Function,
        args: list[ast.expr],
        keywords: list[ast.keyword],
        type_bindings,
    ):
        parameters = {parameter.arg: parameter for parameter in function.params}
        parameters.update(
            {parameter.arg: parameter for parameter in function.kwonlyargs}
        )
        for index, argument in enumerate(args):
            if isinstance(argument, ast.Starred):
                continue
            if index < len(function.params):
                parameter = function.params[index]
                expected_type = substitute_type_variables(
                    parameter.annotation.obj,
                    type_bindings,
                )
            elif function.vararg is not None:
                parameter = function.vararg
                expected_type = substitute_type_variables(
                    iterable_item_type(parameter.annotation.obj),
                    type_bindings,
                )
            else:
                continue
            self.validate_call_argument(
                node.args[index],
                function,
                parameter.arg,
                expected_type,
                argument,
            )

        for source, keyword in zip(node.keywords, keywords, strict=True):
            if keyword.arg is None:
                continue
            parameter = parameters.get(keyword.arg)
            if parameter is None:
                if function.kwarg is None:
                    continue
                parameter = function.kwarg
                expected_type = substitute_type_variables(
                    parameter.annotation.obj.generic_types["V"],
                    type_bindings,
                )
            else:
                expected_type = substitute_type_variables(
                    parameter.annotation.obj,
                    type_bindings,
                )
            self.validate_call_argument(
                source.value,
                function,
                parameter.arg,
                expected_type,
                keyword.value,
            )

    def validate_call_argument(
        self,
        source: ast.expr,
        function: Function,
        parameter: str,
        expected_type: Class | UnionType,
        value: ast.expr,
    ):
        expected_callable = callable_member(expected_type)
        if expected_callable is not None and (
            isinstance(value, ast.Lambda) or isinstance(value.obj, Function)
        ):
            self.validate_callable_argument(
                source,
                function,
                parameter,
                expected_callable,
                value,
            )
            return
        if is_call_argument_compatible(expected_type, value):
            return
        actual_type = analyzed_value_type(value)
        owner = None
        if function.cls is not None:
            owner = function.cls.generic_name or function.cls.name
        callable_name = f"{owner}.{function.name}" if owner else function.name
        expected = expected_type.to_annotation_str()
        actual = actual_type.to_annotation_str()
        self.fail(
            source,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"Argument {parameter!r} to {callable_name} expects {expected}, got {actual}",
            help=f"Pass a value compatible with {expected}.",
        )

    def validate_callable_argument(
        self,
        source,
        function,
        parameter,
        expected,
        value,
    ):
        callable_function = value.obj if isinstance(value.obj, Function) else None
        if isinstance(value, ast.Lambda):
            parameter_types = value.parameter_types
            return_type = value.return_type
            is_async = False
            accepts_expected_count = (
                expected.parameter_types is None
                or len(parameter_types) == len(expected.parameter_types)
            )
        elif callable_function is not None:
            parameter_types = tuple(
                argument.annotation.obj for argument in callable_function.params
            )
            if expected.parameter_types is not None:
                expected_count = len(expected.parameter_types)
                required_count = len(callable_function.params) - len(
                    callable_function.defaults
                )
                required_keyword_only = any(
                    default is None for default in callable_function.kw_defaults
                )
                accepts_expected_count = (
                    not required_keyword_only
                    and required_count <= expected_count
                    and (
                        callable_function.vararg is not None
                        or expected_count <= len(callable_function.params)
                    )
                )
                if callable_function.vararg is not None:
                    vararg_type = iterable_item_type(
                        callable_function.vararg.annotation.obj
                    )
                    parameter_types += (vararg_type,) * max(
                        0,
                        expected_count - len(parameter_types),
                    )
            else:
                accepts_expected_count = True
            return_type = (
                callable_function.return_type
                or callable_function.declared_return_type
            )
            is_async = callable_function.is_async
        expected_return = expected.return_type
        if is_async:
            if not (
                isinstance(expected_return, Class)
                and expected_return.generic_name == "Awaitable"
            ):
                self.fail(
                    source,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Argument {parameter!r} to {function.name} cannot be async",
                    help="Pass a synchronous callable or expect an Awaitable result.",
                )
            expected_return = expected_return.generic_types["T"]
        definition = (
            self.module.context.sources.definition_span(callable_function.py_obj)
            if callable_function is not None
            else None
        )
        secondary = (
            (Label(definition, "callable defined here"),)
            if definition is not None
            else ()
        )
        if expected.parameter_types is not None:
            if not accepts_expected_count:
                expected_count = len(expected.parameter_types)
                argument_label = "argument" if expected_count == 1 else "arguments"
                self.fail(
                    source,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Argument {parameter!r} to {function.name} expects a callable "
                    f"that accepts {expected_count} positional {argument_label}",
                    help="Use a callable with the annotated parameter shape.",
                    secondary=secondary,
                )
            dispatch = (
                callable_function.decoration("__js_dispatch__")
                if callable_function is not None
                else None
            )
            for expected_parameter, actual_parameter in zip(
                expected.parameter_types,
                parameter_types[: len(expected.parameter_types)],
                strict=True,
            ):
                if dispatch is not None and supports_dunder(
                    expected_parameter,
                    dispatch,
                ):
                    continue
                if not is_return_type_compatible(actual_parameter, expected_parameter):
                    self.fail(
                        source,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        f"Callable argument {parameter!r} to {function.name} accepts "
                        f"{actual_parameter.to_annotation_str()}, but must accept "
                        f"{expected_parameter.to_annotation_str()}",
                        help=(
                            "Widen the callable parameter annotation to accept "
                            "every input value."
                        ),
                        secondary=secondary,
                    )
        if return_type is not None and not is_return_type_compatible(
            expected_return,
            return_type,
        ):
            self.fail(
                source,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Callable argument {parameter!r} to {function.name} returns "
                f"{return_type.to_annotation_str()}, expected "
                f"{expected_return.to_annotation_str()}",
                help="Change the callable return annotation or returned values.",
                secondary=secondary,
            )

    def runtime_contract_methods(self, func, function, args):
        contract = function.runtime_dunders
        if contract is None:
            return ()
        item_of, method_names = contract
        if item_of == "self":
            if not isinstance(func, Attribute):
                return ()
            receiver = func.value.obj
            collection_type = (
                receiver.cls if isinstance(receiver, Instance) else receiver
            )
        else:
            if item_of >= len(args):
                return ()
            collection_type = analyzed_value_type(args[item_of])
        item_type = iterable_item_type(collection_type)
        if item_type is None:
            return ()
        if method_names == ("__bool__", "__len__"):
            return truthiness_methods(item_type)
        return runtime_dunder_methods(item_type, *method_names)

    def analyze_getattr(self, node, function, args):
        if len(args) not in {2, 3}:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "getattr() requires an object, attribute name, and optional default",
            )
        name = args[1]
        if not isinstance(name, Constant) or not isinstance(name.value, str):
            self.fail(
                node.args[1],
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "getattr() requires a string literal attribute name",
                help=(
                    "Use direct typed attribute access or branch on the name "
                    "before calling getattr()."
                ),
            )

        receiver = args[0]
        receiver_obj = analyzed_value_object(receiver)
        union_type = self.receiver_union(receiver_obj)
        missing = False
        if len(args) == 3 and union_type is None:
            try:
                receiver_obj.find(name.value)
            except NameError:
                receiver_type = (
                    receiver_obj.cls
                    if isinstance(receiver_obj, Instance)
                    else receiver_obj
                )
                initializer = getattr(receiver_type, "init", None)
                if initializer is not None and not initializer.is_analyzed:
                    raise DependencyError(initializer) from None
                missing = True

        if missing:
            result_type = analyzed_value_type(args[2])
            value_obj = args[2].obj
            return Call(
                result_type,
                value_obj=value_obj,
                func=Name(function),
                args=args,
                keywords=[],
            )

        attribute = ast.copy_location(
            ast.Attribute(
                value=node.args[0],
                attr=name.value,
                ctx=ast.Load(),
            ),
            node,
        )
        result = self.visit(attribute)
        if len(args) != 3:
            return result

        if isinstance(result.obj, Function):
            return BoundGetattr(
                result.obj,
                receiver=args[0],
                default=args[2],
                lineno=node.lineno,
            )

        result_type = analyzed_value_type(result)
        value_obj = result.obj
        if isinstance(value_obj, Instance):
            value_obj = result_type("__getattr_result__", self.scope, self.func)
        return Call(
            result_type,
            value_obj=value_obj,
            func=Name(function),
            args=args,
            keywords=[],
            runtime_methods=getattr(result, "property_getters", ()),
        )

    def get_isinstance_narrowing(self, test):
        if (
            not isinstance(test, ast.Call)
            or not isinstance(test.func, ast.Name)
            or test.func.id != "isinstance"
            or len(test.args) != 2
            or not isinstance(test.args[0], (ast.Name, ast.Attribute))
            or not isinstance(test.args[1], ast.Name)
        ):
            return None
        value_type = self.visit(test.args[1]).obj
        if isinstance(value_type, GenericClass):
            object_type = BUILTINS.search("object")
            if value_type.name == "dict":
                value_type = BUILTINS.search("dict")(object_type, object_type)
            elif value_type.name in ("list", "set"):
                value_type = BUILTINS.search(value_type.name)(object_type)
            else:
                raise NotImplementedError
        assert isinstance(value_type, Class)
        return test.args[0], value_type

    def get_truthiness_narrowing(self, test):
        if not isinstance(test, (ast.Name, ast.Attribute)):
            return None
        value_type = analyzed_value_type(self.visit(test))
        if not isinstance(value_type, UnionType):
            return None
        non_none_types = [
            type_ for type_ in value_type.types if type_.name != "NoneType"
        ]
        if len(non_none_types) == len(value_type.types):
            return None
        narrowed_type = UnionType(types=non_none_types).type
        return test, narrowed_type

    def get_literal_narrowing(self, test, when_true):
        if (
            not isinstance(test, ast.Compare)
            or len(test.ops) != 1
            or len(test.comparators) != 1
            or not isinstance(test.ops[0], (ast.Eq, ast.NotEq))
        ):
            return None
        left, right = test.left, test.comparators[0]
        if isinstance(left, ast.Constant) and isinstance(
            right, (ast.Name, ast.Attribute)
        ):
            value_node, literal = right, left.value
        elif isinstance(right, ast.Constant) and isinstance(
            left, (ast.Name, ast.Attribute)
        ):
            value_node, literal = left, right.value
        else:
            return None
        if not isinstance(literal, str):
            return None
        value_type = analyzed_value_type(self.visit(value_node))
        if not any(
            isinstance(member, LiteralClass)
            for member in get_type_members(value_type)
        ):
            return None
        keep_equal = when_true == isinstance(test.ops[0], ast.Eq)
        narrowed = UnionType()
        for member in get_type_members(value_type):
            if not isinstance(member, LiteralClass):
                if not keep_equal or member.name == "str":
                    narrowed.add(member)
                continue
            values = tuple(
                value
                for value in member.values
                if (value == literal) == keep_equal
            )
            if values:
                narrowed.add(literal_type(values, member.scope))
        if not list(narrowed.types):
            return None
        return value_node, narrowed.type

    def get_condition_narrowings(self, test, when_true):
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return self.get_condition_narrowings(test.operand, not when_true)

        narrowing = self.get_none_identity_narrowing(test)
        if narrowing is not None:
            value_node, value_type, non_none_when_true = narrowing
            if non_none_when_true == when_true:
                return [(value_node, value_type)]
            return []

        narrowing = self.get_isinstance_narrowing(test)
        if narrowing is not None:
            return [narrowing] if when_true else []

        narrowing = self.get_literal_narrowing(test, when_true)
        if narrowing is not None:
            return [narrowing]

        narrowing = self.get_truthiness_narrowing(test)
        if narrowing is not None:
            return [narrowing] if when_true else []

        if not isinstance(test, ast.BoolOp):
            return []
        if isinstance(test.op, ast.And):
            all_values_are_known = when_true
        else:
            assert isinstance(test.op, ast.Or)
            all_values_are_known = not when_true
        if not all_values_are_known:
            return []
        narrowings = []
        visitor = self
        for value in test.values:
            value_narrowings = visitor.get_condition_narrowings(value, when_true)
            narrowings.extend(value_narrowings)
            for value_node, value_type in value_narrowings:
                visitor = visitor.narrow(value_node, value_type)
        return narrowings

    def narrow_for_condition(self, test, when_true):
        visitor = self
        for value_node, value_type in self.get_condition_narrowings(test, when_true):
            visitor = visitor.narrow(value_node, value_type)
        return visitor

    def narrow_after_if(self, source: ast.If, analyzed: ast.If):
        body_falls_through = body_can_fall_through(
            analyzed.body,
            loop_control_exits=True,
        )
        orelse_falls_through = body_can_fall_through(
            analyzed.orelse,
            loop_control_exits=True,
        )
        if body_falls_through == orelse_falls_through:
            if body_falls_through and (
                initialized := self.initialized_optional(source, analyzed)
            ) is not None:
                return self.narrow(*initialized)
            return self

        if body_falls_through:
            visitor = self.narrow_for_condition(source.test, True)
            source_branch = source.body
            analyzed_branch = analyzed.body
        else:
            visitor = self.narrow_for_condition(source.test, False)
            source_branch = source.orelse
            analyzed_branch = analyzed.orelse

        if (
            len(source_branch) == 1
            and len(analyzed_branch) == 1
            and isinstance(source_branch[0], ast.If)
            and isinstance(analyzed_branch[0], ast.If)
        ):
            return visitor.narrow_after_if(source_branch[0], analyzed_branch[0])
        return visitor

    def initialized_optional(self, source: ast.If, analyzed: ast.If):
        narrowing = self.get_none_identity_narrowing(source.test)
        if narrowing is None:
            return None
        value_node, value_type, non_none_when_true = narrowing
        none_branch = analyzed.orelse if non_none_when_true else analyzed.body
        assigned_type = self.last_direct_assignment_type(none_branch, value_node)
        if assigned_type is None or not is_return_type_compatible(
            value_type, assigned_type
        ):
            return None
        return value_node, value_type

    @staticmethod
    def last_direct_assignment_type(statements, target_node):
        target_name = ast.unparse(target_node)
        for statement in reversed(statements):
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            elif isinstance(statement, ast.Assign):
                targets = statement.targets
            else:
                continue
            if any(ast.unparse(target) == target_name for target in targets):
                return analyzed_value_type(statement.value)
        return None

    def visit_body(self, statements):
        body = []
        narrow_visitor = self
        for statement in statements:
            reassignment_target = None
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                try:
                    narrow_visitor.declared_local(statement.targets[0].id)
                except NameError:
                    pass
                else:
                    reassignment_target = statement.targets[0]
            stmt = narrow_visitor.visit(statement)

            if isinstance(stmt, ast.Assert):
                test = stmt.test
                if (
                    isinstance(test, ast.Call)
                    and isinstance(test.func, ast.Name)
                    and test.func.id == "isinstance"
                ):
                    args = test.args
                    assert len(args) == 2
                    assert all(isinstance(a, ast.Name) for a in args)
                    value_type = args[1].obj
                    assert isinstance(value_type, Class)
                    narrow_visitor = narrow_visitor.narrow(args[0], value_type)
                    continue

            if isinstance(statement, ast.If):
                narrow_visitor = narrow_visitor.narrow_after_if(statement, stmt)

            if reassignment_target is not None:
                analyzed_statements = stmt if isinstance(stmt, list) else [stmt]
                assigned_type = self.last_direct_assignment_type(
                    analyzed_statements,
                    reassignment_target,
                )
                if assigned_type is not None:
                    narrow_visitor = narrow_visitor.narrow(
                        reassignment_target,
                        assigned_type,
                    )

            if isinstance(stmt, list):
                body.extend(stmt)
            else:
                body.append(stmt)
        return body

    # region assignment & lookup

    def analyze_assignment_value(self, value_node, annotation_node=None):
        declared_type = None
        if annotation_node:
            annotation = self.visit_type_annotation(annotation_node).obj
            if isinstance(annotation, (Class, UnionType)):
                declared_type = annotation

        value = self.visit_contextual_expression(value_node, declared_type)
        if declared_type is not None:
            apply_typed_dict_literal(value, declared_type)

        inferred_type = None
        if isinstance(value.obj, (Class, UnionType)):
            inferred_type = value.obj
        elif isinstance(value.obj, (Instance, Function)):
            inferred_type = value.obj.cls

        builtin_class = (
            self.func.cls is not None
            and self.func.cls.py_obj.__dict__.get("__builtin__", False)
        )
        if (
            declared_type is not None
            and inferred_type is not None
            and not builtin_class
            and not isinstance(value_node, (ast.Name, ast.Attribute, ast.Call))
            and not is_return_type_compatible(declared_type, inferred_type)
        ):
            expected = declared_type.to_annotation_str()
            actual = inferred_type.to_annotation_str()
            self.fail(
                value_node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"Cannot assign {actual} to a value of type {expected}",
                help=f"Assign a value compatible with {expected}.",
            )

        return AssignmentValue(value, declared_type, inferred_type)

    def apply_contextual_collection_type(self, assignment_value, target_node):
        if assignment_value.storage_type is not None:
            return
        value = assignment_value.node
        if not isinstance(value, (List, Dict)) or not isinstance(value.obj, GenericClass):
            return
        if not isinstance(target_node, (ast.Name, ast.Attribute)):
            return
        try:
            if isinstance(target_node, ast.Name):
                target_obj = self.scope.lookup(target_node.id)
            else:
                self.assignment_target = target_node
                try:
                    target_obj = self.visit(target_node).obj
                finally:
                    self.assignment_target = None
        except NameError:
            return
        if not isinstance(target_obj, Instance):
            return
        target_type = target_obj.cls
        if isinstance(target_type, UnionType):
            matching_types = [
                member
                for member in target_type.types
                if member.generic_name == value.obj.name
            ]
            if len(matching_types) == 1:
                target_type = matching_types[0]
        if isinstance(target_type, Class) and target_type.generic_name == value.obj.name:
            value.obj = target_type
            assignment_value.inferred_type = target_type

    def resolve_assignment_target(self, target, value_type: Class | UnionType):
        if isinstance(target, ast.Attribute):
            source_target = target
            try:
                self.assignment_target = target
                try:
                    target = self.visit(target)
                finally:
                    self.assignment_target = None
            except (NameError, DependencyError) as e:
                parent = self.visit(target.value)
                assert isinstance(parent.obj, Instance)
                if parent.obj.name == "self":
                    value_init = parent.obj.cls.init
                    if (
                        value_init is not None
                        and value_init is not self.func
                        and not value_init.is_analyzed
                    ):
                        raise DependencyError(value_init) from None
                    attr = value_type(target.attr, parent.obj.scope, parent.obj)
                    parent.obj.add(attr)
                    target = Attribute(
                        attr,
                        value=parent,
                        attr=target.attr,
                        lineno=target.lineno,
                    )
                else:
                    raise e
            receiver = analyzed_value_object(target.value)
            if (
                isinstance(receiver, Instance)
                and getattr(receiver.cls, "is_frozen_dataclass", False)
                and self.func is not receiver.cls.init
            ):
                self.fail(
                    source_target,
                    DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                    f"Cannot assign to field {target.attr!r} of frozen "
                    f"dataclass {receiver.cls.name!r}",
                    help="Remove frozen=True or create a new value instead.",
                )
            if target.union_fields:
                receiver_obj = analyzed_value_object(target.value)
                union_type = self.receiver_union(receiver_obj)
                assert union_type is not None
                incompatible = [
                    (member_type, field)
                    for member_type, field in zip(
                        union_type.types,
                        target.union_fields,
                        strict=True,
                    )
                    if not is_return_type_compatible(field.cls, value_type)
                ]
                if incompatible:
                    expected = ", ".join(
                        f"{member_type.name}.{target.attr} expects "
                        f"{field.cls.to_annotation_str()}"
                        for member_type, field in incompatible
                    )
                    actual = value_type.to_annotation_str()
                    union_name = union_type.to_annotation_str(" | ")
                    self.fail(
                        source_target,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Cannot assign {actual} to {target.attr!r} through "
                        f"{union_name}",
                        help=(
                            f"{expected}. A union field assignment must be "
                            "compatible with every possible receiver; narrow the "
                            "receiver with isinstance() otherwise."
                        ),
                    )
                return target, False
            if target.property_setters:
                incompatible = []
                for setter, expected_type in zip(
                    target.property_setters,
                    target.property_setter_types,
                    strict=True,
                ):
                    if not is_return_type_compatible(expected_type, value_type):
                        incompatible.append((setter.cls, expected_type))
                if incompatible:
                    expected = ", ".join(
                        f"{cls.name}.{target.attr} expects "
                        f"{expected_type.to_annotation_str()}"
                        for cls, expected_type in incompatible
                    )
                    actual = value_type.to_annotation_str()
                    self.fail(
                        source_target,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Cannot assign {actual} to property {target.attr!r}",
                        help=f"{expected}.",
                    )
                return target, False
            if target.obj.cls is not value_type:
                current_self = target.value.obj
                other_self = target.obj.container
                inherited = (
                    isinstance(current_self, Instance)
                    and isinstance(other_self, Instance)
                    and current_self.name == "self"
                    and current_self is not other_self
                )
                if inherited:
                    attr = value_type(target.attr, current_self.scope, current_self)
                    current_self.add(attr)
                    target = Attribute(
                        attr,
                        value=target.value,
                        attr=target.attr,
                        lineno=target.lineno,
                    )
                elif not is_return_type_compatible(target.obj.cls, value_type):
                    expected = target.obj.cls.to_annotation_str()
                    actual = value_type.to_annotation_str()
                    self.fail(
                        source_target,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Cannot assign {actual} to {target.attr!r} of type {expected}",
                        help=(
                            f"Assign a value compatible with {expected} or change the "
                            f"annotation for {target.attr!r}."
                        ),
                    )
            return target, False
        elif isinstance(target, ast.Name):
            try:
                existing = self.declared_local(target.id)
                if (
                    isinstance(existing, Instance)
                    and value_type is not None
                    and not is_return_type_compatible(existing.cls, value_type)
                ):
                    expected = existing.cls.to_annotation_str()
                    actual = value_type.to_annotation_str()
                    self.fail(
                        target,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Cannot assign {actual} to {target.id!r} of type {expected}",
                        help=(
                            f"Assign a value compatible with {expected} or change "
                            f"the annotation for {target.id!r}."
                        ),
                    )
                return target, False
            except NameError:
                if not value_type:
                    self.fail(
                        target,
                        DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                        f"Type of {target.id!r} cannot be inferred",
                        help=f"Add an explicit type annotation for {target.id!r}.",
                    )
                self.scope.add(value_type(target.id, self.scope, self.func))
                return target, True
        elif isinstance(target, ast.Subscript):
            target = ast.Subscript(
                slice=target.slice,
                value=self.visit(target.value),
                lineno=target.lineno,
            )
            return target, False
        else:
            raise NotImplementedError

    def declared_local(self, name: str):
        declared = None
        scope = self.scope
        while isinstance(scope, LocalScope):
            if value := scope.names.get(name):
                declared = value
            scope = scope.parent
        if declared is None:
            raise NameError(name)
        return declared

    def visit_Assign(self, node: ast.Assign):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
            target = node.targets[0]
            if isinstance(target.slice, ast.Slice):
                method_name = "__setslice__"
                args = [node.value, *self.slice_parts(target.slice)]
            else:
                method_name = "__setitem__"
                args = [target.slice, node.value]
            method = ast.copy_location(
                ast.Attribute(value=target.value, attr=method_name, ctx=ast.Load()),
                target,
            )
            call = ast.copy_location(
                ast.Call(func=method, args=args, keywords=[]),
                node,
            )
            return ast.Expr(value=self.visit(call))

        assignment_value = self.analyze_assignment_value(node.value)
        unpacking_targets = [
            target
            for target in node.targets
            if isinstance(target, (ast.Tuple, ast.List))
        ]
        if unpacking_targets and len(node.targets) != 1:
            self.fail(
                unpacking_targets[0],
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "chained unpacking assignments are not supported",
                help="Use a separate unpacking statement for each target group.",
            )
        if unpacking_targets:
            return self.resolve_unpacking_assignment(
                unpacking_targets[0], assignment_value
            )
        if len(node.targets) == 1:
            self.apply_contextual_collection_type(assignment_value, node.targets[0])
        target_values = [(node.targets[-1], assignment_value.node)]
        target_values.extend(
            zip(reversed(node.targets[:-1]), reversed(node.targets[1:]), strict=True)
        )

        assignments = []
        for target_node, value in target_values:
            target, is_new_name = self.resolve_assignment_target(
                target_node, assignment_value.storage_type
            )
            if is_new_name:
                assignments.append(
                    ast.AnnAssign(
                        target=target,
                        annotation=assignment_value.storage_type.annotation,
                        value=value,
                        simple=True,
                        lineno=target.lineno,
                    )
                )
            else:
                assignments.append(
                    ast.Assign(
                        targets=[target],
                        value=value,
                        type_comment=None,
                        lineno=target.lineno,
                    )
                )
        return assignments

    def resolve_unpacking_assignment(
        self,
        target_node: ast.Tuple | ast.List,
        assignment_value: AssignmentValue,
    ):
        target_node, value_type, value, literal_value = self.prepare_starred_unpacking(
            target_node,
            assignment_value,
        )
        value = self.checked_unpack_value(target_node, value_type, value)
        if any(isinstance(item, ast.Subscript) for item in target_node.elts):
            return self.resolve_individual_unpacking_assignment(
                target_node,
                value_type,
                value,
            )
        target, declares_name, assigns_non_name = self.resolve_unpacking_target(
            target_node,
            value_type,
            literal_value=literal_value,
            root=True,
        )
        if declares_name and assigns_non_name:
            self.fail(
                target_node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "cannot mix new local names and attribute unpacking targets",
                help="Declare the local names before the unpacking assignment.",
            )
        assignment = ast.Assign(
            targets=[target],
            value=value,
            type_comment=None,
            lineno=target_node.lineno,
        )
        assignment.declares_name = declares_name
        return assignment

    def checked_unpack_value(self, target_node, value_type, value):
        if (
            isinstance(value_type, Class)
            and value_type.generic_name == "list"
            and not isinstance(value, List)
        ):
            unpack_exact = BUILTINS.search("unpack_exact")
            assert isinstance(unpack_exact, Function)
            expected = Constant(
                BUILTINS.search("int"),
                value=len(target_node.elts),
            )
            value = self.call_node(
                target_node,
                value_type,
                func=Name(unpack_exact),
                args=[value, expected],
                keywords=[],
                dependency_objects=self.inline_dependencies(unpack_exact, target_node),
            )
        return value

    def resolve_individual_unpacking_assignment(
        self,
        target: ast.Tuple | ast.List,
        value_type,
        value,
    ):
        if any(isinstance(item, (ast.Tuple, ast.List, ast.Starred)) for item in target.elts):
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "nested unpacking with subscript targets is not supported",
                help="Unpack the nested value in a separate assignment.",
            )
        if not isinstance(value_type, Class) or value_type.generic_name not in {
            "list",
            "tuple",
        }:
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "unpacking requires a statically typed tuple or list",
                help="Return a typed tuple or list before unpacking it.",
            )
        if value_type.generic_name == "tuple":
            item_types = list(value_type.generic_types.values())
        else:
            item_types = [value_type.generic_types["V"]] * len(target.elts)
        if len(item_types) != len(target.elts):
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"cannot unpack {len(item_types)} values into "
                f"{len(target.elts)} targets",
                help="Use one target for each statically known value.",
            )

        assignments = []
        for index, (item_target, item_type) in enumerate(
            zip(target.elts, item_types, strict=True)
        ):
            item_obj = item_type("$unpack", self.scope, self.func)
            item = UnpackItem(item_obj, index, lineno=target.lineno)
            assignment = ast.Assign(
                targets=[item_target],
                value=item,
                lineno=target.lineno,
            )
            analyzed = self.visit_Assign(assignment)
            assignments.extend(analyzed if isinstance(analyzed, list) else [analyzed])
        return UnpackAssignment(value, assignments, lineno=target.lineno)

    def visit_UnpackItem(self, node):
        return node

    def prepare_starred_unpacking(
        self,
        target: ast.Tuple | ast.List,
        assignment_value: AssignmentValue,
    ) -> tuple[
        ast.Tuple | ast.List,
        Class | UnionType,
        ast.expr,
        ast.expr,
    ]:
        starred = next(
            (item for item in target.elts if isinstance(item, ast.Starred)),
            None,
        )
        value_type = assignment_value.storage_type
        value = assignment_value.node
        if starred is None:
            return target, value_type, value, value
        if not isinstance(value_type, Class) or value_type.generic_name not in {
            "list",
            "tuple",
        }:
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "unpacking requires a statically typed tuple or list",
                help="Return a typed tuple or list before unpacking it.",
            )

        star_index = target.elts.index(starred)
        before = star_index
        after = len(target.elts) - star_index - 1
        required = before + after
        known_count = len(value.elts) if isinstance(value, (List, Tuple)) else None
        if known_count is not None and known_count < required:
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"not enough values to unpack (expected at least {required}, "
                f"got {known_count})",
                help="Provide enough values for every non-starred target.",
            )
        if value_type.generic_name == "tuple":
            item_types = list(value_type.generic_types.values())
            suffix_start = len(item_types) - after
            rest_types = item_types[before:suffix_start]
            rest_item_type = (
                UnionType(types=rest_types).type
                if rest_types
                else BUILTINS.search("object")
            )
            prefix_types = item_types[:before]
            suffix_types = item_types[suffix_start:]
        else:
            rest_item_type = value_type.generic_types["V"]
            prefix_types = [rest_item_type] * before
            suffix_types = [rest_item_type] * after

        list_type = BUILTINS.search("list")
        tuple_type = BUILTINS.search("tuple")
        assert isinstance(list_type, GenericClass)
        assert isinstance(tuple_type, GenericClass)
        transformed_type = tuple_type(
            *prefix_types,
            list_type(rest_item_type),
            *suffix_types,
        )
        transformed_target = type(target)(
            elts=[
                starred.value if item is starred else item
                for item in target.elts
            ],
            ctx=target.ctx,
        )
        ast.copy_location(transformed_target, target)
        literal_value = value
        if isinstance(value, (List, Tuple)):
            suffix_start = len(value.elts) - after
            literal_value = type(value)(
                transformed_type,
                elts=[
                    *value.elts[:before],
                    ast.List(
                        elts=value.elts[before:suffix_start],
                        ctx=ast.Load(),
                    ),
                    *value.elts[suffix_start:],
                ],
                ctx=ast.Load(),
            )
            ast.copy_location(literal_value, value)

        unpack_starred = BUILTINS.search("unpack_starred")
        assert isinstance(unpack_starred, Function)
        value = self.call_node(
            target,
            transformed_type,
            func=Name(unpack_starred),
            args=[
                value,
                Constant(BUILTINS.search("int"), value=before),
                Constant(BUILTINS.search("int"), value=after),
            ],
            keywords=[],
            dependency_objects=self.inline_dependencies(unpack_starred, target),
        )
        return transformed_target, transformed_type, value, literal_value

    def resolve_unpacking_target(
        self,
        target,
        value_type,
        *,
        literal_value=None,
        root=False,
    ):
        if isinstance(target, (ast.Name, ast.Attribute)):
            resolved, declares_name = self.resolve_assignment_target(
                target,
                value_type,
            )
            return resolved, declares_name, isinstance(target, ast.Attribute)
        if isinstance(target, ast.Starred):
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "starred unpacking targets are not supported",
                help="Use slicing to collect the remaining values explicitly.",
            )
        if not isinstance(target, (ast.Tuple, ast.List)):
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "unsupported unpacking target",
                help="Unpack into local names or instance attributes.",
            )
        starred = next(
            (item for item in target.elts if isinstance(item, ast.Starred)),
            None,
        )
        if starred is not None:
            self.fail(
                starred,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "starred unpacking targets are not supported",
                help="Use slicing to collect the remaining values explicitly.",
            )
        if not isinstance(value_type, Class) or value_type.generic_name not in {
            "list",
            "tuple",
        }:
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "unpacking requires a statically typed tuple or list",
                help="Return a typed tuple or list before unpacking it.",
            )

        if value_type.generic_name == "tuple":
            item_types = list(value_type.generic_types.values())
            known_count = len(item_types)
        else:
            if not root and not isinstance(literal_value, (List, Tuple)):
                self.fail(
                    target,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "nested list unpacking requires a statically known length",
                    help="Use a tuple for the nested value or unpack it separately.",
                )
            item_types = [value_type.generic_types["V"]] * len(target.elts)
            known_count = (
                len(literal_value.elts)
                if isinstance(literal_value, (List, Tuple))
                else None
            )
        if known_count is not None and len(target.elts) != known_count:
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"cannot unpack {known_count} values into "
                f"{len(target.elts)} targets",
                help="Use one target for each statically known value.",
            )

        resolved_items = []
        declares_name = False
        assigns_non_name = False
        literal_items = (
            literal_value.elts
            if isinstance(literal_value, (List, Tuple))
            else []
        )
        for index, (item_target, item_type) in enumerate(
            zip(target.elts, item_types, strict=True)
        ):
            item_literal = literal_items[index] if literal_items else None
            resolved, declares, non_name = self.resolve_unpacking_target(
                item_target,
                item_type,
                literal_value=item_literal,
            )
            resolved_items.append(resolved)
            declares_name = declares_name or declares
            assigns_non_name = assigns_non_name or non_name
        return (
            type(target)(elts=resolved_items, ctx=ast.Store()),
            declares_name,
            assigns_non_name,
        )

    def visit_AnnAssign(self, node: ast.AnnAssign):
        assignment_value = self.analyze_assignment_value(node.value, node.annotation)
        target, is_new_name = self.resolve_assignment_target(
            node.target, assignment_value.storage_type
        )
        if isinstance(node.target, ast.Attribute):
            return ast.AnnAssign(
                target=target,
                annotation=target.obj.cls.annotation,
                value=assignment_value.node,
                simple=False,
                lineno=target.lineno,
            )
        if is_new_name:
            return ast.AnnAssign(
                target=target,
                annotation=assignment_value.storage_type.annotation,
                value=assignment_value.node,
                simple=True,
                lineno=target.lineno,
            )
        return ast.Assign(
            targets=[target],
            value=assignment_value.node,
            type_comment=None,
            lineno=target.lineno,
        )

    def visit_AugAssign(self, node: ast.AugAssign):
        bin_op_value = ast.BinOp(
            left=node.target,
            op=node.op,
            right=node.value,
        )
        return self.visit_Assign(ast.Assign(targets=[node.target], value=bin_op_value))

    @staticmethod
    def slice_parts(node: ast.Slice):
        return [
            part if part is not None else ast.Constant(value=None)
            for part in (node.lower, node.upper, node.step)
        ]

    def visit_Slice(self, node: ast.Slice):
        lower, upper, step = self.slice_parts(node)
        return ast.Slice(
            lower=self.visit(lower),
            upper=self.visit(upper),
            step=self.visit(step),
        )

    def visit_Delete(self, node: ast.Delete):
        statements = []
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                if isinstance(target.slice, ast.Slice):
                    method_name = "__delslice__"
                    args = self.slice_parts(target.slice)
                else:
                    method_name = "__delitem__"
                    args = [target.slice]
                method = ast.copy_location(
                    ast.Attribute(
                        value=target.value,
                        attr=method_name,
                        ctx=ast.Load(),
                    ),
                    target,
                )
                call = ast.copy_location(
                    ast.Call(func=method, args=args, keywords=[]),
                    target,
                )
                statements.append(ast.Expr(value=self.visit(call)))
            else:
                resolved = self.visit(target)
                if getattr(resolved, "property_getters", ()):
                    self.fail(
                        target,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        "property deletion is not supported",
                        help="Use an explicit method for client-side deletion.",
                    )
                statements.append(ast.Delete(targets=[resolved]))
        return statements

    def visit_Attribute(self, node: ast.Attribute):
        value = self.visit(node.value)
        value_obj = analyzed_value_object(value)
        union_type = self.receiver_union(value_obj)
        resolution = None
        try:
            if node is self.assignment_target:
                if union_type is None:
                    attr = value_obj.find(node.attr)
                else:
                    resolution = self.resolve_union_attribute(
                        node,
                        union_type,
                        for_assignment=True,
                    )
                    if isinstance(resolution, UnionMethodResolution):
                        if not all(
                            method.is_property for method in resolution.methods
                        ):
                            self.fail(
                                node,
                                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                                f"Cannot assign to method {node.attr!r} through "
                                f"{union_type.to_annotation_str(' | ')}",
                                help=(
                                    "Narrow the receiver before replacing a method."
                                ),
                            )
                        attr = resolution.methods[0]
                    else:
                        attr = resolution.value_type(
                            ast.unparse(node),
                            self.scope,
                            self.func,
                        )
            else:
                try:
                    attr = self.scope.lookup(ast.unparse(node))
                except NameError:
                    if union_type is None:
                        attr = value_obj.find(node.attr)
                    else:
                        resolution = self.resolve_union_attribute(node, union_type)
                        if isinstance(resolution, UnionFieldResolution):
                            attr = resolution.value_type(
                                ast.unparse(node),
                                self.scope,
                                self.func,
                            )
                        else:
                            attr = resolution.methods[0]
        except NameError:
            value_init = None
            if isinstance(value_obj, Instance):
                value_init = value_obj.cls.init
            elif isinstance(value_obj, Class):
                value_init = value_obj.init
            if (
                value_init
                and value_init is not self.func
                and not value_init.is_analyzed
            ):
                raise DependencyError(value_init) from None
            if node is self.assignment_target:
                raise
            if isinstance(value_obj, Instance) and value_obj.name == "self":
                self.module.context.attribute_lookup_error(
                    self.func.source_fragment,
                    node,
                    value_obj.cls.name,
                    self.attribute_names(value_obj),
                    value_init.py_func if value_init is not None else None,
                )
            raise

        union_fields = ()
        union_functions = ()
        union_return_type = None
        module_import_alias = None
        if isinstance(value_obj, ModuleAlias):
            module_import_alias = value_obj.import_member(attr)
        if union_type is not None:
            if isinstance(resolution, UnionFieldResolution):
                union_fields = resolution.fields
            elif isinstance(resolution, UnionMethodResolution):
                union_functions = resolution.methods
                union_return_type = resolution.return_type
        attribute = Attribute(
            attr,
            value=value,
            attr=node.attr,
            lineno=node.lineno,
            union_fields=union_fields,
            union_functions=union_functions,
            union_return_type=union_return_type,
            module_import_alias=module_import_alias,
        )
        if isinstance(attr, Function) and attr.is_property:
            if node is self.assignment_target:
                getters = (
                    resolution.methods
                    if isinstance(resolution, UnionMethodResolution)
                    else (attr,)
                )
                missing_setters = [
                    getter.cls.name
                    for getter in getters
                    if getter.property_setter is None
                ]
                if missing_setters:
                    self.fail(
                        node,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Property {node.attr!r} is read-only",
                        help=(
                            "Define a client-side setter on "
                            f"{', '.join(missing_setters)}."
                        ),
                    )
                setters = tuple(
                    getter.property_setter
                    for getter in getters
                    if getter.property_setter is not None
                )
                setter_types = tuple(
                    self.property_setter_type(node, setter) for setter in setters
                )
                target_type = None
                for setter_type in setter_types:
                    target_type = merge_return_types(target_type, setter_type)
                assert isinstance(target_type, (Class, UnionType))
                attribute.obj = target_type(node.attr, self.scope, self.func)
                attribute.property_setters = setters
                attribute.property_setter_types = setter_types
                return attribute
            if not attr.is_analyzed and attr.declared_return_type is None:
                raise DependencyError(attr)
            return_type = (
                union_return_type or attr.return_type or attr.declared_return_type
            )
            assert isinstance(return_type, (Class, UnionType))
            value_obj = return_type
            if isinstance(return_type, Class):
                value_obj = return_type(node.attr, self.scope, self.func)
            attribute.obj = value_obj
            attribute.property_getters = (
                resolution.methods
                if isinstance(resolution, UnionMethodResolution)
                else (attr,)
            )
            return attribute
        if isinstance(attr, Function):
            runtime_dependency = self.function_reference(attr, node)
            if runtime_dependency is not None:
                return RuntimeFunctionReference(
                    attr,
                    runtime_dependency,
                    None
                    if attr.is_staticmethod or isinstance(value_obj, ModuleAlias)
                    else value,
                    lineno=node.lineno,
                )
        return attribute

    def visit_Name(self, node: ast.Name):
        try:
            value = self.scope.search(node.id)
        except NameError:
            self.fail_name_lookup(node)
        if node.id == "super":
            return Name(value, id="super")
        elif node.id == "cls" and self.func.cls == value:
            return Name(value, id="this")
        name = value.name
        if node.id != value.name and not getattr(value.py_obj, "__builtin__", False):
            module = (
                self.func.cls.container if self.func.is_method else self.func.container
            )
            if any(
                imported is value and local_name == node.id
                for imported_values in module.imported.values()
                for imported, local_name in imported_values
            ):
                name = node.id
        runtime_dependency = None
        if isinstance(value, Function):
            runtime_dependency = self.function_reference(value, node)
        elif isinstance(value, Class):
            runtime_dependency = runtime_class_dependency(value, self.module)
        return Name(value, id=name, runtime_dependency=runtime_dependency)

    def visit_Starred(self, node: ast.Starred):
        value = self.visit(node.value)
        item_type = next(iter(value.obj.cls.generic_types.values()))
        return Starred(item_type, value=value)

    def visit_Subscript(self, node: ast.Subscript):
        slice = self.visit(node.slice)
        value = self.visit(node.value)
        receiver_obj = analyzed_value_object(value)
        receiver_type = (
            receiver_obj.cls if isinstance(receiver_obj, Instance) else receiver_obj
        )
        if isinstance(slice, ast.Slice):
            method = receiver_obj.find("__slice__")
            if not method.is_analyzed:
                raise DependencyError(method)
            assert isinstance(method.return_type, (Class, UnionType))
            value_obj = method.return_type
            if isinstance(method.return_type, Class):
                value_obj = method.return_type(
                    "__slice_result__", self.scope, self.func
                )
            simple_step = (
                isinstance(slice.step, Constant)
                and slice.step.value in (None, 1)
            )
            if simple_step:
                dependency_objects = {}
            else:
                dependency_objects = self.inline_dependencies(method, node)
            return Call(
                method.return_type,
                value_obj=value_obj,
                func=Attribute(method, value=value, attr="__slice__"),
                args=[slice.lower, slice.upper, slice.step],
                keywords=[],
                dependency_objects=dependency_objects,
            )
        if isinstance(receiver_type, TypedDictClass):
            if not isinstance(slice, Constant) or not isinstance(slice.value, str):
                raise TypeError("TypedDict keys must be string literals.")
            value_type = receiver_type.field_type(slice.value)
            value_obj = value_type
            if isinstance(value_type, Class):
                value_obj = value_type("__subscript_result__", self.scope, self.func)
            return Subscript(
                value_type,
                value_obj=value_obj,
                slice=slice,
                value=value,
            )
        if isinstance(receiver_type, Class) and receiver_type.generic_name == "tuple":
            item_types = list(receiver_type.generic_types.values())
            if (
                isinstance(slice, Constant)
                and isinstance(slice.value, int)
                and -len(item_types) <= slice.value < len(item_types)
            ):
                value_type = item_types[slice.value]
            else:
                value_type = (
                    UnionType(types=item_types).type
                    if item_types
                    else BUILTINS.search("object")
                )
            getitem = receiver_obj.find("__getitem__")
            if not getitem.is_analyzed:
                raise DependencyError(getitem)
            return self.lower_inline_call(
                node,
                getitem,
                Attribute(getitem, value=value, attr="__getitem__"),
                [slice],
                [],
                value_type,
            )
        getitem = receiver_obj.find("__getitem__")
        if not getitem.is_analyzed:
            raise DependencyError(getitem)
        assert isinstance(getitem.return_type, (Class, UnionType))
        value_obj = getitem.return_type
        if isinstance(getitem.return_type, Class):
            value_obj = getitem.return_type("__subscript_result__", self.scope, self.func)
        getitem_attribute = Attribute(getitem, value=value, attr="__getitem__")
        if getitem.inline_call is not None:
            return self.lower_inline_call(
                node,
                getitem,
                getitem_attribute,
                [slice],
                [],
                getitem.return_type,
            )
        if isinstance(receiver_obj, Instance) and receiver_obj.cls.generic_name == "dict":
            return Call(
                getitem.return_type,
                value_obj=value_obj,
                func=getitem_attribute,
                args=[slice],
                keywords=[],
            )
        return Subscript(
            getitem.return_type,
            value_obj=value_obj,
            slice=slice,
            value=value,
        )

    # endregion

    # region functions

    def dispatch_dunder_call(self, builtin, method_name, args, keywords):
        if not args:
            raise TypeError(f"{builtin.name}() requires an argument")
        receiver_node = args[0]
        receiver_obj = receiver_node.obj
        if isinstance(receiver_obj, Class):
            receiver_obj = receiver_obj._self
        union_type = self.receiver_union(receiver_obj)
        if not isinstance(receiver_obj, Instance):
            raise TypeError(f"Cannot dispatch {builtin.name}() on {receiver_obj}.")
        union_functions = ()
        receiver_name = receiver_obj.cls.name
        if union_type is None:
            try:
                method = receiver_obj.find(method_name)
            except NameError:
                raise TypeError(
                    f"{builtin.name}() is not supported for {receiver_obj.cls.name}."
                ) from None
            assert isinstance(method, Function)
            if not method.is_analyzed:
                raise DependencyError(method)
            return_type = method.return_type
        elif isinstance(builtin, Function) and builtin.inline_call is not None:
            runtime_methods = runtime_dunder_methods(union_type, method_name)
            for method in runtime_methods:
                if method is not self.func and not method.is_analyzed:
                    raise DependencyError(method)
            call = self.lower_inline_call(
                receiver_node,
                builtin,
                Name(builtin),
                args,
                keywords,
                builtin.return_type,
            )
            call.runtime_methods = runtime_methods
            return call
        else:
            receiver_name = union_type.to_annotation_str(" | ")
            attribute = ast.copy_location(
                ast.Attribute(value=receiver_node, attr=method_name),
                receiver_node,
            )
            resolution = self.resolve_union_attribute(attribute, union_type)
            assert isinstance(resolution, UnionMethodResolution)
            union_functions = resolution.methods
            method = union_functions[0]
            return_type = resolution.return_type
            assert isinstance(return_type, (Class, UnionType))
        expected_type = builtin.return_type if isinstance(builtin, Function) else builtin
        if not is_return_type_compatible(expected_type, return_type):
            raise TypeError(
                f"{receiver_name}.{method_name}() returns "
                f"{return_type.to_annotation_str()}, expected "
                f"{expected_type.to_annotation_str()}."
            )
        value_obj = return_type
        if isinstance(return_type, Class):
            value_obj = return_type("__call_result__", self.scope, self.func)
        return self.call_node(
            receiver_node,
            return_type,
            value_obj=value_obj,
            func=Attribute(
                method,
                value=receiver_node,
                attr=method_name,
                union_functions=union_functions,
                union_return_type=return_type if union_functions else None,
            ),
            args=args[1:],
            keywords=keywords,
            dependency_objects=self.inline_dependencies(method, receiver_node),
        )

    @staticmethod
    def overload_accepts_shape(function, node):
        positional_count = len(node.args)
        if function.vararg is None and positional_count > len(function.params):
            return False
        keyword_names = {
            keyword.arg for keyword in node.keywords if keyword.arg is not None
        }
        if function.kwarg is None:
            accepted_keywords = {
                parameter.arg
                for parameter in (*function.params, *function.kwonlyargs)
            }
            if not keyword_names <= accepted_keywords:
                return False
        required_count = len(function.params) - len(function.defaults)
        for parameter in function.params[positional_count:required_count]:
            if parameter.arg not in keyword_names:
                return False
        for parameter, default in zip(
            function.kwonlyargs,
            function.kw_defaults,
            strict=True,
        ):
            if default is None and parameter.arg not in keyword_names:
                return False
        return True

    def overload_candidates(self, function, node):
        return tuple(
            overload
            for overload in function.overloads
            if self.overload_accepts_shape(overload, node)
        )

    def overload_matches_types(self, function, args, keywords):
        bindings = {}
        for index, argument in enumerate(args):
            if isinstance(argument, ast.Starred):
                continue
            pattern = self.call_argument_pattern(function, index)
            if pattern is None:
                return False
            infer_type_variables(pattern, analyzed_value_type(argument), bindings)
        for keyword in keywords:
            pattern = self.call_keyword_pattern(keyword, function)
            if pattern is None:
                return False
            infer_type_variables(
                pattern,
                analyzed_value_type(keyword.value),
                bindings,
            )
        for index, argument in enumerate(args):
            if isinstance(argument, ast.Starred):
                continue
            pattern = self.call_argument_pattern(function, index)
            expected = substitute_type_variables(pattern, bindings)
            if contains_type_variable(expected) or not is_call_argument_compatible(
                expected,
                argument,
            ):
                return False
        for keyword in keywords:
            pattern = self.call_keyword_pattern(keyword, function)
            expected = substitute_type_variables(pattern, bindings)
            if contains_type_variable(expected) or not is_call_argument_compatible(
                expected,
                keyword.value,
            ):
                return False
        return True

    def analyze_call_arguments(
        self,
        node,
        signature_function,
        callable_signature,
    ):
        type_bindings = {}
        args = []
        for index, argument in enumerate(node.args):
            expected_type = None
            if (
                callable_signature is not None
                and callable_signature.parameter_types is not None
                and index < len(callable_signature.parameter_types)
            ):
                expected_type = callable_signature.parameter_types[index]
            if expected_type is None:
                args.append(
                    self.visit_call_argument(
                        argument,
                        signature_function,
                        index,
                        type_bindings,
                    )
                )
            else:
                args.append(
                    self.visit_contextual_expression(argument, expected_type)
                )
        keywords = []
        for keyword in node.keywords:
            pattern = self.call_keyword_pattern(keyword, signature_function)
            expected_type = (
                substitute_type_variables(pattern, type_bindings)
                if pattern is not None
                else None
            )
            value = self.visit_contextual_expression(
                keyword.value,
                expected_type,
            )
            analyzed_keyword = ast.keyword(arg=keyword.arg, value=value)
            keywords.append(analyzed_keyword)
            if pattern is not None:
                infer_type_variables(
                    pattern,
                    callable_value_type(value),
                    type_bindings,
                )
        contextual_type = self.contextual_types.get(node)
        return_pattern = (
            signature_function.declared_return_type
            if signature_function is not None
            else None
        )
        if contextual_type is not None and return_pattern is not None:
            contextual_bindings = {}
            infer_type_variables(
                return_pattern,
                contextual_type,
                contextual_bindings,
            )
            for parameter, value_type in contextual_bindings.items():
                type_bindings.setdefault(parameter, value_type)
        return args, keywords, type_bindings

    def validate_type_bindings(self, node, function, bindings):
        for parameter in function.type_parameters.values():
            value_type = bindings.get(parameter)
            if value_type is None:
                if not contains_type_variable(
                    function.declared_return_type,
                    parameter,
                ):
                    continue
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Cannot infer type parameter {parameter.name!r} for "
                    f"{function.name}",
                    help=(
                        "Add a contextual annotation or pass an argument that "
                        "determines the type."
                    ),
                )
            if parameter.bound is not None and not is_return_type_compatible(
                parameter.bound,
                value_type,
            ):
                value_name = ast.unparse(value_type.annotation)
                bound_name = ast.unparse(parameter.bound.annotation)
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Type argument {value_name} for {parameter.name} does "
                    f"not satisfy bound {bound_name}",
                    help=(
                        f"Pass a {bound_name} subtype for {parameter.name}."
                    ),
                )
            if contains_json_object_schema(parameter.bound):
                try:
                    validate_json_result_type(value_type, value_type.name)
                except TypeError as error:
                    self.fail(
                        node,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        str(error),
                        help=(
                            "Use JSON primitives, lists, and JSONObject "
                            "fields in the schema."
                        ),
                    )

    def visit_Call(self, node: ast.Call):
        """
        Instantiating a class in Python is an ast.Call, for generic class instantiation
        there are two ways to determine the corresponding concrete type to create:
        1. annotation is provided after class name (eg. Foo[int]() )
        2. infer class type arguments if all of them happen to be referenced in the __init__
           parameter list and this ast.Call includes arguments for those parameters
        In case of both 1 and 2 being provided, 1 takes precedence and enforces that 2 matches.
        """

        previous_call_target = self.direct_call_target
        self.direct_call_target = (
            node.func.value if isinstance(node.func, ast.Subscript) else node.func
        )
        try:
            if isinstance(node.func, ast.Subscript):
                func = self.visit(node.func.value)
                if isinstance(func.obj, GenericClass):
                    # types are passed, create concrete class
                    func = self.visit_type_annotation(node.func)
                else:
                    func = self.visit(node.func)
            else:
                func = self.visit(node.func)
        finally:
            self.direct_call_target = previous_call_target

        call_target = analyzed_value_object(func)
        called_function = None
        callable_signature = None
        if isinstance(call_target, Instance):
            called_function = call_target.find("__call__")
            assert isinstance(called_function, Function)
            if isinstance(call_target.cls, CallableClass):
                callable_signature = call_target.cls
        else:
            assert isinstance(call_target, (GenericClass, Class, Function))
            if isinstance(call_target, Function):
                called_function = call_target
        if (
            called_function is not None
            and not called_function.signature_analyzed
        ):
            raise DependencyError(called_function)
        if (
            called_function is not None
            and not called_function.is_analyzed
            and called_function.declared_return_type is None
        ):
            raise DependencyError(called_function)
        if called_function is not None:
            for overload in called_function.overloads:
                if not overload.signature_analyzed:
                    raise DependencyError(overload)
        if (
            called_function is not None
            and called_function.analysis is not None
            and node not in self.active_call_analysis
        ):
            return called_function.analysis(
                _CallAnalysis(self, node, called_function)
            )
        overloads = (
            self.overload_candidates(called_function, node)
            if called_function is not None
            else ()
        )
        signature_function = (
            overloads[0] if len(overloads) == 1 else called_function
        )

        args, keywords, type_bindings = self.analyze_call_arguments(
            node,
            signature_function,
            callable_signature,
        )
        if len(overloads) > 1:
            matches = [
                overload
                for overload in overloads
                if self.overload_matches_types(overload, args, keywords)
            ]
            if matches:
                signature_function = matches[0]
                args, keywords, type_bindings = self.analyze_call_arguments(
                    node,
                    signature_function,
                    callable_signature,
                )

        if signature_function is not None and signature_function.type_parameters:
            self.validate_type_bindings(
                node,
                signature_function,
                type_bindings,
            )

        dunder_builtin = called_function
        if dunder_builtin is None and isinstance(func.obj, Class) and args:
            dunder_builtin = func.obj
        if dunder_builtin is not None and (
            method_name := getattr(
                dunder_builtin.py_obj, "__js_dispatch__", None
            )
        ):
            return self.dispatch_dunder_call(
                dunder_builtin, method_name, args, keywords
            )

        if isinstance(call_target, Instance):
            result_function = signature_function or called_function
            return_type = (
                callable_signature.return_type
                if callable_signature is not None
                else result_function.return_type
                or result_function.declared_return_type
            )
        elif isinstance(call_target, Function):
            result_function = signature_function or call_target
            return_type = (
                func.union_return_type
                if isinstance(func, Attribute) and func.union_return_type is not None
                else result_function.return_type
                or result_function.declared_return_type
            )
        elif isinstance(call_target, Class):
            return_type = call_target
        elif isinstance(call_target, GenericClass):
            # types were not passed, try creating from args
            contextual_type = self.contextual_types.get(node)
            collection_type = contextual_collection_type(
                contextual_type,
                call_target.name,
            )
            if (
                not args
                and not keywords
                and collection_type is not None
            ):
                return_type = collection_type
            else:
                return_type = call_target.from_call([a.obj for a in args])
            func = Name(return_type)
        else:
            raise NotImplementedError(f"Don't know how to handle {call_target} call.")
        if called_function is not None:
            return_type = substitute_type_variables(return_type, type_bindings)
        if callable_signature is not None:
            self.validate_callable_call(node, callable_signature, args, keywords)
        elif called_function is not None:
            self.validate_call_argument_types(
                node,
                signature_function,
                args,
                keywords,
                type_bindings,
            )
        if called_function is not None and called_function.inline_call is not None:
            call = self.lower_inline_call(
                node,
                called_function,
                func,
                args,
                keywords,
                return_type,
            )
            call.runtime_methods = self.runtime_contract_methods(
                func,
                called_function,
                args,
            )
            return call
        if called_function is not None and called_function.returns_self:
            assert isinstance(func, Attribute)
            receiver = func.value.obj
            if isinstance(receiver, Instance):
                return_type = receiver.cls
            else:
                assert isinstance(receiver, Class)
                return_type = receiver
        if called_function is not None and called_function.is_async:
            awaitable = BUILTINS.search("Awaitable")
            assert isinstance(awaitable, GenericClass)
            return_type = awaitable(return_type)

        dependency_objects = {}
        if called_function is not None:
            dependency_objects = self.inline_dependencies(called_function, node)
        runtime_methods = (
            self.runtime_contract_methods(func, called_function, args)
            if called_function is not None
            else ()
        )
        value_obj = return_type
        if isinstance(return_type, Class):
            value_obj = return_type("__call_result__", self.scope, self.func)
        return Call(
            return_type,
            value_obj=value_obj,
            func=func,
            args=args,
            keywords=keywords,
            dependency_objects=dependency_objects,
            runtime_methods=runtime_methods,
        )

    def call_argument_pattern(self, function, index):
        if function is not None:
            if index < len(function.params):
                return function.params[index].annotation.obj
            elif function.vararg is not None:
                return iterable_item_type(function.vararg.annotation.obj)
        return None

    def visit_call_argument(self, argument, function, index, type_bindings):
        pattern = self.call_argument_pattern(function, index)
        expected_type = (
            substitute_type_variables(pattern, type_bindings)
            if pattern is not None
            else None
        )
        expected_callable = callable_member(expected_type)
        callable_parameters_are_known = (
            expected_callable is not None
            and expected_callable.parameter_types is not None
            and not any(
                contains_type_variable(parameter)
                for parameter in expected_callable.parameter_types
            )
        )
        if (
            expected_type is not None
            and contains_type_variable(expected_type)
            and not callable_parameters_are_known
        ):
            expected_type = None
        value = self.visit_contextual_expression(argument, expected_type)
        if pattern is not None:
            infer_type_variables(
                pattern,
                callable_value_type(value),
                type_bindings,
            )
        return value

    def validate_callable_call(self, node, signature, args, keywords):
        if keywords:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Calls through Callable annotations require positional arguments",
                help="Pass callable arguments positionally.",
            )
        if signature.parameter_types is None:
            return
        if len(args) != len(signature.parameter_types):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Callable expects {len(signature.parameter_types)} arguments, "
                f"got {len(args)}",
            )
        for index, (argument, expected_type) in enumerate(
            zip(args, signature.parameter_types, strict=True),
            start=1,
        ):
            actual_type = analyzed_value_type(argument)
            if not is_return_type_compatible(expected_type, actual_type):
                self.fail(
                    node.args[index - 1],
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Callable argument {index} expects "
                    f"{expected_type.to_annotation_str()}, got "
                    f"{actual_type.to_annotation_str()}",
                    help=f"Pass a value compatible with {expected_type.to_annotation_str()}.",
                )

    def call_keyword_pattern(self, keyword, function):
        if function is None or keyword.arg is None:
            return None
        parameters = {
            parameter.arg: parameter
            for parameter in (*function.params, *function.kwonlyargs)
        }
        parameter = parameters.get(keyword.arg)
        if parameter is None:
            if function.kwarg is None:
                return None
            return function.kwarg.annotation.obj.generic_types["V"]
        return parameter.annotation.obj

    def validate_dataclass_utility(
        self,
        node: ast.Call,
        utility: str,
        args: list[ast.expr],
        keywords: list[ast.keyword],
    ) -> Class:
        if len(args) != 1 or isinstance(args[0], ast.Starred):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{utility}() requires one dataclass instance",
                help=f"Pass one statically typed dataclass to {utility}().",
            )
        value_type = analyzed_value_type(args[0])
        if not isinstance(value_type, Class) or not value_type.is_dataclass:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{utility}() requires a dataclass instance",
                help=f"Pass a dataclass instance to {utility}().",
            )
        if utility == "asdict" and keywords:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "asdict() custom dictionary factories are not supported",
                help="Use the default asdict() dictionary conversion.",
            )
        if utility == "replace":
            fields = {
                field.name
                for field in dataclass_fields(value_type.py_cls)
                if field.init
            }
            invalid = [keyword.arg for keyword in keywords if keyword.arg not in fields]
            if invalid:
                names = ", ".join(
                    "**changes" if name is None else repr(name)
                    for name in invalid
                )
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"replace() cannot set {names} on {value_type.name}",
                    help="Replace only fields declared with init=True.",
                )
            for source_keyword, keyword in zip(
                node.keywords,
                keywords,
                strict=True,
            ):
                assert keyword.arg is not None
                field = value_type._self.find(keyword.arg)
                assert isinstance(field, Instance)
                replacement_type = analyzed_value_type(keyword.value)
                if not is_return_type_compatible(field.cls, replacement_type):
                    expected = field.cls.to_annotation_str()
                    actual = replacement_type.to_annotation_str()
                    self.fail(
                        source_keyword.value,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        f"replace() field {keyword.arg!r} expects {expected}, "
                        f"not {actual}",
                        help=f"Pass a value compatible with {expected}.",
                    )
        return value_type

    def infer_parameter_type(self, param, default=None, fallback=None):
        default_type = None
        if default is not None:
            default_type = default.obj
            assert isinstance(default_type, Class)
        annotation_type = None
        if param.annotation is not None:
            annotation_type = self.visit_type_annotation(param.annotation).obj
            assert isinstance(annotation_type, (Class, UnionType))
        arg_type = annotation_type or default_type or fallback
        if arg_type is None:
            self.fail(
                param,
                DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                f"Parameter {param.arg!r} requires a type annotation",
                help=(
                    f"Annotate {param.arg!r} with the value type expected by "
                    "this function."
                ),
            )
        return arg_type

    def collect_native_attributes(self, statements: list[ast.stmt]):
        assert self.func.cls is not None
        for statement in ast.walk(ast.Module(body=statements)):
            annotation = None
            if isinstance(statement, ast.AnnAssign):
                target = statement.target
                annotation = statement.annotation
                value = statement.value
            elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                value = statement.value
            else:
                continue
            if not (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and value is not None
            ):
                continue
            try:
                value_type = self.analyze_assignment_value(
                    value, annotation
                ).storage_type
            except (CompilationError, DependencyError, NameError):
                if annotation is not None:
                    raise
                continue
            assert value_type is not None
            self.func.cls._self.add(
                value_type(target.attr, self.func.cls.scope, self.func.cls._self)
            )

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if self.func.is_generator and self.func.is_async:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "async generators are not supported",
                help="Use a synchronous generator or return a collection.",
            )
        if self.func.is_generator and self.func.is_property:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "generator properties are not supported",
                help="Use a normal method that returns the generator.",
            )
        if self.func.is_generator and self.func.name == "__init__":
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "constructors cannot be generators",
                help="Move the yielded values to a separate method.",
            )
        self.func.params = []
        self.func.vararg = None
        self.func.kwonlyargs = []
        self.func.kwarg = None
        type_parameters = {
            parameter.name: parameter
            for parameter in node.type_params
            if isinstance(parameter, ast.TypeVar)
        }
        for name, parameter in self.func.type_parameters.items():
            parameter.bound = None
            type_parameter = type_parameters.get(name)
            if type_parameter is not None and type_parameter.bound is not None:
                parameter.bound = self.visit_type_annotation(
                    type_parameter.bound
                ).obj
        self.func.defaults = defaults = [
            self.visit(default) for default in node.args.defaults
        ]
        self.func.kw_defaults = kw_defaults = [
            self.visit(default) if default is not None else None
            for default in node.args.kw_defaults
        ]
        self_annotation = (
            isinstance(node.returns, ast.Name) and node.returns.id == "Self"
        ) or (
            isinstance(node.returns, ast.Constant) and node.returns.value == "Self"
        )
        if self_annotation:
            if not self.func.is_method:
                raise TypeError("Self return annotations are only valid on methods.")
            self.func.returns_self = True
            declared_return_type = self.func.cls
        elif node.returns is None:
            declared_return_type = None
        elif isinstance(node.returns, ast.Constant) and node.returns.value is None:
            declared_return_type = get_none_type()
        else:
            declared_return_type = self.visit_type_annotation(node.returns).obj
        assert declared_return_type is None or isinstance(
            declared_return_type, (Class, UnionType)
        )
        self.func.declared_return_type = declared_return_type
        self.func.inferred_return_type = None
        self.func.return_type = None

        pos_params = node.args.args
        no_defaults = len(pos_params) - len(defaults)
        pos_defaults = [None] * no_defaults + defaults

        if self.func.is_method:
            if self.func.is_classmethod:
                assert pos_params[0].arg == "cls", (
                    "First parameter in classmethod should be cls."
                )
            elif self.func.is_staticmethod:
                pass
            else:
                assert pos_params[0].arg == "self", (
                    "First parameter in method should be self."
                )

        for i, (param, default) in enumerate(zip(pos_params, pos_defaults, strict=True)):
            if i == 0 and param.arg == "self" and self.func.is_method:
                self.func.add_self()
                continue
            if i == 0 and param.arg == "cls" and self.func.is_classmethod:
                self.func.add_cls()
                continue
            arg_type = self.infer_parameter_type(param, default)
            self.func.params.append(
                ast.arg(arg=param.arg, annotation=analyzed_annotation(arg_type))
            )
            self.func.scope.add(arg_type(param.arg, self.func.scope, self.func))

        if node.args.vararg is not None:
            item_type = self.infer_parameter_type(
                node.args.vararg,
                fallback=BUILTINS.search("object"),
            )
            arg_type = BUILTINS.search("tuple")(item_type)
            self.func.vararg = ast.arg(
                arg=node.args.vararg.arg,
                annotation=analyzed_annotation(arg_type),
            )
            self.func.scope.add(
                arg_type(node.args.vararg.arg, self.func.scope, self.func)
            )

        for param, default in zip(node.args.kwonlyargs, kw_defaults, strict=True):
            arg_type = self.infer_parameter_type(param, default)
            self.func.kwonlyargs.append(
                ast.arg(arg=param.arg, annotation=analyzed_annotation(arg_type))
            )
            self.func.scope.add(arg_type(param.arg, self.func.scope, self.func))

        if node.args.kwarg is not None:
            value_type = self.infer_parameter_type(
                node.args.kwarg,
                fallback=BUILTINS.search("object"),
            )
            arg_type = BUILTINS.search("dict")(BUILTINS.search("str"), value_type)
            self.func.kwarg = ast.arg(
                arg=node.args.kwarg.arg,
                annotation=analyzed_annotation(arg_type),
            )
            self.func.scope.add(arg_type(node.args.kwarg.arg, self.func.scope, self.func))
        self.func.signature_analyzed = True
        if should_analyze_func_body(self.func):
            self.func.body = self.visit_body(node.body)
            if self.func.is_generator:
                iterable = BUILTINS.search("Iterable")
                assert isinstance(iterable, GenericClass)
                final_return_type = iterable(
                    self.func.yield_type or get_none_type()
                )
            else:
                final_return_type = self.func.inferred_return_type
                if body_can_fall_through(self.func.body):
                    final_return_type = merge_return_types(
                        final_return_type,
                        get_none_type(),
                    )
                final_return_type = (
                    final_return_type or declared_return_type or get_none_type()
                )
            if declared_return_type is not None and not is_interface_stub_body(node.body):
                compatible = is_return_type_compatible(
                    declared_return_type,
                    final_return_type,
                )
                if not compatible:
                    declared = ast.unparse(declared_return_type.annotation)
                    inferred = ast.unparse(final_return_type.annotation)
                    if self.func.is_generator:
                        message = f"Generator produces {inferred}, not {declared}"
                        help_text = (
                            "Change the return annotation to match the yielded "
                            "values."
                        )
                    else:
                        message = f"Function returns {inferred}, not {declared}"
                        help_text = (
                            "Change the return annotation or return values so "
                            "their types match."
                        )
                    self.fail(
                        node.returns or node,
                        DiagnosticCode.INCOMPATIBLE_RETURN,
                        message,
                        help=help_text,
                    )
            self.func.return_type = declared_return_type or final_return_type
        else:
            if not self.func.name == "__init__":
                native = vars(self.func.py_func).get("__js_native__", False) or (
                    self.func.cls is not None
                    and vars(self.func.cls.py_obj).get("__js_native__", False)
                )
                assert node.returns or native, (
                    "Return type annotation required for JavaScript source and "
                    "inline implementations"
                )
                self.func.return_type = declared_return_type or get_none_type()
            else:
                if self.func.cls is not None and vars(self.func.cls.py_obj).get(
                    "__js_native__", False
                ):
                    self.collect_native_attributes(node.body)
                self.func.return_type = self.func.cls

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self.visit_FunctionDef(node)

    def visit_Await(self, node: ast.Await):
        value = self.visit(node.value)
        awaitable_type = value.obj
        if (
            not isinstance(awaitable_type, Class)
            or awaitable_type.generic_name != "Awaitable"
        ):
            raise TypeError("await requires an async function call")
        awaited_type = awaitable_type.generic_types["T"]
        value_obj = awaited_type
        if isinstance(awaited_type, Class):
            value_obj = awaited_type("__await_result__", self.scope, self.func)
        return Await(
            awaited_type,
            value_obj=value_obj,
            value=value,
        )

    def visit_type_annotation(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            annotation = ast.parse(node.value, mode="eval").body
            ast.copy_location(annotation, node)
            return self.visit_type_annotation(annotation)
        if isinstance(node, ast.Subscript):
            alias_name = typing_alias_name(node.value, self.scope)
            if alias_name == "Callable":
                if not isinstance(node.slice, ast.Tuple) or len(node.slice.elts) != 2:
                    self.fail(
                        node,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        "Callable annotations require parameter and return types",
                        help="Use Callable[[ParameterType], ReturnType].",
                    )
                parameters, return_annotation = node.slice.elts
                parameter_types = None
                if not (
                    isinstance(parameters, ast.Constant)
                    and parameters.value is Ellipsis
                ):
                    if not isinstance(parameters, ast.List):
                        self.fail(
                            parameters,
                            DiagnosticCode.UNSUPPORTED_SYNTAX,
                            "Callable parameter types must be enclosed in brackets",
                            help="Use Callable[[ParameterType], ReturnType].",
                        )
                    parameter_types = tuple(
                        self.visit_type_annotation(parameter).obj
                        for parameter in parameters.elts
                    )
                base = BUILTINS.search("callable")
                assert isinstance(base, Class)
                return Name(
                    CallableClass(
                        parameter_types,
                        self.visit_type_annotation(return_annotation).obj,
                        base,
                    )
                )
            if alias_name == "Literal":
                elements = (
                    node.slice.elts
                    if isinstance(node.slice, ast.Tuple)
                    else [node.slice]
                )
                if not elements or any(
                    not isinstance(element, ast.Constant)
                    or not isinstance(element.value, str)
                    for element in elements
                ):
                    self.fail(
                        node.slice,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        "Literal annotations require string values",
                        help=(
                            "Use one or more string values, such as "
                            "Literal['open', 'closed']."
                        ),
                    )
                return Name(
                    literal_type(
                        (element.value for element in elements),
                        self.scope,
                    )
                )
            if alias_name in {"Optional", "Union"}:
                elements = (
                    node.slice.elts
                    if isinstance(node.slice, ast.Tuple)
                    else [node.slice]
                )
                types = [
                    self.visit_type_annotation(element).obj for element in elements
                ]
                if alias_name == "Optional":
                    types.append(get_none_type())
                return Name(UnionType(types=types).type)
            if alias_name in TYPING_TYPE_ALIASES:
                value = Name(BUILTINS.search(TYPING_TYPE_ALIASES[alias_name]))
            else:
                value = self.visit(node.value)
            if isinstance(node.slice, ast.Tuple):
                elements = node.slice.elts
                if (
                    isinstance(value.obj, GenericClass)
                    and value.obj.name == "tuple"
                    and isinstance(elements[-1], ast.Constant)
                    and elements[-1].value is Ellipsis
                ):
                    elements = elements[:-1]
                item_types = [
                    self.visit_type_annotation(elt).obj for elt in elements
                ]
            elif isinstance(
                node.slice, (ast.Name, ast.BinOp, ast.Subscript, ast.Constant)
            ):
                item_types = [self.visit_type_annotation(node.slice).obj]
            else:
                raise NotImplementedError()
            assert isinstance(value.obj, GenericClass)
            return Name(value.obj(*item_types))  # generic class -> concrete class
        elif isinstance(node, ast.BinOp):
            left = self.visit_type_annotation(node.left).obj
            right = self.visit_type_annotation(node.right).obj
            assert isinstance(left, (Class, UnionType))
            assert isinstance(right, (Class, UnionType))
            return BinOp(
                UnionType(types=(left, right)).type,
                left=node.left,
                op=node.op,
                right=node.right,
            )
        elif isinstance(node, ast.Constant) and node.value is None:
            return self.visit(node)
        else:
            alias_name = typing_alias_name(node, self.scope)
            if alias_name in TYPING_TYPE_ALIASES:
                return Name(BUILTINS.search(TYPING_TYPE_ALIASES[alias_name]))
            assert isinstance(node, ast.Name)
            value = self.scope.search(node.id)
            if isinstance(value, TypeAliasValue):
                try:
                    value_type = resolve_python_annotation(
                        value.annotation,
                        value.scope,
                    )
                except UnsupportedLiteralError as error:
                    self.fail(
                        node,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        str(error),
                        help=(
                            "Use one or more string values, such as "
                            "Literal['open', 'closed']."
                        ),
                    )
                return Name(value_type)
            if isinstance(value, GenericClass) and value.name == "type":
                object_type = BUILTINS.search("object")
                assert isinstance(object_type, Class)
                return Name(value(object_type))
            return self.visit(node)

    def visit_Pass(self, node: ast.Pass):
        return node

    def visit_Break(self, node: ast.Break):
        return node

    def visit_Continue(self, node: ast.Continue):
        return node

    def visit_Return(self, node: ast.Return):
        if self.func.is_generator:
            if node.value is not None:
                self.fail(
                    node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "generator return values are not supported",
                    help="Use a bare return to stop the generator.",
                )
            return ast.Return(value=None)
        value = node.value
        if value is None:
            return_type = get_none_type()
        else:
            value = self.visit_contextual_expression(
                value,
                self.func.declared_return_type,
            )
            return_type = analyzed_value_type(value)
        # A partial can specialize a broadly annotated target, such as tag() returning a div.
        if self.func.is_partial_client and self.func.declared_return_type is not None:
            return_type = self.func.declared_return_type
        self.func.inferred_return_type = merge_return_types(
            self.func.inferred_return_type, return_type
        )
        return ast.Return(value=value)

    def visit_Yield(self, node: ast.Yield):
        value = self.visit(node.value) if node.value is not None else self.visit(
            ast.Constant(value=None)
        )
        self.func.yield_type = merge_return_types(
            self.func.yield_type,
            analyzed_value_type(value),
        )
        return ast.Yield(value=value)

    def visit_YieldFrom(self, node: ast.YieldFrom):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "yield from is not supported",
            help="Iterate over the value and yield each item explicitly.",
        )

    def visit_contextual_lambda(self, node, parameter_types):
        parameters = [*node.args.posonlyargs, *node.args.args]
        if len(parameters) != len(parameter_types):
            expected_count = len(parameter_types)
            expected_parameters = (
                "parameter" if expected_count == 1 else "parameters"
            )
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Lambda must declare exactly {expected_count} positional "
                f"{expected_parameters}, "
                f"got {len(parameters)}",
                help="Define the lambda with the callable's expected parameters.",
            )
        visitor = type(self)(self.func, LocalScope(self.scope))
        for parameter, parameter_type in zip(
            parameters,
            parameter_types,
            strict=True,
        ):
            visitor.scope.add(
                parameter_type(parameter.arg, visitor.scope, self.func)
            )
        body = visitor.visit(node.body)
        value = ast.Lambda(args=node.args, body=body)
        value.return_type = analyzed_value_type(body)
        value.parameter_types = tuple(parameter_types)
        base = BUILTINS.search("callable")
        assert isinstance(base, Class)
        value.obj = CallableClass(
            value.parameter_types,
            value.return_type,
            base,
        )
        return value

    def visit_Lambda(self, node: ast.Lambda):
        expected = callable_member(self.contextual_types.get(node))
        if expected is not None and expected.parameter_types is not None:
            return self.visit_contextual_lambda(node, expected.parameter_types)
        object_type = BUILTINS.search("object")
        parameters = [*node.args.posonlyargs, *node.args.args]
        return self.visit_contextual_lambda(
            node,
            tuple(object_type for _ in parameters),
        )

    # endregion

    # region expressions & operators

    def visit_Expr(self, node: ast.Expr):
        if isinstance(node.value, ast.Constant) and node.value.value is Ellipsis:
            return ast.Pass(lineno=node.lineno)
        return ast.Expr(value=self.visit(node.value))

    def visit_JoinedStr(self, node: ast.JoinedStr):
        return JoinedStr(
            BUILTINS.search("str"),
            values=[self.visit(part) for part in node.values],
        )

    def visit_FormattedValue(self, node: ast.FormattedValue):
        value = self.visit(node.value)
        conversion = node.conversion
        if node.format_spec is None and conversion in {-1, ord("r"), ord("s")}:
            method_name = "__repr__" if conversion == ord("r") else "__str__"
            value = self.dispatch_dunder_call(
                BUILTINS.search("str"), method_name, [value], []
            )
            conversion = -1
        return ast.FormattedValue(
            value=value,
            conversion=conversion,
            format_spec=node.format_spec,
        )

    COMPARE_OPS = {
        ast.Is: ("__is__", "__is__"),  # pyjs hack, there is no __is__ in Python
        ast.IsNot: ("__is_not__", "__is_not__"),  # there is no __is_not__ in Python
        ast.Lt: ("__lt__", "__gt__"),
        ast.LtE: ("__le__", "__ge__"),
        ast.Gt: ("__gt__", "__lt__"),
        ast.GtE: ("__ge__", "__le__"),
        ast.Eq: ("__eq__", "__eq__"),
        ast.NotEq: ("__ne__", "__ne__"),
        ast.In: ("__contains__", None),
        ast.NotIn: ("__contains__", None),
    }

    def visit_Compare(self, node: ast.Compare):
        assert len(node.ops) == len(node.comparators) == 1
        # TODO: needs cleanup and refactoring
        left = self.visit(node.left)
        right = self.visit(node.comparators[0])
        left_type = analyzed_value_type(left)
        right_type = analyzed_value_type(right)
        operation = node.ops[0]
        comparison_method = "__ne__" if isinstance(operation, ast.NotEq) else "__eq__"
        if isinstance(operation, (ast.Eq, ast.NotEq)) and (
            isinstance(left_type, UnionType) or isinstance(right_type, UnionType)
        ) and not (
            inherits_object_comparison(left_type, comparison_method)
            and inherits_object_comparison(right_type, comparison_method)
        ):
            return self.dynamic_union_equality(
                node,
                left,
                right,
                left_type,
                right_type,
            )

        if isinstance(left.obj, Instance):
            if isinstance(left.obj.cls, UnionType):
                left_self = left.obj.cls.first._self
            else:
                left_self = left.obj
        elif isinstance(left.obj, UnionType):
            left_self = left.obj.first._self
        else:
            left_self = left.obj._self
        if isinstance(right.obj, Instance):
            if isinstance(right.obj.cls, UnionType):
                right_self = right.obj.cls.first._self
            else:
                right_self = right.obj
        elif isinstance(right.obj, UnionType):
            right_self = right.obj.first._self
        else:
            right_self = right.obj._self
        if isinstance(node.ops[0], (ast.In, ast.NotIn)):
            left_self, right_self = right_self, left_self
            left, right = right, left

        left_op_method, right_op_method = self.COMPARE_OPS[type(node.ops[0])]
        negate_dataclass_equality = isinstance(node.ops[0], ast.NotEq) and getattr(
            left_self.cls, "is_dataclass", False
        )
        if negate_dataclass_equality:
            left_op_method = right_op_method = "__eq__"

        try:
            func = left_self.find(left_op_method)
            assert isinstance(func, Function)
            if func.cls.name == "object":
                # for __eq__, __ne__, etc, Python checks the
                # right side before falling back to object
                raise NameError
        except NameError as e:
            if isinstance(node.ops[0], (ast.In, ast.NotIn)):
                raise e
            func = right_self.find(right_op_method)
            if func.cls.name != "object":
                left, right = right, left
        if func is not self.func and not func.is_analyzed:
            raise DependencyError(func)
        return_type = func.return_type or func.declared_return_type
        assert isinstance(return_type, (Class, UnionType))
        comparison = self.call_node(
            node,
            return_type,
            func=Attribute(func, value=left, attr=func.name),
            args=[right],
            keywords=[],
            operator=node.ops[0],
            dependency_objects=self.inline_dependencies(func, node),
        )
        if isinstance(node.ops[0], ast.NotIn) or negate_dataclass_equality:
            return UnaryOp(return_type, op=ast.Not(), operand=comparison)
        return comparison

    def dynamic_union_equality(self, node, left, right, left_type, right_type):
        is_not_equal = isinstance(node.ops[0], ast.NotEq)
        method_name = "__dynamic_ne__" if is_not_equal else "__dynamic_eq__"
        dynamic_method = BUILTINS.search("object").find(method_name)
        assert isinstance(dynamic_method, Function)
        bool_type = BUILTINS.search("bool")
        assert isinstance(bool_type, Class)
        comparison = self.call_node(
            node,
            bool_type,
            func=Attribute(
                dynamic_method,
                value=left,
                attr=dynamic_method.name,
            ),
            args=[right],
            keywords=[],
            operator=node.ops[0],
        )
        runtime_methods = inequality_methods if is_not_equal else equality_methods
        comparison.runtime_methods = tuple(
            dict.fromkeys(runtime_methods(left_type) + runtime_methods(right_type))
        )
        return comparison

    BIN_OPS = {
        ast.Add: ("__add__", "__radd__"),
        ast.Sub: ("__sub__", "__rsub__"),
        ast.Mult: ("__mul__", "__rmul__"),
        ast.Div: ("__truediv__", "__rtruediv__"),
        ast.FloorDiv: ("__floordiv__", "__rfloordiv__"),
        ast.Mod: ("__mod__", "__rmod__"),
        ast.Pow: ("__pow__", "__rpow__"),
        ast.BitAnd: ("__and__", "__rand__"),
        ast.BitOr: ("__or__", "__ror__"),
        ast.BitXor: ("__xor__", "__rxor__"),
    }

    def visit_BinOp(self, node: ast.BinOp):
        left = self.visit(node.left)
        left_self = left.obj if isinstance(left.obj, Instance) else left.obj._self
        right = self.visit(node.right)
        right_self = right.obj if isinstance(right.obj, Instance) else right.obj._self
        left_op_method, right_op_method = self.BIN_OPS[type(node.op)]
        reverse = False
        try:
            func = left_self.find(left_op_method)
            assert isinstance(func, Function)
            if not func.is_analyzed:
                raise DependencyError(func)
            if right_self.cls not in get_type_members(func.params[0].annotation.obj):
                # this is the equivalent of the op function returning NotImplemented
                raise NameError
        except NameError:
            func = right_self.find(right_op_method)
            left, right = right, left
            reverse = True
        if not func.is_analyzed:
            raise DependencyError(func)
        return self.call_node(
            node,
            func.return_type,
            func=Attribute(func, value=left, attr=func.name),
            args=[right],
            keywords=[],
            operator=node.op,
            reverse=reverse,
            dependency_objects=self.inline_dependencies(func, node),
        )

    UNARY_OPS = {
        ast.UAdd: "__pos__",
        ast.USub: "__neg__",
        ast.Invert: "__invert__",
        ast.Not: "__bool__",
    }

    def visit_UnaryOp(self, node: ast.UnaryOp):
        operand = self.visit(node.operand)
        op_method = self.UNARY_OPS[type(node.op)]
        operand_type = (
            operand.obj.cls if isinstance(operand.obj, Instance) else operand.obj
        )
        if isinstance(node.op, (ast.UAdd, ast.USub)) and operand_type.name in (
            "int",
            "float",
        ):
            return UnaryOp(operand_type, op=node.op, operand=operand)
        if isinstance(node.op, ast.Not):
            if isinstance(operand, Call) and operand.obj.name == "bool":
                return UnaryOp(
                    operand.obj,
                    op=node.op,
                    operand=operand,
                )
            elif isinstance(operand, Attribute) and operand.obj.cls.name == "bool":
                return UnaryOp(
                    operand.obj.cls,
                    op=node.op,
                    operand=operand,
                )
            else:
                func = operand.obj.find(op_method)
                if not func.is_analyzed:
                    raise DependencyError(func)
                assert func.return_type.name == "bool"
                return UnaryOp(
                    func.return_type,
                    op=node.op,
                    operand=Call(
                        func.return_type,
                        func=Attribute(func, value=operand, attr=func.name),
                        args=[],
                        keywords=[],
                    ),
                )
        raise NotImplementedError

    def visit_BoolOp(self, node: ast.BoolOp):
        values = []
        visitor = self
        evaluate_next_when_true = isinstance(node.op, ast.And)
        for value in node.values:
            values.append(visitor.visit(value))
            visitor = visitor.narrow_for_condition(value, evaluate_next_when_true)
        value_types = UnionType()
        for index, value in enumerate(values):
            obj_type = value.obj.type
            types = obj_type.types if isinstance(obj_type, UnionType) else [obj_type]
            for type_ in types:
                assert isinstance(type_, Class)
                if (
                    isinstance(node.op, ast.Or)
                    and index < len(values) - 1
                    and type_.name == "NoneType"
                ):
                    continue
                value_types.add(type_)
        return BoolOp(value_types.type, op=node.op, values=values)

    # endregion

    # region constants

    def visit_Constant(self, node: ast.Constant):
        type_name = type(node.value).__name__
        type_cls = literal_member_for_value(
            self.contextual_types.get(node),
            node.value,
        ) or BUILTINS.search(type_name)
        assert isinstance(type_cls, Class)
        return Constant(type_cls, value=node.value)

    def visit_Tuple(self, node: ast.Tuple):
        generic_tuple = BUILTINS.search("tuple")
        assert isinstance(generic_tuple, GenericClass)
        contextual_type = contextual_collection_type(
            self.contextual_types.get(node),
            "tuple",
        )
        if not node.elts and contextual_type is not None:
            return Tuple(contextual_type, elts=[])
        elts = []
        types = []
        contextual_items = (
            list(contextual_type.generic_types.values())
            if contextual_type is not None
            else []
        )
        for index, item in enumerate(node.elts):
            expected_type = (
                contextual_items[index]
                if index < len(contextual_items)
                else None
            )
            elt = self.visit_contextual_expression(item, expected_type)
            elts.append(elt)
            types.append(analyzed_value_type(elt))
        if (
            contextual_type is not None
            and len(types) == len(contextual_items)
            and all(
                is_return_type_compatible(expected, actual)
                for expected, actual in zip(
                    contextual_items,
                    types,
                    strict=True,
                )
            )
        ):
            tuple_type = contextual_type
        else:
            tuple_type = generic_tuple(*types)
        return Tuple(tuple_type, elts=elts)

    def visit_List(self, node: ast.List):
        generic_list = BUILTINS.search("list")
        assert isinstance(generic_list, GenericClass)
        contextual_type = contextual_collection_type(
            self.contextual_types.get(node),
            "list",
        )
        if not node.elts and contextual_type is not None:
            return List(contextual_type, elts=[])
        V = UnionType()
        elts = []
        expected_item_type = (
            contextual_type.generic_types["V"]
            if contextual_type is not None
            else None
        )
        for item in node.elts:
            elt = self.visit_contextual_expression(item, expected_item_type)
            elts.append(elt)
            V.add(analyzed_value_type(elt))
        if (
            contextual_type is not None
            and all(
                is_return_type_compatible(
                    contextual_type.generic_types["V"],
                    analyzed_value_type(elt),
                )
                for elt in elts
            )
        ):
            list_type = contextual_type
        else:
            list_type = generic_list(V.type) if V.types else generic_list
        return List(list_type, elts=elts)

    def visit_Dict(self, node: ast.Dict):
        generic_dict = BUILTINS.search("dict")
        assert isinstance(generic_dict, GenericClass)
        contextual_type = contextual_collection_type(
            self.contextual_types.get(node),
            "dict",
        )
        if not node.keys and contextual_type is not None:
            return Dict(contextual_type, keys=[], values=[])
        K, keys, V, values = UnionType(), [], UnionType(), []
        contextual_key_type = None
        contextual_value_type = None
        if (
            contextual_type is not None
            and not isinstance(contextual_type, TypedDictClass)
        ):
            contextual_key_type = contextual_type.generic_types["K"]
            contextual_value_type = contextual_type.generic_types["V"]
        for key, value in zip(node.keys, node.values, strict=True):
            keys.append(
                self.visit_contextual_expression(key, contextual_key_type)
            )
            K.add(analyzed_value_type(keys[-1]))
            values.append(
                self.visit_contextual_expression(value, contextual_value_type)
            )
            V.add(analyzed_value_type(values[-1]))
        if (
            contextual_key_type is not None
            and all(
                is_return_type_compatible(
                    contextual_key_type,
                    analyzed_value_type(key),
                )
                for key in keys
            )
            and all(
                is_return_type_compatible(
                    contextual_value_type,
                    analyzed_value_type(value),
                )
                for value in values
            )
        ):
            dict_type = contextual_type
        else:
            dict_type = (
                generic_dict(K.type, V.type)
                if K.types and V.types
                else generic_dict
            )
        return Dict(dict_type, keys=keys, values=values)

    def visit_Set(self, node: ast.Set):
        generic_set = BUILTINS.search("set")
        assert isinstance(generic_set, GenericClass)
        item_types = UnionType()
        elements = []
        for item in node.elts:
            element = self.visit(item)
            elements.append(element)
            item_types.add(analyzed_value_type(element))
        set_type = generic_set(item_types.type)
        return Set(set_type, elts=elements)

    # endregion

    # region looping

    def mapping_keys_iterable(self, iterable):
        iterable_obj = analyzed_value_object(iterable)
        iterable_type = (
            iterable_obj.cls if isinstance(iterable_obj, Instance) else iterable_obj
        )
        if not (
            isinstance(iterable_type, TypedDictClass)
            or getattr(iterable_type, "generic_name", None) == "dict"
        ):
            return iterable
        keys = iterable_obj.find("keys")
        return Call(
            keys.return_type,
            func=Attribute(keys, value=iterable, attr="keys"),
            args=[],
            keywords=[],
        )

    def visit_While(self, node: ast.While):
        test = self.visit(node.test)
        body = self.visit_body(node.body)
        orelse = self.visit(node.orelse) if node.orelse else node.orelse
        return ast.While(
            test=test,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )

    def visit_For(self, node: ast.For):
        node_iter = self.mapping_keys_iterable(self.visit(node.iter))

        item_type = iterable_item_type(analyzed_value_type(node_iter))
        target = self.bind_loop_target(node.target, item_type)

        body = self.visit_body(node.body)
        orelse = self.visit(node.orelse) if node.orelse else node.orelse
        return ast.For(
            target=target,
            iter=node_iter,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )

    def bind_loop_target(self, target, value_type):
        if isinstance(target, ast.Name):
            self.scope.add(value_type(target.id, self.scope, self.func))
            return ast.arg(arg=target.id, annotation=value_type.annotation)
        if isinstance(target, ast.Starred):
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "starred loop targets are not supported",
                help="Unpack the remaining values inside the loop body.",
            )
        if not isinstance(target, (ast.Tuple, ast.List)):
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "unsupported loop target",
                help="Iterate into local names before assigning another target.",
            )
        if not isinstance(value_type, Class) or value_type.generic_name != "tuple":
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "loop target requires tuple values",
                help="Iterate over statically typed tuples before unpacking them.",
            )
        item_types = list(value_type.generic_types.values())
        if len(target.elts) != len(item_types):
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"cannot unpack {len(item_types)} values into "
                f"{len(target.elts)} loop targets",
                help="Use one target for each statically known tuple value.",
            )
        return type(target)(
            elts=[
                self.bind_loop_target(item_target, item_type)
                for item_target, item_type in zip(
                    target.elts,
                    item_types,
                    strict=True,
                )
            ]
        )

    def visit_Try(self, node: ast.Try):
        handlers = []
        for handler in node.handlers:
            handler_type, exception_type = self.analyze_exception_handler_type(handler)
            handler_visitor = type(self)(self.func, LocalScope(self.scope))
            if handler.name is not None:
                handler_visitor.scope.add(
                    exception_type(
                        handler.name,
                        handler_visitor.scope,
                        self.func,
                    )
                )
            handlers.append(
                ast.ExceptHandler(
                    type=handler_type,
                    name=handler.name,
                    body=handler_visitor.visit_body(handler.body),
                )
            )
        return ast.Try(
            body=self.visit_body(node.body),
            handlers=handlers,
            orelse=self.visit_body(node.orelse),
            finalbody=self.visit_body(node.finalbody),
            lineno=node.lineno,
        )

    def analyze_exception_handler_type(
        self,
        handler: ast.ExceptHandler,
    ) -> tuple[ast.expr | None, Class | UnionType]:
        exception_class = BUILTINS.search("Exception")
        assert isinstance(exception_class, Class)
        if handler.type is None:
            return None, exception_class
        type_nodes = (
            handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        )
        names = []
        types = []
        for type_node in type_nodes:
            analyzed = self.visit(type_node)
            value_type = analyzed.obj
            if not isinstance(value_type, Class) or not is_subclass(
                value_type,
                exception_class,
            ):
                self.fail(
                    type_node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "except handler requires an exception class",
                    help="Catch Exception or a subclass of Exception.",
                )
            names.append(analyzed)
            types.append(value_type)
        exception_type = types[0]
        for value_type in types[1:]:
            exception_type = merge_return_types(exception_type, value_type)
        if isinstance(handler.type, ast.Tuple):
            return ast.Tuple(elts=names, ctx=ast.Load()), exception_type
        return names[0], exception_type

    def visit_With(self, node: ast.With):
        return self.analyze_with_items(node.items, node.body)

    def analyze_with_items(
        self,
        items: list[ast.withitem],
        body: list[ast.stmt],
    ) -> ast.With:
        item = items[0]
        context = self.visit(item.context_expr)
        context_obj = analyzed_value_object(context)
        if isinstance(context_obj, Class):
            context_obj = context_obj._self
        if not isinstance(context_obj, Instance) or isinstance(
            context_obj.cls,
            UnionType,
        ):
            self.fail(
                item.context_expr,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "with requires one statically known context-manager type",
                help="Narrow the context manager before entering it.",
            )
        methods = []
        for name in ("__enter__", "__exit__"):
            try:
                methods.append(context_obj.find(name))
            except NameError:
                self.fail(
                    item.context_expr,
                    DiagnosticCode.UNDEFINED_ATTRIBUTE,
                    f"Context manager {context_obj.cls.name!r} has no {name} method",
                    help=(
                        "Define both __enter__() and __exit__() on the "
                        "context manager."
                    ),
                )
        enter, exit_ = methods
        assert isinstance(enter, Function) and isinstance(exit_, Function)
        if not enter.is_analyzed and enter.declared_return_type is None:
            raise DependencyError(enter)
        enter_type = enter.return_type or enter.declared_return_type or get_none_type()
        assert isinstance(enter_type, (Class, UnionType))

        target = item.optional_vars
        declares_target = False
        if target is not None:
            target, declares_target = self.resolve_assignment_target(
                target,
                enter_type,
            )
        nested_body = (
            [self.analyze_with_items(items[1:], body)]
            if len(items) > 1
            else self.visit_body(body)
        )
        analyzed = ast.With(
            items=[ast.withitem(context_expr=context, optional_vars=target)],
            body=nested_body,
            type_comment=None,
            lineno=item.context_expr.lineno,
        )
        analyzed.enter_method = enter
        analyzed.exit_method = exit_
        analyzed.declares_target = declares_target
        return analyzed

    def visit_ListComp(self, node: ast.ListComp):
        visitor, generators = self.analyze_comprehension_generators(node)
        elt = visitor.visit(node.elt)
        return ListComp(
            BUILTINS.search("list")(analyzed_value_type(elt)),
            elt=elt,
            generators=generators,
        )

    def analyze_comprehension_generators(self, node):
        visitor = type(self)(self.func, LocalScope(self.scope))
        generators = []
        for generator_node in node.generators:
            if generator_node.is_async:
                self.fail(
                    generator_node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "asynchronous comprehensions are not supported",
                    help=(
                        "Use an explicit async loop before building the collection."
                    ),
                )
            iter_node = visitor.mapping_keys_iterable(
                visitor.visit(generator_node.iter)
            )
            item_type = iterable_item_type(analyzed_value_type(iter_node))
            self.bind_comprehension_target(
                visitor,
                generator_node.target,
                item_type,
            )
            generators.append(
                ast.comprehension(
                    target=visitor.visit(generator_node.target),
                    iter=iter_node,
                    ifs=[visitor.visit(condition) for condition in generator_node.ifs],
                    is_async=0,
                )
            )
        return visitor, generators

    def bind_comprehension_target(self, visitor, target, value_type):
        if isinstance(target, ast.Name):
            visitor.scope.add(value_type(target.id, visitor.scope, self.func))
            return
        if not isinstance(target, (ast.Tuple, ast.List)):
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "unsupported comprehension target",
                help="Unpack comprehension values into local names.",
            )
        starred = next(
            (item for item in target.elts if isinstance(item, ast.Starred)),
            None,
        )
        if starred is not None:
            self.fail(
                starred,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "starred comprehension targets are not supported",
                help="Use an explicit loop to collect the remaining values.",
            )
        if not isinstance(value_type, Class) or value_type.generic_name != "tuple":
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "comprehension target requires tuple values",
                help="Iterate over statically typed tuples before unpacking them.",
            )
        item_types = list(value_type.generic_types.values())
        if len(target.elts) != len(item_types):
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"cannot unpack {len(item_types)} values into "
                f"{len(target.elts)} comprehension targets",
                help="Use one target for each statically known tuple value.",
            )
        for item_target, item_type in zip(target.elts, item_types, strict=True):
            self.bind_comprehension_target(visitor, item_target, item_type)

    def visit_DictComp(self, node: ast.DictComp):
        visitor, generators = self.analyze_comprehension_generators(node)
        key = visitor.visit(node.key)
        value = visitor.visit(node.value)
        return DictComp(
            BUILTINS.search("dict")(
                analyzed_value_type(key),
                analyzed_value_type(value),
            ),
            key=key,
            value=value,
            generators=generators,
        )

    def visit_SetComp(self, node: ast.SetComp):
        visitor, generators = self.analyze_comprehension_generators(node)
        elt = visitor.visit(node.elt)
        return SetComp(
            BUILTINS.search("set")(analyzed_value_type(elt)),
            elt=elt,
            generators=generators,
        )

    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        visitor, generators = self.analyze_comprehension_generators(node)
        elt = visitor.visit(node.elt)
        iterable = BUILTINS.search("Iterable")
        assert isinstance(iterable, GenericClass)
        return GeneratorExp(
            iterable(analyzed_value_type(elt)),
            elt=elt,
            generators=generators,
        )

    # endregion

    # region conditionals

    def truth_test(self, node, test):
        test_type = analyzed_value_type(test)
        if test_type.name == "bool":
            return test
        if isinstance(test_type, UnionType):
            dynamic_bool = BUILTINS.search("object").find("__dynamic_bool__")
            assert isinstance(dynamic_bool, Function)
            result = self.call_node(
                node,
                dynamic_bool.return_type,
                func=Attribute(
                    dynamic_bool,
                    value=test,
                    attr=dynamic_bool.name,
                ),
                args=[],
                keywords=[],
            )
            result.runtime_methods = truthiness_methods(test_type)
            for method in result.runtime_methods:
                if method is not self.func and not method.is_analyzed:
                    raise DependencyError(method)
            return result
        try:
            func = test_type.find("__bool__")
        except NameError:
            return test
        if not func.is_analyzed:
            raise DependencyError(func)
        return Call(
            func.return_type,
            func=Attribute(func, value=test, attr=func.name),
            args=[],
            keywords=[],
        )

    def visit_If(self, node: ast.If):
        test = self.visit(node.test)
        test = self.truth_test(node.test, test)
        body_visitor = self.narrow_for_condition(node.test, True)
        orelse_visitor = self.narrow_for_condition(node.test, False)
        body = body_visitor.visit_body(node.body)
        orelse = orelse_visitor.visit_body(node.orelse)
        return ast.If(
            test=test,
            body=body,
            orelse=orelse,
        )

    def visit_IfExp(self, node: ast.IfExp):
        test = self.visit(node.test)
        test = self.truth_test(node.test, test)
        body_visitor = self.narrow_for_condition(node.test, True)
        orelse_visitor = self.narrow_for_condition(node.test, False)
        body = body_visitor.visit(node.body)
        orelse = orelse_visitor.visit(node.orelse)
        body_type = analyzed_value_type(body)
        orelse_type = conditional_value_type(orelse, body_type)
        body_type = conditional_value_type(body, orelse_type)
        result_type = merge_return_types(body_type, orelse_type)
        return IfExp(
            result_type,
            test=test,
            body=body,
            orelse=orelse,
        )

    def visit_Assert(self, node: ast.Assert):
        test = self.visit(node.test)
        message = self.visit(node.msg) if node.msg is not None else None
        assertion_type = BUILTINS.search("AssertionError")
        assert isinstance(assertion_type, Class)
        assertion = ast.Assert(test=test, msg=message)
        assertion.runtime_dependency = runtime_class_dependency(
            assertion_type,
            self.module,
        )
        assert assertion.runtime_dependency is not None
        return assertion

    def visit_Raise(self, node: ast.Raise):
        exc = self.visit(node.exc) if node.exc is not None else None
        return ast.Raise(exc=exc, cause=node.cause)

    # endregion


class CallGraphVisitor(ast.NodeVisitor):
    def __init__(self, func: Function, entry_point: Function):
        self.func = func
        self.entry_point = entry_point

    @classmethod
    def start(cls, func: Function):
        cls(func, func).enter(func)

    def enter(self, func: Function):
        if func.cls is not None:
            self.enter_class(func.cls)
        self.isolated_visit(func)

    def mark_visited(self, value: Object) -> None:
        value.visited.add(self.entry_point)
        self.entry_point.compilation_objects.add(value)

    def mark_virtual_visited(self, func: Function) -> None:
        func.virtual_visited.add(self.entry_point)
        self.entry_point.compilation_objects.add(func)

    def retain_runtime_dunder(self, function: Function) -> None:
        method_name = getattr(
            function.py_obj,
            "__js_dispatch__",
            None,
        )
        dependencies = self.entry_point.runtime_dunder_dependencies
        if method_name is None or method_name in dependencies:
            return
        dependencies.add(method_name)
        for value in tuple(self.entry_point.compilation_objects):
            if isinstance(value, Class):
                self.enter_runtime_dunder(value, method_name)

    def enter_runtime_dunder(self, cls: Class, method_name: str) -> None:
        method = cls.find_attrs(method_name, search_bases=False)
        if isinstance(method, Function):
            self.enter(method)

    def enter_virtual(self, func: Function):
        self.enter(func)
        if self.entry_point in func.virtual_visited:
            return
        self.mark_virtual_visited(func)
        self.enter_overrides(func, func.cls)

    @staticmethod
    def property_override(func: Function, cls: Class) -> Function | None:
        override = cls.find_attrs(func.name, search_bases=False)
        if func.is_property_setter:
            if isinstance(override, Function) and override.is_property:
                return override.property_setter
            return None
        return override

    def enter_overrides(self, func: Function, cls: Class):
        for subclass in cls.subclasses:
            if self.entry_point not in subclass.visited:
                continue
            override = self.property_override(func, subclass)
            if isinstance(override, Function):
                self.enter_virtual(override)
            else:
                self.enter_overrides(func, subclass)

    def enter_class(self, cls: Class):
        if cls.super is not None:
            runtime_dependency = runtime_class_dependency(cls.super, cls.container)
            if runtime_dependency is not None:
                cls.runtime_super_dependency = runtime_dependency
                cls.runtime_super_alias = cls.container.register_inline_dependency(
                    runtime_dependency
                )
                self.enter_class(runtime_dependency)
        generic = cls.container.scope.names.get(cls.generic_name)
        if isinstance(generic, GenericClass):
            self.mark_visited(generic)
        while cls is not None:
            if self.entry_point not in cls.visited:
                self.mark_visited(cls)
                for dependency in sorted(
                    getattr(cls, "client_model_dependencies", ()),
                    key=lambda item: (item.container.name, item.name),
                ):
                    if dependency is cls:
                        cls.client_model_aliases[dependency] = cls.name
                        continue
                    if dependency.container is cls.container:
                        alias = dependency.name
                    else:
                        alias = cls.container.register_inline_dependency(dependency)
                    cls.client_model_aliases[dependency] = alias
                    self.enter_class(dependency)
                    self.enter(dependency.find("__init__"))
                for method_name in tuple(
                    self.entry_point.runtime_dunder_dependencies
                ):
                    self.enter_runtime_dunder(cls, method_name)
                for dependency in getattr(
                    cls.py_cls,
                    "__js_append_dependencies__",
                    (),
                ):
                    try:
                        dependency_obj = cls.search(dependency.__name__)
                    except NameError:
                        traverse_imported(
                            dependency.__name__,
                            dependency,
                            cls.container,
                        )
                        dependency_obj = cls.search(dependency.__name__)
                    assert isinstance(dependency_obj, Class)
                    self.enter_class(dependency_obj)
                    self.enter(dependency_obj.find("__init__"))
                for attr in cls.children:
                    if not isinstance(attr, Function):
                        continue
                    if has_keep_decorator(attr.py_obj) or self.parent_has_keep(
                        attr
                    ):
                        self.isolated_visit(attr)
                    elif self.parent_is_virtual(attr):
                        self.enter_virtual(attr)
            cls = cls.super

    def parent_has_keep(self, obj):
        if isinstance(obj, Function):
            parent = obj.cls.super
            while parent is not None:
                parent_func = self.property_override(obj, parent)
                if parent_func and has_keep_decorator(parent_func.py_obj):
                    return True
                parent = parent.super
        return False

    def parent_is_virtual(self, obj):
        if isinstance(obj, Function):
            parent = obj.cls.super
            while parent is not None:
                parent_func = self.property_override(obj, parent)
                if (
                    parent_func is not None
                    and self.entry_point in parent_func.virtual_visited
                ):
                    return True
                parent = parent.super
        return False

    @staticmethod
    def is_virtual_method_reference(node):
        if not isinstance(node, ast.Attribute) or not node.obj.is_method:
            return False
        receiver = node.value
        if isinstance(receiver, Name) and isinstance(receiver.obj, Class):
            return False
        if isinstance(receiver, Call):
            if isinstance(receiver.func, Name) and receiver.func.id == "super":
                return False
            if isinstance(receiver.func.obj, Class):
                return False
        return True

    def isolated_visit(self, func: Function):
        assert isinstance(func, Function)
        if func.has_source_decorator:
            self.mark_visited(func)
            module = func.cls.container if func.is_method else func.container
            for name, dependency in getattr(
                func.py_func,
                "__js_source_imports__",
                {},
            ).items():
                try:
                    dependency_obj = module.search(name)
                except NameError:
                    traverse_imported(name, dependency, module)
                    dependency_obj = module.search(name)
                if isinstance(dependency_obj, Class):
                    self.enter_class(dependency_obj)
                    self.enter(dependency_obj.find("__init__"))
                elif isinstance(dependency_obj, Function):
                    self.enter(dependency_obj)
                else:
                    raise TypeError(
                        f"Source dependency {name!r} must be a class or function."
                    )
            for dependency in getattr(
                func.py_func,
                "__pyjs_source_dependencies__",
                (),
            ):
                dependency_obj = func.search(dependency.__name__)
                assert isinstance(dependency_obj, Class)
                self.enter_class(dependency_obj)
                self.enter(dependency_obj.find("__init__"))
            return
        if (
            self.entry_point not in func.visited
        ):
            type(self)(func, self.entry_point).visit(func.node)

    def visit_FunctionDef(self, node: FunctionDef):
        self.mark_visited(node.obj)
        for arg in node.args.args:
            self.visit(arg)
        for stmt in node.body:
            self.visit(stmt)

    def visit_With(self, node: ast.With):
        self.enter_virtual(node.enter_method)
        self.enter_virtual(node.exit_method)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        module = self.func.cls.container if self.func.is_method else self.func.container
        dependency = node.runtime_dependency
        node.runtime_alias = module.register_inline_dependency(dependency)
        self.enter_class(dependency)
        self.enter(dependency.find("__init__"))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: AsyncFunctionDef):
        self.visit_FunctionDef(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, Name) and node.func.id == "tw":
            self.entry_point.tailwind_classes.update(
                set(node.args[0].value.split(" ")),
            )
        func = node.func.obj
        module = self.func.cls.container if self.func.is_method else self.func.container
        for name, dependency in getattr(node, "dependency_objects", {}).items():
            node.inline_dependencies[name] = module.register_inline_dependency(
                dependency
            )
            self.enter(dependency)
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        if forwarded_func := getattr(node, "forwarded_func", None):
            if isinstance(forwarded_func, Attribute):
                if self.is_virtual_method_reference(forwarded_func):
                    self.enter_virtual(forwarded_func.obj)
                else:
                    self.enter(forwarded_func.obj)
        if isinstance(func, Function):
            self.enter(func)
        elif isinstance(func, Instance):
            pass
        elif isinstance(func, Class):
            self.enter_class(func)
            self.enter(func.find("__init__"))
        else:
            raise NotImplementedError(f"Can't call {node.func}.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if setters := getattr(node, "property_setters", ()):
            for setter in dict.fromkeys(setters):
                self.enter_virtual(setter)
            self.generic_visit(node)
            return
        if getters := getattr(node, "property_getters", ()):
            for getter in dict.fromkeys(getters):
                self.enter_virtual(getter)
            self.generic_visit(node)
            return
        union_functions = getattr(node, "union_functions", ())
        if union_functions:
            for func in dict.fromkeys(union_functions):
                if self.is_virtual_method_reference(node):
                    self.enter_virtual(func)
                else:
                    self.enter(func)
        elif isinstance(node.obj, Function):
            if self.is_virtual_method_reference(node):
                self.enter_virtual(node.obj)
            else:
                self.enter(node.obj)
        elif isinstance(node.obj, Instance):
            self.mark_visited(node.obj)
            if node.obj.member_dependency is not None:
                self.enter_class(node.obj.member_dependency)
                self.enter(node.obj.member_dependency.find("__init__"))
        self.generic_visit(node)

    def visit_RuntimeFunctionReference(self, node: RuntimeFunctionReference):
        module = self.func.cls.container if self.func.is_method else self.func.container
        node.alias = module.register_inline_dependency(node.runtime_dependency)
        self.enter(node.runtime_dependency)
        self.retain_runtime_dunder(node.obj)
        if node.receiver is not None:
            self.visit(node.receiver)

    def visit_BoundGetattr(self, node: BoundGetattr):
        self.enter_virtual(node.obj)
        self.visit(node.receiver)
        self.visit(node.default)

    def visit_Name(self, node: Name):
        if hasattr(node, "obj"):
            if node.runtime_dependency is not None:
                module = (
                    self.func.cls.container
                    if self.func.is_method
                    else self.func.container
                )
                if isinstance(node.runtime_dependency, Class):
                    node.runtime_alias = module.register_inline_dependency(
                        node.runtime_dependency
                    )
                    self.enter_class(node.runtime_dependency)
                    self.enter(node.runtime_dependency.find("__init__"))
                else:
                    node.id = module.register_inline_dependency(
                        node.runtime_dependency
                    )
                    self.enter(node.runtime_dependency)
                if isinstance(node.obj, Function):
                    self.retain_runtime_dunder(node.obj)
            elif isinstance(node.obj, Class):
                self.enter_class(node.obj)
                self.enter(node.obj.find("__init__"))
            elif isinstance(node.obj, Function):
                self.enter(node.obj)
            elif isinstance(node.obj, Instance) and isinstance(
                node.obj.container,
                Module,
            ):
                self.mark_visited(node.obj)
                self.enter_class(node.obj.cls)
                self.enter(node.obj.cls.find("__init__"))
            elif isinstance(node.obj, UnionType):
                for obj_type in node.obj.types:
                    self.enter_class(obj_type)
                    self.enter(obj_type.find("__init__"))
            else:
                self.mark_visited(node.obj)


def from_entry_point(
    entry_point: callable,
    extensions: tuple[CompilationExtension, ...] = (),
    additional_entry_points: tuple[callable, ...] = (),
):
    entry_point.__js__ = True
    for additional_entry_point in additional_entry_points:
        additional_entry_point.__js__ = True
    py_module = inspect.getmodule(entry_point)
    return analyze_module(
        py_module,
        entry_point,
        extensions=extensions,
        additional_entry_points=additional_entry_points,
    )


def _reachable_analyzer_objects(root: Object) -> Iterator[Object]:
    pending = [root]
    seen = set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        yield value
        if isinstance(value, (Module, Class)):
            pending.extend(value.children)
        if isinstance(value, Class):
            pending.append(value._self)
        if isinstance(value, GenericClass):
            pending.extend(value.concrete_classes.values())
        if isinstance(value, Instance):
            pending.extend(value.attrs.values())
        for child in vars(value).values():
            if isinstance(child, Object):
                pending.append(child)
            elif isinstance(child, UnionType):
                pending.extend(child.types)
            elif isinstance(child, dict):
                pending.extend(item for item in child.values() if isinstance(item, Object))
            elif isinstance(child, (list, tuple, set)):
                pending.extend(item for item in child if isinstance(item, Object))


def _type_uses_package(value: Object, package: dict, seen: set[int]) -> bool:
    if id(value) in seen:
        return False
    seen.add(id(value))
    if isinstance(value, UnionType):
        return any(_type_uses_package(item, package, seen) for item in value.types)
    if not isinstance(value, Class):
        return False
    if value.container.container is package:
        return True
    return any(
        _type_uses_package(item, package, seen)
        for item in (value.generic_types or {}).values()
    )


def release_compilation(entry_point: Function) -> None:
    roots = entry_point.compilation_entry_points or (entry_point,)
    package = entry_point.container.container
    for root in roots:
        for value in root.compilation_objects:
            value.visited.discard(root)
            if isinstance(value, Function):
                value.virtual_visited.discard(root)
        root.compilation_objects.clear()
        root.compilation_entry_points = ()
        root.runtime_dunder_dependencies.clear()
    for value in _reachable_analyzer_objects(BUILTINS):
        if isinstance(value, Module) and value.container is not package:
            value.type_dependencies = [
                dependency
                for dependency in value.type_dependencies
                if not _type_uses_package(dependency, package, set())
            ]
        if isinstance(value, GenericClass) and value.container.container is not package:
            for key, concrete in list(value.concrete_classes.items()):
                if any(
                    _type_uses_package(item, package, set())
                    for item in (concrete.generic_types or {}).values()
                ):
                    del value.concrete_classes[key]


def analyze_module(
    py_module,
    entry_point=None,
    extensions: tuple[CompilationExtension, ...] = (),
    additional_entry_points: tuple[callable, ...] = (),
):
    if entry_point is None:
        assert hasattr(py_module, "main"), (
            "No entry_point specified and no main() function found."
        )
        py_module.main.__js__ = True
        entry_point = py_module.main
    package = {}
    context = CompilationContext()
    module = Module(
        py_module,
        package,
        extensions=extensions,
        context=context,
    ).build()
    package[module.name] = module
    entry_point_function = module.search(entry_point.__name__)
    assert isinstance(entry_point_function, Function)
    entry_point_function.compilation_entry_points = (entry_point_function,)
    try:
        annotated = set()
        while pending := [value for value in package.values() if value not in annotated]:
            for imported in pending:
                annotate_types(imported)
                annotated.add(imported)
        entry_point_function, tailwind_classes = visit_entry_point(module, entry_point)
        compilation_entry_points = [entry_point_function]
        for additional_entry_point in additional_entry_points:
            additional_function, additional_tailwind_classes = visit_entry_point(
                module,
                additional_entry_point,
            )
            additional_function.visited.discard(additional_function)
            compilation_entry_points.append(additional_function)
            tailwind_classes.update(additional_tailwind_classes)
        entry_point_function.compilation_entry_points = tuple(compilation_entry_points)
        entry_point_function.visited.discard(entry_point_function)
        return entry_point_function, tailwind_classes
    except BaseException:
        release_compilation(entry_point_function)
        raise


def visit_entry_point(module: Module, py_func):
    entry_point_func = module.search(py_func.__name__)
    assert isinstance(entry_point_func, Function)
    entry_point_func.tailwind_classes = set()
    entry_point_func.compilation_objects = set()
    entry_point_func.runtime_dunder_dependencies = set()
    CallGraphVisitor.start(entry_point_func)
    return entry_point_func, entry_point_func.tailwind_classes


def flatten_objects(parent: Object) -> Iterator[Function]:
    if isinstance(parent, (Module, Class)):
        for obj in parent.children:
            yield from flatten_objects(obj)
        if isinstance(parent, Module):
            for dependency in parent.type_dependencies:
                yield from flatten_objects(dependency)
    elif isinstance(parent, Function):
        yield from parent.overloads
        yield parent


def annotate_types(parent: Object):
    functions = flatten_objects(parent)
    while True:
        dependencies = TopologicalSorter()
        added = False
        for func in functions:
            try:
                func.reset()
                InferenceVisitor(func).visit(func.original_node)
                func.is_analyzed = True
            except DependencyError as e:
                if isinstance(e.class_or_func, Class):
                    module = (
                        func.cls.container if func.is_method else func.container
                    )
                    if e.class_or_func not in module.type_dependencies:
                        module.type_dependencies.append(e.class_or_func)
                    dependencies.add(func, *flatten_objects(e.class_or_func))
                elif isinstance(e.class_or_func, Function):
                    dependencies.add(func, e.class_or_func)
                else:
                    raise TypeError(
                        f"Cannot handle dependency of type {type(e.class_or_func)}."
                    ) from e
                added = True
        if not added:
            break
        functions = dependencies.static_order()


def load_builtins():
    from pyjs import python as python_builtins

    for name, value in vars(python_builtins).items():
        if not (
            name.startswith("_")
            and not name.startswith("__")
            and is_cls_or_func(value)
        ):
            continue
        value.__js__ = True
        value.__builtin__ = True
    return Module(python_builtins, {}, is_builtins=True).build()


ModuleScope.BUILTINS = BUILTINS = load_builtins()
annotate_types(BUILTINS)
