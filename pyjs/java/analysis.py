"""Analysis configuration for direct JVM compilation."""

import ast
import inspect

from pyjs.analysis import create_analysis_environment, super_proxy
from pyjs.analysis.analyzer import (
    CallGraphVisitor,
    analyzed_representation,
    analyzed_value_type,
    field_owner,
)
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.ir import (
    ExceptionRaise,
    FieldStore,
    IRInferenceVisitor,
    ObjectNew,
    Return,
)
from pyjs.analysis.lifetime import refine_lifetimes
from pyjs.analysis.objects import (
    AnalyzedExpression,
    BoolOp,
    Class,
    Function,
    Instance,
    Name,
    StaticCast,
    UnionType,
    resolve_imported,
)
from pyjs.decorators import backend_metadata, is_declaration
from pyjs.python import native as native_builtins
from pyjs.python.native_libraries import NativeProtocolMappings

from .diagnostics import JVMUnsupported
from .exceptions import (
    contained_exception_types,
    exception_type,
    managed_exception,
    nullable_exception,
)
from .models import LIBRARY as MODEL_LIBRARY
from .models import BaseModel, is_model, unsupported_json_codec


class JVMInferenceVisitor(IRInferenceVisitor):
    """JVM analysis policy."""

    numeric_domains = frozenset({"portable", "wgsl", "java"})
    lower_exception_regions = True
    lower_exception_objects = True
    supports_exception_causes = True
    supports_exception_args = True

    def analyze_isinstance(self, call):
        return call.isinstance(validate_numeric=False)

    def truth_test(self, node, test):
        if isinstance(test, ast.BoolOp):
            # A condition consumes only truth, not the operand-valued union.
            # Keep short-circuit evaluation but normalize each visited leaf at
            # its own evaluation point, before incompatible ABIs are joined.
            values = [self.truth_test(node, value) for value in test.values]
            return ast.copy_location(BoolOp(JVM_ENVIRONMENT.builtins.search("bool"),
                                           op=test.op, values=values), node)
        result = super().truth_test(node, test)
        if (isinstance(result, ast.Call)
                and getattr(getattr(result.func, "obj", None), "name", None) == "__len__"):
            result.jvm_truth_length = True
        return result

    def visit_FunctionDef(self, node):
        result = super().visit_FunctionDef(node)
        if not self.pending_flow_widenings:
            for value in super_proxy.prepare(self.func, JVMUnsupported, "JVM"):
                if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                        and value.func.attr == "__str__"
                        and super_proxy.is_receiver(value.func.value)):
                    # Aliases acquire provenance after their calls are analyzed.
                    # Lexical parent calls must not retain subclass overrides.
                    added = getattr(value, "jvm_exception_protocols", ())
                    value.runtime_protocols = tuple(
                        protocol for protocol in value.runtime_protocols if protocol not in added
                    )
            for block in self.func.ir.blocks:
                for value in ast.walk(block):
                    if (isinstance(value, ExceptionRaise) and value.exception is not None
                            and (not value.reraised or value.append_trace)):
                        # Java's uncaught printer consumes both the wrapper
                        # and its cause, even without a Python text call.
                        for operand in (value.exception, value.cause):
                            if operand is None:
                                continue
                            semantic = analyzed_value_type(operand)
                            members = semantic.types if isinstance(semantic, UnionType) else (semantic,)
                            value.runtime_protocols = (
                                *getattr(value, "runtime_protocols", ()),
                                *((member, ("__str__",)) for member in members
                                  if managed_exception(member)),
                            )
        return result

    def visit_Call(self, node):
        result = super().visit_Call(node)
        if not isinstance(result, ast.Call):
            return result
        target = getattr(result.func, "obj", None)
        if (node not in self.active_call_analysis
                and getattr(target, "py_obj", None) is native_builtins._sorted):
            return self.sorted_call(result, node)
        self.validate_model_call(node, target, result.args)
        receiver = None
        if getattr(target, "py_obj", None) is native_builtins._str and result.args:
            receiver = result.args[0]
        elif getattr(target, "name", None) == "__str__" and isinstance(result.func, ast.Attribute):
            value = result.func.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == "super"):
                receiver = value
        if receiver is not None:
            self.retain_exception_formatter(result, receiver)
        return result

    def sorted_call(self, node, source_node):
        from .sorting import Sorted

        key = next((value.value for value in node.keywords if value.arg == "key"), None)
        if key is not None and not (isinstance(key, ast.Constant) and key.value is None):
            self.fail(source_node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "JVM sorted() key callbacks are not implemented")
        if analyzed_representation(node.args[0]) is not None:
            self.fail(source_node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "JVM sorted() fixed-width item representations are not implemented")
        # Generic classes already specialize their methods by concrete source
        # and item types. Reuse that path rather than a second sort bytecode
        # emitter. Wrapped analyzed expressions preserve one evaluation.
        source = analyzed_value_type(node.args[0])
        if (not isinstance(source, Class)
                or source.generic_name not in {"list", "str", "dict", "KeysView", "set"}):
            self.fail(source_node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "JVM sorted() requires a list, string, set, or dictionary key collection")
        item = analyzed_value_type(node).generic_types["V"]
        helper = resolve_imported(Sorted, self.module, "Sorted")(source, item)
        call = ast.Call(func=AnalyzedExpression(Name(helper)),
                        args=[AnalyzedExpression(value) for value in node.args],
                        keywords=[ast.keyword(arg=value.arg, value=AnalyzedExpression(value.value))
                                  for value in node.keywords if value.arg != "key"])
        expression = ast.Attribute(value=call, attr="result", ctx=ast.Load())
        return self.visit(ast.fix_missing_locations(ast.copy_location(expression, source_node)))

    def call_node(self, node, return_type, *, func, args, keywords, **attributes):
        self.validate_model_call(node, func.obj, args)
        return super().call_node(node, return_type, func=func, args=args, keywords=keywords, **attributes)

    def validate_model_call(self, node, target, args):
        model_operation = (isinstance(target, Function) and target.cls is not None
                           and target.cls.py_obj is BaseModel)
        model_operation |= getattr(target, "py_obj", None) is unsupported_json_codec
        if getattr(target, "py_obj", None) in {
                native_builtins._str, native_builtins._repr, native_builtins._hash} and args:
            value_type = analyzed_value_type(args[0])
            members = value_type.types if isinstance(value_type, UnionType) else (value_type,)
            model_operation = any(is_model(member.py_obj) for member in members)
        if model_operation:
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "JVM client models support typed construction and fields, not model operations")

    @staticmethod
    def retain_exception_formatter(call, receiver):
        semantic = analyzed_value_type(receiver)
        members = semantic.types if isinstance(semantic, UnionType) else (semantic,)
        call.jvm_exception_protocols = tuple(
            (member, ("__str__",)) for member in members if exception_type(member) is not None
        )
        call.runtime_protocols = (*getattr(call, "runtime_protocols", ()),
                                  *call.jvm_exception_protocols)

    def dispatch_dunder_call(self, builtin, method_name, args, keywords):
        # Python text consumers share runtime dispatch, including foreign
        # subclasses and unions whose members have unrelated method owners.
        if (method_name == "__str__" and len(args) == 1 and not keywords
                and (exception_type(analyzed_value_type(args[0])) is not None
                     or nullable_exception(analyzed_value_type(args[0])))):
            call = self.call_node(
                args[0], builtin, func=Name(builtin), args=args, keywords=[],
            )
            self.retain_exception_formatter(call, args[0])
            return call
        return super().dispatch_dunder_call(builtin, method_name, args, keywords)

    def expand_static_call_keywords(self, node, call_target=None):
        if getattr(call_target, "py_obj", None) is native_builtins._dict and node.keywords:
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "JVM dict() keyword construction is not implemented")
        if getattr(call_target, "py_obj", None) is native_builtins._dict and node.args:
            self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                      "JVM dict() source construction is not implemented")
        super().expand_static_call_keywords(node, call_target)


def include_definition(name, value, module) -> bool:
    return (
        value is None
        or isinstance(value, (bool, int, float, str, list, tuple, dict))
        or is_declaration(value, "jvm")
        or (
            getattr(value, "__module__", None) == module.name
            and (inspect.isfunction(value) or inspect.isclass(value))
        )
    )


def should_analyze_body(func) -> bool:
    return not (
        is_declaration(func.py_func, "jvm")
        or func.cls is not None
        and is_declaration(func.cls.py_obj, "jvm")
    )


def native_callable(value) -> bool:
    if isinstance(value, Class):
        if is_declaration(value.py_obj, "jvm"):
            return True
        value = value.find_attrs("__init__", search_bases=True)
    return isinstance(value, Function) and not should_analyze_body(value)


def storage_classes(value_type):
    if isinstance(value_type, UnionType):
        for member in value_type.types:
            yield from storage_classes(member)
        return
    if not isinstance(value_type, Class):
        return
    for member in (value_type.generic_types or {}).values():
        yield from storage_classes(member)
    if not getattr(value_type.py_obj, "__builtin__", False):
        yield value_type


def retain_native_exception_text(visitor, value):
    # Java can call Throwable.toString/getMessage without an analyzed Python
    # formatting call. Keep this dependency scoped to values crossing its ABI,
    # including typed containers, rather than every constructed exception.
    if isinstance(value, ast.Constant):
        return  # Includes synthetic, untyped None returns from void callbacks.
    for value_type in contained_exception_types(analyzed_value_type(value)):
        if managed_exception(value_type):
            visitor.retain_runtime_protocol(value_type, ("__str__",))


def retain_native_field_text(visitor, target, value):
    if not isinstance(target, ast.Attribute):
        return
    owner = field_owner(getattr(target, "obj", None))
    if owner is not None and is_declaration(owner.py_obj, "jvm"):
        # Use the declared field owner, not the receiver's class: an inherited
        # native field crosses the ABI, but a Python-owned field on the same
        # native subclass does not.
        retain_native_exception_text(visitor, value)


def retain_native_boundary_dependencies(visitor, function):
    if function.ir is None:
        return
    for block in function.ir.blocks:
        for node in ast.walk(block):
            if isinstance(node, ast.Call) and native_callable(getattr(node.func, "obj", None)):
                values = [*node.args, *(keyword.value for keyword in node.keywords)]
                if isinstance(node.func, ast.Attribute):
                    values.append(node.func.value)
                for value in values:
                    retain_native_exception_text(visitor, value)
            elif isinstance(node, ObjectNew) and managed_exception(node.value_type):
                # Original positional values also escape through args' Object[]
                # storage, even if the authored initializer discards them.
                for value in node.call.args:
                    retain_native_exception_text(visitor, value)
            elif isinstance(node, (FieldStore, ast.AnnAssign)) and node.value is not None:
                retain_native_field_text(visitor, node.target, node.value)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    retain_native_field_text(visitor, target, node.value)
            elif isinstance(node, StaticCast):
                target = analyzed_value_type(node)
                for dependency in storage_classes(target):
                    visitor.enter_class(dependency)
                members = target.types if isinstance(target, UnionType) else (target,)
                if any(isinstance(member, Class) and (
                        member.py_obj is native_builtins._object
                        or is_declaration(member.py_obj, "jvm")) for member in members):
                    # A native view can be stored or passed through another
                    # function before Java consumes it. Nullable native and
                    # plain object views erase the managed source type too.
                    retain_native_exception_text(visitor, node.value)


def finalize_jvm_analysis(entry_point: Function) -> None:
    """Retain callbacks invoked by a native runtime rather than Python code."""

    visitor = CallGraphVisitor(entry_point, entry_point)

    def retain_class(value_type):
        for field in value_type._self.attrs.values():
            if not isinstance(field, Instance):
                continue
            for dependency in storage_classes(field.cls):
                visitor.enter_class(dependency)
        if value_type.super is None:
            return
        native_base = value_type.super
        while native_base is not None and not is_declaration(
            native_base.py_obj,
            "jvm",
        ):
            native_base = native_base.super
        if native_base is None:
            return
        interface = backend_metadata(
            native_base.py_obj,
            "jvm",
            "interface",
            False,
        )
        for declaration in native_base.children:
            if not isinstance(declaration, Function):
                continue
            if interface:
                CallGraphVisitor(declaration, entry_point).enter(declaration)
            implementation = value_type.find_attrs(
                declaration.name,
                search_bases=True,
            )
            if (
                isinstance(implementation, Function)
                and implementation is not declaration
                and not is_declaration(implementation.py_func, "jvm")
            ):
                # A Java-only virtual call still needs its binding signature
                # analyzed before override ABI validation.
                visitor.enter(declaration)
                CallGraphVisitor(implementation, entry_point).enter(implementation)
                if implementation.ir is not None:
                    for block in implementation.ir.blocks:
                        for node in ast.walk(block):
                            if isinstance(node, Return) and node.value is not None:
                                retain_native_exception_text(visitor, node.value)

    processed = set()
    while pending := [
            value
            for value in entry_point.compilation_objects
            if isinstance(value, (Class, Function)) and value not in processed]:
        # Newly reached formatter bodies can expose more native callbacks.
        # Scan the graph once per batch, not once per function or dependency.
        processed.update(pending)
        for value in pending:
            if isinstance(value, Function):
                retain_native_boundary_dependencies(visitor, value)
            else:
                retain_class(value)
    refine_lifetimes(entry_point)


class JVMImports(NativeProtocolMappings):
    def class_info(self, cls):
        if hasattr(cls, "__pyjs_operations__"):
            from .api import class_info

            if info := class_info(cls):
                return info
        return super().class_info(cls)


JVM_ENVIRONMENT = create_analysis_environment(
    "jvm",
    native_builtins,
    inference_visitor=JVMInferenceVisitor,
    library_mappings=JVMImports(
        libraries=(MODEL_LIBRARY,),
        stdlib_imports={
            ("typing", "cast"): ("pyjs.stdlib.typing", "cast"),
            ("pyjs.server", "API"): ("pyjs.server.jvm_client", "API"),
        }
    ),
    analyze_all_definitions=False,
    defer_unselected_imports=True,
    definition_filter=include_definition,
    body_filter=should_analyze_body,
    analysis_finalizer=finalize_jvm_analysis,
)
