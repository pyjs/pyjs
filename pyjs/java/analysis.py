"""Analysis configuration for direct JVM compilation."""

import inspect

from pyjs.analysis import create_analysis_environment
from pyjs.analysis.analyzer import CallGraphVisitor
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.ir import IRInferenceVisitor
from pyjs.analysis.lifetime import refine_lifetimes
from pyjs.analysis.objects import Class, Function, Instance, UnionType
from pyjs.decorators import backend_metadata, is_declaration
from pyjs.python import native as native_builtins
from pyjs.python.native_libraries import NativeProtocolMappings


class JVMInferenceVisitor(IRInferenceVisitor):
    """JVM analysis policy."""

    numeric_domains = frozenset({"portable", "wgsl", "java"})
    lower_exception_regions = True

    def visit_With(self, node):
        self.fail(node, DiagnosticCode.UNSUPPORTED_SYNTAX,
                  "JVM context-manager regions are not implemented yet")

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
