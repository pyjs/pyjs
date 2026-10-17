"""WGSL analysis policy."""

import ast

from pyjs.analysis import create_analysis_environment
from pyjs.analysis.analyzer import (
    InferenceVisitor,
    analyzed_value_type,
)
from pyjs.analysis.diagnostics import DiagnosticCode
from pyjs.analysis.libraries import PYJS_LIBRARY_MAPPINGS
from pyjs.analysis.objects import Class, TypeAliasValue
from pyjs.analysis.representation import apply_representation, direct_representation
from pyjs.analysis.value_representation import (
    analyzed_numeric_format,
    set_analyzed_representation,
)
from pyjs.decorators import is_declaration
from pyjs.numeric import NumericFormat
from pyjs.python import wgsl as wgsl_builtins


class WGSLInferenceVisitor(InferenceVisitor):
    """Enforce WGSL rules while sharing Python inference."""

    numeric_domains = frozenset({"wgsl"})

    def annotation_numeric_format(self, annotation):
        result = super().annotation_numeric_format(annotation)
        if (
            result is not None
            or self.module.scope.is_builtins
            or is_declaration(self.func.py_func, "wgsl")
            or not isinstance(annotation, ast.Name)
        ):
            return result
        try:
            value = self.scope.search(annotation.id)
        except NameError:
            return None
        if isinstance(value, TypeAliasValue):
            value = value.annotation
            numeric_name = getattr(value, "__name__", None)
        elif isinstance(value, Class):
            numeric_name = value.generic_name
        else:
            return None
        if numeric_name not in {"int", "float"}:
            return None
        replacement = "i32" if numeric_name == "int" else "f32"
        self.fail(
            annotation,
            DiagnosticCode.INCOMPATIBLE_ARGUMENT,
            f"Python {numeric_name} annotations cannot compile for WGSL",
            help=f"Use pyjs.shader.{replacement} for shader numeric values.",
        )

    def validate_numeric_format(self, node, numeric) -> None:
        if numeric.domain == "wgsl":
            return
        if numeric.domain == "portable":
            if numeric.kind == "integer" and numeric.bits == 32:
                replacement = "i32" if numeric.signed else "u32"
            elif numeric.kind == "float" and numeric.bits == 32:
                replacement = "f32"
            else:
                replacement = None
            help_text = (
                f"Use pyjs.shader.{replacement}."
                if replacement is not None
                else "Use a WGSL-specific scalar type."
            )
            numeric_name = (
                ("int" if numeric.signed else "uint") + str(numeric.bits)
                if numeric.kind == "integer"
                else f"float{numeric.bits}"
            )
            self.fail(
                node,
                DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                f"portable PyJS {numeric_name} cannot compile for WGSL",
                help=help_text,
            )
        super().validate_numeric_format(node, numeric)

    @staticmethod
    def default_numeric_format(value_type):
        if value_type.generic_name == "int":
            return NumericFormat("integer", 32, True, domain="wgsl")
        if value_type.generic_name == "float":
            return NumericFormat("float", 32, domain="wgsl")
        return None

    def analyze_assignment_value(
        self,
        value_node,
        annotation_node=None,
        contextual_type=None,
    ):
        result = super().analyze_assignment_value(
            value_node,
            annotation_node,
            contextual_type,
        )
        if annotation_node is not None or analyzed_numeric_format(result.node):
            return result
        set_analyzed_representation(
            result.node,
            direct_representation(
                self.default_numeric_format(analyzed_value_type(result.node)),
                None,
            ),
        )
        return result

    def bind_loop_target(self, target, value_type, representation=None):
        result = super().bind_loop_target(target, value_type, representation)
        for target_value in (
            value for value in ast.walk(result) if isinstance(value, ast.arg)
        ):
            value = self.scope.lookup(target_value.arg)
            numeric = self.default_numeric_format(value.cls)
            represented = direct_representation(numeric, None)
            apply_representation(value, represented)
            apply_representation(target_value, represented)
        return result


WGSL_ENVIRONMENT = create_analysis_environment(
    "wgsl",
    wgsl_builtins,
    inference_visitor=WGSLInferenceVisitor,
    library_mappings=PYJS_LIBRARY_MAPPINGS,
    analyze_all_definitions=wgsl_builtins.analyze_all_definitions,
    definition_filter=wgsl_builtins.include_definition,
    body_filter=wgsl_builtins.should_analyze_body,
)
