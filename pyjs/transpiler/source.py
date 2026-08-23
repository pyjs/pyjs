import ast
import contextlib
import linecache
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from .analyzer import analyze_module, release_compilation
from .objects import CompilationExtension, Function
from .sourcemap import SourceMap, TranspiledJavaScript
from .transpiler import (
    Transpiler,
    _write_bundle,
    bundle_import,
    prepare_bundle_with_source_maps,
    transpile_module,
)
from .utils import write_types

TYPE_ALIAS_CONTAINERS = {
    "Annotated",
    "Awaitable",
    "Callable",
    "ClassVar",
    "Collection",
    "Container",
    "Coroutine",
    "Dict",
    "Final",
    "FrozenSet",
    "Generator",
    "Generic",
    "Iterable",
    "Iterator",
    "List",
    "Literal",
    "Mapping",
    "MutableMapping",
    "MutableSequence",
    "MutableSet",
    "Optional",
    "Sequence",
    "Set",
    "Tuple",
    "Type",
    "Union",
    "dict",
    "frozenset",
    "list",
    "set",
    "tuple",
    "type",
}


@dataclass(frozen=True)
class SourceAnalysis:
    module: ModuleType
    entry_point: Function
    wrapped: bool

    def close(self) -> None:
        release_compilation(self.entry_point)

    def __enter__(self) -> SourceAnalysis:
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

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


def is_js_module_annotation(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.Name) and annotation.id == "JS":
        return True
    if not isinstance(annotation, ast.Subscript):
        return False
    if isinstance(annotation.value, ast.Name) and annotation.value.id == "JS":
        return True
    if isinstance(annotation.value, ast.Name) and annotation.value.id == "Final":
        return is_js_module_annotation(annotation.slice)
    if isinstance(annotation.value, ast.Name) and annotation.value.id == "Annotated":
        values = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else []
        return any(isinstance(value, ast.Name) and value.id == "js" for value in values[1:])
    return False


def is_type_alias_declaration(node: ast.stmt) -> bool:
    if isinstance(node, ast.TypeAlias):
        return True
    if isinstance(node, ast.AnnAssign):
        annotation = node.annotation
        return (
            isinstance(annotation, ast.Name) and annotation.id == "TypeAlias"
        ) or (
            isinstance(annotation, ast.Attribute)
            and annotation.attr == "TypeAlias"
        )
    if not (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Subscript)
    ):
        return False
    value = node.value.value
    if isinstance(value, ast.Name):
        return value.id in TYPE_ALIAS_CONTAINERS
    return isinstance(value, ast.Attribute) and value.attr in TYPE_ALIAS_CONTAINERS


def create_module(
    source: str,
    filename: str = "_pyjs_source_.py",
    module_name: str | None = None,
    *,
    display_source: str | None = None,
    simple_wrapper: bool = False,
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
    module.__pyjs_source__ = display_source if display_source is not None else source
    module.__pyjs_simple_wrapper__ = simple_wrapper
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


def wrap_source(source: str) -> tuple[str, bool]:
    source = textwrap.dedent(source)
    module = ast.parse(source)
    declaration_types = (
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )
    declarations = [
        node
        for node in module.body
        if isinstance(node, declaration_types)
        or is_type_alias_declaration(node)
        or (
            isinstance(node, ast.AnnAssign)
            and is_js_module_annotation(node.annotation)
        )
    ]
    statements = [node for node in module.body if node not in declarations]
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
        return ast.unparse(ast.fix_missing_locations(module)) + "\n", False

    body = textwrap.indent(source, "    ")
    if not body.strip():
        body = "    pass\n"
    elif not body.endswith("\n"):
        body += "\n"
    return f"def main():\n{body}", True


def _prepare_source(
    source: str,
    filename: str,
    wrap: bool | None,
) -> tuple[str, bool, str, bool]:
    source = textwrap.dedent(source)
    if wrap is None:
        wrap = not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
            for node in ast.parse(source, filename).body
        )
    if not wrap:
        return source, False, source, False
    wrapped_source, simple_wrapper = wrap_source(source)
    display_source = source if simple_wrapper else wrapped_source
    return wrapped_source, True, display_source, simple_wrapper


def analyze_source(
    source: str,
    *,
    filename: str = "_pyjs_source_.py",
    module_name: str | None = None,
    wrap: bool | None = None,
    extensions: tuple[CompilationExtension, ...] = (),
) -> SourceAnalysis:
    original_source = textwrap.dedent(source)
    source, wrapped, display_source, simple_wrapper = _prepare_source(
        source,
        filename,
        wrap,
    )
    module = create_module(
        source,
        filename,
        module_name,
        display_source=display_source,
        simple_wrapper=simple_wrapper,
    )
    module.__pyjs_original_source__ = original_source
    entry = module.main
    entry.__js__ = True
    entry_point, _ = analyze_module(module, extensions=extensions)
    entry_point.visited.add(entry_point)
    entry_point.compilation_objects.add(entry_point)
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
    original_source = textwrap.dedent(source)
    source, wrapped, display_source, simple_wrapper = _prepare_source(
        source,
        filename,
        wrap,
    )
    module = create_module(
        source,
        filename,
        module_name,
        display_source=display_source,
        simple_wrapper=simple_wrapper,
    )
    module.__pyjs_original_source__ = original_source
    module.main.__js__ = True
    package, source_maps, entry_point, css = prepare_bundle_with_source_maps(
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
