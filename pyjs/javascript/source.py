"""Analyze Python source and compile its JavaScript client graph."""

import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

from pyjs.analysis import source as analysis_source
from pyjs.analysis.objects import CompilationExtension, Function
from pyjs.decorators import configure_js

from .sourcemap import SourceMap, TranspiledJavaScript
from .transpiler import (
    Transpiler,
    _module_output_nodes,
    _write_bundle,
    bundle_import,
    prepare_bundle_with_source_maps,
    transpile_module,
)


@dataclass(frozen=True)
class SourceAnalysis:
    analysis: analysis_source.SourceAnalysis

    def close(self) -> None:
        self.analysis.close()

    def __enter__(self) -> SourceAnalysis:
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    @property
    def module(self):
        return self.analysis.module

    @property
    def entry_point(self) -> Function:
        return self.analysis.entry_point

    @property
    def wrapped(self) -> bool:
        return self.analysis.wrapped

    @property
    def types(self) -> str:
        return self.analysis.types

    @property
    def javascript(self) -> str:
        return Transpiler(self.entry_point).visit(self.entry_point.container.node)


@dataclass(frozen=True)
class SourceCompilation:
    analysis: SourceAnalysis
    sources: dict[str, str]
    javascript: str
    css: str
    elapsed: float
    filename: str
    source_map: SourceMap

    def close(self) -> None:
        self.analysis.close()

    def __enter__(self) -> SourceCompilation:
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    @property
    def entry_point(self) -> Function:
        return self.analysis.entry_point

    @property
    def module_names(self) -> tuple[str, ...]:
        return tuple(self.sources)


def analyze_source(*args, **kwargs) -> SourceAnalysis:
    return SourceAnalysis(analysis_source.analyze_source(*args, **kwargs))


def compile_source(
    source: str,
    *,
    filename: str = "_pyjs_source_.py",
    module_name: str | None = None,
    wrap: bool | None = None,
    include_css: bool = False,
    extensions: tuple[CompilationExtension, ...] = (),
) -> SourceCompilation:
    started = time.perf_counter()
    original_source = textwrap.dedent(source)
    source, wrapped, display_source, simple_wrapper = analysis_source._prepare_source(
        source,
        filename,
        wrap,
    )
    module = analysis_source.create_module(
        source,
        filename,
        module_name,
        display_source=display_source,
        simple_wrapper=simple_wrapper,
    )
    module.__pyjs_original_source__ = original_source
    configure_js(module.main, enabled=True)
    package, source_maps, entry_point, css = prepare_bundle_with_source_maps(
        module.main,
        bundle_import,
        lambda name: f"__export_js__.{name} = {name};",
        include_main=True,
        extensions=extensions,
        include_css=include_css,
    )
    analysis = SourceAnalysis(
        analysis_source.SourceAnalysis(module, entry_point, wrapped)
    )
    sources = {}
    for source_module_name, module_obj in entry_point.container.container.items():
        included_nodes, post_definition_classes = _module_output_nodes(module_obj)
        if not included_nodes and not post_definition_classes:
            continue
        if module_source := transpile_module(module_obj):
            sources[source_module_name] = module_source
    generated = _write_bundle(
        package,
        entry_point,
        call_main=False,
        expose_entry=True,
        source_maps=source_maps,
        filename=f"{Path(filename).stem}.js",
    )
    assert isinstance(generated, TranspiledJavaScript)
    return SourceCompilation(
        analysis,
        sources,
        generated.javascript,
        css,
        time.perf_counter() - started,
        filename,
        generated.source_map,
    )
