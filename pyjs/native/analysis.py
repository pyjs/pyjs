"""Shared analysis configuration for native backends."""

import ast
import builtins
import functools
import importlib
import inspect
import operator
import types
import typing
from copy import copy

from pyjs.analysis import create_analysis_environment
from pyjs.analysis.analyzer import (
    BUILTINS,
    InferenceVisitor,
    analyzed_value_object,
    analyzed_value_type,
    body_can_fall_through,
    contextual_collection_type,
    declared_protocol_method,
    equality_methods,
    flatten_isinstance_targets,
    get_type_members,
    inequality_methods,
    inherits_object_comparison,
    is_return_type_compatible,
    iterable_is_provably_nonempty,
    iterable_item_type,
    iterable_protocol,
    merge_return_types,
    runtime_dunder_methods,
    same_analyzer_type,
    should_analyze_target_body,
)
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.ir import GeneratorInput, IRInferenceVisitor, Suspend
from pyjs.analysis.iterable_protocol import (
    is_abstract_iterable,
    is_abstract_iterator,
    retain_iterable_conversion,
)
from pyjs.analysis.lifetime import refine_lifetimes
from pyjs.analysis.objects import (
    AnalyzedExpression,
    Attribute,
    CallableClass,
    Class,
    Constant,
    EvaluateOnce,
    Function,
    GenericClass,
    Instance,
    LocalScope,
    Module,
    ModuleAlias,
    Name,
    Starred,
    StaticCast,
    Tuple,
    TypedDictClass,
    UnionType,
    resolve_imported,
)
from pyjs.analysis.representation import apply_representation, tuple_representation
from pyjs.analysis.type_relations import (
    is_builtin_class,
    is_isinstance_match,
    is_subclass,
)
from pyjs.analysis.value_representation import (
    analyzed_array_format,
    analyzed_numeric_format,
    analyzed_representation,
    compound_representation,
    merged_representation,
    representation_for_member,
    representations_conflict,
    set_analyzed_representation,
)
from pyjs.decorators import get_native_decoration, is_empty_inline
from pyjs.python import native as native_builtins
from pyjs.python.native_libraries import NativeProtocolMappings
from pyjs.web.dom import DOMTokenList
from pyjs.web.dom import Element as WebElement
from pyjs.web.domx import CustomElement
from pyjs.web.html import (
    HTMLButtonElement,
    HTMLInputElement,
    HTMLSelectElement,
    HTMLTextAreaElement,
)

from . import dataclasses as dataclass_ops
from . import dom_types, enum_ops, models, nullable, super_proxy, unpacking
from .expressions import NativeExpressionLowering


def expands_arguments(node):
    return (any(isinstance(argument, ast.Starred) for argument in node.args)
            or any(keyword.arg is None for keyword in node.keywords))


def is_fromkeys_call(node):
    target = analyzed_value_object(node.func) if isinstance(node, ast.Call) else None
    return (getattr(getattr(target, "cls", None), "py_obj", None) is native_builtins._dict
            and target.name == "fromkeys")


def empty_fromkeys_keys(node):
    source = node.args[0]
    if hasattr(source, "mapping_source_type"):
        source = source.func.value
    if (isinstance(source, (ast.List, ast.Tuple)) and not source.elts
            or isinstance(source, ast.Dict) and not source.keys):
        return source
    return None


def generator_representation_compatible(source, target, actual, expected):
    """Check reference erasure in each channel's direction, never scalar erasure."""
    if not (is_abstract_iterator(source) and is_abstract_iterator(target)
            and source.generic_name == target.generic_name == "Generator"
            and is_return_type_compatible(target, source)):
        return False
    source_parts = actual.arguments if actual else (None, None, None)
    target_parts = expected.arguments if expected else (None, None, None)
    channels = (
        (source_parts[0], target_parts[0], target.generic_types["V"]),
        (target_parts[1], source_parts[1], source.generic_types["S"]),
        (source_parts[2], target_parts[2], target.generic_types["R"]),
    )
    return all(left == right or right is None and InferenceVisitor.permits_reference_erasure(left, receiver)
               for left, right, receiver in channels)


class NativeInferenceVisitor(IRInferenceVisitor):
    """LLVM analysis policy."""

    numeric_domains = frozenset({"portable", "wgsl", "native"})
    lower_exception_regions = True
    lower_generator_suspensions = True

    def __init__(self, func, scope=None):
        super().__init__(func, scope)
        self.lowering = NativeExpressionLowering(self)
        if scope is None:
            # Reset on an inference retry, but share across branch visitors.
            func.native_erased_methods = []
            func.native_attribute_queries = []
            func.native_generator_signature = None

    def subscript_method(self, target, name):
        method = super().subscript_method(target, name)
        method.class_lookup = True
        return method

    def visit_Name(self, node: ast.Name):
        if node.id == "NotImplemented":
            try:
                self.scope.search(node.id)
            except NameError:
                return ast.copy_location(
                    Constant(BUILTINS.search("NotImplementedType"), value=NotImplemented), node,
                )
        return super().visit_Name(node)

    def resolve_comparison_method(self, node, operator, left, right, left_type, right_type):
        if isinstance(operator, (ast.Eq, ast.NotEq)) and any(
                value_type is BUILTINS.search("NotImplementedType")
                for value_type in (left_type, right_type)):
            name = "__ne__" if isinstance(operator, ast.NotEq) else "__eq__"
            methods = (value_type.find_attrs(name) for value_type in (left_type, right_type))
            if not any(isinstance(method, Function)
                       and not method.cls.container.scope.is_builtins for method in methods):
                # The sentinel has identity equality, including unlike builtin
                # operands. Keep application overrides on normal dispatch.
                method = BUILTINS.search("object")._self.find(
                    "__dynamic_ne__" if isinstance(operator, ast.NotEq) else "__dynamic_eq__")
                return method, left, right, False
        resolved = super().resolve_comparison_method(node, operator, left, right, left_type, right_type)
        if isinstance(operator, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)) and any(
                member is BUILTINS.search("NotImplementedType")
                for member in get_type_members(resolved[0].return_type)):
            # The dunder's sentinel result is not the operator's result: keep
            # both source operands for bilateral runtime negotiation.
            name = ("__dynamic_ne__" if isinstance(operator, ast.NotEq) else
                    "__dynamic_eq__" if isinstance(operator, ast.Eq) else self.COMPARE_OPS[type(operator)][0])
            method = BUILTINS.search("object")._self.find(name)
            return method, left, right, False
        return resolved

    def resolve_implicit_attribute(self, node, value):
        if node.attr in {
                "__setitem__", "__delitem__", "__setslice__", "__delslice__"}:
            receiver = analyzed_value_type(value)
            if (not isinstance(receiver, Class) or isinstance(receiver, TypedDictClass)
                    or receiver.container.scope.is_builtins):
                # Builtin storage uses its existing item/slice lowering, not
                # an application-class vtable or runtime protocol selector.
                node.class_lookup = False
            else:
                # Implicit item protocols cannot be supplied by instance fields
                # or an inherited method hidden by a different class declaration.
                method = declared_protocol_method(receiver, node.attr,
                    inspect.getattr_static(receiver.py_obj, node.attr, None))
                if not isinstance(method, Function) or method.is_property or method.is_classmethod:
                    self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              f"native item mutation requires a class-level instance or static {node.attr} method")
        return super().resolve_implicit_attribute(node, value)

    def visit_Attribute(self, node):
        result = super().visit_Attribute(node)
        if getattr(node, "native_typed_completion", False):
            result.native_typed_completion = True
        if (getattr(result.obj, "name", None) == "__init__"
                and getattr(getattr(result.obj, "cls", None), "py_obj", None) is models.BaseModel):
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "construct and validate Pydantic models in Python before calling native code")
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            from . import class_constants
            if class_constants.declaration(result.obj):
                self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native class constants are read-only, including instance shadowing")
            receiver = analyzed_value_type(result.value)
            if any(models.is_model(member.py_obj) for member in get_type_members(receiver)):
                self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native Pydantic model inputs are read-only field snapshots")
        return result

    def visit_IfExp(self, node):
        # Preserve branch expressions until late destination typing finishes;
        # native expression lowering emits them at their evaluation point.
        return InferenceVisitor.visit_IfExp(self, node)

    def prepare_conditional_values(self, body, orelse):
        dom_types.join_values(self, (body, orelse))

    def apply_literal_type(self, value, expected_type):
        if isinstance(value, ast.List) and not value.elts:
            views = [member for member in get_type_members(expected_type) if is_abstract_iterable(member)]
            if len(views) == 1 and contextual_collection_type(expected_type, "list") is None:
                # A fresh empty list has no item evidence. An Iterable
                # destination supplies its item type without changing the
                # concrete allocation into an abstract descriptor. Aliased or
                # nonempty sources must retain their independently inferred
                # storage and use the ordinary checked view conversion.
                expected_type = BUILTINS.search("list")(views[0].generic_types["V"])
        result = super().apply_literal_type(value, expected_type)
        if is_fromkeys_call(value):
            expected = contextual_collection_type(expected_type, "dict")
            actual = analyzed_value_type(value)
            empty = empty_fromkeys_keys(value)
            if (expected is not None
                    and not isinstance(expected, TypedDictClass)
                    and (empty is not None or is_return_type_compatible(expected.generic_types["K"], actual.generic_types["K"]))
                    and is_return_type_compatible(expected.generic_types["V"], actual.generic_types["V"])):
                # fromkeys allocates a new mapping, unlike a returned/aliased
                # dict. Choose its slots before allocation; input keys and the
                # shared default still need ordinary checked value conversions.
                if isinstance(empty, ast.List):
                    self.apply_literal_type(empty, BUILTINS.search("list")(expected.generic_types["K"]))
                elif isinstance(empty, ast.Dict):
                    self.apply_literal_type(empty, BUILTINS.search("dict")(
                        expected.generic_types["K"], BUILTINS.search("object")))
                representation = analyzed_representation(value)
                parts = representation.arguments if representation else (None, None)
                parts = tuple(merged_representation(expected.generic_types[name],
                    ((actual.generic_types[name], part),)) for name, part in zip(("K", "V"), parts, strict=True))
                value.obj = value.value_obj = expected
                set_analyzed_representation(value, compound_representation(arguments=parts))
                return expected
        return dom_types.apply_fresh_type(self, value, expected_type) or result

    def visit_Lambda(self, node):
        if self.lowering.has_suspension(node.body):
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "native generator lambdas require an explicit generator function")
        return super().visit_Lambda(node)

    def visit_contextual_lambda(self, node, parameter_types, parameter_representations=None):
        result = super().visit_contextual_lambda(node, parameter_types, parameter_representations)
        from . import tagged

        if (result.obj.return_representation is not None
                or getattr(nullable.member(result.return_type) or result.return_type, "generic_name", None) != "int"):
            return result
        body = result.body
        functions = {target for part in ast.walk(body) if isinstance(part, ast.Call)
                     for target in (getattr(part.func, "union_functions", ()) or (analyzed_value_object(part.func),))
                     if isinstance(target, Function) and should_analyze_target_body(target)
                     and not (target.cls or target).container.scope.is_builtins}
        # Builtin overload implementations are declarations, not emitted
        # object-returning bodies. Their fallback signature must not invent a
        # possible bool result for a specialized integer call such as min(range).
        if tagged.narrowed_integer(body, functions=functions, scope=result.scope, open_dispatch=True):
            # A lambda has an inferred result, not an authored integer-only
            # return contract. Preserve bool from overload/isinstance integer
            # views through its descriptor, including synthesized operator
            # callbacks. Changing the annotation must never silently cast it.
            result.return_type = UnionType(types=(*get_type_members(result.return_type), BUILTINS.search("bool")))
            result.obj = CallableClass(result.obj.parameter_types, result.return_type,
                                       BUILTINS.search("callable"), result.obj.parameter_representations)
        return result

    def visit_List(self, node):
        value = super().visit_List(node)
        if not node.elts:
            self.apply_literal_type(value, self.contextual_types.get(node))
        if node not in self.contextual_types:
            dom_types.infer_literal(self, value)
        allocation = getattr(node, "native_unpack_allocation", None)
        if allocation is not None:
            if value.obj is BUILTINS.search("list"):
                value.obj = BUILTINS.search("list")(BUILTINS.search("object"))
            value.native_unpack_allocation = allocation
        return value

    def visit_Tuple(self, node):
        if not any(isinstance(value, ast.Starred) for value in node.elts):
            return super().visit_Tuple(node)
        context = contextual_collection_type(self.contextual_types.get(node), "tuple")
        contextual_items = tuple(context.generic_types.values()) if context is not None else ()
        elements, items = [], []
        variadic = False
        for item in node.elts:
            if isinstance(item, ast.Starred):
                value = self.visit(item.value)
                source = analyzed_value_type(value)
                fixed = getattr(source, "generic_name", None) == "tuple" and not source.tuple_variadic
                # Fixed expansion reads fields, not one common iteration slot;
                # int8/int64 fields retain independent types and representations.
                protocol = self.require_iterable(item.value, value, allow_representation_conflict=fixed)
                expanded = ast.copy_location(Starred(protocol.item_type, value=value), item)
                set_analyzed_representation(expanded, protocol.item_representation)
                expanded.runtime_methods = protocol.methods
                elements.append(expanded)
                if fixed:
                    fields = tuple(source.generic_types.values())
                    representation = analyzed_representation(value)
                    representations = representation.arguments if representation else (None,) * len(fields)
                    items.extend(zip(fields, representations, strict=True))
                    continue
                variadic = True
                items.append((protocol.item_type, protocol.item_representation))
            else:
                expected = (
                    contextual_items[0] if context is not None and context.tuple_variadic else
                    contextual_items[len(items)] if not variadic and len(items) < len(contextual_items) else None
                )
                value = self.visit_contextual_expression(item, expected)
                elements.append(value)
                items.append((analyzed_value_type(value), analyzed_representation(value)))
        if variadic:
            item_type = UnionType(types=(value_type for value_type, _ in items)).type
            representation = self.merge_typed_representations(node, item_type, items, "Tuple items")
            items = [(item_type, representation)]
        tuple_type = BUILTINS.search("tuple")(*(value_type for value_type, _ in items), tuple_variadic=variadic)
        result = Tuple(tuple_type, elts=elements)
        set_analyzed_representation(result, tuple_representation(tuple(representation for _, representation in items)))
        return result

    def normalize_parameter_value(self, source, argument, expected, expected_type, *, representation_aware):
        representation = analyzed_representation(argument)
        if (expected is None and nullable.is_object(expected_type)
                and (representation_aware or not (representation and representation.direct_numeric_formats))):
            # Reference boxes retain their declared layout. Scalar boxes do
            # not carry an arithmetic domain: keep the shared diagnostic for
            # portable scalars, including scalar arms inside unions. Builtin
            # consumers such as isinstance inspect the existing representation
            # without storing it as object; actual boxing checks again below.
            return argument
        return super().normalize_parameter_value(source, argument, expected, expected_type,
                                                  representation_aware=representation_aware)

    def normalize_stored_value(self, source, value, representation, expected_type=None):
        if representation is None and nullable.is_object(expected_type):
            return self.normalize_representation(value, representation, expected_type)
        return super().normalize_stored_value(source, value, representation, expected_type)

    def normalize_representation(self, node, representation, expected_type=None):
        actual = analyzed_representation(node)
        source_type = analyzed_value_type(node)
        if generator_representation_compatible(source_type, expected_type, actual, representation):
            # Keep source metadata for the checked adapter. One represented
            # channel must not prevent another reference channel being erased.
            retain_iterable_conversion(node, expected_type)
            return node
        if is_abstract_iterable(expected_type):
            protocol = iterable_protocol(source_type, actual)
            expected_item = representation.item_representation if representation else None
            if (protocol is not None and not protocol.representation_conflict
                    and generator_representation_compatible(
                        protocol.item_type, expected_type.generic_types["V"],
                        protocol.item_representation, expected_item)):
                # Acquisition adapts each stored generator, not the collection
                # itself. In particular, a fresh literal must not combine its
                # source item type with the destination's channel witnesses.
                retain_iterable_conversion(node, expected_type)
                return node
        if (representation is not None and isinstance(expected_type, Class)
                and expected_type.container.scope.is_builtins and expected_type.generic_name == "Iterable"
                and isinstance(expected_type.generic_types["V"], UnionType)):
            return self.normalize_stored_iterable(node, node, representation.item_representation,
                                                  expected_type.generic_types["V"])
        if is_fromkeys_call(node):
            expected = contextual_collection_type(expected_type, "dict")
            parts = representation.arguments if representation else (None, None)
            protocol = self.require_iterable(node.args[0], node.args[0])
            empty = empty_fromkeys_keys(node)
            if (expected is not None and not isinstance(expected, TypedDictClass)
                    and same_analyzer_type(analyzed_value_type(node), expected)
                    and (empty is not None or not representations_conflict(((protocol.item_type, protocol.item_representation),
                        (expected.generic_types["K"], parts[0]))))):
                # New union arms may inherit a destination representation, but
                # existing keys cannot silently change their numeric domain.
                if isinstance(empty, (ast.List, ast.Dict)):
                    source_parts = (parts[0], None) if isinstance(empty, ast.Dict) else (parts[0],)
                    self.normalize_representation(empty, compound_representation(arguments=source_parts),
                                                  analyzed_value_type(empty))
                if len(node.args) > 1:
                    node.args[1] = self.normalize_stored_value(
                        node.args[1], node.args[1], parts[1], expected.generic_types["V"])
                set_analyzed_representation(node, representation)
        if nullable.is_object(expected_type) and actual and actual.direct_numeric_formats:
            self.fail(node, DiagnosticCode.INCOMPATIBLE_ASSIGNMENT,
                      "Native object storage cannot erase represented scalar arithmetic",
                      help="Convert explicitly with int() or float(), or keep the represented type.")
        result = super().normalize_representation(node, representation, expected_type)
        if (isinstance(result, ast.Yield) and expected_type is not None
                and is_return_type_compatible(expected_type, BUILTINS.search("NoneType"))
                and is_return_type_compatible(expected_type, analyzed_value_type(result))):
            # Final destination normalization runs after overload selection.
            # Decode/box at the resume boundary, inside its exception region,
            # without letting a broad provisional call signature widen the
            # receive expression and hide a more specific overload.
            source = analyzed_value_type(result)
            result.obj = expected_type
            destination = representation
            if destination is None and not nullable.is_object(expected_type):
                destination = merged_representation(expected_type, ((source, actual),))
            set_analyzed_representation(result, destination)
        return result

    def normalize_stored_iterable(self, source, value, item_representation, item_type=None):
        if isinstance(item_type, UnionType):
            protocol = self.require_iterable(source, value)
            if (is_return_type_compatible(item_type, protocol.item_type)
                    and not representations_conflict(((item_type, item_representation),
                        (protocol.item_type, protocol.item_representation)))):
                # Consumers copy items into fresh union slots or expose a
                # read-only view; never relabel the source collection's storage.
                return value
        return super().normalize_stored_iterable(source, value, item_representation, item_type)

    def normalize_stored_mapping(self, source, value, key_representation, value_representation,
                                 key_type=None, value_type=None):
        mapping = analyzed_value_type(value)
        representation = analyzed_representation(value)
        arguments = representation.arguments if representation is not None else (None, None)
        if (is_builtin_class(mapping, "dict") and isinstance(value_type, UnionType)
                and same_analyzer_type(mapping.generic_types["K"], key_type)
                and arguments[0] == key_representation
                and is_return_type_compatible(value_type, mapping.generic_types["V"])
                and not representations_conflict(((value_type, value_representation),
                    (mapping.generic_types["V"], arguments[1])))):
            # Copy values into fresh destination slots; never reinterpret the
            # source mapping or erase its represented numeric domains.
            return value
        return super().normalize_stored_mapping(source, value, key_representation,
                                                 value_representation, key_type, value_type)

    def analyze_return_value(self, node, declared_type, representation, numeric_format=None, array_format=None):
        returned = super().analyze_return_value(node, declared_type, representation, numeric_format, array_format)
        value = returned.value
        # An object annotation does not expose item arithmetic. An interface
        # view does, so returns need the same arithmetic-domain protection as
        # arguments and stored bindings.
        # Do not apply this to provisional builtin argument signatures: their
        # representation-aware consumers can retain the input's numeric domain.
        if value is None or nullable.is_object(declared_type):
            return returned
        pending = [(analyzed_value_type(value), analyzed_representation(value), declared_type, representation)]
        seen = set()
        while pending:
            source_type, source_representation, target_type, target_representation = pending.pop()
            pair = (source_type, source_representation, target_type, target_representation)
            if pair in seen or target_type is None or nullable.is_object(target_type):
                continue
            seen.add(pair)
            if isinstance(source_type, UnionType) or isinstance(target_type, UnionType):
                pending.extend((source, representation_for_member(source_type, source_representation, source),
                                target, representation_for_member(target_type, target_representation, target))
                               for source in get_type_members(source_type) for target in get_type_members(target_type))
                continue
            source, actual, target, expected = pair
            if is_abstract_iterator(target) or is_abstract_iterable(target):
                protocol = iterable_protocol(source, actual)
                if protocol is None:
                    continue
                if not is_return_type_compatible(target, source):
                    continue  # Ordinary typing diagnoses incompatible protocols.
                if expected is not None:
                    continue  # Shared normalization validates represented destinations.
                pairs = [(protocol.item_representation, next(iter(target.generic_types.values())))]
                if (is_abstract_iterator(source) and target.generic_name == source.generic_name == "Generator"
                        and actual is not None):
                    # Iterator/Iterable views do not expose send/completion.
                    # A Generator view does: sends flow in the reverse direction.
                    parts = actual.arguments
                    pairs += [(parts[1], target.generic_types["S"]), (parts[2], target.generic_types["R"])]
                if any(value is not None and not self.permits_reference_erasure(value, value_type)
                       for value, value_type in pairs):
                    self.fail(value, DiagnosticCode.INCOMPATIBLE_RETURN,
                              "Native iterator views cannot erase represented arithmetic",
                              help="Keep the represented annotation or explicitly convert transferred values.")
            elif (isinstance(source, Class) and isinstance(target, Class) and source.py_obj is target.py_obj
                  and source.generic_types and target.generic_types):
                # A returned container can hide the same view conversion. Walk
                # its type/representation pairs, not runtime values or bodies;
                # object members remain opaque and keep their original layout.
                slots = []
                for member, represented in ((source, actual), (target, expected)):
                    arguments = tuple(member.generic_types.values())
                    parts = represented.arguments if represented is not None else (None,) * len(arguments)
                    # StaticArray can encode its scalar item format in the
                    # direct array descriptor instead of generic arguments.
                    if represented is not None and represented.array is not None:
                        parts = (represented.item_representation,)
                    # Contextual variadic tuples have one item type but can
                    # retain a fixed literal's per-position representations.
                    if member.tuple_variadic:
                        arguments *= len(parts)
                    slots.append(tuple(zip(arguments, parts, strict=True)))
                source_slots, target_slots = slots
                if source.tuple_variadic and len(source_slots) == 1:
                    source_slots *= len(target_slots)
                if target.tuple_variadic and len(target_slots) == 1:
                    target_slots *= len(source_slots)
                if len(source_slots) == len(target_slots):
                    pending.extend((*left, *right) for left, right in zip(source_slots, target_slots, strict=True))
        return returned

    def runtime_contract_methods(self, func, function, args):
        methods = super().runtime_contract_methods(func, function, args)
        if function.py_func is native_builtins._format:
            from .representation import methods as representation_methods
            for semantic in get_type_members(analyzed_value_type(args[0])):
                # Explicit __format__ does not execute __str__/__repr__. Do
                # not pull unrelated bodies into the reachable program.
                selected = runtime_dunder_methods(semantic, "__format__")
                methods = (*methods, *(selected or representation_methods(semantic, False)))
        if (function.cls is not None and (not getattr(function.cls.py_obj, "__builtin__", False)
                                         or function.cls.py_obj is native_builtins._object)):
            if function.name in {"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"} and isinstance(func, ast.Attribute):
                def dependencies(value_type):
                    if function.name in {"__eq__", "__ne__"}:
                        return (inequality_methods if function.name == "__ne__" else equality_methods)(value_type)
                    inverse = {"__lt__": "__gt__", "__gt__": "__lt__", "__le__": "__ge__", "__ge__": "__le__"}
                    return runtime_dunder_methods(value_type, function.name, inverse[function.name])
                methods = (*methods, *dependencies(analyzed_value_type(func.value)),
                           *(method for argument in args for method in dependencies(analyzed_value_type(argument))))
        return tuple(dict.fromkeys(methods))

    def visit_FormattedValue(self, node):
        # Native formatting is a normal checked builtin call, so reachability,
        # evaluation order and exception lowering stay on the ordinary path.
        # Keep this policy out of JS/WGSL's deliberately smaller format subset.
        value = node.value
        conversion = {-1: None, ord("s"): "str", ord("r"): "repr", ord("a"): "ascii"}[node.conversion]
        if conversion is not None:
            value = ast.Call(func=Name(BUILTINS.search(conversion)), args=[value], keywords=[])
        spec = node.format_spec
        if spec is None:
            spec = ast.Constant(value="")
        elif all(isinstance(part, ast.Constant) for part in spec.values):
            spec = ast.Constant(value="".join(part.value for part in spec.values))
        call = ast.Call(func=Name(BUILTINS.search("format")), args=[value, spec], keywords=[])
        ast.fix_missing_locations(ast.copy_location(call, node))
        return ast.copy_location(ast.FormattedValue(value=self.visit(call), conversion=-1, format_spec=None), node)

    def visit_Call(self, node):
        # Keep static query provenance before library mappings erase HTML
        # interfaces. Do not evaluate arbitrary expressions or descriptors;
        # unresolved class queries get an explicit backend boundary instead.
        def query_class(expression):
            if isinstance(expression, ast.Name):
                code = getattr(self.func.py_func, "__code__", None)
                if code is not None and expression.id in (*code.co_varnames, *code.co_cellvars, *code.co_freevars):
                    return None  # A shadowed global is not the queried class.
                return getattr(self.func.py_func, "__globals__", {}).get(expression.id)
            if isinstance(expression, ast.Attribute):
                owner = query_class(expression.value)
                if isinstance(owner, types.ModuleType):
                    return vars(owner).get(expression.attr)
            return None

        original_query = query_class(node.args[1]) if len(node.args) == 2 else None
        original_cast = query_class(node.args[0]) if len(node.args) == 2 else None
        result = super().visit_Call(node)
        if isinstance(result, ast.Call) and hasattr(node, "runtime_callback_operands"):
            result.runtime_callback_operands = node.runtime_callback_operands
        if isinstance(result, StaticCast):
            result.native_dom_cast = original_cast
        if getattr(node, "borrowed_generator_control", False):
            from .delegation import completion_cursor, throw_cursor
            target = analyzed_value_object(result.func) if isinstance(result, ast.Call) else None
            if getattr(target, "py_func", None) not in {native_builtins._Generator.throw, throw_cursor, completion_cursor}:
                self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "borrowed exceptions may only be passed to generator throw() or internal completion capture")
        if isinstance(result, ast.Call):
            from . import comparisons, mapping_keys
            receiver = analyzed_value_object(result.func)
            if (isinstance(receiver, Instance) and isinstance(receiver.cls, Class)
                    and not isinstance(receiver.cls, CallableClass)
                    and not receiver.cls.container.scope.is_builtins):
                method = receiver.cls.find("__call__")
                if not isinstance(method, Function) or method.is_static or method.is_property:
                    self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "native callable objects require an ordinary instance __call__ method")
                # Signature analysis already bound __call__. Expose that same
                # method to ordinary IR consumers: virtual dispatch, defaults,
                # expansion, roots and result projection must share one path.
                result.func = ast.copy_location(Attribute(method, value=result.func,
                                                          attr="__call__", ctx=ast.Load()), result.func)
                result.func.class_lookup = True
            dom_types.refine_tag_result(result)
            target = getattr(result.func, "obj", None)
            if isinstance(result.func, ast.Attribute):
                # SSR defaults contain virtual calls even though their native
                # declarations have no body. Every union alternative matters:
                # its representative may be an application override instead.
                nested_dom = {
                    native_builtins._WebCustomElement.get_data: "getAttribute",
                    native_builtins._WebCustomElement.set_data: "setAttribute",
                    native_builtins._WebElement.replaceChildren: "append",
                }
                for method in result.func.union_functions or (target,):
                    if nested := nested_dom.get(getattr(method, "py_func", None)):
                        result.runtime_protocols = (*result.runtime_protocols,
                            (analyzed_value_type(result.func.value), (nested,)))
            if getattr(target, "py_func", None) is native_builtins._sum:
                self.refine_sum_result(result)
            if getattr(node, "native_arithmetic_builtin", False):
                from . import binary
                # divmod() lowers to a method call, but it is still negotiating
                # arithmetic, not an explicit authored dunder invocation.
                result.native_arithmetic_builtin = True
                binary.require_supported_result(analyzed_value_type(result), node)
                if isinstance(target, Function):
                    binary.require_supported_result(target.inferred_return_type, node)
            if getattr(target, "py_obj", None) in {native_builtins._bool, native_builtins._hasattr} and result.args:
                result.args[0] = self.guard_value(result.args[0])
            if (getattr(target, "py_obj", None) in {native_builtins._int, native_builtins._float}
                    and len(result.args) == 1 and not result.keywords):
                names = (("__float__", "__index__") if target.py_obj is native_builtins._float
                         else ("__int__", "__index__"))
                result.runtime_protocols = (*result.runtime_protocols,
                                           (analyzed_value_type(result.args[0]), names))
            if getattr(result.func, "class_lookup", False):
                result.runtime_protocols = (*result.runtime_protocols,
                    (analyzed_value_type(result.func.value), (result.func.attr,)))
            if isinstance(target, Class) and (models.is_model(target.py_obj)
                                             or target.py_obj is models.BaseModel):
                self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "construct and validate Pydantic models in Python before calling native code")
            if getattr(target, "py_func", None) is native_builtins._isinstance:
                result.native_dom_query = original_query
            contract = getattr(target, "runtime_dunders", None)
            if contract is not None and "__eq__" in contract[1]:
                values = ([result.func.value] if isinstance(result.func, ast.Attribute) else []) + result.args
                comparisons.retain_erased(result, *(analyzed_value_type(value) for value in values))
            if getattr(target, "py_func", None) is native_builtins._iter and len(result.args) == 2:
                comparisons.retain_erased(result, analyzed_value_type(result.args[1]))
            if contract is not None and contract[1] == ("__bool__", "__len__"):
                item_of = contract[0]
                if (isinstance(item_of, int) and item_of < len(result.args)
                        and (item_of == 0 or getattr(analyzed_value_type(result.args[0]), "generic_name", None) == "NoneType")):
                    member = iterable_item_type(analyzed_value_type(result.args[item_of]))
                    if member is not None:
                        # Implicit item truth must keep protocols introduced
                        # by reached subclasses, just like an explicit bool().
                        result.runtime_protocols = (*result.runtime_protocols,
                                                    (member, ("__bool__", "__len__")))
            if result.args and isinstance(target, Class) and is_subclass(target, BUILTINS.search("BaseException")):
                from .exception_values import retain_methods
                retain_methods(result, target, result.args[0])
            # A constructor needs callbacks even for empty typed mappings.
            # Forwarding calls (list.pop, user helpers, etc.) do not consume
            # returned keys; their later consumers retain any needed methods.
            if (isinstance(target, Class)
                    or getattr(target, "name", None) == "fromkeys"
                    and getattr(getattr(target, "cls", None), "generic_name", None) == "dict"):
                mapping_keys.retain(result, analyzed_value_type(result))
            mapping_keys.retain_receiver(result)
            from . import mapping_views
            mapping_views.retain(result)
            if getattr(target, "py_func", None) in {native_builtins._bin, native_builtins._oct, native_builtins._hex,
                                                    native_builtins._chr, native_builtins._len}:
                protocol = "__len__" if target.py_func is native_builtins._len else "__index__"
                result.runtime_protocols = ((analyzed_value_type(result.args[0]), (protocol,)),)
            decoration = get_native_decoration(getattr(target, "py_func", None))
            if decoration is not None and decoration.operation == "json.dumps":
                from .json_ops import retain_sort_callbacks
                retain_sort_callbacks(result)
            if decoration is not None and decoration.operation == "operator.index" and result.args:
                result.runtime_protocols = (*getattr(result, "runtime_protocols", ()),
                                           (analyzed_value_type(result.args[0]), ("__index__",)))
            if (getattr(getattr(target, "cls", None), "py_obj", None) in {native_builtins._str, native_builtins._bytes}
                    and target.name in {"find", "rfind", "index", "rindex", "count", "startswith", "endswith"}):
                # Bounds accept Python's integer-index protocol, including
                # overrides introduced only by reached subclasses.
                result.runtime_protocols = (*getattr(result, "runtime_protocols", ()),
                    *((analyzed_value_type(value), ("__index__",)) for value in result.args[1:]))
            if getattr(target, "py_obj", None) is native_builtins._bytes and result.args:
                result.runtime_protocols = (*getattr(result, "runtime_protocols", ()),
                    (analyzed_value_type(result.args[0]), ("__bytes__", "__index__", "__iter__")))
            if getattr(target, "py_obj", None) is native_builtins._range:
                result.runtime_protocols = (*getattr(result, "runtime_protocols", ()),
                    *((analyzed_value_type(value), ("__index__",)) for value in result.args))
            if getattr(target, "py_func", None) is native_builtins._enumerate:
                starts = [*result.args[1:], *(kw.value for kw in result.keywords if kw.arg == "start")]
                result.runtime_protocols = (*getattr(result, "runtime_protocols", ()),
                    *((analyzed_value_type(value), ("__index__",)) for value in starts))
            if getattr(target, "py_func", None) is native_builtins._iter and len(result.args) == 1:
                from pyjs.analysis.iterable_protocol import retain_iterator_acquisition
                retain_iterator_acquisition(result, analyzed_value_type(result.args[0]), analyzed_value_type(result))
            if (getattr(target, "py_func", None) in {native_builtins._repr, native_builtins._ascii,
                                                    native_builtins._print, native_builtins._format}
                    or getattr(target, "py_obj", None) is native_builtins._str
                    or getattr(target, "name", None) in {"__str__", "__repr__"}):
                values = ([result.func.value] if isinstance(result.func, ast.Attribute) else result.args)
                if getattr(target, "py_func", None) is not native_builtins._format:
                    from .representation import protocols
                    representation = (getattr(target, "name", None) != "__str__"
                                      and getattr(target, "py_func", None) is not native_builtins._print
                                      and getattr(target, "py_obj", None) is not native_builtins._str)
                    # Keep nested receiver types, not just inherited method
                    # objects that would make object.__str__ globally virtual.
                    formatting = tuple(protocol for value in values
                                       for protocol in protocols(analyzed_value_type(value), representation))
                    for receiver, _ in formatting:
                        self.require_non_model_operation(node, receiver)
                    result.runtime_protocols = (*result.runtime_protocols, *formatting)
                if any(nullable.contains(analyzed_value_type(value), "object") for value in values):
                    result.runtime_protocols = (*getattr(result, "runtime_protocols", ()),
                                                (BUILTINS.search("object"), ("__str__",)),
                                                (BUILTINS.search("object"), ("__repr__",)))
                    if getattr(target, "py_func", None) is native_builtins._format:
                        result.runtime_protocols += ((BUILTINS.search("object"), ("__format__",)),)
        if (isinstance(result, ast.Call) and result.args
                and getattr(getattr(result.func, "obj", None), "py_func", None) is native_builtins._hash):
            from .hashing import protocols
            result.runtime_protocols = protocols(analyzed_value_type(result.args[0]))
            for receiver, _ in result.runtime_protocols:
                self.require_non_model_operation(node, receiver)
        if (isinstance(result, ast.Call) and isinstance(result.func, ast.Attribute)
                and getattr(result.func.obj, "py_func", None) is native_builtins._object.__hash__):
            from .hashing import protocols
            result.runtime_protocols = protocols(analyzed_value_type(result.func.value))
            for receiver, _ in result.runtime_protocols:
                self.require_non_model_operation(node, receiver)
        if (isinstance(result, ast.Call) and result.args
                and getattr(getattr(result.func, "obj", None), "py_obj", None) is native_builtins._bool):
            semantic = analyzed_value_type(result.args[0])
            self.require_non_model_operation(node, semantic)
            result.runtime_protocols = ((semantic, ("__bool__", "__len__")),)
            result.runtime_methods = ()
        if is_fromkeys_call(result):
            result.runtime_member_callbacks = True
            if expands_arguments(result):
                self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native dict.fromkeys does not support expanded arguments")
            protocol = self.require_iterable(result.args[0], result.args[0])
            semantic = analyzed_value_type(result)
            default_type = analyzed_value_type(result.args[1]) if len(result.args) > 1 else BUILTINS.search("NoneType")
            set_analyzed_representation(result, compound_representation(arguments=(
                merged_representation(semantic.generic_types["K"], ((protocol.item_type, protocol.item_representation),)),
                merged_representation(semantic.generic_types["V"], ((default_type,
                    analyzed_representation(result.args[1]) if len(result.args) > 1 else None),)),
            )))
        self.apply_literal_type(result, self.contextual_types.get(node))
        if is_fromkeys_call(result) and node in self.contextual_representations:
            # A conditional joins its branches before the eventual assignment
            # normalization. Fresh absent key arms must inherit context here,
            # not appear to conflict with the populated sibling branch.
            result = self.normalize_representation(result, self.contextual_representations[node],
                                                   self.contextual_types.get(node))
        if getattr(node, "native_repeat_inplace", False):
            from . import binary
            result.native_repeat_inplace = True
            result.operator = ast.Mult()
            binary.retain(result, ("__mul__", "__rmul__"))
        from . import indexing, slices, text_counts
        return text_counts.retain(indexing.retain_sequence(slices.retain(result)))

    def refine_sum_result(self, result):
        """An empty reduction returns its start, before any numeric promotion."""
        if not result.args or analyzed_numeric_format(result) is not None:
            return  # Portable sums have their own checked representation contract.
        source = result.args[0]
        if iterable_is_provably_nonempty(getattr(source, "source", source), source):
            return
        start = result.args[1] if len(result.args) > 1 else next(
            (keyword.value for keyword in result.keywords if keyword.arg == "start"), None)
        start_type = analyzed_value_type(start) if start is not None else BUILTINS.search("int")
        accumulated = analyzed_value_type(result)
        if not (any(is_builtin_class(start_type, name) for name in ("bool", "int", "float"))
                and any(is_builtin_class(accumulated, name) for name in ("int", "float"))):
            return
        if same_analyzer_type(start_type, accumulated):
            return
        result.native_sum_accumulator = accumulated
        result_type = UnionType(types=(start_type, accumulated)).type
        result.obj = result_type
        result.value_obj = result_type("__sum_result__", self.scope, self.func)

    def adapt_conversion_callback(self, node, target):
        """Use ordinary typed lambdas for statically known builtin conversions."""
        if not node.args:
            return
        # Signature selection supplies the selected overload, not the exported
        # implementation function. Check builtin ownership, never spelling alone.
        decoration = get_native_decoration(getattr(target, "py_func", None))
        predicate = decoration is not None and decoration.operation in {
            "itertools.filterfalse", "itertools.takewhile", "itertools.dropwhile",
        }
        builtin = (target is not None and isinstance(target.container, Module)
                   and target.container.scope.is_builtins)
        predicate = predicate or builtin and target.name == "filter"
        if not (predicate or builtin and target.name == "map"):
            return
        source = node.args[0]
        if not isinstance(source, (ast.Name, ast.Attribute)):
            return
        callback = self.visit(source)
        if (isinstance(callback, ast.Attribute)
                and not isinstance(analyzed_value_object(callback.value), (Module, ModuleAlias))):
            return  # Replacing a callback must not drop receiver evaluation.
        conversion = analyzed_value_object(callback)
        decoration = get_native_decoration(getattr(conversion, "py_func", None))
        index_conversion = decoration is not None and decoration.operation == "operator.index"
        if (conversion not in {BUILTINS.search(name) for name in ("str", "int", "float", "bool")}
                and not index_conversion):
            return
        if predicate and conversion is not BUILTINS.search("bool") and not index_conversion:
            return
        if len(node.args) != 2:
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "Native builtin conversion callbacks require exactly one iterable")
        # Contextual lambda inference waits for the iterable's item type and
        # representation. Its normal call then supplies conversions, protocol
        # reachability, rooting and exception behavior; no second runtime ABI.
        argument = "__pyjs_conversion_value"
        body = ast.Call(func=Name(conversion), args=[ast.Name(id=argument, ctx=ast.Load())], keywords=[])
        if predicate and index_conversion:
            # The modeled predicate returns bool. Preserve index()'s
            # integer result for map, and make its truth conversion explicit here.
            body = ast.Call(func=Name(BUILTINS.search("bool")), args=[body], keywords=[])
        node.args[0] = ast.fix_missing_locations(ast.copy_location(ast.Lambda(
            args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=argument)],
                               vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
            body=body,
        ), source))

    def visit_Subscript(self, node):
        from . import indexing, slices
        from .mapping_keys import retain_receiver
        # Operators synthesize calls without visit_Call; retain their mapping
        # contracts after lowering, without revisiting/evaluating operands.
        return indexing.retain_sequence(slices.retain(retain_receiver(super().visit_Subscript(node))))

    def visit_BinOp(self, node):
        from . import binary, indexing
        from . import inplace as inplace_ops
        from .mapping_keys import retain_receiver
        inplace = None
        if getattr(node, "augmented", False):
            if type(node.op) not in self.BIN_OPS:
                self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          f"LLVM augmented assignment does not support {type(node.op).__name__}")
            left = self.visit(node.left)
            if analyzed_array_format(left) is not None:
                # Operator wrappers enter this expression path without a
                # source AugAssign. Preserve its fixed-size-array boundary
                # rather than silently treating iadd as fresh concatenation.
                self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "Static arrays do not support whole-array augmented assignment",
                          help="Assign individual items or create another static array.")
            collection_method = self.collection_inplace_method(left, node.op)
            if collection_method is not None:
                invocation = ast.copy_location(ast.Call(
                    func=ast.Attribute(value=node.left, attr=collection_method, ctx=ast.Load()),
                    args=[node.right], keywords=[]), node)
                if collection_method == "__imul__":
                    # Syntax tries a numeric reflected method before list's
                    # in-place repetition. Explicit __imul__ calls do not.
                    invocation.native_repeat_inplace = True
                return self.visit_Call(ast.fix_missing_locations(invocation))
            left_type = analyzed_value_type(left)
            members = get_type_members(left_type)
            if any(not member.container.scope.is_builtins for member in members):
                inplace = "__i" + self.BIN_OPS[type(node.op)][0][2:]
                methods = [inplace_ops.resolve(member, inplace, node) for member in members]
                if isinstance(left_type, UnionType) and any(
                        method is not None and method.name == inplace for method in methods):
                    self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "LLVM application augmented assignment requires a concrete receiver type",
                              help="Narrow the receiver before applying the in-place operator.")
                method = methods[0] if len(methods) == 1 else None
                if method is not None and method.name == inplace:
                    invocation = ast.copy_location(ast.Call(
                        func=ast.copy_location(ast.Attribute(value=node.left, attr=inplace, ctx=ast.Load()), node.left),
                        args=[node.right], keywords=[]), node)
                    result = self.visit_Call(invocation)
                else:
                    result = super().visit_BinOp(node)
                    if method is not None and (result.func.obj is not method or getattr(result, "reverse", False)):
                        self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                  "LLVM in-place alias must match the statically selected binary method")
                    if isinstance(left_type, UnionType) and any(
                            method is not None and (getattr(result, "reverse", False)
                            or member.find_attrs(result.func.attr) is not method)
                            for member, method in zip(members, methods, strict=True)):
                        self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                  "LLVM union in-place aliases must match their selected binary methods")
                result.inplace_method = inplace
                result.runtime_protocols = (*result.runtime_protocols, (left_type, (inplace,)))
        if inplace is None:
            result = super().visit_BinOp(node)
        binary.require_supported_result(analyzed_value_type(result), node)
        if isinstance(result, ast.Call) and isinstance(result.func.obj, Function):
            binary.require_supported_result(result.func.obj.inferred_return_type, node)
        binary.retain(result, self.BIN_OPS.get(type(node.op)))
        return indexing.retain_sequence(retain_receiver(result))

    def analyze_binary_operation(self, node, left, right):
        if isinstance(node.op, ast.Add) and all(
                is_builtin_class(analyzed_value_type(value), "tuple")
                for value in (left, right)):
            return self.concatenate_tuples(node, left, right)
        return super().analyze_binary_operation(node, left, right)

    def concatenate_tuples(self, node, left, right):
        """Reuse typed tuple expansion, capturing both operands before reading fields."""
        types = [analyzed_value_type(value) for value in (left, right)]
        if not all(is_builtin_class(value, "tuple") for value in types):
            self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                      "native tuple concatenation requires another tuple")
        visitor = self.child_visitor(LocalScope(self.scope))
        bindings = []
        for name, value, semantic in zip(("$tuple_left", "$tuple_right"), (left, right), types, strict=True):
            binding = semantic(name, visitor.scope, visitor.func)
            apply_representation(binding, analyzed_representation(value))
            visitor.scope.add(binding)
            bindings.append(ast.Name(id=name, ctx=ast.Load()))
        # Empty concatenation retains identity, but neither operand's effects
        # may disappear. Lexical lets also root the left across right-side GC.
        if not types[0].generic_types:
            expression = bindings[1]
        elif not types[1].generic_types:
            expression = bindings[0]
        elif any(value.tuple_variadic for value in types):
            expression = ast.Call(func=ast.Attribute(value=bindings[0], attr="__add__", ctx=ast.Load()),
                                  args=[bindings[1]], keywords=[])
        else:
            expression = ast.Tuple(elts=[ast.Starred(value=value, ctx=ast.Load()) for value in bindings],
                                   ctx=ast.Load())
        result = visitor.visit(ast.fix_missing_locations(ast.copy_location(expression, node)))
        representation = analyzed_representation(result)
        for value, binding in reversed(list(zip((left, right), bindings, strict=True))):
            result = EvaluateOnce(analyzed_value_object(result), value, result, binding.id, lineno=node.lineno)
            set_analyzed_representation(result, representation)
        return result

    def analyze_tuple_concat(self, call):
        if expands_arguments(call.node):
            self.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "native tuple.__add__ requires an explicit positional argument")
        left = call.receiver()
        # Keep the narrow signature for binary reflected dispatch, but infer a
        # fresh literal without its tuple[object, ...] contextual storage.
        self.validate_call_shape(call.node, call.function)
        right = self.visit(call.node.args[0])
        # Reuse operands only in this binding pass: revisiting nested calls
        # here is exponential, but mutating source operands leaks stale types
        # and EvaluateOnce bindings into flow retries and duplicated finally
        # paths. Copy the call/attribute shells and replace the argument list;
        # untouched source children remain available for later analysis passes.
        call.node = copy(call.node)
        call.node.func = copy(call.node.func)
        call.node.func.value = ast.copy_location(AnalyzedExpression(left), call.node.func.value)
        call.node.args = [ast.copy_location(AnalyzedExpression(right), call.node.args[0])]
        result = call.standard()
        call.replace_forwarded_argument(result, 0, right)
        types = [analyzed_value_type(value) for value in (left, right)]
        if not all(is_builtin_class(value, "tuple") for value in types):
            self.fail(call.node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                      "native tuple concatenation requires another tuple")
        if not any(value.tuple_variadic for value in types) or any(not value.generic_types for value in types):
            return self.concatenate_tuples(call.node, left, right)
        protocols = [self.require_iterable(call.node, value) for value in (left, right)]
        item = UnionType(types=tuple(protocol.item_type for protocol in protocols)).type
        representation = self.merge_typed_representations(
            call.node, item, [(protocol.item_type, protocol.item_representation) for protocol in protocols],
            "Tuple concatenation items")
        result_type = BUILTINS.search("tuple")(item, tuple_variadic=True)
        result.obj = result_type
        result.value_obj = result_type("__tuple_concat_result__", self.scope, self.func)
        set_analyzed_representation(result, tuple_representation((representation,)))
        return result

    def analyze_getattr(self, node, function, args):
        from .attribute_queries import analyze_getattr
        return analyze_getattr(self, node, args)

    def validate_query_class(self, source, target, operation):
        if not isinstance(target, (Class, GenericClass)):
            return  # Call binding diagnoses values that are not class objects.
        if isinstance(target, Class) and target.generic_types:
            self.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      f"native {operation} does not accept parameterized generic classes")
        name = target.name if isinstance(target, GenericClass) else target.generic_name
        if (target.container.scope.is_builtins and name not in {"NoneType", "NotImplementedType"} and not name.startswith("Web")
                and not isinstance(getattr(builtins, name, None), type)):
            # Mapped annotation interfaces omit host ABC registries/hooks.
            # Their model inheritance is not proof of a runtime class relation.
            self.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      f"native {operation} does not implement typing-interface class checks")
        kind = "instance" if operation == "isinstance" else "subclass"
        hook = f"__{kind}check__"
        if inspect.getattr_static(type(target.py_cls), hook) is not getattr(type, hook):
            self.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      f"native {operation} does not implement metaclass {kind} checks")

    def analyze_isinstance(self, call):
        self.validate_call_shape(call.node, call.function)
        if len(call.node.args) != 2 or expands_arguments(call.node):
            self.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "native type checks require two explicit positional arguments")
        for source in flatten_isinstance_targets(call.node.args[1]):
            if not isinstance(source, (ast.Name, ast.Attribute, ast.Subscript)):
                continue  # Normal argument validation supplies the diagnostic.
            target = analyzed_value_object(self.visit(source))
            self.validate_query_class(source, target, "isinstance")
        return call.isinstance(validate_numeric=False)

    def analyze_issubclass(self, call):
        self.validate_call_shape(call.node, call.function)
        if len(call.node.args) != 2 or expands_arguments(call.node):
            self.fail(call.node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "native type checks require two explicit positional arguments")

        def class_value(source):
            value = analyzed_value_object(self.visit(source))
            if (not isinstance(source, (ast.Name, ast.Attribute, ast.Subscript))
                    or not isinstance(value, (Class, GenericClass))):
                self.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native issubclass requires statically known classes")
            self.validate_query_class(source, value, "issubclass")
            if value.py_cls in {native_builtins._WebElement, native_builtins._WebFormControl,
                                native_builtins._WebCustomElement}:
                self.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native issubclass cannot recover mapped DOM class identities")
            return value

        actual = class_value(call.node.args[0])
        targets = [class_value(source) for source in flatten_isinstance_targets(call.node.args[1])]

        def matches(target):
            if target is BUILTINS.search("object"):
                return True
            if isinstance(actual, GenericClass) or isinstance(target, GenericClass):
                return target.py_cls in actual.py_cls.__mro__
            # Assignment's int-to-float promotion is not a class relationship.
            return is_isinstance_match(actual, target)

        return Constant(BUILTINS.search("bool"), value=any(map(matches, targets)))

    def analyze_comparison(self, node, left, operator, right, left_source, right_source):
        if isinstance(operator, (ast.Is, ast.IsNot)):
            if isinstance(right_source, ast.Constant) and right_source.value is None:
                left = self.guard_value(left)
            if isinstance(left_source, ast.Constant) and left_source.value is None:
                right = self.guard_value(right)
        from . import comparisons
        from .mapping_keys import retain_receiver
        types = analyzed_value_type(left), analyzed_value_type(right)
        if isinstance(operator, (ast.Eq, ast.NotEq)) and any(nullable.is_object(value) for value in types):
            if any(analyzed_representation(value) is not None for value in (left, right)):
                self.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                          "Native erased equality requires ordinary numeric representations",
                          help="Compare explicitly narrowed values or convert the numeric values first.")
            # Erased storage cannot choose a static scalar dunder. Preserve
            # source operand order and retain runtime application protocols.
            result = self.dynamic_union_equality(node, left, right, *types, operator)
            return comparisons.retain_erased(result, *types, inequality=isinstance(operator, ast.NotEq))
        applications = tuple(value for value in types if isinstance(value, Class)
                             and not value.container.scope.is_builtins)
        if (isinstance(operator, ast.NotEq) and applications
                and not any(isinstance(value, UnionType) for value in types)
                and all(inherits_object_comparison(value, "__ne__") for value in applications)):
            # Validate the inherited default against __eq__'s signature, but
            # do not lower it to `not base.__eq__`: a reached subclass may
            # introduce __ne__. Keep the original operands and retain only
            # their application families, not every class in the program.
            super().analyze_comparison(node, left, ast.Eq(), right, left_source, right_source)
            result = self.dynamic_union_equality(node, left, right, *types, operator)
            result.runtime_methods = ()
            result.runtime_protocols = tuple((value, (name,)) for value in applications
                                             for name in ("__eq__", "__ne__"))
            return comparisons.retain_erased(result, *types, inequality=True)
        # Each link is analyzed independently, including not-in's negated call.
        result = retain_receiver(super().analyze_comparison(node, left, operator, right, left_source, right_source))
        call = result.operand if isinstance(result, ast.UnaryOp) else result
        if isinstance(call, ast.Call):
            from . import mapping_views
            mapping_views.retain(call)
        if (isinstance(operator, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE))
                and isinstance(call, ast.Call) and call.func.obj.cls is BUILTINS.search("object")):
            # Replacing a declining dunder with dynamic negotiation must not
            # erase the actual bodies from the analyzed graph. Retain both
            # operand families through ordinary runtime-method reachability;
            # an unrelated direct dunder call must not be needed to emit them.
            if isinstance(operator, (ast.Eq, ast.NotEq)):
                methods = inequality_methods if isinstance(operator, ast.NotEq) else equality_methods
                required = methods(types[0]) + methods(types[1])
            else:
                forward, reflected = self.COMPARE_OPS[type(operator)]
                required = runtime_dunder_methods(types[0], forward) + runtime_dunder_methods(types[1], reflected)
            call.runtime_methods = tuple(dict.fromkeys((*call.runtime_methods, *required)))
        if isinstance(operator, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            comparisons.retain_erased(call, *types, inequality=isinstance(operator, ast.NotEq))
        return result

    def visit_Compare(self, node):
        from . import type_queries
        query = type_queries.operands(self, node)
        return type_queries.analyze(self, node, query) if query is not None else super().visit_Compare(node)

    def get_condition_narrowings(self, test, when_true):
        from . import type_queries
        query = type_queries.operands(self, test) if isinstance(test, ast.Compare) else None
        if query is not None:
            source, target, negate = query
            if when_true != negate and isinstance(source, (ast.Name, ast.Attribute)):
                expected = analyzed_value_object(target)
                if isinstance(expected, GenericClass):
                    # Keep known item/field layouts rather than replacing a
                    # concrete union arm with an unparameterized class token.
                    matching = [member for member in get_type_members(analyzed_value_type(self.visit(source)))
                                if getattr(member, "py_cls", None) is expected.py_cls]
                    return [(source, UnionType(types=matching).type)] if matching else []
                if isinstance(expected, Class):
                    return [(source, expected)]
            # A failed exact check cannot exclude a base-typed arm: it may
            # still contain subclasses (notably bool in an int arm).
            return []
        return super().get_condition_narrowings(test, when_true)

    def narrow_for_condition(self, test, when_true):
        from . import type_queries
        narrowed = super().narrow_for_condition(test, when_true)
        for name in type_queries.integer_proofs(self, test, when_true):
            value = narrowed.scope.names.get(name)
            if value is not None and value.cls is BUILTINS.search("int"):
                # This belongs to the new flow binding, not its storage. A
                # reassignment/closure capture must not inherit the proof.
                value.native_exact_integer = True
        return narrowed

    def without_written_exact_proofs(self, statements):
        visitor = self
        # Exact identity is stronger than semantic type: even an inferred int
        # declaration can carry a bool. Do not filter on type/layout changes.
        for name, binding in self.written_bindings(statements).items():
            if not getattr(binding, "native_exact_integer", False):
                continue
            if visitor is self:
                visitor = self.child_visitor(LocalScope(self.scope))
            # int still includes bool. Keep that type/layout narrowing and its
            # storage origin, but not the stronger observation of exact int.
            # Shared write analysis independently widens the type if needed.
            visitor.scope.add(binding.reassign(name, visitor.scope, self.func))
        return visitor

    def loop_entry(self, node):
        # The for iterable runs once; the target and body can repeat. A loop's
        # own else runs only after exhaustion, but a nested loop's else is still
        # part of the outer repeated body and must participate in invalidation.
        repeated = node.target if isinstance(node, ast.For) else node.test
        return self.without_written_exact_proofs([repeated, *node.body])

    def exception_entry(self, statements, analyzed_statements):
        entry = super().exception_entry(statements, analyzed_statements)
        return entry.without_written_exact_proofs(statements)

    def visit_Dict(self, node):
        from .mapping_keys import retain
        result = super().visit_Dict(node)
        if node not in self.contextual_types:
            dom_types.infer_literal(self, result)
        # An empty **{} contributes no typing evidence. Once sibling entries
        # establish storage, give only that fresh empty mapping the same
        # layout before lowering unpacking to an ordinary update operation.
        expected = contextual_collection_type(analyzed_value_type(result), "dict")
        if expected is not None and not isinstance(expected, TypedDictClass):
            for key, value in zip(result.keys, result.values, strict=True):
                if key is None and isinstance(value, ast.Dict) and not value.keys:
                    self.apply_literal_type(value, expected)
                    set_analyzed_representation(value, analyzed_representation(result))
        retain(result, analyzed_value_type(result))
        return result

    def visit_Set(self, node):
        from .mapping_keys import retain
        result = super().visit_Set(node)
        retain(result, analyzed_value_type(result))
        return result

    def guard_value(self, value, *, preserve_local=False):
        # A fresh guard observes storage, not an earlier flow proof.
        # A deferred closure can run after a capture becomes None OR another
        # union/nominal subtype. Unguarded payload reads still check narrowing.
        binding = analyzed_value_object(value)
        if isinstance(value, (ast.Name, ast.Attribute)) and isinstance(binding, Instance):
            if preserve_local:
                # A selected and/or operand carries a result type, not just a
                # Boolean test. Retain proofs established in this execution;
                # only enclosing creation-time proofs can be stale captures.
                if self.deferred_parent is None:
                    return value
                scope = self.scope
                while scope is not self.deferred_parent:
                    if scope is binding.scope:
                        return value
                    scope = scope.parent
            declaration = binding.storage_declaration
            if declaration is not binding:
                guarded = type(value)(declaration, **{name: getattr(value, name) for name in value._fields})
                vars(guarded).update(vars(value))
                guarded.obj = declaration
                value = guarded
                set_analyzed_representation(value, analyzed_representation(declaration))
        return value

    def require_non_model_operation(self, node, semantic):
        if any(models.is_model(member.py_obj) for member in get_type_members(semantic)):
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "native Pydantic inputs support field reads, not model operations")

    def truth_test(self, node, test):
        from .iterable_views import is_view
        test = self.guard_value(test)
        self.require_non_model_operation(node, analyzed_value_type(test))
        if (is_view(analyzed_value_type(test)) or nullable.is_object(analyzed_value_type(test))
                or any(not member.container.scope.is_builtins for member in get_type_members(analyzed_value_type(test)))):
            # Static method selection cannot model a subclass introducing
            # __bool__ ahead of an inherited __len__. Retain both protocols on
            # reached classes and let native bool select the runtime method.
            semantic = analyzed_value_type(test)
            return self.call_node(node, BUILTINS.search("bool"),
                                  func=Name(BUILTINS.search("bool")), args=[test], keywords=[],
                                  runtime_protocols=((semantic, ("__bool__", "__len__")),))
        return super().truth_test(node, test)

    def visit_ListComp(self, node):
        result = super().visit_ListComp(node)
        self.apply_literal_type(result, self.contextual_types.get(node))
        return result

    def visit_SetComp(self, node):
        from .comprehensions import lower
        return lower(self, super().visit_SetComp(node), node)

    def visit_DictComp(self, node):
        from .comprehensions import lower
        return lower(self, super().visit_DictComp(node), node)

    def visit_GeneratorExp(self, node):
        result = super().visit_GeneratorExp(node)
        representation = analyzed_representation(result)
        none = BUILTINS.search("NoneType")
        result.obj = BUILTINS.search("Generator")(result.obj.generic_types["V"], none, none)
        set_analyzed_representation(result, compound_representation(arguments=(
            representation.arguments[0] if representation and representation.arguments else None,
            None, None,
        )))
        return result

    def visit_Return(self, node):
        if not self.func.is_generator:
            return super().visit_Return(node)
        declared = self.func.declared_return_type
        result = declared.generic_types["R"] if getattr(declared, "generic_name", None) == "Generator" else None
        parts = self.func.return_representation
        representation = parts.arguments[2] if parts and len(parts.arguments) > 2 else None
        returned = self.analyze_return_value(
            node, result, representation,
            representation.numeric if representation else None,
            representation.array if representation else None,
        )
        if returned.value is not None:
            from .exception_values import retain_methods
            # A completion is formatted lazily through StopIteration, even if
            # the source never reads its value property or formats it directly.
            retain_methods(returned, BUILTINS.search("StopIteration"), returned.value)
        return returned

    def inferred_generator_type(self):
        none = BUILTINS.search("NoneType")
        declared = self.func.declared_return_type
        sent = (declared.generic_types["S"]
                if getattr(declared, "generic_name", None) == "Generator" else self.func.send_type or none)
        if body_can_fall_through(self.func.body, exception_sensitive=False):
            self.func.inferred_return_type = merge_return_types(self.func.inferred_return_type, none)
            self.func.inferred_return_values.append((none, None))
        completed = self.func.inferred_return_type
        if completed is None and getattr(declared, "generic_name", None) == "Generator":
            # A raise-only or infinite body imposes no completion constraint,
            # just as an ordinary function with no normal return accepts its
            # declared result. Bare return/fallthrough already contributed None.
            completed = declared.generic_types["R"]
        return BUILTINS.search("Generator")(
            self.func.yield_type or none, sent, completed or none,
        )

    def inferred_generator_representation(self):
        return compound_representation(arguments=(
            self.func.yield_representation, self.func.send_representation,
            self.inferred_return_representation(self.func.inferred_return_type or BUILTINS.search("NoneType")),
        ))

    def normalize_collection_call(self, node, func, args, keywords):
        if isinstance(func, ast.Attribute) and (func.attr == "close" or func.attr in {"send", "throw"} and args):
            receiver = analyzed_value_type(func.value)
            if (isinstance(receiver, Class) and receiver.container.scope.is_builtins
                    and receiver.generic_name == "Generator"):
                representation = analyzed_representation(func.value)
                parts = representation.arguments if representation else (None, None, None)
                if func.attr == "close":
                    returned, none = receiver.generic_types["R"], BUILTINS.search("NoneType")
                    optional = merge_return_types(returned, none)
                    completion = merged_representation(optional, ((returned, parts[2]), (none, None)))
                    return args, keywords, True, completion
                if func.attr == "throw":
                    return args, keywords, True, parts[0]
                sent, none = receiver.generic_types["S"], BUILTINS.search("NoneType")
                optional = merge_return_types(sent, none)
                incoming = merged_representation(optional, ((sent, parts[1]), (none, None)))
                args[0] = self.normalize_stored_value(node.args[0], args[0], incoming, optional)
                return args, keywords, True, parts[0]
        return super().normalize_collection_call(node, func, args, keywords)

    def visit_Yield(self, node):
        result = super().visit_Yield(node)
        declared = self.func.declared_return_type
        context = self.contextual_types.get(node)
        representation = self.contextual_representations.get(node)
        sent = context
        if getattr(declared, "generic_name", None) == "Generator":
            sent = declared.generic_types["S"]
            parts = self.func.return_representation
            representation = parts.arguments[1] if parts and len(parts.arguments) > 1 else None
        elif context is None:
            representation = self.func.send_representation
        none = BUILTINS.search("NoneType")
        sent = sent or self.func.send_type or none
        if sent is not none:
            earlier = getattr(self.func, "native_untyped_receive", None)
            if earlier is not None:
                self.fail(earlier, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "generator input type must be known before its first receiving yield",
                          help="Declare Generator[YieldType, SendType, ReturnType] on the function "
                               "or annotate its first receiving assignment.")
            if self.func.send_type is not None and (
                    not same_analyzer_type(self.func.send_type, sent) or self.func.send_representation != representation):
                self.fail(node, DiagnosticCode.INCOMPATIBLE_RETURN,
                          "Generator receives incompatible value types or representations")
            self.func.send_type = sent
            self.func.send_representation = representation
        elif not getattr(node, "native_discarded_input", False) and self.func.native_untyped_receive is None:
            # Earlier expressions have already been analyzed using NoneType.
            # A later context must not silently change the frame's wire type.
            self.func.native_untyped_receive = node
        optional = merge_return_types(sent, none)
        optional_representation = merged_representation(optional, ((sent, representation), (none, None)))
        # next() always resumes with None, regardless of the explicit send
        # annotation. A nonnullable receiving local gets a checked boundary;
        # inferred locals include None instead of reading uninitialized bits.
        accepts_none = context is None or is_return_type_compatible(context, none)
        result.obj = optional if accepts_none else sent
        set_analyzed_representation(result, optional_representation if accepts_none else representation)
        return result

    def visit_Expr(self, node):
        if isinstance(node.value, ast.YieldFrom):
            from .delegation import lower_statement
            return lower_statement(self, node)
        if isinstance(node.value, ast.Yield):
            node.value.native_discarded_input = True
        return super().visit_Expr(node)

    def visit_YieldFrom(self, node):
        from .delegation import analyze
        return analyze(self, node)

    def emit_statement(self, statement):
        if isinstance(statement, list):
            for item in statement:
                self.emit_statement(item)
            return
        if isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign)) and isinstance(statement.value, ast.Yield):
            resume = self.ir.new_block("resume")
            yielded = statement.value
            value = self.lowering.visit(yielded.value)
            self.ir.terminate(ast.copy_location(Suspend(value, resume.name), statement))
            self.ir.enter(resume)
            statement.value = GeneratorInput(yielded, discard=isinstance(statement, ast.Expr))
            super().emit_statement(statement)
        else:
            super().emit_statement(statement)

    def expand_static_call_keywords(self, node, call_target=None):
        from .dom_types import is_opaque_type

        if getattr(call_target, "py_obj", None) is native_builtins._dict and node.keywords:
            # Constructor keyword tails use ordinary runtime binding, including
            # duplicate errors from literal ** packs. Keep the pack boundaries.
            node.native_dict_keywords = True
            return
        # Builtins retain dedicated lowering and static keyword expansion.
        # Inspect the resolved target rather than its spelling so application
        # code can shadow builtins. An application's inherited object.__init__
        # is not a builtin call target and still receives runtime binding.
        builtin = getattr(getattr(call_target, "py_obj", None), "__module__", None) == native_builtins.__name__
        # DOM methods now use ordinary calls.bind, including runtime keyword
        # packs. Keep static expansion only for dedicated builtin lowerings.
        cls = getattr(call_target, "cls", None)
        if is_opaque_type(cls) or getattr(cls, "py_obj", None) is native_builtins._WebTokenList:
            builtin = False
        if not expands_arguments(node) or builtin:
            super().expand_static_call_keywords(node, call_target)
        if builtin and node.keywords and getattr(call_target, "name", None) != "sort":
            from .collection_ops import CONTAINERS
            from .errors import LLVMUnsupported

            if getattr(getattr(call_target, "cls", None), "generic_name", None) in CONTAINERS:
                # Representation hooks index positional operands. Enforce the
                # native collection boundary before entering those hooks, but
                # keep ordinary unknown-keyword diagnostics from call binding.
                self.validate_call_shape(node, call_target)
                raise LLVMUnsupported("LLVM collection methods require positional arguments", node)

    def validate_call_shape(self, node, function):
        if getattr(function, "py_func", None) is native_builtins._divmod:
            # Preserve builtin identity before its analysis hook replaces it
            # with a dunder; shadowed names and explicit calls remain ordinary.
            node.native_arithmetic_builtin = True
        if not expands_arguments(node):
            super().validate_call_shape(node, function)

    def analyze_call_arguments(self, node, signature_function, callable_signature):
        from . import itertools, operator

        operator.adapt_callback(self, node, signature_function)
        self.adapt_conversion_callback(node, signature_function)
        if (getattr(signature_function, "py_func", None) is itertools.starmap
                and len(node.args) == 2 and not node.keywords and isinstance(node.args[0], ast.Lambda)):
            return itertools.starmap_arguments(self, node, signature_function)
        if getattr(node, "native_dict_keywords", False):
            if expands_arguments(node):
                args = [self.visit(argument) for argument in node.args]
                keywords = [ast.keyword(arg=keyword.arg, value=self.visit(keyword.value)) for keyword in node.keywords]
                result = args, keywords, {}, {}
            else:
                result = super().analyze_call_arguments(node, signature_function, callable_signature)
                args, keywords = result[:2]
            if args and isinstance(analyzed_value_type(args[0]), TypedDictClass):
                self.fail(args[0], DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native dict() construction from TypedDict is not implemented")
            for keyword in keywords:
                if keyword.arg is None:
                    mapping = analyzed_value_type(keyword.value)
                    if (not is_builtin_class(mapping, "dict")
                            or not is_builtin_class(mapping.generic_types["K"], "str")):
                        self.fail(keyword.value, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                  "native ** expansion requires a concrete string-keyed dict")
            return result
        if not expands_arguments(node):
            return super().analyze_call_arguments(node, signature_function, callable_signature)
        if signature_function is None or signature_function.type_parameters or signature_function.overloads:
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "native argument expansion requires a concrete, non-overloaded signature")
        # The destination of an expanded item is only known during binding.
        # Do not normalize it against its syntactic argument index. The native
        # binder validates every possible destination before emitting a store.
        return ([self.visit(argument) for argument in node.args],
                [ast.keyword(arg=keyword.arg, value=self.visit(keyword.value)) for keyword in node.keywords],
                {}, {})

    def validate_call_argument_types(self, node, function, args, keywords, type_bindings, *,
                                     skip_positional=0, representation_bindings=None):
        if expands_arguments(node):
            return ()
        return super().validate_call_argument_types(node, function, args, keywords, type_bindings,
                                                    skip_positional=skip_positional,
                                                    representation_bindings=representation_bindings)

    def normalize_function_signature_arguments(self, node, called_function, signature_function,
                                               args, keywords, type_bindings, representation_bindings):
        if expands_arguments(node):
            return args, keywords
        return super().normalize_function_signature_arguments(node, called_function, signature_function,
                                                             args, keywords, type_bindings, representation_bindings)

    def visit_Constant(self, node):
        if isinstance(node.value, bytes):
            return Constant(BUILTINS.search("bytes"), value=node.value)
        return super().visit_Constant(node)

    def make_exception_raise(self, value_type, message, *, source=None):
        from .exception_values import retain_methods
        result = super().make_exception_raise(value_type, message, source=source)
        if source is None:
            # Assertions have no constructor call to retain formatting methods.
            retain_methods(result, value_type, message)
        return result

    def validate_borrowed_exception_uses(self, node, details, messages, *, caught=False, type_tokens=()):
        # These bindings point into reusable stack snapshots. Reject aliases
        # before lowering can lose the provenance of a store or argument.
        for parent in ast.walk(node):
            if isinstance(parent, ast.GeneratorExp):
                # Only the outermost iterable is evaluated at construction.
                # The body, filters and later iterables can outlive the snapshot;
                # eager comprehensions and copied outer-iterable values cannot.
                deferred = [parent.elt, *parent.generators[0].ifs, *parent.generators[1:]]
                if any(isinstance(child, ast.Name) and child.id in details
                       for region in deferred for child in ast.walk(region)):
                    self.fail(parent, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "native exception details are borrowed and cannot be captured by generator expressions")
            if parent is not node and isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                if any(isinstance(child, ast.Name) and child.id in details for child in ast.walk(parent)):
                    self.fail(parent, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "native exception details are borrowed and cannot be captured by nested definitions")
            for child in ast.iter_child_nodes(parent):
                if not isinstance(child, ast.Name) or child.id not in details:
                    continue
                comparison = isinstance(parent, ast.Compare) and all(
                    isinstance(operation, (ast.Is, ast.IsNot)) for operation in parent.ops
                )
                if comparison and child.id in messages:
                    # Snapshot addresses cannot identify exception instances.
                    # The __exit__ class token is a distinct role, however;
                    # comparing it with the value also preserves the normal
                    # exit's None-is-None result without exposing an alias.
                    operands = [parent.left, *parent.comparators]
                    comparison = all(
                        (left is not child and right is not child)
                        or (isinstance(other := right if left is child else left, ast.Constant)
                            and other.value is None)
                        or isinstance(other, ast.Name) and other.id in type_tokens
                        for left, right in zip(operands[:-1], operands[1:], strict=True)
                    )
                    if not comparison:
                        self.fail(child, DiagnosticCode.UNSUPPORTED_SYNTAX,
                                  "native exception identity comparisons require None or the __exit__ type token"
                                  if type_tokens else "native exception identity comparisons require None")
                message = (child.id in messages and isinstance(parent, ast.Call)
                           and isinstance(parent.func, ast.Name) and parent.func.id == "str"
                           and len(parent.args) == 1 and parent.args[0] is child and not parent.keywords)
                reraise = caught and isinstance(parent, ast.Raise) and parent.exc is child
                payload = (caught and isinstance(parent, ast.Attribute) and parent.value is child
                           and parent.attr == "value" and isinstance(parent.ctx, ast.Load))
                thrown = (caught and isinstance(parent, ast.Call)
                          and isinstance(parent.func, ast.Attribute) and parent.func.attr == "throw"
                          and parent.args == [child] and not parent.keywords)
                thrown |= (caught and isinstance(parent, ast.Call)
                           and getattr(parent, "native_delegated_throw", False)
                           and len(parent.args) == 2 and parent.args[1] is child and not parent.keywords)
                completion = (caught and isinstance(parent, ast.Call)
                              and getattr(parent, "native_delegated_completion", False)
                              and parent.args == [child] and not parent.keywords)
                if thrown or completion:
                    # Syntax permits the use provisionally; visit_Call checks
                    # the resolved declaration before any borrowed value escapes.
                    parent.borrowed_generator_control = True
                if not isinstance(child.ctx, ast.Load) or not (comparison or message or reraise or thrown or payload or completion):
                    self.fail(child, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "native exception details are borrowed: use str(value), compare with None, or reraise a caught exception",
                              help="Caught exceptions also support generator.throw(error) and StopIteration.value. "
                                   "Do not retain or alias the exception record or pass it to other functions.")

    def visit_Try(self, node):
        for handler in node.handlers:
            if handler.name is not None:
                self.validate_borrowed_exception_uses(
                    handler, {handler.name}, {handler.name}, caught=True,
                )
        return super().visit_Try(node)

    def visit_FunctionDef(self, node):
        # Reachability retains constructors even for annotation-only classes.
        # The placeholder constructor has no side effects; all source-level
        # construction and initializer references are rejected above.
        if (self.func.cls is not None and self.func.cls.py_obj is models.BaseModel
                and node.name != "__init__"):
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "native Pydantic inputs support field reads, not model construction or operations")
        self.func.native_untyped_receive = None
        dataclass_ops.prepare_initializer(self.func, node)
        if node.name == "__exit__":
            parameters = node.args.posonlyargs + node.args.args
            if len(parameters) != 4 or node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
                self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                          "native __exit__ requires self and three exception-detail parameters")
            self.validate_borrowed_exception_uses(
                node, {parameter.arg for parameter in parameters[1:]}, {parameters[2].arg},
                type_tokens={parameters[1].arg},
            )
        result = super().visit_FunctionDef(node)
        if not self.pending_flow_widenings:
            # Alias provenance also determines runtime formatter dependencies;
            # establish it before reachability, not during LLVM emission.
            from .errors import LLVMUnsupported
            try:
                super_proxy.prepare(self.func)
            except LLVMUnsupported as error:
                error.add_function_context(self.func)
                raise
        if (self.func.is_generator and self.func.cls is None
                and is_builtin_class(self.func.return_type, "Iterator")
                and should_analyze_target_body(self.func)):
            # The declared Iterator interface hides control/completion types,
            # but a direct call to this compiled body always creates a frame.
            # Keep its concrete ABI fact without changing the public signature.
            none = BUILTINS.search("NoneType")
            self.func.native_generator_signature = (
                BUILTINS.search("Generator")(
                    self.func.return_type.generic_types["V"], self.func.send_type or none,
                    self.func.inferred_return_type or none),
                self.inferred_generator_representation(),
            )
        return result

    def resolve_unpacking_assignment(self, target_node, assignment_value):
        return unpacking.analyze(self, target_node, assignment_value)

    def visit_For(self, node):
        if not isinstance(node.target, (ast.Tuple, ast.List)):
            return super().visit_For(node)
        source = self.visit(node.iter)
        protocol = self.require_iterable(node.iter, source)
        target, body = node.target, node.body
        if is_builtin_class(protocol.item_type, "tuple") and protocol.item_type.tuple_variadic:
            # Reuse ordinary checked unpacking inside the loop, after next()
            # succeeds. A source expression and every yielded row run once;
            # failed arity checks precede assignment to the user's targets.
            name = self.ir.new_name("__unpack_row")
            target = ast.copy_location(ast.Name(id=name, ctx=ast.Store()), node.target)
            assignment = ast.copy_location(ast.Assign(
                targets=[node.target], value=ast.Name(id=name, ctx=ast.Load())), node.target)
            body = [assignment, *body]
        rewritten = ast.copy_location(ast.For(
            target=target, iter=AnalyzedExpression(source), body=body,
            orelse=node.orelse, type_comment=node.type_comment), node)
        return super().visit_For(ast.fix_missing_locations(rewritten))

    def bind_comprehension_target(self, visitor, target, value_type, representation=None):
        if (isinstance(target, (ast.Tuple, ast.List)) and is_builtin_class(value_type, "tuple")
                and value_type.tuple_variadic):
            # Binding needs one element type per target. The actual source
            # remains variadic; lowered loops perform the checked assignment.
            count = len(target.elts)
            value_type = BUILTINS.search("tuple")(*tuple(value_type.generic_types.values()) * count)
            representation = tuple_representation(representation.arguments * count) if representation else None
        return super().bind_comprehension_target(visitor, target, value_type, representation)

    def visit_call_function(self, node):
        # Synthesized f-string calls bypass local format/str/repr/ascii names.
        if isinstance(node.func, Name):
            return node.func
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"callable", "getattr", "hasattr"}:
            owner = analyzed_value_object(self.visit(node.func.value))
            if isinstance(owner, ModuleAlias) and owner.py_obj is builtins:
                if node.func.attr != "callable":
                    return ast.copy_location(Name(BUILTINS.search(node.func.attr)), node.func)
                from .type_queries import query_callable
                return ast.copy_location(Name(resolve_imported(query_callable, self.module)), node.func)
        function = super().visit_call_function(node)
        if analyzed_value_object(function) is BUILTINS.search("callable"):
            # The shared builtin named callable also models Callable annotations.
            # Only the declaration invokes the predicate. CallableClass values
            # (including immediate lambdas) share its py_obj, not its identity.
            from .type_queries import query_callable
            return ast.copy_location(Name(resolve_imported(query_callable, self.module)), function)
        target = analyzed_value_object(function)
        if (isinstance(function, ast.Attribute)
                and isinstance(target, Function) and target.is_method and not target.is_static
                and is_empty_inline(target.py_func, "native")
                and not (isinstance(function.value, (ast.Name, ast.Attribute))
                         and isinstance(analyzed_value_object(function.value), Class))):
            receiver = function.value
            lexical_super = (self.func.cls is not None
                             and isinstance(receiver, ast.Call)
                             and isinstance(receiver.func, ast.Name)
                             and receiver.func.id == "super"
                             and analyzed_value_object(receiver.func) is self.func.cls.super)
            if lexical_super:
                # Function.__init__/reset install this parent binding even if
                # Python shadows super. Do not treat that synthetic identity
                # as proof of builtin lookup, or erase an unsupported explicit
                # super argument before the emitter can reject it.
                source = getattr(self.func.py_func, "__func__", self.func.py_func)
                code = source.__code__
                resolved = source.__globals__.get("super", source.__builtins__.get("super"))
                if (receiver.args or receiver.keywords
                        or "super" in code.co_varnames + code.co_cellvars + code.co_freevars
                        or resolved is not builtins.super):
                    self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "LLVM erased method calls require unshadowed zero-argument super()",
                              help="Use a differently named helper or call a concrete method directly.")
                return function
            # Empty inlines disappear before ordinary call lowering. Retain
            # only receiver provenance, not emitted operands/callback dependencies.
            # Check after reachability: subclasses may be discovered later.
            for method in function.union_functions or (target,):
                self.func.native_erased_methods.append((method, function.value, node))
        if (isinstance(node.func, ast.Name) and node.func.id == "str"
                and analyzed_value_object(function) is not BUILTINS.search("str")):
            for argument in node.args:
                if not isinstance(argument, ast.Name):
                    continue
                try:
                    value = self.scope.lookup(argument.id)
                except NameError:
                    continue
                exit_value = (self.func.name == "__exit__" and len(self.func.params) == 3
                              and argument.id == self.func.params[1].arg)
                if exit_value or getattr(value, "native_exception_binding", False):
                    self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                              "borrowed exception messages require the builtin str(), not a shadowed callable")
        return function

    @staticmethod
    def collection_inplace_method(target, operator):
        if analyzed_array_format(target) is not None:
            return None
        name = getattr(analyzed_value_type(target), "generic_name", None)
        operations = ({ast.Add: "__iadd__", ast.Mult: "__imul__"} if name == "list" else
                      {ast.BitOr: "__ior__", ast.BitAnd: "__iand__", ast.BitXor: "__ixor__", ast.Sub: "__isub__"} if name == "set" else
                      {ast.BitOr: "__ior__"} if name == "dict" else {})
        return operations.get(type(operator))

    def visit_AugAssign(self, node):
        if (isinstance(node.target, ast.Attribute)
                and isinstance(node.target.value, ast.Call)
                and isinstance(node.target.value.func, ast.Name)
                and node.target.value.func.id == "super"
                and not node.target.value.args and not node.target.value.keywords):
            # Native super() is a static base-selection path, not a materialized
            # proxy. Capturing it as an ordinary temporary loses that distinction
            # for both the getter and the failing write. There are no receiver
            # arguments to evaluate; preserve getter -> RHS -> write ordering.
            read = ast.copy_location(ast.Attribute(
                value=node.target.value, attr=node.target.attr, ctx=ast.Load()), node.target)
            value = ast.copy_location(ast.BinOp(left=read, op=node.op, right=node.value), node)
            value.augmented = True
            return self.visit_Assign(ast.copy_location(ast.Assign(targets=[node.target], value=value), node))
        return super().visit_AugAssign(node)


class NativeLibraryMappings(NativeProtocolMappings):
    """Map host interfaces to their native builtin representations."""

    def stdlib_target(self, module, name):
        if module == "dataclasses" and name == "replace":
            return "pyjs.native.dataclasses", name
        if module in {"datetime", "pathlib", "uuid"}:
            replacement = "pyjs.native." + module
            # These libraries implement a subset of the host API. Unused
            # unsupported imports must remain lazy, not fail while scanning
            # a module that also contains reachable records or helpers.
            if name is None or hasattr(importlib.import_module(replacement), name):
                return replacement, name
            return None
        if module == "enum" and name in {None, "IntEnum", "StrEnum"}:
            return "pyjs.native.enum", name
        if module == "json" and name == "dumps":
            return "pyjs.native.json", name
        if module == "urllib.parse" and name in {None, "urlencode"}:
            return "pyjs.native.urllib", name
        if module == "functools" and name in {"reduce", "partial", "Placeholder"}:
            return "pyjs.native.functional", name
        if module == "math":
            return "pyjs.native.math", name
        if module == "itertools":
            return "pyjs.native.itertools", name
        return super().stdlib_target(module, name)

    def resolve(self, value: object) -> object:
        if value is builtins.callable:
            from .type_queries import query_callable
            return query_callable
        if value is builtins.type:
            return native_builtins._type
        if value is builtins.isinstance:
            return native_builtins._isinstance
        if value is builtins.issubclass:
            return native_builtins._issubclass
        if getattr(value, "__module__", None) == "_operator":
            # Resolve by identity without replacing the host namespace: public
            # aliases still work, and unused unsupported imports remain inert.
            from . import operator as operator_models
            model = getattr(operator_models, getattr(value, "__name__", ""), None)
            if model is not None and value is getattr(operator, value.__name__, None):
                return model
        if value is functools.reduce:
            # CPython exposes this C function under _functools, not functools.
            # Map the value without replacing the host module's namespace.
            from .functional import reduce
            return reduce
        if value is functools.Placeholder:
            from .functional import Placeholder
            return Placeholder
        if (isinstance(value, type) and value.__module__ == "pydantic.main"
                and value.__name__ == "BaseModel"):
            return models.BaseModel
        if value is DOMTokenList:
            return native_builtins._WebTokenList
        if value is typing.cast:
            return native_builtins._cast
        if value is CustomElement:
            return native_builtins._WebCustomElement
        if (value is HTMLInputElement or value is HTMLTextAreaElement
                or value is HTMLButtonElement or value is HTMLSelectElement):
            return native_builtins._WebFormControl
        if (
            isinstance(value, type)
            and value.__module__.startswith("pyjs.web.")
            and issubclass(value, WebElement)
            and not (value is not CustomElement and issubclass(value, CustomElement))
        ):
            # Keep the analysis model independent of ``pyjs.native``.  That
            # module intentionally imports the public web fallbacks, so using
            # its Element declaration here would create an import cycle while
            # the analyzer is building ``pyjs.web`` itself.
            return native_builtins._WebElement
        return super().resolve(value)

    def class_info(self, cls):
        if enum_ops.scalar_name(cls):
            enum_ops.validate(cls)
        return models.class_info(cls) or super().class_info(cls)


NATIVE_LIBRARY_MAPPINGS = NativeLibraryMappings()

NATIVE_ENVIRONMENT = create_analysis_environment(
    "native",
    native_builtins,
    inference_visitor=NativeInferenceVisitor,
    library_mappings=NATIVE_LIBRARY_MAPPINGS,
    analyze_all_definitions=False,
    defer_unselected_imports=True,
    definition_filter=native_builtins.include_definition,
    body_filter=native_builtins.should_analyze_body,
    analysis_finalizer=refine_lifetimes,
)
