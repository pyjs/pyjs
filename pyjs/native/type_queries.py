"""Class identity and callability queries without Python type objects."""

import ast
import builtins

from pyjs.analysis.analyzer import BUILTINS, analyzed_value_object, analyzed_value_type
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.iterable_protocol import is_abstract_iterable, is_abstract_iterator
from pyjs.analysis.objects import (
    CallableClass,
    Class,
    Constant,
    DependencyError,
    Function,
    GenericClass,
    Module,
    ModuleAlias,
    Name,
    UnaryOp,
)
from pyjs.analysis.type_relations import get_type_members, is_subclass
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.decorators import configure_js, native_operation
from pyjs.python import native as native_builtins

from . import dom_types, enum_ops, nullable, object_values, tagged
from .errors import LLVMUnsupported


@native_operation("query.callable")
def query_callable(value: object, /) -> bool:
    # This compiler operation is not a new name in Python's builtin namespace.
    return builtins.callable(value)


def declaration(visitor, node, *, call=None):
    if isinstance(node, ast.Attribute):
        owner = analyzed_value_object(visitor.visit(node.value))
        if isinstance(owner, ModuleAlias) and owner.py_obj is builtins and callable(vars(builtins).get(node.attr)):
            # Native builtin models are already canonical; do not try to
            # inspect Python source for the C-defined builtins module.
            try:
                target = BUILTINS.search(node.attr)
            except NameError:
                visitor.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                             f"native queries do not model builtin {node.attr!r}")
            return ast.copy_location(Name(target), node)
    # A probe of an ordinary call must retain call-target context: inline
    # functions such as cast() may be called but cannot become function values.
    return visitor.visit_call_function(call) if call is not None else visitor.visit(node)


def require_static_owner(visitor, node):
    if (isinstance(node, ast.Attribute)
            and not isinstance(analyzed_value_object(visitor.visit(node.value)), (Module, ModuleAlias))):
        visitor.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native exact type comparisons require static module or name bindings")


def type_call(visitor, node):
    if not isinstance(node, ast.Call) or not isinstance(node.func, (ast.Name, ast.Attribute)):
        return None
    target = analyzed_value_object(declaration(visitor, node.func, call=node))
    if getattr(target, "py_cls", None) is not native_builtins._type:
        return None
    require_static_owner(visitor, node.func)
    if len(node.args) != 1 or node.keywords or isinstance(node.args[0], ast.Starred):
        visitor.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native exact type comparisons require one positional subject")
    return node.args[0]


def operands(visitor, node):
    if len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Is, ast.IsNot)):
        return None
    left, right = type_call(visitor, node.left), type_call(visitor, node.comparators[0])
    if left is None and right is None:
        return None
    target_node = node.comparators[0] if left is not None else node.left
    if left is not None and right is not None or not isinstance(target_node, (ast.Name, ast.Attribute)):
        visitor.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native exact type comparisons require a statically named class")
    target = declaration(visitor, target_node)
    require_static_owner(visitor, target_node)
    expected = analyzed_value_object(target)
    if not isinstance(expected, (Class, GenericClass)):
        visitor.fail(target_node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native exact type comparisons require a statically named class")
    visitor.validate_query_class(target_node, expected, "type")
    if dom_types.is_opaque_type(expected):
        visitor.fail(target_node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native exact type comparisons cannot recover mapped DOM identities")
    return left if left is not None else right, target, isinstance(node.ops[0], ast.IsNot)


def analyze(visitor, node, query):
    source, target, negate = query
    value = visitor.visit(source)
    representation = analyzed_representation(value)
    if representation and (representation.direct_numeric_formats or representation.array):
        visitor.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native exact type comparisons require ordinary runtime representations")
    if any(dom_types.is_opaque_type(member) or enum_ops.scalar_name(member)
           for member in get_type_members(analyzed_value_type(value))):
        visitor.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native exact type comparisons cannot recover mapped or scalar-enum identities")
    helper = BUILTINS.search("type_is")
    assert isinstance(helper, Function)
    if not helper.signature_analyzed:
        raise DependencyError(helper)
    boolean = BUILTINS.search("bool")
    result = visitor.call_node(node, boolean, func=Name(helper, runtime_dependency=helper),
                               args=[value, target], keywords=[])
    return ast.copy_location(UnaryOp(boolean, op=ast.Not(), operand=result), node) if negate else result


def integer_proofs(visitor, test, when_true):
    """Exact-int proofs on paths where every selected boolean term holds."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        yield from integer_proofs(visitor, test.operand, not when_true)
    elif isinstance(test, ast.BoolOp):
        if isinstance(test.op, ast.And) == when_true:
            for term in test.values:
                yield from integer_proofs(visitor, term, when_true)
    elif isinstance(test, ast.Compare) and (query := operands(visitor, test)) is not None:
        source, target, negate = query
        if (when_true != negate and isinstance(source, (ast.Name, ast.Attribute))
                and analyzed_value_object(target) is BUILTINS.search("int")):
            yield ast.unparse(source)


def proven_integer(node, scope):
    binding = analyzed_value_object(node)
    if not getattr(binding, "native_exact_integer", False):
        return False
    # A deferred closure cannot inherit the creation site's flow proof. Its
    # own exact check can create a fresh proof in a scope below its own root.
    current = binding.scope
    while current is not None:
        if current is scope:
            return True
        current = getattr(current, "parent", None)
    return False


def call(emitter, node):
    source = node.args[0]
    expected = analyzed_value_object(node.args[1])
    kind, value = emitter.expression(source, check_layout=False)
    return "i1", exact(emitter, analyzed_value_type(source), kind, value, expected, source)


def analyze_callable(call):
    node, visitor = call.node, call.visitor
    if len(node.args) != 1 or node.keywords or isinstance(node.args[0], ast.Starred):
        visitor.fail(node, DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                     "callable() requires one positional subject without argument expansion")
    source = node.args[0]
    if isinstance(source, (ast.Name, ast.Attribute)):
        # A named inline builtin (e.g. len) is callable in Python even when
        # this backend cannot package it as a first-class function value. Use
        # call-target lookup only for the probe; no invocation/body is reached.
        probe = ast.copy_location(ast.Call(func=source, args=[], keywords=[]), node)
        value = declaration(visitor, source, call=probe)
        if isinstance(analyzed_value_object(value), (Function, Class, GenericClass)) and (
                isinstance(value, ast.Name) or isinstance(value, ast.Attribute)
                and isinstance(analyzed_value_object(value.value), (Module, ModuleAlias))):
            return ast.copy_location(Constant(BUILTINS.search("bool"), value=True), node)
    result = call.standard()
    # Queries observe current storage. A lambda/generator may run after an
    # assertion-narrowed capture changed type; do not read its old payload.
    result.args[0] = visitor.guard_value(result.args[0])
    if any(is_abstract_iterable(member) or is_abstract_iterator(member)
           for member in get_type_members(analyzed_value_type(result.args[0]))):
        visitor.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native callable() queries require a concrete value, not an Iterable/Iterator/Generator view")
    if any(dom_types.is_opaque_type(member)
           for member in get_type_members(object_values.instance_type(result.args[0]))):
        visitor.fail(source, DiagnosticCode.UNSUPPORTED_SYNTAX,
                     "native callable() queries cannot recover mapped DOM call slots")
    return result


configure_js(query_callable, analysis=analyze_callable)


def callable_instance(semantic):
    # CPython tests the type's call slot, not whether getattr(obj, '__call__')
    # produces a callable. Even a property or __call__ = None installs a slot;
    # querying it must neither execute the descriptor nor analyze its body.
    return isinstance(semantic, CallableClass) or any(
        "__call__" in vars(base) for base in getattr(semantic.py_cls, "__mro__", ()))


def callable_call(e, node):
    source = node.args[0]
    subject = analyzed_value_object(source)
    if object_values.instance_type(source) is None:
        if (isinstance(source, ast.Name) or isinstance(source, ast.Attribute)
                and isinstance(analyzed_value_object(source.value), (Module, ModuleAlias))):
            return "i1", "true"
        raise LLVMUnsupported("LLVM callable class queries require a static class binding", source)
    if isinstance(subject, Function) and isinstance(source, ast.Name):
        return "i1", "true"
    # Evaluate even statically known answers: receivers, constructors, indexing,
    # and arbitrary value-producing calls may raise or have observable effects.
    kind, value = e.expression(source, check_layout=False)
    if isinstance(subject, Function):
        return "i1", "true"
    return "i1", callable_value(e, analyzed_value_type(source), kind, value, source)


def callable_value(e, semantic, kind, value, node):
    if kind == tagged.STORAGE:
        return tagged.dispatch(e, semantic, value, "i1",
            lambda member, storage, payload: callable_value(e, member, storage, payload, node),
            runtime_classes=True)
    if nullable.member(semantic):
        return nullable.dispatch(e, semantic, kind, value, "i1", "false",
            lambda member, storage, payload: callable_value(e, member, storage, payload, node))
    if semantic.generic_name == "type":
        return "true"  # Supported runtime class tokens (e.g. exception types).
    if nullable.is_object(semantic) or semantic in e.module.vtable_roots:
        erased = nullable.is_object(semantic)
        identity = (object_values.runtime_identity(e, value) if erased
                    else e.emit_value(f"load ptr, ptr {value}"))
        result = "false"
        for candidate in e.module.vtable_roots:
            if (erased or is_subclass(candidate, semantic)) and callable_instance(candidate):
                matched = e.emit_value(f"icmp eq ptr {identity}, @{e.vtable_name(candidate)}")
                result = matched if result == "false" else e.emit_value(f"or i1 {result}, {matched}")
        return result
    return str(callable_instance(semantic)).lower()


def application_identity(emitter, actual, expected, kind="ptr"):
    # PEP 695 specializations have distinct native layouts, but share the
    # original Python class identity. Subclasses have a different py_cls.
    result = "false"
    candidates = emitter.module.classes if kind == "i64" else emitter.module.vtable_roots
    for concrete in candidates:
        if concrete.py_cls is expected.py_cls:
            identity = tagged.tag(emitter, concrete) if kind == "i64" else "@" + emitter.vtable_name(concrete)
            matched = emitter.emit_value(f"icmp eq {kind} {actual}, {identity}")
            result = matched if result == "false" else emitter.emit_value(f"or i1 {result}, {matched}")
    return result


def exact(emitter, semantic, kind, value, expected, node):
    if kind == tagged.STORAGE:
        actual, _ = tagged.parts(emitter, value)
        if not expected.container.scope.is_builtins:
            return application_identity(emitter, actual, expected, "i64")
        return emitter.emit_value(f"icmp eq i64 {actual}, {tagged.tag(emitter, expected)}")
    if nullable.is_object(semantic):
        name = object_values.runtime_name(expected)
        if name == "NoneType":
            return emitter.emit_value(f"icmp eq ptr {value}, null")
        if name in {"bool", "int", "float", *object_values.REFERENCES}:
            symbol = f"pyjs.object.type.{name}"
        elif not expected.container.scope.is_builtins:
            return application_identity(emitter, object_values.runtime_identity(emitter, value), expected)
        else:
            raise LLVMUnsupported("LLVM exact type query requires a preserved runtime identity", node)
        actual = object_values.runtime_identity(emitter, value)
        return emitter.emit_value(f"icmp eq ptr {actual}, @{symbol}")
    if nullable.member(semantic):
        absent = str(getattr(expected, "generic_name", None) == "NoneType").lower()
        return nullable.dispatch(emitter, semantic, kind, value, "i1", absent,
            lambda member, storage, payload: exact(emitter, member, storage, payload, expected, node))
    if semantic in emitter.module.classes:
        if semantic not in emitter.module.vtable_roots:
            raise LLVMUnsupported("LLVM exact application type query requires runtime class identity", node)
        table = emitter.emit_value(f"load ptr, ptr {value}")
        return application_identity(emitter, table, expected)
    actual = tagged.runtime_type(semantic)
    # Ordinary builtin ABIs retain class identity: implicit bool-to-i64 and
    # scalar-enum widening are rejected by their existing conversion gates.
    # Interface views, unlike concrete containers, are not runtime classes.
    if object_values.runtime_name(actual) not in {"NoneType", "bool", "int", "float", *object_values.REFERENCES}:
        raise LLVMUnsupported("LLVM exact type query requires a preserved runtime identity", node)
    return str(getattr(actual, "py_cls", None) is expected.py_cls).lower()
