import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from graphlib import CycleError, TopologicalSorter

from .diagnostics import CompilationContext, CompilationError, DiagnosticCode, Label
from .objects import *

TYPING_TYPE_ALIASES = {
    "Any": "object",
    "Dict": "dict",
    "List": "list",
    "Set": "set",
    "Tuple": "tuple",
    **GENERIC_TYPE_ALIASES,
}

FORMAT_SPEC = re.compile(
    r"(?P<zero>0)?(?P<width>\d+)?(?:\.(?P<precision>\d+))?(?P<type>[df%])"
)
JS_MAX_SAFE_INTEGER = 2**53 - 1


def constant_integer_value(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant):
        return int(node.value) if type(node.value) in (bool, int) else None
    if isinstance(node, ast.UnaryOp):
        value = constant_integer_value(node.operand)
        if value is None:
            return None
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Invert):
            return ~value
        return None
    if not isinstance(node, ast.BinOp):
        return None
    left = constant_integer_value(node.left)
    right = constant_integer_value(node.right)
    if left is None or right is None:
        return None
    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        return left * right
    if isinstance(node.op, ast.FloorDiv) and right:
        return left // right
    if isinstance(node.op, ast.Mod) and right:
        return left % right
    if isinstance(node.op, ast.Pow) and right >= 0:
        if abs(left) > 1 and right > 53:
            return JS_MAX_SAFE_INTEGER + 1
        return left**right
    if isinstance(node.op, ast.BitAnd):
        return left & right
    if isinstance(node.op, ast.BitOr):
        return left | right
    if isinstance(node.op, ast.BitXor):
        return left ^ right
    if isinstance(node.op, ast.LShift) and right >= 0:
        if left != 0 and right > 53:
            return JS_MAX_SAFE_INTEGER + 1
        return left << right
    if isinstance(node.op, ast.RShift) and right >= 0:
        return left >> right
    return None


def constant_format_spec(node: ast.JoinedStr | None) -> str | None:
    if node is None or not all(
        isinstance(value, ast.Constant) and isinstance(value.value, str)
        for value in node.values
    ):
        return None
    return "".join(value.value for value in node.values)


def flatten_isinstance_targets(node: ast.expr) -> list[ast.expr]:
    if not isinstance(node, ast.Tuple):
        return [node]
    return [
        target
        for element in node.elts
        for target in flatten_isinstance_targets(element)
    ]


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


@dataclass(frozen=True)
class IterableProtocol:
    item_type: Class | UnionType
    methods: tuple[Function, ...]


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


def generated_method(value_type, marker: str) -> Function | None:
    if not isinstance(value_type, Class):
        return None
    method_name = getattr(value_type.py_cls, marker, None)
    if method_name is None:
        return None
    method = value_type.find(method_name)
    return method if isinstance(method, Function) else None


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


def iterable_protocol(value_type):
    item_type = None
    methods = []
    for member in get_type_members(value_type):
        if isinstance(member, TypedDictClass):
            member_type = BUILTINS.search("str")
        else:
            method = member.find_attrs("__iter__")
            if not isinstance(method, Function):
                return None
            if not method.signature_analyzed:
                raise DependencyError(method)
            if (
                method.is_static
                or method.is_classmethod
                or method.params
                or method.vararg is not None
                or method.kwonlyargs
                or method.kwarg is not None
            ):
                return None
            return_type = method.declared_return_type
            if not (
                isinstance(return_type, Class)
                and return_type.generic_name == "Iterator"
            ):
                return None
            methods.append(method)
            if member.generic_name == "tuple":
                member_type = None
                for tuple_type in member.generic_types.values():
                    member_type = merge_return_types(member_type, tuple_type)
            else:
                member_type = return_type.generic_types["V"]
        item_type = merge_return_types(item_type, member_type)
    if item_type is None:
        return None
    return IterableProtocol(item_type, tuple(dict.fromkeys(methods)))


def expects_iterable(value_type):
    return any(
        isinstance(member, Class) and member.generic_name == "Iterable"
        for member in get_type_members(value_type)
    )


def uses_iterable_protocol(expected, value):
    return expects_iterable(expected) and not is_return_type_compatible(
        expected,
        analyzed_value_type(value),
    )


def is_iterable_argument_compatible(expected, actual):
    expected_members = get_type_members(expected)
    expected_iterables = [
        member
        for member in expected_members
        if isinstance(member, Class) and member.generic_name == "Iterable"
    ]
    if not expected_iterables:
        return False
    for actual_member in get_type_members(actual):
        protocol = iterable_protocol(actual_member)
        if protocol is not None:
            if any(
                is_return_type_compatible(
                    expected_type.generic_types["V"],
                    protocol.item_type,
                )
                for expected_type in expected_iterables
            ):
                continue
            return False
        if not any(is_subclass(actual_member, member) for member in expected_members):
            return False
    return True


def is_call_argument_compatible(expected, value):
    actual = analyzed_value_type(value)
    if is_return_type_compatible(expected, actual):
        return True
    if expects_iterable(expected):
        if isinstance(value.obj, GenericClass):
            return value.obj.name in {"dict", "list", "set", "tuple"}
        return is_iterable_argument_compatible(expected, actual)
    expected_members = get_type_members(expected)
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
    return False


def is_subclass(actual, expected):
    if same_analyzer_type(actual, expected):
        return True
    if isinstance(actual, TypeVariableClass):
        return actual.bound is not None and is_return_type_compatible(
            expected,
            actual.bound,
        )
    if (
        isinstance(actual, Class)
        and isinstance(expected, Class)
        and expected.name == "object"
    ):
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
    ):
        if expected.generic_name == "tuple" and len(expected.generic_types) == 1:
            expected_item = next(iter(expected.generic_types.values()))
            return all(
                is_return_type_compatible(expected_item, actual_item)
                for actual_item in actual.generic_types.values()
            )
        if actual.generic_types.keys() == expected.generic_types.keys():
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
        try:
            if all(
                isinstance(actual.find(name), Function)
                for name in structural_method_names(expected)
            ):
                return True
        except NameError:
            pass
    while actual is not None:
        if actual.name == expected.name:
            return True
        actual = actual.super
    return False


def is_isinstance_match(actual, expected):
    if expected.name == "float" and actual.name in {"bool", "int"}:
        return False
    return is_subclass(actual, expected)


def structural_method_names(cls: Class) -> tuple[str, ...]:
    if not getattr(cls.py_cls, "__pyjs_structural__", False):
        return ()
    return tuple(
        name
        for name, value in cls.internal_scope.names.items()
        if isinstance(value, Function) and not name.startswith("_")
    )


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


def merge_conditional_types(left, right):
    if not isinstance(left, CallableClass) or not isinstance(right, CallableClass):
        return merge_return_types(left, right)
    if left.parameter_types is None:
        parameters = right.parameter_types
    elif right.parameter_types is None:
        parameters = left.parameter_types
    elif len(left.parameter_types) == len(right.parameter_types) and all(
        same_analyzer_type(left_type, right_type)
        for left_type, right_type in zip(
            left.parameter_types,
            right.parameter_types,
            strict=True,
        )
    ):
        parameters = left.parameter_types
    else:
        return merge_return_types(left, right)
    return CallableClass(
        parameters,
        merge_return_types(left.return_type, right.return_type),
        left.super,
    )


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
        if len(candidates) == 1:
            infer_type_variables(candidates[0], actual, bindings)
            return
        concrete = [
            member
            for member in pattern.types
            if not contains_type_variable(member)
        ]
        if any(is_return_type_compatible(member, actual) for member in concrete):
            return
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
    if not isinstance(actual, Class):
        return
    while actual is not None and pattern.generic_name != actual.generic_name:
        actual = actual.super
    if actual is None:
        return
    for pattern_member, actual_member in zip(
        pattern.generic_types.values(),
        actual.generic_types.values(),
        strict=False,
    ):
        infer_type_variables(pattern_member, actual_member, bindings)


def analyzed_value_object(value):
    return value.value_obj if isinstance(value, (Call, Subscript, IfExp)) else value.obj


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
    if value_obj.is_async:
        awaitable = BUILTINS.search("Awaitable")
        assert isinstance(awaitable, GenericClass)
        return_type = awaitable(return_type)
    return CallableClass(
        tuple(parameter.annotation.obj for parameter in value_obj.params),
        return_type,
        base,
    )


def infer_generic_call_type(generic: GenericClass, arguments: list[ast.expr]):
    if not generic.init_params or not generic.type_parameters:
        return None
    bindings = {}
    parameters = list(generic.init_params.values())[1:]
    for argument, parameter in zip(arguments, parameters, strict=False):
        if parameter.annotation is parameter.empty:
            continue
        pattern = resolve_python_annotation(parameter.annotation, generic.scope)
        infer_type_variables(pattern, callable_value_type(argument), bindings)
    concrete = [
        bindings.get(parameter)
        for parameter in generic.type_parameters.values()
    ]
    if not all(isinstance(value, (Class, UnionType)) for value in concrete):
        return None
    return generic(*concrete)


def conditional_value_type(value, other_type):
    value_obj = analyzed_value_object(value)
    if isinstance(value_obj, (CallableClass, Function)) or (
        isinstance(value_obj, Instance)
        and isinstance(value_obj.cls, CallableClass)
    ):
        return callable_value_type(value)
    value_type = value.obj
    if (
        isinstance(value_type, GenericClass)
        and isinstance(other_type, Class)
        and other_type.generic_name == value_type.name
    ):
        return other_type
    return analyzed_value_type(value)


def iterable_item_type(value_type):
    protocol = iterable_protocol(value_type)
    return protocol.item_type if protocol is not None else value_type


def field_owner(field):
    if not isinstance(field, Instance):
        return None
    if isinstance(field.container, Class):
        return field.container
    if (
        isinstance(field.container, Instance)
        and field.container is field.container.cls._self
    ):
        return field.container.cls
    return None


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
        except CompilationError:
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

    def round(self, runtime):
        result = self.standard()
        ndigits = [*result.args, *(keyword.value for keyword in result.keywords)]
        ndigit_members = tuple(
            member
            for value in ndigits
            for member in get_type_members(analyzed_value_type(value))
        )
        if not ndigits or all(member.name == "NoneType" for member in ndigit_members):
            result.args = []
            result.keywords = []
            return result

        assert isinstance(result.func, Attribute)
        receiver = result.func.value
        members = get_type_members(analyzed_value_type(receiver))
        if any(member.name not in {"bool", "float", "int"} for member in members):
            return result

        runtime_interface = resolve_imported(runtime, self.visitor.module)
        if not isinstance(runtime_interface, Function):
            raise TypeError("round() runtime must be a function")
        runtime_obj = runtime_interface.container.value_implementation(
            runtime_interface
        )
        if not runtime_obj.is_analyzed:
            annotate_types(runtime_obj)
        result_types = [
            BUILTINS.search("float")
            if member.name == "float"
            else BUILTINS.search("int")
            for member in members
        ]
        if any(member.name == "NoneType" for member in ndigit_members):
            result_types.append(BUILTINS.search("int"))
        result_type = UnionType(types=result_types).type
        value_obj = result_type
        if isinstance(result_type, Class):
            value_obj = result_type(
                "__round_result__",
                self.visitor.scope,
                self.visitor.func,
            )
        return Call(
            result_type,
            value_obj=value_obj,
            func=Name(runtime_obj, runtime_dependency=runtime_obj),
            args=[
                receiver,
                ndigits[0],
                Constant(
                    BUILTINS.search("bool"),
                    value=any(member.name == "float" for member in members),
                ),
            ],
            keywords=[],
        )

    def isinstance(self):
        if len(self.node.args) != 2 or self.node.keywords:
            return self.standard()

        value = self.visitor.visit(self.node.args[0])
        target_nodes = flatten_isinstance_targets(self.node.args[1])
        if all(
            isinstance(target, (ast.Name, ast.Attribute))
            for target in target_nodes
        ):
            target_types = [
                self.visitor.isinstance_type(target) for target in target_nodes
            ]
            self.validate_numeric_isinstance(
                analyzed_value_type(value),
                target_types,
            )

        if not isinstance(self.node.args[1], ast.Tuple):
            return self.standard()

        value_obj = analyzed_value_object(value)
        checks = []
        for target in target_nodes:
            check = ast.copy_location(
                ast.Call(
                    func=self.node.func,
                    args=[self.node.args[0], target],
                    keywords=[],
                ),
                self.node,
            )
            analyzed = _CallAnalysis(
                self.visitor,
                check,
                self.function,
            ).standard()
            assert isinstance(analyzed, Call)
            analyzed.args[0] = Name(value_obj, id="$value")
            checks.append(analyzed)

        if checks:
            body = (
                checks[0]
                if len(checks) == 1
                else ast.BoolOp(op=ast.Or(), values=checks)
            )
        else:
            body = Constant(BUILTINS.search("bool"), value=False)
        return EvaluateOnce(
            BUILTINS.search("bool"),
            value,
            body,
            "$value",
            lineno=self.node.lineno,
        )

    def validate_numeric_isinstance(self, value_type, target_types):
        members = get_type_members(value_type)
        could_be_int = any(
            member.name in {"bool", "int", "object"} for member in members
        )
        could_be_float = any(
            member.name in {"float", "object"} for member in members
        )
        if not (could_be_int and could_be_float):
            return

        int_type = BUILTINS.search("int")
        float_type = BUILTINS.search("float")
        matches_int = any(
            is_isinstance_match(int_type, target) for target in target_types
        )
        matches_float = any(
            is_isinstance_match(float_type, target) for target in target_types
        )
        if matches_int == matches_float:
            return

        self.visitor.fail(
            self.node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            "isinstance() cannot distinguish int from float after JavaScript "
            "lowering",
            help="Narrow the value statically before testing its numeric type.",
        )

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
        method = generated_method(
            analyzed_value_type(result),
            "__pyjs_reference_method__",
        )
        if method is not None:
            result.generated_virtual_methods = (method,)
        return result

    def receiver_metadata_type(
        self,
        attribute: str,
        *,
        runtime_method: str | None = None,
    ):
        result = self.standard()
        if not isinstance(result.func, Attribute):
            return result
        receiver = analyzed_value_type(result.func.value)
        if not isinstance(receiver, Class):
            return result
        metadata_type = getattr(receiver.py_cls, attribute, None)
        if not isinstance(metadata_type, type):
            return result
        result_type = resolve_imported(metadata_type, self.visitor.module)
        if not isinstance(result_type, Class):
            return result
        result = self.with_result_type(result_type)
        if runtime_method is not None:
            method = result_type.find(runtime_method)
            if not isinstance(method, Function):
                raise TypeError(
                    f"{metadata_type.__name__}.{runtime_method} must be a method"
                )
            result.generated_virtual_methods = (
                *result.generated_virtual_methods,
                method,
            )
        return result

    def receiver_mapped_annotation_type(
        self,
        attribute: str,
        selector_argument: int,
        *,
        optional: bool = False,
    ):
        result = self.standard()
        if not isinstance(result.func, Attribute):
            return result
        receiver = analyzed_value_type(result.func.value)
        if not isinstance(receiver, Class):
            return result
        if selector_argument >= len(result.args):
            return result
        selector = result.args[selector_argument]
        if not isinstance(selector, Attribute):
            return result
        annotations = getattr(receiver.py_cls, attribute, None)
        if annotations is None:
            return result
        annotation = annotations.get(selector.attr)
        if annotation is None:
            return result
        ensure_annotation_dependencies(annotation, self.visitor.module)
        result_type = resolve_python_annotation(annotation, receiver.scope)
        if optional and not any(
            member.name == "NoneType" for member in get_type_members(result_type)
        ):
            result_type = UnionType(types=(result_type, get_none_type())).type
        return self.with_result_type(result_type)

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

    def mapped(self, *, max_iterables):
        if len(self.node.args) > max_iterables + 1:
            self.visitor.fail(
                self.node.args[max_iterables + 1],
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"map() supports at most {max_iterables} iterables",
                help=(
                    "Define a typed loop when mapping more iterables in one "
                    "operation."
                ),
            )
        return self.standard()

    def argument_dunders(self, *method_names):
        result = self.standard()
        methods = [
            method
            for argument in result.args
            for method in runtime_dunder_methods(
                analyzed_value_type(argument),
                *method_names,
            )
        ]
        result.runtime_methods = tuple(
            dict.fromkeys((*result.runtime_methods, *methods))
        )
        return result

    def stringify_arguments(self, *type_names):
        result = self.standard()
        for index, argument in enumerate(result.args):
            argument_type = analyzed_value_type(argument)
            if (
                not isinstance(argument_type, Class)
                or argument_type.generic_name not in type_names
            ):
                continue
            method = argument_type.find("__str__")
            assert isinstance(method, Function)
            return_type = method.return_type or method.declared_return_type
            assert isinstance(return_type, Class)
            result.args[index] = self.visitor.call_node(
                self.node,
                return_type,
                func=Attribute(method, value=argument, attr="__str__"),
                args=[],
                keywords=[],
                dependency_objects=self.visitor.inline_dependencies(method, self.node),
            )
        return result

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
        result_type = self.visitor.typed_dict_field_type(receiver_type, key)
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
        value_type = getattr(
            result.args[0],
            "mapping_source_type",
            analyzed_value_type(result.args[0]),
        )
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
        self.in_exception_handler = False

    def visit(self, node):
        result = super().visit(node)
        if isinstance(result, list):
            for replacement in result:
                if isinstance(replacement, ast.AST):
                    ast.copy_location(replacement, node)
        elif isinstance(result, ast.AST):
            ast.copy_location(result, node)
        return result

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
    def attribute_names(value: Instance | Class) -> set[str]:
        if isinstance(value, Instance):
            names = set(value.attrs)
            cls = value.cls
        else:
            names = set()
            cls = value
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
        first_inline = first.decoration("__js_inline__")
        first_dependencies = first.decoration("__js_inline_dependencies__")
        incompatible = [
            member_type.name
            for member_type, method in zip(value_type.types, methods, strict=True)
            if method.decoration("__js_inline__") is not first_inline
            or method.is_async != first.is_async
            or method.decoration("__js_inline_dependencies__") != first_dependencies
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
        forwarded_count = len(interface.params) + receiver_count
        extra_parameters = len(target_obj.params) - forwarded_count
        compatible = (
            extra_parameters >= 0
            and len(target_obj.defaults) - len(interface.defaults)
            == extra_parameters
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
                target_obj.params[receiver_count:forwarded_count],
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
        *,
        skip_positional: int = 0,
    ):
        runtime_methods = []
        parameters = {
            parameter.arg: parameter
            for parameter in function.params[function.posonly_count :]
        }
        parameters.update(
            {parameter.arg: parameter for parameter in function.kwonlyargs}
        )
        for index, argument in enumerate(args):
            if index < skip_positional or isinstance(argument, ast.Starred):
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
            runtime_methods.extend(
                self.argument_protocol_methods(expected_type, argument)
            )
            if uses_iterable_protocol(expected_type, argument):
                args[index] = self.mapping_keys_iterable(argument)

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
            runtime_methods.extend(
                self.argument_protocol_methods(expected_type, keyword.value)
            )
            if uses_iterable_protocol(expected_type, keyword.value):
                keyword.value = self.mapping_keys_iterable(keyword.value)
        return tuple(dict.fromkeys(runtime_methods))

    @staticmethod
    def argument_protocol_methods(expected_type, value):
        methods = []
        actual_members = get_type_members(analyzed_value_type(value))
        if uses_iterable_protocol(expected_type, value):
            for member in actual_members:
                protocol = iterable_protocol(member)
                if protocol is not None:
                    methods.extend(protocol.methods)
        for expected_member in get_type_members(expected_type):
            for method_name in structural_method_names(expected_member):
                for actual_member in actual_members:
                    try:
                        method = actual_member.find(method_name)
                    except NameError:
                        continue
                    if isinstance(method, Function):
                        methods.append(method)
        return tuple(dict.fromkeys(methods))

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
            if (
                callable_function is not self.func
                and not callable_function.signature_analyzed
            ):
                raise DependencyError(callable_function)
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

    def isinstance_type(self, node):
        value_type = self.visit(node).obj
        if (
            isinstance(value_type, Instance)
            and value_type.cls.generic_name == "type"
        ):
            target_type = value_type.cls.generic_types["T"]
            if isinstance(target_type, Class):
                return target_type
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "isinstance() requires one concrete runtime class",
                help="Narrow the type object before using it with isinstance().",
            )
        if isinstance(value_type, GenericClass):
            object_type = BUILTINS.search("object")
            if value_type.name == "dict":
                return BUILTINS.search("dict")(object_type, object_type)
            if value_type.name in ("list", "set"):
                return BUILTINS.search(value_type.name)(object_type)
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"isinstance() does not support unsubscripted "
                f"{value_type.name!r}",
                help="Test against a concrete runtime class.",
            )
        assert isinstance(value_type, Class)
        return value_type

    def get_isinstance_narrowing(self, test, when_true):
        if (
            not isinstance(test, ast.Call)
            or not isinstance(test.func, ast.Name)
            or test.func.id != "isinstance"
            or len(test.args) != 2
            or not isinstance(test.args[0], (ast.Name, ast.Attribute))
            or not isinstance(test.args[1], (ast.Name, ast.Tuple))
        ):
            return None
        target_nodes = flatten_isinstance_targets(test.args[1])
        if not target_nodes:
            return None
        target_types = [self.isinstance_type(node) for node in target_nodes]
        value_node = test.args[0]
        current_type = analyzed_value_type(self.visit(value_node))
        matching = [
            member
            for member in get_type_members(current_type)
            if any(
                is_isinstance_match(member, target) for target in target_types
            )
        ]
        nonmatching = [
            member
            for member in get_type_members(current_type)
            if member not in matching
        ]
        if not when_true:
            if not nonmatching:
                return None
            return value_node, UnionType(types=nonmatching).type
        if matching and not any(
            is_isinstance_match(target, member)
            for member in nonmatching
            for target in target_types
        ):
            value_type = UnionType(types=matching).type
        else:
            value_type = UnionType(types=target_types).type
        return value_node, value_type

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

        narrowing = self.get_isinstance_narrowing(test, when_true)
        if narrowing is not None:
            return [narrowing]

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

    def branch_visitor(self, test, when_true):
        narrowed = self.narrow_for_condition(test, when_true)
        return type(self)(self.func, LocalScope(narrowed.scope))

    def merge_branch_declarations(self, *visitors):
        names = dict.fromkeys(
            name for visitor in visitors for name in visitor.scope.names
        )
        for name in names:
            value_type = None
            for visitor in visitors:
                value = visitor.scope.names.get(name)
                if isinstance(value, Instance):
                    value_type = merge_return_types(value_type, value.cls)
            if value_type is not None:
                self.scope.add(value_type(name, self.scope, self.func))

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

    def typed_dict_field_type(self, typed_dict, key):
        if key.value not in typed_dict.annotations:
            fields = ", ".join(repr(name) for name in typed_dict.annotations)
            help = (
                f"Use one of: {fields}."
                if fields
                else f"{typed_dict.name} defines no fields."
            )
            self.fail(
                key,
                DiagnosticCode.UNDEFINED_KEY,
                f"{typed_dict.name} has no key {key.value!r}",
                help=help,
            )
        return typed_dict.field_type(key.value)

    def apply_typed_dict_literal(self, value, expected_type):
        if isinstance(expected_type, TypedDictClass) and isinstance(value, Dict):
            value.obj = expected_type
            for key, item in zip(value.keys, value.values, strict=True):
                if not isinstance(key, Constant) or not isinstance(key.value, str):
                    self.fail(
                        key,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        "TypedDict literal keys must be string literals",
                        help=(
                            "Use a literal key so its field type can be "
                            "determined statically."
                        ),
                    )
                self.apply_typed_dict_literal(
                    item,
                    self.typed_dict_field_type(expected_type, key),
                )
        elif (
            isinstance(expected_type, Class)
            and expected_type.generic_name == "list"
            and isinstance(value, List)
        ):
            item_type = expected_type.generic_types["V"]
            for item in value.elts:
                self.apply_typed_dict_literal(item, item_type)

    def analyze_assignment_value(
        self,
        value_node,
        annotation_node=None,
        contextual_type=None,
    ):
        declared_type = None
        if annotation_node:
            annotation = self.visit_type_annotation(annotation_node).obj
            if isinstance(annotation, (Class, UnionType)):
                declared_type = annotation

        expected_type = declared_type or contextual_type
        value = self.visit_contextual_expression(value_node, expected_type)
        if declared_type is not None:
            self.apply_typed_dict_literal(value, declared_type)

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

        contextual_type = None
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                existing = self.declared_local(node.targets[0].id)
            except NameError:
                pass
            else:
                if isinstance(existing, Instance):
                    contextual_type = existing.cls
        assignment_value = self.analyze_assignment_value(
            node.value,
            contextual_type=contextual_type,
        )
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
        if node.value is None:
            if not isinstance(node.target, ast.Name):
                self.fail(
                    node.target,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "Annotation-only declarations require a local name",
                    help=(
                        "Assign an initial value in __init__(), or declare the type "
                        "on the class when initialization must happen later."
                    ),
                )
            declared_type = self.visit_type_annotation(node.annotation).obj
            assert isinstance(declared_type, (Class, UnionType))
            target, is_new_name = self.resolve_assignment_target(
                node.target,
                declared_type,
            )
            if not is_new_name:
                return ast.Pass(lineno=node.lineno)
            return ast.AnnAssign(
                target=target,
                annotation=declared_type.annotation,
                value=None,
                simple=isinstance(node.target, ast.Name),
                lineno=target.lineno,
            )
        assignment_value = self.analyze_assignment_value(node.value, node.annotation)
        if (
            isinstance(node.target, ast.Attribute)
            and isinstance(node.target.value, ast.Name)
            and node.target.value.id == "self"
            and assignment_value.declared_type is not None
            and self.func.cls is not None
        ):
            self.record_native_attribute(
                node.target.attr,
                assignment_value.declared_type,
                declared=True,
            )
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
            if isinstance(target, ast.Name):
                self.fail(
                    target,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "Deleting local names is not supported",
                    help="Let local values go out of scope instead of deleting them.",
                )
            elif isinstance(target, ast.Subscript):
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
            client_initializer = None
            if isinstance(value_obj, Instance):
                value_init = value_obj.cls.init
                client_initializer = value_obj.cls.find_attrs(
                    "initialize",
                    search_bases=False,
                )
            elif isinstance(value_obj, Class):
                value_init = value_obj.init
                client_initializer = value_obj.find_attrs(
                    "initialize",
                    search_bases=False,
                )
            if not isinstance(client_initializer, Function):
                client_initializer = None
            for initializer in (value_init, client_initializer):
                if (
                    isinstance(initializer, Function)
                    and initializer is not self.func
                    and not initializer.is_analyzed
                ):
                    raise DependencyError(initializer) from None
            value_init = client_initializer or value_init
            if (
                isinstance(value_obj, Instance)
                and value_obj.cls.generic_name == "tuple"
                and node.attr
                in {"__setitem__", "__setslice__", "__delitem__", "__delslice__"}
            ):
                action = "assign to" if node.attr.startswith("__set") else "delete"
                self.fail(
                    node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    f"Cannot {action} tuple items",
                    help="Use a list when items need to be changed.",
                )
            if node is self.assignment_target:
                raise
            if isinstance(value_obj, (Instance, Class)):
                cls = value_obj.cls if isinstance(value_obj, Instance) else value_obj
                can_define = isinstance(value_obj, Instance) and not (
                    cls.container.scope.is_builtins
                    or getattr(cls.py_obj, "__dict__", {}).get(
                        "__js_native__",
                        False,
                    )
                )
                self.module.context.attribute_lookup_error(
                    self.func.source_fragment,
                    node,
                    cls.name,
                    self.attribute_names(value_obj),
                    ast.unparse(node.value),
                    value_init.py_func
                    if can_define and value_init is not None
                    else None,
                    can_define=can_define,
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
            ctx=node.ctx,
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
        protocol = self.require_iterable(node.value, value)
        result = Starred(protocol.item_type, value=value)
        result.runtime_methods = protocol.methods
        return result

    def visit_Subscript(self, node: ast.Subscript):
        slice_node = self.visit(node.slice)
        value = self.visit(node.value)
        receiver_obj = analyzed_value_object(value)
        receiver_type = (
            receiver_obj.cls if isinstance(receiver_obj, Instance) else receiver_obj
        )
        if isinstance(slice_node, ast.Slice):
            method = receiver_obj.find("__slice__")
            if not method.is_analyzed:
                raise DependencyError(method)
            assert isinstance(method.return_type, (Class, UnionType))
            result_type = method.return_type
            if isinstance(receiver_type, Class) and receiver_type.generic_name == "tuple":
                item_types = list(receiver_type.generic_types.values())
                parts = (slice_node.lower, slice_node.upper, slice_node.step)
                try:
                    static_parts = tuple(ast.literal_eval(part) for part in parts)
                except (TypeError, ValueError):
                    static_parts = None
                if static_parts is not None and static_parts[2] != 0:
                    bounds = slice(*static_parts)
                    item_types = item_types[bounds]
                elif item_types:
                    item_types = [UnionType(types=item_types).type]
                tuple_type = BUILTINS.search("tuple")
                assert isinstance(tuple_type, GenericClass)
                result_type = tuple_type(*item_types)
            value_obj = result_type
            if isinstance(result_type, Class):
                value_obj = result_type(
                    "__slice_result__", self.scope, self.func
                )
            simple_step = (
                isinstance(slice_node.step, Constant)
                and slice_node.step.value in (None, 1)
            )
            if simple_step:
                dependency_objects = {}
            else:
                dependency_objects = self.inline_dependencies(method, node)
            return Call(
                result_type,
                value_obj=value_obj,
                func=Attribute(method, value=value, attr="__slice__"),
                args=[slice_node.lower, slice_node.upper, slice_node.step],
                keywords=[],
                dependency_objects=dependency_objects,
            )
        if isinstance(receiver_type, TypedDictClass):
            if not isinstance(slice_node, Constant) or not isinstance(
                slice_node.value, str
            ):
                self.fail(
                    slice_node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "TypedDict keys must be string literals",
                    help="Use a literal key so its field type can be determined statically.",
                )
            value_type = self.typed_dict_field_type(receiver_type, slice_node)
            value_obj = value_type
            if isinstance(value_type, Class):
                value_obj = value_type("__subscript_result__", self.scope, self.func)
            return Subscript(
                value_type,
                value_obj=value_obj,
                slice=slice_node,
                value=value,
            )
        if isinstance(receiver_type, Class) and receiver_type.generic_name == "tuple":
            item_types = list(receiver_type.generic_types.values())
            if (
                isinstance(slice_node, Constant)
                and isinstance(slice_node.value, int)
                and -len(item_types) <= slice_node.value < len(item_types)
            ):
                value_type = item_types[slice_node.value]
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
                [slice_node],
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
                [slice_node],
                [],
                getitem.return_type,
            )
        return Call(
            getitem.return_type,
            value_obj=value_obj,
            func=getitem_attribute,
            args=[slice_node],
            keywords=[],
        )

    # endregion

    # region functions

    def dispatch_dunder_call(self, builtin, method_name, args, keywords):
        assert args
        receiver_node = args[0]
        receiver_obj = receiver_node.obj
        if isinstance(receiver_obj, Class):
            receiver_obj = receiver_obj._self
        union_type = self.receiver_union(receiver_obj)
        if not isinstance(receiver_obj, Instance):
            receiver_type = analyzed_value_type(receiver_node).to_annotation_str()
            self.fail(
                receiver_node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{builtin.name}() is not supported for {receiver_type}",
                help=f"Pass a value that defines {method_name}().",
            )
        union_functions = ()
        receiver_name = receiver_obj.cls.name
        if union_type is None:
            try:
                method = receiver_obj.find(method_name)
            except NameError:
                self.fail(
                    receiver_node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{builtin.name}() is not supported for "
                    f"{receiver_obj.cls.to_annotation_str()}",
                    help=f"Pass a value that defines {method_name}().",
                )
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
            self.fail(
                receiver_node,
                DiagnosticCode.INCOMPATIBLE_RETURN,
                f"{receiver_name}.{method_name}() returns "
                f"{return_type.to_annotation_str()}, expected "
                f"{expected_type.to_annotation_str()}",
                help=(
                    f"Change {method_name}() to return "
                    f"{expected_type.to_annotation_str()}."
                ),
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
                for parameter in (
                    *function.params[function.posonly_count :],
                    *function.kwonlyargs,
                )
            }
            if not keyword_names <= accepted_keywords:
                return False
        required_count = len(function.params) - len(function.defaults)
        for index, parameter in enumerate(
            function.params[positional_count:required_count],
            start=positional_count,
        ):
            if index < function.posonly_count or parameter.arg not in keyword_names:
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

    @staticmethod
    def lambda_needs_type_bindings(argument, expected_type):
        expected_callable = callable_member(expected_type)
        return (
            isinstance(argument, ast.Lambda)
            and expected_callable is not None
            and expected_callable.parameter_types is not None
            and any(
                contains_type_variable(parameter)
                for parameter in expected_callable.parameter_types
            )
        )

    def analyze_call_arguments(
        self,
        node,
        signature_function,
        callable_signature,
    ):
        type_bindings = {}
        args = [None] * len(node.args)
        deferred_args = []
        for index, argument in enumerate(node.args):
            expected_type = None
            if (
                callable_signature is not None
                and callable_signature.parameter_types is not None
                and index < len(callable_signature.parameter_types)
            ):
                expected_type = callable_signature.parameter_types[index]
            pattern = self.call_argument_pattern(signature_function, index)
            parameter_type = expected_type
            if parameter_type is None and pattern is not None:
                parameter_type = substitute_type_variables(pattern, type_bindings)
            if self.lambda_needs_type_bindings(argument, parameter_type):
                deferred_args.append(index)
                continue
            if expected_type is None:
                args[index] = self.visit_call_argument(
                    argument,
                    signature_function,
                    index,
                    type_bindings,
                )
            else:
                args[index] = self.visit_contextual_expression(
                    argument,
                    expected_type,
                )
        keywords = [None] * len(node.keywords)
        deferred_keywords = []
        for index, keyword in enumerate(node.keywords):
            pattern = self.call_keyword_pattern(keyword, signature_function)
            expected_type = (
                substitute_type_variables(pattern, type_bindings)
                if pattern is not None
                else None
            )
            if self.lambda_needs_type_bindings(keyword.value, expected_type):
                deferred_keywords.append(index)
                continue
            keywords[index] = self.visit_call_keyword(
                keyword,
                signature_function,
                type_bindings,
            )
        for index in deferred_args:
            args[index] = self.visit_call_argument(
                node.args[index],
                signature_function,
                index,
                type_bindings,
            )
        for index in deferred_keywords:
            keywords[index] = self.visit_call_keyword(
                node.keywords[index],
                signature_function,
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

    def expand_static_call_keywords(self, node: ast.Call) -> None:
        keywords = []
        expanded_names = set()
        for keyword in node.keywords:
            if keyword.arg is not None:
                keywords.append(keyword)
                continue
            if not isinstance(keyword.value, ast.Dict) or any(
                not isinstance(key, ast.Constant) or not isinstance(key.value, str)
                for key in keyword.value.keys
            ):
                self.fail(
                    keyword.value,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "dynamic ** argument expansion is not supported",
                    help="Pass named arguments or expand a literal string-keyed dictionary.",
                )
            for key, value in zip(
                keyword.value.keys,
                keyword.value.values,
                strict=True,
            ):
                if key.value in expanded_names:
                    self.fail(
                        key,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        f"** argument contains duplicate key {key.value!r}",
                        help="Keep each named argument only once.",
                    )
                expanded_names.add(key.value)
                expanded = ast.keyword(arg=key.value, value=value)
                ast.copy_location(expanded, key)
                keywords.append(expanded)
        node.keywords = keywords

    def validate_call_shape(self, node: ast.Call, function: Function | None) -> None:
        if function is None:
            return
        positional_names = [parameter.arg for parameter in function.params]
        positional_only = set(positional_names[: function.posonly_count])
        keyword_only = {parameter.arg for parameter in function.kwonlyargs}
        accepted_keywords = set(positional_names) | keyword_only
        assigned_parameters = set()
        seen_keywords = set()
        has_starred = any(isinstance(argument, ast.Starred) for argument in node.args)
        if not has_starred:
            if function.vararg is None and len(node.args) > len(positional_names):
                self.fail(
                    node.args[len(positional_names)],
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{function.name}() received too many positional arguments",
                    help=f"Pass at most {len(positional_names)} positional arguments.",
                )
            assigned_parameters.update(positional_names[: len(node.args)])

        for keyword in node.keywords:
            name = keyword.arg
            assert name is not None
            if name in seen_keywords:
                self.fail(
                    keyword,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{function.name}() received multiple values for {name!r}",
                    help=f"Pass {name!r} only once.",
                )
            seen_keywords.add(name)
            if name in positional_only and function.kwarg is None:
                self.fail(
                    keyword,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{function.name}() parameter {name!r} is positional-only",
                    help=f"Pass {name!r} as a positional argument.",
                )
            if name not in positional_only and name in assigned_parameters:
                self.fail(
                    keyword,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{function.name}() received multiple values for {name!r}",
                    help=f"Pass {name!r} only once.",
                )
            if name not in accepted_keywords and function.kwarg is None:
                self.fail(
                    keyword,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{function.name}() got an unexpected keyword argument {name!r}",
                    help="Use a parameter name from the function signature.",
                )
            if name not in positional_only:
                assigned_parameters.add(name)

        if has_starred:
            return
        required_count = len(function.params) - len(function.defaults)
        missing = [
            name
            for name in positional_names[:required_count]
            if name not in assigned_parameters
        ]
        missing.extend(
            parameter.arg
            for parameter, default in zip(
                function.kwonlyargs,
                function.kw_defaults,
                strict=True,
            )
            if default is None and parameter.arg not in assigned_parameters
        )
        if missing:
            names = ", ".join(repr(name) for name in missing)
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{function.name}() is missing required argument(s): {names}",
                help="Pass every required argument.",
            )

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

    def fail_not_callable(self, node, value_type):
        members = get_type_members(value_type)
        if len(members) > 1 and all(
            isinstance(member, CallableClass) for member in members
        ):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Callable value has incompatible signatures",
                help=(
                    "Narrow the value or use callables with matching positional "
                    "parameter types."
                ),
            )
        self.fail(
            node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"Value of type {value_type.to_annotation_str(' | ')} is not callable",
            help="Call a function, class, or typed Callable value.",
        )

    @staticmethod
    def prepare_dictionary_call(
        call_target: Class,
        called_function: Function,
        args: list[ast.expr],
        keywords: list[ast.keyword],
    ) -> tuple[str, ...] | None:
        if not getattr(call_target.py_obj, "__js_dictionary__", False):
            return None
        supplied = {
            parameter.arg for parameter in called_function.params[: len(args)]
        } | {keyword.arg for keyword in keywords}
        first_default = len(called_function.params) - len(called_function.defaults)
        defaults = [
            *zip(
                called_function.params[first_default:],
                called_function.defaults,
                strict=True,
            ),
            *zip(
                called_function.kwonlyargs,
                called_function.kw_defaults,
                strict=True,
            ),
        ]
        keywords.extend(
            ast.keyword(arg=parameter.arg, value=default)
            for parameter, default in defaults
            if parameter.arg not in supplied
            and default is not None
            and not (isinstance(default, ast.Constant) and default.value is None)
        )

        property_names = {}
        for statement in ast.walk(called_function.original_node):
            if isinstance(statement, ast.Assign):
                targets = statement.targets
                value = statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
                value = statement.value
            else:
                continue
            if not isinstance(value, ast.Name):
                continue
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    property_names[value.id] = target.attr

        def property_name(parameter_name: str) -> str:
            return property_names.get(parameter_name, parameter_name)

        return tuple(
            [
                property_name(parameter.arg)
                for parameter in called_function.params[: len(args)]
            ]
            + [property_name(keyword.arg) for keyword in keywords]
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
        if (
            isinstance(call_target, GenericClass)
            and call_target.name == "type"
        ) or (
            isinstance(call_target, Class)
            and call_target.generic_name == "type"
        ):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "runtime type() introspection is not supported",
                help=(
                    "Use static annotations or a supported isinstance() check "
                    "instead."
                ),
            )
        if isinstance(call_target, CallableClass):
            callable_signature = call_target
        elif isinstance(call_target, Instance):
            if isinstance(call_target.cls, UnionType):
                self.fail_not_callable(node.func, call_target.cls)
            try:
                called_function = call_target.find("__call__")
            except NameError:
                self.fail_not_callable(node.func, call_target.cls)
            assert isinstance(called_function, Function)
            if isinstance(call_target.cls, CallableClass):
                callable_signature = call_target.cls
        elif (
            isinstance(call_target, Class)
            and analyzed_value_type(func) is call_target
        ):
            self.fail_not_callable(node.func, call_target)
        else:
            assert isinstance(call_target, (GenericClass, Class, Function))
            if isinstance(call_target, Function):
                called_function = call_target
            elif (
                isinstance(call_target, Class)
                and not getattr(call_target.py_obj, "__builtin__", False)
                and not is_client_model_type(call_target)
                and not (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "super"
                )
            ):
                called_function = call_target.find("__init__")
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
            if called_function is self.func:
                self.fail(
                    node,
                    DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                    f"Return type of recursive function {self.func.name!r} "
                    "cannot be inferred",
                    help="Add an explicit return annotation.",
                )
            raise DependencyError(called_function)
        if called_function is not None:
            for overload in called_function.overloads:
                if not overload.signature_analyzed:
                    raise DependencyError(overload)
        self.expand_static_call_keywords(node)
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
        is_super_method_call = (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        )
        generated_dataclass_init = (
            self.func.name == "__init__"
            and self.func.cls is not None
            and self.func.cls.is_dataclass
            and self.func.py_func.__code__.co_filename == "<string>"
        )
        if not (is_super_method_call and generated_dataclass_init):
            self.validate_call_shape(node, signature_function)

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
            runtime_methods = ()
            if signature_function is not None:
                runtime_methods = self.validate_call_argument_types(
                    node,
                    signature_function,
                    args,
                    keywords,
                    type_bindings,
                    skip_positional=1,
                )
            result = self.dispatch_dunder_call(
                dunder_builtin, method_name, args, keywords
            )
            result.runtime_methods = tuple(
                dict.fromkeys((*result.runtime_methods, *runtime_methods))
            )
            return result

        if isinstance(call_target, CallableClass):
            return_type = call_target.return_type
        elif isinstance(call_target, Instance):
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
                return_type = infer_generic_call_type(call_target, args)
                if return_type is None:
                    try:
                        return_type = call_target.from_call([a.obj for a in args])
                    except TypeError:
                        self.fail(
                            node,
                            DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                            f"Type arguments for {call_target.name}() cannot "
                            "be inferred",
                            help=(
                                "Add an explicit specialized annotation that "
                                "provides the missing types."
                            ),
                        )
            func = Name(return_type)
        else:
            raise NotImplementedError(f"Don't know how to handle {call_target} call.")
        if called_function is not None:
            return_type = substitute_type_variables(return_type, type_bindings)
        argument_runtime_methods = ()
        if callable_signature is not None:
            argument_runtime_methods = self.validate_callable_call(
                node,
                callable_signature,
                args,
                keywords,
            )
        elif called_function is not None:
            argument_runtime_methods = self.validate_call_argument_types(
                node,
                signature_function,
                args,
                keywords,
                type_bindings,
            )
        elif (
            args
            and isinstance(return_type, Class)
            and return_type.generic_name in {"dict", "list", "set", "tuple"}
        ):
            protocol = iterable_protocol(analyzed_value_type(args[0]))
            if protocol is not None:
                argument_runtime_methods = protocol.methods
        contract_methods = (
            self.runtime_contract_methods(func, called_function, args)
            if called_function is not None
            else ()
        )
        runtime_methods = tuple(
            dict.fromkeys((*argument_runtime_methods, *contract_methods))
        )
        if (
            isinstance(call_target, Instance)
            and not isinstance(call_target.cls, CallableClass)
            and not getattr(call_target.cls.py_obj, "__builtin__", False)
            and called_function is not None
        ):
            runtime_methods = tuple(
                dict.fromkeys((*runtime_methods, called_function))
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
            call.runtime_methods = runtime_methods
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
        inline_function = called_function
        if inline_function is None and isinstance(func.obj, Class):
            constructor = func.obj.find_attrs("__init__")
            if isinstance(constructor, Function) and constructor.inline_decorator:
                inline_function = constructor
        if inline_function is not None:
            dependency_objects = self.inline_dependencies(inline_function, node)
        value_obj = return_type
        if isinstance(return_type, Class):
            value_obj = return_type("__call_result__", self.scope, self.func)
        dictionary_keys = None
        if isinstance(call_target, Class) and called_function is not None:
            dictionary_keys = self.prepare_dictionary_call(
                call_target,
                called_function,
                args,
                keywords,
            )
        generated_method_owner = None
        if isinstance(call_target, Class):
            generated_method_owner = call_target
        elif (
            is_super_method_call
            and called_function is not None
            and called_function.name == "__init__"
        ):
            generated_method_owner = called_function.cls
        method = generated_method(
            generated_method_owner,
            "__pyjs_constructor_method__",
        )
        return Call(
            return_type,
            value_obj=value_obj,
            func=func,
            args=args,
            keywords=keywords,
            dependency_objects=dependency_objects,
            runtime_methods=runtime_methods,
            generated_methods=(method,) if method is not None else (),
            dictionary_keys=dictionary_keys,
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
            concrete_types = [
                member
                for member in get_type_members(expected_type)
                if not contains_type_variable(member)
            ]
            expected_type = (
                UnionType(types=concrete_types).type if concrete_types else None
            )
        value = self.visit_contextual_expression(argument, expected_type)
        if pattern is not None:
            infer_type_variables(
                pattern,
                callable_value_type(value),
                type_bindings,
            )
        return value

    def visit_call_keyword(self, keyword, function, type_bindings):
        pattern = self.call_keyword_pattern(keyword, function)
        expected_type = (
            substitute_type_variables(pattern, type_bindings)
            if pattern is not None
            else None
        )
        value = self.visit_contextual_expression(keyword.value, expected_type)
        if pattern is not None:
            infer_type_variables(
                pattern,
                callable_value_type(value),
                type_bindings,
            )
        return ast.keyword(arg=keyword.arg, value=value)

    def validate_callable_call(self, node, signature, args, keywords):
        if keywords:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Calls through Callable annotations require positional arguments",
                help="Pass callable arguments positionally.",
            )
        if signature.parameter_types is None:
            return ()
        if len(args) != len(signature.parameter_types):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Callable expects {len(signature.parameter_types)} arguments, "
                f"got {len(args)}",
            )
        runtime_methods = []
        for index, (argument, expected_type) in enumerate(
            zip(args, signature.parameter_types, strict=True),
            start=1,
        ):
            if not is_call_argument_compatible(expected_type, argument):
                actual_type = analyzed_value_type(argument)
                self.fail(
                    node.args[index - 1],
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Callable argument {index} expects "
                    f"{expected_type.to_annotation_str()}, got "
                    f"{actual_type.to_annotation_str()}",
                    help=f"Pass a value compatible with {expected_type.to_annotation_str()}.",
                )
            runtime_methods.extend(
                self.argument_protocol_methods(expected_type, argument)
            )
            if uses_iterable_protocol(expected_type, argument):
                args[index - 1] = self.mapping_keys_iterable(argument)
        return tuple(dict.fromkeys(runtime_methods))

    def call_keyword_pattern(self, keyword, function):
        if function is None or keyword.arg is None:
            return None
        parameters = {
            parameter.arg: parameter
            for parameter in (
                *function.params[function.posonly_count :],
                *function.kwonlyargs,
            )
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
            default_type = analyzed_value_type(default)
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

    def record_native_attribute(self, name, value_type, *, declared=False):
        assert self.func.cls is not None
        attribute = value_type(name, self.func.cls.scope, self.func.cls._self)
        attribute.has_declared_type = declared
        self.func.cls._self.add(attribute)
        return attribute

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
            existing = self.func.cls._self.find_attrs(target.attr)
            if (
                annotation is None
                and isinstance(existing, Instance)
                and existing.has_declared_type
            ):
                continue
            try:
                value_type = self.analyze_assignment_value(
                    value, annotation
                ).storage_type
            except DependencyError:
                raise
            except (CompilationError, NameError):
                if annotation is not None:
                    raise
                continue
            assert value_type is not None
            self.record_native_attribute(
                target.attr,
                value_type,
                declared=annotation is not None,
            )

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if self.func.is_async and self.func.name == "__init__":
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "constructors cannot be async",
                help="Move asynchronous setup to a separate method.",
            )
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
        self.func.posonly_count = 0
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
                self.fail(
                    node.returns,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "Self return annotations are only valid on methods",
                    help="Return a concrete type or move this function onto a class.",
                )
            self.func.returns_self = True
            declared_return_type = self.func.cls
        elif node.returns is None:
            declared_return_type = None
        elif isinstance(node.returns, ast.Constant) and node.returns.value is None:
            declared_return_type = get_none_type()
        else:
            declared_return_type = self.visit_type_annotation(node.returns).obj
        if isinstance(declared_return_type, GenericClass):
            self.fail(
                node.returns,
                DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                f"Return type {declared_return_type.name!r} requires type arguments",
                help=(
                    f"Use {declared_return_type.name}[...] to describe the returned "
                    "values."
                ),
            )
        assert declared_return_type is None or isinstance(
            declared_return_type, (Class, UnionType)
        )
        self.func.declared_return_type = declared_return_type
        self.func.inferred_return_type = None
        self.func.return_type = None

        pos_params = [*node.args.posonlyargs, *node.args.args]
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

        positional_only = {parameter.arg for parameter in node.args.posonlyargs}
        self.func.posonly_count = sum(
            parameter.arg in positional_only for parameter in self.func.params
        )

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
                iterator = BUILTINS.search("Iterator")
                assert isinstance(iterator, GenericClass)
                final_return_type = iterator(
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
            actual_type = analyzed_value_type(value).to_annotation_str()
            self.fail(
                node.value,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Cannot await value of type {actual_type}",
                help="Await an Awaitable value, usually by calling an async function.",
            )
        awaited_type = awaitable_type.generic_types["T"]
        value_obj = awaited_type
        if isinstance(awaited_type, Class):
            value_obj = awaited_type("__await_result__", self.scope, self.func)
        return Await(
            awaited_type,
            value_obj=value_obj,
            value=value,
        )

    def fail_invalid_type_annotation(self, node):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            f"{ast.unparse(node)!r} is not a supported type annotation",
            help="Use a class, union, or supported generic type annotation.",
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
            if not isinstance(value.obj, GenericClass):
                value_name = ast.unparse(node.value)
                self.fail(
                    node.value,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    f"Type {value_name!r} does not accept type arguments",
                    help=f"Use {value_name!r} without square brackets.",
                )
            if isinstance(node.slice, ast.Tuple):
                elements = node.slice.elts
                if (
                    isinstance(value.obj, GenericClass)
                    and value.obj.name == "tuple"
                    and elements
                    and isinstance(elements[-1], ast.Constant)
                    and elements[-1].value is Ellipsis
                ):
                    elements = elements[:-1]
                item_types = [
                    self.visit_type_annotation(elt).obj for elt in elements
                ]
            elif isinstance(
                node.slice,
                (ast.Name, ast.Attribute, ast.BinOp, ast.Subscript, ast.Constant),
            ):
                item_types = [self.visit_type_annotation(node.slice).obj]
            else:
                self.fail_invalid_type_annotation(node.slice)
            expected_count = len(value.obj.generic_params)
            if value.obj.name != "tuple" and len(item_types) != expected_count:
                argument = "argument" if expected_count == 1 else "arguments"
                self.fail(
                    node.slice,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{value.obj.name} expects {expected_count} type {argument}, "
                    f"got {len(item_types)}",
                    help=(
                        f"Parameterize {value.obj.name} with "
                        f"{expected_count} type {argument}."
                    ),
                )
            return Name(value.obj(*item_types))  # generic class -> concrete class
        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, ast.BitOr):
                self.fail_invalid_type_annotation(node)
            left = self.visit_type_annotation(node.left).obj
            right = self.visit_type_annotation(node.right).obj
            return BinOp(
                UnionType(types=(left, right)).type,
                left=node.left,
                op=node.op,
                right=node.right,
            )
        elif isinstance(node, ast.Constant) and node.value is None:
            return self.visit(node)
        elif isinstance(node, ast.Attribute):
            alias_name = typing_alias_name(node, self.scope)
            if alias_name in TYPING_TYPE_ALIASES:
                return Name(BUILTINS.search(TYPING_TYPE_ALIASES[alias_name]))
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "Qualified type annotations are not supported",
                help=f"Import {node.attr!r} directly and use it as the annotation.",
            )
        else:
            alias_name = typing_alias_name(node, self.scope)
            if alias_name in TYPING_TYPE_ALIASES:
                return Name(BUILTINS.search(TYPING_TYPE_ALIASES[alias_name]))
            if not isinstance(node, ast.Name):
                self.fail_invalid_type_annotation(node)
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
            annotation = self.visit(node)
            if not isinstance(annotation.obj, (Class, GenericClass, UnionType)):
                self.fail_invalid_type_annotation(node)
            return annotation

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

    def visit_NamedExpr(self, node: ast.NamedExpr):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "assignment expressions are not supported",
            help="Assign the value in a separate statement before using it.",
        )

    def visit_Import(self, node: ast.Import):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "function-local imports are not supported",
            help="Move the import to module scope.",
        )

    def visit_ImportFrom(self, node: ast.ImportFrom):
        self.visit_Import(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "function-local class definitions are not supported",
            help="Move the class to module scope and decorate it with @js.",
        )

    def visit_Global(self, node: ast.Global):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "global declarations are not supported",
            help="Pass the value explicitly or store it on a client-side object.",
        )

    def visit_Nonlocal(self, node: ast.Nonlocal):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "nonlocal declarations are not supported",
            help="Pass the value explicitly or store it on a client-side object.",
        )

    def visit_AsyncFor(self, node: ast.AsyncFor):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "async for statements are not supported",
            help="Await values explicitly inside a supported loop.",
        )

    def visit_AsyncWith(self, node: ast.AsyncWith):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "async with statements are not supported",
            help="Call and await the resource lifecycle explicitly.",
        )

    def visit_TryStar(self, node: ast.TryStar):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "except* handlers are not supported",
            help="Use ordinary try/except with supported exception types.",
        )

    def visit_TypeAlias(self, node: ast.TypeAlias):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "type statements inside client functions are not supported",
            help="Define the type alias at module scope.",
        )

    def visit_Match(self, node: ast.Match):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "match statements are not supported",
            help="Use typed if/elif branches instead.",
        )

    def visit_TemplateStr(self, node: ast.TemplateStr):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "template string literals are not supported",
            help="Use an f-string when interpolation is sufficient.",
        )

    def visit_JoinedStr(self, node: ast.JoinedStr):
        return JoinedStr(
            BUILTINS.search("str"),
            values=[self.visit(part) for part in node.values],
        )

    def visit_FormattedValue(self, node: ast.FormattedValue):
        value = self.visit(node.value)
        conversion = node.conversion
        if node.format_spec is not None:
            spec = constant_format_spec(node.format_spec)
            if spec is None:
                self.fail(
                    node.format_spec,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "dynamic f-string format specifications are not supported",
                    help="Use a constant d, f, or % format specification.",
                )
            match = FORMAT_SPEC.fullmatch(spec)
            if match is None:
                self.fail(
                    node.format_spec,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    f"f-string format specification {spec!r} is not supported",
                    help=(
                        "Use d, f, or % with optional zero padding, width, "
                        "and precision."
                    ),
                )
            if (
                match.group("type") == "d"
                and match.group("precision") is not None
            ):
                self.fail(
                    node.format_spec,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "precision is not allowed with integer f-string formatting",
                    help="Remove the precision from the d format specification.",
                )
            if conversion != -1:
                self.fail(
                    node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "f-string conversions cannot be combined with numeric formatting",
                    help="Apply !s or !r without a numeric format specification.",
                )
            value_type = analyzed_value_type(value)
            allowed = {"bool", "int"}
            if match.group("type") != "d":
                allowed.add("float")
            if any(member.name not in allowed for member in get_type_members(value_type)):
                self.fail(
                    node.value,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Format code {match.group('type')!r} does not support "
                    f"{value_type.to_annotation_str()}",
                    help="Format a compatible numeric value.",
                )
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
    COMPARE_OP_SYMBOLS = {
        ast.Is: "is",
        ast.IsNot: "is not",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.In: "in",
        ast.NotIn: "not in",
    }
    EMPTY_COLLECTION_NAMES = {
        ast.Dict: "dict",
        ast.List: "list",
        ast.Tuple: "tuple",
    }

    def visit_comparison_value(self, node, previous=None):
        collection_name = self.EMPTY_COLLECTION_NAMES.get(type(node))
        if collection_name is None:
            return self.visit(node)
        items = node.keys if isinstance(node, ast.Dict) else node.elts
        if items:
            return self.visit(node)
        expected_type = (
            contextual_collection_type(analyzed_value_type(previous), collection_name)
            if previous is not None
            else None
        )
        if expected_type is None:
            generic = BUILTINS.search(collection_name)
            object_type = BUILTINS.search("object")
            assert isinstance(generic, GenericClass)
            assert isinstance(object_type, Class)
            expected_type = (
                generic(object_type, object_type)
                if collection_name == "dict"
                else generic(object_type)
            )
        return self.visit_contextual_expression(node, expected_type)

    def visit_Compare(self, node: ast.Compare):
        assert len(node.ops) == len(node.comparators)
        operands = []
        for source in (node.left, *node.comparators):
            operands.append(
                self.visit_comparison_value(
                    source,
                    operands[-1] if operands else None,
                )
            )
        if len(node.ops) > 1:
            temporaries = []
            for index, operand in enumerate(operands):
                value_type = analyzed_value_type(operand)
                temporary = value_type(
                    f"$compare{index}",
                    self.scope,
                    self.func,
                )
                temporaries.append(Name(temporary, ctx=ast.Load()))
            comparisons = [
                self.analyze_comparison(
                    node,
                    temporaries[index],
                    operator,
                    temporaries[index + 1],
                )
                for index, operator in enumerate(node.ops)
            ]
            bool_type = BUILTINS.search("bool")
            assert isinstance(bool_type, Class)
            return ChainedCompare(
                bool_type,
                operands=operands,
                comparisons=comparisons,
                temporaries=temporaries,
                lineno=node.lineno,
            )

        left, right = operands
        return self.analyze_comparison(node, left, node.ops[0], right)

    def analyze_comparison(self, node, left, operator, right):
        # TODO: needs cleanup and refactoring
        left_type = analyzed_value_type(left)
        right_type = analyzed_value_type(right)
        comparison_method = (
            "__ne__" if isinstance(operator, ast.NotEq) else "__eq__"
        )
        if isinstance(operator, (ast.Eq, ast.NotEq)) and (
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
                operator,
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
        if isinstance(operator, (ast.In, ast.NotIn)):
            left_self, right_self = right_self, left_self
            left, right = right, left

        left_op_method, right_op_method = self.COMPARE_OPS[type(operator)]
        negate_dataclass_equality = isinstance(operator, ast.NotEq) and getattr(
            left_self.cls, "is_dataclass", False
        )
        if negate_dataclass_equality:
            left_op_method = right_op_method = "__eq__"

        use_typed_dispatch = not (
            isinstance(left_type, UnionType)
            or isinstance(right_type, UnionType)
            or isinstance(operator, (ast.Is, ast.IsNot, ast.In, ast.NotIn))
        )
        func = None
        if use_typed_dispatch:
            try:
                func, reverse = self.resolve_binary_operator(
                    left_type,
                    right_type,
                    left_op_method,
                    right_op_method,
                    reject_object=isinstance(operator, (ast.Eq, ast.NotEq)),
                )
            except NameError:
                pass
            if func is not None and reverse:
                left, right = right, left
        else:
            try:
                func = left_self.find(left_op_method)
                assert isinstance(func, Function)
                if func.cls.name == "object":
                    # Python tries reflected equality before object identity.
                    raise NameError
            except NameError:
                if not isinstance(operator, (ast.In, ast.NotIn)):
                    try:
                        func = right_self.find(right_op_method)
                    except NameError:
                        pass
                    else:
                        if func.cls.name != "object":
                            left, right = right, left
        if func is None:
            self.fail_unsupported_operator(
                node,
                self.COMPARE_OP_SYMBOLS[type(operator)],
                left_type,
                right_type,
                left_op_method,
            )
        if func is not self.func and not func.is_analyzed:
            raise DependencyError(func)
        return_type = func.return_type or func.declared_return_type
        assert isinstance(return_type, (Class, UnionType))
        function = Attribute(func, value=left, attr=func.name)
        comparison = self.call_node(
            node,
            return_type,
            func=function,
            args=[right],
            keywords=[],
            operator=operator,
            dependency_objects=self.inline_dependencies(func, node),
        )
        comparison.runtime_methods = self.runtime_contract_methods(
            function,
            func,
            [right],
        )
        if isinstance(operator, ast.NotIn) or negate_dataclass_equality:
            return UnaryOp(return_type, op=ast.Not(), operand=comparison)
        return comparison

    def dynamic_union_equality(
        self,
        node,
        left,
        right,
        left_type,
        right_type,
        operator,
    ):
        is_not_equal = isinstance(operator, ast.NotEq)
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
            operator=operator,
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
        ast.LShift: ("__lshift__", "__rlshift__"),
        ast.RShift: ("__rshift__", "__rrshift__"),
    }
    BIN_OP_SYMBOLS = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.FloorDiv: "//",
        ast.Mod: "%",
        ast.Pow: "**",
        ast.BitAnd: "&",
        ast.BitOr: "|",
        ast.BitXor: "^",
        ast.LShift: "<<",
        ast.RShift: ">>",
    }

    def fail_unsupported_operator(
        self,
        node,
        symbol,
        left_type,
        right_type,
        method_name,
    ):
        self.fail(
            node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"Operator {symbol!r} is not supported for "
            f"{left_type.to_annotation_str()} and "
            f"{right_type.to_annotation_str()}",
            help=(
                "Use operands with compatible types or define the "
                f"corresponding {method_name}() method."
            ),
        )

    def reject_unsafe_constant_integer(self, node: ast.expr):
        value = constant_integer_value(node)
        if value is None or abs(value) <= JS_MAX_SAFE_INTEGER:
            return
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "constant integer expression exceeds JavaScript's safe integer range",
            help=(
                "Keep statically known integers between "
                f"{-JS_MAX_SAFE_INTEGER} and {JS_MAX_SAFE_INTEGER}."
            ),
        )

    def resolve_binary_operator(
        self,
        left_type,
        right_type,
        left_method,
        right_method,
        *,
        reject_object=False,
    ):
        left_self = left_type._self
        right_self = right_type._self
        right_override = right_self.cls.find_attrs(
            right_method,
            search_bases=False,
        )
        right_is_subclass = not same_analyzer_type(
            right_type,
            left_type,
        ) and is_subclass(right_type, left_type)
        method = None
        reverse = False
        if isinstance(right_override, Function) and right_is_subclass:
            if not right_override.signature_analyzed:
                raise DependencyError(right_override)
            if is_return_type_compatible(
                right_override.params[0].annotation.obj,
                left_type,
            ):
                method = right_override
                reverse = True
        if method is None:
            try:
                method = left_self.find(left_method)
                assert isinstance(method, Function)
                if not method.signature_analyzed:
                    raise DependencyError(method)
                if reject_object and method.cls.name == "object":
                    raise NameError
                if not is_return_type_compatible(
                    method.params[0].annotation.obj,
                    right_type,
                ):
                    raise NameError
                reverse = False
            except NameError:
                method = right_self.find(right_method)
                assert isinstance(method, Function)
                if not method.signature_analyzed:
                    raise DependencyError(method) from None
                if not is_return_type_compatible(
                    method.params[0].annotation.obj,
                    left_type,
                ):
                    raise NameError from None
                reverse = not reject_object or method.cls.name != "object"
        if not method.is_analyzed:
            raise DependencyError(method)
        return method, reverse

    def visit_union_binop(self, node, left, right, left_type, right_type):
        left_method, right_method = self.BIN_OPS[type(node.op)]
        symbol = self.BIN_OP_SYMBOLS[type(node.op)]
        try:
            resolutions = [
                self.resolve_binary_operator(
                    left_member,
                    right_member,
                    left_method,
                    right_method,
                )
                for left_member in get_type_members(left_type)
                for right_member in get_type_members(right_type)
            ]
        except NameError:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Operator {symbol!r} is not supported for every combination "
                f"of {left_type.to_annotation_str()} and "
                f"{right_type.to_annotation_str()}",
                help="Narrow either operand before applying the operator.",
            )

        first_method, first_reverse = resolutions[0]
        first_inline = first_method.decoration("__js_inline__")
        first_dependencies = first_method.decoration("__js_inline_dependencies__")
        incompatible = any(
            reverse != first_reverse
            or method.decoration("__js_inline__") is not first_inline
            or method.is_async != first_method.is_async
            or method.decoration("__js_inline_dependencies__") != first_dependencies
            for method, reverse in resolutions[1:]
        )
        if incompatible:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Operator {symbol!r} has incompatible client lowering across "
                f"{left_type.to_annotation_str()} and "
                f"{right_type.to_annotation_str()}",
                help="Narrow either operand before applying the operator.",
            )

        return_type = None
        for method, _ in resolutions:
            return_type = merge_return_types(return_type, method.return_type)
        assert isinstance(return_type, (Class, UnionType))
        receiver, argument = (right, left) if first_reverse else (left, right)
        methods = tuple(dict.fromkeys(method for method, _ in resolutions))
        function = Attribute(
            first_method,
            value=receiver,
            attr=first_method.name,
            union_functions=methods,
            union_return_type=return_type,
        )
        return self.call_node(
            node,
            return_type,
            func=function,
            args=[argument],
            keywords=[],
            operator=node.op,
            reverse=first_reverse,
            dependency_objects=self.inline_dependencies(first_method, node),
        )

    def visit_BinOp(self, node: ast.BinOp):
        self.reject_unsafe_constant_integer(node)
        left = self.visit(node.left)
        right = self.visit(node.right)
        left_type = analyzed_value_type(left)
        right_type = analyzed_value_type(right)
        if isinstance(left_type, UnionType) or isinstance(right_type, UnionType):
            return self.visit_union_binop(
                node,
                left,
                right,
                left_type,
                right_type,
            )
        left_op_method, right_op_method = self.BIN_OPS[type(node.op)]
        try:
            func, reverse = self.resolve_binary_operator(
                left_type,
                right_type,
                left_op_method,
                right_op_method,
            )
        except NameError:
            self.fail_unsupported_operator(
                node,
                self.BIN_OP_SYMBOLS[type(node.op)],
                left_type,
                right_type,
                left_op_method,
            )
        if reverse:
            left, right = right, left
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
    UNARY_SYMBOLS = {ast.UAdd: "+", ast.USub: "-", ast.Invert: "~", ast.Not: "not"}

    def visit_UnaryOp(self, node: ast.UnaryOp):
        self.reject_unsafe_constant_integer(node)
        operand = self.visit(node.operand)
        op_method = self.UNARY_OPS[type(node.op)]
        operand_obj = analyzed_value_object(operand)
        operand_type = analyzed_value_type(operand)
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
        try:
            func = operand_obj.find(op_method)
        except NameError:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Unary operator {self.UNARY_SYMBOLS[type(node.op)]!r} is not supported "
                f"for {operand_type.to_annotation_str()}",
                help=f"Define {op_method}(self) for this client-side type.",
            )
        if not func.is_analyzed:
            raise DependencyError(func)
        call = Call(
            func.return_type,
            func=Attribute(func, value=operand, attr=func.name),
            args=[],
            keywords=[],
            dependency_objects=self.inline_dependencies(func, node),
        )
        if isinstance(node.op, ast.Not):
            assert func.return_type.name == "bool"
            return UnaryOp(func.return_type, op=node.op, operand=call)
        return call

    def visit_BoolOp(self, node: ast.BoolOp):
        values = []
        visitor = self
        evaluate_next_when_true = isinstance(node.op, ast.And)
        for value in node.values:
            values.append(visitor.visit_comparison_value(value))
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
        result_type = value_types.type

        native_truth_types = {"bool", "int", "NoneType", "str"}
        if all(
            {
                member.name
                for member in get_type_members(analyzed_value_type(value))
            }
            <= native_truth_types
            for value in values[:-1]
        ):
            return BoolOp(result_type, op=node.op, values=values)

        result = values[-1]
        for index in range(len(values) - 2, -1, -1):
            value = values[index]
            value_type = analyzed_value_type(value)
            temporary_obj = value_type(
                f"$boolop{index}",
                self.scope,
                self.func,
            )
            temporary = Name(temporary_obj, ctx=ast.Load())
            test = self.truth_test(node.values[index], temporary)
            if isinstance(node.op, ast.And):
                body, orelse = result, temporary
            else:
                body, orelse = temporary, result
            conditional = IfExp(
                result_type,
                result_type,
                test=test,
                body=body,
                orelse=orelse,
            )
            result = EvaluateOnce(
                result_type,
                value,
                conditional,
                temporary.id,
                lineno=node.lineno,
            )
        return result

    # endregion

    # region constants

    def visit_Constant(self, node: ast.Constant):
        unsupported = {
            bytes: (
                "bytes literals are not supported",
                "Use str for text or a supported typed-array API for binary data.",
            ),
            complex: (
                "complex number literals are not supported",
                "Represent the real and imaginary components explicitly.",
            ),
            type(Ellipsis): (
                "ellipsis values are not supported",
                "Use None or an explicit client-side sentinel value.",
            ),
        }
        if diagnostic := unsupported.get(type(node.value)):
            message, help_text = diagnostic
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                message,
                help=help_text,
            )
        self.reject_unsafe_constant_integer(node)
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
        item_types = []
        contextual_key_type = None
        contextual_value_type = None
        if (
            contextual_type is not None
            and not isinstance(contextual_type, TypedDictClass)
        ):
            contextual_key_type = contextual_type.generic_types["K"]
            contextual_value_type = contextual_type.generic_types["V"]
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                mapping = self.visit_contextual_expression(value, contextual_type)
                mapping_type = analyzed_value_object(mapping)
                if isinstance(mapping_type, Instance):
                    mapping_type = mapping_type.cls
                is_generic_dict = (
                    isinstance(mapping_type, GenericClass)
                    and mapping_type.name == "dict"
                )
                is_concrete_dict = (
                    isinstance(mapping_type, Class)
                    and mapping_type.generic_name == "dict"
                )
                if not (is_generic_dict or is_concrete_dict):
                    self.fail(
                        value,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        "dictionary unpacking requires a dict value",
                        help=(
                            "Unpack a dict with known key and value types or "
                            "construct the result explicitly."
                        ),
                )
                keys.append(None)
                values.append(mapping)
                if isinstance(mapping_type, Class):
                    key_type = mapping_type.generic_types["K"]
                    value_type = mapping_type.generic_types["V"]
                    K.add(key_type)
                    V.add(value_type)
                    item_types.append((key_type, value_type))
                continue
            analyzed_key = self.visit_contextual_expression(
                key,
                contextual_key_type,
            )
            analyzed_value = self.visit_contextual_expression(
                value,
                contextual_value_type,
            )
            key_type = analyzed_value_type(analyzed_key)
            value_type = analyzed_value_type(analyzed_value)
            keys.append(analyzed_key)
            values.append(analyzed_value)
            K.add(key_type)
            V.add(value_type)
            item_types.append((key_type, value_type))
        if (
            contextual_key_type is not None
            and all(
                is_return_type_compatible(contextual_key_type, key_type)
                and is_return_type_compatible(
                    contextual_value_type,
                    value_type,
                )
                for key_type, value_type in item_types
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
        result = Call(
            keys.return_type,
            func=Attribute(keys, value=iterable, attr="keys"),
            args=[],
            keywords=[],
        )
        result.mapping_source_type = iterable_type
        return result

    def require_iterable(self, node, iterable):
        value_type = analyzed_value_type(iterable)
        protocol = iterable_protocol(value_type)
        if protocol is not None:
            return protocol
        self.fail(
            node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"Type {value_type.to_annotation_str()!r} is not iterable",
            help=(
                "Define a client-side __iter__(self) -> Iterator[T] method "
                "or iterate over a supported collection."
            ),
        )

    def visit_While(self, node: ast.While):
        test = self.visit(node.test)
        body = self.visit_body(node.body)
        orelse = self.visit_body(node.orelse) if node.orelse else node.orelse
        return ast.While(
            test=test,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )

    def visit_For(self, node: ast.For):
        node_iter = self.mapping_keys_iterable(self.visit(node.iter))
        protocol = self.require_iterable(node.iter, node_iter)
        target = self.bind_loop_target(node.target, protocol.item_type)

        body = self.visit_body(node.body)
        orelse = self.visit_body(node.orelse) if node.orelse else node.orelse
        result = ast.For(
            target=target,
            iter=node_iter,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )
        result.runtime_methods = protocol.methods
        return result

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
            handler_visitor.in_exception_handler = True
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
                    generator_node.target,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "asynchronous comprehensions are not supported",
                    help=(
                        "Use an explicit async loop before building the collection."
                    ),
                )
            iter_node = visitor.mapping_keys_iterable(
                visitor.visit(generator_node.iter)
            )
            protocol = visitor.require_iterable(generator_node.iter, iter_node)
            self.bind_comprehension_target(
                visitor,
                generator_node.target,
                protocol.item_type,
            )
            generator = ast.comprehension(
                target=visitor.visit(generator_node.target),
                iter=iter_node,
                ifs=[visitor.visit(condition) for condition in generator_node.ifs],
                is_async=0,
            )
            generator.runtime_methods = protocol.methods
            generators.append(generator)
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
        contextual_type = contextual_collection_type(
            self.contextual_types.get(node),
            "dict",
        )
        if isinstance(contextual_type, TypedDictClass):
            contextual_type = None
        expected_key_type = (
            contextual_type.generic_types["K"]
            if contextual_type is not None
            else None
        )
        expected_value_type = (
            contextual_type.generic_types["V"]
            if contextual_type is not None
            else None
        )
        key = visitor.visit_contextual_expression(node.key, expected_key_type)
        value = visitor.visit_contextual_expression(
            node.value,
            expected_value_type,
        )
        key_type = analyzed_value_type(key)
        value_type = analyzed_value_type(value)
        dict_type = BUILTINS.search("dict")(key_type, value_type)
        if (
            contextual_type is not None
            and is_return_type_compatible(expected_key_type, key_type)
            and is_return_type_compatible(expected_value_type, value_type)
        ):
            dict_type = contextual_type
        return DictComp(
            dict_type,
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
        iterator = BUILTINS.search("Iterator")
        assert isinstance(iterator, GenericClass)
        return GeneratorExp(
            iterator(analyzed_value_type(elt)),
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
            try:
                func = test_type.find("__len__")
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
        body_visitor = self.branch_visitor(node.test, True)
        orelse_visitor = self.branch_visitor(node.test, False)
        body = body_visitor.visit_body(node.body)
        orelse = orelse_visitor.visit_body(node.orelse)
        self.merge_branch_declarations(body_visitor, orelse_visitor)
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
        result_type = merge_conditional_types(body_type, orelse_type)
        value_obj = result_type(
            "__conditional_result__",
            self.scope,
            self.func,
        )
        return IfExp(
            result_type,
            value_obj=value_obj,
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
        if node.exc is None and not self.in_exception_handler:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "bare raise requires an active exception handler",
                help="Raise an explicit exception in this context.",
            )
        if node.cause is not None:
            self.fail(
                node.cause,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "exception chaining with 'raise ... from ...' is not supported",
                help="Raise the exception without an explicit cause.",
            )
        exc = self.visit(node.exc) if node.exc is not None else None
        if exc is not None:
            exception_type = BUILTINS.search("Exception")
            assert isinstance(exception_type, Class)
            value_type = analyzed_value_type(exc)
            if not all(
                isinstance(member, Class) and is_subclass(member, exception_type)
                for member in get_type_members(value_type)
            ):
                self.fail(
                    node.exc,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "raise requires an exception instance",
                    help="Raise Exception or an instance of one of its subclasses.",
                )
        return ast.Raise(exc=exc, cause=None)

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

    def mark_virtual_visited(self, value: Function | Instance) -> None:
        value.virtual_visited.add(self.entry_point)
        self.entry_point.compilation_objects.add(value)

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

    def enter_overrides(self, func: Function, cls: Class) -> bool:
        visited = False
        for subclass in cls.subclasses:
            override = self.property_override(func, subclass)
            if isinstance(override, Function):
                inherited = self.enter_overrides(override, subclass)
                if self.entry_point in subclass.visited or inherited:
                    self.enter_virtual(override)
                    visited = True
            elif self.enter_overrides(func, subclass):
                visited = True
            elif self.entry_point in subclass.visited:
                visited = True
        return visited

    def enter_virtual_field(self, field: Instance):
        owner = field_owner(field)
        assert owner is not None
        self.enter_field(field)
        if self.entry_point in field.virtual_visited:
            return
        self.mark_virtual_visited(field)
        self.enter_field_overrides(field, owner)

    def enter_field(self, field: Instance):
        if self.entry_point in field.visited:
            return
        self.mark_visited(field)
        if field.static_value is not None:
            self.visit(field.static_value)

    def enter_field_overrides(self, field: Instance, cls: Class):
        for subclass in cls.subclasses:
            if self.entry_point not in subclass.visited:
                continue
            override = subclass.find_attrs(field.name, search_bases=False)
            if isinstance(override, Instance) and override.static_value is not None:
                self.enter_virtual_field(override)
            else:
                self.enter_field_overrides(field, subclass)

    @staticmethod
    def inherited_field_declaration(
        cls: Class,
        name: str,
    ) -> tuple[Class, Class | UnionType] | None:
        parent = cls.super
        while parent is not None:
            declarations = getattr(parent, "field_declarations", {})
            if declared_type := declarations.get(name):
                return parent, declared_type
            parent = parent.super
        return None

    @staticmethod
    def class_display_name(cls: Class) -> str:
        return cls.to_annotation_str() if cls.generic_types else cls.name

    def field_declaration_label(
        self,
        cls: Class,
        name: str,
        declared_type: Class | UnionType,
    ) -> tuple[Label, ...]:
        node = cls.field_declaration_nodes.get(name)
        fragment = cls.container.source_fragment
        if node is None or fragment is None:
            return ()
        return (
            Label(
                fragment.span(node),
                f"{self.class_display_name(cls)}.{name} is declared as "
                f"{declared_type.to_annotation_str()} here",
            ),
        )

    def validate_class_fields(self, cls: Class) -> None:
        fragment = cls.container.source_fragment
        if fragment is None or not hasattr(cls, "field_declarations"):
            return
        names = cls.field_declarations.keys() | cls.field_value_nodes.keys()
        for name in names:
            field_name = f"{self.class_display_name(cls)}.{name}"
            declared_type = cls.field_declarations.get(name)
            inherited = self.inherited_field_declaration(cls, name)
            if declared_type is not None and inherited is not None:
                parent, parent_type = inherited
                if not is_return_type_compatible(parent_type, declared_type):
                    node = cls.field_declaration_nodes[name]
                    actual = declared_type.to_annotation_str()
                    expected = parent_type.to_annotation_str()
                    cls.container.context.error(
                        fragment,
                        node,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Cannot override inherited field {field_name!r} "
                        f"of type {expected} with {actual}",
                        secondary=self.field_declaration_label(
                            parent,
                            name,
                            parent_type,
                        ),
                        help=(
                            f"Use a type compatible with {expected} or change "
                            "the declaration of "
                            f"{self.class_display_name(parent)}.{name}."
                        ),
                    )

            field = cls.find_attrs(name, search_bases=False)
            if not (
                isinstance(field, Instance)
                and field.static_value is not None
                and name in cls.field_value_nodes
            ):
                continue
            expected_type = declared_type
            parent = None
            if expected_type is None and inherited is not None:
                parent, expected_type = inherited
            if expected_type is None or is_return_type_compatible(
                expected_type,
                field.cls,
            ):
                continue
            actual = field.cls.to_annotation_str()
            expected = expected_type.to_annotation_str()
            if parent is None:
                message = (
                    f"Cannot assign {actual} to class field "
                    f"{field_name!r} of type {expected}"
                )
                secondary = ()
                declaration_owner = cls
            else:
                message = (
                    f"Cannot assign {actual} to inherited field "
                    f"{field_name!r} of type {expected}"
                )
                secondary = self.field_declaration_label(
                    parent,
                    name,
                    expected_type,
                )
                declaration_owner = parent
            cls.container.context.error(
                fragment,
                cls.field_value_nodes[name],
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                message,
                secondary=secondary,
                help=(
                    f"Assign a value compatible with {expected} or change "
                    "the declaration of "
                    f"{self.class_display_name(declaration_owner)}.{name}."
                ),
            )

    def enter_class(self, cls: Class):
        if cls.super is not None:
            runtime_dependency = runtime_class_dependency(cls.super, cls.container)
            if runtime_dependency is not None:
                cls.runtime_super_dependency = runtime_dependency
                cls.runtime_super_alias = cls.container.register_inline_dependency(
                    runtime_dependency,
                    self.entry_point,
                )
                self.enter_class(runtime_dependency)
        while cls is not None:
            generic = cls.container.scope.names.get(cls.generic_name)
            if isinstance(generic, GenericClass):
                self.mark_visited(generic)
            if self.entry_point not in cls.visited:
                self.validate_class_fields(cls)
                self.mark_visited(cls)
                for dependency in sorted(
                    getattr(cls, "client_model_dependencies", ()),
                    key=lambda item: (item.container.name, item.name),
                ):
                    dependency.client_model_registry_required = True
                    if dependency.container is not cls.container:
                        cls.container.side_effect_dependencies.add(dependency)
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
                    if isinstance(attr, Instance):
                        if self.parent_field_is_virtual(attr):
                            self.enter_virtual_field(attr)
                        continue
                    if not isinstance(attr, Function):
                        continue
                    if has_keep_decorator(attr.py_obj) or self.parent_has_keep(
                        attr
                    ):
                        self.isolated_visit(attr)
                    elif self.parent_is_virtual(attr):
                        self.enter_virtual(attr)
                method_names = (
                    *getattr(cls.py_cls, "__pyjs_external_methods__", ()),
                    *getattr(cls.py_cls, "__pyjs_generated_methods__", ()),
                )
                for method_name in dict.fromkeys(method_names):
                    method = cls.find_attrs(method_name)
                    if isinstance(method, Function):
                        self.enter_virtual(method)
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

    def parent_field_is_virtual(self, field: Instance):
        if field.static_value is None or not isinstance(field.container, Class):
            return False
        parent = field.container.super
        while parent is not None:
            parent_field = parent.find_attrs(field.name, search_bases=False)
            if parent_field is None:
                parent_field = parent._self.attrs.get(field.name)
            if (
                isinstance(parent_field, Instance)
                and self.entry_point in parent_field.virtual_visited
            ):
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

    @staticmethod
    def is_virtual_field_reference(node):
        if not (
            isinstance(node, ast.Attribute)
            and isinstance(node.obj, Instance)
            and field_owner(node.obj) is not None
        ):
            return False
        receiver = node.value
        if isinstance(receiver, Name) and isinstance(receiver.obj, Class):
            return False
        if isinstance(receiver, Call) and isinstance(receiver.func.obj, Class):
            return False
        return True

    def isolated_visit(self, func: Function):
        assert isinstance(func, Function)
        if func.has_source_decorator:
            self.mark_visited(func)
            module = func.cls.container if func.is_method else func.container
            remote_operation = getattr(func.py_func, "__pyjs_operation__", None)
            if remote_operation is not None and not is_supported_client_result_type(
                func.return_type
            ):
                module.context.definition_error(
                    func.py_func,
                    DiagnosticCode.UNSUPPORTED_CLIENT_RESULT,
                    f"Operation {func.name!r} has unsupported client result type "
                    f"{func.return_type.to_annotation_str()!r}.",
                    help=(
                        "Return a supported primitive, Pydantic model, optional, "
                        "list, dictionary, tuple, set, or Page value."
                    ),
                )
            if (
                remote_operation is not None
                and not remote_operation.jsonapi
                and client_result_requires_decoding(func.return_type)
            ):
                decoder = func.cls.find("_decode_result")
                assert isinstance(decoder, Function)
                self.enter_virtual(decoder)
            for dependency_obj in client_model_types(func.return_type):
                if remote_operation is not None and not remote_operation.jsonapi:
                    dependency_obj.client_model_registry_required = True
                self.enter_class(dependency_obj)
                self.enter(dependency_obj.find("__init__"))
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
        if self.entry_point not in func.visited:
            if not func.is_analyzed:
                annotate_types(func)
            type(self)(func, self.entry_point).visit(func.node)

    def visit_FunctionDef(self, node: FunctionDef):
        self.mark_visited(node.obj)
        for arg in (*node.args.posonlyargs, *node.args.args):
            self.visit(arg)
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        for stmt in node.body:
            self.visit(stmt)

    def visit_With(self, node: ast.With):
        self.enter_virtual(node.enter_method)
        self.enter_virtual(node.exit_method)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        module = self.func.cls.container if self.func.is_method else self.func.container
        dependency = node.runtime_dependency
        node.runtime_alias = module.register_inline_dependency(
            dependency,
            self.entry_point,
        )
        self.enter_class(dependency)
        self.enter(dependency.find("__init__"))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: AsyncFunctionDef):
        self.visit_FunctionDef(node)

    def visit_For(self, node: ast.For):
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension):
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        self.generic_visit(node)

    def visit_Starred(self, node: Starred):
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, Name) and node.func.id == "tw":
            self.entry_point.tailwind_classes.update(
                set(node.args[0].value.split(" ")),
            )
        func = node.func.obj
        module = self.func.cls.container if self.func.is_method else self.func.container
        for name, dependency in getattr(node, "dependency_objects", {}).items():
            node.inline_dependencies[name] = module.register_inline_dependency(
                dependency,
                self.entry_point,
            )
            self.enter(dependency)
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        for method in node.generated_methods:
            self.enter(method)
        for method in node.generated_virtual_methods:
            self.enter_virtual(method)
        if node.dictionary_keys is not None:
            for argument in node.args:
                self.visit(argument)
            for keyword in node.keywords:
                self.visit(keyword.value)
            return
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
            if self.is_virtual_field_reference(node):
                self.enter_virtual_field(node.obj)
            else:
                field = node.obj
                if (
                    isinstance(node.value, Call)
                    and isinstance(node.value.func.obj, Class)
                ):
                    override = node.value.func.obj.find_attrs(
                        node.attr,
                        search_bases=False,
                    )
                    if isinstance(override, Instance):
                        field = override
                self.enter_field(field)
            if node.obj.member_dependency is not None:
                self.enter_class(node.obj.member_dependency)
                self.enter(node.obj.member_dependency.find("__init__"))
        self.generic_visit(node)

    def visit_RuntimeFunctionReference(self, node: RuntimeFunctionReference):
        module = self.func.cls.container if self.func.is_method else self.func.container
        node.alias = module.register_inline_dependency(
            node.runtime_dependency,
            self.entry_point,
        )
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
                        node.runtime_dependency,
                        self.entry_point,
                    )
                    self.enter_class(node.runtime_dependency)
                    self.enter(node.runtime_dependency.find("__init__"))
                else:
                    node.id = module.register_inline_dependency(
                        node.runtime_dependency,
                        self.entry_point,
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
                if node.obj.static_value is None:
                    self.enter_class(node.obj.cls)
                    self.enter(node.obj.cls.find("__init__"))
                else:
                    self.visit(node.obj.static_value)
            elif isinstance(node.obj, UnionType):
                for obj_type in node.obj.types:
                    self.enter_class(obj_type)
                    self.enter(obj_type.find("__init__"))
            else:
                self.mark_visited(node.obj)


class RenderGraphVisitor(CallGraphVisitor):
    """Discover server-render dependencies without retaining creation code."""

    def mark_visited(self, value: Object) -> None:
        self.entry_point.compilation_objects.add(value)

    def enter(self, func: Function):
        if self.entry_point in func.render_visited:
            return
        func.render_visited.add(self.entry_point)
        self.entry_point.compilation_objects.add(func)
        if has_inline_decorator(func.py_obj) or func.has_source_decorator:
            return
        type(self)(func, self.entry_point).visit(func.node)

    def enter_class(self, cls: Class):
        if getattr(cls.py_cls, "__pyjs_constructor_method__", None) != "_create":
            return
        client = CallGraphVisitor(self.func, self.entry_point)
        client.enter_class(cls)
        initialize = cls.find_attrs("initialize", search_bases=False)
        if isinstance(initialize, Function):
            client.enter(initialize)
        reference_method_name = getattr(
            cls.py_cls,
            "__pyjs_reference_method__",
            None,
        )
        if reference_method_name is not None:
            reference_method = cls.find(reference_method_name)
            client.enter(reference_method)
        init = cls.find("__init__")
        hydration = HydrationGraphVisitor(init, self.entry_point)
        hydration.visit(init.node)
        if hydration.has_bindings:
            init.hydrate_visited.add(self.entry_point)
            self.entry_point.compilation_objects.add(init)

    def visit_FunctionDef(self, node: FunctionDef):
        for arg in (*node.args.posonlyargs, *node.args.args):
            self.visit(arg)
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        for stmt in node.body:
            self.visit(stmt)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, Name) and node.func.id == "tw":
            self.entry_point.tailwind_classes.update(node.args[0].value.split(" "))
        func = node.func.obj
        if isinstance(func, Function):
            self.enter(func)
        elif isinstance(func, Class):
            self.enter_class(func)
            init = func.find("__init__")
            self.enter(init)
        for argument in node.args:
            self.visit(argument)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Attribute(self, node: ast.Attribute):
        self.generic_visit(node)

    def visit_Name(self, node: Name):
        if isinstance(getattr(node, "obj", None), Class):
            self.enter_class(node.obj)
            self.enter(node.obj.find("__init__"))


def hydration_ref_call(value: ast.expr) -> Call | None:
    """Return a ref call through compile-time-only type casts."""
    while isinstance(value, StaticCast):
        value = value.value
    if isinstance(value, Call) and getattr(value, "is_ref", False):
        return value
    return None


class HydrationGraphVisitor(ast.NodeVisitor):
    def __init__(self, func: Function, entry_point: Function):
        self.func = func
        self.entry_point = entry_point
        self.client = CallGraphVisitor(func, entry_point)
        self.elements = set()
        self.has_bindings = False

    def visit_Assign(self, node: ast.Assign):
        if hydration_ref_call(node.value) is None:
            return
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                self.elements.add(target.obj)
                self.has_bindings = True

    def visit_Expr(self, node: ast.Expr):
        if not isinstance(node.value, ast.Call):
            return
        func = node.value.func
        if not isinstance(func, Attribute):
            return
        if (
            func.attr == "__init__"
            and isinstance(func.value, Call)
            and isinstance(func.value.func, Name)
            and func.value.func.id == "super"
        ):
            parent = self.func.cls.super
            if parent is not None:
                init = parent.find("__init__")
                parent_hydration = type(self)(init, self.entry_point)
                parent_hydration.visit(init.node)
                if parent_hydration.has_bindings:
                    init.hydrate_visited.add(self.entry_point)
                    self.entry_point.compilation_objects.add(init)
            return
        if func.attr == "addEventListener":
            receiver = func.value
            while isinstance(receiver, ast.Attribute):
                receiver = receiver.value
            if (
                isinstance(receiver, Name)
                and receiver.id != "self"
                and receiver.id in self.func.scope.names
            ):
                module = (
                    self.func.cls.container
                    if self.func.is_method
                    else self.func.container
                )
                module.context.error(
                    self.func.source_fragment,
                    func.value,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "Hydrated event targets cannot be constructor-local values",
                    help=(
                        "Store the target as a ref() attribute on self before "
                        "registering the event listener."
                    ),
                )
        if func.value.obj in self.elements or func.attr == "addEventListener":
            self.has_bindings = True
            if func.attr == "addEventListener":
                self.client.visit(func.value)
            if isinstance(func.obj, Function):
                if self.client.is_virtual_method_reference(func):
                    self.client.enter_virtual(func.obj)
                else:
                    self.client.enter(func.obj)
            for argument in node.value.args:
                self.client.visit(argument)
            for keyword in node.value.keywords:
                self.client.visit(keyword.value)


def from_entry_point(
    entry_point: callable,
    extensions: tuple[CompilationExtension, ...] = (),
    additional_entry_points: tuple[callable, ...] = (),
    render_entry_points: tuple[callable, ...] = (),
    render_primary: bool = False,
):
    entry_point.__js__ = True
    for additional_entry_point in additional_entry_points:
        additional_entry_point.__js__ = True
    for render_entry_point in render_entry_points:
        render_entry_point.__js__ = True
    py_module = inspect.getmodule(entry_point)
    return analyze_module(
        py_module,
        entry_point,
        extensions=extensions,
        additional_entry_points=additional_entry_points,
        render_entry_points=render_entry_points,
        render_primary=render_primary,
    )


def _reachable_analyzer_objects_from(roots: Iterable[Object]) -> Iterator[Object]:
    pending = list(roots)
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


def _reachable_analyzer_objects(root: Object) -> Iterator[Object]:
    yield from _reachable_analyzer_objects_from((root,))


@dataclass
class _SharedAnalyzerState:
    type_dependencies: dict[Module, tuple[Class, ...]]
    concrete_classes: dict[GenericClass, set[tuple]]
    closed: bool = False

    @classmethod
    def capture(cls) -> _SharedAnalyzerState:
        values = tuple(_reachable_analyzer_objects(BUILTINS))
        state = cls(
            {
                value: tuple(value.type_dependencies)
                for value in values
                if isinstance(value, Module)
            },
            {
                value: set(value.concrete_classes)
                for value in values
                if isinstance(value, GenericClass)
            },
        )
        _SHARED_ANALYZER_STATES.append(state)
        return state

    def restore(self) -> None:
        for module, dependencies in self.type_dependencies.items():
            module.type_dependencies[:] = dependencies
        for generic, retained_keys in self.concrete_classes.items():
            for key in set(generic.concrete_classes) - retained_keys:
                del generic.concrete_classes[key]

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        while _SHARED_ANALYZER_STATES and _SHARED_ANALYZER_STATES[-1].closed:
            _SHARED_ANALYZER_STATES.pop().restore()


_SHARED_ANALYZER_STATES: list[_SharedAnalyzerState] = []


def release_compilation(entry_point: Function) -> None:
    roots = entry_point.compilation_entry_points or (entry_point,)
    for root in roots:
        for value in root.compilation_objects:
            value.visited.discard(root)
            if isinstance(value, (Function, Instance)):
                value.virtual_visited.discard(root)
            if isinstance(value, Function):
                value.hydrate_visited.discard(root)
                value.render_visited.discard(root)
        root.compilation_objects.clear()
        root.compilation_entry_points = ()
        root.runtime_dunder_dependencies.clear()
    if entry_point.compilation_cleanup is not None:
        entry_point.compilation_cleanup()
        entry_point.compilation_cleanup = None


def analyze_module(
    py_module,
    entry_point=None,
    extensions: tuple[CompilationExtension, ...] = (),
    additional_entry_points: tuple[callable, ...] = (),
    render_entry_points: tuple[callable, ...] = (),
    render_primary: bool = False,
):
    if entry_point is None:
        assert hasattr(py_module, "main"), (
            "No entry_point specified and no main() function found."
        )
        py_module.main.__js__ = True
        entry_point = py_module.main
    shared_state = _SharedAnalyzerState.capture()
    entry_point_function = None
    try:
        package = {}
        context = CompilationContext()
        module = Module(
            py_module,
            package,
            extensions=extensions,
            context=context,
        ).build()
        package[module.name] = module
        entry_points = (
            entry_point,
            *additional_entry_points,
            *render_entry_points,
        )
        entry_point_functions = [
            resolve_entry_point(module, py_func) for py_func in entry_points
        ]
        entry_point_function = entry_point_functions[0]
        assert isinstance(entry_point_function, Function)
        entry_point_function.compilation_entry_points = (entry_point_function,)
        entry_point_function.compilation_cleanup = shared_state.close
        prepared = set()
        while pending := [value for value in package.values() if value not in prepared]:
            for imported in pending:
                annotate_types(imported)
                analyze_static_initializers(imported)
                prepared.add(imported)
        if render_primary:
            entry_point_function.tailwind_classes = set()
            entry_point_function.compilation_objects = set()
            entry_point_function.runtime_dunder_dependencies = set()
            RenderGraphVisitor(
                entry_point_function,
                entry_point_function,
            ).enter(entry_point_function)
            tailwind_classes = entry_point_function.tailwind_classes
        else:
            entry_point_function, tailwind_classes = visit_entry_point(
                entry_point_functions[0]
            )
        compilation_entry_points = [entry_point_function]
        additional_end = 1 + len(additional_entry_points)
        for additional_function in entry_point_functions[1:additional_end]:
            additional_function, additional_tailwind_classes = visit_entry_point(
                additional_function,
            )
            additional_function.visited.discard(additional_function)
            compilation_entry_points.append(additional_function)
            tailwind_classes.update(additional_tailwind_classes)
        for render_function in entry_point_functions[additional_end:]:
            render_function.tailwind_classes = set()
            render_function.compilation_objects = set()
            render_function.runtime_dunder_dependencies = set()
            RenderGraphVisitor(render_function, render_function).enter(render_function)
            compilation_entry_points.append(render_function)
            tailwind_classes.update(render_function.tailwind_classes)
        entry_point_function.compilation_entry_points = tuple(compilation_entry_points)
        entry_point_function.visited.discard(entry_point_function)
        return entry_point_function, tailwind_classes
    except BaseException:
        if entry_point_function is None:
            shared_state.close()
        else:
            release_compilation(entry_point_function)
        raise


def resolve_entry_point(module: Module, py_func) -> Function:
    if inspect.getmodule(py_func) is module.py_module:
        entry_point_func = module.search(py_func.__name__)
    else:
        entry_point_func = resolve_imported(py_func, module)
    assert isinstance(entry_point_func, Function)
    return entry_point_func


def visit_entry_point(entry_point_func: Function):
    entry_point_func.tailwind_classes = set()
    entry_point_func.compilation_objects = set()
    entry_point_func.runtime_dunder_dependencies = set()
    CallGraphVisitor.start(entry_point_func)
    return entry_point_func, entry_point_func.tailwind_classes


def promote_atomic_class_reachability(entry_point: Function) -> None:
    """Keep every reached method dependency with its emitted class."""
    package = entry_point.container.container
    changed = True
    while changed:
        changed = False
        values = tuple(_reachable_analyzer_objects_from(package.values()))
        for value in values:
            if not isinstance(value, Class) or not value.visited:
                continue
            roots = tuple(value.visited)
            methods = [
                method
                for method in value.children
                if isinstance(method, Function) and method.visited
            ]
            for method in methods:
                for root in roots:
                    if root in method.visited:
                        continue
                    CallGraphVisitor(method, root).enter(method)
                    changed = True


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
        try:
            functions = tuple(dependencies.static_order())
        except CycleError as error:
            cycle = error.args[1]
            func = next(value for value in cycle if isinstance(value, Function))
            module = func.cls.container if func.is_method else func.container
            names = " -> ".join(
                value.name for value in cycle if isinstance(value, Function)
            )
            module.context.definition_error(
                func.py_func,
                DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                f"Types in dependency cycle {names} cannot be inferred",
                help=(
                    "Add explicit annotations to values shared by the functions "
                    "in the cycle."
                ),
            )


def analyze_static_initializers(module: Module) -> None:
    def module_initializer():
        pass

    initializers = [
        (module, name, module.scope.names[name], initializer)
        for name, initializer in module.static_initializers.items()
        if name in module.preserved_static_initializers
    ]
    for value in module.scope.names.values():
        classes = (
            tuple(value.concrete_classes.values())
            if isinstance(value, GenericClass)
            else (value,)
        )
        for cls in classes:
            if not isinstance(cls, Class) or cls.container is not module:
                continue
            initializers.extend(
                (cls, name, cls.find_attrs(name, search_bases=False), initializer)
                for name, initializer in getattr(
                    cls,
                    "static_initializers",
                    {},
                ).items()
            )

    for container, name, value, initializer in initializers:
        assert isinstance(value, Instance)
        context = Function(module_initializer, container)
        context.name = name
        context.source_fragment = module.source_fragment
        while True:
            try:
                analyzed = InferenceVisitor(context).analyze_assignment_value(
                    initializer,
                    value.cls.annotation,
                )
                value.static_value = ast.fix_missing_locations(analyzed.node)
                break
            except DependencyError as dependency:
                annotate_types(dependency.class_or_func)


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
