"""Backend-neutral Python analysis and its typed object graph."""

from .analyzer import (
    AnalysisEnvironment,
    analyze_module,
    create_analysis_environment,
    release_compilation,
)
from .diagnostics import (
    CompilationError,
    Diagnostic,
    DiagnosticCode,
    format_compilation_error,
)
from .libraries import LibraryMappings
from .objects import CompilationExtension
from .source import SourceAnalysis, analyze_source, create_module

__all__ = [
    "AnalysisEnvironment",
    "CompilationError",
    "CompilationExtension",
    "Diagnostic",
    "DiagnosticCode",
    "LibraryMappings",
    "SourceAnalysis",
    "analyze_module",
    "analyze_source",
    "create_analysis_environment",
    "create_module",
    "format_compilation_error",
    "release_compilation",
]
