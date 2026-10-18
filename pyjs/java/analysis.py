"""Analysis configuration for direct JVM compilation."""

import ast
import inspect

from pyjs.analysis import create_analysis_environment, super_proxy
from pyjs.analysis.analyzer import CallGraphVisitor, analyzed_value_type
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.ir import ExceptionRaise, IRInferenceVisitor
from pyjs.analysis.lifetime import refine_lifetimes
from pyjs.analysis.objects import Class, Function, Instance, UnionType
from pyjs.decorators import backend_metadata, is_declaration
from pyjs.python import native as native_builtins
from pyjs.python.native_libraries import NativeProtocolMappings

from .diagnostics import JVMUnsupported
from .exceptions import managed_exception


class JVMInferenceVisitor(IRInferenceVisitor):
    """JVM analysis policy."""

    numeric_domains = frozenset({"portable", "wgsl", "java"})
    lower_exception_regions = True
    lower_exception_objects = True

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
                        semantic = analyzed_value_type(value.exception)
                        members = semantic.types if isinstance(semantic, UnionType) else (semantic,)
                        value.runtime_protocols = (
                            *getattr(value, "runtime_protocols", ()),
                            *((member, ("__str__",)) for member in members if managed_exception(member)),
                        )
        return result

    def visit_Call(self, node):
        result = super().visit_Call(node)
        if not isinstance(result, ast.Call):
            return result
        target = getattr(result.func, "obj", None)
        receiver = None
        if getattr(target, "py_obj", None) is native_builtins._str and result.args:
            receiver = result.args[0]
        elif getattr(target, "name", None) == "__str__" and isinstance(result.func, ast.Attribute):
            value = result.func.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == "super"):
                receiver = value
        if receiver is not None:
            semantic = analyzed_value_type(receiver)
            members = semantic.types if isinstance(semantic, UnionType) else (semantic,)
            result.jvm_exception_protocols = tuple(
                (member, ("__str__",)) for member in members if managed_exception(member)
            )
            result.runtime_protocols = (*getattr(result, "runtime_protocols", ()),
                                        *result.jvm_exception_protocols)
        return result

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


def finalize_jvm_analysis(entry_point: Function) -> None:
    """Retain callbacks invoked by a native runtime rather than Python code."""

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

    visitor = CallGraphVisitor(entry_point, entry_point)
    pending = [
        value for value in entry_point.compilation_objects if isinstance(value, Class)
    ]
    processed = set()
    while pending:
        value_type = pending.pop()
        if value_type in processed:
            continue
        processed.add(value_type)
        for field in value_type._self.attrs.values():
            if not isinstance(field, Instance):
                continue
            for dependency in storage_classes(field.cls):
                visitor.enter_class(dependency)
        if value_type.super is None:
            continue
        native_base = value_type.super
        while native_base is not None and not is_declaration(
            native_base.py_obj,
            "jvm",
        ):
            native_base = native_base.super
        if native_base is None:
            continue
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
                CallGraphVisitor(implementation, entry_point).enter(implementation)
        pending.extend(
            value
            for value in entry_point.compilation_objects
            if isinstance(value, Class) and value not in processed
        )
    refine_lifetimes(entry_point)


JVM_ENVIRONMENT = create_analysis_environment(
    "jvm",
    native_builtins,
    inference_visitor=JVMInferenceVisitor,
    library_mappings=NativeProtocolMappings(
        stdlib_imports={
            ("typing", "cast"): ("pyjs.stdlib.typing", "cast"),
        }
    ),
    analyze_all_definitions=False,
    defer_unselected_imports=True,
    definition_filter=include_definition,
    body_filter=should_analyze_body,
    analysis_finalizer=finalize_jvm_analysis,
)
