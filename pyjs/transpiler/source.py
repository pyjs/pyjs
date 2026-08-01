import ast
import linecache
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from .analyzer import analyze_module
from .objects import CompilationExtension, Function
from .transpiler import (
    Transpiler,
    _write_bundle,
    bundle_import,
    prepare_bundle,
    transpile_module,
)
from .utils import write_types


@dataclass(frozen=True)
class SourceAnalysis:
    module: ModuleType
    entry_point: Function
    wrapped: bool

    @property
    def types(self) -> str:
        return write_types(self.entry_point.container.node)

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

    @property
    def entry_point(self) -> Function:
        return self.analysis.entry_point

    @property
    def module_names(self) -> tuple[str, ...]:
        return tuple(self.sources)


def create_module(
    source: str, filename: str = "_pyjs_source_.py", module_name: str | None = None
):
    """Execute source in an inspectable in-memory module.

    Compilation executes Python module-level code, just like importing a source
    module. This is a compilation API, not a sandbox for untrusted source.
    """
    filename = str(filename)
    name = module_name or Path(filename).stem.replace("-", "_")
    linecache.cache[filename] = (
        len(source),
        None,
        source.splitlines(keepends=True),
        filename,
    )
    module = ModuleType(name)
    module.__file__ = filename
    module.__package__ = name.rpartition(".")[0]
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(source, filename, "exec"), module.__dict__)
    except BaseException:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        raise
    return module


def wrap_source(source: str) -> str:
    source = textwrap.dedent(source)
    module = ast.parse(source)
    declaration_types = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )
    declarations = [node for node in module.body if isinstance(node, declaration_types)]
    statements = [node for node in module.body if not isinstance(node, declaration_types)]
    if declarations:
        main = ast.FunctionDef(
            name="main",
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=statements or [ast.Pass()],
            decorator_list=[],
            returns=None,
            type_comment=None,
            type_params=[],
        )
        module = ast.Module(body=declarations + [main], type_ignores=[])
        return ast.unparse(ast.fix_missing_locations(module)) + "\n"

    body = textwrap.indent(source, "    ")
    if not body.strip():
        body = "    pass\n"
    elif not body.endswith("\n"):
        body += "\n"
    return f"def main():\n{body}"


def _prepare_source(source: str, filename: str, wrap: bool | None) -> tuple[str, bool]:
    source = textwrap.dedent(source)
    if wrap is None:
        wrap = not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
            for node in ast.parse(source, filename).body
        )
    return (wrap_source(source) if wrap else source), wrap


def analyze_source(
    source: str,
    *,
    filename: str = "_pyjs_source_.py",
    module_name: str | None = None,
    wrap: bool | None = None,
    extensions: tuple[CompilationExtension, ...] = (),
) -> SourceAnalysis:
    source, wrapped = _prepare_source(source, filename, wrap)
    module = create_module(source, filename, module_name)
    entry = module.main
    entry.__js__ = True
    entry.__js_include__ = True
    entry_point, _ = analyze_module(module, extensions=extensions)
    return SourceAnalysis(module, entry_point, wrapped)


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
    source, wrapped = _prepare_source(source, filename, wrap)
    module = create_module(source, filename, module_name)
    module.main.__js__ = True
    module.main.__js_include__ = True
    package, entry_point, css = prepare_bundle(
        module.main,
        bundle_import,
        lambda name: f"__export_js__.{name} = {name};",
        include_main=True,
        extensions=extensions,
        include_css=include_css,
    )
    analysis = SourceAnalysis(module, entry_point, wrapped)
    sources = {}
    for module_name, module_obj in entry_point.container.container.items():
        if source := transpile_module(module_obj):
            sources[module_name] = source
    javascript = _write_bundle(package, entry_point, call_main=False, expose_entry=True)
    return SourceCompilation(
        analysis,
        sources,
        javascript,
        css,
        time.perf_counter() - started,
        filename,
    )
