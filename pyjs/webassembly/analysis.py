"""Analysis configuration for direct WebAssembly compilation."""

import inspect

from pyjs.analysis import create_analysis_environment
from pyjs.analysis.ir import IRInferenceVisitor
from pyjs.analysis.lifetime import refine_lifetimes
from pyjs.python import native as native_builtins
from pyjs.python.native_libraries import NativeProtocolMappings
from pyjs.stdlib.math import isfinite


class WebAssemblyInferenceVisitor(IRInferenceVisitor):
    """Direct WebAssembly analysis policy."""

    numeric_domains = frozenset({"portable", "wgsl", "webassembly"})


WEBASSEMBLY_LIBRARY_MAPPINGS = NativeProtocolMappings(
    stdlib_imports={
        ("math", None): ("pyjs.stdlib.math", None),
        ("math", "isfinite"): ("pyjs.stdlib.math", "isfinite"),
        ("typing", "cast"): ("pyjs.stdlib.typing", "cast"),
    }
)


def include_definition(name, value, module) -> bool:
    return getattr(value, "__module__", None) == module.name and (
        inspect.isfunction(value) or inspect.isclass(value)
    )


def should_analyze_body(func) -> bool:
    return func.py_func is not isfinite


WEBASSEMBLY_ENVIRONMENT = create_analysis_environment(
    "webassembly",
    native_builtins,
    inference_visitor=WebAssemblyInferenceVisitor,
    library_mappings=WEBASSEMBLY_LIBRARY_MAPPINGS,
    analyze_all_definitions=False,
    defer_unselected_imports=True,
    definition_filter=include_definition,
    body_filter=should_analyze_body,
    analysis_finalizer=refine_lifetimes,
)
