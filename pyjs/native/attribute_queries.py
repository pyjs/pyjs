"""Literal attribute queries using ordinary typed reads and runtime class dispatch."""

import ast
import inspect
import types

from pyjs.analysis.analyzer import analyzed_value_object, analyzed_value_type
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.objects import (
    Class,
    DependencyError,
    EvaluateOnce,
    Function,
    LocalScope,
)
from pyjs.analysis.representation import apply_representation
from pyjs.analysis.type_relations import get_type_members
from pyjs.analysis.value_representation import (
    analyzed_representation,
    set_analyzed_representation,
)

from . import calls, collection_ops, nullable, object_values
from .errors import LLVMUnsupported

_MISSING = object()


def attribute(semantic, name):
    return semantic._self.find_attrs(name) or semantic.find_attrs(name)


def private_name(candidate, name):
    # Member tables retain source spellings, whereas literal queries never
    # undergo Python's private-name mangling. Until those tables distinguish
    # owners, neither raw private names nor a reached owner's mangled spelling
    # may be interpreted as an ordinary field/method lookup.
    if name.endswith("__"):
        return False
    return name.startswith("__") or any(
        owner and name.startswith(f"_{owner}__")
        for base in candidate.py_obj.__mro__
        if (owner := base.__name__.lstrip("_")))


def ordinary_lookup(candidate, name, node):
    if private_name(candidate, name):
        raise LLVMUnsupported("LLVM literal attribute queries do not support private name spellings", node)
    python_type = candidate.py_obj
    if python_type.__getattribute__ is not object.__getattribute__ or hasattr(python_type, "__getattr__"):
        raise LLVMUnsupported("LLVM literal attribute queries require ordinary attribute lookup", node)
    descriptor = inspect.getattr_static(python_type, name, _MISSING)
    if (hasattr(type(descriptor), "__get__") and not isinstance(
            descriptor, (types.FunctionType, staticmethod, classmethod, types.MemberDescriptorType, property))):
        raise LLVMUnsupported("LLVM literal attribute queries do not support custom descriptors", node)
    return descriptor


def require_initialized_field(candidate, name, node):
    if candidate._self.find_attrs(name) is None:
        return

    def plain_target(target, receiver):
        if isinstance(target, ast.Name):
            return target.id != receiver
        if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                and target.value.id == receiver):
            descriptor = inspect.getattr_static(candidate.py_obj, target.attr, _MISSING)
            return (candidate.py_obj.__setattr__ is object.__setattr__
                    and (not hasattr(type(descriptor), "__set__")
                         or isinstance(descriptor, types.MemberDescriptorType)))
        return False

    source = getattr(candidate.find_attrs("__init__"), "original_node", None)
    if source is not None:
        parameters = [*source.args.posonlyargs, *source.args.args]
        receiver = parameters[0].arg if parameters else None
        # The object layout has no per-field presence bits. Only fold a field
        # assigned in the constructor's straight prefix, before self can escape
        # to a query/helper. More elaborate initialization needs a real proof,
        # not a guess based on the presence of a declared field.
        for statement in source.body:
            targets = (statement.targets if isinstance(statement, ast.Assign)
                       else [statement.target] if isinstance(statement, ast.AnnAssign) else [])
            value = getattr(statement, "value", None)
            if (targets and value is not None
                    and not any(isinstance(part, ast.Name) and part.id == receiver for part in ast.walk(value))
                    and all(plain_target(target, receiver) for target in targets)):
                if any(isinstance(target, ast.Attribute) and target.attr == name for target in targets):
                    return
                continue
            if isinstance(statement, ast.Pass) or isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                continue
            break
    raise LLVMUnsupported("LLVM literal attribute queries require a field initialized before self can escape", node)


def validate_getattr(e):
    # A static miss must stay a miss on every reached subclass. Check after
    # reachability; otherwise a later constructor could invalidate the fold.
    for function in e.module.functions:
        try:
            for semantic, name, with_default, found, node in getattr(function, "native_attribute_queries", ()):
                if semantic not in e.module.classes:
                    raise LLVMUnsupported("LLVM getattr requires an application instance", node)
                for candidate in e.module.classes:
                    if not collection_ops.is_layout_subclass(candidate, semantic):
                        continue
                    descriptor = ordinary_lookup(candidate, name, node)
                    require_initialized_field(candidate, name, node)
                    if with_default and isinstance(descriptor, property):
                        raise LLVMUnsupported("LLVM getattr with a default cannot yet catch a property AttributeError", node)
                    if found is None and (attribute(candidate, name) is not None
                                          or descriptor is not _MISSING):
                        raise LLVMUnsupported("LLVM missing getattr defaults require the attribute to be absent on every reached subclass", node)
        except LLVMUnsupported as error:
            error.add_function_context(function)
            raise


def analyze_getattr(visitor, node, args):
    if (node.keywords or len(args) not in (2, 3)
            or any(isinstance(arg, ast.Starred) for arg in node.args)):
        visitor.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                     "native getattr() requires two or three positional arguments")
    if not isinstance(args[1], ast.Constant) or not isinstance(args[1].value, str):
        visitor.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                     "native getattr() requires a string literal attribute name")
    receiver, name = visitor.guard_value(args[0], preserve_local=True), args[1].value
    semantic = analyzed_value_type(receiver)
    if (not isinstance(semantic, Class) or object_values.instance_type(receiver) is None
            or nullable.is_object(semantic)):
        visitor.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native getattr() requires a concrete instance")
    if private_name(semantic, name):
        visitor.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native literal attribute queries do not support private name spellings")
    initializer = semantic.find_attrs("__init__")
    if initializer is not None and not initializer.is_analyzed:
        raise DependencyError(initializer)
    found = attribute(semantic, name)
    visitor.func.native_attribute_queries.append((semantic, name, len(args) == 3, found, node))
    if isinstance(found, Function) and found.is_property and len(args) == 3:
        visitor.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native getattr() with a default cannot yet catch a property AttributeError")
    if found is None and len(args) == 2:
        # Ordinary attribute analysis supplies the located missing-member error.
        return visitor.visit(ast.copy_location(ast.Attribute(
            value=node.args[0], attr=name, ctx=ast.Load()), node))

    local = visitor.child_visitor(LocalScope(visitor.scope))
    bindings = []
    values = [receiver, *args[2:]]
    for index, value in enumerate(values):
        binding = analyzed_value_type(value)(f"$getattr_{index}", local.scope, local.func)
        apply_representation(binding, analyzed_representation(value))
        local.scope.add(binding)
        bindings.append(ast.Name(id=binding.name, ctx=ast.Load()))
    body = (bindings[1] if found is None else ast.Attribute(
        value=bindings[0], attr=name, ctx=ast.Load()))
    result = local.visit(ast.fix_missing_locations(ast.copy_location(body, node)))
    representation = analyzed_representation(result)
    # Python evaluates the default before lookup, even when the member exists.
    # Lexical lets retain the receiver through default-side allocations/GC.
    for value, binding in reversed(list(zip(values, bindings, strict=True))):
        result = EvaluateOnce(analyzed_value_object(result), value, result, binding.id, lineno=node.lineno)
        set_analyzed_representation(result, representation)
    return result


def hasattr_call(e, node):
    if (len(node.args) != 2 or node.keywords
            or not isinstance(node.args[1], ast.Constant) or not isinstance(node.args[1].value, str)):
        raise LLVMUnsupported("LLVM hasattr requires a literal attribute name", node)
    source, name = node.args[0], node.args[1].value
    semantic = analyzed_value_type(source)
    members = [member for member in get_type_members(semantic) if member.generic_name != "NoneType"]
    if len(members) > 1 or object_values.instance_type(source) is None:
        raise LLVMUnsupported("LLVM hasattr requires a concrete or optional application instance", node)
    if any(member not in e.module.classes for member in members):
        raise LLVMUnsupported("LLVM hasattr requires a concrete or optional application instance", node)
    kind, value = e.expression(source, check_layout=False)

    def select(candidate):
        descriptor = ordinary_lookup(candidate, name, node)
        require_initialized_field(candidate, name, node)
        found = attribute(candidate, name)
        if isinstance(descriptor, property) or isinstance(found, Function) and found.is_property:
            raise LLVMUnsupported("LLVM hasattr cannot yet catch a property AttributeError", node)
        if found is None and descriptor is not _MISSING:
            raise LLVMUnsupported("LLVM hasattr cannot query unmodeled class attributes", node)
        return "true" if found is not None else "false"

    def query(member, storage, payload):
        return calls.runtime_protocol(e, member, payload, "i1", select, lambda result: result,
                                      node, compatible=collection_ops.is_layout_subclass)

    # None still has ordinary builtin attributes such as __class__ and
    # __repr__; only application-specific names are absent on that arm.
    absent = "true" if hasattr(None, name) else "false"
    if not members:
        return "i1", absent
    if nullable.member(semantic):
        return "i1", nullable.dispatch(e, semantic, kind, value, "i1", absent, query)
    return "i1", query(semantic, kind, value)
