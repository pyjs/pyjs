import enum
import inspect
import math
import re
import typing
from collections.abc import Callable, Iterable, Iterator
from contextvars import ContextVar
from copy import copy
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from graphlib import CycleError, TopologicalSorter

from pyjs import python as python_builtins
from pyjs.decorators import is_empty_inline
from pyjs.numeric import (
    ArrayFormat,
    NumericFormat,
    array_format,
    float_literal,
    integer_literal,
    numeric_format,
    wrapped_integer_value,
)

from .diagnostics import (
    CompilationContext,
    CompilationError,
    DiagnosticCode,
    Label,
    describe_type,
)
from .generic_inference import (
    infer_representation_variables as infer_generic_representations,
)
from .generic_inference import (
    infer_type_variables as infer_generic_types,
)
from .generic_inference import (
    substitute_representation_variables,
)
from .iterable_protocol import (
    IterableProtocol,
    cursor_protocol_methods,
    expects_iterable,
    is_abstract_iterable,
    is_abstract_iterator,
    resolve_iterable_protocol,
)
from .libraries import PYJS_LIBRARY_MAPPINGS, LibraryMappings
from .objects import *
from .representation import (
    ValueRepresentation,
    apply_representation,
    array_representation,
    compound_representation,
    direct_representation,
    numeric_comparison_representations_compatible,
    tuple_representation,
)
from .representation import (
    annotation_representation as runtime_annotation_representation,
)
from .type_relations import (
    callable_member,
    contains_json_object_schema,
    contains_type_variable,
    contextual_collection_type,
    generated_method,
    get_type_members,
    inherited_sequence_slot,
    is_builtin_class,
    is_isinstance_match,
    is_return_type_compatible,
    is_strict_runtime_subclass,
    is_subclass,
    literal_member_for_value,
    merge_conditional_types,
    merge_return_types,
    structural_method_names,
    substitute_type_variables,
)
from .value_representation import (
    analyzed_array_format,
    analyzed_numeric_format,
    analyzed_representation,
    analyzed_value_object,
    common_array_format,
    common_numeric_format,
    inconsistent_numeric_formats,
    integer_numeric_formats,
    is_portable_float_format,
    merged_representation,
    mixed_array_formats,
    mixed_numeric_formats,
    narrowed_representation,
    numeric_format_matches_type,
    numeric_formats,
    operation_numeric_format,
    possible_numeric_formats,
    representation_for_member,
    representations_conflict,
    resolve_sum_numeric_format,
    same_erased_type,
    set_analyzed_representation,
)

TYPING_TYPE_ALIASES = {
    "Any": "object",
    "Dict": "dict",
    "List": "list",
    "Set": "set",
    "Tuple": "tuple",
    **GENERIC_TYPE_ALIASES,
}

MAX_FIXED_TUPLE_ITEMS = 256

FORMAT_SPEC = re.compile(
    r"(?P<zero>0)?(?P<width>\d+)?(?:\.(?P<precision>\d+))?"
    r"(?P<type>[deEf%])"
)


@dataclass(frozen=True)
class AnalysisEnvironment:
    """Semantic builtins and analysis policy for one compilation target."""

    name: str
    builtins: Module
    library_mappings: LibraryMappings
    inference_visitor: type[ast.NodeVisitor]
    analyze_all_definitions: bool = True
    defer_unselected_imports: bool = False
    definition_filter: Callable[[str, object, Module], bool] | None = None
    body_filter: Callable[[Function], bool] | None = None
    analysis_finalizer: Callable[[Function], None] | None = None


def js_lowering(function: Function | Class):
    implementation = own_js_metadata(function.py_obj, "implementation")
    if implementation is None or implementation.kind not in {"inline", "call"}:
        return None, None
    return implementation.value, backend_references(function.py_obj, "js")


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
            if isinstance(module, ModuleAlias):
                module_name = module.py_module.__name__
                if module_name in {"typing", "pyjs.stdlib.typing"}:
                    return node.attr
                if module_name == "collections.abc" and node.attr == "Callable":
                    return "Callable"
        return None
    if not isinstance(node, ast.Name):
        return None
    try:
        value = scope.search(node.id)
    except NameError:
        return node.id
    if isinstance(value, TypeAliasValue) and (value.annotation is Callable or value.annotation is typing.Callable):
        return "Callable"
    if isinstance(value, TypeAliasValue) and value.annotation is typing.Literal:
        return "Literal"
    return None


@dataclass
class AssignmentValue:
    node: ast.expr
    declared_type: Class | UnionType | None
    inferred_type: Class | UnionType | None
    representation: ValueRepresentation | None = None

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


def iterable_protocol(value_type, representation=None, *, iterator=False):
    return resolve_iterable_protocol(value_type, representation, BUILTINS, iterator=iterator)


def function_parameters_by_name(function, *, include_positional_only=False):
    positional = (
        function.params
        if include_positional_only
        else function.params[function.posonly_count :]
    )
    return {
        parameter.arg: parameter
        for parameter in (*positional, *function.kwonlyargs)
    }


def uses_iterable_protocol(expected, value):
    # Structural return compatibility does not remove the runtime __iter__
    # dependency. Only an already nominally compatible arm bypasses adaptation
    # (notably dict in dict | Iterable), preserving its ordinary call contract.
    return expects_iterable(expected) and not all(
        any(is_subclass(actual, member) for member in get_type_members(expected))
        for actual in get_type_members(analyzed_value_type(value))
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
        if (isinstance(actual_member, Class) and actual_member.container.scope.is_builtins
                and actual_member.generic_name == "tuple" and not actual_member.generic_types):
            continue
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
    if isinstance(value, ast.Constant) and literal_member_for_value(
        expected,
        value.value,
    ):
        return True
    if isinstance(analyzed_value_object(value), Function) and any(
        member.name in {"callable", "object"} and member.container.scope.is_builtins
        and not isinstance(member, CallableClass)
        for member in get_type_members(expected)
    ):
        # An opaque callback contract does not depend on its inferred result.
        # Requiring that result here can block a constructor before it declares
        # the fields used by a registered event handler.
        return True
    actual = analyzed_value_type(value)
    if is_return_type_compatible(expected, actual):
        return True
    if expects_iterable(expected):
        if isinstance(value.obj, GenericClass):
            return value.obj.name in {"dict", "list", "set", "frozenset", "tuple"}
        return is_iterable_argument_compatible(expected, actual)
    expected_members = get_type_members(expected)
    if any(type_.name == "callable" and type_.container.scope.is_builtins for type_ in expected_members):
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


def infer_type_variables(pattern, actual, bindings, *, defaults=False):
    return infer_generic_types(pattern, actual, bindings, iterable_item_type,
                               defaults=defaults)


def default_type_variables(patterns, parameters, bindings):
    # Empty iterables supply no constraints, but can supply object as a last
    # resort after peers/context have resolved all the useful constraints.
    if any(parameter not in bindings for parameter in parameters):
        for pattern, argument in patterns:
            if pattern is not None:
                infer_type_variables(pattern, callable_value_type(argument),
                                     bindings, defaults=True)


def infer_representation_variables(
    pattern,
    actual,
    representation,
    bindings,
) -> bool:
    return infer_generic_representations(
        pattern,
        actual,
        representation,
        bindings,
        iterable_protocol,
    )


def analyzed_value_type(value):
    value_type = analyzed_value_object(value)
    if isinstance(value_type, Function):
        return callable_value_type(value)
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


def has_ordinary_float(values):
    return any(
        analyzed_numeric_format(value) is None
        and any(
            getattr(member, "generic_name", None) == "float"
            for member in get_type_members(analyzed_value_type(value))
        )
        for value in values
    )


def analyzed_iterable_protocol(value) -> IterableProtocol | None:
    representation = analyzed_representation(value)
    protocol = iterable_protocol(analyzed_value_type(value), representation)
    if protocol is not None:
        return protocol
    value_obj = analyzed_value_object(value)
    if not isinstance(value_obj, GenericClass):
        return None
    type_argument_count = {
        "dict": 2,
        "list": 1,
        "set": 1,
        "frozenset": 1,
    }.get(value_obj.name)
    if type_argument_count is None:
        return None
    object_type = BUILTINS.search("object")
    assert isinstance(object_type, Class)
    return iterable_protocol(
        value_obj(*([object_type] * type_argument_count)),
        representation,
    )


def type_has_ordinary_float(value_type, representation) -> bool:
    return any(
        member.generic_name == "float"
        and representation_for_member(value_type, representation, member) is None
        for member in get_type_members(value_type)
    )


def guarantees_ordinary_float_item(value, protocol: IterableProtocol) -> bool:
    if (
        isinstance(value, Call)
        and hasattr(value, "mapping_source_type")
        and isinstance(value.func, Attribute)
    ):
        value = value.func.value
    if isinstance(value, ast.Dict) and any(
        key is not None and has_ordinary_float((key,))
        for key in value.keys
    ):
        return True
    if isinstance(value, (ast.List, ast.Set, ast.Tuple)) and any(
        not isinstance(item, ast.Starred) and has_ordinary_float((item,))
        for item in value.elts
    ):
        return True
    value_type = analyzed_value_type(value)
    representation = analyzed_representation(value)
    if (
        isinstance(value_type, Class)
        and value_type.generic_name == "tuple"
        and not value_type.tuple_variadic
        and value_type.generic_types
    ):
        item_types = tuple(value_type.generic_types.values())
        item_representations = (
            representation.arguments
            if representation is not None
            and len(representation.arguments) == len(item_types)
            else (None,) * len(item_types)
        )
        return any(
            type_has_ordinary_float(item_type, item_representation)
            for item_type, item_representation in zip(
                item_types,
                item_representations,
                strict=True,
            )
        )
    return (
        analyzed_array_format(value) is not None
        and protocol.ordinary_item_types == {"float"}
    )


def is_slice_index(value):
    value_type = analyzed_value_type(value)
    return (isinstance(value_type, Class) and value_type.container.scope.is_builtins
            and value_type.generic_name == "slice")


def dynamic_slice_index(value):
    """An index domain that can select both item and slice behavior."""
    # Syntax slices do not imply first-class slice values. The selected
    # builtin model owns that capability (JavaScript has no slice class).
    return not is_slice_index(value) and any(
        isinstance(member, Class) and member.container.scope.is_builtins
        and "slice" in member.container.scope.names
        and member.generic_name in {"object", "slice"}
        for member in get_type_members(analyzed_value_type(value))
    )


def dynamic_builtin_subscript(function, args):
    return (bool(args) and is_builtin_method(function)
            and function.name in {"__getitem__", "__setitem__", "__delitem__"}
            and function.cls.generic_name in {"list", "tuple", "str", "bytes", "range"}
            and dynamic_slice_index(args[0]))


def is_builtin_method(function):
    return (isinstance(function, Function) and function.cls is not None
            and function.cls.container.scope.is_builtins)


def apply_subscript_result_representation(result, receiver, declared_result=None):
    layout = analyzed_array_format(receiver)
    representation = None
    receiver_representation = analyzed_representation(receiver)
    receiver_type = analyzed_value_type(receiver)
    if (isinstance(receiver_type, Class) and receiver_type.container.scope.is_builtins
            and receiver_type.generic_name == "list"
            and isinstance(result, Call) and result.args and is_slice_index(result.args[0])):
        set_analyzed_representation(result, receiver_representation or declared_result)
        return result
    if (
        layout is not None
        and receiver_representation is not None
        and receiver_representation.arguments
    ):
        representation = receiver_representation.arguments[0]
    elif layout is not None:
        representation = direct_representation(
            layout.item_numeric,
            layout.item_array,
        )
    else:
        receiver_type = analyzed_value_type(receiver)
        if receiver_representation is not None and receiver_representation.arguments:
            if getattr(receiver_type, "generic_name", None) == "dict":
                representation = receiver_representation.arguments[1]
            else:
                representation = receiver_representation.arguments[0]
    if representation is None:
        representation = declared_result
    if (isinstance(receiver_type, Class) and receiver_type.container.scope.is_builtins
            and receiver_type.generic_name == "list" and isinstance(result, Call)
            and result.args and dynamic_slice_index(result.args[0])):
        representation = merged_representation(analyzed_value_type(result), (
            (receiver_type.generic_types["V"], representation),
            (receiver_type, receiver_representation),
        ))
    set_analyzed_representation(result, representation)
    return result


def collection_items(value):
    if isinstance(value, (List, Tuple, Set)):
        return value.elts
    if isinstance(value, Dict):
        return [
            item
            for pair in zip(value.keys, value.values, strict=True)
            for item in pair
            if item is not None
        ]
    if isinstance(value, (ListComp, SetComp, GeneratorExp)):
        return [value.elt]
    if isinstance(value, DictComp):
        return [value.key, value.value]
    return []


def collection_contains_numeric_format(value):
    return any(
        analyzed_numeric_format(item) is not None
        or collection_contains_numeric_format(item)
        for item in collection_items(value)
    )


def callable_value_type(value):
    value_obj = analyzed_value_object(value)
    if isinstance(value_obj, CallableClass):
        return value_obj
    if not isinstance(value_obj, Function):
        return analyzed_value_type(value)
    if not value_obj.signature_analyzed:
        raise DependencyError(value_obj)
    return_type = (getattr(value, "union_return_type", None)
                   or value_obj.return_type or value_obj.declared_return_type)
    if return_type is None:
        raise DependencyError(value_obj)
    base = BUILTINS.search("callable")
    assert isinstance(base, Class)
    representation = analyzed_representation(value)
    if value_obj.is_async:
        awaitable = BUILTINS.search("Awaitable")
        assert isinstance(awaitable, GenericClass)
        return_type = awaitable(return_type)
    methods = getattr(value, "union_functions", ()) or (value_obj,)
    parameters = list(value_obj.params)
    for method in methods[1:]:
        # A positional view promises only the common typed prefix. Optional
        # suffixes can differ in length or type without forbidding calls that
        # omit them. Taking the first member's full signature was order-sensitive.
        length = 0
        for left, right in zip(parameters, method.params, strict=False):
            if analyzed_representation(left) != analyzed_representation(right):
                break
            if is_return_type_compatible(left.annotation.obj, right.annotation.obj):
                parameters[length] = right
            elif not is_return_type_compatible(right.annotation.obj, left.annotation.obj):
                break
            length += 1
        parameters = parameters[:length]
    return CallableClass(
        tuple(parameter.annotation.obj for parameter in parameters),
        return_type,
        base,
        tuple(
            getattr(parameter, "representation", None) for parameter in parameters
        ),
        representation.result if representation is not None else None,
        minimum_arguments=max(
            len(method.params) - len(method.defaults)
            for method in methods
        ),
        required_keywords=tuple(dict.fromkeys(
            parameter.arg
            for method in methods
            for parameter, default in zip(method.kwonlyargs, method.kw_defaults, strict=True)
            if default is None
        )),
    )


def infer_generic_call_type(
    generic: GenericClass,
    arguments: list[ast.expr],
    keywords: list[ast.keyword],
):
    if not generic.init_params or not generic.type_parameters:
        return None
    bindings = {}
    parameters = list(generic.init_params.values())[1:]
    patterns = []
    if generic.name == "dict" and generic.container.scope.is_builtins and arguments:
        source = analyzed_value_type(arguments[0])
        # The union constructor signature has two generic branches, so ordinary
        # inference cannot choose one. Both mappings and pair iterables must
        # contribute constraints before keyword values determine the result.
        if is_builtin_class(source, "dict"):
            pairs = (tuple(source.generic_types.values()),)
        else:
            # A heterogeneous outer tuple exposes a union of pair types.
            pairs = (tuple(pair.generic_types.values())
                     for pair in get_type_members(iterable_item_type(source))
                     if is_builtin_class(pair, "tuple") and not pair.tuple_variadic)
        for members in pairs:
            if len(members) == 2:
                for name, member in zip(("K", "V"), members, strict=True):
                    infer_type_variables(generic.type_parameters[name], member, bindings)
    for argument, parameter in zip(arguments, parameters, strict=False):
        if parameter.annotation is parameter.empty:
            continue
        pattern = resolve_python_annotation(parameter.annotation, generic.scope)
        patterns.append((pattern, argument))
        infer_type_variables(pattern, callable_value_type(argument), bindings)
    parameters_by_name = {parameter.name: parameter for parameter in parameters}
    variadic_keyword = next(
        (
            parameter
            for parameter in parameters
            if parameter.kind is inspect.Parameter.VAR_KEYWORD
        ),
        None,
    )
    for keyword in keywords:
        if keyword.arg is None:
            # Backends supporting runtime ** packs retain the mapping operand;
            # dict construction infers its values, not a dictionary of dicts.
            if generic.name == "dict" and generic.container.scope.is_builtins:
                mapping = analyzed_value_type(keyword.value)
                if is_builtin_class(mapping, "dict"):
                    infer_type_variables(generic.type_parameters["K"], mapping.generic_types["K"], bindings)
                    infer_type_variables(generic.type_parameters["V"], mapping.generic_types["V"], bindings)
            continue
        parameter = parameters_by_name.get(keyword.arg, variadic_keyword)
        if parameter is not None and parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            parameter = variadic_keyword
        if parameter is None or parameter.annotation is parameter.empty:
            continue
        pattern = resolve_python_annotation(parameter.annotation, generic.scope)
        patterns.append((pattern, keyword.value))
        infer_type_variables(
            pattern,
            callable_value_type(keyword.value),
            bindings,
        )
    if generic.name == "dict" and generic.container.scope.is_builtins and any(
        keyword.arg is not None for keyword in keywords
    ):
        infer_type_variables(
            generic.type_parameters["K"],
            generic.scope.search("str"),
            bindings,
        )
    default_type_variables(patterns, generic.type_parameters.values(), bindings)
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


def iterable_item_type(value_type, *, iterator=False):
    protocol = iterable_protocol(value_type, iterator=iterator)
    if protocol is None and iterator:
        # Invalid next(list[T]) arguments still infer T for the mismatch
        # diagnostic; structural argument validation rejects the list itself.
        protocol = iterable_protocol(value_type)
    return protocol.item_type if protocol is not None else value_type


def initializer_declares_field(initializer, name):
    if not isinstance(initializer, Function):
        return False
    initializers = [initializer]
    owner = initializer.cls
    while owner is not None and owner.super is not None:
        owner = owner.super
        inherited = owner.find_attrs("__init__", search_bases=False)
        if isinstance(inherited, Function):
            initializers.append(inherited)
    for method in initializers:
        definition = method.original_node
        if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = definition.args.posonlyargs + definition.args.args
        if not arguments:
            continue
        receiver = arguments[0].arg
        pending = list(definition.body)
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
                    and isinstance(node.value, ast.Name) and node.value.id == receiver
                    and node.attr == name):
                return True
            pending.extend(ast.iter_child_nodes(node))
    return False


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
        signature = callable_value_type(key)
        if isinstance(signature, CallableClass):
            return signature.return_type
        return BUILTINS.search("object")

    return value_type


def supports_order_comparison(value_type):
    if value_type is None:
        return True
    members = get_type_members(value_type)
    names = {member.name for member in members}
    if names <= {"bool", "float", "int"} or names == {"str"} or names == {"bytes"}:
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
                methods.extend(equality_methods(item_type))
            continue
        methods.extend(runtime_dunder_methods(member, "__lt__", "__gt__"))
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


def declared_protocol_method(cls, name, declaration):
    """Return the analyzed method only if it models the actual class declaration.

    Class-body values/aliases are not all represented in the analyzed attribute
    map. Its inherited Function must not stand in for a different declaration.
    Property analysis stores the getter; static/class methods keep descriptors.
    """
    method = cls.find_attrs(name)
    declared = declaration.fget if isinstance(declaration, property) else declaration
    return method if isinstance(method, Function) and method.py_func is declared else None


def runtime_dunder_methods(value_type, *method_names):
    methods = []
    pending = list(reversed(get_type_members(value_type)))
    seen = set()
    while pending:
        member = pending.pop()
        if member in seen:
            continue
        seen.add(member)
        if getattr(member.py_obj, "__builtin__", False):
            # Builtin collection comparisons invoke these methods recursively,
            # when no source-level call mentions the contained object's type.
            if set(method_names) <= {"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"} and member.generic_name in {
                "list", "tuple", "dict", "set", "frozenset", "KeysView", "ItemsView",
            }:
                for item in reversed(tuple(member.generic_types.values())):
                    pending.extend(reversed(get_type_members(item)))
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
        if not isinstance(method, Function) or method.cls is not BUILTINS.search("object"):
            return False
    return True


def runtime_class_dependency(value: Class, module: Module) -> Class | None:
    runtime_type = js_metadata(value.py_obj, "runtime_type")
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
    break_exits: bool = False,
    exception_sensitive: bool = True,
):
    for statement in statements:
        if statement_always_exits(
            statement,
            loop_control_exits=loop_control_exits,
            break_exits=break_exits,
            exception_sensitive=exception_sensitive,
        ):
            return False
    return True


def statement_parts_reaching_next(statement: ast.stmt):
    """Yield the parts of a statement that can run before the next statement."""
    if not isinstance(statement, ast.If):
        yield statement
        return
    yield statement.test
    for branch in (statement.body, statement.orelse):
        if body_can_fall_through(branch, loop_control_exits=True):
            for child in branch:
                yield from statement_parts_reaching_next(child)


def literal_iterable_is_nonempty(node: ast.expr) -> bool:
    # A splice avoids repeated analysis, not source-shape proofs. Inspect its
    # original syntax, rather than visiting the typed value a second time.
    while isinstance(node, AnalyzedExpression):
        node = node.python_node
    if isinstance(node, ast.Dict):
        return any(key is not None for key in node.keys)
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return any(not isinstance(item, ast.Starred) for item in node.elts)
    return False


def iterable_is_provably_nonempty(source, value) -> bool:
    if analyzed_array_format(value) is not None or literal_iterable_is_nonempty(
        source
    ):
        return True
    value_type = analyzed_value_type(value)
    return (
        isinstance(value_type, Class)
        and value_type.generic_name == "tuple"
        and not value_type.tuple_variadic
        and bool(value_type.generic_types)
    )


def body_always_returns(statements: list[ast.stmt]):
    for statement in statements:
        if statement_always_returns(statement):
            return True
        if statement_always_exits(statement):
            return False
    return False


def should_analyze_func_body(function: Function, target: str) -> bool:
    obj = getattr(function.py_obj, "__func__", function.py_obj)
    if is_declaration(obj, target):
        return False
    if function.cls is None or not is_declaration(function.cls.py_obj, target):
        return True
    if target == "js" and is_inline_for(function.cls.py_obj, target):
        return function.name != "__init__"
    return False


def should_analyze_target_body(func: Function) -> bool:
    environment = _ACTIVE_ENVIRONMENT.get()
    if environment.body_filter is not None:
        return environment.body_filter(func)
    return should_analyze_func_body(func, environment.name)


def representation_aware_function(function: Function) -> bool:
    return (
        getattr(function.py_obj, "__builtin__", False)
        or function.cls is not None
        and function.cls.py_obj.__dict__.get("__builtin__", False)
        or function.inline_decorator is not None
        or analysis_metadata(
            function.py_obj,
            "preserves_numeric_format",
            False,
        )
    )


def accepts_static_array_argument(function: Function) -> bool:
    return (
        function.name == "__add__"
        and function.cls is not None
        and function.cls.generic_name == "list"
        and getattr(function.cls.py_obj, "__builtin__", False)
    )


class LoopBreakFinder(ast.NodeVisitor):
    def __init__(self):
        self.found = False

    def visit_Break(self, node):
        self.found = True

    def visit_For(self, node):
        # Breaks in the nested body belong to that loop; its else suite is
        # outside that loop and can break the enclosing loop being inspected.
        for statement in node.orelse:
            self.visit(statement)

    def visit_AsyncFor(self, node):
        self.visit_For(node)

    def visit_While(self, node):
        self.visit_For(node)


class _CallAnalysis:
    """Compiler-private escape hatch for syntax-dependent call semantics."""

    def __init__(self, visitor, node, function, *, receiver=None):
        self.visitor = visitor
        self.node = node
        self.function = function
        self._result = None
        self._receiver = receiver

    def standard(self, *, defer_representation_arguments=()):
        if self._result is None:
            self.visitor.active_call_analysis.add(self.node)
            self.visitor.deferred_call_representation_arguments[self.node] = frozenset(
                defer_representation_arguments
            )
            try:
                self._result = self.visitor.visit_Call(self.node)
            finally:
                self.visitor.deferred_call_representation_arguments.pop(
                    self.node,
                    None,
                )
                self.visitor.active_call_analysis.remove(self.node)
        return self._result

    def receiver(self):
        assert isinstance(self.node.func, ast.Attribute)
        # Method resolution has already analyzed this receiver. Reuse it only
        # for this call hook, never by caching it on the original source AST.
        if self._receiver is None:
            self._receiver = self.visitor.visit(self.node.func.value)
        return self._receiver

    @staticmethod
    def replace_forwarded_argument(result, index, value):
        offset = int(
            isinstance(getattr(result, "forwarded_func", None), Attribute)
        )
        result.args[index + offset] = value

    def with_result_type(self, result_type, *, result=None):
        if result is None:
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

    @staticmethod
    def set_result_formats(result, numeric=None, array=None):
        set_analyzed_representation(
            result,
            direct_representation(numeric, array),
        )
        return result

    @staticmethod
    def set_result_representation(result, representation):
        set_analyzed_representation(result, representation)
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
        source_representation = analyzed_representation(value)
        source_type = analyzed_value_type(value)
        target_representation = self.visitor.annotation_representation(self.node.args[0])
        if target_representation is not None and representations_conflict(
            (
                (source_type, source_representation),
                (target_type, target_representation),
            )
        ):
            self.visitor.fail(
                self.node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "typing.cast() cannot change a value's runtime representation",
                help=(
                    "Construct the fixed-width or StaticArray value explicitly "
                    "before casting it."
                ),
            )
        value_obj = target_type
        if isinstance(target_type, Class):
            value_obj = target_type(
                "__cast_result__",
                self.visitor.scope,
                self.visitor.func,
            )
        result = StaticCast(value_obj, value, lineno=self.node.lineno)
        result_representation = target_representation or source_representation
        if target_representation is None and isinstance(source_type, UnionType):
            result_representation = narrowed_representation(
                source_type,
                source_representation,
                target_type,
            )
        set_analyzed_representation(
            result,
            result_representation,
        )
        return result

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
        call = Call(
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
        representation = analyzed_representation(receiver)
        if representation is not None and representation.numeric is not None:
            call = self.visitor.normalize_numeric_value(
                call,
                representation.numeric,
                force=True,
            )
        set_analyzed_representation(call, representation)
        return call

    def isinstance(self, *, validate_numeric=True):
        if len(self.node.args) != 2 or self.node.keywords:
            return self.standard()

        value = self.visitor.guard_value(self.visitor.visit(self.node.args[0]))
        target_nodes = flatten_isinstance_targets(self.node.args[1])
        if validate_numeric and all(
            isinstance(target, (ast.Name, ast.Attribute, AnalyzedExpression))
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
            result = self.standard()
            result.args[0] = self.visitor.guard_value(result.args[0])
            return result

        # Literal nodes carry their Class in .obj, not an Instance. The lexical
        # subject is a value, even when its source is constant or represented.
        value_obj = analyzed_value_type(value)("$value", self.visitor.scope, self.visitor.func)
        apply_representation(value_obj, analyzed_representation(value))
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
            ast.copy_location(analyzed, self.node)
            analyzed.args[0] = ast.copy_location(Name(value_obj, id="$value"), self.node.args[0])
            checks.append(analyzed)

        if checks:
            body = (
                checks[0]
                if len(checks) == 1
                else BoolOp(BUILTINS.search("bool"), op=ast.Or(), values=checks)
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
            "isinstance() cannot distinguish int from float after JavaScript lowering",
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
            iterable_item_type(analyzed_value_type(argument)) for argument in result.args
        ]
        result = self.with_result_type(iterator(tuple_type(*item_types)))
        zipped_representation = tuple_representation(
            tuple(
                self.visitor.require_iterable(source, argument).item_representation
                for source, argument in zip(
                    self.node.args,
                    result.args,
                    strict=True,
                )
            )
        )
        return self.set_result_representation(
            result,
            compound_representation(arguments=(zipped_representation,)),
        )

    def mapped(self, *, max_iterables):
        if len(self.node.args) > max_iterables + 1:
            self.visitor.fail(
                self.node.args[max_iterables + 1],
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"map() supports at most {max_iterables} iterables",
                help=(
                    "Define a typed loop when mapping more iterables in one operation."
                ),
            )
        result = self.standard()
        callback_obj = analyzed_value_object(result.args[0])
        callback = callable_value_type(result.args[0])
        representation = (
            callback.return_representation
            if isinstance(callback, CallableClass)
            else None
        )
        if isinstance(callback_obj, Function) and analysis_metadata(
            callback_obj.py_obj,
            "preserves_numeric_format",
            False,
        ):
            protocol = self.visitor.require_iterable(
                self.node.args[1],
                result.args[1],
            )
            iterator = BUILTINS.search("Iterator")
            assert isinstance(iterator, GenericClass)
            result = self.with_result_type(iterator(protocol.item_type))
            representation = protocol.item_representation
        return self.set_result_representation(
            result,
            compound_representation(arguments=(representation,)),
        )

    def preserving_iterator(self, operation: str, iterable_index: int):
        result = self.standard()
        protocol = self.visitor.require_iterable(
            self.node.args[iterable_index],
            result.args[iterable_index],
        )
        return self.set_result_representation(
            result,
            compound_representation(arguments=(protocol.item_representation,)),
        )

    def mapping_view(self, *indexes: int):
        receiver = self.receiver()
        result = self.standard()
        representation = analyzed_representation(receiver)
        members = (
            tuple(
                representation.arguments[index]
                if index < len(representation.arguments)
                else None
                for index in indexes
            )
            if representation is not None
            else (None,) * len(indexes)
        )
        if getattr(analyzed_value_type(result), "generic_name", None) == "ItemsView":
            arguments = members  # The view has K/V fields, not one iterator item.
        else:
            item = members[0] if len(members) == 1 else tuple_representation(members)
            arguments = (item,)
        return self.set_result_representation(result, compound_representation(arguments=arguments))

    def collection_item(self, index: int = 0):
        receiver = self.receiver()
        result = self.standard()
        representation = analyzed_representation(receiver)
        item = (
            representation.arguments[index]
            if representation is not None and index < len(representation.arguments)
            else None
        )
        return self.set_result_representation(result, item)

    def compare_collection_item(self, index: int = 0):
        self.visitor.validate_call_shape(self.node, self.function)
        receiver = self.receiver()
        argument = self.visitor.visit(self.node.args[index])
        result = self.standard()
        protocol = self.visitor.require_iterable(self.node, receiver)
        argument = self.visitor.normalize_comparison_value(
            self.node.args[index],
            argument,
            protocol.item_type,
            protocol.item_representation,
            message="Collection comparison uses an incompatible item representation",
            help_text="Convert the compared value to the collection's item type first.",
        )
        self.replace_forwarded_argument(result, index, argument)
        return result

    def compare_collection_iterable(self, index: int = 0):
        self.visitor.validate_call_shape(self.node, self.function)
        receiver = self.receiver()
        argument = self.visitor.visit(self.node.args[index])
        result = self.standard()
        receiver_protocol = self.visitor.require_iterable(self.node, receiver)
        if isinstance(argument, List) and not argument.elts:
            # A fresh empty argument has no item domain of its own. Reuse the
            # receiver contract, without reinterpreting any existing container.
            argument = self.visitor.normalize_stored_iterable(
                self.node.args[index], argument,
                receiver_protocol.item_representation, receiver_protocol.item_type,
            )
            self.replace_forwarded_argument(result, index, argument)
        argument_protocol = self.visitor.require_iterable(
            self.node.args[index],
            argument,
        )
        if (
            receiver_protocol.item_representation
            != argument_protocol.item_representation
            and not numeric_comparison_representations_compatible(
                receiver_protocol.item_representation,
                argument_protocol.item_representation,
            )
        ):
            self.visitor.fail(
                self.node.args[index],
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Set comparison uses incompatible item representations",
                help="Convert both sets to the same item type first.",
            )
        return result

    def compare_collection(self, index: int = 0):
        self.visitor.validate_call_shape(self.node, self.function)
        receiver = self.receiver()
        argument = self.visitor.visit(self.node.args[index])
        result = self.standard()
        receiver_representation = analyzed_representation(receiver)
        argument_representation = analyzed_representation(argument)
        set_comparison = all(isinstance(value_type, Class) and value_type.container.scope.is_builtins
                             and value_type.generic_name in {"set", "frozenset", "KeysView", "ItemsView"}
                             for value_type in map(analyzed_value_type, (receiver, argument)))
        if set_comparison:
            # Compare item contracts, not container-generic argument shapes:
            # ItemsView[K, V] and set[tuple[K, V]] describe the same item.
            receiver_representation = self.visitor.require_iterable(self.node, receiver).item_representation
            argument_representation = self.visitor.require_iterable(self.node, argument).item_representation
        conflict = receiver_representation != argument_representation if set_comparison else representations_conflict(
            (
                (analyzed_value_type(receiver), receiver_representation),
                (analyzed_value_type(argument), argument_representation),
            )
        )
        if conflict and not numeric_comparison_representations_compatible(
            receiver_representation,
            argument_representation,
        ):
            self.visitor.fail(
                self.node.args[index],
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Collection comparison uses incompatible item representations",
                help="Convert both collections to the same item types first.",
            )
        return result

    def collection_copy(self):
        receiver = self.receiver()
        result = self.standard()
        representation = analyzed_representation(receiver)
        if (layout := analyzed_array_format(receiver)) is not None:
            item = (
                representation.arguments[0]
                if representation is not None and representation.arguments
                else direct_representation(
                    layout.item_numeric,
                    layout.item_array,
                )
            )
            representation = compound_representation(arguments=(item,))
        return self.set_result_representation(result, representation)

    def sequence_repeat(self):
        receiver = self.receiver()
        if analyzed_array_format(receiver) is not None:
            self.visitor.fail(
                self.node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "StaticArray repetition would change its declared length",
                help="Copy items explicitly into a new StaticArray of that length.",
            )
        result = self.standard()
        return self.visitor.repeated_tuple(
            self.node,
            result,
            receiver,
            self.node.args[0],
        )

    def mapping_key(self):
        _receiver, result = self.validated_mapping_call()
        return result

    def validated_mapping_call(self):
        self.visitor.validate_call_shape(self.node, self.function)
        receiver = self.receiver()
        key = self.visitor.visit(self.node.args[0])
        key = self.visitor.normalize_mapping_key(
            self.node.args[0],
            receiver,
            key,
        )
        result = self.standard()
        self.replace_forwarded_argument(result, 0, key)
        return receiver, result

    def mapping_value(self):
        receiver, result = self.validated_mapping_call()
        representation = analyzed_representation(receiver)
        value_representation = (
            representation.arguments[1]
            if representation is not None and len(representation.arguments) > 1
            else None
        )
        result_type = analyzed_value_type(result)
        # The bound method has the resolved mapping signature even when the
        # receiver is a recursive alias, which has no generic_types of its own.
        value_type = self.function.cls.generic_types["V"]
        default = result.args[1] if len(result.args) > 1 else None
        represented_results = [(value_type, value_representation)]
        if default is not None:
            represented_results.append(
                (analyzed_value_type(default), analyzed_representation(default))
            )
        elif isinstance(result_type, UnionType):
            represented_results.append((get_none_type(), None))
        return self.set_result_representation(
            result,
            self.visitor.merge_typed_representations(
                self.node,
                result_type,
                represented_results,
                "Dictionary fallback values",
            ),
        )

    def enumerated(self, iterable_parameter="values"):
        result = self.standard()
        source = self.node.args[0] if self.node.args else next(
            keyword.value for keyword in self.node.keywords if keyword.arg == iterable_parameter
        )
        argument = result.args[0] if result.args else next(
            keyword.value for keyword in result.keywords if keyword.arg == iterable_parameter
        )
        protocol = self.visitor.require_iterable(source, argument)
        item = tuple_representation((None, protocol.item_representation))
        return self.set_result_representation(
            result,
            compound_representation(arguments=(item,)),
        )

    def iterator(self):
        if len(self.node.args) not in {1, 2} or self.node.keywords:
            self.visitor.fail(self.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "iter() requires one or two positional arguments")
        if len(self.node.args) == 1:
            return self.preserving_iterator("iter()", 0)
        result = self.standard()
        callback = callable_value_type(result.args[0])
        sentinel = result.args[1]
        if (not isinstance(callback, CallableClass) or callback.parameter_types != ()
                or not same_analyzer_type(callback.return_type, analyzed_value_type(sentinel))
                or callback.return_representation != analyzed_representation(sentinel)):
            self.visitor.fail(self.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "iter(callable, sentinel) requires a zero-argument callable and matching result/sentinel types and representations")
        result = self.with_result_type(BUILTINS.search("Iterator")(callback.return_type))
        result.runtime_methods = tuple(dict.fromkeys((*result.runtime_methods, *equality_methods(callback.return_type))))
        return self.set_result_representation(result, compound_representation(arguments=(callback.return_representation,)))

    def iterator_item(self):
        result = self.standard()
        protocol = iterable_protocol(analyzed_value_type(result.args[0]),
                                     analyzed_representation(result.args[0]), iterator=True)
        if protocol is None:
            self.visitor.fail(self.node.args[0], DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "next() requires an iterator with a zero-argument __next__ method")
        represented_results = [(protocol.item_type, protocol.item_representation)]
        if len(result.args) > 1:
            represented_results.append(
                (
                    analyzed_value_type(result.args[1]),
                    analyzed_representation(result.args[1]),
                )
            )
            for target, target_representation in represented_results:
                if not is_builtin_class(target, "tuple") or not target.tuple_variadic:
                    continue
                member = next(iter(target.generic_types.values()))
                item_representation = target_representation.item_representation if target_representation else None
                compatible = True
                for actual, representation in represented_results:
                    if not is_builtin_class(actual, "tuple"):
                        compatible = False
                        break
                    fields = tuple(actual.generic_types.values())
                    parts = representation.arguments if representation else (None,) * len(fields)
                    if any(not same_analyzer_type(field, member) or part != item_representation
                           for field, part in zip(fields, parts, strict=True)):
                        compatible = False
                        break
                if compatible:
                    # Immutable homogeneous tuples can share a variable-length
                    # view without copying. Avoid a union whose arms differ only
                    # in tuple length; retain the selected/default object's identity.
                    return self.set_result_representation(
                        self.with_result_type(target, result=result), target_representation,
                    )
        result_type = None
        for value_type, _representation in represented_results:
            result_type = merge_return_types(result_type, value_type)
        result = self.with_result_type(result_type, result=result)
        return self.set_result_representation(
            result,
            self.visitor.merge_typed_representations(
                self.node,
                analyzed_value_type(result),
                represented_results,
                "Iterator fallback values",
            ),
        )

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
        represented_results = [
            (
                result_type,
                runtime_annotation_representation(
                    receiver_type.annotations[key.value]
                ),
            )
        ]
        if key.value not in receiver_type.required_keys:
            if len(result.args) > 1:
                default_type = analyzed_value_type(result.args[1])
                default_representation = analyzed_representation(result.args[1])
            else:
                default_type = get_none_type()
                default_representation = None
            represented_results.append((default_type, default_representation))
            result_type = merge_return_types(result_type, default_type)
        result = self.with_result_type(result_type)
        representation = self.visitor.merge_typed_representations(
            self.node,
            result_type,
            represented_results,
            "TypedDict.get() results",
        )
        return self.set_result_representation(result, representation)

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
        candidates = result.args
        wgsl_context = (
            _ACTIVE_ENVIRONMENT.get().name == "wgsl"
            or get_wgsl_decoration(self.visitor.func.py_func) is not None
        )
        if wgsl_context and len(candidates) > 1:
            formats = numeric_formats(candidates)
            if len(formats) == 1:
                numeric = next(iter(formats))
                if numeric.domain == "wgsl":
                    representation = direct_representation(numeric, None)
                    for source, candidate in zip(
                        self.node.args,
                        candidates,
                        strict=True,
                    ):
                        if analyzed_representation(candidate) is None and (
                            integer_literal(source) is not None
                            or float_literal(source) is not None
                        ):
                            set_analyzed_representation(
                                candidate,
                                representation,
                            )
        typed_representations = []
        if len(result.args) == 1:
            candidate = result.args[0]
            protocol = analyzed_iterable_protocol(candidate)
            if protocol is None and analyzed_representation(candidate) is not None:
                protocol = self.visitor.require_iterable(
                    self.node.args[0],
                    candidate,
                )
            if protocol is not None:
                typed_representations.append(
                    (protocol.item_type, protocol.item_representation)
                )
        else:
            typed_representations.extend(
                (analyzed_value_type(candidate), analyzed_representation(candidate))
                for candidate in candidates
            )
        defaults = [
            keyword.value for keyword in result.keywords if keyword.arg == "default"
        ]
        typed_representations.extend(
            (analyzed_value_type(default), analyzed_representation(default))
            for default in defaults
        )
        representation = self.visitor.merge_typed_representations(
            self.node,
            analyzed_value_type(result),
            typed_representations,
            f"{operation}() candidates",
        )
        return self.set_result_representation(
            result,
            representation,
        )

    def represented_sum(self):
        result = self.standard(defer_representation_arguments=(0,))
        if not result.args:
            return result
        source = result.args[0]
        protocol = self.visitor.require_iterable(
            self.node.args[0],
            source,
            allow_representation_conflict=True,
        )
        item_representation = protocol.item_representation
        numeric = item_representation.numeric if item_representation is not None else None
        starts = result.args[1:]
        starts.extend(
            keyword.value for keyword in result.keywords if keyword.arg == "start"
        )
        if isinstance(self.node.args[0], (ast.List, ast.Tuple)) and not self.node.args[0].elts:
            # An empty literal returns the start unchanged; contextual iterable
            # widening must not make sum([], 5) a floating-point result.
            start_type = analyzed_value_type(starts[0]) if starts else BUILTINS.search("int")
            start_representation = analyzed_representation(starts[0]) if starts else None
            return self.set_result_representation(
                self.with_result_type(start_type), start_representation,
            )
        ordinary_float_start = bool(starts) and has_ordinary_float(starts)
        possible_formats = protocol.item_numeric_formats
        start_numeric = analyzed_numeric_format(starts[0]) if starts else None
        provably_nonempty = iterable_is_provably_nonempty(
            self.node.args[0],
            source,
        )
        guaranteed_ordinary_float = (
            numeric is None
            and start_numeric is not None
            and not possible_formats
            and start_numeric.kind == "integer"
            and "float" in protocol.ordinary_item_types
            and guarantees_ordinary_float_item(source, protocol)
        )
        numeric, error = resolve_sum_numeric_format(
            numeric,
            possible_formats,
            protocol.ordinary_item_types,
            start_numeric,
            ordinary_float_start=ordinary_float_start,
            guaranteed_ordinary_float=guaranteed_ordinary_float,
            provably_nonempty=provably_nonempty,
        )
        if error == "ambiguous":
            self.visitor.fail(
                self.node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "sum() has an ambiguous numeric result across iterable branches",
                help=(
                    "Convert every branch to one item type. A represented "
                    "float start can absorb ordinary numeric branches; an "
                    "ordinary float start can absorb fixed-width integer "
                    "branches."
                ),
            )
        if error == "incompatible_start":
            self.visitor.fail(
                self.node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "sum() start uses an incompatible numeric representation",
                help="Use an ordinary integer or the iterable item type.",
            )
        if error == "potentially_empty":
            self.visitor.fail(
                self.node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "sum() has an ambiguous fixed-width result for a potentially "
                "empty iterable",
                help=(
                    "Pass a start value using the iterable's fixed-width item "
                    "type, or sum a statically non-empty value such as a "
                    "StaticArray."
                ),
            )
        if numeric is None:
            return result
        self.set_result_formats(result, numeric)
        return self.visitor.normalize_numeric_value(result, numeric, force=True)

    def absolute(self):
        result = self.standard()
        if any(member.generic_name not in {"bool", "int", "float"}
               for member in get_type_members(analyzed_value_type(result.args[0]))):
            return self.visitor.dispatch_dunder_call(self.function, "__abs__", result.args, result.keywords)
        return result

    def represented_divmod(self):
        result = self.standard()
        if any(member.generic_name not in {"bool", "int", "float"}
               for argument in result.args for member in get_type_members(analyzed_value_type(argument))):
            left, right = result.args
            left_type, right_type = analyzed_value_type(left), analyzed_value_type(right)
            if isinstance(left_type, UnionType) or isinstance(right_type, UnionType):
                self.visitor.fail(self.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                                  "application divmod() operands must have concrete types",
                                  help="Narrow application unions before calling divmod().")
            try:
                method, reverse = self.visitor.resolve_binary_operator(
                    left_type, right_type, "__divmod__", "__rdivmod__")
            except NameError:
                self.visitor.fail(self.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                                  "divmod() operands do not define compatible division",
                                  help="Define __divmod__() or __rdivmod__().")
            if reverse:
                left, right = right, left
            signature = self.visitor.binary_operator_signature(method, right, self.node)
            [right] = self.visitor.normalize_lowered_method_arguments(
                [self.node.args[0] if reverse else self.node.args[1]], [right], signature, left)
            call = self.visitor.call_node(
                self.node, signature.return_type,
                func=Attribute(method, value=left, attr=method.name),
                args=[right], keywords=[], reverse=reverse,
                dependency_objects=self.visitor.inline_dependencies(method, self.node))
            if signature is not method:
                self.set_result_representation(call, signature.return_representation)
            return call
        formats = possible_numeric_formats(result.args)
        if any(is_portable_float_format(numeric) for numeric in formats):
            self.visitor.fail_portable_float_operation(
                self.node,
                "divmod()",
            )
        ordinary_float = has_ordinary_float(result.args)
        numeric = operation_numeric_format(result.args)
        first_type = analyzed_value_type(result.args[0])
        ordinary_bool = (
            isinstance(first_type, Class)
            and first_type.generic_name == "bool"
            and any(value.kind == "integer" for value in formats)
        )
        if ordinary_bool:
            numeric = None
        if numeric is None and formats and not ordinary_float and not ordinary_bool:
            self.visitor.fail(
                self.node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "divmod() has an ambiguous numeric result across union branches",
                help=(
                    "Convert every branch to one numeric type, or include an "
                    "ordinary float operand to select ordinary float results."
                ),
            )
        if ordinary_float:
            numeric = None
        representation = direct_representation(
            numeric,
            None,
        )
        return self.set_result_representation(
            result,
            tuple_representation((representation, representation)),
        )

    def reject_portable_float_operation(self, operation: str):
        result = self.standard()
        assert isinstance(result.func, Attribute)
        numeric = analyzed_numeric_format(result.func.value)
        if is_portable_float_format(numeric):
            self.visitor.fail_portable_float_operation(
                self.node,
                operation,
            )
        return result

    def sortable(self, *, method=False):
        result = self.standard()
        operation = "list.sort" if method else "sorted"
        protocol = self.visitor.require_iterable(
            self.node.func.value if method else self.node.args[0],
            result.func.value if method else result.args[0],
        )
        value_type = protocol.item_type
        item_representation = protocol.item_representation
        self.visitor.validate_sort_order(
            self.node,
            value_type,
            result.keywords,
            operation,
        )
        for keyword in result.keywords:
            if keyword.arg != "key":
                continue
            signature = callable_value_type(keyword.value)
            if not isinstance(signature, CallableClass) or not signature.parameter_types:
                continue
            parameter_representation = (
                signature.parameter_representations[0]
                if signature.parameter_representations else None
            )
            # The receiver's item representation is not an explicit argument
            # to list.sort, so ordinary argument inference can miss this edge.
            if representations_conflict((
                (value_type, item_representation),
                (signature.parameter_types[0], parameter_representation),
            )):
                self.visitor.fail(
                    self.node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "Sort items and key parameter use incompatible representations",
                    help="Use a key parameter matching the iterable item type.",
                )
        comparison_type = keyed_comparison_type(value_type, result.keywords)
        result.runtime_methods = tuple(
            dict.fromkeys((*result.runtime_methods, *ordering_methods(comparison_type)))
        )
        if not method:
            self.set_result_representation(
                result,
                compound_representation(arguments=(item_representation,)),
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
            protocol = self.visitor.require_iterable(
                self.node.args[0],
                result.args[0],
            )
            return self.set_result_representation(
                result,
                compound_representation(arguments=(protocol.item_representation,)),
            )
        type_names = ", ".join(
            sorted(
                type_.generic_name or type_.name for type_ in get_type_members(value_type)
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


def context_exit_can_suppress(method):
    """Only a None-returning __exit__ proves exceptions cannot be suppressed."""
    result = getattr(method, "return_type", None)
    return not (isinstance(result, Class) and result.generic_name == "NoneType")


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
    break_exits: bool = False,
    exception_sensitive: bool = True,
):
    if isinstance(statement, (ast.Return, ast.Raise)):
        return True
    if (loop_control_exits or break_exits) and isinstance(statement, ast.Break):
        return True
    if loop_control_exits and isinstance(statement, ast.Continue):
        return True
    if isinstance(statement, ast.If):
        return (
            bool(statement.orelse)
            and not body_can_fall_through(
                statement.body,
                loop_control_exits=loop_control_exits,
                break_exits=break_exits,
                exception_sensitive=exception_sensitive,
            )
            and not body_can_fall_through(
                statement.orelse,
                loop_control_exits=loop_control_exits,
                break_exits=break_exits,
                exception_sensitive=exception_sensitive,
            )
        )
    if isinstance(statement, ast.Match):
        return bool(statement.cases) and all(
            not body_can_fall_through(
                case.body,
                loop_control_exits=loop_control_exits,
                break_exits=break_exits,
                exception_sensitive=exception_sensitive,
            )
            for case in statement.cases
        )
    if isinstance(statement, ast.While):
        if (
            statement.orelse
            and not body_breaks_current_loop(statement.body)
            and not body_can_fall_through(statement.body, exception_sensitive=exception_sensitive)
            and not body_can_fall_through(statement.orelse, exception_sensitive=exception_sensitive)
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
            break_exits=break_exits,
            exception_sensitive=exception_sensitive,
        ):
            return True
        body_exits = not body_can_fall_through(
            statement.body,
            loop_control_exits=loop_control_exits,
            break_exits=break_exits,
            exception_sensitive=exception_sensitive,
        )
        success_exits = body_exits or (
            bool(statement.orelse)
            and not body_can_fall_through(
                statement.orelse,
                loop_control_exits=loop_control_exits,
                break_exits=break_exits,
                exception_sensitive=exception_sensitive,
            )
        )
        handlers_exit = all(
            not body_can_fall_through(
                handler.body,
                loop_control_exits=loop_control_exits,
                break_exits=break_exits,
                exception_sensitive=exception_sensitive,
            )
            for handler in statement.handlers
        )
        return success_exits and handlers_exit
    if isinstance(statement, ast.With):
        # A raise, return expression, or preceding statement can throw an
        # exception swallowed by __exit__. Raw/untyped With nodes
        # also need the conservative answer; lowering uses the same contract.
        if exception_sensitive and context_exit_can_suppress(getattr(statement, "exit_method", None)):
            return False
        return not body_can_fall_through(
            statement.body,
            loop_control_exits=loop_control_exits,
            break_exits=break_exits,
            exception_sensitive=exception_sensitive,
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


def without_docstring(statements: list[ast.stmt]) -> list[ast.stmt]:
    if not statements:
        return statements
    first = statements[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return statements[1:]
    return statements


class ComprehensionScope(LocalScope):
    def __init__(self, parent, resolve):
        super().__init__(parent)
        self.resolve = resolve

    def search(self, name):
        if name not in self.names and self.resolve is not None:
            self.resolve(name)
        return super().search(name)

    def lookup(self, name):
        if name not in self.names and self.resolve is not None:
            self.resolve(name)
        return super().lookup(name)


def flow_source_site(statement):
    # Generated loop nodes can be recreated on a function retry. Source
    # coordinates keep the monotone widening set stable across attempts.
    return type(statement), getattr(statement, "lineno", 0), getattr(statement, "col_offset", 0)


class InferenceVisitor(ast.NodeVisitor):
    numeric_domains: frozenset[str] | None = None
    supports_exception_causes = False

    def __init__(self, func: Function, scope: LocalScope = None):
        self.func = func
        self.scope = scope or func.scope
        self.assignment_scope = func.scope
        # Parent of the current deferred expression; proofs below this scope
        # belong to its execution, while enclosing proofs belong to creation.
        self.deferred_parent = None
        self.assignment_target: ast.AST | None = None
        self.contextual_types: dict[ast.AST, Class | UnionType] = {}
        self.contextual_numeric_formats: dict[ast.AST, NumericFormat] = {}
        self.contextual_representations: dict[
            ast.AST,
            ValueRepresentation,
        ] = {}
        self.direct_call_target: ast.AST | None = None
        self.active_call_analysis: set[ast.Call] = set()
        self.deferred_call_representation_arguments: dict[
            ast.Call,
            frozenset[int],
        ] = {}
        self.in_exception_handler = False
        self.in_type_annotation = False
        self.loop_break_collectors: list[tuple[LocalScope, list[InferenceVisitor]]] = []
        self.pending_finally_breaks: list[
            list[tuple[list[InferenceVisitor], InferenceVisitor]]
        ] = []
        self.flow_widenings: dict[tuple, set[str]] = {}
        self.pending_flow_widenings: dict[tuple, set[str]] = {}
        self.written_names: dict[ast.AST, frozenset[str]] = {}

    def visit(self, node):
        result = super().visit(node)
        if isinstance(result, list):
            for replacement in result:
                if isinstance(replacement, ast.AST):
                    ast.copy_location(replacement, node)
                    if replacement is not node:
                        replacement.python_node = getattr(node, "python_node", node)
        elif isinstance(result, ast.AST):
            ast.copy_location(result, node)
            if result is not node:
                result.python_node = getattr(node, "python_node", node)
        return result

    @property
    def module(self) -> Module:
        return self.func.cls.container if self.func.is_method else self.func.container

    def visit_AnalyzedExpression(self, node):
        return node.value

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

    def visit_contextual_expression(
        self,
        node,
        expected_type,
        expected_numeric_format=None,
        expected_representation=None,
    ):
        if expected_type is not None:
            self.contextual_types[node] = expected_type
        if expected_numeric_format is not None:
            self.contextual_numeric_formats[node] = expected_numeric_format
        if expected_representation is not None:
            self.contextual_representations[node] = expected_representation
        try:
            return self.visit(node)
        finally:
            self.contextual_types.pop(node, None)
            self.contextual_numeric_formats.pop(node, None)
            self.contextual_representations.pop(node, None)

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

    def reject_union_subscript(
        self,
        node: ast.AST,
        value: Object | UnionType,
        method_name: str | None = None,
    ) -> None:
        union_type = self.receiver_union(value)
        if union_type is None:
            return
        if method_name is not None:
            for member_type in union_type.types:
                try:
                    member_type._self.find(method_name)
                except NameError:
                    return
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "Subscript access on union values is not supported",
            help="Narrow the value with isinstance() before indexing it.",
        )

    def check_opaque_library_attribute(self, node: ast.Attribute, cls: Class):
        info = cls.library_info
        if (info is not None and info.opaque
                and any(node.attr in vars(base) for base in cls.py_cls.__mro__)):
            # Inspect namespaces, not descriptors: reporting an unsupported
            # host property must not execute it during compilation.
            self.fail(
                node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Field-only library model {cls.name!r} does not expose "
                f"host-side member {node.attr!r}",
                help="Read declared fields, or compute this value in Python before the native call.",
            )

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
                self.check_opaque_library_attribute(node, member_type)
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
                f"Attribute {node.attr!r} is not defined on every member of {union_name}",
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
                    f"Narrow the value with isinstance() before accessing {node.attr!r}."
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
        first_inline, first_dependencies = js_lowering(first)
        target = _ACTIVE_ENVIRONMENT.get().name
        first_erased = is_empty_inline(first.py_func, target)
        incompatible = [
            member_type.name
            for member_type, method in zip(value_type.types, methods, strict=True)
            if js_lowering(method)[0] is not first_inline
            or method.is_async != first.is_async
            or js_lowering(method)[1] != first_dependencies
            or is_empty_inline(method.py_func, target) != first_erased
        ]
        if incompatible:
            union_name = value_type.to_annotation_str(" | ")
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Method {node.attr!r} has incompatible client lowering on {union_name}",
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
        narrowed = self.child_visitor(LocalScope(self.scope))
        value_name = ast.unparse(value_node)
        value = value_type(value_name, narrowed.scope, self.func)
        try:
            original = self.visit(value_node)
        except DependencyError, NameError:
            pass
        else:
            # A closure captures storage, not a snapshot of this flow proof.
            value.narrowed_from = analyzed_value_object(original)
            representation = narrowed_representation(
                analyzed_value_type(original),
                analyzed_representation(original),
                value_type,
            )
            apply_representation(value, representation)
        narrowed.scope.add(value)
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
        value = self.guard_value(self.visit(value_node), preserve_local=True)
        if not isinstance(value.obj, Instance):
            return None
        value_types = get_type_members(value.obj.cls)
        non_none_types = [type_ for type_ in value_types if type_.name != "NoneType"]
        if not non_none_types or len(non_none_types) == len(value_types):
            return None
        return value_node, UnionType(types=non_none_types).type, isinstance(test.ops[0], ast.IsNot)

    def inline_dependencies(self, function: Function | Class, node: ast.AST):
        objects = {}
        dependencies = js_lowering(function)[1] or {}
        for name, dependency in dependencies.items():
            if is_js_enabled(dependency) is not True:
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
                if is_js_enabled(dependency) is False:
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
            if not isinstance(dependency_obj, (Class, Function)):
                self.fail(
                    node,
                    DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                    f"Inline dependency {name!r} of {function.name!r} must be a "
                    "class or function",
                )
            if isinstance(dependency_obj, Function) and dependency_obj.inline_decorator:
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
        *,
        reverse: bool = False,
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
            if isinstance(interface, Function):
                representation = interface.return_representation
                if interface.is_async:
                    representation = compound_representation(
                        arguments=(representation,)
                    )
                apply_representation(value_obj, representation)
        call = Call(
            return_type,
            value_obj=value_obj,
            reverse=reverse,
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
                # Forwarding moves the receiver into args[0], but must not
                # discard the source operand order of membership/reflection.
                reverse=attributes.get("reverse", False),
            )
        if isinstance(return_type, Class) and "value_obj" not in attributes:
            # Preserve attributes on operator results such as (a * 2.0).z.
            attributes["value_obj"] = return_type(
                "__call_result__", self.scope, self.func
            )
        call = Call(
            return_type,
            func=func,
            args=args,
            keywords=keywords,
            **attributes,
        )
        if isinstance(call.value_obj, Instance):
            interface = func.obj
            representation = None
            if isinstance(interface, Function):
                representation = interface.return_representation
                if analysis_metadata(
                    interface.py_obj,
                    "preserves_numeric_format",
                    False,
                ):
                    source = func.value if isinstance(func, Attribute) else args[0]
                    representation = direct_representation(
                        analyzed_numeric_format(source),
                        None,
                    )
            if (
                representation is None
                and attributes.get("operator") is not None
                and return_type.generic_name in {"float", "int"}
            ):
                operands = [*args]
                if isinstance(func, Attribute):
                    operands.insert(0, func.value)
                representation = direct_representation(
                    operation_numeric_format(operands),
                    None,
                )
            apply_representation(call.value_obj, representation)
        return call

    def function_reference(self, function: Function, node: ast.AST):
        if node is self.direct_call_target:
            return None
        target = self.direct_call_target
        if isinstance(target, ast.Attribute) and target.value is node:
            backend = _ACTIVE_ENVIRONMENT.get().name
            if (is_declaration(function.py_obj, backend)
                    and is_declaration(getattr(function.py_obj, target.attr, None), backend)):
                return None
        if not function.inline_decorator and not getattr(
            function.py_obj,
            "__builtin__",
            False,
        ):
            return None

        value = js_metadata(function.py_obj, "value")
        replacement = (
            value.value if value is not None and value.kind == "function" else None
        )
        value_source = (
            value.value if value is not None and value.kind == "source" else None
        )
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

        if replacement is not None and is_js_enabled(replacement) is not True:
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
                defer_unselected_imports=self.module.defer_unselected_imports,
                definition_filter=self.module.definition_filter,
                library_mappings=self.module.library_mappings,
                backend=self.module.backend,
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

    def inline_class_reference(self, value: Class, node: ast.AST) -> None:
        if (
            self.in_type_annotation
            or node is self.direct_call_target
            or not is_inline_class(value.py_obj)
        ):
            return
        definition = self.module.context.sources.definition_span(value.py_obj)
        secondary = (
            (Label(definition, "inline class defined here"),)
            if definition is not None
            else ()
        )
        self.fail(
            node,
            DiagnosticCode.INLINE_FUNCTION_VALUE,
            f"Inline class {value.name!r} cannot be used as a value",
            help=(
                "Use inline classes only as direct call targets. Define an "
                "ordinary class when runtime class identity is required."
            ),
            secondary=secondary,
        )

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
        representation_bindings=None,
    ):
        def expected_type(pattern):
            result = substitute_type_variables(pattern, type_bindings)
            if isinstance(pattern, CallableClass) and representation_bindings:
                # Callable types carry their ABI formats as well as their
                # nominal types. Substitute both before compatibility checks.
                result.parameter_representations = (
                    tuple(substitute_representation_variables(item, declared, representation_bindings)
                          for item, declared in zip(pattern.parameter_types,
                                                    pattern.parameter_representations
                                                    or (None,) * len(pattern.parameter_types), strict=True))
                    if pattern.parameter_types is not None else None
                )
                result.return_representation = substitute_representation_variables(
                    pattern.return_type, pattern.return_representation, representation_bindings,
                )
            return result

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
                expected = expected_type(parameter.annotation.obj)
            elif function.vararg is not None:
                parameter = function.vararg
                expected = expected_type(iterable_item_type(parameter.annotation.obj))
            else:
                continue
            self.validate_call_argument(
                node.args[index],
                function,
                parameter.arg,
                expected,
                argument,
            )
            runtime_methods.extend(
                self.argument_protocol_methods(expected, argument)
            )
            # Retain the source identity. Iteration selects mapping keys;
            # replacing an argument with keys() here loses truth and identity.

        for source, keyword in zip(node.keywords, keywords, strict=True):
            if keyword.arg is None:
                continue
            parameter = parameters.get(keyword.arg)
            if parameter is None:
                if function.kwarg is None:
                    continue
                parameter = function.kwarg
                expected = expected_type(parameter.annotation.obj.generic_types["V"])
            else:
                expected = expected_type(parameter.annotation.obj)
            self.validate_call_argument(
                source.value,
                function,
                parameter.arg,
                expected,
                keyword.value,
            )
            runtime_methods.extend(
                self.argument_protocol_methods(expected, keyword.value)
            )
        return tuple(dict.fromkeys(runtime_methods))

    @staticmethod
    def argument_protocol_methods(expected_type, value):
        if isinstance(analyzed_value_object(value), Function):
            return ()
        methods = []
        actual_members = get_type_members(analyzed_value_type(value))
        if uses_iterable_protocol(expected_type, value):
            for member in actual_members:
                protocol = iterable_protocol(member)
                if protocol is not None:
                    methods.extend(protocol.methods)
        for expected_member in get_type_members(expected_type):
            if expected_member.generic_name == "Iterator":
                for actual_member in actual_members:
                    protocol = iterable_protocol(actual_member, iterator=True)
                    if protocol is not None:
                        methods.extend(protocol.methods)
                        methods.extend(cursor_protocol_methods(actual_member))
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
                expected_type,
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
        expected = describe_type(expected_type)
        actual = describe_type(actual_type)
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
        expected_type,
        value,
    ):
        expected = callable_member(expected_type)
        if any(member is not expected and is_call_argument_compatible(member, value)
               for member in get_type_members(expected_type)):
            # A union is a choice of contracts. Opaque object/callable arms
            # accept function values without requiring their typed signature.
            return
        callable_name = function.name if function is not None else "Callable"
        if len(methods := getattr(value, "union_functions", ())) > 1:
            # Each runtime alternative must implement the promised contract.
            # Reuse the ordinary path, including variadic/async handling and
            # definition labels, rather than treating the first method as proof.
            for method in methods:
                self.validate_callable_argument(source, function, parameter, expected, Name(method))
            return
        callable_function = value.obj if isinstance(value.obj, Function) else None
        if isinstance(value, ast.Lambda):
            parameter_types = value.parameter_types
            return_type = value.return_type
            is_async = False
            accepts_expected_count = expected.parameter_types is None or (
                expected.minimum_arguments == len(parameter_types) == len(expected.parameter_types)
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
                    and required_count <= expected.minimum_arguments
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
            if return_type is None:
                raise DependencyError(callable_function)
            is_async = callable_function.is_async
        expected_return = expected.return_type
        if is_async:
            if not any(
                isinstance(member, Class) and member.generic_name == "Awaitable"
                for member in get_type_members(expected_return)
            ):
                self.fail(
                    source,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Argument {parameter!r} to {callable_name} cannot be async",
                    help="Pass a synchronous callable or expect an Awaitable result.",
                )
            if isinstance(expected_return, Class):
                expected_return = expected_return.generic_types["T"]
            else:
                awaitable = BUILTINS.search("Awaitable")
                assert isinstance(awaitable, GenericClass)
                return_type = awaitable(return_type)
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
                    f"Argument {parameter!r} to {callable_name} expects a callable "
                    f"that accepts {expected_count} positional {argument_label}",
                    help="Use a callable with the annotated parameter shape.",
                    secondary=secondary,
                )
            dispatch = (
                js_metadata(callable_function.py_obj, "dispatch")
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
                        f"Callable argument {parameter!r} to {callable_name} accepts "
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
                f"Callable argument {parameter!r} to {callable_name} returns "
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
            collection_type = receiver.cls if isinstance(receiver, Instance) else receiver
        else:
            if item_of >= len(args):
                return ()
            collection_type = analyzed_value_type(args[item_of])
        if (set(method_names) <= {"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"}
                and function.name in {"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"}
                and getattr(collection_type, "generic_name", None) in {"list", "tuple", "dict", "set", "frozenset"}):
            # Mapping equality compares values too, not only iterated keys.
            methods = []
            for value_type in (collection_type, *(analyzed_value_type(arg) for arg in args)):
                # Set ordering compares members for equality, never ordering.
                # The other operand may itself be an application object whose
                # reflected ordering method must remain reachable, however.
                for member in get_type_members(value_type):
                    names = (("__eq__",) if any(is_builtin_class(member, kind)
                             for kind in ("set", "frozenset")) else method_names)
                    methods.extend(runtime_dunder_methods(member, *names))
            return tuple(dict.fromkeys(methods))
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
        if isinstance(value_type, Instance) and getattr(value_type.cls, "generic_name", None) == "type":
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
            if value_type.name == "dict" and value_type.container.scope.is_builtins:
                return BUILTINS.search("dict")(object_type, object_type)
            if value_type.name in ("list", "set", "frozenset") and value_type.container.scope.is_builtins:
                return BUILTINS.search(value_type.name)(object_type)
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"isinstance() does not support unsubscripted {value_type.name!r}",
                help="Test against a concrete runtime class.",
            )
        if not isinstance(value_type, Class):
            self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                      "isinstance() requires a runtime class target")
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
        current_type = analyzed_value_type(self.guard_value(self.visit(value_node), preserve_local=True))
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
            # A structural annotation also admits unrelated implementations.
            # Failing its nominal class check does not eliminate that storage
            # arm; only object membership is guaranteed for every inhabitant.
            or (getattr(getattr(member, "py_cls", None), "__pyjs_structural__", False)
                and not any(target is BUILTINS.search("object") for target in target_types))
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
        value_type = analyzed_value_type(self.guard_value(self.visit(test), preserve_local=True))
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
        return self.child_visitor(LocalScope(narrowed.scope))

    def child_visitor(self, scope):
        visitor = type(self)(self.func, scope)
        visitor.assignment_scope = self.assignment_scope
        visitor.written_names = self.written_names
        visitor.deferred_parent = self.deferred_parent
        visitor.loop_break_collectors = self.loop_break_collectors
        visitor.pending_finally_breaks = self.pending_finally_breaks
        visitor.flow_widenings = self.flow_widenings
        visitor.pending_flow_widenings = self.pending_flow_widenings
        visitor.in_exception_handler = self.in_exception_handler
        return visitor

    def merge_branch_declarations(self, source, *visitors):
        names = dict.fromkeys(
            name for visitor in visitors for name in visitor.scope.names
        )
        for name in names:
            value_type = None
            branch_values = []
            for visitor in visitors:
                value = visitor.scope.names.get(name)
                if value is None:
                    try:
                        value = visitor.scope.parent.lookup(name)
                    except NameError:
                        pass
                if isinstance(value, Instance):
                    branch_values.append(value)
                    value_type = merge_return_types(value_type, value.cls)
            if value_type is not None:
                typed_representations = tuple(
                    (value.cls, value.representation) for value in branch_values
                )
                has_representation_conflict = representations_conflict(
                    typed_representations
                )
                if has_representation_conflict and inconsistent_numeric_formats(
                    branch_values
                ):
                    self.fail(
                        source,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Branches assign incompatible numeric representations to {name!r}",
                        help=(
                            "Use an explicit fixed-width annotation to convert every "
                            "branch, or keep every branch as an ordinary Python number."
                        ),
                    )
                if has_representation_conflict and mixed_array_formats(branch_values):
                    self.fail(
                        source,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Branches assign incompatible array layouts to {name!r}",
                        help=(
                            "Use one StaticArray type in every branch, or use "
                            "ordinary lists in every branch."
                        ),
                    )
                if has_representation_conflict:
                    self.fail(
                        source,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Branches assign incompatible nested representations "
                        f"to {name!r}",
                        help=(
                            "Use one represented type for each runtime value type, "
                            "or add an explicit conversion."
                        ),
                    )
                value = value_type(name, self.scope, self.func)
                try:
                    declared = self.declared_local(name)
                except NameError:
                    pass
                else:
                    if isinstance(declared, Instance) and declared.storage_declaration.has_declared_type:
                        value.storage_binding = declared.storage_declaration
                apply_representation(
                    value,
                    merged_representation(value_type, typed_representations),
                )
                self.scope.add(value)

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
            if (
                body_falls_through
                and (initialized := self.initialized_optional(analyzed))
                is not None
            ):
                return self.narrow(*initialized)
            return self

        if body_falls_through:
            source_branch = source.body
            analyzed_branch = analyzed.body
        else:
            source_branch = source.orelse
            analyzed_branch = analyzed.orelse

        # A condition describes entry to a branch, not its outgoing state.
        # Apply the same write check to truthiness, isinstance, negation and
        # compound guards, rather than only direct None identity tests.
        visitor = self
        for value_node, value_type in analyzed.condition_narrowings[body_falls_through]:
            if self.branch_initializes_optional(
                analyzed_branch, value_node, value_type, True
            ):
                visitor = visitor.narrow(value_node, value_type)

        narrowing = analyzed.optional_narrowing
        if narrowing is not None:
            value_node, value_type, non_none_when_true = narrowing
            # The initially absent path may establish presence by assignment.
            if self.branch_initializes_optional(
                analyzed_branch, value_node, value_type,
                body_falls_through == non_none_when_true,
            ):
                visitor = visitor.narrow(value_node, value_type)

        if (
            len(source_branch) == 1
            and len(analyzed_branch) == 1
            and isinstance(source_branch[0], ast.If)
            and isinstance(analyzed_branch[0], ast.If)
        ):
            return visitor.narrow_after_if(source_branch[0], analyzed_branch[0])
        return visitor

    def initialized_optional(self, analyzed: ast.If):
        narrowing = analyzed.optional_narrowing
        if narrowing is None:
            return None
        value_node, value_type, non_none_when_true = narrowing
        none_branch = analyzed.orelse if non_none_when_true else analyzed.body
        present_branch = analyzed.body if non_none_when_true else analyzed.orelse
        if (self.branch_initializes_optional(none_branch, value_node, value_type, False)
                and self.branch_initializes_optional(present_branch, value_node, value_type, True)):
            return value_node, value_type
        return None

    @staticmethod
    def branch_initializes_optional(statements, target_node, expected, initialized):
        # Both live paths must establish presence. A nested/conditional write
        # invalidates this simple proof; a subsequent direct assignment can
        # establish it again. Do not infer the entire join from the None arm.
        target_name = ast.unparse(target_node)
        for statement in statements:
            if isinstance(statement, UnpackAssignment):
                initialized = InferenceVisitor.branch_initializes_optional(
                    statement.assignments, target_node, expected, initialized
                )
                continue
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            elif isinstance(statement, ast.Assign):
                targets = statement.targets
            else:
                targets = ()
            assigned = []
            if targets and statement.value is not None:
                for target in targets:
                    assigned.extend(
                        value_type for leaf, value_type, _ in InferenceVisitor.assigned_target_layouts(
                            target, analyzed_value_type(statement.value))
                        if ast.unparse(leaf) == target_name
                    )
            if assigned:
                initialized = is_return_type_compatible(expected, assigned[-1])
                # object includes None, even without an explicit union member.
                # Neither it nor NoneType can establish a presence proof.
                if (any(member.container.scope.is_builtins and member.name in {"NoneType", "object"}
                        for member in get_type_members(assigned[-1]))
                        and not any(member is BUILTINS.search("NoneType") for member in get_type_members(expected))):
                    initialized = False
            elif any(target_name == (name := ast.unparse(node)) or target_name.startswith(name + ".")
                     for node in InferenceVisitor.written_targets([statement])):
                initialized = False
        return initialized

    @staticmethod
    def assigned_target_layouts(target, value_type, representation=None):
        if not isinstance(target, (ast.Tuple, ast.List)):
            yield target, value_type, representation
        elif isinstance(value_type, Class):
            if value_type.generic_name == "tuple":
                item_types = list(value_type.generic_types.values())
                formats = representation.arguments if representation is not None else (None,) * len(item_types)
                if value_type.tuple_variadic:
                    item_types *= len(target.elts)
                    formats *= len(target.elts)
            elif value_type.generic_name == "list":
                item_types = [value_type.generic_types["V"]] * len(target.elts)
                item = representation.item_representation if representation is not None else None
                formats = (item,) * len(target.elts)
            else:
                return
            for item, item_type, item_format in zip(target.elts, item_types, formats, strict=True):
                yield from InferenceVisitor.assigned_target_layouts(item, item_type, item_format)

    @staticmethod
    def written_targets(statements):
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef, ast.Lambda, ast.ListComp,
                                      ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                continue
            if isinstance(statement, (ast.Name, ast.Attribute)) and isinstance(
                statement.ctx, (ast.Store, ast.Del)
            ):
                yield statement
            yield from InferenceVisitor.written_targets(ast.iter_child_nodes(statement))

    def statement_writes(self, node):
        """Source write targets shared by flow visitors within one inference attempt."""
        cached = self.written_names.get(node)
        if cached is not None:
            return cached
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda, ast.ListComp,
                             ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            result = frozenset()
        elif isinstance(node, ast.Name):
            result = frozenset((node.id,)) if isinstance(node.ctx, (ast.Store, ast.Del)) else frozenset()
        else:
            names = set()
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                names.add(ast.unparse(node))
            for child in ast.iter_child_nodes(node):
                names.update(self.statement_writes(child))
            result = frozenset(names)
        self.written_names[node] = result
        return result

    def written_bindings(self, statements):
        """Visible flow bindings affected by explicit writes, including receiver replacement."""
        written = set().union(*(self.statement_writes(statement) for statement in statements))
        if not written:
            return {}
        names = {}
        scope = self.scope
        while isinstance(scope, LocalScope):
            for name in scope.names:
                target = name
                while target:
                    if target in written:
                        names.setdefault(name, None)
                        break
                    target = target.rpartition(".")[0]
            scope = scope.parent
        return {name: self.scope.lookup(name) for name in names}

    def written_narrowings(self, statements):
        # Without an overriding flow scope or a narrowed alias, visible bindings
        # are their own declarations and cannot carry a narrower proof.
        scope = self.scope
        while isinstance(scope, LocalScope) and not scope.names:
            scope = scope.parent
        if (isinstance(scope, LocalScope) and not isinstance(scope.parent, LocalScope)
                and all(getattr(value, "narrowed_from", None) is None for value in scope.names.values())):
            return {}
        bindings = {}
        for name, current in self.written_bindings(statements).items():
            declared = self.declared_local(name)
            while getattr(declared, "narrowed_from", None) is not None:
                declared = declared.narrowed_from
            if not isinstance(declared, Instance):
                continue
            if (isinstance(current, Instance) and current.cls is declared.cls
                    and current.representation == declared.representation):
                continue
            bindings[name] = current, declared
        return bindings

    def invalidate_written_narrowings(self, statements, only=None):
        visitor = self
        for name, (_, declared) in self.written_narrowings(statements).items():
            if only is not None and name not in only:
                continue
            if visitor is self:
                visitor = self.child_visitor(LocalScope(self.scope))
            # Copy the declaration, including its full representation. Projecting
            # from the narrowed type would lose the other union members' formats.
            visitor.scope.add(declared.reassign(name, visitor.scope, self.func))
        return visitor

    @staticmethod
    def writes_preserve_binding(node, name, expected, representation):
        """Prove both entry type and layout from actual writes, not syntax."""
        if hasattr(node, "flow_statements"):
            return all(InferenceVisitor.writes_preserve_binding(child, name, expected, representation)
                       for child in node.flow_statements)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
                             ast.GeneratorExp)):
            return True

        def compatible(target, value_type, actual):
            target_name = target.arg if isinstance(target, ast.arg) else ast.unparse(target)
            if name.startswith(target_name + "."):
                return False  # Replacing a receiver invalidates field proofs.
            if name != target_name:
                return True
            return is_return_type_compatible(expected, value_type) and not representations_conflict(
                ((expected, representation), (value_type, actual))
            ) and (
                any(item is BUILTINS.search("NoneType") for item in get_type_members(expected))
                or not any(item.container.scope.is_builtins and item.name in {"NoneType", "object"}
                           for item in get_type_members(value_type))
            )

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value is None:
                return True
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            return all(compatible(leaf, value_type, actual) for target in targets
                       for leaf, value_type, actual in InferenceVisitor.assigned_target_layouts(
                           target, analyzed_value_type(node.value), analyzed_representation(node.value)))
        if isinstance(node, ast.For):
            protocol = analyzed_iterable_protocol(node.iter)
            if protocol is None or not all(
                compatible(leaf, value_type, actual)
                for leaf, value_type, actual in InferenceVisitor.assigned_target_layouts(
                    node.target, protocol.item_type, protocol.item_representation)
            ):
                return False
            return all(InferenceVisitor.writes_preserve_binding(child, name, expected, representation)
                       for child in (*node.body, *node.orelse))
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            target_name = ast.unparse(node)
            return name != target_name and not name.startswith(target_name + ".")
        return all(InferenceVisitor.writes_preserve_binding(child, name, expected, representation)
                   for child in ast.iter_child_nodes(node))

    def exception_entry(self, statements, analyzed_statements):
        # An exception can leave after any write in the protected region. Its
        # handlers need that conservative state; the region's first statement
        # does not (there is no exception backedge into the try body).
        # Else/finally joins also use this state when their original visitor
        # does not retain writes made in child flow scopes.
        invalid = {
            name for name, (current, _) in self.written_narrowings(statements).items()
            if not all(self.writes_preserve_binding(item, name, current.cls, current.representation)
                       for item in analyzed_statements)
        }
        return self.invalidate_written_narrowings(statements, only=invalid)

    @staticmethod
    def last_direct_assignment_value(statements, target_node):
        target_name = ast.unparse(target_node)
        for statement in reversed(statements):
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            elif isinstance(statement, ast.Assign):
                targets = statement.targets
            else:
                continue
            if any(ast.unparse(target) == target_name for target in targets):
                return statement.value
        return None

    def visit_body(self, statements):
        body = []
        narrow_visitor = self
        for statement in statements:
            if isinstance(statement, (ast.For, ast.While)):
                narrow_visitor = narrow_visitor.invalidate_written_narrowings(
                    [statement], only=self.flow_widenings.get(flow_source_site(statement), set()))
            entry_narrowings = narrow_visitor.written_narrowings([statement])
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
            if isinstance(statement, ast.If):
                # Preserve entry proofs before branch writes change bindings.
                # Re-reading obj.field after the branch sets obj=None would
                # incorrectly diagnose the already-valid condition itself.
                condition_narrowings = (
                    narrow_visitor.get_condition_narrowings(statement.test, False),
                    narrow_visitor.get_condition_narrowings(statement.test, True),
                )
                optional_narrowing = narrow_visitor.get_none_identity_narrowing(statement.test)
            elif isinstance(statement, ast.Assert):
                assertion_narrowings = narrow_visitor.get_condition_narrowings(statement.test, True)
            stmt = narrow_visitor.visit(statement)
            analyzed_statements = stmt if isinstance(stmt, list) else [stmt]
            # An exited branch's write cannot reach the next statement. Loops
            # and try statements keep checking every write, because a continue
            # reaches the next iteration and a finally block runs after return.
            reaching_next = [
                part for item in analyzed_statements
                for part in statement_parts_reaching_next(item)
            ] if entry_narrowings else []
            preserved = {
                name: current for name, (current, _) in entry_narrowings.items()
                if all(self.writes_preserve_binding(item, name, current.cls, current.representation)
                       for item in reaching_next)
            }
            if isinstance(statement, (ast.For, ast.While)):
                invalid = entry_narrowings.keys() - preserved.keys()
                if invalid:
                    # Keep collecting independent sites in this provisional
                    # pass, then discard its analysis/IR together. Stopping at
                    # the first site would restart the function once per loop.
                    self.pending_flow_widenings.setdefault(flow_source_site(statement), set()).update(invalid)

            narrow_visitor = narrow_visitor.invalidate_written_narrowings([statement])
            if preserved:
                narrow_visitor = narrow_visitor.child_visitor(LocalScope(narrow_visitor.scope))
                for name, value in preserved.items():
                    narrow_visitor.scope.add(value.reassign(name, narrow_visitor.scope, self.func))
            if isinstance(statement, ast.If):
                stmt.condition_narrowings = condition_narrowings
                stmt.optional_narrowing = optional_narrowing
                narrow_visitor = narrow_visitor.narrow_after_if(statement, stmt)
            elif isinstance(statement, ast.Assert):
                # Only the successful edge continues. Keep the assertion itself
                # (including runtime checks), and do not retain a proof invalidated
                # by a write inside its condition.
                for value_node, value_type in assertion_narrowings:
                    if self.branch_initializes_optional([stmt.test], value_node, value_type, True):
                        narrow_visitor = narrow_visitor.narrow(value_node, value_type)

            if reassignment_target is not None:
                assigned_value = self.last_direct_assignment_value(
                    analyzed_statements,
                    reassignment_target,
                )
                if assigned_value is not None:
                    assigned_type = analyzed_value_type(assigned_value)
                    if isinstance(assigned_type, CallableClass):
                        # A write can install an adapter for the declared
                        # input view: the source may accept extra arguments.
                        # Keep the source's covariant result proof, however;
                        # native callable views project it from the storage ABI.
                        declared = narrow_visitor.declared_local(reassignment_target.id)
                        signature = callable_member(declared.cls)
                        if signature is not None and signature.parameter_types is not None:
                            assigned_type = CallableClass(
                                signature.parameter_types,
                                assigned_type.return_type,
                                signature.super,
                                signature.parameter_representations,
                                assigned_type.return_representation,
                                minimum_arguments=signature.minimum_arguments,
                                required_keywords=signature.required_keywords,
                            )
                    if any(member is BUILTINS.search("object") for member in get_type_members(assigned_type)):
                        declared = narrow_visitor.declared_local(reassignment_target.id)
                        while getattr(declared, "narrowed_from", None) is not None:
                            declared = declared.narrowed_from
                        none_types = [member for member in get_type_members(declared.cls)
                                      if member.name == "NoneType"]
                        # A visible object-valued assignment does not establish
                        # non-nullness. Retain explicit nullable storage/proofs.
                        if none_types:
                            assigned_type = UnionType(types=[*get_type_members(assigned_type), *none_types]).type
                    narrow_visitor = narrow_visitor.narrow(
                        reassignment_target,
                        assigned_type,
                    )
                    # The write proves both type and layout. An erased object's
                    # declaration has no item representation to recover, but its
                    # newly assigned reference still has one (e.g. list[int8]).
                    apply_representation(
                        narrow_visitor.scope.lookup(reassignment_target.id),
                        analyzed_representation(assigned_value),
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

    def apply_literal_type(self, value, expected_type):
        """Apply a late destination type only to fresh literal allocations.

        Field/setter types become available after RHS analysis. Reuse those
        types without revisiting expressions or widening an aliased container.
        Numeric representation normalization remains the normal storage step.
        """
        name = {List: "list", Set: "set", Tuple: "tuple", Dict: "dict"}.get(type(value))
        if name is None:
            return
        expected_type = contextual_collection_type(expected_type, name)
        if expected_type is None:
            return
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
                self.apply_literal_type(
                    item,
                    self.typed_dict_field_type(expected_type, key),
                )
            return expected_type
        if isinstance(value, (List, Set)):
            item_type = expected_type.generic_types["V"]
            items = [(item, item_type) for item in value.elts]
        elif isinstance(value, Tuple):
            members = list(expected_type.generic_types.values())
            if expected_type.tuple_variadic:
                members *= len(value.elts)
            if len(members) != len(value.elts):
                return
            items = list(zip(value.elts, members, strict=True))
        else:
            key_type, item_type = expected_type.generic_types.values()
            items = []
            for key, item in zip(value.keys, value.values, strict=True):
                if key is None:
                    items.append((item, expected_type))
                else:
                    items.extend(((key, key_type), (item, item_type)))
        for item, item_type in items:
            self.apply_literal_type(item, item_type)
        if all(is_call_argument_compatible(item_type, item) for item, item_type in items):
            value.obj = expected_type
            return expected_type

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
        expected_numeric_format = (
            self.annotation_numeric_format(annotation_node)
            if annotation_node is not None
            else None
        )
        expected_representation = (
            self.annotation_representation(annotation_node)
            if annotation_node is not None
            else None
        )
        value = self.visit_contextual_expression(
            value_node,
            expected_type,
            expected_numeric_format,
            expected_representation,
        )
        if declared_type is not None:
            self.apply_literal_type(value, declared_type)

        inferred_type = None
        if isinstance(value.obj, (Class, UnionType)):
            inferred_type = value.obj
        elif isinstance(value.obj, Function):
            inferred_type = callable_value_type(value)
        elif isinstance(value.obj, Instance):
            inferred_type = value.obj.cls

        builtin_class = self.func.cls is not None and self.func.cls.py_obj.__dict__.get(
            "__builtin__", False
        )
        if (
            declared_type is not None
            and inferred_type is not None
            and not builtin_class
            and not is_return_type_compatible(declared_type, inferred_type)
        ):
            expected = describe_type(declared_type)
            actual = describe_type(inferred_type)
            self.fail(
                value_node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"Cannot assign {actual} to a value of type {expected}",
                help=f"Assign a value compatible with {expected}.",
            )

        return AssignmentValue(
            value,
            declared_type,
            inferred_type,
            self.annotation_representation(annotation_node)
            if annotation_node is not None
            else analyzed_representation(value),
        )

    def resolve_assignment_target(self, target, value_type: Class | UnionType, *, value=None):
        if isinstance(target, ast.Attribute):
            source_target = target
            try:
                self.assignment_target = target
                try:
                    target = self.visit(target)
                finally:
                    self.assignment_target = None
            except NameError:
                # An unresolved initializer must reach the dependency scheduler,
                # not this fallback for declaring fields on self.
                parent = self.visit(target.value)
                if isinstance(parent.obj, Instance) and parent.obj.name == "self":
                    value_init = parent.obj.cls.init
                    if (
                        value_init is not None
                        and value_init is not self.func
                        and (value_type is None or initializer_declares_field(value_init, target.attr) or
                             parent.obj.cls.find_attrs("initialize", search_bases=False) is not self.func)
                        and not value_init.is_analyzed
                    ):
                        raise DependencyError(value_init) from None
                    attr = value_type(target.attr, parent.obj.scope, parent.obj)
                    apply_representation(
                        attr,
                        parent.obj.cls.field_representations.get(target.attr),
                    )
                    parent.obj.add(attr)
                    target = ast.copy_location(Attribute(
                        attr,
                        value=parent,
                        attr=target.attr,
                    ), source_target)
                else:
                    raise
            if value is not None:
                value_type = self.apply_literal_type(value, target.obj.cls) or value_type
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
                        f"Cannot assign {actual} to {target.attr!r} through {union_name}",
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
                setter_representation = self.merge_typed_representations(
                    source_target,
                    target.obj.cls,
                    tuple(
                        zip(
                            target.property_setter_types,
                            target.property_setter_representations,
                            strict=True,
                        )
                    ),
                    f"Property {target.attr!r} setters",
                )
                apply_representation(target.obj, setter_representation)
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
                # Unannotated fields may specialize in a subclass, but a write
                # to declared storage must retain the parent's type and layout.
                if inherited and not target.obj.storage_declaration.has_declared_type:
                    attr = value_type(target.attr, current_self.scope, current_self)
                    apply_representation(attr, target.obj.representation)
                    current_self.add(attr)
                    target = ast.copy_location(Attribute(
                        attr,
                        value=target.value,
                        attr=target.attr,
                    ), source_target)
                elif not is_return_type_compatible(target.obj.cls, value_type):
                    expected = describe_type(target.obj.cls)
                    actual = describe_type(value_type)
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
                if value is not None and isinstance(existing, Instance):
                    value_type = self.apply_literal_type(value, existing.cls) or value_type
                if (
                    isinstance(existing, Instance)
                    and value_type is not None
                    and not is_return_type_compatible(existing.cls, value_type)
                ):
                    expected = describe_type(existing.cls)
                    actual = describe_type(value_type)
                    self.fail(
                        target,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"Cannot assign {actual} to {target.id!r} of type {expected}",
                        help=(
                            f"Assign a value compatible with {expected} or change "
                            f"the annotation for {target.id!r}."
                        ),
                    )
                return ast.copy_location(Name(self.scope.lookup(target.id), ctx=target.ctx), target), False
            except NameError:
                if not value_type:
                    self.fail(
                        target,
                        DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                        f"Type of {target.id!r} cannot be inferred",
                        help=f"Add an explicit type annotation for {target.id!r}.",
                    )
                declared = value_type(target.id, self.scope, self.func)
                self.scope.add(declared)
                # Declarations after a narrowing live in a child flow scope.
                # Keep their binding on the target for backend storage/boxing.
                return ast.copy_location(Name(declared, ctx=target.ctx), target), True
        elif isinstance(target, ast.Subscript):
            target = ast.Subscript(
                slice=target.slice,
                value=self.visit(target.value),
                lineno=target.lineno,
            )
            return target, False
        else:
            self.fail(
                target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"{type(target).__name__} assignment targets are not supported",
                help="Assign to a name, attribute, or indexed value instead.",
            )

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

    def isolate_branch_assignment(self, target):
        if (
            not isinstance(target, ast.Name)
            or type(self.scope) is not LocalScope
        ):
            return
        try:
            value = self.scope.lookup(target.id)
        except NameError:
            return
        if isinstance(value, Instance):
            if getattr(value, "narrowed_from", None) is not None:
                # The RHS has already used the entry proof. A write targets
                # the declared storage, not that proof's narrower type/format.
                # Replace the binding rather than mutating earlier reads.
                value = self.declared_local(target.id)
                while getattr(value, "narrowed_from", None) is not None:
                    value = value.narrowed_from
            elif target.id in self.scope.names:
                return
            self.scope.add(value.reassign(target.id, self.scope, self.func))

    def capture_assignment_value(self, value):
        # Executable-scope names remain unique across branch visitors and cannot
        # collide with Python identifiers. Deferred bodies have their own scope.
        # Keep local representations so every backend sees the same stored
        # value, including portable numbers.
        scope = self.assignment_scope
        name = f"$assignment{len(scope.names)}"
        value_type = analyzed_value_type(value)
        temporary = value_type(name, scope, self.func)
        apply_representation(temporary, analyzed_representation(value))
        scope.add(temporary)
        assignment = ast.AnnAssign(
            target=Name(temporary, ctx=ast.Store()),
            annotation=value_type.annotation,
            value=value,
            simple=True,
        )
        ast.copy_location(assignment, value)
        return assignment, ast.copy_location(Name(temporary, ctx=ast.Load()), value)

    def subscript_method(self, target, name):
        return ast.copy_location(
            ast.Attribute(value=target.value, attr=name, ctx=ast.Load()), target,
        )

    def visit_Assign(self, node: ast.Assign):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
            target = node.targets[0]
            if isinstance(target.slice, ast.Slice):
                method_name = "__setslice__"
                args = [node.value, *self.slice_parts(target.slice)]
            else:
                method_name = "__setitem__"
                args = [target.slice, node.value]
            method = self.subscript_method(target, method_name)
            call = ast.copy_location(
                ast.Call(func=method, args=args, keywords=[]),
                node,
            )
            if not isinstance(node.value, ast.Constant):
                # Capture after argument typing, before inline expansion can
                # rearrange the operands. Explicit dunder calls keep call order.
                call.assignment_value_index = 0 if isinstance(target.slice, ast.Slice) else 1
            expression = ast.Expr(value=self.visit(call))
            prefix = getattr(call, "assignment_prefix", None)
            return [prefix, expression] if prefix is not None else expression

        contextual_type = None
        contextual_array = None
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                existing = self.declared_local(node.targets[0].id)
            except NameError:
                pass
            else:
                if isinstance(existing, Instance):
                    contextual_type = existing.cls
                    contextual_array = analyzed_array_format(existing)
        assignment_value = self.analyze_assignment_value(
            node.value,
            contextual_type=contextual_type,
        )
        if contextual_array is None:
            self.reject_unpreserved_collection_items(
                node.value,
                assignment_value.node,
            )
        value_representation = analyzed_representation(assignment_value.node)
        unpacking_targets = [
            target for target in node.targets if isinstance(target, (ast.Tuple, ast.List))
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
        if len(node.targets) > 1:
            # Python stores left-to-right and evaluates the RHS once, even if
            # a target setter changes another target or the original RHS name.
            prefix, value = self.capture_assignment_value(assignment_value.node)
            assignments = [prefix]
            for target in node.targets:
                assignment = ast.copy_location(
                    ast.Assign(targets=[target], value=value), node,
                )
                result = self.visit_Assign(assignment)
                assignments.extend(result if isinstance(result, list) else [result])
            return assignments
        target_values = [(node.targets[0], assignment_value.node)]

        assignments = []
        for target_node, value in target_values:
            self.isolate_branch_assignment(target_node)
            target, is_new_name = self.resolve_assignment_target(
                target_node, assignment_value.storage_type, value=value
            )
            property_target = bool(getattr(target, "property_setters", ()))
            target_value = (
                analyzed_value_object(target)
                if hasattr(target, "obj")
                else self.scope.lookup(target.id)
            )
            if value is assignment_value.node and property_target:
                value = self.normalize_stored_value(
                    target_node,
                    value,
                    target_value.representation,
                    target_value.cls,
                )
            declared_storage = isinstance(target_value, Instance) and (
                target_value.has_declared_type
                or isinstance(target_value.cls, UnionType) and target_value.representation is not None
            )
            if (
                isinstance(target_value, Instance)
                and not declared_storage
                and not property_target
            ):
                apply_representation(target_value, value_representation)
            if value is assignment_value.node and isinstance(target_value, Instance):
                # A represented union keeps the full member map even when
                # this write supplies only one arm (including on parameters).
                if declared_storage:
                    self.reject_static_array_widening(
                        target_node,
                        value,
                        target_value.cls,
                        analyzed_array_format(target_value),
                    )
                    value = self.normalize_numeric_value(
                        value,
                        analyzed_numeric_format(target_value),
                    )
                    value = self.normalize_array_value(
                        value,
                        analyzed_array_format(target_value),
                    )
                    value = self.normalize_stored_value(
                        target_node,
                        value,
                        target_value.representation,
                        target_value.cls,
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
        # Attribute stores need normal per-target type/property checks too.
        # Nested targets must unpack at their turn, after earlier stores.
        if any(isinstance(item, (ast.Subscript, ast.Attribute)) for item in ast.walk(target_node)):
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
        self.apply_unpack_target_representation(
            target,
            analyzed_representation(value),
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

    def apply_unpack_target_representation(self, target, representation) -> None:
        if isinstance(target, ast.Name):
            value = self.scope.lookup(target.id)
            if isinstance(value, Instance):
                if representation is None and value.has_declared_type:
                    return
                apply_representation(value, representation)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            if representation is None:
                # Ordinary values clear an inferred representation just as a
                # scalar assignment does, including nested tuple leaves.
                item_representations = (None,) * len(target.elts)
            elif representation.array is not None and representation.arguments:
                item_representations = representation.arguments * len(target.elts)
            elif representation.array is not None:
                item_representation = direct_representation(
                    representation.array.item_numeric,
                    representation.array.item_array,
                )
                item_representations = (item_representation,) * len(target.elts)
            elif len(representation.arguments) == len(target.elts):
                item_representations = representation.arguments
            elif len(representation.arguments) == 1:
                item_representations = representation.arguments * len(target.elts)
            else:
                return
            for item, item_representation in zip(
                target.elts,
                item_representations,
                strict=True,
            ):
                self.apply_unpack_target_representation(
                    item,
                    item_representation,
                )

    @staticmethod
    def unpack_literal_items(value):
        # A starred source has a runtime length even inside a list literal.
        if isinstance(value, (List, Tuple)) and not any(isinstance(item, ast.Starred) for item in value.elts):
            return value.elts
        return None

    def checked_unpack_value(self, target_node, value_type, value):
        if (
            isinstance(value_type, Class)
            and value_type.generic_name == "list"
        ):
            items = self.unpack_literal_items(value)
            if items is not None:
                if len(items) != len(target_node.elts):
                    self.fail(
                        target_node,
                        DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                        f"cannot unpack {len(items)} values into {len(target_node.elts)} targets",
                        help="Use one target for each statically known value.",
                    )
                return value
            representation = analyzed_representation(value)
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
            set_analyzed_representation(value, representation)
        return value

    def resolve_individual_unpacking_assignment(
        self,
        target: ast.Tuple | ast.List,
        value_type,
        value,
    ):
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
                f"cannot unpack {len(item_types)} values into {len(target.elts)} targets",
                help="Use one target for each statically known value.",
            )

        assignments = []
        representation = analyzed_representation(value)
        if (
            representation is not None
            and representation.array is not None
            and representation.arguments
        ):
            item_representations = representation.arguments * len(item_types)
        elif representation is not None and representation.array is not None:
            item_representation = direct_representation(
                representation.array.item_numeric,
                representation.array.item_array,
            )
            item_representations = (item_representation,) * len(item_types)
        elif representation is not None and len(representation.arguments) == len(
            item_types
        ):
            item_representations = representation.arguments
        elif representation is not None and len(representation.arguments) == 1:
            item_representations = representation.arguments * len(item_types)
        else:
            item_representations = (None,) * len(item_types)
        for index, (item_target, item_type, item_representation) in enumerate(
            zip(
                target.elts,
                item_types,
                item_representations,
                strict=True,
            )
        ):
            item_obj = item_type("$unpack", self.scope, self.func)
            apply_representation(item_obj, item_representation)
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
        literal_items = self.unpack_literal_items(value)
        known_count = len(literal_items) if literal_items is not None else None
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
        literal_value = None
        if literal_items is not None:
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
        source_representation = assignment_value.representation
        if source_representation is not None:
            if (
                source_representation.array is not None
                and source_representation.arguments
            ):
                source_items = source_representation.arguments * (
                    len(literal_value.elts)
                    if isinstance(literal_value, (List, Tuple))
                    else len(target.elts)
                )
            elif source_representation.array is not None:
                item_representation = direct_representation(
                    source_representation.array.item_numeric,
                    source_representation.array.item_array,
                )
                source_items = (item_representation,) * (
                    len(literal_value.elts)
                    if isinstance(literal_value, (List, Tuple))
                    else len(target.elts)
                )
            elif value_type.generic_name == "tuple":
                source_items = source_representation.arguments
            else:
                item_representation = (
                    source_representation.arguments[0]
                    if source_representation.arguments
                    else None
                )
                source_items = (item_representation,) * len(target.elts)
            suffix_start = len(source_items) - after
            if value_type.generic_name == "tuple":
                source_types = tuple(value_type.generic_types.values())
            else:
                source_types = (rest_item_type,) * len(source_items)
            rest_items = tuple(
                zip(
                    source_types[before:suffix_start],
                    source_items[before:suffix_start],
                    strict=True,
                )
            )
            rest_representation = compound_representation(
                arguments=(
                    self.merge_typed_representations(
                        target,
                        rest_item_type,
                        rest_items,
                        "Starred unpacking items",
                    )
                    if rest_items
                    else None,
                )
            )
            transformed_representation = tuple_representation(
                (
                    *source_items[:before],
                    rest_representation,
                    *source_items[suffix_start:],
                )
            )
            set_analyzed_representation(value, transformed_representation)
            if isinstance(literal_value, (List, Tuple)):
                set_analyzed_representation(
                    literal_value,
                    transformed_representation,
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
            self.isolate_branch_assignment(target)
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

        literal_items = self.unpack_literal_items(literal_value)
        if value_type.generic_name == "tuple":
            item_types = list(value_type.generic_types.values())
            known_count = len(item_types)
        else:
            if not root and literal_items is None:
                self.fail(
                    target,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "nested list unpacking requires a statically known length",
                    help="Use a tuple for the nested value or unpack it separately.",
                )
            item_types = [value_type.generic_types["V"]] * len(target.elts)
            known_count = len(literal_items) if literal_items is not None else None
        if known_count is not None and len(target.elts) != known_count:
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                f"cannot unpack {known_count} values into {len(target.elts)} targets",
                help="Use one target for each statically known value.",
            )

        resolved_items = []
        declares_name = False
        assigns_non_name = False
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
        if isinstance(node.target, ast.Subscript):
            self.fail(
                node.target,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "Annotated subscript assignments are not supported",
                help=(
                    "Annotate the container's item type and use a normal "
                    "subscript assignment."
                ),
            )
        storage_representation = self.annotation_representation(node.annotation)
        storage_format = (
            storage_representation.numeric
            if storage_representation is not None
            else None
        )
        storage_array = (
            storage_representation.array
            if storage_representation is not None
            else None
        )
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
            self.validate_compound_representation(
                node.annotation,
                declared_type,
                storage_representation,
            )
            target, is_new_name = self.resolve_assignment_target(
                node.target,
                declared_type,
            )
            target_value = (
                self.scope.lookup(target.id)
                if isinstance(target, ast.Name)
                else analyzed_value_object(target)
            )
            if isinstance(target_value, Instance):
                apply_representation(target_value, storage_representation)
                target_value.has_declared_type = True
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
        assert assignment_value.declared_type is not None
        self.validate_compound_representation(
            node.annotation,
            assignment_value.declared_type,
            storage_representation,
        )
        if storage_array is None:
            self.reject_unpreserved_collection_items(
                node.value,
                assignment_value.node,
            )
        self.reject_static_array_widening(
            node.value,
            assignment_value.node,
            assignment_value.declared_type,
            storage_array,
        )
        assignment_value.node = self.normalize_numeric_value(
            assignment_value.node,
            storage_format,
        )
        assignment_value.node = self.normalize_array_value(
            assignment_value.node,
            storage_array,
        )
        assignment_value.node = self.normalize_stored_value(
            node.value,
            assignment_value.node,
            storage_representation,
            assignment_value.declared_type,
        )
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
                storage_representation=storage_representation,
            )
        target, is_new_name = self.resolve_assignment_target(
            node.target, assignment_value.storage_type
        )
        target_value = (
            self.scope.lookup(target.id)
            if isinstance(target, ast.Name)
            else analyzed_value_object(target)
        )
        if isinstance(target_value, Instance):
            apply_representation(target_value, storage_representation)
            target_value.has_declared_type = True
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
        target = self.visit(node.target)
        if analyzed_array_format(target) is not None:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Static arrays do not support whole-array augmented assignment",
                help="Assign individual items or create another static array.",
            )
        write_target = copy(node.target)
        prefixes = []
        if isinstance(write_target, (ast.Attribute, ast.Subscript)):
            # Unlike ordinary assignment, augmented assignment resolves its
            # receiver (and index) before reading the old value and the RHS.
            receiver = self.visit(node.target.value)
            # Class names (including cls) have no evaluation side effects.
            # Reifying them as type[T] locals loses static class-field lookup.
            if not (isinstance(receiver, Name) and isinstance(receiver.obj, Class)):
                prefix, write_target.value = self.capture_assignment_value(receiver)
                prefixes.append(prefix)
            if isinstance(write_target, ast.Subscript):
                if isinstance(write_target.slice, ast.Slice):
                    write_target.slice = copy(write_target.slice)
                    for part in ("lower", "upper", "step"):
                        bound = getattr(write_target.slice, part)
                        if bound is not None:
                            prefix, captured = self.capture_assignment_value(self.visit(bound))
                            prefixes.append(prefix)
                            setattr(write_target.slice, part, captured)
                else:
                    prefix, write_target.slice = self.capture_assignment_value(
                        self.visit(node.target.slice),
                    )
                    prefixes.append(prefix)
            # Narrowed field facts are keyed by their source access path. The
            # captured receiver is an alias, so its read needs the same fact;
            # store validation still checks the field's declared type.
            try:
                narrowed = self.scope.lookup(ast.unparse(node.target))
            except NameError:
                pass
            else:
                if isinstance(narrowed, Instance):
                    self.scope.add(narrowed.reassign(
                        ast.unparse(write_target), self.scope, self.func,
                    ))
        read_target = copy(write_target)
        read_target.ctx = ast.Load()
        bin_op_value = ast.BinOp(
            left=read_target,
            op=node.op,
            right=node.value,
        )
        ast.copy_location(bin_op_value, node)
        # Preserve the in-place protocol intent for backends that distinguish
        # __iadd__ (and peers) from ordinary binary operators after lowering.
        bin_op_value.augmented = True
        assignment = ast.copy_location(
            ast.Assign(targets=[write_target], value=bin_op_value), node,
        )
        result = self.visit_Assign(assignment)
        return prefixes + (result if isinstance(result, list) else [result])

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
                method = self.subscript_method(target, method_name)
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

    def resolve_implicit_attribute(self, node, value):
        return analyzed_value_type(value).find(node.attr)

    def visit_Attribute(self, node: ast.Attribute):
        value = self.visit(node.value)
        value_object = analyzed_value_object(value)
        if isinstance(value_object, Class) and issubclass(value_object.py_cls, enum.Enum):
            member = value_object.py_cls.__members__.get(node.attr)
            if member is not None:
                if not isinstance(node.ctx, ast.Load):
                    self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX, "Enum members are read-only")
                # EnumType redirects class access to the member, but instance
                # access still resolves the inherited scalar method (for
                # example Label.upper.upper()). Do not replace that method
                # in the shared class/instance attribute namespace.
                constant = value_object(node.attr, value_object.scope, value_object,
                                        value=member, is_const=True)
                return Attribute(constant, value=value, attr=node.attr, ctx=node.ctx)
        if isinstance(value_object, Function) and isinstance(node.ctx, ast.Load):
            backend = _ACTIVE_ENVIRONMENT.get().name
            member = getattr(value_object.py_obj, node.attr, None)
            if is_declaration(value_object.py_obj, backend) and is_declaration(member, backend):
                # Declaration namespaces (such as chain.from_iterable) contain
                # static APIs, not mutable attributes on a runtime function.
                target = resolve_imported(member, self.module)
                if isinstance(target, Function):
                    return Name(target, runtime_dependency=self.function_reference(target, node))
        if analyzed_array_format(value) is not None and node.attr in {
            "__delitem__",
            "__delslice__",
            "__setslice__",
        }:
            operation = {
                "__delitem__": "item deletion",
                "__delslice__": "slice deletion",
                "__setslice__": "slice assignment",
            }[node.attr]
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Static arrays do not support {operation}",
                help="Assign individual items without changing the array length.",
            )
        value_obj = analyzed_value_object(value)
        if (
            isinstance(value_obj, TypeAliasValue)
            and numeric_format(value_obj.annotation) is not None
        ):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "Runtime access to fixed-width type attributes is not supported",
                help=(
                    "Use fixed-width types in annotations, constructors, and "
                    "instance operations."
                ),
            )
        if isinstance(value_obj, GenericClass):
            descriptor = inspect.getattr_static(value_obj.py_cls, node.attr, None)
            if node is self.direct_call_target and isinstance(descriptor, classmethod):
                # Infer a class method's generics from its call arguments.
                # This symbolic receiver never becomes a runtime class value.
                value_obj = value_obj(*value_obj.type_parameters.values())
                value = Name(value_obj)
            else:
                self.fail(
                    node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "Runtime access to unspecialized generic type attributes "
                    "is not supported",
                    help="Access the attribute through a concrete value instead.",
                )
        union_type = self.receiver_union(value_obj)
        if node.attr in {
            "__getitem__",
            "__slice__",
            "__setitem__",
            "__setslice__",
            "__delitem__",
            "__delslice__",
        }:
            self.reject_union_subscript(node.value, value_obj, node.attr)
        resolution = None
        narrowed_attribute = None
        try:
            if getattr(node, "class_lookup", False):
                # Synthesized implicit protocol calls bypass instance fields and
                # flow-local attribute bindings, but retain normal call analysis.
                if union_type is None:
                    attr = self.resolve_implicit_attribute(node, value)
                else:
                    methods = tuple(member.find(node.attr) for member in union_type.types)
                    resolution = self.resolve_union_method(node, union_type, methods)
                    attr = resolution.methods[0]
            elif node is self.assignment_target:
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
                    if getattr(attr, "narrowed_from", None) is not None:
                        # A flow proof refines a property's result, not the
                        # descriptor access itself. Retain getter identity so
                        # IR lowering does not turn the next read into a field.
                        narrowed_attribute = attr
                        if union_type is None:
                            declared = value_obj.find(node.attr)
                        else:
                            resolution = self.resolve_union_attribute(node, union_type)
                            declared = (resolution.methods[0]
                                        if isinstance(resolution, UnionMethodResolution) else attr)
                        if isinstance(declared, Function) and declared.is_property:
                            attr = declared
                except NameError:
                    if union_type is None:
                        if isinstance(value_obj, Function):
                            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                      f"Runtime function attribute {node.attr!r} is not supported")
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
            if isinstance(value_obj, ModuleAlias) and (
                    node.attr not in value_obj.target.scope.names
                    or not hasattr(value_obj.py_obj, node.attr)):
                self.fail(node, DiagnosticCode.UNDEFINED_ATTRIBUTE,
                          f"Module {ast.unparse(node.value)!r} has no attribute {node.attr!r}")
            value_init = None
            client_initializer = None
            if isinstance(value_obj, Instance):
                value_init = value_obj.cls.find_attrs("__init__")
                client_initializer = value_obj.cls.find_attrs(
                    "initialize",
                    search_bases=False,
                )
            elif isinstance(value_obj, Class):
                value_init = value_obj.find_attrs("__init__")
                client_initializer = value_obj.find_attrs(
                    "initialize",
                    search_bases=False,
                )
            if not isinstance(client_initializer, Function):
                client_initializer = None
            if (
                node is self.assignment_target
                and isinstance(value_obj, Instance)
                and value_obj.name == "self"
                and (value_init is self.func or
                     (client_initializer is self.func and not initializer_declares_field(value_init, node.attr)))
            ):
                # initialize() may add fields, but resets of constructor-owned
                # fields must wait for their original type, including unions.
                raise
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
            if (node is self.assignment_target
                    and isinstance(value_obj, Instance) and value_obj.name == "self"):
                raise
            if isinstance(value_obj, (Instance, Class)):
                numeric = analyzed_numeric_format(value)
                operation = self.PORTABLE_FLOAT_MISSING_METHOD_OPERATIONS.get(
                    node.attr
                )
                if (
                    operation is not None
                    and is_portable_float_format(numeric)
                ):
                    self.fail_portable_float_operation(node, operation)
                cls = value_obj.cls if isinstance(value_obj, Instance) else value_obj
                self.check_opaque_library_attribute(node, cls)
                can_define = isinstance(value_obj, Instance) and not (
                    cls.container.scope.is_builtins
                    or is_native_for(
                        cls.py_obj,
                        _ACTIVE_ENVIRONMENT.get().name,
                    )
                )
                self.module.context.attribute_lookup_error(
                    self.func.source_fragment,
                    node,
                    cls.name,
                    self.attribute_names(value_obj),
                    ast.unparse(node.value),
                    value_init.py_func
                    if can_define and value_init is not None and not is_builtin_method(value_init)
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
        if (
            _ACTIVE_ENVIRONMENT.get().name == "js"
            and isinstance(value_obj, Instance)
            and isinstance(value_obj.cls, Class)
            and is_inline_class(value_obj.cls.py_obj)
            and isinstance(attr, Function)
            and attr.inline_decorator is None
            and not is_native_for(attr.py_obj, "js")
        ):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Inline class method {value_obj.cls.name}.{attr.name} has no "
                "JavaScript implementation",
                help=(
                    "Mark the method @js.inline to lower each call, or "
                    "@js.native when the inline JavaScript value provides it."
                ),
            )
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
        if getattr(node, "class_lookup", False):
            attribute.class_lookup = True
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
                attribute.property_setter_representations = tuple(
                    setter.params[0].representation for setter in setters
                )
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
            representation = self.merge_typed_representations(
                node,
                return_type,
                tuple(
                    (
                        getter.return_type or getter.declared_return_type,
                        getter.return_representation,
                    )
                    for getter in attribute.property_getters
                ),
                f"Property {node.attr!r} getters",
            )
            set_analyzed_representation(attribute, representation)
            if narrowed_attribute is not None:
                attribute.obj = narrowed_attribute
                set_analyzed_representation(attribute, analyzed_representation(narrowed_attribute))
            return attribute
        if isinstance(attr, Function):
            if union_functions:
                # An extracted method must keep the same combined result as a
                # direct union call, rather than inheriting only its first arm.
                result_representation = self.merge_typed_representations(
                    node, union_return_type,
                    ((method.return_type or method.declared_return_type,
                      method.return_representation) for method in union_functions),
                    f"Method {node.attr!r} results",
                )
                if attr.is_async:
                    result_representation = compound_representation(arguments=(result_representation,))
                set_analyzed_representation(attribute, compound_representation(
                    parameters=tuple(getattr(param, "representation", None) for param in attr.params),
                    result=result_representation,
                ))
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
        elif isinstance(attr, Class):
            self.inline_class_reference(attr, node)
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
            self.inline_class_reference(value, node)
            runtime_dependency = runtime_class_dependency(value, self.module)
        return Name(value, id=name, runtime_dependency=runtime_dependency)

    def visit_Starred(self, node: ast.Starred):
        value = self.visit(node.value)
        protocol = self.require_iterable(node.value, value)
        result = Starred(protocol.item_type, value=value)
        set_analyzed_representation(result, protocol.item_representation)
        result.runtime_methods = protocol.methods
        return result

    def tuple_subscript(self, node, value, source_index, argument):
        """Keep syntax and explicit __getitem__ calls on one typed result path."""
        receiver_type = analyzed_value_type(value)
        items = list(receiver_type.generic_types.values())
        index = integer_literal(source_index, allow_bool=True)
        sliced = is_slice_index(argument)
        member = UnionType(types=items).type if items else BUILTINS.search("object")
        if sliced:
            result_type = BUILTINS.search("tuple")(*([member] if items else []), tuple_variadic=bool(items))
        elif dynamic_slice_index(argument):
            sliced_type = BUILTINS.search("tuple")(*([member] if items else []), tuple_variadic=bool(items))
            result_type = UnionType(types=(member, sliced_type)).type
        elif index is not None and -len(items) <= index < len(items):
            result_type = items[index]
        else:
            result_type = member
        getitem = analyzed_value_object(value).find("__getitem__")
        if not getitem.is_analyzed:
            raise DependencyError(getitem)
        [argument] = self.normalize_lowered_method_arguments([source_index], [argument], getitem, value)
        function = Attribute(getitem, value=value, attr="__getitem__")
        if getitem.inline_call is not None:
            result = self.lower_inline_call(node, getitem, function, [argument], [], result_type)
        else:
            value_obj = (result_type("__subscript_result__", self.scope, self.func)
                         if isinstance(result_type, Class) else result_type)
            result = Call(result_type, value_obj=value_obj, func=function, args=[argument], keywords=[])
        representation = analyzed_representation(value)
        item_representation = None
        if representation is not None and representation.arguments:
            if index is not None and -len(representation.arguments) <= index < len(representation.arguments):
                item_representation = representation.arguments[index]
            else:
                tuple_items = tuple(zip(items, representation.arguments, strict=True))
                if representations_conflict(tuple_items):
                    self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "Dynamic tuple index has incompatible item representations",
                              help="Use a literal index or convert equal runtime types to one represented type first.")
                item_representation = merged_representation(member, tuple_items)
        if sliced:
            item_representation = tuple_representation((item_representation,) if items else ())
        elif dynamic_slice_index(argument):
            item_representation = merged_representation(result_type, (
                (member, item_representation),
                (sliced_type, tuple_representation((item_representation,) if items else ())),
            ))
        set_analyzed_representation(result, item_representation)
        return result

    def visit_Subscript(self, node: ast.Subscript):
        slice_node = self.visit(node.slice)
        value = self.visit(node.value)
        receiver_obj = analyzed_value_object(value)
        if isinstance(receiver_obj, GenericClass):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "Runtime use of specialized generic types is not supported",
                help=(
                    "Use specialized generic types in annotations or call "
                    "them directly as constructors."
                ),
            )
        self.reject_union_subscript(node.value, receiver_obj)
        receiver_type = (
            receiver_obj.cls if isinstance(receiver_obj, Instance) else receiver_obj
        )
        if isinstance(slice_node, ast.Slice):
            method = receiver_obj.find("__slice__")
            if not method.is_analyzed:
                raise DependencyError(method)
            slice_node.lower, slice_node.upper, slice_node.step = (
                self.normalize_lowered_method_arguments(
                    (node.slice.lower, node.slice.upper, node.slice.step),
                    (slice_node.lower, slice_node.upper, slice_node.step),
                    method,
                    value,
                )
            )
            assert isinstance(method.return_type, (Class, UnionType))
            result_type = method.return_type
            if isinstance(receiver_type, Class) and receiver_type.generic_name == "tuple":
                item_types = list(receiver_type.generic_types.values())
                parts = (slice_node.lower, slice_node.upper, slice_node.step)
                try:
                    static_parts = tuple(ast.literal_eval(part) for part in parts)
                except TypeError, ValueError:
                    static_parts = None
                if receiver_type.tuple_variadic:
                    pass
                elif static_parts is not None and static_parts[2] != 0:
                    bounds = slice(*static_parts)
                    item_types = item_types[bounds]
                elif item_types:
                    item_types = [UnionType(types=item_types).type]
                tuple_type = BUILTINS.search("tuple")
                assert isinstance(tuple_type, GenericClass)
                result_type = tuple_type(
                    *item_types,
                    tuple_variadic=(
                        bool(item_types)
                        and (receiver_type.tuple_variadic or static_parts is None)
                    ),
                )
            value_obj = result_type
            if isinstance(result_type, Class):
                value_obj = result_type("__slice_result__", self.scope, self.func)
            simple_step = isinstance(
                slice_node.step, Constant
            ) and slice_node.step.value in (None, 1)
            if simple_step:
                dependency_objects = {}
            else:
                dependency_objects = self.inline_dependencies(method, node)
            result = Call(
                result_type,
                value_obj=value_obj,
                func=Attribute(method, value=value, attr="__slice__"),
                args=[slice_node.lower, slice_node.upper, slice_node.step],
                keywords=[],
                dependency_objects=dependency_objects,
            )
            representation = analyzed_representation(value)
            if representation is not None:
                if representation.array is not None:
                    item = (
                        representation.arguments[0]
                        if representation.arguments
                        else direct_representation(
                            representation.array.item_numeric,
                            representation.array.item_array,
                        )
                    )
                    representation = compound_representation(arguments=(item,))
                elif (
                    isinstance(receiver_type, Class)
                    and receiver_type.generic_name == "tuple"
                    and len(representation.arguments) == len(receiver_type.generic_types)
                ):
                    if receiver_type.tuple_variadic:
                        set_analyzed_representation(result, representation)
                        return result
                    parts = (slice_node.lower, slice_node.upper, slice_node.step)
                    try:
                        static_parts = tuple(ast.literal_eval(part) for part in parts)
                    except TypeError, ValueError:
                        tuple_items = tuple(
                            zip(
                                receiver_type.generic_types.values(),
                                representation.arguments,
                                strict=True,
                            )
                        )
                        if representations_conflict(tuple_items):
                            self.fail(
                                node,
                                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                                "Dynamic tuple slice has incompatible item "
                                "representations",
                                help=(
                                    "Use a static slice or convert equal runtime "
                                    "types to one represented type first."
                                ),
                            )
                        representation = tuple_representation(
                            (
                                merged_representation(
                                    UnionType(
                                        types=receiver_type.generic_types.values()
                                    ).type,
                                    tuple_items,
                                ),
                            )
                        )
                    else:
                        representation = tuple_representation(
                            representation.arguments[slice(*static_parts)]
                        )
            if representation is None:
                representation = method.return_representation
            set_analyzed_representation(result, representation)
            return result
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
            result = Subscript(
                value_type,
                value_obj=value_obj,
                slice=slice_node,
                value=value,
            )
            set_analyzed_representation(
                result,
                runtime_annotation_representation(
                    receiver_type.annotations[slice_node.value]
                ),
            )
            return result
        if isinstance(receiver_type, Class) and receiver_type.generic_name == "tuple":
            return self.tuple_subscript(node, value, node.slice, slice_node)
        if isinstance(receiver_type, Class) and receiver_type.generic_name == "dict":
            slice_node = self.normalize_mapping_key(node.slice, value, slice_node)
        try:
            getitem = receiver_obj.find("__getitem__")
        except NameError:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Value does not have a statically known subscript operation",
                help="Narrow or cast the value to a compatible collection type before indexing it.",
            )
        if not getitem.is_analyzed:
            raise DependencyError(getitem)
        signature = getitem
        if getitem.cls is not None and getitem.cls.container.scope.is_builtins and getitem.overloads:
            # Builtin subscripts synthesize calls rather than passing through
            # visit_Call. Select their declared result just like an explicit
            # __getitem__ call (e.g. an index returns an item, a slice a list).
            for overload in getitem.overloads:
                if not overload.signature_analyzed:
                    raise DependencyError(overload)
            if not dynamic_builtin_subscript(getitem, [slice_node]):
                signature = next((overload for overload in getitem.overloads
                                  if self.overload_matches_types(overload, [slice_node], [])), getitem)
        [slice_node] = self.normalize_lowered_method_arguments(
            [node.slice],
            [slice_node],
            signature,
            value,
        )
        result_type = signature.return_type or signature.declared_return_type
        assert isinstance(result_type, (Class, UnionType))
        value_obj = result_type
        if isinstance(result_type, Class):
            value_obj = result_type("__subscript_result__", self.scope, self.func)
        getitem_attribute = Attribute(getitem, value=value, attr="__getitem__")
        if getitem.inline_call is not None:
            return apply_subscript_result_representation(
                self.lower_inline_call(
                    node,
                    getitem,
                    getitem_attribute,
                    [slice_node],
                    [],
                    result_type,
                ),
                value,
                signature.return_representation,
            )
        return apply_subscript_result_representation(
            Call(
                result_type,
                value_obj=value_obj,
                func=getitem_attribute,
                args=[slice_node],
                keywords=[],
            ),
            value,
            signature.return_representation,
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
        call = self.call_node(
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
        if (
            method_name == "__abs__"
            and analysis_metadata(
                method.py_obj,
                "preserves_numeric_format",
                False,
            )
            and (result_format := analyzed_numeric_format(call)) is not None
        ):
            return self.normalize_numeric_value(
                call,
                result_format,
                force=True,
            )
        return call

    @staticmethod
    def overload_accepts_shape(function, node):
        positional_count = len(node.args)
        if function.vararg is None and positional_count > len(function.params):
            return False
        keyword_names = {
            keyword.arg for keyword in node.keywords if keyword.arg is not None
        }
        if function.kwarg is None:
            accepted_keywords = set(function_parameters_by_name(function))
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
        patterns = []
        for index, argument in enumerate(args):
            if isinstance(argument, ast.Starred):
                continue
            pattern = self.call_argument_pattern(function, index)
            if pattern is None:
                return False
            patterns.append((pattern, argument))
            infer_type_variables(pattern, analyzed_value_type(argument), bindings)
        for keyword in keywords:
            pattern = self.call_keyword_pattern(keyword, function)
            if pattern is None:
                return False
            patterns.append((pattern, keyword.value))
            infer_type_variables(
                pattern,
                analyzed_value_type(keyword.value),
                bindings,
            )
        default_type_variables(patterns, function.type_parameters.values(), bindings)
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
    def call_argument_declared_representation(function, index):
        if index < len(function.params):
            return function.params[index].representation
        if function.vararg is None:
            return None
        representation = function.vararg.representation
        return (
            representation.arguments[0]
            if representation is not None and representation.arguments
            else None
        )

    @staticmethod
    def call_keyword_declared_representation(keyword, function):
        if keyword.arg is not None:
            parameters = function_parameters_by_name(function)
            if parameter := parameters.get(keyword.arg):
                return parameter.representation
        if function.kwarg is None:
            return None
        representation = function.kwarg.representation
        return (
            representation.arguments[1]
            if representation is not None and len(representation.arguments) > 1
            else None
        )

    def overload_matches_representations(self, function, args, keywords):
        bindings = {}
        values = []
        for index, argument in enumerate(args):
            if isinstance(argument, ast.Starred):
                continue
            pattern = self.call_argument_pattern(function, index)
            if pattern is None:
                return False
            declared = self.call_argument_declared_representation(function, index)
            actual_type = analyzed_value_type(argument)
            actual = analyzed_representation(argument)
            if not infer_representation_variables(
                pattern,
                actual_type,
                actual,
                bindings,
            ):
                return False
            values.append((pattern, declared, actual))
        for keyword in keywords:
            pattern = self.call_keyword_pattern(keyword, function)
            if pattern is None:
                return False
            declared = self.call_keyword_declared_representation(keyword, function)
            actual_type = analyzed_value_type(keyword.value)
            actual = analyzed_representation(keyword.value)
            if not infer_representation_variables(
                pattern,
                actual_type,
                actual,
                bindings,
            ):
                return False
            values.append((pattern, declared, actual))
        return all(
            substitute_representation_variables(pattern, declared, bindings) == actual
            for pattern, declared, actual in values
        )

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
        representation_bindings = {}
        if (
            signature_function is not None
            and signature_function.cls is not None
            and isinstance(node.func, ast.Attribute)
        ):
            receiver = self.visit(node.func.value)
            receiver_type = analyzed_value_type(receiver)
            infer_type_variables(
                signature_function.cls,
                receiver_type,
                type_bindings,
            )
            infer_representation_variables(
                signature_function.cls,
                receiver_type,
                analyzed_representation(receiver),
                representation_bindings,
            )
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
            if self.lambda_needs_type_bindings(argument, expected_type or pattern):
                deferred_args.append(index)
                continue
            if expected_type is None:
                args[index] = self.visit_call_argument(
                    argument,
                    signature_function,
                    index,
                    type_bindings,
                    representation_bindings,
                )
            else:
                args[index] = self.visit_contextual_expression(
                    argument,
                    expected_type,
                    expected_representation=(
                        callable_signature.parameter_representations[index]
                        if callable_signature.parameter_representations else None
                    ),
                )
        if (dynamic_builtin_subscript(signature_function, args)
                and signature_function.name == "__setitem__" and len(args) == 2
                and isinstance(args[1], (List, Tuple))):
            replacement = args[1]
            item_type = signature_function.cls.generic_types["V"]
            if (not any(isinstance(item, Starred) for item in ast.walk(replacement))
                    and not self.literal_fits_context(replacement, item_type)
                    and all(self.literal_fits_context(item, item_type) for item in replacement.elts)):
                # Item-first inference may type an empty child at the wrong
                # depth. Establish the sole admissible fresh shape before
                # overload matching; borrowed children are never relabeled.
                constructor = BUILTINS.search(analyzed_value_type(replacement).generic_name)
                context = (constructor(*([item_type] * len(replacement.elts)))
                           if isinstance(replacement, Tuple) else constructor(item_type))
                self.apply_literal_type(replacement, context)
        keywords = [None] * len(node.keywords)
        deferred_keywords = []
        for index, keyword in enumerate(node.keywords):
            pattern = self.call_keyword_pattern(keyword, signature_function)
            if self.lambda_needs_type_bindings(keyword.value, pattern):
                deferred_keywords.append(index)
                continue
            keywords[index] = self.visit_call_keyword(
                keyword,
                signature_function,
                type_bindings,
                representation_bindings,
            )
        if deferred_args or deferred_keywords:
            self.infer_call_representation_bindings(
                node,
                signature_function,
                args,
                keywords,
                representation_bindings,
            )
        for index in deferred_args:
            args[index] = self.visit_call_argument(
                node.args[index],
                signature_function,
                index,
                type_bindings,
                representation_bindings,
            )
        for index in deferred_keywords:
            keywords[index] = self.visit_call_keyword(
                node.keywords[index],
                signature_function,
                type_bindings,
                representation_bindings,
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
        if signature_function is not None and any(
            parameter not in type_bindings
            for parameter in signature_function.type_parameters.values()
        ):
            patterns = (
                [(self.call_argument_pattern(signature_function, index), argument)
                 for index, argument in enumerate(args)]
                + [(self.call_keyword_pattern(keyword, signature_function), keyword.value)
                   for keyword in keywords]
            )
            default_type_variables(patterns, signature_function.type_parameters.values(), type_bindings)
        self.infer_call_representation_bindings(
            node,
            signature_function,
            args,
            keywords,
            representation_bindings,
        )
        return args, keywords, type_bindings, representation_bindings

    def infer_call_representation_bindings(
        self,
        node,
        signature_function,
        args,
        keywords,
        representation_bindings,
    ):
        if signature_function is not None:
            for index, argument in enumerate(args):
                if argument is None:
                    continue
                pattern = self.call_argument_pattern(signature_function, index)
                if pattern is None:
                    continue
                if index in self.deferred_call_representation_arguments.get(node, ()):
                    continue
                source = node.args[index]
                if (
                    (
                        _ACTIVE_ENVIRONMENT.get().name == "wgsl"
                        or get_wgsl_decoration(self.func.py_func) is not None
                    )
                    and analyzed_representation(argument) is None
                    and (
                        integer_literal(source) is not None
                        or float_literal(source) is not None
                    )
                ):
                    continue
                argument_obj = analyzed_value_object(argument)
                if (
                    isinstance(argument_obj, Function)
                    and not contains_type_variable(pattern)
                ):
                    continue
                if isinstance(argument_obj, Function) and analysis_metadata(
                    argument_obj.py_obj,
                    "preserves_numeric_format",
                    False,
                ):
                    continue
                if not infer_representation_variables(
                    pattern,
                    callable_value_type(argument),
                    analyzed_representation(argument),
                    representation_bindings,
                ):
                    self.fail(
                        source,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        "Type variable arguments use incompatible representations",
                        help=(
                            "Pass one represented type for each generic type parameter."
                        ),
                    )
            for source, keyword in zip(node.keywords, keywords, strict=True):
                if keyword is None:
                    continue
                pattern = self.call_keyword_pattern(
                    keyword,
                    signature_function,
                )
                if pattern is None:
                    continue
                if (
                    isinstance(analyzed_value_object(keyword.value), Function)
                    and not contains_type_variable(pattern)
                ):
                    continue
                if not infer_representation_variables(
                    pattern,
                    callable_value_type(keyword.value),
                    analyzed_representation(keyword.value),
                    representation_bindings,
                ):
                    self.fail(
                        source.value,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        "Type variable arguments use incompatible representations",
                        help=(
                            "Pass one represented type for each generic type parameter."
                        ),
                    )

    def expand_static_call_keywords(self, node: ast.Call, call_target=None) -> None:
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

    def canonicalize_numeric_dunder_keywords(
        self,
        node: ast.Call,
        func,
        function: Function | None,
    ):
        if (
            function is None
            or function.inline_decorator is None
            or not isinstance(func, Attribute)
            or func.attr not in self.NUMERIC_BINARY_DUNDER_METHODS
            or analyzed_numeric_format(func.value) is None
            or any(isinstance(argument, ast.Starred) for argument in node.args)
        ):
            return
        keywords = {keyword.arg: keyword for keyword in node.keywords}
        while len(node.args) < len(function.params):
            name = function.params[len(node.args)].arg
            keyword = keywords.get(name)
            if keyword is None:
                break
            node.args.append(keyword.value)
            node.keywords.remove(keyword)

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
                    f"Cannot infer type parameter {parameter.name!r} for {function.name}",
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
        if isinstance(value_type, TypeAliasValue):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Type alias {value_type.name!r} cannot be called at runtime",
                help=(
                    "Call the underlying class directly or use the alias only "
                    "in annotations."
                ),
            )
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

    def validate_generic_constructor_shape(
        self,
        node: ast.Call,
        generic: GenericClass,
    ) -> None:
        if (
            generic.init_params is None
            or any(isinstance(argument, ast.Starred) for argument in node.args)
            or any(keyword.arg is None for keyword in node.keywords)
        ):
            return
        parameters = tuple(generic.init_params.values())[1:]
        positional_only = {
            parameter.name
            for parameter in parameters
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        }
        keyword_parameters = {
            parameter.name
            for parameter in parameters
            if parameter.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        }
        accepts_keywords = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
        )
        for keyword in node.keywords:
            if keyword.arg in positional_only and not accepts_keywords:
                self.fail(
                    keyword,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{generic.name}() parameter {keyword.arg!r} is positional-only",
                    help=f"Pass {keyword.arg!r} as a positional argument.",
                )
            if not accepts_keywords and keyword.arg not in keyword_parameters:
                self.fail(
                    keyword,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"{generic.name}() got an unexpected keyword argument "
                    f"{keyword.arg!r}",
                    help=(
                        f"Remove {keyword.arg!r} or pass a parameter accepted "
                        f"by {generic.name}.__init__()."
                    ),
                )
        signature = inspect.Signature(parameters)
        marker = object()
        try:
            signature.bind(
                *([marker] * len(node.args)),
                **{keyword.arg: marker for keyword in node.keywords},
            )
        except TypeError as error:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Invalid {generic.name}() constructor arguments: {error}",
                help=f"Pass arguments accepted by {generic.name}.__init__().",
            )

    @staticmethod
    def prepare_dictionary_call(
        call_target: Class,
        called_function: Function,
        args: list[ast.expr],
        keywords: list[ast.keyword],
    ) -> tuple[tuple[str, ...], frozenset[str]] | None:
        if not js_metadata(call_target.py_obj, "dictionary", False):
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

        # WebIDL None defaults mean absent rather than JavaScript null.
        optional = frozenset(
            property_name(parameter.arg)
            for parameter, default in defaults
            if isinstance(default, ast.Constant) and default.value is None
        )
        keys = tuple(
            [
                property_name(parameter.arg)
                for parameter in called_function.params[: len(args)]
            ]
            + [property_name(keyword.arg) for keyword in keywords]
        )
        return keys, optional

    def validate_numeric_constructor(self, node, numeric, args) -> None:
        """Apply optional target policy to a numeric conversion."""
        self.validate_numeric_format(node, numeric)
        if (
            args
            and numeric.kind == "integer"
            and numeric.domain == "portable"
            and any(member.generic_name == "float" for member in get_type_members(analyzed_value_type(args[0])))
        ):
            source = getattr(args[0], "python_node", args[0])
            literal = float_literal(source)
            if literal is None or not math.isfinite(literal):
                self.fail(
                    node.args[0],
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "fixed-width integer conversion requires a finite float literal",
                    help=(
                        "Validate and convert a dynamic float to int before "
                        "constructing a fixed-width integer."
                    ),
                )
        if not args:
            return
        self.validate_wgsl_integer_literal(node.args[0], args[0], numeric)

    def validate_wgsl_integer_literal(self, source, value, numeric) -> None:
        if (
            numeric is None
            or numeric.domain != "wgsl"
            or numeric.kind != "integer"
            or _ACTIVE_ENVIRONMENT.get().name == "wgsl"
            or is_native_for(self.func.py_func, "wgsl")
        ):
            return
        literal = integer_literal(getattr(value, "python_node", value))
        if literal is None:
            if analyzed_numeric_format(value) is not None:
                return
            if not any(member.generic_name == "int" for member in get_type_members(analyzed_value_type(value))):
                return
            self.fail(
                source,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Dynamic Python integers cannot enter WGSL integer operations",
                help=(
                    "Accept a pyjs.shader integer at this boundary, or use a "
                    "statically representable literal."
                ),
            )
        bits = numeric.bits
        minimum, maximum = numeric.integer_bounds
        if minimum <= literal <= maximum:
            return
        self.fail(
            source,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"{literal} cannot be represented as "
            f"{'i' if numeric.signed else 'u'}{bits} in WGSL",
            help=(
                "Use a representable literal or explicitly convert another "
                "concrete WGSL integer value."
            ),
        )

    def validate_numeric_format(self, node, numeric) -> None:
        if self.numeric_domains is None or numeric.domain in self.numeric_domains:
            return
        target = _ACTIVE_ENVIRONMENT.get().name
        self.fail(
            node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"{numeric.domain} numeric types cannot compile for {target}",
            help=(
                f"Use a portable PyJS numeric type or a {target}-specific "
                "type explicitly."
            ),
        )

    def numeric_binary_result_type(
        self,
        operator: ast.operator,
        operands: tuple[ast.expr, ast.expr],
        default: Class,
    ) -> Class:
        """Return a domain-specific result type for a numeric operator."""
        formats = numeric_formats(operands)
        if (
            isinstance(operator, ast.Div)
            and len(formats) == 1
            and (numeric := formats.pop()).domain == "wgsl"
            and numeric.kind == "integer"
        ):
            return self.scope.search("int")
        return default

    def repeated_tuple(self, node, result, receiver, times):
        receiver_type = analyzed_value_type(receiver)
        if not (
            isinstance(receiver_type, Class)
            and receiver_type.generic_name == "tuple"
        ):
            return result
        tuple_type = BUILTINS.search("tuple")
        assert isinstance(tuple_type, GenericClass)
        count = integer_literal(times, allow_bool=True)
        representation = analyzed_representation(receiver)
        fixed_items = tuple((receiver_type.generic_types or {}).values())
        if not receiver_type.tuple_variadic and not fixed_items:
            result_type = receiver_type
            result_representation = representation
        elif (
            count is not None
            and not receiver_type.tuple_variadic
            and len(fixed_items) * max(count, 0) <= MAX_FIXED_TUPLE_ITEMS
        ):
            count = max(count, 0)
            result_type = tuple_type(*(fixed_items * count))
            arguments = representation.arguments if representation is not None else ()
            result_representation = tuple_representation(arguments * count)
        elif receiver_type.tuple_variadic:
            result_type = receiver_type
            result_representation = representation
        else:
            protocol = self.require_iterable(node, receiver)
            result_type = tuple_type(
                protocol.item_type,
                tuple_variadic=True,
            )
            result_representation = tuple_representation(
                (protocol.item_representation,)
            )
        result.obj = result_type
        result.value_obj = result_type(
            "__tuple_repeat_result__",
            self.scope,
            self.func,
        )
        set_analyzed_representation(result, result_representation)
        return result

    def unbound_sequence_repeat(self, node: ast.Call):
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"__mul__", "__rmul__"}
            and isinstance(node.func.value, ast.Name)
        ):
            return None
        generic = analyzed_value_object(self.visit(node.func.value))
        if not (
            isinstance(generic, GenericClass)
            and generic.name in {"list", "tuple"}
            and generic.container.scope.is_builtins
        ):
            return None
        if not node.args:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{generic.name}.{node.func.attr}() requires a positional receiver",
                help=f"Pass the {generic.name} value as the first argument.",
            )
        receiver = self.visit(node.args[0])
        receiver_type = analyzed_value_type(receiver)
        if not (
            isinstance(receiver_type, Class)
            and receiver_type.generic_name == generic.name
        ):
            self.fail(
                node.args[0],
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{generic.name}.{node.func.attr}() requires a {generic.name} receiver",
                help=f"Pass a {generic.name} value as the first argument.",
            )
        method = ast.copy_location(
            ast.Attribute(
                value=node.args[0],
                attr=node.func.attr,
                ctx=ast.Load(),
            ),
            node.func,
        )
        rewritten = ast.copy_location(
            ast.Call(
                func=method,
                args=node.args[1:],
                keywords=node.keywords,
            ),
            node,
        )
        return self.visit_contextual_expression(
            rewritten,
            self.contextual_types.get(node),
            self.contextual_numeric_formats.get(node),
            self.contextual_representations.get(node),
        )

    def normalize_typed_dict_call(self, node, func, args, receiver_type):
        if func.attr != "__setitem__" or len(args) != 2:
            return
        key = args[0]
        if not isinstance(key, Constant) or not isinstance(key.value, str):
            self.fail(
                node.args[0],
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "TypedDict keys must be string literals",
                help=(
                    "Use a literal key so its field type can be determined "
                    "statically."
                ),
            )
        self.typed_dict_field_type(receiver_type, key)
        args[1] = self.normalize_stored_value(
            node.args[1],
            args[1],
            runtime_annotation_representation(receiver_type.annotations[key.value]),
            receiver_type.field_type(key.value),
        )

    def contextual_subscript_literal(self, node, call):
        """Select a fresh literal's storage context without repeating its effects.

        Snapshot the ordinary RHS before choosing a context. Reconstruct only
        fresh list/tuple nodes; nonliteral children remain the captured values,
        so callbacks run once and borrowed child collections retain identity.
        Ordinary EvaluateOnce/IfExp nodes keep this independent of codegen.
        """
        sources = (call.func.value, *call.args)
        names = []
        for index, source in enumerate(sources):
            semantic = analyzed_value_type(source)
            temporary = semantic(f"$subscript{index}", self.scope, self.func)
            apply_representation(temporary, analyzed_representation(source))
            names.append(Name(temporary, ctx=ast.Load()))
        receiver, index, snapshot = names
        receiver_type = analyzed_value_type(receiver)
        item_type = receiver_type.generic_types["V"]
        represented = analyzed_representation(receiver)
        item_representation = represented.arguments[0] if represented and represented.arguments else None

        def clone(value):
            # Analyzed nodes have typed constructors, unlike ast's pickle/copy
            # protocol. Copy only the node, retaining its resolved declarations.
            result = ast.AST.__new__(type(value))
            vars(result).update(vars(value))
            return result

        def reconstruct(original, saved):
            original_type = analyzed_value_type(original)
            if not same_analyzer_type(original_type, analyzed_value_type(saved)):
                # A fresh parent may have boxed this child into an object/union
                # slot. Its literal position still identifies the original
                # layout; recover it before projecting its captured members.
                saved = StaticCast(original_type, saved)
                set_analyzed_representation(saved, analyzed_representation(original))
            if not isinstance(original, (List, Tuple)):
                return saved
            result = clone(original)
            result.elts = []
            for offset, item in enumerate(original.elts):
                access = self.visit(ast.copy_location(ast.Subscript(
                    value=AnalyzedExpression(saved), slice=ast.Constant(value=offset), ctx=ast.Load()), item))
                result.elts.append(reconstruct(item, access))
            return result

        branches, errors = [], []
        for sliced in (True, False):
            fresh = reconstruct(node.subscript_literal, snapshot)
            try:
                context = item_type
                if sliced:
                    constructor = BUILTINS.search(analyzed_value_type(fresh).generic_name)
                    context = (constructor(*([item_type] * len(fresh.elts)))
                               if isinstance(fresh, Tuple) else constructor(item_type))
                if not self.literal_fits_context(fresh, context):
                    self.fail(node.args[1], DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "Literal replacement does not fit the selected subscript context")
                self.apply_literal_type(fresh, context)
                fresh = (self.normalize_stored_iterable(node.args[1], fresh, item_representation, item_type)
                         if sliced else self.normalize_stored_value(
                             node.args[1], fresh, item_representation, item_type))
            except CompilationError as error:
                # An explicit width can make only one arm admissible. Keep
                # its original value on the other arm for the checked runtime
                # TypeError; never relabel or implicitly change that width.
                errors.append(error)
                fresh = snapshot
            selected = clone(call)
            selected.func = clone(call.func)
            selected.func.value = receiver
            selected.args = [index, fresh]
            selected.runtime_protocols = (*selected.runtime_protocols,
                (analyzed_value_type(index), ("__index__",)),
                (analyzed_value_type(fresh), ("__iter__", "__getitem__")))
            branches.append(selected)
        if len(errors) == 2:
            raise errors[0]
        test = self.visit(ast.copy_location(ast.Call(
            func=AnalyzedExpression(Name(BUILTINS.search("isinstance"))),
            args=[AnalyzedExpression(index), AnalyzedExpression(Name(BUILTINS.search("slice")))],
            keywords=[]), node))
        result_type = analyzed_value_type(call)
        result = IfExp(result_type, result_type, test=test, body=branches[0], orelse=branches[1])
        for source, name in reversed(tuple(zip(sources, names, strict=True))):
            result = EvaluateOnce(result_type, source, result, name.id)
        return ast.copy_location(result, node)

    def literal_fits_context(self, value, expected):
        # A nested empty literal may already have inherited the item context.
        # Its fresh shape can still fit the slice context; borrowed values
        # must retain their actual analyzed type.
        if is_call_argument_compatible(expected, value):
            return True
        if not isinstance(value, (List, Tuple)):
            return False
        context = contextual_collection_type(expected, "list" if isinstance(value, List) else "tuple")
        if context is None:
            return False
        members = tuple(context.generic_types.values())
        if isinstance(value, List) or context.tuple_variadic:
            members *= len(value.elts)
        return len(members) == len(value.elts) and all(
            self.literal_fits_context(child, member)
            for child, member in zip(value.elts, members, strict=True))

    def normalize_list_call(self, node, func, args, receiver_type, members):
        item_representation = members[0] if members else None
        item_type = receiver_type.generic_types["V"]
        if args and dynamic_slice_index(args[0]) and func.attr == "__getitem__":
            return True, merged_representation(UnionType(types=(item_type, receiver_type)).type, (
                (item_type, item_representation),
                (receiver_type, analyzed_representation(func.value)),
            ))
        if len(args) == 2 and dynamic_slice_index(args[0]) and func.attr == "__setitem__":
            # The implementation signature validates V | Iterable[V]. The
            # runtime index selects the arm, but fresh literals still need
            # the same contextual representation as a static item/slice store.
            # Existing aliased values retain their own layout until dispatch.
            replacement = args[1]

            if (isinstance(replacement, (List, Tuple))
                    and not any(isinstance(item, Starred) for item in ast.walk(replacement))
                    and all(self.literal_fits_context(item, item_type) for item in replacement.elts)):
                # A possible slice replacement needs its own nested context,
                # including when the item arm is not admissible at all.
                # Capture its values once; construct in the selected context
                # and leave the other arm to its checked runtime rejection.
                node.subscript_literal = replacement
                return False, None
            # Scalars own copied slots, regardless of their expression shape;
            # keeping an aliased container's layout does not apply to them.
            scalar = all(
                any(is_builtin_class(member, name)
                    for name in ("int", "float", "bool", "str", "bytes", "NoneType"))
                for member in get_type_members(analyzed_value_type(replacement)))
            if scalar or isinstance(replacement, (Constant, UnaryOp, List, Set, Tuple, Dict)):
                if is_call_argument_compatible(item_type, replacement):
                    args[1] = self.normalize_stored_value(node.args[1], replacement,
                                                         item_representation, item_type)
                elif isinstance(replacement, (List, Set, Tuple)):
                    args[1] = self.normalize_stored_iterable(node.args[1], replacement,
                                                            item_representation, item_type)
            return False, None
        if args and is_slice_index(args[0]):
            if func.attr == "__getitem__":
                return True, analyzed_representation(func.value)
            if func.attr == "__setitem__" and len(args) == 2:
                args[1] = self.normalize_stored_iterable(node.args[1], args[1], item_representation, item_type)
                # A broad index-protocol overload can match the scalar V even
                # for a slice (e.g. list[list[int]] receiving list[int]). Keep
                # the actual slice's iterable-of-V contract after normalization.
                expected = BUILTINS.search("Iterable")(item_type)
                if not is_return_type_compatible(expected, analyzed_value_type(args[1])):
                    self.fail(node.args[1], DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "Slice replacement has incompatible item types",
                              help=f"Pass an iterable of {item_type.to_annotation_str()}.")
                return False, None
        result_representation = None
        if func.attr == "__add__" and args:
            receiver_protocol = self.require_iterable(
                node.func.value,
                func.value,
            )
            argument_protocol = self.require_iterable(node.args[0], args[0])
            item_representation = self.merge_typed_representations(
                node,
                item_type,
                (
                    (
                        receiver_protocol.item_type,
                        receiver_protocol.item_representation,
                    ),
                    (
                        argument_protocol.item_type,
                        argument_protocol.item_representation,
                    ),
                ),
                "List concatenation items",
            )
            result_representation = compound_representation(
                arguments=(item_representation,)
            )
        value_index = {
            "__setitem__": 1,
            "append": 0,
            "insert": 1,
        }.get(func.attr)
        if value_index is not None and value_index < len(args):
            args[value_index] = self.normalize_stored_value(
                node.args[value_index],
                args[value_index],
                item_representation,
                item_type,
            )
        elif func.attr in {"__setslice__", "extend"} and args:
            args[0] = self.normalize_stored_iterable(
                node.args[0],
                args[0],
                item_representation,
                item_type,
            )
        return func.attr == "__add__" and bool(args), result_representation

    def normalize_dict_call(
        self,
        node,
        func,
        args,
        keywords,
        receiver_type,
        members,
    ):
        key_representation = members[0] if members else None
        value_representation = members[1] if len(members) > 1 else None
        key_type = receiver_type.generic_types["K"]
        value_type = receiver_type.generic_types["V"]
        result_representation = None
        if func.attr == "__setitem__" and len(args) == 2:
            args[0] = self.normalize_stored_value(
                node.args[0], args[0], key_representation, key_type
            )
            args[1] = self.normalize_stored_value(
                node.args[1], args[1], value_representation, value_type
            )
        elif func.attr == "setdefault" and args:
            args[0] = self.normalize_stored_value(
                node.args[0], args[0], key_representation, key_type
            )
            if len(args) > 1:
                args[1] = self.normalize_stored_value(
                    node.args[1], args[1], value_representation, value_type
                )
        elif func.attr in {"update", "__or__", "__ror__", "__ior__"}:
            if args:
                source_type = analyzed_value_type(args[0])
                if getattr(source_type, "generic_name", None) == "dict":
                    args[0] = self.normalize_stored_mapping(
                        node.args[0],
                        args[0],
                        key_representation,
                        value_representation,
                        key_type,
                        value_type,
                    )
                else:
                    args[0] = self.normalize_stored_iterable(
                        node.args[0],
                        args[0],
                        tuple_representation(
                            (key_representation, value_representation)
                        ),
                        BUILTINS.search("tuple")(key_type, value_type),
                    )
            keywords = [
                ast.keyword(
                    arg=keyword.arg,
                    value=self.normalize_stored_value(
                        source.value,
                        keyword.value,
                        value_representation,
                        value_type,
                    ),
                )
                for source, keyword in zip(node.keywords, keywords, strict=True)
            ]
        elif func.attr == "popitem":
            result_representation = tuple_representation(
                (key_representation, value_representation)
            )
        return (
            args,
            keywords,
            func.attr == "popitem",
            result_representation,
        )

    def normalize_set_call(
        self,
        node,
        func,
        args,
        receiver_type,
        receiver_representation,
        members,
    ):
        item_representation = members[0] if members else None
        item_type = receiver_type.generic_types["V"]
        if func.attr == "add" and args:
            args[0] = self.normalize_stored_value(
                node.args[0], args[0], item_representation, item_type
            )
        operations = {
            "difference",
            "difference_update",
            "intersection",
            "intersection_update",
            "symmetric_difference",
            "symmetric_difference_update",
            "union",
            "update",
            "__or__", "__and__", "__sub__", "__xor__",
            "__ior__", "__iand__", "__isub__", "__ixor__",
        }
        if func.attr not in operations:
            return args, False, None
        args = [
            self.normalize_stored_iterable(
                source,
                argument,
                item_representation,
                item_type,
            )
            for source, argument in zip(node.args, args, strict=True)
        ]
        preserve_result = not func.attr.endswith("_update") and func.attr != "update"
        return args, preserve_result, receiver_representation

    def normalize_collection_call(self, node, func, args, keywords):
        if not isinstance(func, Attribute):
            return args, keywords, False, None
        receiver_type = analyzed_value_type(func.value)
        receiver_representation = analyzed_representation(func.value)
        receiver_array = analyzed_array_format(func.value)
        if func.attr == "__setitem__" and receiver_array is not None:
            if args and is_slice_index(args[0]):
                self.fail(node.args[0], DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "Static arrays do not support slice assignment",
                          help="Assign individual items without changing the array length.")
            item_representation = (
                receiver_representation.arguments[0]
                if receiver_representation is not None
                and receiver_representation.arguments
                else direct_representation(
                    receiver_array.item_numeric,
                    receiver_array.item_array,
                )
            )
            args[1] = self.normalize_representation(
                args[1],
                item_representation,
                next(iter(receiver_type.generic_types.values())),
            )
            return args, keywords, False, None
        members = (
            receiver_representation.arguments
            if receiver_representation is not None
            else ()
        )
        if isinstance(receiver_type, TypedDictClass):
            self.normalize_typed_dict_call(node, func, args, receiver_type)
            return args, keywords, False, None
        # Application methods may have builtin collection names without the
        # builtin's storage or generic parameters (e.g. a class named list).
        if not isinstance(receiver_type, Class) or not receiver_type.container.scope.is_builtins:
            return args, keywords, False, None
        generic_name = getattr(receiver_type, "generic_name", None)
        if generic_name == "list":
            preserve, result = self.normalize_list_call(
                node, func, args, receiver_type, members
            )
            return args, keywords, preserve, result
        if generic_name == "dict":
            return self.normalize_dict_call(
                node, func, args, keywords, receiver_type, members
            )
        if generic_name in {"set", "frozenset"}:
            args, preserve, result = self.normalize_set_call(
                node,
                func,
                args,
                receiver_type,
                receiver_representation,
                members,
            )
            return args, keywords, preserve, result
        return args, keywords, False, None

    def normalize_parameter_value(
        self,
        source,
        argument,
        expected,
        expected_type,
        *,
        representation_aware,
    ):
        if (expected is None and isinstance(expected_type, CallableClass)
                and expected_type.parameter_types is None):
            callback = callable_value_type(argument)
            if isinstance(callback, CallableClass) and callback.return_representation is None:
                # Callable[..., ordinary] may still have represented parameters.
                # Keep that actual ABI instead of treating it as value erasure.
                return argument
        if expected is None:
            argument = self.normalize_float_argument(
                source,
                argument,
                expected_type,
            )
        if (
            not representation_aware
            and expected is None
            and analyzed_representation(argument) is not None
        ):
            self.fail(
                source,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Argument uses a represented value where an ordinary "
                "Python value is required",
                help=(
                    "Convert it to the annotated Python type, or change "
                    "the parameter to the represented type."
                ),
            )
        return self.normalize_representation(argument, expected, expected_type)

    def normalize_function_signature_arguments(
        self,
        node,
        called_function,
        signature_function,
        args,
        keywords,
        type_bindings,
        representation_bindings,
    ):
        assert isinstance(signature_function, Function)
        positional_parameters = signature_function.params
        parameters_by_name = function_parameters_by_name(
            signature_function,
            include_positional_only=True,
        )
        representation_aware_signature = representation_aware_function(
            signature_function
        )
        custom_call_analysis = (
            called_function is not None and called_function.analysis is not None
        )
        accepts_static_arrays = accepts_static_array_argument(signature_function)

        def parameter_representation(parameter):
            return substitute_representation_variables(
                parameter.annotation.obj,
                getattr(parameter, "representation", None),
                representation_bindings,
            )

        def parameter_type(parameter):
            return substitute_type_variables(
                parameter.annotation.obj,
                type_bindings,
            )

        def normalize_expected(
            source,
            argument,
            expected,
            expected_type=None,
        ):
            if custom_call_analysis:
                return argument
            if (expected is None and signature_function.cls is not None
                    and signature_function.cls.generic_name in {"list", "dict", "set", "frozenset"}
                    and signature_function.cls.py_obj.__dict__.get("__builtin__", False)
                    and any(member.generic_name == "Iterator" for member in get_type_members(expected_type))):
                # Specialized collection signatures carry nominal item types;
                # their represented item contract lives on the receiver. The
                # collection pass below validates these storage conversions.
                return argument
            return self.normalize_parameter_value(
                source,
                argument,
                expected,
                expected_type,
                representation_aware=representation_aware_signature,
            )

        def normalize_parameter(source, argument, parameter):
            assert parameter is not None
            return normalize_expected(
                source,
                argument,
                parameter_representation(parameter),
                parameter_type(parameter),
            )

        def normalize_keyword(source, keyword):
            if custom_call_analysis:
                return keyword.value
            parameter = parameters_by_name.get(keyword.arg)
            if parameter is not None:
                return normalize_parameter(source, keyword.value, parameter)
            parameter = signature_function.kwarg
            assert parameter is not None
            expected = parameter_representation(parameter)
            item_representation = (
                expected.arguments[1]
                if expected is not None and len(expected.arguments) > 1
                else None
            )
            item_type = parameter_type(parameter).generic_types["V"]
            return normalize_expected(
                source,
                keyword.value,
                item_representation,
                item_type,
            )

        for index, argument in enumerate(args):
            if index >= len(positional_parameters):
                break
            parameter = positional_parameters[index]
            if not accepts_static_arrays:
                self.reject_static_array_widening(
                    node.args[index],
                    argument,
                    parameter.annotation.obj,
                    analyzed_array_format(parameter),
                )
        vararg_representation = (
            parameter_representation(signature_function.vararg)
            if signature_function.vararg is not None
            else None
        )
        vararg_item_representation = (
            vararg_representation.arguments[0]
            if vararg_representation is not None
            and vararg_representation.arguments
            else None
        )
        vararg_item_type = (
            next(
                iter(parameter_type(signature_function.vararg).generic_types.values())
            )
            if signature_function.vararg is not None
            else None
        )
        normalized_args = []
        for index, (source, argument) in enumerate(
            zip(node.args, args, strict=True)
        ):
            if isinstance(source, ast.Starred):
                if (
                    index >= len(positional_parameters)
                    and vararg_item_representation is not None
                ):
                    actual = analyzed_representation(argument)
                    if actual != vararg_item_representation:
                        self.fail(
                            source.value,
                            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                            "Starred argument items use an incompatible representation",
                            help=(
                                "Convert each item explicitly to the variadic "
                                "parameter type."
                            ),
                        )
                normalized_args.append(argument)
            elif (
                index >= len(positional_parameters)
                and signature_function.vararg is not None
            ):
                normalized_args.append(
                    normalize_expected(
                        source,
                        argument,
                        vararg_item_representation,
                        vararg_item_type,
                    )
                )
            else:
                parameter = (
                    positional_parameters[index]
                    if index < len(positional_parameters)
                    else signature_function.vararg
                )
                normalized_args.append(
                    normalize_parameter(
                        source,
                        argument,
                        parameter,
                    )
                )
        args = normalized_args
        for source, keyword in zip(node.keywords, keywords, strict=True):
            parameter = parameters_by_name.get(keyword.arg)
            if parameter is not None and not accepts_static_arrays:
                self.reject_static_array_widening(
                    source.value,
                    keyword.value,
                    parameter.annotation.obj,
                    analyzed_array_format(parameter),
                )
        keywords = [
            ast.keyword(
                arg=keyword.arg,
                value=normalize_keyword(
                    source.value,
                    keyword,
                ),
            )
            for source, keyword in zip(node.keywords, keywords, strict=True)
        ]
        return args, keywords

    def normalize_callable_signature_arguments(
        self,
        node,
        callable_signature,
        args,
    ):
        parameter_types = callable_signature.parameter_types
        if parameter_types is None:
            return args
        representations = callable_signature.parameter_representations
        if representations is None:
            representations = (None,) * len(parameter_types)
        return [
            self.normalize_parameter_value(
                source,
                argument,
                representation,
                parameter_type,
                representation_aware=False,
            )
            for source, argument, representation, parameter_type in zip(
                node.args,
                args,
                representations[:len(args)],
                parameter_types[:len(args)],
                strict=True,
            )
        ]

    def normalize_declared_call_arguments(
        self,
        node,
        called_function,
        signature_function,
        callable_signature,
        args,
        keywords,
        type_bindings,
        representation_bindings,
    ):
        if callable_signature is not None:
            args = self.normalize_callable_signature_arguments(
                node,
                callable_signature,
                args,
            )
        elif isinstance(signature_function, Function):
            args, keywords = self.normalize_function_signature_arguments(
                node,
                called_function,
                signature_function,
                args,
                keywords,
                type_bindings,
                representation_bindings,
            )
        return args, keywords

    def represented_generic_argument_source(
        self,
        node,
        return_type,
        constructor,
        args,
        keywords,
    ):
        if (
            isinstance(node.func, ast.Subscript)
            and self.annotation_representation(node.func) is not None
        ):
            return node.func.slice
        if not isinstance(constructor, Function) or constructor.original_node is None:
            return None

        generic_names = frozenset(return_type.generic_types)
        source_parameters = {
            parameter.arg: parameter.annotation
            for parameter in (
                *constructor.original_node.args.posonlyargs,
                *constructor.original_node.args.args,
                *constructor.original_node.args.kwonlyargs,
            )
        }

        def represents_generic(parameter, argument):
            annotation = source_parameters.get(parameter.arg)
            return (
                annotation is not None
                and analyzed_representation(argument) is not None
                and any(
                    isinstance(value, ast.Name) and value.id in generic_names
                    for value in ast.walk(annotation)
                )
            )

        for parameter, argument, source in zip(
            constructor.params,
            args,
            node.args,
            strict=False,
        ):
            if represents_generic(parameter, argument):
                return source

        parameters_by_name = function_parameters_by_name(
            constructor,
            include_positional_only=True,
        )
        for keyword, source in zip(keywords, node.keywords, strict=True):
            parameter = parameters_by_name.get(keyword.arg)
            if parameter is not None and represents_generic(
                parameter,
                keyword.value,
            ):
                return source.value
        return None

    def reject_represented_generic_class_call(
        self,
        node,
        call_target,
        called_function,
        generic_constructor,
        return_type,
        args,
        keywords,
    ):
        if not (
            isinstance(return_type, Class)
            and return_type.generic_types
            and not getattr(return_type.py_obj, "__builtin__", False)
            and (
                isinstance(call_target, GenericClass)
                or isinstance(call_target, Class)
                and called_function is not None
                and called_function.name == "__init__"
                and return_type is call_target
            )
        ):
            return
        source = self.represented_generic_argument_source(
            node,
            return_type,
            called_function or generic_constructor,
            args,
            keywords,
        )
        if source is not None and not getattr(
            return_type.py_obj, "__pyjs_allow_represented_generics__", False,
        ):
            self.fail(
                source,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "Generic classes cannot use represented type arguments",
                help=(
                    "Use a concrete class with fixed-width or StaticArray "
                    "field annotations."
                ),
            )

    def resolve_call_return_type(
        self,
        node,
        func,
        call_target,
        callable_signature,
        signature_function,
        called_function,
        args,
        keywords,
        type_bindings,
    ):
        generic_constructor = None
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
        else:
            assert isinstance(call_target, GenericClass)
            contextual_type = self.contextual_types.get(node)
            collection_type = contextual_collection_type(
                contextual_type,
                call_target.name,
            )
            if not args and not keywords and call_target.name == "tuple":
                return_type = call_target()
            elif not args and not keywords and collection_type is not None:
                return_type = collection_type
            else:
                return_type = infer_generic_call_type(
                    call_target,
                    args,
                    keywords,
                )
                if return_type is None:
                    try:
                        return_type = call_target.from_call([a.obj for a in args])
                    except TypeError:
                        self.fail(
                            node,
                            DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                            f"Type arguments for {call_target.name}() cannot be inferred",
                            help=(
                                "Add an explicit specialized annotation that "
                                "provides the missing types."
                            ),
                        )
            func = Name(return_type)
            if not getattr(return_type.py_obj, "__builtin__", False):
                generic_constructor = return_type.find("__init__")
                assert isinstance(generic_constructor, Function)
                if not generic_constructor.signature_analyzed:
                    raise DependencyError(generic_constructor)
        if called_function is not None:
            return_type = substitute_type_variables(return_type, type_bindings)
        return func, return_type, generic_constructor

    def resolve_call_return_representation(
        self,
        node,
        return_type,
        func,
        signature_function,
        args,
        representation_bindings,
        preserve_receiver,
        receiver_result,
        explicit_numeric,
    ):
        result = None
        if (
            isinstance(return_type, Class)
            and getattr(return_type.py_obj, "__pyjs_allow_represented_generics__", False)
            and isinstance(node.func, ast.Subscript)
        ):
            result = self.annotation_representation(node.func)
        if isinstance(signature_function, Function):
            declared_type = signature_function.declared_return_type
            declared_representation = signature_function.return_representation
            if getattr(func, "union_functions", ()):
                # Method selection cannot select only one arm's result layout.
                # Reuse the same merged metadata as an extracted callable;
                # unwrap Awaitable here before the ordinary async wrapping below.
                declared_type = func.union_return_type
                callable_representation = analyzed_representation(func)
                declared_representation = (
                    callable_representation.result if callable_representation is not None else None
                )
                if signature_function.is_async and declared_representation is not None:
                    declared_representation = declared_representation.arguments[0]
            declared_result = substitute_representation_variables(
                declared_type,
                declared_representation,
                representation_bindings,
            )
            if declared_result is not None:
                result = declared_result
            if analysis_metadata(
                signature_function.py_obj,
                "preserves_numeric_format",
                False,
            ):
                source = func.value if isinstance(func, Attribute) else args[0]
                result = analyzed_representation(source)
            if signature_function.is_async:
                result = compound_representation(arguments=(result,))
        if preserve_receiver:
            result = receiver_result
        if explicit_numeric is not None:
            result = explicit_numeric
        return result

    def apply_generic_collection_result_representation(
        self,
        node,
        call_target,
        return_type,
        args,
        keywords,
        call,
    ):
        if (isinstance(call_target, Class) and call_target.container.scope.is_builtins
                and call_target.generic_name in {"list", "set", "frozenset", "tuple"}):
            # An explicitly specialized constructor owns its new slots. The
            # signature's erased V cannot supply their portable representation.
            representation = self.annotation_representation(node.func)
            if args:
                members = tuple(call_target.generic_types.values())
                representations = representation.arguments if representation is not None else (None,) * len(members)
                fixed_tuple = call_target.generic_name == "tuple" and not call_target.tuple_variadic
                homogeneous = not fixed_tuple or bool(members) and all(same_analyzer_type(member, members[0])
                    and represented == representations[0]
                    for member, represented in zip(members, representations, strict=True))
                if fixed_tuple and not homogeneous:
                    # Heterogeneous tuples retain positional representations;
                    # homogeneous tuples can copy any matching iterable.
                    source = args[0]
                    if isinstance(source, List):
                        # The fresh input list cannot escape. Retain its ordered
                        # item expressions, not a homogeneous intermediate layout.
                        source = ast.copy_location(Tuple(call_target, elts=source.elts), source)
                    call.args[0] = self.normalize_stored_value(node.args[0], source, representation, call_target)
                else:
                    item_representation = None
                    if representation is not None:
                        item_representation = representations[0] if fixed_tuple else representation.item_representation
                    call.args[0] = self.normalize_stored_iterable(node.args[0], args[0],
                        item_representation,
                        members[0] if members else None)
            set_analyzed_representation(call, representation)
            return
        if not isinstance(call_target, GenericClass) or not call_target.container.scope.is_builtins:
            return
        if return_type.generic_name == "dict":
            key_values = []
            item_values = []
            if args:
                source_type = analyzed_value_type(args[0])
                source_representation = analyzed_representation(args[0])
                if is_builtin_class(source_type, "dict"):
                    source_members = (
                        source_representation.arguments
                        if source_representation is not None
                        else (None, None)
                    )
                    key_values.append(
                        (source_type.generic_types["K"], source_members[0])
                    )
                    item_values.append(
                        (source_type.generic_types["V"], source_members[1])
                    )
                else:
                    protocol = self.require_iterable(node.args[0], args[0])
                    for pair_type in get_type_members(protocol.item_type):
                        if (not is_builtin_class(pair_type, "tuple") or pair_type.tuple_variadic
                                or len(pair_type.generic_types) != 2):
                            continue
                        pair_representation = representation_for_member(
                            protocol.item_type, protocol.item_representation, pair_type)
                        pair_members = (
                            pair_representation.arguments
                            if pair_representation is not None
                            else (None, None)
                        )
                        pair_types = tuple(pair_type.generic_types.values())
                        key_values.append((pair_types[0], pair_members[0]))
                        item_values.append((pair_types[1], pair_members[1]))
            string_type = BUILTINS.search("str")
            key_values.extend((string_type, None) for _keyword in keywords)
            for keyword in keywords:
                item_type = analyzed_value_type(keyword.value)
                item_representation = analyzed_representation(keyword.value)
                if keyword.arg is None:
                    item_type = item_type.generic_types["V"]
                    item_representation = item_representation.arguments[1] if item_representation is not None else None
                item_values.append((item_type, item_representation))
            key_representation = (
                self.merge_typed_representations(
                    node,
                    return_type.generic_types["K"],
                    key_values,
                    "Dictionary constructor keys",
                )
                if key_values
                else None
            )
            item_representation = (
                self.merge_typed_representations(
                    node,
                    return_type.generic_types["V"],
                    item_values,
                    "Dictionary constructor values",
                )
                if item_values
                else None
            )
            set_analyzed_representation(
                call,
                compound_representation(
                    arguments=(key_representation, item_representation)
                ),
            )
            return
        if return_type.generic_name in {"list", "set", "frozenset", "tuple"} and args:
            if (return_type.generic_name == "tuple"
                    and getattr(analyzed_value_type(args[0]), "generic_name", None) == "tuple"):
                set_analyzed_representation(call, analyzed_representation(args[0]))
                return
            protocol = self.require_iterable(node.args[0], args[0])
            representation = (
                tuple_representation((protocol.item_representation,))
                if return_type.generic_name == "tuple"
                else compound_representation(
                    arguments=(protocol.item_representation,)
                )
            )
            set_analyzed_representation(call, representation)

    def normalize_typed_dict_constructor(self, call_target, args, call):
        if not isinstance(call_target, TypedDictClass):
            return
        representation = runtime_annotation_representation(call_target.py_cls)
        if args and representation is not None:
            args[0] = self.normalize_representation(
                args[0],
                representation,
                call_target,
            )
            call.args[0] = args[0]
        for keyword in call.keywords:
            if keyword.arg not in call_target.annotations:
                continue
            keyword.value = self.normalize_representation(
                keyword.value,
                runtime_annotation_representation(
                    call_target.annotations[keyword.arg]
                ),
                call_target.field_type(keyword.arg),
            )
        set_analyzed_representation(call, representation)

    def finish_static_array_constructor(
        self,
        node,
        args,
        keywords,
        array_format_value,
        array_representation_value,
        item_type,
    ):
        if len(args) != 1 or keywords:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "StaticArray construction requires one fixed-size value",
                help="Pass one list or tuple literal with the declared length.",
            )
        item_representation = (
            array_representation_value.arguments[0]
            if array_representation_value is not None
            and array_representation_value.arguments
            else None
        )
        assert isinstance(item_type, (Class, UnionType))
        list_type = BUILTINS.search("list")
        assert isinstance(list_type, GenericClass)
        array_value_type = list_type(item_type)
        value = self.normalize_array_value(
            args[0],
            array_format_value,
            item_representation,
            item_type,
        )
        if isinstance(value, Tuple):
            value = List(array_value_type, elts=value.elts)
            apply_representation(
                value,
                array_representation(
                    array_format_value,
                    item_representation,
                ),
            )
        elif not isinstance(value, List):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "StaticArray copying is not implemented",
                help="Construct a static array from a list or tuple literal.",
            )
        else:
            value.obj = array_value_type
        return value

    def finish_numeric_call(
        self,
        numeric_constructor_format,
        args,
        call,
        explicit_numeric_representation,
        signature_function,
    ):
        if numeric_constructor_format is None:
            if (
                explicit_numeric_representation is not None
                and explicit_numeric_representation.numeric is not None
            ):
                return self.normalize_numeric_value(
                    call,
                    explicit_numeric_representation.numeric,
                    force=True,
                )
            if (
                isinstance(signature_function, Function)
                and analysis_metadata(
                    signature_function.py_obj,
                    "preserves_numeric_format",
                    False,
                )
                and (result_format := analyzed_numeric_format(call)) is not None
            ):
                return self.normalize_numeric_value(
                    call,
                    result_format,
                    force=True,
                )
            return call

        numeric_name = (
            "int" if numeric_constructor_format.kind == "integer" else "float"
        )
        numeric_type = BUILTINS.search(numeric_name)
        default_value = 0 if numeric_name == "int" else 0.0
        value = args[0] if args else Constant(numeric_type, value=default_value)
        if (
            args
            and numeric_constructor_format.kind == "integer"
            and numeric_constructor_format.domain == "portable"
            and analyzed_value_type(value).generic_name == "float"
            and (literal := float_literal(getattr(value, "python_node", value)))
            is not None
        ):
            value = Constant(
                numeric_type,
                value=wrapped_integer_value(
                    int(literal),
                    numeric_constructor_format,
                ),
            )
        elif (
            args
            and numeric_constructor_format.kind == "integer"
            and numeric_constructor_format.domain != "wgsl"
            and (
                literal := integer_literal(
                    getattr(value, "python_node", value),
                )
            )
            is not None
        ):
            value = Constant(
                numeric_type,
                value=wrapped_integer_value(
                    literal,
                    numeric_constructor_format,
                ),
            )
        return self.numeric_cast(value, numeric_constructor_format)

    def numeric_cast(self, value, storage_format):
        """Convert one result without relabeling the source expression/storage."""
        numeric_name = "int" if storage_format.kind == "integer" else "float"
        numeric_type = BUILTINS.search(numeric_name)
        value_obj = numeric_type(
            "__numeric_cast__",
            self.scope,
            self.func,
        )
        apply_representation(
            value_obj,
            direct_representation(storage_format, None),
        )
        cast = Call(
            numeric_type,
            value_obj=value_obj,
            func=Name(numeric_type, id=numeric_name),
            args=[value],
            keywords=[],
        )
        cast.numeric_cast = storage_format
        return cast

    def call_runtime_methods(
        self,
        node,
        func,
        call_target,
        callable_signature,
        signature_function,
        called_function,
        generic_constructor,
        return_type,
        args,
        keywords,
        type_bindings,
        representation_bindings,
    ):
        argument_methods = ()
        if callable_signature is not None:
            argument_methods = self.validate_callable_call(
                node,
                callable_signature,
                args,
                keywords,
            )
        elif called_function is not None:
            argument_methods = self.validate_call_argument_types(
                node,
                signature_function,
                args,
                keywords,
                type_bindings,
                representation_bindings=representation_bindings,
            )
        elif generic_constructor is not None:
            argument_methods = self.validate_call_argument_types(
                node,
                generic_constructor,
                args,
                keywords,
                {},
            )
        elif (
            args
            and isinstance(return_type, Class)
            and return_type.generic_name in {"dict", "list", "set", "frozenset", "tuple"}
        ):
            protocol = iterable_protocol(analyzed_value_type(args[0]))
            if protocol is not None:
                argument_methods = protocol.methods
        contract_methods = (
            self.runtime_contract_methods(func, called_function, args)
            if called_function is not None
            else ()
        )
        methods = tuple(dict.fromkeys((*argument_methods, *contract_methods)))
        if (
            isinstance(call_target, Instance)
            and not isinstance(call_target.cls, CallableClass)
            and not getattr(call_target.cls.py_obj, "__builtin__", False)
            and called_function is not None
        ):
            methods = tuple(dict.fromkeys((*methods, called_function)))
        return methods

    def apply_call_result_modifiers(
        self,
        func,
        called_function,
        return_type,
        return_representation,
    ):
        if called_function is not None and called_function.returns_self:
            assert isinstance(func, Attribute)
            receiver = func.value.obj
            if isinstance(receiver, Instance):
                return_type = receiver.cls
            else:
                assert isinstance(receiver, Class)
                return_type = receiver
            return_representation = analyzed_representation(func.value)
        if called_function is not None and called_function.is_async:
            awaitable = BUILTINS.search("Awaitable")
            assert isinstance(awaitable, GenericClass)
            return_type = awaitable(return_type)
        return return_type, return_representation

    def build_call_node(
        self,
        node,
        *,
        func,
        call_target,
        callable_signature,
        signature_function,
        called_function,
        return_type,
        return_representation,
        args,
        keywords,
        runtime_methods,
        is_super_method_call,
    ):
        dependency_objects = {}
        inline_function = called_function
        if isinstance(func.obj, Class) and is_inline_class(func.obj.py_obj):
            inline_function = func.obj
        elif inline_function is None and isinstance(func.obj, Class):
            constructor = func.obj.find_attrs("__init__")
            if isinstance(constructor, Function) and constructor.inline_decorator:
                inline_function = constructor
        if inline_function is not None:
            dependency_objects = self.inline_dependencies(inline_function, node)

        value_obj = return_type
        if isinstance(return_type, Class):
            value_obj = return_type("__call_result__", self.scope, self.func)
            if callable_signature is not None:
                apply_representation(
                    value_obj,
                    callable_signature.return_representation,
                )
            elif isinstance(signature_function, Function):
                representation = return_representation
                if representation is None and not signature_function.is_async:
                    representation = direct_representation(
                        signature_function.return_numeric_format,
                        signature_function.return_array_format,
                    )
                apply_representation(value_obj, representation)

        dictionary_keys = None
        dictionary_optional: frozenset[str] = frozenset()
        if isinstance(call_target, Class) and called_function is not None:
            prepared = self.prepare_dictionary_call(
                call_target,
                called_function,
                args,
                keywords,
            )
            if prepared is not None:
                dictionary_keys, dictionary_optional = prepared

        generated_method_owner = None
        if isinstance(call_target, Class):
            generated_method_owner = call_target
        elif (
            is_super_method_call
            and called_function is not None
            and called_function.name == "__init__"
        ):
            generated_method_owner = called_function.cls
        # Constructor replacement is a JavaScript hydration mechanism. Other
        # backends construct the Python class and run its ordinary initializer.
        method = (
            generated_method(
                generated_method_owner,
                "__pyjs_constructor_method__",
            )
            if _ACTIVE_ENVIRONMENT.get().name == "js"
            else None
        )
        call = Call(
            return_type,
            value_obj=value_obj,
            func=func,
            args=args,
            keywords=keywords,
            dependency_objects=dependency_objects,
            runtime_methods=runtime_methods,
            generated_methods=(method,) if method is not None else (),
            dictionary_keys=dictionary_keys,
            dictionary_optional=dictionary_optional,
        )
        if callable_signature is not None:
            set_analyzed_representation(
                call,
                callable_signature.return_representation,
            )
        elif isinstance(signature_function, Function):
            set_analyzed_representation(call, return_representation)
        return call

    def visit_call_function(self, node):
        previous_call_target = self.direct_call_target
        self.direct_call_target = (
            node.func.value if isinstance(node.func, ast.Subscript) else node.func
        )
        try:
            if isinstance(node.func, ast.Subscript):
                func = self.visit(node.func.value)
                if isinstance(func.obj, GenericClass):
                    return self.visit_type_annotation(node.func)
            return self.visit(node.func)
        finally:
            self.direct_call_target = previous_call_target

    def analyze_static_array_call(self, node, func):
        array_format = analyzed_array_format(func)
        array_representation = analyzed_representation(func)
        item_type = None
        if array_format is not None:
            assert isinstance(node.func, ast.Subscript)
            array_arguments = (
                node.func.slice.elts
                if isinstance(node.func.slice, ast.Tuple)
                else (node.func.slice,)
            )
            item_type = self.visit_type_annotation(array_arguments[0]).obj
            if node.args:
                list_type = BUILTINS.search("list")
                assert isinstance(list_type, GenericClass)
                self.contextual_types[node.args[0]] = list_type(item_type)
                self.contextual_representations[node.args[0]] = array_representation
        if (
            isinstance(func, Attribute)
            and func.attr in {"append", "clear", "extend", "insert", "pop", "remove"}
            and analyzed_array_format(func.value) is not None
        ):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Static arrays do not support {func.attr}()",
                help="Assign an existing item or create another static array.",
            )
        return array_format, array_representation, item_type

    def resolve_numeric_call_target(self, node, func, call_target):
        if not isinstance(call_target, TypeAliasValue):
            return func, call_target, None
        numeric = numeric_format(call_target.annotation)
        if numeric is None:
            self.fail_not_callable(node.func, call_target)
        numeric_name = "int" if numeric.kind == "integer" else "float"
        call_target = BUILTINS.search(numeric_name)
        assert isinstance(call_target, Class)
        return Name(call_target, id=call_target.name), call_target, numeric

    def resolve_called_function(self, node, func, call_target):
        called_function = None
        callable_signature = None
        if (isinstance(call_target, (Class, GenericClass))
                and call_target.container.scope.is_builtins
                and getattr(call_target, "generic_name", call_target.name) == "type"):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "runtime type() introspection is not supported",
                help=(
                    "Use static annotations or a supported isinstance() check instead."
                ),
            )
        if isinstance(call_target, CallableClass):
            callable_signature = call_target
        elif isinstance(call_target, GenericClass):
            self.validate_generic_constructor_shape(node, call_target)
        elif isinstance(call_target, Instance):
            if isinstance(call_target.cls, UnionType):
                self.fail_not_callable(node.func, call_target.cls)
            try:
                called_function = call_target.find("__call__")
            except NameError:
                self.fail_not_callable(node.func, call_target.cls)
            if not isinstance(called_function, Function):
                self.fail(
                    node.func, DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "Implicit calls through non-method __call__ attributes are not supported",
                    help="Call a callable instance field explicitly with value.__call__(...).",
                )
            if isinstance(call_target.cls, CallableClass):
                callable_signature = call_target.cls
        elif isinstance(call_target, Class) and analyzed_value_type(func) is call_target:
            self.fail_not_callable(node.func, call_target)
        else:
            if isinstance(call_target, (Module, ModuleAlias)):
                self.fail(
                    node.func,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Module {call_target.name!r} is not callable",
                    help="Call a function or class defined by the module instead.",
                )
            if not isinstance(call_target, (GenericClass, Class, Function)):
                self.fail(
                    node.func,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "This expression is not callable",
                    help="Call a function, class, or typed Callable value.",
                )
            if isinstance(call_target, Function):
                called_function = call_target
            elif (
                isinstance(call_target, Class)
                # Application subclasses must bind their initializer even when
                # a browser/native declaration supplies an inherited marker.
                and not vars(call_target.py_obj).get("__builtin__", False)
                and not is_client_model_type(call_target)
                and not (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "super"
                )
            ):
                called_function = (
                    call_target.inline_constructor
                    if is_inline_class(call_target.py_obj)
                    and call_target.inline_constructor is not None
                    else call_target.find("__init__")
                )
        return called_function, callable_signature

    def ensure_call_signature_ready(self, node, called_function):
        if called_function is None:
            return
        if not called_function.signature_analyzed:
            raise DependencyError(called_function)
        if (
            not called_function.is_analyzed
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
        for overload in called_function.overloads:
            if not overload.signature_analyzed:
                raise DependencyError(overload)

    def initial_call_signature(self, node, called_function):
        overloads = (
            self.overload_candidates(called_function, node)
            if called_function is not None
            else ()
        )
        semantic_overloads = bool(
            called_function is not None
            and (
                called_function.analysis is not None
                or js_metadata(called_function.py_obj, "dispatch") is not None
                or getattr(called_function.py_obj, "__builtin__", False)
            )
        )
        if len(overloads) == 1:
            signature_function = overloads[0]
        elif len(overloads) > 1:
            signature_function = called_function if semantic_overloads or is_builtin_method(called_function) else None
        else:
            signature_function = called_function
        return overloads, semantic_overloads, signature_function

    def select_call_overload(
        self,
        node,
        called_function,
        callable_signature,
        overloads,
        semantic_overloads,
        args,
        keywords,
    ):
        # A broad item overload cannot exclude slices hidden behind object or
        # unions. The implementation declares both result/replacement domains.
        if dynamic_builtin_subscript(called_function, args):
            overloads = (called_function,)
        matches = [
            overload
            for overload in overloads
            if self.overload_matches_types(overload, args, keywords)
            and (
                semantic_overloads
                # Builtin method bodies normalize represented operands, but
                # unlike semantic functions they still require a matching
                # overload. Their broad implementation union is not a fallback.
                or is_builtin_method(called_function)
                or self.overload_matches_representations(
                    overload,
                    args,
                    keywords,
                )
            )
        ]
        if not matches:
            if not semantic_overloads:
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"No overload of {called_function.name!r} accepts these "
                    "argument types and representations",
                    help="Pass arguments matching one declared overload.",
                )
            return None
        signature_function = matches[0]
        args, keywords, type_bindings, representation_bindings = (
            self.analyze_call_arguments(
                node,
                signature_function,
                callable_signature,
            )
        )
        return (
            signature_function,
            args,
            keywords,
            type_bindings,
            representation_bindings,
        )

    def reject_unpreserved_call_arguments(
        self,
        node,
        signature_function,
        args,
        keywords,
        array_constructor_format,
    ):
        if array_constructor_format is not None:
            return
        positional_parameters = (
            signature_function.params if isinstance(signature_function, Function) else ()
        )
        parameters_by_name = (
            function_parameters_by_name(
                signature_function,
                include_positional_only=True,
            )
            if isinstance(signature_function, Function)
            else {}
        )
        for index, (source, argument) in enumerate(zip(node.args, args, strict=True)):
            expected_array = (
                analyzed_array_format(positional_parameters[index])
                if index < len(positional_parameters)
                else None
            )
            if expected_array is None:
                self.reject_unpreserved_collection_items(source, argument)
        for source, keyword in zip(node.keywords, keywords, strict=True):
            parameter = parameters_by_name.get(keyword.arg)
            if parameter is None or analyzed_array_format(parameter) is None:
                self.reject_unpreserved_collection_items(
                    source.value,
                    keyword.value,
                )

    def validate_fixed_numeric_call(self, node, numeric, args, keywords):
        if numeric is None:
            return
        if keywords or len(args) > 1:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "fixed-width numeric construction accepts one number",
                help="Call the fixed-width type with zero or one int or float.",
            )
        if args and any(member.generic_name not in {"bool", "float", "int"}
                        for member in get_type_members(analyzed_value_type(args[0]))):
            self.fail(
                node.args[0],
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "fixed-width numeric construction requires a number",
                help="Pass an int or float value.",
            )
        self.validate_numeric_constructor(node, numeric, args)

    def normalize_numeric_call_arguments(
        self,
        node,
        func,
        call_target,
        called_function,
        args,
        keywords,
    ):
        from .iterable_protocol import is_abstract_iterable
        if (call_target is BUILTINS.search("bool") and len(args) == 1 and not keywords
                and is_abstract_iterable(analyzed_value_type(args[0]))):
            return args, keywords, None, self.dynamic_truth_test(node, args[0])
        integer_index_function = called_function
        if integer_index_function is None and isinstance(call_target, Class):
            try:
                integer_index_function = call_target.find("__init__")
            except NameError:
                pass
        if integer_index_function is not None:
            args, keywords = self.normalize_integer_index_arguments(
                node,
                integer_index_function,
                args,
                keywords,
            )

        explicit_representation = None
        if node not in self.active_call_analysis:
            args, explicit_representation = self.normalize_explicit_numeric_dunder(
                node,
                func,
                args,
            )
            if (
                _ACTIVE_ENVIRONMENT.get().name == "js"
                and isinstance(func, Attribute)
                and func.attr in {"__truediv__", "__rtruediv__"}
                and python_builtins.is_int64_format(
                    analyzed_numeric_format(func.value)
                )
            ):
                left, right = (
                    (args[0], func.value)
                    if func.attr == "__rtruediv__"
                    else (func.value, args[0])
                )
                return (
                    args,
                    keywords,
                    explicit_representation,
                    self.int64_division_call(node, left, right),
                )
        return args, keywords, explicit_representation, None

    def dispatched_dunder_call(
        self,
        node,
        func,
        called_function,
        signature_function,
        args,
        keywords,
        type_bindings,
    ):
        dunder_builtin = called_function
        if dunder_builtin is None and isinstance(func.obj, Class) and args:
            dunder_builtin = func.obj
        if dunder_builtin is None or not (
            method_name := js_metadata(dunder_builtin.py_obj, "dispatch")
        ):
            return None
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
            dunder_builtin,
            method_name,
            args,
            keywords,
        )
        result.runtime_methods = tuple(
            dict.fromkeys((*result.runtime_methods, *runtime_methods))
        )
        return result

    def prepare_call_signature(self, node, func, called_function):
        overloads, semantic_overloads, signature_function = (
            self.initial_call_signature(node, called_function)
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
            self.validate_call_shape(
                node,
                signature_function or called_function,
            )
        self.canonicalize_numeric_dunder_keywords(
            node,
            func,
            signature_function or called_function,
        )
        return (
            overloads,
            semantic_overloads,
            signature_function,
            is_super_method_call,
        )

    def visit_Call(self, node: ast.Call):
        unbound_repeat = self.unbound_sequence_repeat(node)
        if unbound_repeat is not None:
            return unbound_repeat

        func = self.visit_call_function(node)

        if (isinstance(func, Attribute) and func.attr == "__getitem__"
                and is_builtin_method(func.obj)
                and analyzed_value_type(func.value).generic_name == "tuple"):
            if len(node.args) != 1 or node.keywords:
                self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "tuple.__getitem__ takes one positional argument")
            return self.tuple_subscript(node, func.value, node.args[0], self.visit(node.args[0]))

        call_target = analyzed_value_object(func)
        (
            array_constructor_format,
            array_constructor_representation,
            array_constructor_item_type,
        ) = self.analyze_static_array_call(node, func)
        func, call_target, numeric_constructor_format = (
            self.resolve_numeric_call_target(node, func, call_target)
        )
        called_function, callable_signature = self.resolve_called_function(
            node,
            func,
            call_target,
        )
        if called_function is not None and is_empty_inline(
            called_function.py_func, _ACTIVE_ENVIRONMENT.get().name,
        ):
            # Discarded arguments may intentionally contain code belonging to
            # another runtime. Resolve the declaration without visiting them.
            self.ensure_call_signature_ready(node, called_function)
            none_type = BUILTINS.search("NoneType")
            if called_function.return_type is not none_type:
                self.fail(
                    node, DiagnosticCode.INCOMPATIBLE_RETURN,
                    "An empty inline template requires a None return type",
                )
            return Constant(none_type, value=None)
        self.ensure_call_signature_ready(node, called_function)
        self.expand_static_call_keywords(node, call_target)
        if (
            called_function is not None
            and called_function.analysis is not None
            and node not in self.active_call_analysis
        ):
            return called_function.analysis(_CallAnalysis(
                self, node, called_function,
                receiver=func.value if isinstance(func, Attribute) else None,
            ))
        (
            overloads,
            semantic_overloads,
            signature_function,
            is_super_method_call,
        ) = self.prepare_call_signature(
            node,
            func,
            called_function,
        )

        (
            args,
            keywords,
            type_bindings,
            representation_bindings,
        ) = self.analyze_call_arguments(
            node,
            signature_function,
            callable_signature,
        )
        if (called_function is not None and called_function.is_classmethod
                and isinstance(func, Attribute)
                and isinstance(receiver := analyzed_value_object(func.value), Class)):
            specialized = substitute_type_variables(receiver, type_bindings)
            if specialized is not receiver:
                # Inference must specialize the runtime receiver too, not just
                # the result annotation. Otherwise JS constructs Box[T] while
                # reached instance methods live on the distinct Box[str].
                called_function = specialized.find_attrs(func.attr)
                func = ast.copy_location(Attribute(called_function, value=Name(specialized),
                                                   attr=func.attr, ctx=ast.Load()), func)
                call_target = called_function
                self.ensure_call_signature_ready(node, called_function)
                overloads, semantic_overloads, signature_function, is_super_method_call = self.prepare_call_signature(
                    node, func, called_function)
                args, keywords, type_bindings, representation_bindings = self.analyze_call_arguments(
                    node, signature_function, callable_signature)
        self.reject_unpreserved_call_arguments(
            node,
            signature_function,
            args,
            keywords,
            array_constructor_format,
        )
        self.validate_fixed_numeric_call(
            node,
            numeric_constructor_format,
            args,
            keywords,
        )
        if len(overloads) > 1:
            selection = self.select_call_overload(
                node,
                called_function,
                callable_signature,
                overloads,
                semantic_overloads,
                args,
                keywords,
            )
            if selection is not None:
                (
                    signature_function,
                    args,
                    keywords,
                    type_bindings,
                    representation_bindings,
                ) = selection

        (
            args,
            keywords,
            explicit_numeric_representation,
            numeric_replacement,
        ) = self.normalize_numeric_call_arguments(
            node,
            func,
            call_target,
            called_function,
            args,
            keywords,
        )
        if numeric_replacement is not None:
            return numeric_replacement

        if signature_function is not None and signature_function.type_parameters:
            self.validate_type_bindings(
                node,
                signature_function,
                type_bindings,
            )

        dispatched = self.dispatched_dunder_call(
            node,
            func,
            called_function,
            signature_function,
            args,
            keywords,
            type_bindings,
        )
        if dispatched is not None:
            return dispatched

        func, return_type, generic_constructor = self.resolve_call_return_type(
            node,
            func,
            call_target,
            callable_signature,
            signature_function,
            called_function,
            args,
            keywords,
            type_bindings,
        )

        self.reject_represented_generic_class_call(
            node,
            call_target,
            called_function,
            generic_constructor,
            return_type,
            args,
            keywords,
        )

        runtime_methods = self.call_runtime_methods(
            node,
            func,
            call_target,
            callable_signature,
            signature_function,
            called_function,
            generic_constructor,
            return_type,
            args,
            keywords,
            type_bindings,
            representation_bindings,
        )
        args, keywords = self.normalize_declared_call_arguments(
            node,
            called_function,
            signature_function,
            callable_signature,
            args,
            keywords,
            type_bindings,
            representation_bindings,
        )
        (
            args,
            keywords,
            preserve_receiver_representation,
            receiver_result_representation,
        ) = self.normalize_collection_call(node, func, args, keywords)
        resolved_return_representation = self.resolve_call_return_representation(
            node,
            return_type,
            func,
            signature_function,
            args,
            representation_bindings,
            preserve_receiver_representation,
            receiver_result_representation,
            explicit_numeric_representation,
        )
        if hasattr(node, "assignment_value_index"):
            args = list(args)
            index = node.assignment_value_index
            node.assignment_prefix, args[index] = self.capture_assignment_value(args[index])
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
            set_analyzed_representation(call, resolved_return_representation)
            return call
        return_type, resolved_return_representation = (
            self.apply_call_result_modifiers(
                func,
                called_function,
                return_type,
                resolved_return_representation,
            )
        )

        call = self.build_call_node(
            node,
            func=func,
            call_target=call_target,
            callable_signature=callable_signature,
            signature_function=signature_function,
            called_function=called_function,
            return_type=return_type,
            return_representation=resolved_return_representation,
            args=args,
            keywords=keywords,
            runtime_methods=runtime_methods,
            is_super_method_call=is_super_method_call,
        )
        if called_function is not None and called_function.type_parameters and not is_builtin_method(called_function):
            # Backends with erased generic bodies still need the call site's
            # inferred contract when crossing a concrete ABI boundary.
            call.type_bindings = dict(type_bindings)
            call.representation_bindings = dict(representation_bindings)
        if isinstance(return_type, Class):
            self.apply_generic_collection_result_representation(
                node,
                call_target,
                return_type,
                args,
                keywords,
                call,
            )
        self.normalize_typed_dict_constructor(call_target, args, call)
        if hasattr(node, "subscript_literal"):
            return self.contextual_subscript_literal(node, call)
        if array_constructor_format is not None:
            return self.finish_static_array_constructor(
                node,
                args,
                keywords,
                array_constructor_format,
                array_constructor_representation,
                array_constructor_item_type,
            )
        return self.finish_numeric_call(
            numeric_constructor_format,
            args,
            call,
            explicit_numeric_representation,
            signature_function,
        )

    def call_argument_pattern(self, function, index):
        if function is not None:
            if index < len(function.params):
                return function.params[index].annotation.obj
            elif function.vararg is not None:
                return iterable_item_type(function.vararg.annotation.obj)
        return None

    def visit_call_argument(
        self,
        argument,
        function,
        index,
        type_bindings,
        representation_bindings=None,
    ):
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
        expected_representation = (
            substitute_representation_variables(
                pattern,
                self.call_argument_declared_representation(function, index),
                representation_bindings,
            )
            if pattern is not None and representation_bindings is not None
            else None
        )
        value = self.visit_contextual_expression(
            argument,
            expected_type,
            expected_representation=expected_representation,
        )
        if pattern is not None and contains_type_variable(pattern):
            infer_type_variables(
                pattern,
                callable_value_type(value),
                type_bindings,
            )
        return value

    def visit_call_keyword(
        self,
        keyword,
        function,
        type_bindings,
        representation_bindings=None,
    ):
        pattern = self.call_keyword_pattern(keyword, function)
        expected_type = (
            substitute_type_variables(pattern, type_bindings)
            if pattern is not None
            else None
        )
        expected_representation = (
            substitute_representation_variables(
                pattern,
                self.call_keyword_declared_representation(keyword, function),
                representation_bindings,
            )
            if pattern is not None and representation_bindings is not None
            else None
        )
        value = self.visit_contextual_expression(
            keyword.value,
            expected_type,
            expected_representation=expected_representation,
        )
        if pattern is not None and contains_type_variable(pattern):
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
        if signature.required_keywords:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Callable requires keyword-only arguments: " + ", ".join(signature.required_keywords),
                help="Call the function directly to pass named arguments.",
            )
        if signature.minimum_arguments > len(signature.parameter_types):
            self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                      "Callable alternatives have no common positional signature")
        if not signature.accepts_arity(len(args)):
            count = str(len(signature.parameter_types))
            if signature.minimum_arguments != len(signature.parameter_types):
                count = f"{signature.minimum_arguments} to {count}"
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Callable expects {count} arguments, "
                f"got {len(args)}",
            )
        runtime_methods = []
        for index, (argument, expected_type) in enumerate(
            zip(args, signature.parameter_types[:len(args)], strict=True),
            start=1,
        ):
            expected_callable = callable_member(expected_type)
            if expected_callable is not None and (
                isinstance(argument, ast.Lambda) or isinstance(argument.obj, Function)
            ):
                # Indirect callees need the same function/union checks as
                # named calls, not just compatibility with the first method.
                self.validate_callable_argument(node.args[index - 1], None, str(index),
                                                expected_type, argument)
            elif not is_call_argument_compatible(expected_type, argument):
                actual_type = analyzed_value_type(argument)
                self.fail(
                    node.args[index - 1],
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Callable argument {index} expects "
                    f"{describe_type(expected_type)}, got "
                    f"{describe_type(actual_type)}",
                    help=f"Pass a value compatible with {expected_type.to_annotation_str()}.",
                )
            runtime_methods.extend(
                self.argument_protocol_methods(expected_type, argument)
            )
        return tuple(dict.fromkeys(runtime_methods))

    def call_keyword_pattern(self, keyword, function):
        if function is None or keyword.arg is None:
            return None
        parameters = function_parameters_by_name(function)
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
                keyword.value = self.normalize_stored_value(
                    source_keyword.value,
                    keyword.value,
                    field.representation,
                    field.cls,
                )
        return value_type

    def annotation_numeric_format(self, annotation: ast.expr | None):
        source_annotation = annotation
        while annotation is not None:
            if isinstance(annotation, ast.Constant) and isinstance(
                annotation.value,
                str,
            ):
                try:
                    value = self.scope.search(annotation.value)
                except NameError:
                    return None
            elif isinstance(annotation, ast.Name):
                try:
                    value = self.scope.search(annotation.id)
                except NameError:
                    return None
            elif isinstance(annotation, ast.Subscript):
                alias = typing_alias_name(annotation.value, self.scope)
                if alias in {"Annotated", "ClassVar", "Final"}:
                    values = (
                        annotation.slice.elts
                        if isinstance(annotation.slice, ast.Tuple)
                        else (annotation.slice,)
                    )
                    annotation = values[0]
                    continue
                return None
            else:
                return None
            if isinstance(value, TypeAliasValue):
                result = numeric_format(value.annotation)
                if result is not None:
                    self.validate_numeric_format(source_annotation, result)
                return result
            return None
        return None

    def annotation_representation(
        self,
        annotation: ast.expr | None,
    ) -> ValueRepresentation | None:
        if annotation is None:
            return None
        if isinstance(annotation, ast.Constant) and isinstance(
            annotation.value,
            str,
        ):
            annotation = ast.parse(annotation.value, mode="eval").body

        # Backend overrides may validate even ordinary Python annotations.
        named_type = None
        if (isinstance(annotation, ast.Name)
                and type(self).annotation_numeric_format is InferenceVisitor.annotation_numeric_format
                and type(self).annotation_array_format is InferenceVisitor.annotation_array_format):
            try:
                named_type = self.scope.search(annotation.id)
            except NameError:
                return None
            if isinstance(named_type, Class):
                return runtime_annotation_representation(named_type.py_cls)
            if not isinstance(named_type, TypeAliasValue):
                return None

        numeric = self.annotation_numeric_format(annotation)
        array = self.annotation_array_format(annotation)
        if numeric is not None:
            return direct_representation(numeric, array)
        if array is not None:
            item = None
            array_annotation = annotation
            while isinstance(array_annotation, ast.Subscript):
                alias = typing_alias_name(array_annotation.value, self.scope)
                if alias not in {
                    "Annotated",
                    "ClassVar",
                    "Final",
                    "NotRequired",
                    "ReadOnly",
                    "Required",
                }:
                    break
                elements = (
                    array_annotation.slice.elts
                    if isinstance(array_annotation.slice, ast.Tuple)
                    else (array_annotation.slice,)
                )
                array_annotation = elements[0]
            if isinstance(array_annotation, ast.Subscript):
                item_node = (
                    array_annotation.slice.elts[0]
                    if isinstance(array_annotation.slice, ast.Tuple)
                    else array_annotation.slice
                )
                item = self.annotation_representation(item_node)
            elif isinstance(array_annotation, ast.Name):
                try:
                    alias = self.scope.search(array_annotation.id)
                except NameError:
                    alias = None
                if isinstance(alias, TypeAliasValue):
                    return runtime_annotation_representation(alias.annotation)
            direct_item = direct_representation(
                array.item_numeric,
                array.item_array,
            )
            return array_representation(
                array,
                None if item == direct_item else item,
            )

        if isinstance(annotation, ast.Name):
            if named_type is None:
                try:
                    named_type = self.scope.search(annotation.id)
                except NameError:
                    return None
            if isinstance(named_type, TypeAliasValue):
                try:
                    return runtime_annotation_representation(named_type.annotation)
                except TypeError as error:
                    self.fail(annotation, DiagnosticCode.UNSUPPORTED_SYNTAX, str(error),
                              help="Use an ordinary recursive type without represented numeric or array members.")
            if isinstance(named_type, Class):
                return runtime_annotation_representation(named_type.py_cls)
            return None

        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            elements = []

            def add_members(value):
                if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
                    add_members(value.left)
                    add_members(value.right)
                else:
                    elements.append(value)

            add_members(annotation)
            return self.union_annotation_representation(elements)

        if not isinstance(annotation, ast.Subscript):
            return None
        alias = typing_alias_name(annotation.value, self.scope)
        elements = (
            annotation.slice.elts
            if isinstance(annotation.slice, ast.Tuple)
            else (annotation.slice,)
        )
        if alias in {
            "Annotated",
            "ClassVar",
            "Final",
            "NotRequired",
            "ReadOnly",
            "Required",
        }:
            return self.annotation_representation(elements[0])
        if alias == "Optional":
            return self.union_annotation_representation(
                elements,
                extra_members=((get_none_type(), None),),
            )
        if alias == "Union":
            return self.union_annotation_representation(elements)

        try:
            generic = self.visit(annotation.value).obj
        except CompilationError, DependencyError, NameError:
            generic = None
        generic_name = getattr(generic, "name", None) or alias
        if generic_name == "Callable" and len(elements) == 2:
            parameter_node, result_node = elements
            parameters = None
            if not (
                isinstance(parameter_node, ast.Constant)
                and parameter_node.value is Ellipsis
            ):
                if not isinstance(parameter_node, (ast.List, ast.Tuple)):
                    return None
                parameters = tuple(
                    self.annotation_representation(parameter)
                    for parameter in parameter_node.elts
                )
            return compound_representation(
                parameters=parameters,
                result=self.annotation_representation(result_node),
            )
        arguments = tuple(
            self.annotation_representation(element)
            for element in elements
            if not isinstance(element, ast.Constant) or element.value is not Ellipsis
        )
        if generic_name == "tuple":
            return tuple_representation(arguments)
        return compound_representation(arguments=arguments)

    def union_annotation_representation(self, elements, *, extra_members=()):
        elements = tuple(elements)
        element_representations = tuple(self.annotation_representation(element) for element in elements)
        # Erased member types only determine positions in a nonempty representation.
        if not any(element_representations) and not any(value for _type, value in extra_members):
            return None
        members = []
        for element, representation in zip(elements, element_representations, strict=True):
            value_type = self.visit_type_annotation(element).obj
            value_types = tuple(get_type_members(value_type))
            representations = (
                representation.arguments
                if isinstance(value_type, UnionType)
                and representation is not None
                and representation.kind == "union"
                and len(representation.arguments) == len(value_types)
                else (None,) * len(value_types)
                if isinstance(value_type, UnionType)
                else (representation,)
            )
            for member in zip(value_types, representations, strict=True):
                if any(
                    same_erased_type(member[0], existing_type)
                    and member[1] == existing_representation
                    for existing_type, existing_representation in members
                ):
                    continue
                members.append(member)
        for member in extra_members:
            if any(
                same_erased_type(member[0], existing_type)
                and member[1] == existing_representation
                for existing_type, existing_representation in members
            ):
                continue
            members.append(member)
        return compound_representation(
            kind="union",
            arguments=tuple(representation for _type, representation in members),
        )

    def static_array_length(self, node: ast.expr) -> int:
        length = integer_literal(node)
        if isinstance(node, ast.Name):
            try:
                value = self.scope.search(node.id)
            except NameError:
                value = None
            if isinstance(value, Instance) and type(value.py_value) is int:
                length = value.py_value
            elif (
                isinstance(value, Instance)
                and isinstance(value.static_value, ast.Constant)
                and type(value.static_value.value) is int
            ):
                length = value.static_value.value
        if length is None:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "Static array lengths must be compile-time integer constants",
                help="Use a positive integer literal or module constant.",
            )
        if length <= 0:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Static array lengths must be positive",
                help="Use an array length greater than zero.",
            )
        return length

    def static_array_annotation(
        self,
        node: ast.Subscript,
        generic: GenericClass,
    ) -> Name:
        elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        if len(elements) != 2:
            self.fail(
                node.slice,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{generic.name} expects an item type and length",
                help=f"Use {generic.name}[ItemType, positive_length].",
            )
        item_node, length_node = elements
        item = self.visit_type_annotation(item_node)
        domain = generic.py_cls.__pyjs_array_domain__
        self.validate_array_domain(node, domain)
        item_numeric = self.annotation_numeric_format(item_node)
        item_array = self.annotation_array_format(item_node)
        item_format = item_numeric or item_array
        if item_format is not None and item_format.domain != domain:
            self.fail(
                item_node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{domain} arrays cannot store {item_format.domain} values implicitly",
                help="Use item and array types from the same numeric domain.",
            )
        result_format = ArrayFormat(
            self.static_array_length(length_node),
            domain=domain,
            item_numeric=item_numeric,
            item_array=item_array,
        )
        self.validate_array_format(node, result_format)
        list_type = BUILTINS.search("list")
        assert isinstance(list_type, GenericClass)
        result = Name(list_type(item.obj))
        item_representation = self.annotation_representation(item_node)
        direct_item = direct_representation(item_numeric, item_array)
        apply_representation(
            result,
            array_representation(
                result_format,
                None if item_representation == direct_item else item_representation,
            ),
        )
        return result

    def annotation_array_format(
        self,
        annotation: ast.expr | None,
    ) -> ArrayFormat | None:
        if annotation is None:
            return None
        if isinstance(annotation, ast.Constant) and isinstance(
            annotation.value,
            str,
        ):
            annotation = ast.parse(annotation.value, mode="eval").body
        if isinstance(annotation, ast.Name):
            try:
                value = self.scope.search(annotation.id)
            except NameError:
                return None
            if isinstance(value, TypeAliasValue):
                try:
                    result = array_format(value.annotation)
                except TypeError as error:
                    self.fail(
                        annotation,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        str(error),
                        help=("Use item and array types from the same numeric domain."),
                    )
                if result is not None:
                    self.validate_array_format(annotation, result)
                return result
            return None
        if not isinstance(annotation, ast.Subscript):
            return None
        alias = typing_alias_name(annotation.value, self.scope)
        if alias in {
            "Annotated",
            "ClassVar",
            "Final",
            "NotRequired",
            "ReadOnly",
            "Required",
        }:
            elements = (
                annotation.slice.elts
                if isinstance(annotation.slice, ast.Tuple)
                else (annotation.slice,)
            )
            return self.annotation_array_format(elements[0])
        try:
            value = self.visit(annotation.value)
        except NameError, CompilationError:
            return None
        if not isinstance(value.obj, GenericClass) or not hasattr(
            value.obj.py_cls,
            "__pyjs_array_domain__",
        ):
            return None
        return analyzed_array_format(
            self.static_array_annotation(annotation, value.obj)
        )

    def validate_array_format(self, node, value: ArrayFormat) -> None:
        self.validate_array_domain(node, value.domain)

    def validate_array_domain(self, node, domain: str) -> None:
        if self.numeric_domains is None or domain in self.numeric_domains:
            return
        target = _ACTIVE_ENVIRONMENT.get().name
        self.fail(
            node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"{domain} array types cannot compile for {target}",
            help=f"Use a portable StaticArray or a {target}-specific array.",
        )

    def normalize_numeric_value(self, node, storage_format, *, force=False):
        self.validate_wgsl_integer_literal(
            getattr(node, "python_node", node),
            node,
            storage_format,
        )
        value_format = analyzed_numeric_format(node)
        if (
            storage_format is not None
            and value_format is not None
            and storage_format != value_format
        ):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "different fixed-width numeric types cannot be assigned implicitly",
                help="Convert the value to the destination fixed-width type first.",
            )
        if _ACTIVE_ENVIRONMENT.get().name != "js":
            if storage_format is not None and value_format is None and not isinstance(node, Constant):
                # A storage conversion owns a new result. Stamping a Name or
                # Attribute also stamps its shared Instance and changes later
                # reads of the source; metadata alone would not narrow the
                # copied value either. Reuse the explicit numeric cast path.
                return ast.copy_location(self.numeric_cast(node, storage_format), node)
            literal = integer_literal(getattr(node, "python_node", node))
            if (
                storage_format is not None
                and storage_format.kind == "integer"
                and storage_format.domain != "wgsl"
                and value_format is None
                and literal is not None
            ):
                node = Constant(
                    analyzed_value_type(node),
                    value=wrapped_integer_value(literal, storage_format),
                )
            if storage_format is not None:
                set_analyzed_representation(
                    node,
                    direct_representation(storage_format, None),
                )
            return node
        normalizer_name = python_builtins.numeric_normalizer_name(storage_format)
        if normalizer_name is None:
            return node
        if (
            not force
            and value_format == storage_format
            and (
                isinstance(node, (Name, Attribute))
                or isinstance(node, Call)
                and node.operator is None
            )
        ):
            return node
        normalizer = BUILTINS.search(normalizer_name)
        assert isinstance(normalizer, Function)
        if not normalizer.signature_analyzed:
            raise DependencyError(normalizer)
        value_type = analyzed_value_type(node)
        argument = node
        literal = integer_literal(getattr(node, "python_node", node))
        if literal is not None and abs(literal) > 2**53 - 1 and storage_format.bits == 64:
            argument = Constant(BUILTINS.search("str"), value=str(literal))
        normalized = self.call_node(
            node,
            value_type,
            func=Name(normalizer),
            args=[argument],
            keywords=[],
            dependency_objects=self.inline_dependencies(normalizer, node),
        )
        representation = direct_representation(storage_format, None)
        if isinstance(normalized.value_obj, Instance):
            apply_representation(normalized.value_obj, representation)
        apply_representation(normalized, representation)
        return normalized

    def coerce_int64_operand(self, node, storage_format, source=None):
        if analyzed_numeric_format(node) is not None:
            return node
        if _ACTIVE_ENVIRONMENT.get().name != "js":
            return node
        helper = BUILTINS.search("int64_operand")
        assert isinstance(helper, Function)
        if not helper.signature_analyzed:
            raise DependencyError(helper)
        argument = node
        literal = integer_literal(source or getattr(node, "python_node", node))
        if literal is not None and abs(literal) > 2**53 - 1:
            argument = Constant(BUILTINS.search("str"), value=str(literal))
        return self.call_node(
            node,
            BUILTINS.search("int"),
            func=Name(helper),
            args=[argument],
            keywords=[],
            dependency_objects=self.inline_dependencies(helper, node),
        )

    def int64_division_call(self, node, left, right):
        helper = resolve_imported(python_builtins.int64_divide, self.module)
        assert isinstance(helper, Function)
        if not helper.signature_analyzed:
            raise DependencyError(helper)
        return self.call_node(
            node,
            BUILTINS.search("float"),
            func=Name(helper, runtime_dependency=helper),
            args=[left, right],
            keywords=[],
        )

    def normalize_integer_index_arguments(
        self,
        node: ast.Call,
        function: Function,
        args: list[ast.expr],
        keywords: list[ast.keyword],
    ) -> tuple[list[ast.expr], list[ast.keyword]]:
        names = analysis_metadata(
            function.py_obj,
            "integer_index_parameters",
            (),
        )
        if not names or _ACTIVE_ENVIRONMENT.get().name != "js":
            return args, keywords

        parameter_names = tuple(parameter.arg for parameter in function.params)
        argument_offset = max(0, len(args) - len(parameter_names))
        args = [
            self.normalize_integer_index_value(source, value)
            if 0 <= index - argument_offset < len(parameter_names)
            and parameter_names[index - argument_offset] in names
            else value
            for index, (source, value) in enumerate(
                zip(node.args, args, strict=True)
            )
        ]
        keywords = [
            ast.keyword(
                arg=keyword.arg,
                value=(
                    self.normalize_integer_index_value(
                        source.value,
                        keyword.value,
                    )
                    if keyword.arg in names
                    else keyword.value
                ),
            )
            for source, keyword in zip(node.keywords, keywords, strict=True)
        ]
        return args, keywords

    def normalize_integer_index_value(self, source, value):
        if _ACTIVE_ENVIRONMENT.get().name != "js" or not any(
            python_builtins.is_int64_format(numeric)
            for numeric in possible_numeric_formats((value,))
        ):
            return value
        helper = resolve_imported(python_builtins.integer_index, self.module)
        assert isinstance(helper, Function)
        if not helper.signature_analyzed:
            raise DependencyError(helper)
        return self.call_node(
            source,
            analyzed_value_type(value),
            func=Name(helper, runtime_dependency=helper),
            args=[value],
            keywords=[],
            dependency_objects=self.inline_dependencies(helper, source),
        )

    def normalize_float_argument(self, source, value, expected_type):
        if (
            _ACTIVE_ENVIRONMENT.get().name != "js"
            or not isinstance(expected_type, Class)
            or expected_type.generic_name != "float"
            or not any(
                python_builtins.is_int64_format(numeric)
                for numeric in possible_numeric_formats((value,))
            )
        ):
            return value
        helper = BUILTINS.search("float_operand")
        assert isinstance(helper, Function)
        if not helper.signature_analyzed:
            raise DependencyError(helper)
        return self.call_node(
            source,
            expected_type,
            func=Name(helper),
            args=[value],
            keywords=[],
            dependency_objects=self.inline_dependencies(helper, source),
        )

    def reduce_large_modular_operand(self, node, source, storage_format):
        if (
            _ACTIVE_ENVIRONMENT.get().name != "js"
            or storage_format.kind != "integer"
            or storage_format.bits == 64
            or analyzed_numeric_format(node) is not None
        ):
            return node
        value = integer_literal(source)
        if value is None or abs(value) <= 2**53 - 1:
            return node
        return Constant(
            BUILTINS.search("int"),
            value=wrapped_integer_value(value, storage_format),
        )

    def normalize_array_value(
        self,
        node: ast.expr,
        storage_format: ArrayFormat | None,
        item_representation: ValueRepresentation | None = None,
        item_type: Class | UnionType | None = None,
    ) -> ast.expr:
        value_format = analyzed_array_format(node)
        if storage_format is None:
            return node
        if value_format is not None and value_format != storage_format:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "different static array types cannot be assigned implicitly",
                help="Convert or copy the value to the destination array type.",
            )
        if isinstance(node, (List, Tuple)):
            item_count = 0
            for item in node.elts:
                if not isinstance(item, Starred):
                    item_count += 1
                    continue
                expanded = analyzed_array_format(item.value)
                if expanded is None:
                    self.fail(
                        getattr(item, "python_node", item),
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        "StaticArray starred values require a statically known length",
                        help="Spread another StaticArray or list every item explicitly.",
                    )
                item_count += expanded.length
            if item_count != storage_format.length:
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    f"Static array requires {storage_format.length} items, "
                    f"got {item_count}",
                    help="Provide exactly the declared number of items.",
                )
            stored_item = item_representation or direct_representation(
                storage_format.item_numeric,
                storage_format.item_array,
            )
            normalized_items = []
            for item in node.elts:
                if isinstance(item, Starred):
                    if analyzed_representation(item) != stored_item:
                        self.fail(
                            getattr(item, "python_node", item),
                            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                            "Starred StaticArray items use an incompatible "
                            "representation",
                            help=(
                                "Convert each item explicitly before spreading the array."
                            ),
                        )
                    normalized_items.append(item)
                else:
                    normalized_items.append(
                        self.normalize_representation(item, stored_item, item_type)
                    )
            node.elts = normalized_items
        elif value_format is None:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "A static array requires a statically sized value",
                help="Use a matching StaticArray value or a fixed-size literal.",
            )
        representation = array_representation(
            storage_format,
            item_representation,
        )
        apply_representation(node, representation)
        value = analyzed_value_object(node)
        if isinstance(value, Instance):
            apply_representation(value, representation)
        return node

    def normalize_union_representation(
        self,
        node: ast.expr,
        representation: ValueRepresentation,
        expected_type: Class | UnionType | None,
    ) -> ast.expr:
        arguments = representation.arguments
        actual = analyzed_representation(node)
        actual_type = analyzed_value_type(node)
        expected_members = (
            tuple(get_type_members(expected_type))
            if expected_type is not None
            else ()
        )
        if isinstance(actual_type, UnionType) and len(expected_members) == len(arguments):
            # A union is not a scalar: narrowing int8 must leave None, str and
            # reference alternatives alone. Reuse ordinary typed conditionals
            # and lexical single-evaluation bindings rather than backend casts
            # of the whole tagged value or metadata changes on its source.
            targets = []
            for member in actual_type.types:
                matching = [(target, candidate) for target, candidate in
                            zip(expected_members, arguments, strict=True)
                            if is_return_type_compatible(target, member)]
                exact = [item for item in matching if same_analyzer_type(member, item[0])]
                matching = exact or matching
                if len(matching) != 1:
                    break
                targets.append((member, *matching[0]))
            else:
                if all(representation_for_member(actual_type, actual, member) == candidate
                       for member, _, candidate in targets):
                    return node
                temporary_obj = actual_type("$union_value", self.scope, self.func)
                apply_representation(temporary_obj, actual)
                temporary = Name(temporary_obj, ctx=ast.Load())
                # Test bool before its int parent. Unchanged alternatives need
                # no runtime class check (including None and generic containers).
                targets.sort(key=lambda item: not is_builtin_class(item[0], "bool"))
                branches, unchanged = [], []
                for member, target, candidate in targets:
                    source_representation = representation_for_member(actual_type, actual, member)
                    if source_representation == candidate and not is_builtin_class(member, "bool"):
                        unchanged.append(member)
                        continue
                    narrowed = ast.copy_location(StaticCast(member, temporary), node)
                    set_analyzed_representation(narrowed, source_representation)
                    branches.append((member, self.normalize_stored_value(
                        node, narrowed, candidate, target,
                    )))
                if unchanged:
                    remainder = UnionType(types=unchanged).type
                    result = StaticCast(remainder, temporary)
                    set_analyzed_representation(result,
                        narrowed_representation(actual_type, actual, remainder))
                else:
                    _, result = branches.pop()
                for member, converted in reversed(branches):
                    test = self.visit(ast.copy_location(ast.Call(
                        func=AnalyzedExpression(Name(BUILTINS.search("isinstance"))),
                        args=[AnalyzedExpression(temporary), AnalyzedExpression(Name(member))],
                        keywords=[],
                    ), node))
                    result = IfExp(expected_type, expected_type, test=test, body=converted, orelse=result)
                    set_analyzed_representation(result, representation)
                result = EvaluateOnce(expected_type, node, result, temporary.id)
                set_analyzed_representation(result, representation)
                return ast.copy_location(result, node)
        if len(expected_members) == len(arguments):
            matching = [
                (member, candidate)
                for member, candidate in zip(
                    expected_members,
                    arguments,
                    strict=True,
                )
                if is_return_type_compatible(member, actual_type)
                or expects_iterable(member)
                and is_iterable_argument_compatible(member, actual_type)
                or isinstance(node, Dict)
                and isinstance(member, TypedDictClass)
            ]
            exact = [
                candidate
                for candidate in matching
                if same_analyzer_type(candidate[0], actual_type)
            ]
            if exact:
                matching = exact
            if len(matching) == 1:
                member, candidate = matching[0]
                if candidate == actual:
                    return node
                if candidate is None:
                    self.fail(
                        getattr(node, "python_node", node),
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        "Value uses an incompatible represented union member",
                        help=(
                            "Convert the value explicitly to the selected "
                            "union member."
                        ),
                    )
                return self.normalize_representation(
                    node,
                    candidate,
                    member,
                )
            if isinstance(actual_type, UnionType) and not representations_conflict(
                (
                    (actual_type, actual),
                    (expected_type, representation),
                )
            ):
                return node
        if isinstance(node, Constant) and node.value is None:
            return node
        candidates = [argument for argument in arguments if argument is not None]
        if actual in candidates:
            return node
        if actual is not None:
            matching = [
                candidate
                for candidate in candidates
                if candidate.direct is not None
                and actual.direct is not None
                and type(candidate.direct) is type(actual.direct)
            ]
        else:
            matching = candidates
        if len(matching) == 1 and expected_type is not None and not isinstance(actual_type, UnionType):
            return self.normalize_representation(node, matching[0])
        self.fail(
            getattr(node, "python_node", node),
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            "Value has an ambiguous represented union type",
            help="Convert the value explicitly to one represented union member.",
        )

    def normalize_record_representation(
        self,
        node: ast.expr,
        representation: ValueRepresentation,
        expected_type: Class | UnionType | None,
    ) -> ast.expr:
        fields = dict(representation.fields)
        field_types = (
            {
                name: expected_type.field_type(name)
                for name in expected_type.annotations
            }
            if isinstance(expected_type, TypedDictClass)
            else {}
        )
        if isinstance(node, Dict):
            if isinstance(expected_type, TypedDictClass):
                node.obj = expected_type
            for index, (key, value) in enumerate(
                zip(node.keys, node.values, strict=True)
            ):
                if not isinstance(key, Constant) or not isinstance(
                    key.value,
                    str,
                ):
                    self.fail(
                        getattr(key, "python_node", key) if key else node,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        "Represented TypedDict values require literal keys",
                        help="Construct the TypedDict with explicit field names.",
                    )
                node.values[index] = self.normalize_stored_value(
                    getattr(value, "python_node", value),
                    value,
                    fields.get(key.value),
                    field_types.get(key.value),
                )
        elif analyzed_representation(node) != representation:
            self.fail(
                getattr(node, "python_node", node),
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Value uses an incompatible TypedDict representation",
                help="Use the declared TypedDict field representations.",
            )
        set_analyzed_representation(node, representation)
        return node

    def normalize_fixed_tuple_representation(self, node, representation, expected_type):
        """Normalize fixed positions, including statically sized spreads."""
        types = tuple(expected_type.generic_types.values())
        representations = representation.arguments
        pending, items, offset = list(reversed(node.elts)), [], 0
        while pending:
            item = pending.pop()
            if isinstance(item, Starred) and isinstance(item.value, (Tuple, List)):
                # Flatten only fresh builtin literals, preserving operand order
                # and single evaluation. Aliases/calls must retain their value.
                pending.extend(reversed(item.value.elts))
                continue
            width = 1
            if isinstance(item, Starred):
                source_type = analyzed_value_type(item.value)
                if not is_builtin_class(source_type, "tuple") or source_type.tuple_variadic:
                    self.fail(item, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                              "Fixed tuple representations require statically sized tuple spreads",
                              help="Construct the fixed positions explicitly or spread a fixed tuple.")
                width = len(source_type.generic_types)
            if offset + width > len(types):
                self.fail(item, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "Fixed tuple literal has more items than its declared positions")
            if isinstance(item, Starred):
                expected = BUILTINS.search("tuple")(*types[offset:offset + width])
                actual = item.value
                target_representation = tuple_representation(representations[offset:offset + width])
            else:
                expected, actual = types[offset], item
                target_representation = representations[offset]
            if not is_call_argument_compatible(expected, actual):
                self.fail(item, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "Fixed tuple literal item does not match its declared type")
            normalized = self.normalize_stored_value(
                getattr(actual, "python_node", actual), actual, target_representation, expected,
            )
            if isinstance(item, Starred):
                item.value = normalized
            else:
                item = normalized
            items.append(item)
            offset += width
        if offset != len(types):
            self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                      "Fixed tuple literal has fewer items than its declared positions")
        node.obj, node.elts = expected_type, items
        set_analyzed_representation(node, representation)
        return node

    def normalize_generic_representation(
        self,
        node: ast.expr,
        representation: ValueRepresentation,
        expected_type: Class | UnionType | None,
    ) -> ast.expr:
        arguments = representation.arguments
        value_type = analyzed_value_type(node)
        if isinstance(expected_type, CallableClass):
            callback = callable_value_type(node)
            if isinstance(callback, CallableClass) and (
                expected_type.parameter_types is None
                and callback.return_representation == representation.result
                or is_return_type_compatible(expected_type, callback)
            ):
                # A callable view can omit optional source parameters. Keep
                # the actual signature/representations for backend adaptation,
                # rather than relabelling its longer ABI with the view's shape.
                # Ellipsis constrains only the resolved result representation;
                # its generic result type may still be an unbound variable here.
                return node
        generic_name = getattr(value_type, "generic_name", None)
        expected_arguments = (
            tuple(expected_type.generic_types.values())
            if isinstance(expected_type, Class) and expected_type.generic_types
            else ()
        )
        if isinstance(node, (List, Set)) and generic_name in {"list", "set"}:
            item_representation = arguments[0] if arguments else None
            item_type = expected_arguments[0] if expected_arguments else None
            node.elts = [
                self.normalize_stored_value(
                    getattr(item, "python_node", item),
                    item,
                    item_representation,
                    item_type,
                )
                for item in node.elts
            ]
        elif isinstance(node, Tuple) and generic_name == "tuple":
            if is_builtin_class(expected_type, "tuple") and not expected_type.tuple_variadic:
                return self.normalize_fixed_tuple_representation(node, representation, expected_type)
            if len(arguments) == len(node.elts):
                node.elts = [
                    self.normalize_stored_value(
                        getattr(item, "python_node", item),
                        item,
                        item_representation,
                        item_type,
                    )
                    for item, item_representation, item_type in zip(
                        node.elts,
                        arguments,
                        expected_arguments or (None,) * len(arguments),
                        strict=True,
                    )
                ]
            elif len(arguments) == 1:
                item_type = expected_arguments[0] if expected_arguments else None
                node.elts = [
                    self.normalize_stored_value(
                        getattr(item, "python_node", item),
                        item,
                        arguments[0],
                        item_type,
                    )
                    for item in node.elts
                ]
        elif isinstance(node, Dict) and generic_name == "dict":
            key_representation = arguments[0] if len(arguments) > 0 else None
            item_representation = arguments[1] if len(arguments) > 1 else None
            key_type = expected_arguments[0] if expected_arguments else None
            item_type = expected_arguments[1] if len(expected_arguments) > 1 else None
            node.keys = [
                self.normalize_stored_value(
                    getattr(key, "python_node", key), key, key_representation, key_type
                )
                if key is not None
                else None
                for key in node.keys
            ]
            node.values = [
                self.normalize_stored_mapping(
                    getattr(value, "python_node", value), value,
                    key_representation, item_representation, key_type, item_type,
                )
                if key is None else
                self.normalize_stored_value(
                    getattr(value, "python_node", value),
                    value,
                    item_representation,
                    item_type,
                )
                for key, value in zip(node.keys, node.values, strict=True)
            ]
        elif analyzed_representation(node) != representation:
            self.fail(
                getattr(node, "python_node", node),
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Value uses an incompatible nested representation",
                help="Convert each represented value explicitly.",
            )
        set_analyzed_representation(node, representation)
        return node

    def normalize_representation(
        self,
        node: ast.expr,
        representation: ValueRepresentation | None,
        expected_type: Class | UnionType | None = None,
    ) -> ast.expr:
        from .iterable_protocol import retain_iterable_conversion
        retain_iterable_conversion(node, expected_type)
        destinations = [member for member in get_type_members(expected_type)
                        if isinstance(member, Class) and member.generic_name != "NoneType"]
        if len(destinations) == 1 and destinations[0].generic_name == "Iterator":
            item = representation_for_member(expected_type, representation, destinations[0])
            expected_item = item.item_representation if item is not None else None
            converted = False
            for actual in get_type_members(analyzed_value_type(node)):
                if actual.generic_name in {"NoneType", "Iterator", "Generator"}:
                    continue
                protocol = iterable_protocol(actual, iterator=True)
                if protocol is None:
                    continue
                if protocol.representation_conflict or (
                    protocol.item_representation != expected_item
                    and not self.permits_reference_erasure(
                        protocol.item_representation, next(iter(destinations[0].generic_types.values())),
                    )
                ):
                    self.fail(
                        getattr(node, "python_node", node), DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        "Custom iterator items use an incompatible representation",
                        help="Match Iterator's item annotation to __next__ or explicitly convert yielded values.",
                    )
                converted = True
            if converted:
                # Interface storage and returns need the protocol even without
                # a direct call. Keep the concrete source layout on the node;
                # a backend may need an adapter at the destination boundary.
                node.conversion_methods = self.argument_protocol_methods(destinations[0], node)
                return node
        if representation is None:
            if isinstance(node, (List, Set, Tuple, Dict)) and analyzed_representation(node) is None:
                literal_type = contextual_collection_type(
                    expected_type, getattr(analyzed_value_type(node), "generic_name", None),
                )
                if literal_type is not None and not isinstance(literal_type, TypedDictClass):
                    # A plain destination can still contain protocol views.
                    # Normalize fresh members rather than silently dropping
                    # their conversion contracts with the empty numeric map.
                    self.normalize_generic_representation(
                        node, ValueRepresentation(kind="generic", arguments=(None,) * len(literal_type.generic_types)),
                        literal_type,
                    )
                    set_analyzed_representation(node, None)
            return node
        if (
            representation.kind != "union"
            and expected_type is not None
            and (expects_iterable(expected_type)
                 or isinstance(expected_type, Class) and expected_type.generic_name == "Iterator")
        ):
            # Iterator views constrain yielded items, not a Generator's extra
            # send/completion metadata. Keep the source's full representation.
            protocol = analyzed_iterable_protocol(node)
            expected_item = representation.item_representation
            if (
                protocol is not None
                and not protocol.representation_conflict
                and protocol.item_representation == expected_item
                and not isinstance(node, (List, Set, Tuple, Dict))
            ):
                return node
        if representation.numeric is not None:
            return self.normalize_numeric_value(node, representation.numeric)
        if representation.array is not None:
            item_type = (
                next(iter(expected_type.generic_types.values()))
                if isinstance(expected_type, Class) and expected_type.generic_types
                else None
            )
            return self.normalize_array_value(
                node,
                representation.array,
                representation.arguments[0] if representation.arguments else None,
                item_type,
            )

        if representation.kind == "union":
            return self.normalize_union_representation(
                node,
                representation,
                expected_type,
            )

        if representation.kind == "record":
            return self.normalize_record_representation(
                node,
                representation,
                expected_type,
            )

        return self.normalize_generic_representation(
            node,
            representation,
            expected_type,
        )

    @staticmethod
    def permits_reference_erasure(representation, expected_type):
        return representation is not None and not representation.direct_numeric_formats and any(
            getattr(member, "generic_name", None) == "object"
            for member in get_type_members(expected_type)
        )

    def normalize_stored_value(
        self,
        source,
        value,
        representation: ValueRepresentation | None,
        expected_type: Class | UnionType | None = None,
    ):
        if isinstance(value, Starred):
            # A spread contributes iterable items, not a scalar expression.
            # Normalize fresh nested literals, but validate an aliased iterable
            # without changing its storage or wrapping the spread in a cast.
            value.value = self.normalize_stored_iterable(
                source, value.value, representation, expected_type,
            )
            protocol = self.require_iterable(source, value.value)
            value_type = analyzed_value_type(value.value)
            # Tuple emptiness survives aliases and calls. Empty mutable
            # containers are proven empty only while they are fresh literals.
            empty = ((is_builtin_class(value_type, "tuple") and not value_type.generic_types)
                     or isinstance(value.value, (List, Set)) and not value.value.elts)
            value.obj = expected_type if empty and expected_type is not None else protocol.item_type
            set_analyzed_representation(value, representation if empty else protocol.item_representation)
            value.runtime_methods = protocol.methods
            return value
        actual = analyzed_representation(value)
        if representation is None and actual is not None:
            if self.permits_reference_erasure(actual, expected_type):
                # Erasing a reference's static type does not change the layout
                # or arithmetic of its contents. Portable scalars themselves
                # still require conversion before entering ordinary storage.
                return value
            literal_type = contextual_collection_type(
                # A contextual TypedDict has its record's nominal name already,
                # but still uses dictionary-literal field normalization.
                expected_type, "dict" if isinstance(value, Dict)
                else getattr(analyzed_value_type(value), "generic_name", None),
            ) if isinstance(value, (List, Set, Tuple, Dict)) else None
            if literal_type is not None:
                # Fresh literals can populate erased member slots one by one;
                # an aliased collection cannot change its existing item layout.
                if isinstance(literal_type, TypedDictClass):
                    self.normalize_record_representation(
                        value, ValueRepresentation(kind="record"), literal_type,
                    )
                else:
                    self.normalize_generic_representation(
                        value,
                        ValueRepresentation(
                            kind="generic", arguments=(None,) * len(literal_type.generic_types),
                        ),
                        literal_type,
                    )
                # Empty member maps are traversal shapes, not representations.
                set_analyzed_representation(value, None)
                return value
            self.fail(
                source,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Stored value uses an incompatible representation",
                help="Convert it to the destination's declared type before storing it.",
            )
        return self.normalize_representation(value, representation, expected_type)

    def normalize_mapping_key(self, source, mapping, key):
        representation = analyzed_representation(mapping)
        expected = (
            representation.arguments[0]
            if representation is not None and representation.arguments
            else None
        )
        mapping_type = analyzed_value_type(mapping)
        expected_type = (
            mapping_type.generic_types["K"]
            if isinstance(mapping_type, Class)
            else None
        )
        return self.normalize_comparison_value(
            source,
            key,
            expected_type,
            expected,
            message="Dictionary lookup uses an incompatible key representation",
            help_text="Convert the key to the dictionary's key type first.",
        )

    def normalize_comparison_value(
        self,
        source,
        value,
        expected_type,
        expected_representation,
        *,
        message,
        help_text,
    ):
        actual_representation = analyzed_representation(value)
        if actual_representation == expected_representation:
            return value
        value_type = analyzed_value_type(value)
        # A missing union arm is not a representation conflict, but it is not
        # permission to skip normalization either (e.g. float querying int64).
        # Limit this shortcut to scalar arms: compound key equality has its own
        # backend contract and is not established by matching representation.
        if (isinstance(expected_type, UnionType)
                and all(any(is_builtin_class(actual, name)
                            for name in ("bool", "int", "float", "str", "bytes", "NoneType"))
                        and any(same_erased_type(actual, expected)
                            for expected in expected_type.types)
                        for actual in get_type_members(value_type))
                and not representations_conflict((
            (expected_type, expected_representation),
            (value_type, actual_representation),
        ))):
            return value
        expected_numeric = (
            expected_representation.numeric
            if expected_representation is not None
            else None
        )
        actual_numeric = (
            actual_representation.numeric
            if actual_representation is not None
            else None
        )
        numeric = expected_numeric or actual_numeric
        ordinary_type = value_type if expected_numeric is not None else expected_type
        allowed = (
            {"bool", "int"}
            if numeric is not None and numeric.kind == "integer"
            else {"bool", "float", "int"}
        )
        ordinary_members = (
            get_type_members(ordinary_type)
            if isinstance(ordinary_type, (Class, UnionType))
            else ()
        )
        if (
            numeric is not None
            and {expected_numeric, actual_numeric} == {None, numeric}
            and ordinary_members
            and all(member.generic_name in allowed for member in ordinary_members)
        ):
            if python_builtins.is_int64_format(expected_numeric):
                return self.coerce_int64_operand(value, expected_numeric, source)
            if python_builtins.is_int64_format(actual_numeric):
                if all(member.generic_name == "float" for member in ordinary_members):
                    return self.normalize_float_argument(
                        source,
                        value,
                        BUILTINS.search("float"),
                    )
                return self.normalize_integer_index_value(source, value)
            return value
        self.fail(
            source,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            message,
            help=help_text,
        )

    def normalize_stored_iterable(
        self,
        source,
        value,
        item_representation: ValueRepresentation | None,
        item_type: Class | UnionType | None = None,
    ):
        value_type = analyzed_value_type(value)
        if is_builtin_class(value_type, "tuple") and not value_type.generic_types:
            # This remains empty through aliases and native expansion temporaries;
            # it contributes no storage whose representation could conflict.
            return value
        if isinstance(value, List) and not value.elts and item_type is not None:
            # An Iterable parameter alone need not specialize a fresh empty
            # list. The destination's item contract supplies its allocation type.
            self.apply_literal_type(value, BUILTINS.search("list")(item_type))
        protocol = self.require_iterable(source, value)
        if protocol.item_representation == item_representation:
            return value
        if (isinstance(item_type, UnionType)
                and all(any(same_analyzer_type(actual, expected)
                            for expected in get_type_members(item_type))
                        for actual in get_type_members(protocol.item_type))
                and not representations_conflict(((item_type, item_representation),
                    (protocol.item_type, protocol.item_representation)))):
            # Copying an existing union member preserves its representation;
            # the union wrapper alone is not a numeric-domain mismatch. Leave
            # the source's own metadata intact, including nested mutable items.
            return value
        expected = compound_representation(arguments=(item_representation,))
        if expected is not None and isinstance(value, (List, Set, Tuple)):
            value_type = analyzed_value_type(value)
            expected_type = value_type
            if item_type is not None:
                collection_type = BUILTINS.search(value_type.generic_name)
                assert isinstance(collection_type, GenericClass)
                if isinstance(value, Tuple):
                    # A fresh fixed tuple needs one type/representation per
                    # position. A spread's AST position is not its runtime
                    # arity; all yielded items share the requested item view.
                    if any(isinstance(item, Starred) for item in value.elts):
                        expected_type = collection_type(item_type, tuple_variadic=True)
                        self.apply_literal_type(value, expected_type)
                    else:
                        expected_type = collection_type(*([item_type] * len(value.elts)))
                else:
                    expected_type = collection_type(item_type)
            if isinstance(value, Tuple) and not expected_type.tuple_variadic:
                expected = tuple_representation((item_representation,) * len(value.elts))
            result = self.normalize_representation(value, expected, expected_type)
            self.apply_literal_type(result, expected_type)
            return result
        self.fail(
            source,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            "Stored iterable items use an incompatible representation",
            help=("Convert each item to the collection's item type before storing it."),
        )

    def normalize_stored_mapping(
        self,
        source,
        value,
        key_representation: ValueRepresentation | None,
        value_representation: ValueRepresentation | None,
        key_type: Class | UnionType | None = None,
        value_type: Class | UnionType | None = None,
    ):
        expected = compound_representation(
            arguments=(key_representation, value_representation)
        )
        if analyzed_representation(value) == expected:
            return value
        actual = analyzed_representation(value)
        if actual is not None and len(actual.arguments) == 2 and all(
            source_rep == target_rep or (
                target_rep is None and self.permits_reference_erasure(source_rep, target_type)
            )
            for source_rep, target_rep, target_type in zip(
                actual.arguments, (key_representation, value_representation),
                (key_type, value_type), strict=True,
            )
        ):
            # A spread/update copies members, not the mapping reference. Only
            # reference-valued members may enter erased destination slots.
            return value
        if expected is not None and isinstance(value, Dict):
            mapping_type = analyzed_value_type(value)
            expected_type = mapping_type
            if key_type is not None and value_type is not None:
                collection_type = BUILTINS.search(mapping_type.generic_name)
                assert isinstance(collection_type, GenericClass)
                expected_type = collection_type(key_type, value_type)
            return self.normalize_representation(value, expected, expected_type)
        self.fail(
            source,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            "Stored mapping items use incompatible representations",
            help=(
                "Convert each key and value to the destination dictionary's "
                "types before storing them."
            ),
        )

    def normalize_lowered_method_arguments(
        self,
        sources,
        arguments,
        function: Function,
        receiver,
    ):
        integer_index_parameters = analysis_metadata(
            function.py_obj,
            "integer_index_parameters",
            (),
        )
        if integer_index_parameters:
            arguments = [
                self.normalize_integer_index_value(source, argument)
                if parameter.arg in integer_index_parameters
                else argument
                for source, argument, parameter in zip(
                    sources,
                    arguments,
                    function.params,
                    strict=True,
                )
            ]
        if function.analysis is not None:
            return arguments
        type_bindings = {}
        representation_bindings = {}
        if function.cls is not None:
            receiver_type = analyzed_value_type(receiver)
            infer_type_variables(function.cls, receiver_type, type_bindings)
            infer_representation_variables(
                function.cls,
                receiver_type,
                analyzed_representation(receiver),
                representation_bindings,
            )
        normalized = []
        for source, argument, parameter in zip(
            sources,
            arguments,
            function.params,
            strict=True,
        ):
            expected_type = substitute_type_variables(
                parameter.annotation.obj,
                type_bindings,
            )
            expected_representation = substitute_representation_variables(
                parameter.annotation.obj,
                getattr(parameter, "representation", None),
                representation_bindings,
            )
            if not accepts_static_array_argument(function):
                self.reject_static_array_widening(
                    source,
                    argument,
                    expected_type,
                    analyzed_array_format(parameter),
                )
            normalized.append(
                self.normalize_parameter_value(
                    source,
                    argument,
                    expected_representation,
                    expected_type,
                    representation_aware=representation_aware_function(function),
                )
            )
        return normalized

    def merge_expression_representations(
        self,
        source: ast.AST,
        result_type: Class | UnionType,
        values,
        description: str,
    ) -> ValueRepresentation | None:
        typed_representations = tuple(
            (analyzed_value_type(value), analyzed_representation(value))
            for value in values
        )
        return self.merge_typed_representations(
            source,
            result_type,
            typed_representations,
            description,
        )

    def merge_typed_representations(
        self,
        source: ast.AST,
        result_type: Class | UnionType,
        typed_representations,
        description: str,
    ) -> ValueRepresentation | None:
        typed_representations = tuple(typed_representations)
        if representations_conflict(typed_representations):
            self.fail(
                source,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"{description} use incompatible nested representations",
                help=(
                    "Convert the values to one represented type before combining them."
                ),
            )
        return merged_representation(result_type, typed_representations)

    def validate_compound_representation(
        self,
        node: ast.expr,
        value_type: Class | UnionType,
        representation: ValueRepresentation | None,
    ) -> None:
        if representation is None or representation.direct is not None:
            return
        if representation.kind == "record":
            if not isinstance(value_type, TypedDictClass):
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "Record representation requires a TypedDict type",
                )
            fields = dict(representation.fields)
            if fields.keys() != value_type.annotations.keys():
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "TypedDict representation has incompatible fields",
                )
            for name in value_type.annotations:
                self.validate_compound_representation(
                    node,
                    value_type.field_type(name),
                    fields[name],
                )
            return
        if representation.kind == "union":
            members = tuple(get_type_members(value_type))
            if len(members) != len(representation.arguments):
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "Union members use indistinguishable represented types",
                    help=(
                        "Use one represented type at this boundary, or use "
                        "ordinary Python values throughout the union."
                    ),
                )
            if representations_conflict(
                zip(members, representation.arguments, strict=True)
            ):
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "Union members use indistinguishable represented types",
                    help=(
                        "Use one represented type at this boundary, or use "
                        "ordinary Python values throughout the union."
                    ),
                )
            for member, child in zip(
                members,
                representation.arguments,
                strict=True,
            ):
                self.validate_compound_representation(node, member, child)
            return
        if isinstance(value_type, CallableClass):
            if representation.parameters is not None:
                for parameter_type, child in zip(
                    value_type.parameter_types or (),
                    representation.parameters,
                    strict=True,
                ):
                    self.validate_compound_representation(
                        node,
                        parameter_type,
                        child,
                    )
            self.validate_compound_representation(
                node,
                value_type.return_type,
                representation.result,
            )
            return
        if not isinstance(value_type, Class):
            return
        members = tuple((value_type.generic_types or {}).values())
        if len(members) != len(representation.arguments):
            return
        for member, child in zip(
            members,
            representation.arguments,
            strict=True,
        ):
            self.validate_compound_representation(node, member, child)

    def reject_static_array_widening(
        self,
        source: ast.AST,
        value: ast.expr,
        storage_type,
        storage_format: ArrayFormat | None,
    ) -> None:
        if (
            analyzed_array_format(value) is None
            or storage_format is not None
            or not isinstance(storage_type, Class)
            or storage_type.generic_name != "list"
        ):
            return
        self.fail(
            source,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            "StaticArray cannot be widened to a mutable list",
            help=(
                "Keep the matching StaticArray type, or explicitly convert "
                "each item while building an ordinary list."
            ),
        )

    def reject_unpreserved_collection_items(
        self,
        source: ast.AST,
        value: ast.expr,
    ) -> None:
        if analyzed_array_format(value) is not None:
            return
        if analyzed_representation(value) is not None:
            return
        if not collection_contains_numeric_format(value):
            return
        self.fail(
            source,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "This collection boundary cannot preserve represented item types",
            help=(
                "Keep the represented item annotation through this operation, "
                "or convert each item explicitly."
            ),
        )

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

    def record_native_attribute(
        self,
        name,
        value_type,
        *,
        declared=False,
        storage_representation=None,
    ):
        assert self.func.cls is not None
        attribute = value_type(name, self.func.cls.scope, self.func.cls._self)
        attribute.has_declared_type = declared
        representation = (
            storage_representation
            if storage_representation is not None
            else self.func.cls.field_representations.get(name)
        )
        apply_representation(attribute, representation)
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
                value_type = self.analyze_assignment_value(value, annotation).storage_type
            except DependencyError:
                raise
            except CompilationError, NameError:
                if annotation is not None:
                    raise
                continue
            assert value_type is not None
            representation = self.annotation_representation(annotation)
            self.record_native_attribute(
                target.attr,
                value_type,
                declared=annotation is not None,
                storage_representation=representation,
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
        self.func.set_return_representation(
            self.annotation_representation(node.returns)
        )
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
        if declared_return_type is not None and node.returns is not None:
            self.validate_compound_representation(
                node.returns,
                declared_return_type,
                self.func.return_representation,
            )
        self.func.declared_return_type = declared_return_type
        self.func.inferred_return_type = None
        self.func.return_type = None

        pos_params = [*node.args.posonlyargs, *node.args.args]
        no_defaults = len(pos_params) - len(defaults)
        pos_defaults = [None] * no_defaults + defaults

        if self.func.is_method:
            if self.func.is_classmethod:
                if not pos_params or pos_params[0].arg != "cls":
                    self.fail(
                        pos_params[0] if pos_params else node,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        "PyJS class methods require a first parameter named 'cls'",
                        help="Add or rename the first parameter to cls.",
                    )
            elif self.func.is_staticmethod:
                pass
            elif not pos_params or pos_params[0].arg != "self":
                self.fail(
                    pos_params[0] if pos_params else node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "PyJS instance methods require a first parameter named 'self'",
                    help=(
                        "Add or rename the first parameter to self, or decorate "
                        "the method with @staticmethod."
                    ),
                )

        for i, (param, default) in enumerate(zip(pos_params, pos_defaults, strict=True)):
            if i == 0 and param.arg == "self" and self.func.is_method:
                self.func.add_self()
                continue
            if i == 0 and param.arg == "cls" and self.func.is_classmethod:
                self.func.add_cls()
                continue
            arg_type = self.infer_parameter_type(param, default)
            argument = ast.arg(
                arg=param.arg,
                annotation=analyzed_annotation(arg_type),
            )
            apply_representation(
                argument,
                self.annotation_representation(param.annotation),
            )
            self.validate_compound_representation(
                param.annotation,
                arg_type,
                argument.representation,
            )
            self.func.params.append(argument)
            value = arg_type(param.arg, self.func.scope, self.func)
            apply_representation(value, argument.representation)
            value.has_declared_type = param.annotation is not None
            self.func.scope.add(value)

        positional_only = {parameter.arg for parameter in node.args.posonlyargs}
        self.func.posonly_count = sum(
            parameter.arg in positional_only for parameter in self.func.params
        )

        if node.args.vararg is not None:
            item_type = self.infer_parameter_type(
                node.args.vararg,
                fallback=BUILTINS.search("object"),
            )
            arg_type = BUILTINS.search("tuple")(
                item_type,
                tuple_variadic=True,
            )
            item_representation = self.annotation_representation(
                node.args.vararg.annotation
            )
            if node.args.vararg.annotation is not None:
                self.validate_compound_representation(
                    node.args.vararg.annotation,
                    item_type,
                    item_representation,
                )
            self.func.vararg = ast.arg(
                arg=node.args.vararg.arg,
                annotation=analyzed_annotation(arg_type),
            )
            apply_representation(
                self.func.vararg,
                tuple_representation((item_representation,)),
            )
            value = arg_type(node.args.vararg.arg, self.func.scope, self.func)
            apply_representation(value, self.func.vararg.representation)
            value.has_declared_type = node.args.vararg.annotation is not None
            self.func.scope.add(value)

        for param, default in zip(node.args.kwonlyargs, kw_defaults, strict=True):
            arg_type = self.infer_parameter_type(param, default)
            argument = ast.arg(
                arg=param.arg,
                annotation=analyzed_annotation(arg_type),
            )
            apply_representation(
                argument,
                self.annotation_representation(param.annotation),
            )
            self.validate_compound_representation(
                param.annotation,
                arg_type,
                argument.representation,
            )
            self.func.kwonlyargs.append(argument)
            value = arg_type(param.arg, self.func.scope, self.func)
            apply_representation(value, argument.representation)
            value.has_declared_type = param.annotation is not None
            self.func.scope.add(value)

        if node.args.kwarg is not None:
            value_type = self.infer_parameter_type(
                node.args.kwarg,
                fallback=BUILTINS.search("object"),
            )
            arg_type = BUILTINS.search("dict")(BUILTINS.search("str"), value_type)
            item_representation = self.annotation_representation(
                node.args.kwarg.annotation
            )
            if node.args.kwarg.annotation is not None:
                self.validate_compound_representation(
                    node.args.kwarg.annotation,
                    value_type,
                    item_representation,
                )
            self.func.kwarg = ast.arg(
                arg=node.args.kwarg.arg,
                annotation=analyzed_annotation(arg_type),
            )
            apply_representation(
                self.func.kwarg,
                compound_representation(arguments=(None, item_representation)),
            )
            value = arg_type(node.args.kwarg.arg, self.func.scope, self.func)
            apply_representation(value, self.func.kwarg.representation)
            value.has_declared_type = node.args.kwarg.annotation is not None
            self.func.scope.add(value)
        default_parameters = self.func.params[len(self.func.params) - len(defaults) :]

        def normalize_default(default, parameter):
            if (
                isinstance(default, Call)
                and isinstance(default.func, Name)
                and default.func.obj.py_obj is python_builtins._dataclass_missing
            ):
                return default
            return self.normalize_representation(
                default,
                getattr(parameter, "representation", None),
                parameter.annotation.obj,
            )

        self.func.defaults = defaults = [
            normalize_default(default, parameter)
            for default, parameter in zip(defaults, default_parameters, strict=True)
        ]
        self.func.kw_defaults = kw_defaults = [
            normalize_default(default, parameter) if default is not None else None
            for default, parameter in zip(
                kw_defaults,
                self.func.kwonlyargs,
                strict=True,
            )
        ]
        self.func.signature_analyzed = True
        function_body = without_docstring(node.body)
        if should_analyze_target_body(self.func):
            self.func.body = self.visit_body(function_body)
            if self.func.is_generator:
                final_return_type = self.inferred_generator_type()
                declared_yield_representation = (
                    self.func.return_representation.arguments[0]
                    if self.func.return_representation is not None
                    and self.func.return_representation.arguments
                    else None
                )
                self.func.yield_representation = (
                    declared_yield_representation
                    if self.func.declared_return_type is not None
                    else self.inferred_return_representation(
                        self.func.yield_type or get_none_type(),
                        self.func.yield_values,
                    )
                )
                if self.func.declared_return_type is None:
                    self.func.set_return_representation(
                        self.inferred_generator_representation()
                    )
            else:
                final_return_type = self.func.inferred_return_type
                # Infer nominal returns from ordinary control flow. Potential
                # exceptions from arbitrary expressions are not an effect
                # inference system; refinements use the conservative default.
                if body_can_fall_through(self.func.body, exception_sensitive=False):
                    if declared_return_type is None:
                        self.func.inferred_return_values.append((get_none_type(), None))
                    final_return_type = merge_return_types(
                        final_return_type,
                        get_none_type(),
                    )
                final_return_type = (
                    final_return_type or declared_return_type or get_none_type()
                )
            if declared_return_type is not None and not is_interface_stub_body(
                function_body
            ):
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
                            "Change the return annotation to match the yielded, sent, and completion values."
                            if getattr(declared_return_type, "generic_name", None) == "Generator" else
                            "Change the return annotation to match the yielded values."
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
            if declared_return_type is None and not self.func.is_generator:
                self.func.set_return_representation(
                    self.inferred_return_representation(final_return_type)
                )
            self.func.return_type = declared_return_type or final_return_type
        else:
            if not self.func.name == "__init__":
                target = _ACTIVE_ENVIRONMENT.get().name
                native = is_native_for(self.func.py_func, target) or (
                    self.func.cls is not None
                    and is_native_for(self.func.cls.py_obj, target)
                )
                if node.returns is None and not native:
                    self.fail(
                        node,
                        DiagnosticCode.TYPE_ANNOTATION_REQUIRED,
                        f"Function {self.func.name!r} requires a return type annotation",
                        help=(
                            "Add -> ReturnType so PyJS can type-check calls to this "
                            "source or inline implementation."
                        ),
                    )
                self.func.return_type = declared_return_type or get_none_type()
            else:
                if self.func.cls is not None and is_native_for(
                    self.func.cls.py_obj,
                    _ACTIVE_ENVIRONMENT.get().name,
                ):
                    self.collect_native_attributes(function_body)
                self.func.return_type = self.func.cls

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self.visit_FunctionDef(node)

    def visit_Await(self, node: ast.Await):
        value = self.visit(node.value)
        awaitable_type = analyzed_value_type(value)
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
        result = Await(
            awaited_type,
            value_obj=value_obj,
            value=value,
        )
        representation = analyzed_representation(value)
        if representation is not None and representation.arguments:
            set_analyzed_representation(result, representation.arguments[0])
        return result

    def fail_invalid_type_annotation(self, node):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            f"{ast.unparse(node)!r} is not a supported type annotation",
            help="Use a class, union, or supported generic type annotation.",
        )

    def visit_type_annotation(self, node):
        previous = self.in_type_annotation
        self.in_type_annotation = True
        try:
            return self._visit_type_annotation(node)
        finally:
            self.in_type_annotation = previous

    def _visit_type_annotation(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            annotation = ast.parse(node.value, mode="eval").body
            ast.copy_location(annotation, node)
            return self.visit_type_annotation(annotation)
        if isinstance(node, ast.Name) and node.id == "Self":
            if not self.func.is_method:
                self.fail(
                    node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "Self annotations are only valid on methods",
                    help="Use a concrete type or move this function onto a class.",
                )
            return Name(self.func.cls)
        if isinstance(node, ast.Subscript):
            alias_name = typing_alias_name(node.value, self.scope)
            if alias_name == "Annotated":
                if not isinstance(node.slice, ast.Tuple) or len(node.slice.elts) < 2:
                    self.fail(
                        node,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        "Annotated requires a type and at least one metadata value",
                        help="Use Annotated[Type, metadata, ...].",
                    )
                return self.visit_type_annotation(node.slice.elts[0])
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
                parameter_representations = None
                if not (
                    isinstance(parameters, ast.Constant) and parameters.value is Ellipsis
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
                    parameter_representations = tuple(
                        self.annotation_representation(parameter)
                        for parameter in parameters.elts
                    )
                base = BUILTINS.search("callable")
                assert isinstance(base, Class)
                return Name(
                    CallableClass(
                        parameter_types,
                        self.visit_type_annotation(return_annotation).obj,
                        base,
                        parameter_representations,
                        self.annotation_representation(return_annotation),
                    )
                )
            if alias_name == "Literal":
                elements = (
                    node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
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
                    node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
                )
                types = [self.visit_type_annotation(element).obj for element in elements]
                if alias_name == "Optional":
                    types.append(get_none_type())
                return Name(UnionType(types=types).type)
            if alias_name in TYPING_TYPE_ALIASES:
                value = Name(BUILTINS.search(TYPING_TYPE_ALIASES[alias_name]))
            else:
                value = self.visit(node.value)
            if isinstance(value.obj, GenericClass) and hasattr(
                value.obj.py_cls, "__pyjs_array_domain__"
            ):
                return self.static_array_annotation(node, value.obj)
            if not isinstance(value.obj, GenericClass):
                value_name = ast.unparse(node.value)
                self.fail(
                    node.value,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    f"Type {value_name!r} does not accept type arguments",
                    help=f"Use {value_name!r} without square brackets.",
                )
            builtin_tuple = value.obj is BUILTINS.search("tuple")
            if isinstance(node.slice, ast.Tuple):
                elements = node.slice.elts
                tuple_variadic = (
                    builtin_tuple
                    and bool(elements)
                    and isinstance(elements[-1], ast.Constant)
                    and elements[-1].value is Ellipsis
                )
                if tuple_variadic:
                    elements = elements[:-1]
                item_types = [self.visit_type_annotation(elt).obj for elt in elements]
            elif isinstance(
                node.slice,
                (ast.Name, ast.Attribute, ast.BinOp, ast.Subscript, ast.Constant),
            ):
                elements = [node.slice]
                item_types = [self.visit_type_annotation(node.slice).obj]
            else:
                self.fail_invalid_type_annotation(node.slice)
            if not isinstance(node.slice, ast.Tuple):
                tuple_variadic = False
            expected_count = len(value.obj.generic_params)
            if not builtin_tuple and len(item_types) != expected_count:
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
            return Name(
                value.obj(
                    *item_types,
                    tuple_variadic=tuple_variadic,
                )
            )
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
                    ensure_annotation_dependencies(value.annotation, self.module)
                    value_type = value.resolve_type()
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
                except TypeError as error:
                    self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX, str(error),
                              help="Use a supported class, union or container alias.")
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
        if self.loop_break_collectors:
            base_scope, exits = self.loop_break_collectors[-1]
            snapshot_scope = LocalScope(base_scope.parent)
            scopes = []
            scope = self.scope
            while isinstance(scope, LocalScope) and scope is not base_scope.parent:
                scopes.append(scope)
                if scope is base_scope:
                    break
                scope = scope.parent
            for branch_scope in reversed(scopes):
                for name, value in branch_scope.names.items():
                    if isinstance(value, Instance):
                        value = value.reassign(name, snapshot_scope, self.func)
                    snapshot_scope.add(value, name)
            snapshot = self.child_visitor(snapshot_scope)
            if self.pending_finally_breaks:
                self.pending_finally_breaks[-1].append((exits, snapshot))
            else:
                exits.append(snapshot)
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
        return self.analyze_return_value(
            node, self.func.declared_return_type, self.func.return_representation,
            self.func.return_numeric_format, self.func.return_array_format,
        )

    def analyze_return_value(
        self, node, declared_type, representation,
        numeric_format=None, array_format=None,
    ):
        value = node.value
        if value is None:
            return_type = get_none_type()
        else:
            value = self.visit_contextual_expression(
                value,
                declared_type,
                numeric_format,
                expected_representation=representation,
            )
            if array_format is None:
                self.reject_unpreserved_collection_items(node.value, value)
            self.reject_static_array_widening(
                node.value,
                value,
                declared_type,
                array_format,
            )
            value = self.normalize_numeric_value(
                value,
                numeric_format,
            )
            value = self.normalize_array_value(
                value,
                array_format,
            )
            value = self.normalize_representation(
                value,
                representation,
                declared_type,
            )
            return_type = analyzed_value_type(value)
        if declared_type is None:
            representation = analyzed_representation(value) if value is not None else None
            if representations_conflict(
                (
                    *self.func.inferred_return_values,
                    (return_type, representation),
                )
            ):
                self.fail(
                    node.value if node.value is not None else node,
                    DiagnosticCode.INCOMPATIBLE_RETURN,
                    "Function returns incompatible value representations",
                    help=(
                        "Return one represented type for each result type, "
                        "or add an explicit conversion."
                    ),
                )
            self.func.inferred_return_values.append((return_type, representation))
        # A partial can specialize a broadly annotated target, such as tag() returning a div.
        if self.func.is_partial_client and declared_type is not None:
            return_type = declared_type
        self.func.inferred_return_type = merge_return_types(
            self.func.inferred_return_type, return_type
        )
        return ast.Return(value=value)

    def inferred_return_representation(self, return_type, values=None):
        values = self.func.inferred_return_values if values is None else values
        if not values:
            return None
        return merged_representation(return_type, values)

    def inferred_generator_type(self):
        return BUILTINS.search("Iterator")(self.func.yield_type or get_none_type())

    def inferred_generator_representation(self):
        return compound_representation(arguments=(self.func.yield_representation,))

    def visit_Yield(self, node: ast.Yield):
        declared_type = self.func.declared_return_type
        declared = self.func.return_representation
        item_representation = declared.arguments[0] if declared is not None and declared.arguments else None
        value = (
            self.visit_contextual_expression(
                node.value, declared_type.generic_types["V"] if declared_type is not None else None,
                expected_representation=item_representation,
            )
            if node.value is not None
            else self.visit(ast.Constant(value=None))
        )
        return self.analyze_yield_value(node, value)

    def analyze_yield_value(self, node, value):
        declared_type = self.func.declared_return_type
        declared = self.func.return_representation
        item_representation = declared.arguments[0] if declared is not None and declared.arguments else None
        if declared_type is not None:
            value = self.normalize_stored_value(
                node.value or node,
                value,
                item_representation,
                self.func.declared_return_type.generic_types["V"],
            )
        representation = analyzed_representation(value)
        value_type = analyzed_value_type(value)
        if representations_conflict(
            (*self.func.yield_values, (value_type, representation))
        ):
            self.fail(
                node.value if node.value is not None else node,
                DiagnosticCode.INCOMPATIBLE_RETURN,
                "Generator yields incompatible value representations",
                help=(
                    "Yield one represented type for each result type, or "
                    "add an explicit conversion."
                ),
            )
        self.func.yield_values.append((value_type, representation))
        self.func.yield_type = merge_return_types(
            self.func.yield_type,
            value_type,
        )
        return ast.Yield(value=value)

    def visit_YieldFrom(self, node: ast.YieldFrom):
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "yield from is not supported",
            help="Iterate over the value and yield each item explicitly.",
        )

    def visit_contextual_lambda(
        self,
        node,
        parameter_types,
        parameter_representations=None,
    ):
        parameters = [*node.args.posonlyargs, *node.args.args]
        if len(parameters) != len(parameter_types):
            expected_count = len(parameter_types)
            expected_parameters = "parameter" if expected_count == 1 else "parameters"
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"Lambda must declare exactly {expected_count} positional "
                f"{expected_parameters}, "
                f"got {len(parameters)}",
                help="Define the lambda with the callable's expected parameters.",
            )
        visitor = type(self)(self.func, LocalScope(self.scope))
        visitor.deferred_parent = self.scope
        parameter_representations = parameter_representations or (None,) * len(
            parameter_types
        )
        for parameter, parameter_type, representation in zip(
            parameters,
            parameter_types,
            parameter_representations,
            strict=True,
        ):
            value = parameter_type(parameter.arg, visitor.scope, self.func)
            apply_representation(value, representation)
            visitor.scope.add(value)
        expected_type = self.contextual_types.get(node)
        expected = callable_member(expected_type)
        if expected is not None:
            representation = representation_for_member(
                expected_type, self.contextual_representations.get(node), expected,
            )
            visitor.contextual_types[node.body] = expected.return_type
            visitor.contextual_representations[node.body] = (
                representation.result if representation is not None
                else expected.return_representation
            )
        value = visitor.analyze_lambda_body(node)
        body = value.body
        value.return_type = analyzed_value_type(body)
        value.parameter_types = tuple(parameter_types)
        base = BUILTINS.search("callable")
        assert isinstance(base, Class)
        value.obj = CallableClass(
            value.parameter_types,
            value.return_type,
            base,
            tuple(parameter_representations),
            analyzed_representation(body),
        )
        return value

    def analyze_lambda_body(self, node):
        return ast.Lambda(args=node.args, body=self.visit(node.body))

    def visit_Lambda(self, node: ast.Lambda):
        expected_type = self.contextual_types.get(node)
        expected = callable_member(expected_type)
        if expected is not None and expected.parameter_types is not None:
            representation = representation_for_member(
                expected_type,
                self.contextual_representations.get(node),
                expected,
            )
            return self.visit_contextual_lambda(
                node,
                expected.parameter_types,
                representation.parameters
                if representation is not None and representation.parameters is not None
                else expected.parameter_representations,
            )
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
                    help="Use a constant d, e, E, f, or % format specification.",
                )
            match = FORMAT_SPEC.fullmatch(spec)
            if match is None:
                self.fail(
                    node.format_spec,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    f"f-string format specification {spec!r} is not supported",
                    help=(
                        "Use d, e, E, f, or % with optional zero padding, "
                        "width, and precision."
                    ),
                )
            if match.group("type") == "d" and match.group("precision") is not None:
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
            ast.copy_location(value, node)
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
    # A fixed tuple's arity must not be inferred from its comparison peer.
    EMPTY_COLLECTION_NAMES = {
        ast.Dict: "dict",
        ast.List: "list",
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

    def prepare_chained_comparison_operands(self, sources, operands):
        operands = list(operands)
        for index in range(len(operands) - 1):
            pair = operands[index : index + 2]
            formats = possible_numeric_formats(pair)
            if len(formats) != 1:
                continue
            numeric = next(iter(formats))
            if not python_builtins.is_int64_format(numeric):
                continue
            for operand_index in (index, index + 1):
                operand = operands[operand_index]
                if analyzed_numeric_format(operand) is not None:
                    continue
                literal = integer_literal(sources[operand_index])
                if literal is None or abs(literal) <= 2**53 - 1:
                    continue
                operands[operand_index] = self.coerce_int64_operand(
                    operand,
                    numeric,
                    sources[operand_index],
                )
        return operands

    def visit_Compare(self, node: ast.Compare):
        assert len(node.ops) == len(node.comparators)
        sources = (node.left, *node.comparators)
        operands = []
        for index, source in enumerate(sources):
            operand = self.visit_comparison_value(
                source,
                operands[-1] if operands else None,
            )
            # Validate lookup proxies before chained comparisons replace their
            # operands with temporaries and lose the lexical super binding.
            # Implicit protocol lookup does not forward through this proxy;
            # explicit super().__contains__(value) remains a base-method call.
            if (index and isinstance(node.ops[index - 1], (ast.In, ast.NotIn))
                    and is_lexical_super_call(operand, self.func)):
                self.fail(
                    source,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "Membership on super() is not supported",
                    help="Call super().__contains__(value) explicitly to invoke the base method.",
                )
            operands.append(operand)
        if len(node.ops) > 1:
            operands = self.prepare_chained_comparison_operands(sources, operands)
            temporaries = []
            for index, operand in enumerate(operands):
                value_type = analyzed_value_type(operand)
                temporary = value_type(
                    f"$compare{index}",
                    self.scope,
                    self.func,
                )
                apply_representation(
                    temporary,
                    analyzed_representation(operand),
                )
                temporaries.append(Name(temporary, ctx=ast.Load()))
            comparisons = [
                self.analyze_comparison(
                    node,
                    temporaries[index],
                    operator,
                    temporaries[index + 1],
                    sources[index],
                    sources[index + 1],
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
        return self.analyze_comparison(
            node,
            left,
            node.ops[0],
            right,
            sources[0],
            sources[1],
        )

    @staticmethod
    def comparison_receiver(value):
        if isinstance(value.obj, Function):
            # A function value has a callable interface, not an instance of
            # the analyzer's Function declaration object.
            return callable_value_type(value)._self
        value = value.obj
        if isinstance(value, Instance):
            value_type = value.cls
            return value_type.first._self if isinstance(value_type, UnionType) else value
        if isinstance(value, UnionType):
            return value.first._self
        return value._self

    def resolve_comparison_method(
        self,
        node,
        operator,
        left,
        right,
        left_type,
        right_type,
    ):
        left_receiver = self.comparison_receiver(left)
        right_receiver = self.comparison_receiver(right)
        if isinstance(operator, (ast.In, ast.NotIn)):
            left_receiver, right_receiver = right_receiver, left_receiver
            left, right = right, left

        left_method, right_method = self.COMPARE_OPS[type(operator)]
        negate = isinstance(operator, ast.NotEq) and getattr(
            left_receiver.cls,
            "is_dataclass",
            False,
        )
        if negate:
            left_method = right_method = "__eq__"

        typed = not (
            isinstance(left_type, UnionType)
            or isinstance(right_type, UnionType)
            or isinstance(operator, (ast.Is, ast.IsNot, ast.In, ast.NotIn))
        )
        function = None
        if typed:
            try:
                function, reverse = self.resolve_binary_operator(
                    left_type,
                    right_type,
                    left_method,
                    right_method,
                    reject_object=isinstance(operator, (ast.Eq, ast.NotEq)),
                )
            except NameError:
                pass
            if function is not None and reverse:
                left, right = right, left
        else:
            try:
                function = left_receiver.find(left_method)
                assert isinstance(function, Function)
                if function.cls is BUILTINS.search("object"):
                    # Python tries reflected equality before object identity.
                    raise NameError
            except NameError:
                if not isinstance(operator, (ast.In, ast.NotIn)):
                    try:
                        reflected = right_receiver.find(right_method)
                    except NameError:
                        pass
                    else:
                        if reflected.cls is not BUILTINS.search("object"):
                            function = reflected
                            left, right = right, left
        if function is None:
            self.fail_unsupported_operator(
                node,
                self.COMPARE_OP_SYMBOLS[type(operator)],
                left_type,
                right_type,
                left_method,
            )
        return function, left, right, negate

    def prepare_membership_comparison(
        self,
        node,
        left,
        operator,
        right,
        right_type,
        right_source,
    ):
        if not isinstance(operator, (ast.In, ast.NotIn)):
            return left, None
        protocol = analyzed_iterable_protocol(right)
        if protocol is not None:
            left = self.normalize_comparison_value(
                node,
                left,
                protocol.item_type,
                protocol.item_representation,
                message=(
                    "Collection membership uses incompatible item representations"
                ),
                help_text=(
                    "Convert the searched value to the collection's item type first."
                ),
            )
        receiver = self.comparison_receiver(right)
        try:
            receiver.find("__contains__")
        except NameError:
            if protocol is None:
                members = get_type_members(right_type)
                if any(
                    isinstance(member.find_attrs("__iter__"), Function)
                    for member in members
                ):
                    self.require_iterable(right_source, right)
                if any(
                    isinstance(member.find_attrs("__getitem__"), Function)
                    for member in members
                ):
                    self.fail(
                        node,
                        DiagnosticCode.UNSUPPORTED_SYNTAX,
                        "Membership through __getitem__ is not supported",
                        help=(
                            "Define __iter__(self) -> Iterator[T] or "
                            "__contains__(self, value) -> bool."
                        ),
                    )
            return left, protocol
        return left, None

    def iterable_membership_comparison(
        self,
        node,
        left,
        operator,
        right,
        protocol,
    ):
        helper = resolve_imported(
            python_builtins.contains_equal_sequence_item,
            self.module,
        )
        assert isinstance(helper, Function)
        if not helper.signature_analyzed:
            raise DependencyError(helper)
        bool_type = BUILTINS.search("bool")
        assert isinstance(bool_type, Class)
        comparison = self.call_node(
            node,
            bool_type,
            func=Name(helper, runtime_dependency=helper),
            args=[right, left],
            keywords=[],
            operator=operator,
            reverse=True,
            dependency_objects=self.inline_dependencies(helper, node),
        )
        comparison.runtime_methods = tuple(
            dict.fromkeys(
                (
                    *protocol.methods,
                    *equality_methods(protocol.item_type),
                )
            )
        )
        if isinstance(operator, ast.NotIn):
            return UnaryOp(bool_type, op=ast.Not(), operand=comparison)
        return comparison

    def validate_collection_comparison(
        self,
        node,
        left,
        operator,
        right,
        left_type,
        right_type,
    ):
        equality = isinstance(operator, (ast.Eq, ast.NotEq))
        typed_dict_equality = equality and any(
            isinstance(value_type, TypedDictClass)
            for value_type in (left_type, right_type)
        )
        collection_equality = equality and any(
            isinstance(value_type, TypedDictClass)
            or isinstance(value_type, Class) and value_type.container.scope.is_builtins
            and value_type.generic_name
            in {"dict", "list", "set", "frozenset", "tuple", "KeysView", "ItemsView"}
            for value_type in (left_type, right_type)
        )
        set_comparison = all(
            isinstance(value_type, Class) and value_type.container.scope.is_builtins
            and value_type.generic_name in {"set", "frozenset", "KeysView", "ItemsView"}
            for value_type in (left_type, right_type)
        )
        set_ordering = isinstance(
            operator,
            (ast.Lt, ast.LtE, ast.Gt, ast.GtE),
        ) and set_comparison
        if not collection_equality and not set_ordering:
            return typed_dict_equality
        left_representation = analyzed_representation(left)
        right_representation = analyzed_representation(right)
        if set_comparison:
            # Syntax uses the same item-level contract as explicit dunders.
            left_representation = self.require_iterable(node, left).item_representation
            right_representation = self.require_iterable(node, right).item_representation
        compatible_numeric_comparison = (
            numeric_comparison_representations_compatible(
                left_representation,
                right_representation,
            )
        )
        representation_conflict = left_representation != right_representation if set_comparison else representations_conflict(
            (
                (left_type, left_representation),
                (right_type, right_representation),
            )
        ) or typed_dict_equality and left_representation != right_representation
        if representation_conflict and not compatible_numeric_comparison:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "Set comparison uses incompatible item representations"
                if set_ordering
                else "Collection equality uses incompatible item representations",
                help=(
                    "Convert both sets to the same item type first."
                    if set_ordering
                    else "Convert both collections to the same item types first."
                ),
            )
        return typed_dict_equality

    def prepare_numeric_comparison(
        self,
        node,
        left,
        operator,
        right,
        left_type,
        right_type,
        left_source,
        right_source,
    ):
        if not isinstance(
            operator,
            (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE),
        ):
            return left, right
        formats = possible_numeric_formats((left, right))
        if len(formats) > 1:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "different fixed-width numeric types cannot be compared implicitly",
                help="Convert the values to one fixed-width type first.",
            )
        int64_format = next(
            (value for value in formats if value.kind == "integer" and value.bits == 64),
            None,
        )
        if int64_format is None:
            return left, right
        if any(member.generic_name == "float" for value_type in (left_type, right_type)
               for member in get_type_members(value_type)):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "int64 and float comparisons cannot be mixed implicitly",
                help="Convert the values to one numeric representation first.",
            )
        # Union equality dispatch retains None and nonnumeric members. A
        # blanket BigInt conversion would turn None into zero or parse text.
        if getattr(left_type, "generic_name", None) in {"int", "bool"}:
            left = self.coerce_int64_operand(left, int64_format, left_source)
        if getattr(right_type, "generic_name", None) in {"int", "bool"}:
            right = self.coerce_int64_operand(right, int64_format, right_source)
        return left, right

    def analyze_comparison(
        self,
        node,
        left,
        operator,
        right,
        left_source,
        right_source,
    ):
        left_type = analyzed_value_type(left)
        right_type = analyzed_value_type(right)
        left, iterable_membership = self.prepare_membership_comparison(
            node,
            left,
            operator,
            right,
            right_type,
            right_source,
        )
        typed_dict_equality = self.validate_collection_comparison(
            node,
            left,
            operator,
            right,
            left_type,
            right_type,
        )
        if iterable_membership is not None:
            return self.iterable_membership_comparison(
                node,
                left,
                operator,
                right,
                iterable_membership,
            )
        left, right = self.prepare_numeric_comparison(
            node,
            left,
            operator,
            right,
            left_type,
            right_type,
            left_source,
            right_source,
        )
        if typed_dict_equality:
            return self.dynamic_union_equality(
                node,
                left,
                right,
                left_type,
                right_type,
                operator,
            )
        comparison_method = "__ne__" if isinstance(operator, ast.NotEq) else "__eq__"
        if (
            isinstance(operator, (ast.Eq, ast.NotEq))
            and (isinstance(left_type, UnionType) or isinstance(right_type, UnionType))
            and not (
                inherits_object_comparison(left_type, comparison_method)
                and inherits_object_comparison(right_type, comparison_method)
            )
        ):
            return self.dynamic_union_equality(
                node,
                left,
                right,
                left_type,
                right_type,
                operator,
            )

        # Representation coercion may replace operands. Determine swapping
        # from the prepared pair, before argument normalization can replace
        # the selected argument again.
        prepared_left = left
        func, left, right, negate = self.resolve_comparison_method(
            node,
            operator,
            left,
            right,
            left_type,
            right_type,
        )
        if func is not self.func and not func.is_analyzed:
            raise DependencyError(func)
        reverse = right is prepared_left
        argument_source = left_source if reverse else right_source
        [right] = self.normalize_lowered_method_arguments(
            [argument_source],
            [right],
            func,
            left,
        )
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
            reverse=reverse,
            dependency_objects=self.inline_dependencies(func, node),
        )
        comparison.runtime_methods = self.runtime_contract_methods(
            function,
            func,
            [right],
        )
        if isinstance(operator, ast.NotIn) or negate:
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
    PORTABLE_FLOAT_MISSING_METHOD_OPERATIONS = {
        "__divmod__": "divmod()",
        "__rdivmod__": "divmod()",
        "__pow__": "**",
        "__rpow__": "**",
    }
    NUMERIC_BINARY_DUNDER_METHODS = frozenset(
        method
        for methods in BIN_OPS.values()
        for method in methods
    ) | {
        "__divmod__",
        "__eq__",
        "__ge__",
        "__gt__",
        "__le__",
        "__lt__",
        "__ne__",
        "__rdivmod__",
    }

    REPRESENTED_INTEGER_RESULT_DUNDERS = NUMERIC_BINARY_DUNDER_METHODS - {
        "__divmod__",
        "__eq__",
        "__ge__",
        "__gt__",
        "__le__",
        "__lt__",
        "__ne__",
        "__rdivmod__",
        "__rtruediv__",
        "__truediv__",
    }

    REPRESENTED_FLOAT_RESULT_DUNDERS = {
        "__add__",
        "__mul__",
        "__radd__",
        "__rmul__",
        "__rsub__",
        "__rtruediv__",
        "__sub__",
        "__truediv__",
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

    def fail_portable_float_operation(self, node, operation: str):
        self.fail(
            node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"Portable fixed-width floats do not support {operation!r}",
            help=(
                "Use a supported arithmetic operation or convert both "
                "operands to ordinary float values first."
            ),
        )

    def fail_mixed_numeric_formats(self, node):
        self.fail(
            node,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            "different fixed-width numeric types cannot be mixed implicitly",
            help="Convert the values to one fixed-width type first.",
        )

    def normalize_explicit_numeric_dunder(self, node, func, args):
        if (
            not isinstance(func, Attribute)
            or func.attr not in self.NUMERIC_BINARY_DUNDER_METHODS
            or not args
        ):
            return args, None
        receiver_numeric = analyzed_numeric_format(func.value)
        if receiver_numeric is not None and any(
            argument_numeric != receiver_numeric
            for argument in args
            if (argument_numeric := analyzed_numeric_format(argument)) is not None
        ):
            self.fail_mixed_numeric_formats(node)
        result = None
        if receiver_numeric is not None:
            if (
                (
                    receiver_numeric.kind == "integer"
                    and func.attr in self.REPRESENTED_INTEGER_RESULT_DUNDERS
                )
                or (
                    receiver_numeric.kind == "float"
                    and func.attr in self.REPRESENTED_FLOAT_RESULT_DUNDERS
                )
            ):
                result = direct_representation(receiver_numeric, None)
            elif (
                receiver_numeric.kind == "integer"
                and func.attr in {"__divmod__", "__rdivmod__"}
            ):
                item = direct_representation(receiver_numeric, None)
                result = tuple_representation((item, item))
        if _ACTIVE_ENVIRONMENT.get().name != "js":
            return args, result
        receiver_type = analyzed_value_type(func.value)
        if python_builtins.is_int64_format(receiver_numeric):
            args = [
                self.coerce_int64_operand(argument, receiver_numeric, source)
                for source, argument in zip(node.args, args, strict=True)
            ]
        elif (
            receiver_numeric is None
            and isinstance(receiver_type, Class)
            and receiver_type.generic_name in {"bool", "float", "int"}
        ):
            args = [
                (
                    self.normalize_float_argument(
                        source,
                        argument,
                        BUILTINS.search("float"),
                    )
                    if receiver_type.generic_name == "float"
                    else self.normalize_integer_index_value(source, argument)
                )
                for source, argument in zip(node.args, args, strict=True)
            ]
        return args, result

    def resolve_binary_operator(
        self,
        left_type,
        right_type,
        left_method,
        right_method,
        *,
        reject_object=False,
    ):
        # CPython tries numeric slots before sq_repeat. A builtin sequence's
        # exposed __mul__ is that fallback, not a numeric forward slot: an
        # application's __rmul__ therefore wins without being a subtype.
        # Keep this in shared dispatch so widening a native repeat parameter
        # to object does not hide reflected methods in other backends.
        if (left_method == "__mul__"
                and inherited_sequence_slot(left_type, left_method) is not None
                and not right_type.container.scope.is_builtins):
            method, reverse = self.resolve_binary_operator(
                right_type, left_type, right_method, left_method,
                reject_object=reject_object)
            return method, not reverse
        left_self = left_type._self
        right_self = right_type._self
        right_override = right_self.cls.find_attrs(
            right_method,
            search_bases=False,
        )
        # Typing compatibility (structural interfaces, numeric promotion or
        # different tuple specializations) is not runtime subclass priority.
        right_is_subclass = is_strict_runtime_subclass(right_type, left_type)
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
                if reject_object and method.cls is BUILTINS.search("object"):
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
                reverse = not reject_object or method.cls is not BUILTINS.search("object")
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
        first_inline, first_dependencies = js_lowering(first_method)
        incompatible = any(
            reverse != first_reverse
            or js_lowering(method)[0] is not first_inline
            or method.is_async != first_method.is_async
            or js_lowering(method)[1] != first_dependencies
            or method.params[0].representation != first_method.params[0].representation
            or method.return_representation != first_method.return_representation
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
        [argument] = self.normalize_lowered_method_arguments(
            [node.left if first_reverse else node.right],
            [argument],
            first_method,
            receiver,
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

    def prepare_binary_dispatch(
        self,
        node,
        left,
        right,
        left_type,
        right_type,
        left_method,
        right_method,
    ):
        integer = BUILTINS.search("int")
        inherited_integer_slot = (
            is_strict_runtime_subclass(left_type, integer)
            and left_type._self.find(left_method) is integer._self.find(left_method)
        )
        ordinary_integer_result = (
            (left_type.generic_name == "bool" or inherited_integer_slot)
            and analyzed_numeric_format(left) is None
            and (right_format := analyzed_numeric_format(right)) is not None
            and right_format.kind == "integer"
        )
        if not ordinary_integer_result:
            try:
                function, reverse = self.resolve_binary_operator(
                    left_type,
                    right_type,
                    left_method,
                    right_method,
                )
            except NameError:
                self.fail_unsupported_operator(
                    node,
                    self.BIN_OP_SYMBOLS[type(node.op)],
                    left_type,
                    right_type,
                    left_method,
                )
            return left, left_type, function, reverse, False

        # An IntEnum inherits int's slots but is not an ancestor of a portable
        # operand. Like bool, its ordinary slot wins. Preserve that owner
        # instead of letting the right operand dictate wrapping arithmetic.
        assert isinstance(integer, Class)
        constructor = integer._self.find("__init__")
        assert isinstance(constructor, Function)
        left = self.call_node(
            node.left,
            integer,
            func=Name(integer, id="int"),
            args=[left],
            keywords=[],
            dependency_objects=self.inline_dependencies(
                constructor,
                node.left,
            ),
        )
        function = integer._self.find(left_method)
        assert isinstance(function, Function)
        if not function.is_analyzed:
            raise DependencyError(function)
        return left, integer, function, False, True

    def binary_item_representation(
        self,
        node,
        result_type,
        left,
        right,
        label,
    ):
        left_protocol = self.require_iterable(node.left, left)
        right_protocol = self.require_iterable(node.right, right)
        return self.merge_typed_representations(
            node,
            result_type.generic_types["V"],
            (
                (
                    left_protocol.item_type,
                    left_protocol.item_representation,
                ),
                (
                    right_protocol.item_type,
                    right_protocol.item_representation,
                ),
            ),
            label,
        )

    def prepare_binary_numeric_operands(
        self,
        node,
        left,
        right,
        left_type,
        right_type,
        function,
        formats,
        numeric,
        ordinary_integer_result,
    ):
        if len(formats) > 1:
            self.fail_mixed_numeric_formats(node)
        if numeric is not None:
            for operand in (left, right):
                if analyzed_numeric_format(operand) is None:
                    self.validate_wgsl_integer_literal(
                        getattr(operand, "python_node", operand),
                        operand,
                        numeric,
                    )
            if isinstance(
                node.op,
                (
                    ast.Add,
                    ast.Sub,
                    ast.Mult,
                    ast.BitAnd,
                    ast.BitOr,
                    ast.BitXor,
                ),
            ):
                left = self.reduce_large_modular_operand(
                    left,
                    node.left,
                    numeric,
                )
                right = self.reduce_large_modular_operand(
                    right,
                    node.right,
                    numeric,
                )
        integer_formats = integer_numeric_formats((left, right))
        int64_format = next(
            (value for value in integer_formats if value.bits == 64),
            None,
        )
        numeric_operator = (
            function.cls is not None
            and function.cls.generic_name in {"bool", "float", "int"}
        )
        ordinary_float_operation = "float" in {
            left_type.generic_name,
            right_type.generic_name,
        }
        if int64_format is not None and numeric_operator:
            if ordinary_float_operation:
                float_type = BUILTINS.search("float")
                assert isinstance(float_type, Class)
                left = self.normalize_float_argument(node.left, left, float_type)
                right = self.normalize_float_argument(node.right, right, float_type)
            elif ordinary_integer_result:
                right = self.normalize_integer_index_value(node.right, right)
            else:
                left = self.coerce_int64_operand(left, int64_format, node.left)
                right = self.coerce_int64_operand(right, int64_format, node.right)
        return left, right, int64_format, ordinary_float_operation

    def finish_binary_result(
        self,
        node,
        result,
        result_type,
        left,
        right,
        func,
        reverse,
        ordinary_integer_result,
    ):
        if ordinary_integer_result:
            set_analyzed_representation(result, None)
        if (
            isinstance(node.op, ast.Mult)
            and isinstance(analyzed_value_type(left), Class)
            and analyzed_value_type(left).generic_name == "tuple"
        ):
            return self.repeated_tuple(
                node,
                result,
                left,
                node.left if reverse else node.right,
            )
        if (
            isinstance(node.op, ast.Add)
            and isinstance(result_type, Class)
            and result_type.generic_name in {"list", "tuple"}
        ):
            left_representation = analyzed_representation(left)
            right_representation = analyzed_representation(right)
            if result_type.generic_name == "tuple":
                left_items = (
                    left_representation.arguments
                    if left_representation is not None
                    else ()
                )
                right_items = (
                    right_representation.arguments
                    if right_representation is not None
                    else ()
                )
                representation = tuple_representation((*left_items, *right_items))
            else:
                item_representation = self.binary_item_representation(
                    node,
                    result_type,
                    left,
                    right,
                    "Concatenated collection items",
                )
                representation = compound_representation(
                    arguments=(item_representation,)
                )
            set_analyzed_representation(result, representation)
        elif (
            isinstance(result_type, Class)
            and result_type.generic_name in {"set", "frozenset"}
            and isinstance(
                node.op,
                (ast.BitAnd, ast.BitOr, ast.BitXor, ast.Sub),
            )
        ):
            item_representation = self.binary_item_representation(
                node,
                result_type,
                left,
                right,
                "Combined set items",
            )
            set_analyzed_representation(
                result,
                compound_representation(arguments=(item_representation,)),
            )
        elif (isinstance(node.op, ast.BitOr) and is_builtin_class(result_type, "dict")
              and is_builtin_class(analyzed_value_type(left), "dict")):
            # Resolution has already put the owning receiver on the left,
            # including reflected unions. The new mapping uses that storage;
            # validate copied members rather than relabeling the other input.
            # An application operator merely returning a dict is not a union.
            representation = analyzed_representation(left)
            key, value = representation.arguments if representation else (None, None)
            result.args[0] = self.normalize_stored_mapping(
                node.left if reverse else node.right, right, key, value,
                result_type.generic_types["K"], result_type.generic_types["V"],
            )
            set_analyzed_representation(result, representation)
        elif func.returns_self:
            set_analyzed_representation(result, analyzed_representation(left))
        result_format = (
            None if ordinary_integer_result else operation_numeric_format((left, right))
        )
        if result_format is None:
            return result
        if numeric_format_matches_type(result_format, result.obj):
            return self.normalize_numeric_value(result, result_format)
        set_analyzed_representation(result, None)
        return result

    def binary_operator_signature(self, method, argument, node):
        """Select static overload metadata without replacing the runtime body."""
        if not method.overloads:
            return method
        for overload in method.overloads:
            if not overload.signature_analyzed:
                raise DependencyError(overload)
            if (self.overload_matches_types(overload, [argument], [])
                    and self.overload_matches_representations(overload, [argument], [])):
                return overload
        self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                  f"No overload of {method.name!r} accepts this operand type and representation")

    def visit_BinOp(self, node: ast.BinOp):
        left = self.visit(node.left)
        right = self.visit(node.right)
        return self.analyze_binary_operation(node, left, right)

    def analyze_binary_operation(self, node, left, right):
        """Resolve an operator after evaluating its operands' types once."""
        if isinstance(node.op, ast.Mult) and any(
            analyzed_array_format(value) is not None for value in (left, right)
        ):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                "StaticArray repetition would change its declared length",
                help="Copy items explicitly into a new StaticArray of that length.",
            )
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
        formats = numeric_formats((left, right))
        numeric = next(iter(formats)) if len(formats) == 1 else None
        if numeric is not None:
            if (
                is_portable_float_format(numeric)
                and isinstance(node.op, (ast.FloorDiv, ast.Mod, ast.Pow))
            ):
                self.fail_portable_float_operation(
                    node,
                    self.BIN_OP_SYMBOLS[type(node.op)],
                )
        left_op_method, right_op_method = self.BIN_OPS[type(node.op)]
        left, left_type, func, reverse, ordinary_integer_result = (
            self.prepare_binary_dispatch(
                node,
                left,
                right,
                left_type,
                right_type,
                left_op_method,
                right_op_method,
            )
        )
        signature = self.binary_operator_signature(func, left if reverse else right, node)
        left, right, int64_format, ordinary_float_operation = (
            self.prepare_binary_numeric_operands(
                node,
                left,
                right,
                left_type,
                right_type,
                func,
                formats,
                numeric,
                ordinary_integer_result,
            )
        )
        if reverse:
            left, right = right, left
        [right] = self.normalize_lowered_method_arguments(
            [node.left if reverse else node.right],
            [right],
            signature,
            left,
        )
        result_type = self.numeric_binary_result_type(
            node.op,
            (left, right),
            signature.return_type,
        )
        if (
            _ACTIVE_ENVIRONMENT.get().name == "js"
            and int64_format is not None
            and isinstance(node.op, ast.Div)
            and not ordinary_integer_result
            and not ordinary_float_operation
        ):
            return self.int64_division_call(node, left, right)
        result = self.call_node(
            node,
            result_type,
            func=Attribute(func, value=left, attr=func.name),
            args=[right],
            keywords=[],
            operator=node.op,
            reverse=reverse,
            dependency_objects=self.inline_dependencies(func, node),
        )
        if signature is not func:
            set_analyzed_representation(result, signature.return_representation)
        return self.finish_binary_result(
            node,
            result,
            result_type,
            left,
            right,
            func,
            reverse,
            ordinary_integer_result,
        )

    UNARY_OPS = {
        ast.UAdd: "__pos__",
        ast.USub: "__neg__",
        ast.Invert: "__invert__",
        ast.Not: "__bool__",
    }
    UNARY_SYMBOLS = {ast.UAdd: "+", ast.USub: "-", ast.Invert: "~", ast.Not: "not"}

    def visit_UnaryOp(self, node: ast.UnaryOp):
        operand = self.visit(node.operand)
        op_method = self.UNARY_OPS[type(node.op)]
        operand_obj = analyzed_value_object(operand)
        operand_type = analyzed_value_type(operand)
        if isinstance(node.op, ast.Not):
            if isinstance(operand, ast.Constant) and operand.value is None:
                # The literal has no protocol method or evaluation effects.
                return self.visit(ast.copy_location(ast.Constant(value=True), node))
            # Negation uses the same truth protocol as a conditional, including
            # unions and __len__ fallbacks; it is not a direct __bool__ lookup.
            truth = self.truth_test(node.operand, operand)
            boolean = BUILTINS.search("bool")
            if analyzed_value_type(truth).name != "bool":
                truth = self.truth_test(node.operand, truth)
            return UnaryOp(boolean, op=node.op, operand=truth)
        if isinstance(operand_type, UnionType):
            self.fail(
                node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Unary operator {self.UNARY_SYMBOLS[type(node.op)]!r} requires narrowing "
                f"{operand_type.to_annotation_str()}",
                help="Narrow the operand to a concrete type before applying this operator.",
            )
        if isinstance(node.op, ast.UAdd) and python_builtins.is_int64_format(
            analyzed_numeric_format(operand)
        ):
            return operand
        if isinstance(node.op, (ast.UAdd, ast.USub)) and operand_type.name in (
            "int",
            "float",
        ):
            result = UnaryOp(operand_type, op=node.op, operand=operand)
            result_format = analyzed_numeric_format(operand)
            apply_representation(
                result,
                direct_representation(result_format, None),
            )
            return self.normalize_numeric_value(result, result_format)
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
        call = self.call_node(
            node,
            func.return_type,
            func=Attribute(func, value=operand, attr=func.name),
            args=[],
            keywords=[],
            operator=node.op,
            dependency_objects=self.inline_dependencies(func, node),
        )
        result_format = analyzed_numeric_format(call)
        if result_format is not None and call.obj.generic_name == "int":
            return self.normalize_numeric_value(call, result_format)
        return call

    def boolean_result_contract(self, node, values):
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
        typed_representations = tuple(
            (analyzed_value_type(value), analyzed_representation(value))
            for value in values
        )
        has_representation_conflict = representations_conflict(typed_representations)
        if has_representation_conflict and mixed_numeric_formats(values):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "Boolean operands use incompatible numeric representations",
                help=(
                    "Convert every value to one represented type, or use "
                    "ordinary Python numbers throughout."
                ),
            )
        if has_representation_conflict and mixed_array_formats(values):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "Boolean operands use incompatible array layouts",
                help="Use one StaticArray type for every value.",
            )
        if has_representation_conflict:
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "Boolean operands use incompatible nested representations",
                help=(
                    "Use one represented type for each runtime value type, or "
                    "add an explicit conversion."
                ),
            )
        representation = merged_representation(
            result_type,
            typed_representations,
        ) or direct_representation(
            common_numeric_format(values),
            common_array_format(values),
        )
        return result_type, representation

    def visit_BoolOp(self, node: ast.BoolOp):
        values = []
        visitor = self
        evaluate_next_when_true = isinstance(node.op, ast.And)
        for index, value in enumerate(node.values):
            operand = visitor.visit_comparison_value(value)
            if index < len(node.values) - 1:
                # These operands are tested and may also become the result.
                # Resolve their read contract before joining result types;
                # truth_test alone misses the raw BoolOp fast path below.
                operand = visitor.guard_value(operand, preserve_local=True)
            values.append(operand)
            visitor = visitor.narrow_for_condition(value, evaluate_next_when_true)
        result_type, result_representation = self.boolean_result_contract(node, values)
        native_truth_types = {"bool", "int", "NoneType", "str"}
        if all(
            {member.name for member in get_type_members(analyzed_value_type(value))}
            <= native_truth_types
            for value in values[:-1]
        ):
            result = BoolOp(result_type, op=node.op, values=values)
            set_analyzed_representation(result, result_representation)
            return result

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
        set_analyzed_representation(result, result_representation)
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
        type_name = type(node.value).__name__
        type_cls = literal_member_for_value(
            self.contextual_types.get(node),
            node.value,
        ) or BUILTINS.search(type_name)
        assert isinstance(type_cls, Class)
        return Constant(type_cls, value=node.value)

    def sequence_literal_context(self, node, generic):
        expected = self.contextual_types.get(node)
        representation = self.contextual_representations.get(node)
        direct = contextual_collection_type(expected, generic.name)
        if direct is not None:
            return direct, representation_for_member(expected, representation, direct)
        iterable = contextual_collection_type(expected, "Iterable")
        if iterable is None or not iterable.container.scope.is_builtins:
            return None, None
        # A fresh sequence owns its slots, so an Iterable item contract can
        # contextualize nested empty literals before argument matching. Keep
        # tuple arity concrete; this does not retype any borrowed container.
        item = iterable.generic_types["V"]
        representation = representation_for_member(expected, representation, iterable)
        item_representation = representation.arguments[0] if representation and representation.arguments else None
        if generic.name == "tuple":
            return (generic(*([item] * len(node.elts))),
                    tuple_representation((item_representation,) * len(node.elts)))
        return generic(item), representation

    def visit_Tuple(self, node: ast.Tuple):
        generic_tuple = BUILTINS.search("tuple")
        assert isinstance(generic_tuple, GenericClass)
        contextual_type, contextual_representation = self.sequence_literal_context(node, generic_tuple)
        if not node.elts and contextual_type is not None:
            result = Tuple(contextual_type, elts=[])
            set_analyzed_representation(result, contextual_representation)
            return result
        elts = []
        contextual_items = (
            list(contextual_type.generic_types.values())
            if contextual_type is not None
            else []
        )
        if contextual_type is not None and contextual_type.tuple_variadic:
            contextual_items *= len(node.elts)
        contextual_arguments = contextual_representation.arguments if contextual_representation else ()
        if contextual_type is not None and contextual_type.tuple_variadic:
            contextual_arguments *= len(node.elts)
        for index, item in enumerate(node.elts):
            expected_type = (
                contextual_items[index]
                if index < len(contextual_items)
                else None
            )
            elt = self.visit_contextual_expression(
                item, expected_type,
                expected_representation=(contextual_arguments[index] if index < len(contextual_arguments) else None),
            )
            elts.append(elt)
        types = [value_type for value_type, _ in self.infer_empty_collection_literals(elts)]
        if (
            contextual_type is not None
            # Iterable context types fresh children; it must not widen an
            # otherwise concrete source tuple into the interface's union item.
            and contextual_collection_type(self.contextual_types.get(node), "tuple") is not None
            and (
                contextual_type.tuple_variadic
                or len(types) == len(contextual_items)
            )
            and all(
                is_call_argument_compatible(expected, elt)
                for expected, elt in zip(
                    contextual_items,
                    elts,
                    strict=True,
                )
            )
        ):
            tuple_type = contextual_type
        else:
            tuple_type = generic_tuple(*types)
        result = Tuple(tuple_type, elts=elts)
        set_analyzed_representation(
            result,
            tuple_representation(
                tuple(analyzed_representation(elt) for elt in elts)
            ),
        )
        return result

    def infer_empty_collection_literals(self, values, typed_representations=None):
        if typed_representations is None:
            typed_representations = [
                (analyzed_value_type(value), analyzed_representation(value))
                for value in values
            ]
        def empty_only(value):
            if not isinstance(value, (List, Dict)) or analyzed_representation(value) is not None:
                return False
            if isinstance(value.obj, GenericClass):
                return True
            return all(empty_only(child) for child in value.elts) if isinstance(value, List) else not value.keys

        empty = [(index, value) for index, value in enumerate(values) if empty_only(value)]
        if not empty:
            return typed_representations
        # An empty literal has no item evidence of its own. Use an unambiguous
        # sibling before GenericClass is erased to object in the parent type.
        # A receiver-substituted context can supply the type without a storage
        # representation. Children holding only fresh empty descendants also
        # need sibling evidence, recursively through the new storage slots.
        # Do not infer a fixed-size array (an empty literal has length zero).
        candidates = {}
        empty_indices = {index for index, _ in empty}
        for index, (value_type, representation) in enumerate(typed_representations):
            if index in empty_indices:
                continue
            for member in get_type_members(value_type):
                if (
                    isinstance(member, Class) and member.container.scope.is_builtins
                    and not isinstance(member, TypedDictClass)
                    and member.generic_name in {"list", "dict"}
                ):
                    member_representation = representation_for_member(
                        value_type, representation, member,
                    )
                    if member_representation is None or member_representation.array is None:
                        candidates.setdefault(member.generic_name, set()).add(
                            (member, member_representation),
                        )
        for index, value in empty:
            matching = candidates.get(
                value.obj.name if isinstance(value.obj, GenericClass) else value.obj.generic_name,
                (),
            )
            if len(matching) != 1:
                continue
            value_type, representation = next(iter(matching))
            if self.apply_literal_type(value, value_type) is None:
                continue
            self.normalize_representation(value, representation, value_type)
            typed_representations[index] = value_type, representation
        return typed_representations

    def visit_List(self, node: ast.List):
        generic_list = BUILTINS.search("list")
        assert isinstance(generic_list, GenericClass)
        contextual_type, contextual_representation = self.sequence_literal_context(node, generic_list)
        if not node.elts and contextual_type is not None:
            result = List(contextual_type, elts=[])
            set_analyzed_representation(result, contextual_representation)
            return result
        elts = []
        expected_item_type = (
            contextual_type.generic_types["V"] if contextual_type is not None else None
        )
        item_representation = (
            contextual_representation.arguments[0]
            if contextual_representation and contextual_representation.arguments else None
        )
        for item in node.elts:
            elt = self.visit_contextual_expression(
                item, expected_item_type, expected_representation=item_representation,
            )
            if item_representation is not None and isinstance(elt, (List, Tuple, Dict, Set)):
                # Populate fresh storage before merging siblings: an empty
                # child already carries its contextual representation, while
                # an ordinary populated child still needs slot conversions.
                elt = self.normalize_stored_value(item, elt, item_representation, expected_item_type)
            elts.append(elt)
        item_representations = self.infer_empty_collection_literals(elts)
        V = UnionType(types=(value_type for value_type, _ in item_representations))
        if (
            contextual_type is not None
            and contextual_collection_type(self.contextual_types.get(node), "list") is not None
            and all(is_call_argument_compatible(contextual_type.generic_types["V"], elt) for elt in elts)
        ):
            list_type = contextual_type
        else:
            list_type = generic_list(V.type) if V.types else generic_list
        result = List(list_type, elts=elts)
        contextual_representation = self.contextual_representations.get(node)
        if (
            contextual_representation is not None
            and contextual_representation.array is not None
        ):
            set_analyzed_representation(result, contextual_representation)
        else:
            item_representation = (
                self.merge_expression_representations(
                    node,
                    V.type,
                    elts,
                    "List items",
                )
                if elts
                else None
            )
            set_analyzed_representation(
                result,
                compound_representation(arguments=(item_representation,)),
            )
        return result

    def visit_Dict(self, node: ast.Dict):
        generic_dict = BUILTINS.search("dict")
        assert isinstance(generic_dict, GenericClass)
        contextual_type = contextual_collection_type(
            self.contextual_types.get(node),
            "dict",
        )
        if not node.keys and contextual_type is not None:
            return Dict(contextual_type, keys=[], values=[])
        K, keys, values = UnionType(), [], []
        key_representations = []
        value_representations = []
        literal_values = []
        contextual_key_type = None
        contextual_value_type = None
        if contextual_type is not None and not isinstance(
            contextual_type, TypedDictClass
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
                    literal_values.append(None)
                    mapping_representation = analyzed_representation(mapping)
                    mapping_arguments = (
                        mapping_representation.arguments
                        if mapping_representation is not None
                        else ()
                    )
                    key_representations.append(
                        (
                            key_type,
                            mapping_arguments[0] if mapping_arguments else None,
                        )
                    )
                    value_representations.append(
                        (
                            value_type,
                            mapping_arguments[1] if len(mapping_arguments) > 1 else None,
                        )
                    )
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
            literal_values.append(analyzed_value)
            key_representations.append((key_type, analyzed_representation(analyzed_key)))
            value_representations.append(
                (value_type, analyzed_representation(analyzed_value))
            )
        self.infer_empty_collection_literals(literal_values, value_representations)
        V = UnionType(types=(value_type for value_type, _ in value_representations))
        if contextual_key_type is not None and all(
            is_return_type_compatible(contextual_key_type, key_type)
            and is_return_type_compatible(
                contextual_value_type,
                value_type,
            )
            for (key_type, _), (value_type, _) in zip(key_representations, value_representations, strict=True)
        ):
            dict_type = contextual_type
        else:
            dict_type = (
                generic_dict(K.type, V.type) if K.types and V.types else generic_dict
            )
        result = Dict(dict_type, keys=keys, values=values)
        key_representation = (
            self.merge_typed_representations(
                node,
                K.type,
                key_representations,
                "Dictionary keys",
            )
            if key_representations
            else None
        )
        value_representation = (
            self.merge_typed_representations(
                node,
                V.type,
                value_representations,
                "Dictionary values",
            )
            if value_representations
            else None
        )
        set_analyzed_representation(
            result,
            compound_representation(
                arguments=(
                    key_representation,
                    value_representation,
                )
            ),
        )
        return result

    def visit_Set(self, node: ast.Set):
        generic_set = BUILTINS.search("set")
        assert isinstance(generic_set, GenericClass)
        contextual_type = contextual_collection_type(
            self.contextual_types.get(node), "set"
        )
        expected_item_type = (
            contextual_type.generic_types["V"] if contextual_type is not None else None
        )
        item_types = UnionType()
        elements = []
        for item in node.elts:
            element = self.visit_contextual_expression(item, expected_item_type)
            elements.append(element)
            item_types.add(analyzed_value_type(element))
        set_type = (
            contextual_type
            if contextual_type is not None
            and all(is_call_argument_compatible(expected_item_type, item) for item in elements)
            else generic_set(item_types.type)
        )
        result = Set(set_type, elts=elements)
        set_analyzed_representation(
            result,
            compound_representation(
                arguments=(
                    self.merge_expression_representations(
                        node,
                        item_types.type,
                        elements,
                        "Set items",
                    ),
                )
            ),
        )
        return result

    # endregion

    # region looping

    def mapping_keys_iterable(self, iterable):
        iterable_obj = analyzed_value_object(iterable)
        iterable_type = (
            iterable_obj.cls if isinstance(iterable_obj, Instance) else iterable_obj
        )
        if not (
            isinstance(iterable_type, TypedDictClass)
            or isinstance(iterable_type, Class)
            and iterable_type.container.scope.is_builtins
            and iterable_type.generic_name == "dict"
        ):
            return iterable
        keys = iterable_obj.find("keys")
        if not keys.signature_analyzed:
            raise DependencyError(keys)
        result = Call(
            keys.return_type,
            func=Attribute(keys, value=iterable, attr="keys"),
            args=[],
            keywords=[],
        )
        representation = analyzed_representation(iterable)
        if representation is not None and representation.arguments:
            set_analyzed_representation(
                result,
                compound_representation(arguments=(representation.arguments[0],)),
            )
        result.mapping_source_type = iterable_type
        return result

    def require_iterable(
        self,
        node,
        iterable,
        *,
        allow_representation_conflict=False,
    ):
        value_type = analyzed_value_type(iterable)
        protocol = analyzed_iterable_protocol(iterable)
        if protocol is not None:
            if protocol.representation_conflict and not allow_representation_conflict:
                self.fail(
                    node,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "Iterable items use incompatible nested representations",
                    help=(
                        "Convert items with the same runtime type to one "
                        "represented type before iterating."
                    ),
                )
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
        test = self.truth_test(node.test, test)
        body_visitor = self.branch_visitor(node.test, True)
        zero_visitor = self.branch_visitor(node.test, False)
        break_exits = []
        body_visitor.loop_break_collectors = [
            *self.loop_break_collectors,
            (body_visitor.scope, break_exits),
        ]
        body = body_visitor.visit_body(node.body)
        normal_visitors = []
        if body_can_fall_through(body, break_exits=True):
            normal_visitors.append(body_visitor)
        if not isinstance(node.test, ast.Constant) or not node.test.value:
            normal_visitors.append(zero_visitor)
        normal_visitor = self.child_visitor(LocalScope(self.scope))
        if normal_visitors:
            normal_visitor.merge_branch_declarations(node, *normal_visitors)
        if node.orelse:
            # Else continues the exhaustion state. Keep its visible loop
            # declarations in the final scope-name merge, not only else writes.
            orelse = normal_visitor.visit_body(node.orelse)
        else:
            orelse = node.orelse
        final_visitors = [*break_exits]
        if normal_visitors and body_can_fall_through(orelse, loop_control_exits=True):
            final_visitors.insert(0, normal_visitor)
        if final_visitors:
            self.merge_branch_declarations(node, *final_visitors)
        return ast.While(
            test=test,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )

    def visit_For(self, node: ast.For):
        node_iter = self.mapping_keys_iterable(self.visit(node.iter))
        protocol = self.require_iterable(node.iter, node_iter)
        body_visitor = self.child_visitor(LocalScope(self.scope))
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

        body = body_visitor.visit_body(node.body)
        normal_visitors = []
        if body_can_fall_through(body, break_exits=True):
            normal_visitors.append(body_visitor)
        definitely_nonempty = literal_iterable_is_nonempty(node.iter)
        if not definitely_nonempty:
            normal_visitors.append(zero_visitor)
        normal_visitor = self.child_visitor(LocalScope(self.scope))
        if normal_visitors:
            normal_visitor.merge_branch_declarations(node, *normal_visitors)
        if node.orelse:
            orelse = normal_visitor.visit_body(node.orelse)
        else:
            orelse = node.orelse
        final_visitors = [*break_exits]
        if normal_visitors and body_can_fall_through(orelse, loop_control_exits=True):
            final_visitors.insert(0, normal_visitor)
        if final_visitors:
            self.merge_branch_declarations(node, *final_visitors)
        result = ast.For(
            target=target,
            iter=node_iter,
            body=body,
            orelse=orelse,
            lineno=node.lineno,
        )
        result.runtime_methods = protocol.methods
        return result

    def bind_loop_target(self, target, value_type, representation=None):
        if isinstance(target, ast.Name):
            value = value_type(target.id, self.scope, self.func)
            apply_representation(value, representation)
            try:
                declared = self.declared_local(target.id)
            except NameError:
                pass
            else:
                if isinstance(declared, Instance):
                    declared = declared.storage_declaration
                if isinstance(declared, Instance) and declared.has_declared_type:
                    # A loop item refines reads, not the existing storage ABI.
                    # Zero iterations must still load the pre-loop declaration.
                    value.storage_binding = declared
            self.scope.add(value)
            result = ast.arg(arg=target.id, annotation=value_type.annotation)
            # Preserve this binding: a later loop can reuse the name with a
            # different item type before a backend consumes the analyzed IR.
            result.obj = value
            apply_representation(result, representation)
            return result
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
        if not isinstance(value_type, Class):
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "loop target requires a statically sized sequence",
                help="Iterate over a tuple or StaticArray before unpacking it.",
            )
        if value_type.generic_name == "tuple":
            item_types = list(value_type.generic_types.values())
            item_representations = (
                representation.arguments
                if representation is not None
                and len(representation.arguments) == len(item_types)
                else (None,) * len(item_types)
            )
        elif (
            value_type.generic_name == "list"
            and representation is not None
            and representation.array is not None
        ):
            array = representation.array
            item_types = [value_type.generic_types["V"]] * array.length
            item_representations = (
                representation.arguments[0]
                if representation.arguments
                else direct_representation(
                    array.item_numeric,
                    array.item_array,
                ),
            ) * array.length
        else:
            self.fail(
                target,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "loop target requires a statically sized sequence",
                help="Iterate over a tuple or StaticArray before unpacking it.",
            )
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
                self.bind_loop_target(
                    item_target,
                    item_type,
                    item_representation,
                )
                for item_target, item_type, item_representation in zip(
                    target.elts,
                    item_types,
                    item_representations,
                    strict=True,
                )
            ]
        )

    def visit_Try(self, node: ast.Try):
        pending_breaks = []

        def try_visitor(scope):
            visitor = self.child_visitor(scope)
            if node.finalbody:
                visitor.pending_finally_breaks = [
                    *self.pending_finally_breaks,
                    pending_breaks,
                ]
            return visitor

        body_visitor = try_visitor(LocalScope(self.scope))
        analyzed_body = body_visitor.visit_body(node.body)
        handler_entry = self.exception_entry(node.body, analyzed_body)
        handlers = []
        handler_visitors = []
        for handler in node.handlers:
            handler_type, exception_type = self.analyze_exception_handler_type(handler)
            handler_visitor = try_visitor(LocalScope(handler_entry.scope))
            handler_visitors.append(handler_visitor)
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
        if node.orelse:
            # visit_body can record writes in child flow scopes. The original
            # visitor retains declarations but not every invalidated proof.
            orelse_entry = body_visitor.exception_entry(node.body, analyzed_body)
            orelse_visitor = try_visitor(LocalScope(orelse_entry.scope))
            orelse = orelse_visitor.visit_body(node.orelse)
            successful_visitor = orelse_visitor
        else:
            orelse = []
            successful_visitor = body_visitor
        normal_visitors = []
        successful_body = orelse if node.orelse else analyzed_body
        if body_can_fall_through(analyzed_body) and body_can_fall_through(
            successful_body
        ):
            normal_visitors.append(successful_visitor)
        normal_visitors.extend(
            visitor
            for visitor, handler in zip(
                handler_visitors,
                handlers,
                strict=True,
            )
            if body_can_fall_through(handler.body)
        )
        if node.finalbody:
            exceptional_entry = self.exception_entry(
                [*node.body, *node.orelse, *node.handlers],
                [*analyzed_body, *orelse, *handlers],
            )
            # finally also runs on exceptions and returns, not only the normal
            # fallthrough states below. Emit the body checked for every entry.
            finalbody = exceptional_entry.visit_body(node.finalbody)
            completed_visitors = []
            for visitor in normal_visitors:
                final_visitor = self.child_visitor(visitor.scope)
                analyzed_finalbody = final_visitor.visit_body(node.finalbody)
                if body_can_fall_through(
                    analyzed_finalbody,
                    loop_control_exits=True,
                ):
                    completed_visitors.append(final_visitor)
            if completed_visitors:
                self.merge_branch_declarations(node, *completed_visitors)
        else:
            finalbody = []
            if normal_visitors:
                self.merge_branch_declarations(node, *normal_visitors)
        for exits, break_visitor in pending_breaks:
            break_visitor.pending_finally_breaks = self.pending_finally_breaks
            analyzed_finalbody = break_visitor.visit_body(node.finalbody)
            if not body_can_fall_through(
                analyzed_finalbody,
                loop_control_exits=True,
            ):
                continue
            if self.pending_finally_breaks:
                self.pending_finally_breaks[-1].append((exits, break_visitor))
            else:
                exits.append(break_visitor)
        return ast.Try(
            body=analyzed_body,
            handlers=handlers,
            orelse=orelse,
            finalbody=finalbody,
            lineno=node.lineno,
        )

    @staticmethod
    def exception_base_class():
        name = "BaseException" if "BaseException" in BUILTINS.scope.names else "Exception"
        exception_class = BUILTINS.search(name)
        assert isinstance(exception_class, Class)
        return exception_class

    def analyze_exception_handler_type(
        self,
        handler: ast.ExceptHandler,
    ) -> tuple[ast.expr | None, Class | UnionType]:
        exception_class = self.exception_base_class()
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
                    help=f"Catch {exception_class.name} or a subclass of {exception_class.name}.",
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
        context, target, enter, exit_, declares_target = self.analyze_with_item(item)
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

    def analyze_with_item(self, item: ast.withitem):
        """Analyze a manager header before its protected body is visited."""
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
                        "Define both __enter__() and __exit__() on the context manager."
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
            if isinstance(target, (ast.List, ast.Tuple)):
                self.fail(
                    target,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "context-manager result unpacking is not supported",
                    help=(
                        "Bind the result to one name, then unpack it in the "
                        "with block."
                    ),
                )
            target, declares_target = self.resolve_assignment_target(
                target,
                enter_type,
            )
            target_value = (
                analyzed_value_object(target)
                if hasattr(target, "obj")
                else self.scope.lookup(target.id) if isinstance(target, ast.Name) else None
            )
            if isinstance(target_value, Instance):
                apply_representation(target_value, enter.return_representation)
        return context, target, enter, exit_, declares_target

    def visit_ListComp(self, node: ast.ListComp):
        return self.sequence_comprehension(node, "list", ListComp)

    def sequence_comprehension(self, node, collection, expression):
        visitor, generators = self.analyze_comprehension_generators(node)
        contextual_type = contextual_collection_type(self.contextual_types.get(node), collection)
        representation = self.contextual_representations.get(node)
        elt = visitor.visit_contextual_expression(
            node.elt,
            contextual_type.generic_types["V"] if contextual_type is not None else None,
            expected_representation=representation.arguments[0] if representation and representation.arguments else None,
        )
        result = expression(
            BUILTINS.search(collection)(analyzed_value_type(elt)),
            elt=elt,
            generators=generators,
        )
        result.scope = visitor.scope
        set_analyzed_representation(
            result,
            compound_representation(arguments=(analyzed_representation(elt),)),
        )
        return result

    def comprehension_visitor(self):
        visitor = type(self)(self.func, LocalScope(self.scope))
        visitor.deferred_parent = self.deferred_parent
        return visitor

    def analyze_comprehension_generators(self, node):
        visitor = self.comprehension_visitor()
        for generator_node in node.generators:
            if generator_node.is_async:
                self.fail(
                    generator_node.target,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    "asynchronous comprehensions are not supported",
                    help=("Use an explicit async loop before building the collection."),
                )
        # Only the outer source uses the enclosing scope. Every target is local
        # throughout the body, even in filters preceding its first assignment.
        outer = node.generators[0].iter
        iter_node = visitor.mapping_keys_iterable(visitor.visit(outer))
        sources = {0: (iter_node, visitor.require_iterable(outer, iter_node))}
        targets = {}
        for index, generator in enumerate(node.generators):
            for target in ast.walk(generator.target):
                if isinstance(target, ast.Name):
                    targets.setdefault(target.id, index)
        resolving = set()

        def source(index):
            if index not in sources:
                expression = node.generators[index].iter
                if index in resolving:
                    self.fail(expression, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "cannot infer cyclic comprehension target types",
                              help="Use independently typed iterable sources for comprehension targets.")
                resolving.add(index)
                value = visitor.mapping_keys_iterable(visitor.visit(expression))
                sources[index] = value, visitor.require_iterable(expression, value)
                resolving.remove(index)
            return sources[index]

        def resolve(name):
            if name in targets:
                index = targets[name]
                _, protocol = source(index)
                self.bind_comprehension_target(target_visitor, node.generators[index].target,
                                               protocol.item_type, protocol.item_representation)

        visitor.scope = comprehension_scope = ComprehensionScope(self.scope, resolve)
        target_visitor = visitor
        if isinstance(node, ast.GeneratorExp):
            # The outer iterable was evaluated above, in the enclosing scope.
            # Only the remaining clauses/body execute after construction.
            visitor.deferred_parent = self.scope
        generators = []
        for index, generator_node in enumerate(node.generators):
            iter_node, protocol = source(index)
            # The source still uses the previous target's proofs. Assigning the
            # next item then invalidates both that name and its field proofs.
            visitor = visitor.invalidate_written_narrowings([generator_node.target])
            self.bind_comprehension_target(
                visitor,
                generator_node.target,
                protocol.item_type,
                protocol.item_representation,
            )
            target = visitor.visit(generator_node.target)
            conditions = []
            for condition in generator_node.ifs:
                conditions.append(visitor.visit(condition))
                # Later filters, inner sources and the result execute only
                # after this filter passed. Keep their ordinary flow proofs.
                visitor = visitor.narrow_for_condition(condition, True)
            generator = ast.comprehension(
                target=target,
                iter=iter_node,
                ifs=conditions,
                is_async=0,
            )
            generator.runtime_methods = protocol.methods
            generators.append(generator)
        # Do not retain the source-inference closure after all targets are typed.
        comprehension_scope.resolve = None
        return visitor, generators

    def bind_comprehension_target(
        self,
        visitor,
        target,
        value_type,
        representation=None,
    ):
        if isinstance(target, ast.Name):
            value = value_type(target.id, visitor.scope, self.func)
            apply_representation(value, representation)
            visitor.scope.add(value)
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
        item_representations = (
            representation.arguments
            if representation is not None
            and len(representation.arguments) == len(item_types)
            else (None,) * len(item_types)
        )
        for item_target, item_type, item_representation in zip(
            target.elts,
            item_types,
            item_representations,
            strict=True,
        ):
            self.bind_comprehension_target(
                visitor,
                item_target,
                item_type,
                item_representation,
            )

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
        representation = self.contextual_representations.get(node)
        members = representation.arguments if representation and len(representation.arguments) == 2 else (None, None)
        key = visitor.visit_contextual_expression(node.key, expected_key_type, expected_representation=members[0])
        value = visitor.visit_contextual_expression(
            node.value,
            expected_value_type,
            expected_representation=members[1],
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
        result = DictComp(
            dict_type,
            key=key,
            value=value,
            generators=generators,
        )
        result.scope = visitor.scope
        set_analyzed_representation(
            result,
            compound_representation(
                arguments=(
                    analyzed_representation(key),
                    analyzed_representation(value),
                )
            ),
        )
        return result

    def visit_SetComp(self, node: ast.SetComp):
        return self.sequence_comprehension(node, "set", SetComp)

    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        return self.sequence_comprehension(node, "Iterator", GeneratorExp)

    # endregion

    # region conditionals

    def dynamic_truth_test(self, node, test):
        dynamic_bool = BUILTINS.search("object").find("__dynamic_bool__")
        assert isinstance(dynamic_bool, Function)
        result = self.call_node(
            node, dynamic_bool.return_type,
            func=Attribute(dynamic_bool, value=test, attr=dynamic_bool.name),
            args=[], keywords=[],
        )
        result.runtime_methods = truthiness_methods(analyzed_value_type(test))
        for method in result.runtime_methods:
            if method is not self.func and not method.is_analyzed:
                raise DependencyError(method)
        return result

    def guard_value(self, value, *, preserve_local=False):
        """A fresh guard read, optionally retaining current-execution proofs."""
        return value

    def truth_test(self, node, test):
        test_type = analyzed_value_type(test)
        if test_type is BUILTINS.search("bool"):
            return test
        if isinstance(test_type, UnionType) or (
            isinstance(test_type, Class) and test_type.container.scope.is_builtins
            and test_type.generic_name == "Iterable"
        ):
            return self.dynamic_truth_test(node, test)
        try:
            func = test_type.find("__bool__")
        except NameError:
            try:
                func = test_type.find("__len__")
            except NameError:
                return test
        if not func.is_analyzed:
            raise DependencyError(func)
        return ast.copy_location(Call(
            func.return_type,
            func=Attribute(func, value=test, attr=func.name),
            args=[],
            keywords=[],
        ), node)

    def visit_If(self, node: ast.If):
        test = self.visit(node.test)
        test = self.truth_test(node.test, test)
        body_visitor = self.branch_visitor(node.test, True)
        orelse_visitor = self.branch_visitor(node.test, False)
        body = body_visitor.visit_body(node.body)
        orelse = orelse_visitor.visit_body(node.orelse)
        self.merge_branch_declarations(node, body_visitor, orelse_visitor)
        return ast.If(
            test=test,
            body=body,
            orelse=orelse,
        )

    def conditional_numeric_format(self, node, body, orelse):
        contextual_format = self.contextual_numeric_formats.get(node)
        branch_formats = tuple(analyzed_numeric_format(value) for value in (body, orelse))
        context_converts_branches = contextual_format is not None and all(
            value_format is None or value_format == contextual_format
            for value_format in branch_formats
        )
        typed_representations = tuple(
            (analyzed_value_type(value), analyzed_representation(value))
            for value in (body, orelse)
        )
        if (
            representations_conflict(typed_representations)
            and mixed_numeric_formats((body, orelse))
            and not context_converts_branches
        ):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "Conditional branches use incompatible numeric representations",
                help=(
                    "Convert both branches to one fixed-width type, or use ordinary "
                    "Python numbers in both branches."
                ),
            )
        result = contextual_format or common_numeric_format((body, orelse))
        if result is not None:
            for value in (body, orelse):
                if analyzed_numeric_format(value) is None:
                    self.validate_wgsl_integer_literal(
                        getattr(value, "python_node", value),
                        value,
                        result,
                    )
        return result

    def validate_conditional_array_formats(self, node, body, orelse) -> None:
        typed_representations = tuple(
            (analyzed_value_type(value), analyzed_representation(value))
            for value in (body, orelse)
        )
        if representations_conflict(typed_representations) and mixed_array_formats(
            (body, orelse)
        ):
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                "Conditional branches use incompatible array layouts",
                help=(
                    "Use one StaticArray type in both branches, or use ordinary "
                    "lists in both branches."
                ),
            )

    def prepare_conditional_values(self, body, orelse):
        """Type fresh empty branches before their allocations enter the IR."""
        self.infer_empty_collection_literals([body, orelse])

    def visit_IfExp(self, node: ast.IfExp):
        test = self.visit(node.test)
        test = self.truth_test(node.test, test)
        body_visitor = self.narrow_for_condition(node.test, True)
        orelse_visitor = self.narrow_for_condition(node.test, False)
        body = body_visitor.visit_contextual_expression(
            node.body, self.contextual_types.get(node),
            expected_representation=self.contextual_representations.get(node),
        )
        orelse = orelse_visitor.visit_contextual_expression(
            node.orelse, self.contextual_types.get(node),
            expected_representation=self.contextual_representations.get(node),
        )
        self.prepare_conditional_values(body, orelse)
        body_type = analyzed_value_type(body)
        orelse_type = conditional_value_type(orelse, body_type)
        body_type = conditional_value_type(body, orelse_type)
        branch_representations = (
            (body_type, analyzed_representation(body)),
            (orelse_type, analyzed_representation(orelse)),
        )
        result_format = self.conditional_numeric_format(node, body, orelse)
        self.validate_conditional_array_formats(node, body, orelse)
        if (
            representations_conflict(branch_representations)
            and result_format is None
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
        value_obj = result_type(
            "__conditional_result__",
            self.scope,
            self.func,
        )
        representation = (
            direct_representation(result_format, None)
            if result_format is not None
            else merged_representation(
                result_type,
                branch_representations,
            )
        )
        result = IfExp(
            result_type,
            value_obj=value_obj,
            test=test,
            body=body,
            orelse=orelse,
        )
        set_analyzed_representation(result, representation)
        return result

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
        return assertion

    def visit_Raise(self, node: ast.Raise):
        if node.exc is None and not self.in_exception_handler:
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "bare raise requires an active exception handler",
                help="Raise an explicit exception in this context.",
            )
        if node.cause is not None and not self.supports_exception_causes:
            self.fail(
                node.cause,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                "exception chaining with 'raise ... from ...' is not supported",
                help="Raise the exception without an explicit cause.",
            )
        exc = self.visit(node.exc) if node.exc is not None else None
        if exc is not None:
            exception_type = self.exception_base_class()
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
        cause = self.visit(node.cause) if node.cause is not None else None
        if cause is not None:
            exception_type = self.exception_base_class()
            if not all(
                isinstance(member, Class) and (
                    member is get_none_type() or is_subclass(member, exception_type)
                )
                for member in get_type_members(analyzed_value_type(cause))
            ):
                self.fail(
                    node.cause,
                    DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                    "exception cause requires an exception instance or None",
                    help="Construct the cause exception or use 'from None'.",
                )
        return ast.Raise(exc=exc, cause=cause)

    # endregion


class CallGraphVisitor(ast.NodeVisitor):
    def __init__(self, func: Function, entry_point: Function):
        self.func = func
        self.entry_point = entry_point

    def visit(self, node):
        # Conversions can occur on any expression, including a bare name or
        # an item nested in a literal, not only at an explicit call site.
        for method in getattr(node, "conversion_methods", ()):
            self.enter_virtual(method)
        for receiver_type, names in getattr(node, "conversion_protocols", ()):
            self.retain_runtime_protocol(receiver_type, names)
        for source, target in getattr(node, "conversion_views", ()):
            self.retain_view_source(source, target)
        return super().visit(node)

    @classmethod
    def start(cls, func: Function):
        cls(func, func).enter(func)

    def enter(self, func: Function):
        # Eager JavaScript analysis normally prepares every function before
        # reachability begins. Targeted analysis instead arrives here with an
        # unanalyzed root or dependency, so prepare it before code paths such
        # as source implementations inspect its signature and return type.
        if not func.is_analyzed:
            annotate_types(func)
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
        method_name = js_metadata(function.py_obj, "dispatch")
        if method_name is not None:
            self.retain_runtime_protocol(None, (method_name,))

    def retain_runtime_protocol(self, receiver_type, method_names: tuple[str, ...]) -> None:
        dependencies = self.entry_point.runtime_dunder_dependencies
        dependency = receiver_type, method_names
        if dependency in dependencies:
            return
        dependencies.add(dependency)
        for source, target in tuple(self.entry_point.runtime_view_sources):
            if receiver_type is not None and any(is_subclass(target, member)
                                                for member in get_type_members(receiver_type)):
                self.retain_runtime_protocol(source, method_names)
        # A typed receiver can arrive through a host boundary without any
        # constructor call in the analyzed program. Its own protocol is still
        # reachable; unrelated methods and its constructor are not implied.
        if receiver_type is not None:
            for member in get_type_members(receiver_type):
                if isinstance(member, Class) and not member.container.scope.is_builtins:
                    self.enter_runtime_protocol(member, method_names)
        for value in tuple(self.entry_point.compilation_objects):
            if isinstance(value, Class) and self.protocol_applies(value, receiver_type):
                self.enter_runtime_protocol(value, method_names)

    @staticmethod
    def protocol_applies(cls, receiver_type):
        # Abstract views get their concrete sources from reached conversions,
        # not a structural scan that could analyze unrelated class signatures.
        return receiver_type is None or any(
            not (is_abstract_iterable(member) or is_abstract_iterator(member)) and is_subclass(cls, member)
            for member in get_type_members(receiver_type))

    def retain_view_source(self, source, target):
        sources = self.entry_point.runtime_view_sources
        if (source, target) in sources:
            return
        sources.add((source, target))
        # Discovery can happen before or after its consumer. Existing protocol
        # deduplication closes both orders without another object-graph pass.
        for receiver, names in tuple(self.entry_point.runtime_dunder_dependencies):
            if receiver is not None and any(is_subclass(target, member) for member in get_type_members(receiver)):
                self.retain_runtime_protocol(source, names)

    def enter_runtime_protocol(self, cls: Class, method_names: tuple[str, ...]) -> None:
        # Protocol names are ordered fallbacks, not independent requirements.
        # Retain only what this reached class actually calls (e.g. __bool__
        # before __len__), including implementations inherited from its base.
        absent = object()
        for name in method_names:
            declaration = inspect.getattr_static(cls.py_obj, name, absent)
            if name == "__str__" and declaration is object.__str__:
                # Python's object default delegates to __repr__; unlike a
                # user-defined/disabled __str__, it does not stop that fallback.
                continue
            method = (cls.find_attrs(name) if declaration is absent else
                      declared_protocol_method(cls, name, declaration))
            if isinstance(method, Function):
                self.enter(method)
                if name == "__iter__" and method.return_type is not None:
                    # Acquisition exposes a cursor, not just its factory.
                    # Follow its advancement/reacquisition closure, including
                    # Self and mutually returning cursor types (deduplicated
                    # by retain_runtime_protocol before entering methods).
                    for cursor in get_type_members(method.return_type):
                        if isinstance(cursor, Class) and not cursor.container.scope.is_builtins:
                            # Builtin iterator handles already carry callbacks.
                            # Structurally matching every reached class against
                            # Iterator here can inspect unreached signatures.
                            self.retain_runtime_protocol(cursor, ("__next__",))
                            self.retain_runtime_protocol(cursor, ("__iter__",))
                break
            if declaration is not absent:
                # A present but unmodeled primary still prohibits fallback.
                # Alias/descriptor/callability validation belongs to the consumer.
                break

    def enter_virtual(self, func: Function):
        self.enter(func)
        parent = func.cls.super
        while parent is not None:
            inherited = parent.find_attrs(func.name, search_bases=False)
            if func.is_property_setter and isinstance(inherited, Function):
                inherited = inherited.property_setter
            if isinstance(inherited, Function):
                if not inherited.is_analyzed:
                    annotate_types(inherited)
                self.validate_override_storage(inherited, func)
                break
            parent = parent.super
        if self.entry_point in func.virtual_visited:
            return
        self.mark_virtual_visited(func)
        self.enter_overrides(func, func.cls)

    def retain_receiver_declaration(self, func: Function, receiver):
        value = analyzed_value_object(receiver)
        if not isinstance(value, Instance):
            return
        declared = value.storage_declaration
        if isinstance(declared, Instance):
            declared = declared.cls
        # A mutable field's refinement can outlive a mutation. Keep the stored
        # receiver's member available, not only the selected subtype override.
        for member in get_type_members(declared):
            if (not isinstance(member, Class) or member is value.cls
                    or member.container.scope.is_builtins
                    or not is_subclass(func.cls, member)):
                continue
            inherited = member.find_attrs(func.name)
            if func.is_property_setter and isinstance(inherited, Function):
                inherited = inherited.property_setter
            if isinstance(inherited, Function) and inherited is not func:
                self.enter_virtual(inherited)

    def enter_virtual_reference(self, func: Function, receiver):
        self.retain_receiver_declaration(func, receiver)
        receiver_type = analyzed_value_type(receiver)
        if (not func.cls.container.scope.is_builtins or receiver_type is func.cls
                or contains_type_variable(receiver_type)):
            # Generic receivers are not nominal bases of their substitutions.
            # Keep the existing virtual-root contract until their domain is
            # concrete; T and Box[T] cannot be used as nominal receiver filters.
            self.enter_virtual(func)
            return
        # Inherited builtin declarations do not describe the receiver domain:
        # int.__hash__ may resolve to object.__hash__, but cannot call an
        # unrelated application's override. Retain the receiver constraint for
        # classes discovered later, without marking the builtin root virtual.
        dependency = func, receiver_type
        dependencies = self.entry_point.virtual_receiver_dependencies
        if dependency in dependencies:
            return
        dependencies.add(dependency)
        self.enter(func)
        for member in get_type_members(receiver_type):
            if isinstance(member, Class) and not member.container.scope.is_builtins:
                self.enter_receiver_override(func, receiver_type, member)
        for cls in tuple(self.entry_point.compilation_objects):
            if isinstance(cls, Class):
                self.enter_receiver_override(func, receiver_type, cls)

    def enter_receiver_override(self, func: Function, receiver_type, cls: Class):
        if not is_subclass(cls, func.cls) or not any(
                is_subclass(cls, member) for member in get_type_members(receiver_type)):
            return
        override = cls.find_attrs(func.name)
        if isinstance(override, Function):
            self.enter(override)
            self.validate_override_storage(func, override)

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
        subclasses = cls.subclasses
        if cls.container.scope.is_builtins:
            # Builtin bases deliberately do not register application subclasses.
            # Find already reached roots through the complete builtin base
            # chain (not only direct children); enter_class handles later roots.
            # A builtin intermediate class has no subclass registry either.
            def inherits_builtin(value):
                parent = value.super
                while parent is not None and parent.container.scope.is_builtins:
                    if parent is cls:
                        return True
                    parent = parent.super
                return False

            subclasses = sorted(
                (value for value in self.entry_point.compilation_objects
                 if isinstance(value, Class) and inherits_builtin(value)
                 and not value.container.scope.is_builtins),
                key=lambda value: (value.container.name, value.name),
            )
        for subclass in subclasses:
            override = self.property_override(func, subclass)
            if isinstance(override, Function):
                inherited = self.enter_overrides(override, subclass)
                if self.entry_point in subclass.visited or inherited:
                    self.enter_virtual(override)
                    self.validate_override_storage(func, override)
                    visited = True
            elif self.enter_overrides(func, subclass):
                visited = True
            elif self.entry_point in subclass.visited:
                visited = True
        return visited

    def validate_override_storage(self, base: Function, override: Function) -> None:
        if (base.cls.container.scope.is_builtins and base.cls.generic_name == "object"
                and base.name == "__hash__"):
            # The object default is a protocol fallback, not a shared slot ABI.
            # hash() converts a represented integer result to ordinary int;
            # explicit base-view calls must validate their result at lowering.
            return
        incompatible_parameter = next(
            (
                child
                for parent, child in zip(
                    base.params,
                    override.params,
                    strict=False,
                )
                if getattr(parent, "representation", None)
                != getattr(child, "representation", None)
            ),
            None,
        )
        return_mismatch = base.return_representation != override.return_representation
        if incompatible_parameter is None and not return_mismatch:
            return
        node = override.original_node
        fragment = override.source_fragment
        if node is None or fragment is None:
            return
        override.cls.container.context.error(
            fragment,
            node,
            DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
            f"Override {override.cls.name}.{override.name} changes the "
            "represented storage contract",
            help=(
                "Use the same fixed-width and StaticArray annotations as the base method."
            ),
        )

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
        representation = cls.field_representations.get(name)
        display_type = (
            ast.unparse(node)
            if representation is not None
            else declared_type.to_annotation_str()
        )
        return (
            Label(
                fragment.span(node),
                f"{self.class_display_name(cls)}.{name} is declared as "
                f"{display_type} here",
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
                parent_representation = parent.field_representations.get(name)
                declared_representation = cls.field_representations.get(name)
                if (
                    not is_return_type_compatible(parent_type, declared_type)
                    or parent_representation != declared_representation
                ):
                    node = cls.field_declaration_nodes[name]
                    parent_node = parent.field_declaration_nodes.get(name)
                    actual = ast.unparse(node)
                    expected = (
                        ast.unparse(parent_node)
                        if parent_node is not None
                        else parent_type.to_annotation_str()
                    )
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
            if expected_type is None:
                continue
            expected_representation = (
                cls.field_representations.get(name)
                if declared_type is not None
                else parent.field_representations.get(name)
            )
            actual_representation = cls.field_initializer_representations.get(name)
            if (
                actual_representation is not None
                and actual_representation != expected_representation
            ):
                cls.container.context.error(
                    fragment,
                    cls.field_value_nodes[name],
                    DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                    f"Cannot change the represented storage of field "
                    f"{field_name!r} in its default value",
                    secondary=(
                        self.field_declaration_label(parent, name, expected_type)
                        if parent is not None
                        else ()
                    ),
                    help=(
                        "Construct the default explicitly with the field's declared type."
                    ),
                )
            static_value = (
                field.static_value.value
                if isinstance(field.static_value, ast.Constant)
                else None
            )
            actual_type = literal_member_for_value(
                expected_type, static_value
            ) or cls.field_initializer_types.get(name, field.cls)
            if is_return_type_compatible(expected_type, actual_type):
                continue
            actual = actual_type.to_annotation_str()
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
                for method, receiver in tuple(self.entry_point.virtual_receiver_dependencies):
                    self.enter_receiver_override(method, receiver, cls)
                for dependency in sorted(
                    getattr(cls, "client_model_dependencies", ()),
                    key=lambda item: (item.container.name, item.name),
                ):
                    dependency.client_model_registry_required = True
                    if dependency.container is not cls.container:
                        cls.container.side_effect_dependencies.add(dependency)
                    self.enter_class(dependency)
                    self.enter(dependency.find("__init__"))
                for receiver_type, method_names in tuple(
                    self.entry_point.runtime_dunder_dependencies
                ):
                    if self.protocol_applies(cls, receiver_type):
                        self.enter_runtime_protocol(cls, method_names)
                post_definition = js_metadata(
                    cls.py_cls,
                    "post_definition_source",
                )
                if post_definition is not None:
                    self.enter_code_references(cls, post_definition)
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
                    elif attr.is_property and self.base_annotates(attr):
                        # Reads resolve to the base declaration, not this getter.
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

    def enter_code_references(self, owner: Class | Function, source=None):
        """Retain references named only inside generated JavaScript source."""
        references = dict(backend_references(owner.py_obj, "js"))
        if source is not None:
            for name, reference in backend_references(source, "js").items():
                previous = references.get(name)
                if previous is not None and previous is not reference:
                    raise TypeError(
                        f"Generated code reference {name!r} has conflicting values."
                    )
                references[name] = reference
        module = (
            owner.container
            if isinstance(owner, Class)
            else (owner.cls.container if owner.is_method else owner.container)
        )
        for name, reference in references.items():
            if is_js_enabled(reference) is not True:
                if is_js_enabled(reference) is False:
                    help_text = (
                        f"Remove @nojs from {reference.__name__!r} if it should "
                        "run on the client."
                    )
                else:
                    help_text = f"Decorate {reference.__name__!r} with @js."
                module.context.definition_error(
                    owner.py_obj,
                    DiagnosticCode.MISSING_JS_DECORATOR,
                    f"JavaScript reference {name!r} of generated code for "
                    f"{owner.name!r} is not available to client code",
                    help=help_text,
                )
            try:
                # Raw source uses the declared name directly. Inline templates
                # instead receive collision-free aliases at each call site.
                dependency_obj = module.search(name)
            except NameError:
                traverse_imported(name, reference, module)
                dependency_obj = module.search(name)
            if dependency_obj.py_obj is not reference:
                raise NameError(
                    f"Generated code reference conflicts with existing {name!r}."
                )
            if isinstance(dependency_obj, Class):
                self.enter_class(dependency_obj)
                self.enter(dependency_obj.find("__init__"))
            elif isinstance(dependency_obj, Function):
                self.enter(dependency_obj)
            else:
                raise TypeError(
                    f"Generated code reference {name!r} must be a class or function."
                )

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

    @staticmethod
    def base_annotates(func: Function) -> bool:
        parent = func.cls.super
        while parent is not None:
            annotations = getattr(parent.py_cls, "__pyjs_instance_annotations__", None)
            if annotations is None:
                annotations = getattr(parent.py_cls, "__annotations__", {})
            if func.name in annotations:
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
            if isinstance(receiver.func.obj, Class) and not isinstance(receiver.func.obj, CallableClass):
                # A callable result is represented by CallableClass too, but
                # invoking it does not construct an exact instance of its
                # declared return type. Preserve virtual dispatch on the result.
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
            client_result_type = func.return_type
            if remote_operation is not None and remote_operation.kind == "stream":
                client_result_type = func.return_type.generic_types["Value"]
            if remote_operation is not None and not is_supported_client_result_type(
                client_result_type
            ):
                module.context.definition_error(
                    func.py_func,
                    DiagnosticCode.UNSUPPORTED_CLIENT_RESULT,
                    f"Operation {func.name!r} has unsupported client result type "
                    f"{client_result_type.to_annotation_str()!r}.",
                    help=(
                        "Return a supported primitive, Pydantic model, optional, "
                        "list, dictionary, tuple, set, or Page value."
                    ),
                )
            if (
                remote_operation is not None
                and not remote_operation.jsonapi
                and client_result_requires_decoding(client_result_type)
            ):
                decoder = func.cls.find("_decode_result")
                assert isinstance(decoder, Function)
                self.enter_virtual(decoder)
            for dependency_obj in client_model_types(func.return_type):
                if remote_operation is not None and not remote_operation.jsonapi:
                    dependency_obj.client_model_registry_required = True
                self.enter_class(dependency_obj)
                self.enter(dependency_obj.find("__init__"))
            implementation = own_js_metadata(func.py_func, "implementation")
            source = implementation.value if implementation is not None else None
            self.enter_code_references(func, source)
            return
        if self.entry_point not in func.visited:
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
        if dependency is None:
            self.generic_visit(node)
            return
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

    def visit_IteratorCreate(self, node):
        # IR replaces the source For, but acquiring its iterator still calls
        # the same protocol methods (including reached virtual overrides).
        self.visit_For(node)

    def visit_ExceptionRaise(self, node):
        # Lowering removes the constructor call, but not its backend-declared
        # formatting/validation dependencies.
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        for receiver_type, names in getattr(node, "runtime_protocols", ()):
            self.retain_runtime_protocol(receiver_type, names)
        self.generic_visit(node)

    # Backends may attach dependencies to completion values as well as raises.
    visit_Return = visit_ExceptionRaise

    def visit_comprehension(self, node: ast.comprehension):
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        self.generic_visit(node)

    def visit_Starred(self, node: Starred):
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        self.generic_visit(node)

    def visit_Dict(self, node):
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        for receiver_type, names in getattr(node, "runtime_protocols", ()):
            self.retain_runtime_protocol(receiver_type, names)
        self.generic_visit(node)

    visit_Set = visit_Dict

    def collect_tailwind_classes(self, node: ast.Call):
        func = node.func.obj
        if not (
            isinstance(func, Function)
            and func.py_obj.__module__ == "pyjs.web.domx"
            and func.name == "tw"
        ):
            return
        argument = node.args[0] if node.args else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "classes"),
            None,
        )
        # tw() still returns a class dictionary for dynamic values. Extraction
        # is static: do not evaluate application code or invent CSS for those
        # values. Resolve the function, not its spelling, so aliases work and
        # unrelated application functions named tw are not treated as markers.
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            self.entry_point.tailwind_classes.update(argument.value.split())

    def retain_hydration_reference(self, node):
        if not getattr(node, "is_ref", False) or not isinstance(node.obj, Class):
            return
        method = getattr(node.obj.py_cls, "__pyjs_reference_method__", None)
        if method is None:
            return
        module = self.func.cls.container if self.func.is_method else self.func.container
        if node.obj.container is not module:
            node.hydration_type_alias = module.register_inline_dependency(node.obj, self.entry_point)
        self.enter_class(node.obj)
        self.enter(node.obj.find(method))

    def visit_Call(self, node: ast.Call):
        self.collect_tailwind_classes(node)
        self.retain_hydration_reference(node)
        func = node.func.obj
        module = self.func.cls.container if self.func.is_method else self.func.container
        for name, dependency in getattr(node, "dependency_objects", {}).items():
            node.inline_dependencies[name] = module.register_inline_dependency(
                dependency,
                self.entry_point,
            )
            if isinstance(dependency, Class):
                self.enter_class(dependency)
                self.enter(dependency.find("__init__"))
            else:
                self.enter(dependency)
        for method in getattr(node, "runtime_methods", ()):
            self.enter_virtual(method)
        for receiver_type, names in node.runtime_protocols:
            self.retain_runtime_protocol(receiver_type, names)
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
                if forwarded_func.obj.is_staticmethod:
                    # Static forwarding omits the receiver argument,
                    # not its source evaluation or reachable dependencies.
                    self.visit(forwarded_func.value)
                if self.is_virtual_method_reference(forwarded_func):
                    self.enter_virtual_reference(forwarded_func.obj, forwarded_func.value)
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
                self.retain_receiver_declaration(setter, node.value)
                self.enter_virtual(setter)
            self.generic_visit(node)
            return
        if getters := getattr(node, "property_getters", ()):
            for getter in dict.fromkeys(getters):
                self.retain_receiver_declaration(getter, node.value)
                self.enter_virtual(getter)
            self.generic_visit(node)
            return
        union_functions = getattr(node, "union_functions", ())
        if union_functions:
            for func in dict.fromkeys(union_functions):
                if self.is_virtual_method_reference(node):
                    self.enter_virtual_reference(func, node.value)
                else:
                    self.enter(func)
        elif isinstance(node.obj, Function):
            if self.is_virtual_method_reference(node):
                self.enter_virtual_reference(node.obj, node.value)
            else:
                self.enter(node.obj)
        elif isinstance(node.obj, Instance):
            if self.is_virtual_field_reference(node):
                self.enter_virtual_field(node.obj)
            else:
                field = node.obj
                if isinstance(node.value, Call) and isinstance(
                    node.value.func.obj, Class
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
        self.enter_virtual_reference(node.obj, node.receiver)
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
        if is_inline_for(func.py_obj, "js") or func.has_source_decorator:
            return
        type(self)(func, self.entry_point).visit(func.node)

    def enter_class(self, cls: Class):
        # Client protocol discovery scans compilation_objects for classes.
        # Keep render construction separate: sharing that population can ship
        # server-only methods, or skip overrides first discovered by hydration.
        if cls not in self.entry_point.render_classes:
            self.entry_point.render_classes.add(cls)
            for method in tuple(self.entry_point.render_virtual_dependencies):
                self.enter_render_override(method, cls)
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

    def enter_virtual(self, func: Function):
        # Render dispatch must not mark client virtual_visited: a later
        # hydration walk would otherwise retain server-only method bodies.
        dependencies = self.entry_point.render_virtual_dependencies
        if func in dependencies:
            return
        dependencies.add(func)
        self.enter(func)
        for cls in tuple(self.entry_point.render_classes):
            self.enter_render_override(func, cls)

    def enter_virtual_reference(self, func: Function, receiver):
        # Render-only getattr references must not publish client dependencies.
        self.enter_virtual(func)

    def enter_render_override(self, func: Function, cls: Class):
        if not is_subclass(cls, func.cls):
            return
        override = cls.find_attrs(func.name)
        if func.is_property_setter and isinstance(override, Function):
            override = override.property_setter
        if isinstance(override, Function):
            self.validate_override_storage(func, override)
            self.enter(override)

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
        self.collect_tailwind_classes(node)
        # Named targets are handled below; computed callees also evaluate
        # dependencies. len(tw(...)), for example, calls tw(...).__len__().
        if not isinstance(node.func, Name):
            self.visit(node.func)
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
        accessors = getattr(node, "property_setters", ()) or getattr(node, "property_getters", ())
        if accessors:
            for accessor in dict.fromkeys(accessors):
                self.enter_virtual(accessor)
            # Union properties also carry union_functions, but their value is
            # a property result, not an ordinary bound method reference.
            self.generic_visit(node)
            return
        target = getattr(node, "obj", None)
        functions = getattr(node, "union_functions", ())
        if not functions and isinstance(target, Function):
            functions = (target,)
        for target in dict.fromkeys(functions):
            if self.is_virtual_method_reference(node):
                self.enter_virtual(target)
            else:
                self.enter(target)
            if (target.is_static and isinstance(node.value, Name)
                    and isinstance(node.value.obj, Class)):
                # Reading a static/class method from a class is not instance
                # construction. An instance receiver must still be evaluated.
                return
        self.generic_visit(node)

    def visit_Name(self, node: Name):
        if isinstance(getattr(node, "obj", None), Function):
            # Returned, conditional and indexed callees carry their function
            # dependency as a value; retain it only in the render graph.
            self.enter(node.obj)
        elif isinstance(getattr(node, "obj", None), Class):
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
        reference = hydration_ref_call(node.value)
        if reference is None:
            return
        self.client.retain_hydration_reference(reference)
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
    configure_js(entry_point, enabled=True)
    for additional_entry_point in additional_entry_points:
        configure_js(additional_entry_point, enabled=True)
    for render_entry_point in render_entry_points:
        configure_js(render_entry_point, enabled=True)
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
        if isinstance(value, _ActiveBuiltins):
            # The proxy has no analyzer graph of its own. Follow the selected
            # target module so compilation cleanup still reaches its generics.
            pending.append(value.module)
            continue
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
                pending.extend(
                    item for item in child.values() if isinstance(item, Object)
                )
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
    def capture(cls, builtins_module: Module) -> _SharedAnalyzerState:
        generics = tuple(
            value
            for value in builtins_module.scope.names.values()
            if isinstance(value, GenericClass)
        )
        state = cls(
            {
                module: tuple(module.type_dependencies)
                for module in (builtins_module,)
            },
            {
                generic: set(generic.concrete_classes)
                for generic in generics
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
        root.render_classes.clear()
        root.render_virtual_dependencies.clear()
        root.compilation_entry_points = ()
        root.runtime_dunder_dependencies.clear()
        root.virtual_receiver_dependencies.clear()
        root.runtime_view_sources.clear()
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
    environment: AnalysisEnvironment | None = None,
):
    environment = environment or JS_ENVIRONMENT
    if entry_point is None:
        assert hasattr(py_module, "main"), (
            "No entry_point specified and no main() function found."
        )
        if environment.name == "js":
            configure_js(py_module.main, enabled=True)
        entry_point = py_module.main
    builtins_module = environment.builtins
    environment_token = _ACTIVE_ENVIRONMENT.set(environment)
    shared_state = _SharedAnalyzerState.capture(builtins_module)
    entry_point_function = None
    try:
        package = {}
        context = CompilationContext()
        entry_points = (
            entry_point,
            *additional_entry_points,
            *render_entry_points,
        )
        definition_filter = environment.definition_filter
        if definition_filter is not None:
            target_filter = definition_filter

            # Target policies select ordinary definitions, while the analyzer
            # owns the entry-point convention. This keeps synthetic ``main``
            # functions and explicit roots without teaching every target their
            # names or accidentally retaining an imported function named main.
            def definition_filter(name, value, module):
                return any(value is root for root in entry_points) or target_filter(
                    name,
                    value,
                    module,
                )

        module = Module(
            py_module,
            package,
            extensions=extensions,
            context=context,
            defer_unselected_imports=environment.defer_unselected_imports,
            definition_filter=definition_filter,
            library_mappings=environment.library_mappings,
            backend=environment.name,
        ).build()
        package[module.name] = module
        entry_point_functions = [
            resolve_entry_point(module, py_func) for py_func in entry_points
        ]
        entry_point_function = entry_point_functions[0]
        assert isinstance(entry_point_function, Function)
        entry_point_function.compilation_entry_points = (entry_point_function,)
        entry_point_function.compilation_cleanup = shared_state.close
        if environment.analyze_all_definitions:
            prepared = set()
            while pending := [
                value for value in package.values() if value not in prepared
            ]:
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
            finalize_entry_point_analysis(entry_point_function)
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
            finalize_entry_point_analysis(render_function)
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
    finally:
        _ACTIVE_ENVIRONMENT.reset(environment_token)


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
    finalize_entry_point_analysis(entry_point_func)
    return entry_point_func, entry_point_func.tailwind_classes


def finalize_entry_point_analysis(entry_point_func: Function) -> None:
    finalizer = _ACTIVE_ENVIRONMENT.get().analysis_finalizer
    if finalizer is not None:
        finalizer(entry_point_func)


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
    inference_visitor = _ACTIVE_ENVIRONMENT.get().inference_visitor
    while True:
        dependencies = TopologicalSorter()
        added = False
        for func in functions:
            if func.is_analyzed:
                continue
            try:
                flow_widenings = {}
                while True:
                    func.reset()
                    visitor = inference_visitor(func)
                    visitor.flow_widenings = flow_widenings
                    try:
                        visitor.visit(func.original_node)
                    except CompilationError:
                        # A provisional proof can affect later diagnostics.
                        # Report only after all recorded widenings are applied.
                        if not visitor.pending_flow_widenings:
                            raise
                    if not visitor.pending_flow_widenings:
                        break
                    for site, invalid in visitor.pending_flow_widenings.items():
                        names = flow_widenings.setdefault(site, set())
                        if not invalid - names:
                            raise RuntimeError("flow widening must make progress")
                        names.update(invalid)
                func.is_analyzed = True
            except DependencyError as e:
                if isinstance(e.class_or_func, Class):
                    module = func.cls.container if func.is_method else func.container
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
                inference_visitor = _ACTIVE_ENVIRONMENT.get().inference_visitor
                visitor = inference_visitor(context)
                analyzed = visitor.analyze_assignment_value(
                    initializer,
                    value.cls.annotation,
                )
                analyzed_value = visitor.normalize_stored_value(
                    initializer,
                    analyzed.node,
                    value.representation,
                    value.cls,
                )
                value.static_value = ast.fix_missing_locations(analyzed_value)
                break
            except DependencyError as dependency:
                annotate_types(dependency.class_or_func)


def load_builtins(
    python_builtins,
    library_mappings: LibraryMappings,
    *,
    mark_js=False,
    backend="js",
):
    for name, value in vars(python_builtins).items():
        if not (
            name.startswith("_")
            and not name.startswith("__")
            and is_cls_or_func(value)
        ):
            continue
        if mark_js:
            # The JavaScript semantic classes are also imported as ordinary
            # implementation dependencies, where they must remain visible to
            # the existing JS module selector.
            configure_js(value, enabled=True)
        value.__builtin__ = True
    return Module(
        python_builtins,
        {},
        is_builtins=True,
        library_mappings=library_mappings,
        backend=backend,
        definition_filter=lambda _name, value, _module: bool(
            getattr(value, "__builtin__", False)
        ),
    ).build()


JS_BUILTINS = load_builtins(
    python_builtins,
    PYJS_LIBRARY_MAPPINGS,
    mark_js=True,
)


class JavaScriptInferenceVisitor(InferenceVisitor):
    """JavaScript analysis policy."""

    numeric_domains = frozenset({"portable", "wgsl", "javascript"})


JS_ENVIRONMENT = AnalysisEnvironment(
    "js",
    JS_BUILTINS,
    PYJS_LIBRARY_MAPPINGS,
    JavaScriptInferenceVisitor,
)
_ACTIVE_ENVIRONMENT = ContextVar(
    "pyjs_analysis_environment",
    default=JS_ENVIRONMENT,
)


class _ActiveBuiltins:
    """Resolve shared analyzer lookups against the current target semantics.

    Most analyzer code intentionally keeps using the single ``BUILTINS`` name.
    The context-local proxy avoids mutating that global during nested source
    analyses while allowing JS and WGSL to provide different Python surfaces.
    """

    @property
    def module(self):
        return _ACTIVE_ENVIRONMENT.get().builtins

    @property
    def scope(self):
        return self.module.scope

    def search(self, name):
        return self.module.search(name)


ModuleScope.BUILTINS = BUILTINS = _ActiveBuiltins()
annotate_types(JS_BUILTINS)


def create_analysis_environment(
    name: str,
    semantic_builtins,
    *,
    inference_visitor: type[InferenceVisitor],
    library_mappings: LibraryMappings | None = None,
    analyze_all_definitions: bool = True,
    defer_unselected_imports: bool = False,
    definition_filter: Callable[[str, object, Module], bool] | None = None,
    body_filter: Callable[[Function], bool] | None = None,
    analysis_finalizer: Callable[[Function], None] | None = None,
) -> AnalysisEnvironment:
    """Build and type-check the Python surface for an external backend."""
    mappings = library_mappings if library_mappings is not None else LibraryMappings()
    builtins = load_builtins(semantic_builtins, mappings, backend=name)
    environment = AnalysisEnvironment(
        name,
        builtins,
        mappings,
        inference_visitor,
        analyze_all_definitions=analyze_all_definitions,
        defer_unselected_imports=defer_unselected_imports,
        definition_filter=definition_filter,
        body_filter=body_filter,
        analysis_finalizer=analysis_finalizer,
    )
    token = _ACTIVE_ENVIRONMENT.set(environment)
    try:
        annotate_types(builtins)
    finally:
        _ACTIVE_ENVIRONMENT.reset(token)
    return environment
