"""Analysis configuration for direct WebAssembly compilation."""

import inspect

from pyjs.analysis import create_analysis_environment
from pyjs.analysis.ir import IRInferenceVisitor
from pyjs.analysis.lifetime import refine_lifetimes
from pyjs.python import native as native_builtins
from pyjs.python.native_libraries import NativeProtocolMappings
from pyjs.stdlib.math import cos, hypot, isfinite, radians, sin, sqrt

from . import memory as linear_memory


class WebAssemblyInferenceVisitor(IRInferenceVisitor):
    """Direct WebAssembly analysis policy."""

    numeric_domains = frozenset({"portable", "wgsl", "webassembly"})


WEBASSEMBLY_LIBRARY_MAPPINGS = NativeProtocolMappings(
    stdlib_imports={
        ("math", None): ("pyjs.stdlib.math", None),
        ("math", "isfinite"): ("pyjs.stdlib.math", "isfinite"),
        ("math", "hypot"): ("pyjs.stdlib.math", "hypot"),
        ("math", "cos"): ("pyjs.stdlib.math", "cos"),
        ("math", "radians"): ("pyjs.stdlib.math", "radians"),
        ("math", "sin"): ("pyjs.stdlib.math", "sin"),
        ("math", "sqrt"): ("pyjs.stdlib.math", "sqrt"),
        ("typing", "cast"): ("pyjs.stdlib.typing", "cast"),
    }
)


def include_definition(name, value, module) -> bool:
    client_annotation = module.js_annotations.get(name)
    return (client_annotation is not None and client_annotation[1]) or (
        getattr(value, "__module__", None) == module.name
        and (inspect.isfunction(value) or inspect.isclass(value))
    )


def should_analyze_body(func) -> bool:
    return func.py_func not in {
        hypot,
        isfinite,
        cos,
        radians,
        sin,
        sqrt,
        linear_memory.grow_memory,
        linear_memory.load_f32,
        linear_memory.load_f64,
        linear_memory.load_i32,
        linear_memory.memory_byte_length,
        linear_memory.store_f32,
        linear_memory.store_f64,
        linear_memory.store_i32,
    }


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
