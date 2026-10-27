import keyword
import textwrap
from _ast_unparse import Unparser as _Unparser
from _ast_unparse import _Precedence
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass

from pyjs.analysis.analyzer import *
from pyjs.python import (
    _dict,
    _set,
    _str,
    _typed_dict,
    abstract_iterable,
    dynamic_iterable_source,
    is_int64_format,
    iterable_source,
    normalize_numeric_expression,
)
from pyjs.tooling.npm import collect_npm_imports, module_npm_imports
from pyjs.web.dom import Element as DOMElement
from pyjs.web.domx import ContextProxy, CustomElement, ProxyElement

from .sourcemap import (
    GeneratedScope,
    SourceMap,
    SourceMapping,
    SourceScope,
    TranspiledJavaScript,
    utf16_length,
)
from .utils import TailwindCSS

BUILTIN_EXCEPTION_NAMES = {
    "Exception": "Error",
    "TypeError": "TypeError",
    "ValueError": "RangeError",
}

JAVASCRIPT_RESERVED_IDENTIFIERS = {
    "arguments",
    "await",
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "debugger",
    "default",
    "delete",
    "do",
    "else",
    "enum",
    "eval",
    "export",
    "extends",
    "false",
    "finally",
    "for",
    "function",
    "if",
    "implements",
    "import",
    "in",
    "instanceof",
    "interface",
    "let",
    "new",
    "null",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "static",
    "super",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "typeof",
    "var",
    "void",
    "while",
    "with",
    "yield",
}

JS_MAX_SAFE_INTEGER = 2**53 - 1


def javascript_constant_integer(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant):
        return int(node.value) if type(node.value) in (bool, int) else None
    if isinstance(node, ast.UnaryOp):
        value = javascript_constant_integer(node.operand)
        if value is None:
            return None
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Invert):
            return ~value
        return None
    if not isinstance(node, ast.BinOp):
        return None
    left = javascript_constant_integer(node.left)
    right = javascript_constant_integer(node.right)
    if left is None or right is None:
        return None
    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        return left * right
    if isinstance(node.op, ast.FloorDiv) and right:
        return left // right
    if isinstance(node.op, ast.Mod) and right:
        return left % right
    if isinstance(node.op, ast.Pow) and right >= 0:
        if abs(left) > 1 and right > 53:
            return JS_MAX_SAFE_INTEGER + 1
        return left**right
    if isinstance(node.op, ast.BitAnd):
        return left & right
    if isinstance(node.op, ast.BitOr):
        return left | right
    if isinstance(node.op, ast.BitXor):
        return left ^ right
    if isinstance(node.op, ast.LShift) and right >= 0:
        if left != 0 and right > 53:
            return JS_MAX_SAFE_INTEGER + 1
        return left << right
    if isinstance(node.op, ast.RShift) and right >= 0:
        return left >> right
    return None


def javascript_identifier(name: str) -> str:
    if name in JAVASCRIPT_RESERVED_IDENTIFIERS:
        return f"$${name}"
    return name


def transpile_module(
    module,
    importer=None,
    exporter=None,
    *,
    include_object=should_include,
    reference_object=should_include,
    same_module_imports=(),
    include_hydration=lambda _func: False,
    include_inline_dependency=None,
):
    return Transpiler(
        module,
        importer,
        exporter,
        include_object=include_object,
        reference_object=reference_object,
        same_module_imports=same_module_imports,
        include_hydration=include_hydration,
        include_inline_dependency=include_inline_dependency,
    ).visit(module.node)


def transpile_module_with_source_map(
    module,
    importer=None,
    exporter=None,
    *,
    include_object=should_include,
    reference_object=should_include,
    same_module_imports=(),
    include_hydration=lambda _func: False,
    include_inline_dependency=None,
):
    transpiler = Transpiler(
        module,
        importer,
        exporter,
        source_maps=True,
        include_object=include_object,
        reference_object=reference_object,
        same_module_imports=same_module_imports,
        include_hydration=include_hydration,
        include_inline_dependency=include_inline_dependency,
    )
    javascript = transpiler.visit(module.node)
    npm_imports = module_npm_imports(module.name) if javascript else ()
    return TranspiledJavaScript(javascript, transpiler.source_map, npm_imports)


def _module_output_nodes(module, include_object=should_include):
    included_nodes = [
        node
        for node in module.node.body
        if include_object(node.obj) and node.obj.container.name == module.name
    ]
    post_definition_classes = {
        node.obj
        for node in module.node.body
        if isinstance(node.obj, Class)
        and not include_object(node.obj)
        and any(include_object(member) for member in node.obj._self.attrs.values())
        and js_metadata(node.obj.py_cls, "post_definition_source")
    }
    return included_nodes, post_definition_classes


def generate_css(tailwind_classes: set):
    return TailwindCSS().get_css(tailwind_classes)


@dataclass(frozen=True)
class BundleTarget:
    name: str
    entry_point: Callable[..., object]
    parent: str | None = None


@dataclass(frozen=True)
class StandaloneBundleTarget:
    name: str
    entry_point: Callable[..., object]
    additional_entry_points: tuple[Callable[..., object], ...] = ()
    include_css: bool = True


def _defining_module(obj) -> Module:
    while not isinstance(obj, Module):
        obj = obj.container
    return obj


def prepare_bundle(
    entry_point_py_func,
    importer=None,
    exporter=None,
    include_main=False,
    extensions: tuple[CompilationExtension, ...] = (),
    include_css=True,
    additional_entry_points: tuple[callable, ...] = (),
):
    package, _, entry_point, css = _prepare_bundle(
        entry_point_py_func,
        importer,
        exporter,
        include_main,
        extensions,
        include_css,
        additional_entry_points,
        include_source_maps=False,
    )
    return package, entry_point, css


def prepare_bundle_with_source_maps(
    entry_point_py_func,
    importer=None,
    exporter=None,
    include_main=False,
    extensions: tuple[CompilationExtension, ...] = (),
    include_css=True,
    additional_entry_points: tuple[callable, ...] = (),
):
    return _prepare_bundle(
        entry_point_py_func,
        importer,
        exporter,
        include_main,
        extensions,
        include_css,
        additional_entry_points,
        include_source_maps=True,
    )


def _prepare_bundle(
    entry_point_py_func,
    importer,
    exporter,
    include_main,
    extensions,
    include_css,
    additional_entry_points,
    *,
    include_source_maps,
):
    entry_point, tailwind_classes = from_entry_point(
        entry_point_py_func,
        extensions,
        additional_entry_points,
    )
    try:
        if include_main:
            entry_point.visited.add(entry_point)
            entry_point.compilation_objects.add(entry_point)
        module = entry_point.container
        package = {}
        source_maps = {}
        css = ""
        if include_css and tailwind_classes:
            css = generate_css(tailwind_classes)
        for module_name, module_obj in module.container.items():
            if include_source_maps:
                generated = transpile_module_with_source_map(
                    module_obj,
                    importer,
                    exporter,
                )
                package[module_name] = generated.javascript
                source_maps[module_name] = generated.source_map
            else:
                package[module_name] = transpile_module(
                    module_obj,
                    importer,
                    exporter,
                )
        return package, source_maps, entry_point, css
    except BaseException:
        release_compilation(entry_point)
        raise


def bundle_import(module, names):
    if not names:
        return f"__import_js__.defer({module!r});"
    imported_names = ", ".join(
        source if source == local else f"{source}: {local}" for source, local in names
    )
    return f"const {{{imported_names}}} = __import_js__({module!r});"


def bundle(
    entry_point_py_func,
    include_main=False,
    extensions: tuple[CompilationExtension, ...] = (),
    include_css=True,
    *,
    additional_entry_points: tuple[callable, ...] = (),
    call_main: bool | None = None,
    expose_entry: bool = False,
):
    if call_main is None:
        call_main = include_main
    if call_main and not include_main:
        raise ValueError("call_main=True requires include_main=True")
    package, entry_point, css = prepare_bundle(
        entry_point_py_func,
        bundle_import,
        lambda name: f"__export_js__.{name} = {name};",
        include_main=include_main,
        extensions=extensions,
        include_css=include_css,
        additional_entry_points=additional_entry_points,
    )
    try:
        source = _write_bundle(
            package, entry_point, call_main=call_main, expose_entry=expose_entry
        )
        return source, css
    finally:
        release_compilation(entry_point)


def bundle_with_source_map(
    entry_point_py_func,
    include_main=False,
    extensions: tuple[CompilationExtension, ...] = (),
    include_css=True,
    *,
    additional_entry_points: tuple[callable, ...] = (),
    call_main: bool | None = None,
    expose_entry: bool = False,
    filename: str = "bundle.js",
):
    if call_main is None:
        call_main = include_main
    if call_main and not include_main:
        raise ValueError("call_main=True requires include_main=True")
    package, source_maps, entry_point, css = prepare_bundle_with_source_maps(
        entry_point_py_func,
        bundle_import,
        lambda name: f"__export_js__.{name} = {name};",
        include_main=include_main,
        extensions=extensions,
        include_css=include_css,
        additional_entry_points=additional_entry_points,
    )
    try:
        generated = _write_bundle(
            package,
            entry_point,
            call_main=call_main,
            expose_entry=expose_entry,
            source_maps=source_maps,
            filename=filename,
        )
        assert isinstance(generated, TranspiledJavaScript)
        return generated, css
    finally:
        release_compilation(entry_point)


def bundle_standalone_with_source_maps(
    targets: tuple[StandaloneBundleTarget, ...],
    *,
    extensions: tuple[CompilationExtension, ...] = (),
    filename_suffix: str = ".js",
) -> dict[str, tuple[TranspiledJavaScript, str]]:
    """Compile independent bundles through one shared analysis pass."""
    if not targets:
        raise ValueError("At least one standalone bundle target is required.")
    if "/" in filename_suffix or "\\" in filename_suffix:
        raise ValueError("The bundle filename suffix cannot contain a path.")
    names = {target.name for target in targets}
    if len(names) != len(targets):
        raise ValueError("Standalone bundle target names must be unique.")

    functions = tuple(
        function
        for target in targets
        for function in (target.entry_point, *target.additional_entry_points)
    )
    entry_point, _tailwind_classes = from_entry_point(
        functions[0],
        extensions,
        additional_entry_points=functions[1:],
    )
    try:
        analyzed = iter(entry_point.compilation_entry_points)
        roots_by_target = {
            target: tuple(
                next(analyzed)
                for _function in (
                    target.entry_point,
                    *target.additional_entry_points,
                )
            )
            for target in targets
        }
        package = entry_point.container.container
        generated = {}
        for target, roots in roots_by_target.items():
            root_set = set(roots)
            active_modules = {
                _defining_module(obj)
                for root in roots
                for obj in root.compilation_objects
            }

            def include_object(
                obj,
                root_set=root_set,
                active_modules=active_modules,
            ):
                return should_include(obj) and (
                    bool(root_set.intersection(obj.visited))
                    or (
                        has_keep_decorator(obj.py_obj)
                        and _defining_module(obj) in active_modules
                    )
                )

            javascript = {}
            source_maps = {}
            for module_name, module_obj in package.items():
                included_nodes, post_definition_classes = _module_output_nodes(
                    module_obj,
                    include_object,
                )
                if not included_nodes and not post_definition_classes:
                    javascript[module_name] = ""
                    source_maps[module_name] = SourceMap()
                    continue

                def include_inline_dependency(
                    dependency,
                    module_obj=module_obj,
                    root_set=root_set,
                ):
                    roots = module_obj.inline_dependency_roots.get(
                        dependency,
                        (),
                    )
                    return bool(root_set.intersection(roots))

                transpiled = transpile_module_with_source_map(
                    module_obj,
                    bundle_import,
                    lambda name: f"__export_js__.{name} = {name};",
                    include_object=include_object,
                    reference_object=include_object,
                    include_inline_dependency=include_inline_dependency,
                )
                javascript[module_name] = transpiled.javascript
                source_maps[module_name] = transpiled.source_map

            filename = f"{target.name}{filename_suffix}"
            source = _write_bundle(
                javascript,
                roots[0],
                call_main=False,
                expose_entry=False,
                source_maps=source_maps,
                filename=filename,
            )
            assert isinstance(source, TranspiledJavaScript)
            tailwind_classes = set().union(*(root.tailwind_classes for root in roots))
            css = (
                generate_css(tailwind_classes)
                if target.include_css and tailwind_classes
                else ""
            )
            generated[target.name] = source, css
        return generated
    finally:
        release_compilation(entry_point)


def bundle_targets_with_source_maps(
    targets: tuple[BundleTarget, ...],
    *,
    extensions: tuple[CompilationExtension, ...] = (),
    filename_suffix: str = ".js",
) -> tuple[dict[str, TranspiledJavaScript], str]:
    """Compile a static application/section/page hierarchy into ES modules."""
    if not targets:
        raise ValueError("At least one bundle target is required.")
    if "/" in filename_suffix or "\\" in filename_suffix:
        raise ValueError("The bundle filename suffix cannot contain a path.")
    names = {target.name for target in targets}
    if len(names) != len(targets):
        raise ValueError("Bundle target names must be unique.")
    roots = [target for target in targets if target.parent is None]
    if len(roots) != 1 or roots[0] is not targets[0]:
        raise ValueError("The first bundle target must be the only root target.")
    by_name = {target.name: target for target in targets}
    for target in targets[1:]:
        if target.parent not in by_name:
            raise ValueError(
                f"Bundle target {target.name!r} has unknown parent {target.parent!r}."
            )

    def path(target: BundleTarget) -> tuple[str, ...]:
        result = []
        current = target
        seen = set()
        while current is not None:
            if current.name in seen:
                raise ValueError("Bundle target parents must not contain a cycle.")
            seen.add(current.name)
            result.append(current.name)
            current = by_name.get(current.parent)
        return tuple(reversed(result))

    target_paths = {target.name: path(target) for target in targets}
    root_target = targets[0]
    entry_point, tailwind_classes = from_entry_point(
        root_target.entry_point,
        extensions,
        render_entry_points=tuple(target.entry_point for target in targets[1:]),
        render_primary=True,
    )
    try:
        promote_atomic_class_reachability(entry_point)
        analyzed_roots = entry_point.compilation_entry_points
        if len(analyzed_roots) != len(targets):
            raise AssertionError("Analyzer did not preserve every bundle target.")
        paths_by_root = {
            root: target_paths[target.name]
            for root, target in zip(analyzed_roots, targets, strict=True)
        }

        def common_path(reached) -> tuple[str, ...] | None:
            if not reached:
                return None
            common = list(reached[0])
            for reached_path in reached[1:]:
                prefix = []
                for left, right in zip(common, reached_path, strict=False):
                    if left != right:
                        break
                    prefix.append(left)
                common = prefix
                if not common:
                    raise AssertionError("Bundle targets do not share their root.")
            return tuple(common)

        def placement(obj) -> tuple[str, ...] | None:
            reached = [
                paths_by_root[root] for root in obj.visited if root in paths_by_root
            ]
            if not reached:
                if has_keep_decorator(obj.py_obj):
                    return target_paths[root_target.name]
                return None
            return common_path(reached)

        def hydration_placement(func) -> tuple[str, ...] | None:
            return common_path(
                [
                    paths_by_root[root]
                    for root in func.hydrate_visited
                    if root in paths_by_root
                ]
            )

        generated = {}
        package = entry_point.container.container
        for target, analyzed_root in zip(targets, analyzed_roots, strict=True):
            target_path = target_paths[target.name]

            def include_object(obj, target_path=target_path):
                return should_include(obj) and placement(obj) == target_path

            def reference_object(obj, target_path=target_path):
                obj_path = placement(obj)
                return (
                    should_include(obj)
                    and obj_path is not None
                    and target_path[: len(obj_path)] == obj_path
                )

            javascript = {}
            source_maps = {}
            for module_name, module_obj in package.items():
                included_nodes, post_definition_classes = _module_output_nodes(
                    module_obj,
                    include_object,
                )
                referenced_objects = {
                    child.obj
                    for node in included_nodes
                    for child in ast.walk(node)
                    if isinstance(getattr(child, "obj", None), Object)
                    and child.obj.container is module_obj
                }
                referenced_objects.update(post_definition_classes)
                referenced_objects.update(
                    dependency
                    for dependency in module_obj.inline_dependencies
                    if reference_object(dependency)
                )
                if not included_nodes and not post_definition_classes:
                    javascript[module_name] = ""
                    source_maps[module_name] = SourceMap()
                    continue
                imported_names = {
                    local_name
                    for imported_values in module_obj.imported.values()
                    for _obj, local_name in imported_values
                }
                same_module_imports = tuple(
                    node.obj
                    for node in module_obj.node.body
                    if isinstance(
                        node,
                        (
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                            ast.ClassDef,
                            ast.Assign,
                            ast.AnnAssign,
                        ),
                    )
                    and node.obj in referenced_objects
                    and node.obj.name not in imported_names
                    and placement(node.obj) is not None
                    and placement(node.obj) != target_path
                    and target_path[: len(placement(node.obj))] == placement(node.obj)
                )
                transpiled = transpile_module_with_source_map(
                    module_obj,
                    bundle_import,
                    lambda name: f"__export_js__.{name} = {name};",
                    include_object=include_object,
                    reference_object=reference_object,
                    same_module_imports=same_module_imports,
                    include_hydration=lambda func, target_path=target_path: (
                        hydration_placement(func) == target_path
                    ),
                )
                javascript[module_name] = transpiled.javascript
                source_maps[module_name] = transpiled.source_map

            parent_filename = None
            if target.parent is not None:
                parent_filename = f"{target.parent}{filename_suffix}"
            generated[target.name] = _write_bundle(
                javascript,
                analyzed_root,
                call_main=False,
                expose_entry=False,
                source_maps=source_maps,
                filename=f"{target.name}{filename_suffix}",
                fragmented=True,
                parent_filename=parent_filename,
            )
        css = generate_css(tailwind_classes) if tailwind_classes else ""
        return generated, css
    finally:
        release_compilation(entry_point)


def _write_bundle(
    package,
    entry_point,
    *,
    call_main,
    expose_entry,
    source_maps=None,
    filename=None,
    fragmented=False,
    parent_filename=None,
):
    source = []
    generated_line = 0
    generated_column = 0
    combined_mappings = [] if source_maps is not None else None
    combined_scopes = [] if source_maps is not None else None
    combined_generated_scopes = [] if source_maps is not None else None

    if source_maps is None:
        w = source.append
    else:

        def w(value):
            nonlocal generated_line, generated_column
            source.append(value)
            lines = value.split("\n")
            if len(lines) == 1:
                generated_column += utf16_length(value)
            else:
                generated_line += len(lines) - 1
                generated_column = utf16_length(lines[-1])

    npm_imports = collect_npm_imports(
        module_name
        for module_name, module_javascript in package.items()
        if module_javascript
    )
    if npm_imports:
        names = ", ".join(value.alias for value in npm_imports)
        w(f"import {{ {names} }} from './pyjs-vendor.js';\n")

    if parent_filename is not None:
        w(f"import {{ define, importModule }} from {f'./{parent_filename}'!r};\n")
    elif fragmented:
        w(
            textwrap.dedent("""\
        const modules = new Map();
        const moduleCache = new Map();
        const define = (name, moduleFactory) => {
          if (!modules.has(name)) {
            modules.set(name, []);
          }
          modules.get(name).push(moduleFactory);
        };
        const runModuleFactories = (name, module) => {
          const factories = modules.get(name);
          while (module.factoryIndex < factories.length) {
            const moduleFactory = factories[module.factoryIndex++];
            moduleFactory(module.exports, module.importer);
          }
          for (const dependency of module.deferredImports) {
            module.deferredImports.delete(dependency);
            importModule(dependency);
          }
        };
        const importModule = (name) => {
          if (moduleCache.has(name)) {
            const module = moduleCache.get(name);
            runModuleFactories(name, module);
            return module.exports;
          }
          if (!modules.has(name)) {
            throw new Error(`Module '${name}' does not exist.`);
          }
          const module = {
            exports: {},
            factoryIndex: 0,
            deferredImports: new Set(),
          };
          module.importer = (dependency) => importModule(dependency);
          module.importer.defer = (dependency) => {
            module.deferredImports.add(dependency);
          };
          moduleCache.set(name, module);
          runModuleFactories(name, module);
          return module.exports;
        };
        const __pyjsAssert__ = (condition, message, AssertionError) => {
          if (condition) {
            return;
          }
          throw new AssertionError(message === undefined ? "" : String(message()));
        };
        """)
        )
    else:
        w(
            textwrap.dedent("""\
    const modules = new Map();
    const define = (name, moduleFactory) => {
      modules.set(name, moduleFactory);
    };
    const moduleCache = new Map();
    const importModule = (name) => {
      if (moduleCache.has(name)) {
        return moduleCache.get(name).exports;
      }
      if (!modules.has(name)) {
        throw new Error(`Module '${name}' does not exist.`);
      }
      const moduleFactory = modules.get(name);
      const module = {exports: {}, deferredImports: new Set()};
      const importer = (dependency) => importModule(dependency);
      importer.defer = (dependency) => {
        module.deferredImports.add(dependency);
      };
      moduleCache.set(name, module);
      moduleFactory(module.exports, importer);
      for (const dependency of module.deferredImports) {
        importModule(dependency);
      }
      return module.exports;
    };
    const __pyjsAssert__ = (condition, message, AssertionError) => {
      if (condition) {
        return;
      }
      throw new AssertionError(message === undefined ? "" : String(message()));
    };
    """)
        )
    for module_name, module_js in package.items():
        if module_js:
            w(f"define({repr(module_name)}, function (__export_js__, __import_js__) {{\n")
            if source_maps is not None:
                assert combined_mappings is not None
                combined_mappings.extend(
                    mapping.shifted(generated_line, generated_column)
                    for mapping in source_maps[module_name].mappings
                )
                assert combined_scopes is not None
                assert combined_generated_scopes is not None
                combined_scopes.extend(source_maps[module_name].scopes)
                combined_generated_scopes.extend(
                    scope.shifted(generated_line, generated_column)
                    for scope in source_maps[module_name].generated_scopes
                )
            w(module_js)
            w("\n});\n")
    if fragmented:
        for module_name, module_js in package.items():
            if module_js:
                w(f"importModule({module_name!r});\n")
    else:
        if expose_entry:
            w("const __pyjsEntry__ = ")
        w(f"importModule({repr(entry_point.container.name)})")
        if call_main:
            w(f".{javascript_identifier(entry_point.name)}()")
        w(";\n")
    if fragmented:
        w("export { define, importModule };\n")
    javascript = "".join(source)
    if source_maps is not None:
        assert combined_mappings is not None
        return TranspiledJavaScript(
            javascript,
            SourceMap(
                tuple(combined_mappings),
                filename,
                tuple(dict.fromkeys(combined_scopes)),
                tuple(combined_generated_scopes),
            ),
            npm_imports,
        )
    return javascript


class Transpiler(_Unparser):
    def __init__(
        self,
        entry_point: Function,
        importer=None,
        exporter=None,
        *,
        source_maps=False,
        include_object=should_include,
        reference_object=should_include,
        same_module_imports=(),
        include_hydration=lambda _func: False,
        include_inline_dependency=None,
    ):
        super().__init__()
        self.entry_point = entry_point
        self.importer = importer
        self.exporter = exporter
        self.temporary_index = 0
        self.source_maps = source_maps
        self.include_object = include_object
        self.reference_object = reference_object
        self.same_module_imports = tuple(same_module_imports)
        self.include_hydration = include_hydration
        self.include_inline_dependency = include_inline_dependency or reference_object
        self._generated_line = 0
        self._generated_column = 0
        self._mapping_fragment = None
        self._mapping_node = None
        self._source_mappings = []
        self._source_scopes = []
        self._generated_scopes = []
        self.current_function = None
        self.local_declarations = None
        self.exception_stack = []
        self.loop_else_stack = []
        self.direct_call_target = None
        self.comparison_bindings = {}
        self.awaited_comparisons = {}

    @contextmanager
    def caught_exception(self, name):
        self.exception_stack.append(name)
        try:
            yield
        finally:
            self.exception_stack.pop()

    @property
    def source_map(self) -> SourceMap:
        return SourceMap(
            tuple(self._source_mappings),
            scopes=tuple(self._source_scopes),
            generated_scopes=tuple(self._generated_scopes),
        )

    def visit(self, node):
        self._generated_line = 0
        self._generated_column = 0
        self._mapping_fragment = None
        self._mapping_node = None
        self._source_mappings = []
        self._source_scopes = []
        self._generated_scopes = []
        return super().visit(node)

    def traverse(self, node):
        if isinstance(node, ast.expr):
            self.reject_unsafe_constant_integer(node)
        if not self.source_maps:
            return super().traverse(node)
        if isinstance(node, list):
            for item in node:
                self.traverse(item)
            return

        previous_node = self._mapping_node
        previous_fragment = self._mapping_fragment
        self._mapping_node = node
        obj = getattr(node, "obj", None)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(
            obj,
            Function,
        ):
            self._mapping_fragment = obj.source_fragment
        try:
            super().traverse(node)
        finally:
            self._mapping_node = previous_node
            self._mapping_fragment = previous_fragment

    def write(self, *text):
        super().write(*text)
        if not self.source_maps:
            return
        for part in text:
            lines = part.split("\n")
            if len(lines) == 1:
                self._generated_column += utf16_length(part)
                continue
            self._generated_line += len(lines) - 1
            self._generated_column = utf16_length(lines[-1])

    def fill(self, text="", *, allow_semicolon=True):
        if not self.source_maps:
            return super().fill(text, allow_semicolon=allow_semicolon)
        if self._in_interactive and not self._indent and allow_semicolon:
            self.maybe_semicolon()
            indentation = ""
        else:
            self.maybe_newline()
            indentation = "    " * self._indent
        self.record_source_mapping(self._generated_column + len(indentation))
        self.write(indentation + text)

    def record_source_mapping(self, generated_column: int) -> None:
        node = self._mapping_node
        fragment = self._mapping_fragment
        if fragment is None or not isinstance(node, ast.AST):
            return
        if not hasattr(node, "lineno"):
            return
        position = fragment.span(node).start_position
        source = fragment.source
        original_prefix = (
            source.line_text(position.line + 1)
            .encode("utf-8")[: position.column]
            .decode("utf-8", errors="replace")
        )
        original_column = utf16_length(original_prefix)
        self._source_mappings.append(
            SourceMapping(
                self._generated_line,
                generated_column,
                source,
                position.line,
                original_column,
                getattr(node, "name", None),
            )
        )

    def temporary_name(self, prefix: str) -> str:
        name = f"${prefix}{self.temporary_index}"
        self.temporary_index += 1
        return name

    def fail(self, node, code, message, *, help=None):
        module = _defining_module(self.entry_point)
        caller = self.current_function
        fragment = caller.source_fragment if caller is not None else None
        if fragment is None:
            fragment = module.context.sources.fragment_for(module.py_module)
        module.context.error(
            fragment,
            node,
            code,
            message,
            help=help,
        )

    def reject_unsafe_constant_integer(self, node: ast.expr):
        python_node = getattr(node, "python_node", node)
        value = javascript_constant_integer(python_node)
        if value is None or abs(value) <= JS_MAX_SAFE_INTEGER:
            return
        self.fail(
            node,
            DiagnosticCode.UNSUPPORTED_SYNTAX,
            "constant integer expression exceeds JavaScript's safe integer range",
            help=(
                "Keep statically known integers between "
                f"{-JS_MAX_SAFE_INTEGER} and {JS_MAX_SAFE_INTEGER}."
            ),
        )

    @staticmethod
    def builtin_exception_name(value) -> str | None:
        if not isinstance(value, Class) or not value.container.scope.is_builtins:
            return None
        return BUILTIN_EXCEPTION_NAMES.get(value.name)

    def isolated_visit(self, node, precedence=None):
        transpiler = Transpiler(self.entry_point)
        transpiler.current_function = self.current_function
        # Inline generators need an isolated output buffer, not a new lexical
        # scope. Nested comparisons still use the caller's allocated locals.
        transpiler.comparison_bindings = self.comparison_bindings
        transpiler.awaited_comparisons = self.awaited_comparisons
        transpiler.temporary_index = self.temporary_index
        if isinstance(node, (ast.IfExp, ast.JoinedStr, ast.Await)):
            precedence = _Precedence.ATOM
        if precedence is not None:
            transpiler.set_precedence(precedence, node)
        try:
            return transpiler.visit(node)
        finally:
            self.temporary_index = transpiler.temporary_index

    @staticmethod
    def operator_precedence(node):
        if isinstance(node.operator, ast.cmpop):
            operand_precedence = _Precedence.CMP.next()
            return _Precedence.CMP, operand_precedence, operand_precedence
        if isinstance(node.operator, ast.operator):
            operator = _Unparser.binop[type(node.operator).__name__]
            precedence = _Unparser.binop_precedence[operator]
            if operator in _Unparser.binop_rassoc:
                left_precedence, right_precedence = precedence.next(), precedence
            else:
                left_precedence, right_precedence = precedence, precedence.next()
            if node.reverse:
                left_precedence, right_precedence = right_precedence, left_precedence
            return precedence, left_precedence, right_precedence
        return None

    @contextmanager
    def block(self, *, extra=None):
        self.write(" {")
        self._indent += 1
        yield
        self._indent -= 1
        self.fill("}")

    def visit_ModuleDef(self, node: ModuleDef):
        module = node.obj
        has_output = any(
            self.include_object(value.obj) and value.obj.container.name == module.name
            for value in node.body
        )
        if self.importer is None and has_output:
            npm_imports = module_npm_imports(module.name)
            if npm_imports:
                names = ", ".join(value.alias for value in npm_imports)
                self.fill(f"import {{ {names} }} from './pyjs-vendor.js';")
        side_effect_imports = {
            dependency.container.name
            for dependency in module.side_effect_dependencies
            if self.reference_object(dependency)
        }
        for imported_module in sorted(side_effect_imports):
            if self.importer is not None:
                self.fill(self.importer(imported_module, ()))
            else:
                self.fill(f"import './{imported_module}.js';")
        if self.same_module_imports:
            imported_names = [
                (
                    javascript_identifier(obj.name),
                    javascript_identifier(obj.name),
                )
                for obj in self.same_module_imports
            ]
            self.fill(self.importer(module.name, imported_names))
        for imported_module, imported_values in module.imported.items():
            imported_names = []
            for obj, local_name in imported_values:
                if module.inline_dependencies.get(
                    obj
                ) == local_name and not self.include_inline_dependency(obj):
                    continue
                if isinstance(obj, GenericClass):
                    imported_names.extend(
                        (
                            javascript_identifier(concrete.name),
                            javascript_identifier(concrete.name),
                        )
                        for concrete in obj.concrete_classes.values()
                        if self.reference_object(concrete)
                    )
                elif not isinstance(obj, TypedDictClass) and self.reference_object(obj):
                    imported_names.append(
                        (
                            javascript_identifier(obj.name),
                            javascript_identifier(local_name),
                        )
                    )
            if imported_names:
                if self.importer is not None:
                    self.fill(self.importer(imported_module, imported_names))
                else:
                    names = ", ".join(
                        source if source == local else f"{source} as {local}"
                        for source, local in imported_names
                    )
                    self.fill(f"import {{ {names} }} from './{imported_module}.js';")
        for dependency, alias in module.inline_dependencies.items():
            if (
                dependency.container is module
                and self.reference_object(dependency)
                and self.include_inline_dependency(dependency)
            ):
                self.fill(f"const {alias} = {javascript_identifier(dependency.name)};")
        for n in node.body:
            if self.include_object(n.obj) and n.obj.container.name == module.name:
                self.traverse(n)
        for n in node.body:
            if not isinstance(n.obj, Class) or self.include_object(n.obj):
                continue
            post_definition = js_metadata(
                n.obj.py_cls,
                "post_definition_source",
            )
            if post_definition is None:
                continue
            included_members = {
                name
                for name, member in n.obj._self.attrs.items()
                if self.include_object(member)
            }
            if included_members:
                self.fill(
                    post_definition(
                        included_members,
                    )
                )

    def visit_ClassDef(self, node):
        constructor = node.obj.find_attrs("__init__", search_bases=False)
        if (
            constructor is not None
            and constructor.inline_decorator is not None
            and not is_inline_for(node.obj.py_cls, "js")
        ):
            self.fail(
                node,
                DiagnosticCode.UNSUPPORTED_SYNTAX,
                f"Class {node.name!r} has an inline __init__ method",
                help=(
                    "Move @js.inline to the class when construction should "
                    "produce an inline value, or use a function for an inline "
                    "value factory."
                ),
            )
        self.maybe_newline()
        export = "export " if self.exporter is None else ""
        class_name = javascript_identifier(node.name)
        self.fill(f"{export}class {class_name}")
        if node.bases:
            assert len(node.bases) == 1
            self.write(" extends ")
            if node.obj.runtime_super_dependency is not None:
                self.traverse(node.bases[0])
            elif exception_name := self.builtin_exception_name(node.obj.super):
                self.write(exception_name)
            else:
                self.traverse(node.bases[0])
        with self.block():
            for member in node.body:
                if self.include_object(member.obj):
                    self.traverse(member)
            init = node.obj.init
            explicit_hydrate = node.obj.find_attrs(
                "_hydrate",
                search_bases=False,
            )
            if (
                init is not None
                and self.include_hydration(init)
                and not self.include_object(init)
                and not (
                    isinstance(explicit_hydrate, Function)
                    and self.include_object(explicit_hydrate)
                )
            ):
                self.generate_bind_method(init)
        if node.obj.client_defaults:
            self.fill(f"{class_name}.__pyjs_defaults__ = ")
            self.traverse(
                ast.Dict(
                    keys=[ast.Constant(value=name) for name in node.obj.client_defaults],
                    values=list(node.obj.client_defaults.values()),
                )
            )
            self.write(";")
        if node.obj.client_required:
            self.fill(f"{class_name}.__pyjs_required__ = ")
            self.traverse(
                ast.List(
                    elts=[ast.Constant(value=name) for name in node.obj.client_required],
                    ctx=ast.Load(),
                )
            )
            self.write(";")
        if node.obj.client_fields:
            self.fill(f"{class_name}.__pyjs_fields__ = new Map(")
            with self.delimit("[", "]"):
                for index, (name, value_type) in enumerate(
                    node.obj.client_fields.items()
                ):
                    if index:
                        self.write(", ")
                    with self.delimit("[", "]"):
                        self.traverse(ast.Constant(value=name))
                        self.write(", ")
                        self.write_client_field_descriptor(value_type)
            self.write(");")
        if node.obj.client_model_registry_required:
            model_key = f"{node.obj.container.name}.{node.obj.name}"
            self.fill(
                f"(globalThis.$pyjsModels ??= new Map()).set("
                f"{model_key!r}, {class_name});"
            )
        if post_definition := js_metadata(
            node.obj.py_cls,
            "post_definition_source",
        ):
            included_members = {
                name
                for name, member in node.obj._self.attrs.items()
                if self.include_object(member)
            }
            self.fill(post_definition(included_members))
        if self.exporter is not None:
            self.fill(self.exporter(class_name))

    def write_client_field_descriptor(self, value_type):
        self.traverse(py_to_ast(client_type_descriptor(value_type)))

    def visit_FunctionDef(self, node):
        previous = self.current_function
        previous_declarations = self.local_declarations
        self.current_function = node.obj
        self.local_declarations = set()
        try:
            self._function_helper(node, is_async=False)
        finally:
            self.current_function = previous
            self.local_declarations = previous_declarations

    def visit_AsyncFunctionDef(self, node):
        previous = self.current_function
        previous_declarations = self.local_declarations
        self.current_function = node.obj
        self.local_declarations = set()
        try:
            self._function_helper(node, is_async=True)
        finally:
            self.current_function = previous
            self.local_declarations = previous_declarations

    def visit_StaticCast(self, node):
        self.traverse(node.value)

    def visit_EvaluateOnce(self, node: EvaluateOnce):
        self.write("((")
        self.write(node.parameter)
        self.write(") => ")
        self.traverse(node.body)
        self.write(")(")
        self.traverse(node.value)
        self.write(")")

    def _function_helper(self, node, is_async):
        self.maybe_newline()
        func = node.obj
        assert not (func.is_generator and is_async)
        is_custom_element_init = (
            func.name == "__init__"
            and func.is_method
            and issubclass(func.cls.py_obj, (CustomElement, ProxyElement))
            and func.cls.py_obj != CustomElement
        )
        if is_custom_element_init:
            if is_async:
                raise NotImplementedError("custom element initialization cannot be async")
            def_str = "_create"
        elif node.name == "__init__":
            if is_async:
                raise NotImplementedError("constructors cannot be async")
            def_str = "constructor"
        elif func.is_method:
            if func.is_property:
                def_str = "get "
            elif func.is_property_setter:
                def_str = "set "
            else:
                def_str = ""
            if func.is_static:
                def_str = "static "
            if is_async:
                def_str += "async "
            if func.is_generator:
                def_str += "*"
            def_str += "[Symbol.iterator]" if node.name == "__iter__" else node.name
        else:
            if is_async:
                fill_suffix = "async function"
            elif func.is_generator:
                fill_suffix = "function*"
            else:
                fill_suffix = "function"
            if self.exporter is None and isinstance(func.container, Module):
                fill_suffix = "export " + fill_suffix
            def_str = fill_suffix + " " + javascript_identifier(node.name)
        self.fill(def_str)
        generated_start = (self._generated_line, 4 * self._indent)
        with self.delimit("(", ")"):
            self.traverse(node.args)
        with self.block():
            if func.has_source_decorator:
                func_src = func.get_predefined_source()
                func_lines = textwrap.dedent(func_src).splitlines()
                for line in func_lines:
                    if line:
                        self.fill(line)
            else:
                self.declare_awaited_comparison_locals(node.body)
                if node.args.kwarg is not None:
                    name = javascript_identifier(node.args.kwarg.arg)
                    rest_name = f"${name}"
                    self.fill(f"var {name} = new Map(Object.entries({rest_name}));")
                self.traverse(node.body)
                if is_custom_element_init:
                    self.fill("return this;")
        self.record_function_scope(func, node, generated_start)
        if is_custom_element_init and issubclass(func.cls.py_obj, CustomElement):
            self.generate_bind_method(func)
        if self.exporter is not None and isinstance(func.container, Module):
            self.fill(self.exporter(javascript_identifier(node.name)))

    def declare_awaited_comparison_locals(self, body):
        def walk(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return
            if isinstance(node, ChainedCompare) and any(isinstance(value, ast.Await) for value in ast.walk(node)):
                names = [self.temporary_name("compare") for _ in node.temporaries]
                self.awaited_comparisons[node] = names
                self.fill("var " + ", ".join(names) + ";")
            for child in ast.iter_child_nodes(node):
                walk(child)

        for statement in body:
            walk(statement)

    def record_function_scope(self, func, node, generated_start):
        if (
            not self.source_maps
            or func.source_fragment is None
            or func.has_synthetic_source
        ):
            return
        span = func.source_fragment.span(func.original_node)

        def original_position(position):
            prefix = span.source.line_text(position.line + 1).encode("utf-8")[
                : position.column
            ]
            column = utf16_length(prefix.decode("utf-8", errors="replace"))
            return position.line, column

        variables = []
        values = []
        if func.is_method and not func.is_staticmethod:
            name = "cls" if func.is_classmethod else "self"
            variables.append(name)
            values.append("this")
        arguments = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        for argument in arguments:
            if argument.arg not in variables:
                variables.append(argument.arg)
                values.append(javascript_identifier(argument.arg))
        for name in sorted(self.local_declarations or ()):
            if name not in variables:
                variables.append(name)
                values.append(javascript_identifier(name))
        source_scope = SourceScope(
            span.source,
            *original_position(span.start_position),
            *original_position(span.end_position),
            func.name,
            tuple(variables),
        )
        self._source_scopes.append(source_scope)
        self._generated_scopes.append(
            GeneratedScope(
                source_scope,
                *generated_start,
                self._generated_line,
                self._generated_column,
                tuple(values),
            )
        )

    def generate_bind_method(self, func):
        self.maybe_newline()
        self.fill("_hydrate()")
        with self.block():
            generator = HydrateGenerator(func, self)
            for line in func.body:
                generator.visit(line)

    def visit_arguments(self, node):
        first = True
        positional = [*node.posonlyargs, *node.args]
        required_count = len(positional) - len(node.defaults)
        for arg in positional[:required_count]:
            if first:
                first = False
            else:
                self.write(", ")
            self.traverse(arg)

        option_args = positional[required_count:] + node.kwonlyargs
        option_defaults = node.defaults + node.kw_defaults
        if option_args or node.kwarg is not None:
            if not first:
                self.write(", ")
            self.write("{ ")
            for index, (arg, default) in enumerate(
                zip(option_args, option_defaults, strict=True)
            ):
                if index:
                    self.write(", ")
                emitted_name = javascript_identifier(arg.arg)
                parameter_index = required_count + index
                property_name = (
                    f"${parameter_index}"
                    if parameter_index < len(node.posonlyargs)
                    else arg.arg
                )
                if emitted_name != property_name:
                    self.write(f"{property_name}: ")
                self.write(emitted_name)
                if default is not None:
                    self.write("=")
                    self.traverse(default)
            if node.kwarg is not None:
                if option_args:
                    self.write(", ")
                name = javascript_identifier(node.kwarg.arg)
                self.write(f"...${name}")
            self.write("} = {}")
            first = False

        if node.vararg:
            if not first:
                self.write(", ")
            self.write("...")
            self.write(javascript_identifier(node.vararg.arg))

    def visit_arg(self, node):
        self.write(javascript_identifier(node.arg))

    def visit_RuntimeFunctionReference(self, node: RuntimeFunctionReference):
        self.write(node.alias)
        if node.receiver is not None:
            self.write(".bind(null, ")
            self.traverse(node.receiver)
            self.write(")")

    def visit_BoundGetattr(self, node: BoundGetattr):
        self.write(f"((obj,fallback)=>obj.{node.obj.name}.bind(obj))(")
        self.traverse(node.receiver)
        self.write(",")
        self.traverse(node.default)
        self.write(")")

    def visit_Call(self, node: Call):
        previous = self.direct_call_target
        self.direct_call_target = node.func
        try:
            self.visit_call(node)
        finally:
            self.direct_call_target = previous

    def literal_string_membership(self, node: Call) -> bool:
        if not (
            isinstance(node.func, Attribute)
            and node.func.attr == "__contains__"
            and isinstance(node.func.value, ast.Set)
            and 1 <= len(node.func.value.elts) <= 4
            and len(node.args) == 1
            and not node.keywords
        ):
            return False
        owner = getattr(node.func.obj, "cls", None)
        item_type = analyzed_value_type(node.args[0])
        if not all(
            isinstance(cls, Class) and cls.py_obj is builtin
            for cls, builtin in ((owner, _set), (item_type, _str))
        ) or not all(
            isinstance(value, ast.Constant) and type(value.value) is str
            for value in node.func.value.elts
        ):
            return False
        # Small immutable string literals need no fresh Set allocation. Capture
        # the needle once, including explicit __contains__(side_effect()) calls.
        # Other domains retain hashing/equality and ordinary set construction.
        capture = not isinstance(node.args[0], (ast.Name, ast.Constant))
        needle = "$item" if capture else self.isolated_call_arg(node.args[0])

        def write_comparison(value):
            self.write(needle, " === ")
            self.traverse(value)

        # A plain name or constant needs no capture: none of these literal
        # comparisons can change its value. Other expressions must run once.
        self.write("(($item) => " if capture else "(")
        self.interleave(
            lambda: self.write(" || "),
            write_comparison,
            node.func.value.elts,
        )
        self.write(")")
        if capture:
            self.write("(")
            self.visit_call_arg(node.args[0])
            self.write(")")
        return True

    def visit_call(self, node: Call):
        self.set_precedence(_Precedence.ATOM, node.func)
        call_target = analyzed_value_object(node.func)

        if self.literal_string_membership(node):
            return

        forwarded = getattr(node, "forwarded_func", None)
        if (not node.reverse and isinstance(forwarded, Attribute)
                and forwarded.obj.is_staticmethod):
            # A static helper does not consume its receiver, but Python still
            # evaluates that expression before the arguments. Keep await/yield
            # in the enclosing function rather than introducing a callback.
            call = Call(node.obj, func=node.func)
            vars(call).update(vars(node))
            call.forwarded_func = None
            if is_lexical_super_call(forwarded.value, self.current_function):
                # As in ordinary super.member emission, this is lexical lookup,
                # not a standalone JS construction or a read of uninitialized
                # `this` before a derived constructor calls super.__init__.
                # Match the analyzed base binding: an application function or
                # callable named super still has ordinary receiver effects.
                self.traverse(call)
                return
            self.write("(")
            self.traverse(forwarded.value)
            self.write(", ")
            self.traverse(call)
            self.write(")")
            return

        if (getattr(node, "reverse", False) and isinstance(call_target, Function)
                and isinstance(node.func, (Name, Attribute))):
            # Forwarded methods and generic iterable membership carry the
            # receiver in args[0]; ordinary methods keep it in the Attribute.
            helper_call = isinstance(node.func, Name)
            forwarded = getattr(node, "forwarded_func", None)
            static_helper = (helper_call and isinstance(forwarded, Attribute)
                             and forwarded.obj.is_staticmethod)
            if static_helper:
                # A static protocol receives only the needle, but evaluating
                # its container still belongs to the source comparison.
                sources = (node.args[0], forwarded.value)
            else:
                sources = ((node.args[1], node.args[0]) if helper_call
                           else (node.args[0], node.func.value))
            # A constant left operand cannot observe right-operand effects.
            # Attributes are not generally pure: they may invoke getters.
            # Static forwarding additionally needs the otherwise omitted
            # container evaluation, even when the needle is constant.
            needs_capture = static_helper or (
                not isinstance(sources[0], ast.Constant) and not all(
                    isinstance(value, (ast.Name, ast.Constant)) for value in sources
                )
            )
            if needs_capture and (helper_call or call_target.inline_decorator is not None):
                # Inline membership often emits receiver.has(needle). Honor
                # the analyzed source-order flag before expanding that template.
                # Do not rewrite shared analysis or evaluate either operand twice.
                names = []
                owner = self.current_function or self.entry_point
                # Literals/call results may carry their Class in .obj, but a
                # captured local denotes a value, not a reference to that class.
                for label, source in zip(("compare_left", "compare_right"), sources, strict=True):
                    name = self.temporary_name(label)
                    local = analyzed_value_type(source)(name, owner.scope, owner)
                    value = Name(local, id=name, ctx=ast.Load())
                    set_analyzed_representation(value, analyzed_representation(source))
                    names.append(value)
                comparison = Call(node.obj, func=node.func)
                vars(comparison).update(vars(node))
                if static_helper:
                    comparison.args = [names[0], *node.args[1:]]
                    # The receiver is already evaluated by the outer capture.
                    comparison.forwarded_func = None
                elif helper_call:
                    comparison.args = [names[1], names[0], *node.args[2:]]
                else:
                    receiver = Attribute(node.func.obj, value=node.func.value, attr=node.func.attr)
                    vars(receiver).update(vars(node.func))
                    receiver.value = names[1]
                    comparison.func = receiver
                    comparison.args = [names[0], *node.args[1:]]
                comparison.reverse = False
                # Keep both operands outside the wrapper: either may contain
                # await/yield, which belongs to the enclosing source function.
                self.write(f"(({names[0].id}, {names[1].id}) => ")
                self.traverse(comparison)
                self.write(")(")
                self.interleave(lambda: self.write(", "), self.visit_call_arg, sources)
                self.write(")")
                return
            if needs_capture:
                # Reflected application operators still evaluate the source's left
                # operand first. An ordinary receiver(args) call reverses that order.
                self.write(f"((left,right)=>right.{node.func.attr}(left))(")
                self.visit_call_arg(node.args[0])
                self.write(",")
                self.visit_call_arg(node.func.value)
                self.write(")")
                return

        if (numeric_cast := getattr(node, "numeric_cast", None)) is not None:
            argument = node.args[0]
            source_format = analyzed_numeric_format(argument)
            source_is_bigint = (
                source_format is not None
                and source_format.kind == "integer"
                and source_format.bits == 64
            )
            if numeric_cast.kind == "float":
                if numeric_cast.bits == 32:
                    self.write("Math.fround(")
                    if source_is_bigint:
                        self.write("Number(")
                    self.visit_call_arg(argument)
                    if source_is_bigint:
                        self.write(")")
                    self.write(")")
                else:
                    self.write("Number(")
                    self.visit_call_arg(argument)
                    self.write(")")
                return
            literal = integer_literal(getattr(argument, "python_node", argument))
            if numeric_cast.bits == 64:
                if literal is not None:
                    self.write(f"BigInt.asIntN(64,BigInt('{literal}'))")
                    return
                self.write(
                    "BigInt.asIntN(64,((value)=>typeof value==='bigint'?"
                    "value:BigInt(Math.trunc(value)))("
                )
                self.visit_call_arg(argument)
                self.write("))")
                return
            if literal is not None and abs(literal) > 2**53 - 1:
                method = "asIntN" if numeric_cast.signed else "asUintN"
                self.write(
                    f"Number(BigInt.{method}({numeric_cast.bits},BigInt('{literal}')))"
                )
                return
            prefix, suffix = {
                (8, True): ("((", " << 24) >> 24)"),
                (8, False): ("(", " & 255)"),
                (16, True): ("((", " << 16) >> 16)"),
                (16, False): ("(", " & 65535)"),
                (32, True): ("(", " | 0)"),
                (32, False): ("(", " >>> 0)"),
            }[(numeric_cast.bits, numeric_cast.signed)]
            if source_is_bigint:
                method = "asIntN" if numeric_cast.signed else "asUintN"
                self.write(f"Number(BigInt.{method}({numeric_cast.bits},")
                self.visit_call_arg(argument)
                self.write("))")
                return
            self.write(prefix)
            self.visit_call_arg(argument)
            self.write(suffix)
            return

        if node.dictionary_keys is not None:
            values = [*node.args, *(keyword.value for keyword in node.keywords)]
            items = [
                (name, value)
                for name, value in zip(node.dictionary_keys, values, strict=True)
                if not (
                    name in node.dictionary_optional
                    and isinstance(value, ast.Constant)
                    and value.value is None
                )
            ]

            def write_item(item):
                name, value = item
                optional = name in node.dictionary_optional
                if name.endswith("_") and keyword.iskeyword(name[:-1]):
                    name = name[:-1]
                if optional:
                    if isinstance(value, ast.Constant):
                        self.write(name)
                        self.write(": ")
                        self.visit_call_arg(value)
                        return
                    if isinstance(value, ast.Name):
                        self.write("...(")
                        self.visit_call_arg(value)
                        self.write(" != null ? {")
                        self.write(name)
                        self.write(": ")
                        self.visit_call_arg(value)
                        self.write("} : {})")
                        return
                    # Preserve side effects while conditionally omitting the value.
                    self.write("...((value)=>value != null ? {")
                    self.write(name)
                    self.write(": value} : {})(")
                    self.visit_call_arg(value)
                    self.write(")")
                    return
                self.write(name)
                self.write(": ")
                self.visit_call_arg(value)

            with self.delimit("{", "}"):
                self.interleave(
                    lambda: self.write(", "),
                    write_item,
                    items,
                )
                return
        if decorator_func := getattr(node.func.obj, "inline_decorator", None):
            operator_rule = self.operator_precedence(node)
            if operator_rule is None:
                operator_precedence = None
                self_precedence = argument_precedence = None
            else:
                operator_precedence, self_precedence, argument_precedence = operator_rule
            self_ = None
            if isinstance(node.func, Attribute):
                self_ = self.isolated_visit(node.func.value, self_precedence)
            elif isinstance(node.func.obj, Class):
                self_ = node.func.obj._self
            src = decorator_func.rewrite_call(
                [self.isolated_call_arg(arg, argument_precedence) for arg in node.args],
                [
                    arg.obj
                    if isinstance(arg.obj, (GenericClass, Class, UnionType))
                    else arg.obj.cls
                    for arg in node.args
                ],
                [analyzed_numeric_format(arg) for arg in node.args],
                self_,
                keyword_strs={
                    keyword.arg: self.isolated_call_arg(keyword.value)
                    for keyword in node.keywords
                    if keyword.arg is not None
                },
                inline_dependencies=node.inline_dependencies,
                self_format=(
                    analyzed_numeric_format(node.func.value)
                    if isinstance(node.func, Attribute)
                    else None
                ),
                result_format=analyzed_numeric_format(node),
                arg_representations=[
                    analyzed_representation(arg) for arg in node.args
                ],
                arg_item_representations=[
                    (
                        protocol.item_representation
                        if (protocol := analyzed_iterable_protocol(arg)) is not None
                        else None
                    )
                    for arg in node.args
                ],
                arg_item_formats=[
                    (
                        protocol.item_numeric_formats
                        if (protocol := analyzed_iterable_protocol(arg)) is not None
                        else frozenset()
                    )
                    for arg in node.args
                ],
            )
            if src is NotImplemented:
                self.fail(
                    node,
                    DiagnosticCode.UNSUPPORTED_SYNTAX,
                    f"Inline implementation for {decorator_func.name!r} "
                    "cannot lower this call",
                    help=(
                        "Use supported argument types or provide a runtime "
                        "implementation for this operation."
                    ),
                )
            if not isinstance(src, str):
                self.fail(
                    node,
                    DiagnosticCode.INVALID_INLINE_DEPENDENCY,
                    f"Inline implementation for {decorator_func.name!r} "
                    f"returned {type(src).__name__}, not str",
                    help="Return JavaScript source text from the inline generator.",
                )
            result_format = analyzed_numeric_format(node)
            owner = getattr(decorator_func, "cls", None)
            builtin = getattr(decorator_func.py_obj, "__builtin__", False) or (
                owner is not None
                and owner.py_obj.__dict__.get("__builtin__", False)
            )
            if result_format is not None and not builtin:
                src = normalize_numeric_expression(f"({src})", result_format)
            if operator_precedence is None:
                self.write(src)
            else:
                with self.require_parens(operator_precedence, node):
                    self.write(src)
            return

        super_call = (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        )

        if super_call:
            if node.func.attr == "__init__":
                self.write("super")
                if issubclass(node.func.value.obj.py_obj, (CustomElement, ProxyElement)):
                    self.write("._create")
            else:
                self.write("super.")
                self.write(node.func.attr)
        elif isinstance(call_target, Class) and not isinstance(
            call_target, CallableClass
        ):
            self.write("new ")
            self.traverse(node.func)
            if issubclass(call_target.py_obj, (CustomElement, ProxyElement)):
                self.write("()._create")
        elif (
            isinstance(call_target, Instance)
            and not isinstance(call_target.cls, CallableClass)
            and not getattr(call_target.cls.py_obj, "__builtin__", False)
        ):
            self.traverse(node.func)
            self.write(".__call__")
        else:
            self.traverse(node.func)

        args = list(node.args)
        trailing_args = []
        keywords = list(node.keywords)
        called_function = call_target
        is_builtin = False
        if isinstance(called_function, Class):
            base = called_function
            while base is not None and base.name != "Exception":
                base = base.super
            is_builtin = base is not None or called_function.py_obj.__dict__.get(
                "__builtin__", False
            )
        elif isinstance(called_function, Function):
            is_builtin = getattr(called_function.py_obj, "__builtin__", False) or (
                called_function.cls is not None
                and called_function.cls.py_obj.__dict__.get("__builtin__", False)
            )
        elif isinstance(called_function, Instance):
            called_function = (called_function.cls if isinstance(called_function.cls, CallableClass)
                               else called_function.find("__call__"))
        if isinstance(called_function, CallableClass):
            if called_function.minimum_arguments < len(called_function.parameter_types or ()):
                # Count supplied values, not AST nodes: a spread can reach the
                # options-object slot even when it is the only written argument.
                pending, count = list(args), 0
                while pending:
                    argument = pending.pop()
                    if not isinstance(argument, ast.Starred):
                        count += 1
                    elif isinstance(argument.value, (ast.List, ast.Tuple)):
                        pending.extend(argument.value.elts)
                    else:
                        source_type = analyzed_value_type(argument.value)
                        if is_builtin_class(source_type, "tuple") and not source_type.tuple_variadic:
                            count += len(source_type.generic_types)
                        else:
                            count = None
                            break
                if count is None or count > called_function.minimum_arguments:
                    self.fail(
                        node,
                        DiagnosticCode.INCOMPATIBLE_ARGUMENT,
                        "JavaScript indirect calls cannot supply optional positional arguments",
                        help="Call the named function directly or use a fixed-arity wrapper.",
                    )
            called_function = None
        elif isinstance(called_function, Class):
            called_function = called_function.find("__init__")
        native_iterable_parameters = set()
        if isinstance(called_function, Function):
            implementation = js_metadata(called_function.py_obj, "implementation")
            if implementation is None and called_function.cls is not None:
                implementation = js_metadata(called_function.cls.py_obj, "implementation")
            if implementation is not None and implementation.kind == "native":
                # Host APIs consume JavaScript iterables, whereas emitted Python
                # functions must retain the source for repeated iteration/identity.
                native_iterable_parameters = {
                    index for index, param in enumerate(called_function.params)
                    if abstract_iterable(param.annotation.obj)
                }
        needs_empty_options = False
        if not is_builtin and isinstance(called_function, Function):
            required_count = len(called_function.params) - len(called_function.defaults)
            if len(args) < required_count:
                keyword_values = {keyword.arg: keyword.value for keyword in keywords}
                lowered_names = set()
                for param in called_function.params[len(args) : required_count]:
                    if param.arg not in keyword_values:
                        break
                    args.append(keyword_values[param.arg])
                    lowered_names.add(param.arg)
                keywords = [
                    keyword for keyword in keywords if keyword.arg not in lowered_names
                ]

            lowered_default_args = False
            if called_function.defaults:
                first_default = len(called_function.params) - len(
                    called_function.defaults
                )
                default_args = args[first_default : len(called_function.params)]
                if default_args:
                    lowered_default_args = True
                    keywords = [
                        ast.keyword(
                            arg=(
                                f"${index}"
                                if index < called_function.posonly_count
                                else called_function.params[index].arg
                            ),
                            value=value,
                        )
                        for index, value in enumerate(default_args, first_default)
                    ] + keywords
                    trailing_args = args[len(called_function.params) :]
                    args = args[:first_default]
            has_keyword_only_varargs = called_function.vararg is not None and bool(
                called_function.kwonlyargs or called_function.kwarg
            )
            if has_keyword_only_varargs and not lowered_default_args:
                trailing_args = args[len(called_function.params) :]
                args = args[: len(called_function.params)]
            if has_keyword_only_varargs:
                needs_empty_options = bool(trailing_args) and not keywords

        with self.delimit("(", ")"):
            first = True
            if native_iterable_parameters and any(isinstance(arg, ast.Starred) for arg in args):
                self.visit_native_starred_args(args, native_iterable_parameters)
                args = []
                first = False
            for index, e in enumerate(args):
                if not first:
                    self.write(", ")
                if index in native_iterable_parameters:
                    self.traverse_iterable(e, allow_none=True)
                else:
                    self.visit_call_arg(e)
                first = False
            if keywords or needs_empty_options:
                if not first:
                    self.write(", ")
                with self.delimit("{", "}"):
                    first_keyword = True
                    for e in keywords:
                        if not first_keyword:
                            self.write(", ")
                        self.visit_call_arg(e)
                        first_keyword = False
                first = False
            for e in trailing_args:
                if not first:
                    self.write(", ")
                self.visit_call_arg(e)
                first = False

    def visit_native_starred_args(self, args, iterable_parameters):
        # Syntactic argument indices are not parameter indices after * expansion.
        # Evaluate the argument pack once, then adapt only present bound values;
        # omitted defaults, the original containers and call order stay intact.
        self.write("...(($args)=>{")
        for index in sorted(iterable_parameters):
            value = f"$args[{index}]"
            source = dynamic_iterable_source(value, allow_none=True)
            self.write(f"if($args.length>{index}){value}={source};")
        self.write("return $args;})([")
        for index, arg in enumerate(args):
            if index:
                self.write(", ")
            self.visit_call_arg(arg)
        self.write("])")

    def bound_method_source(self, node):
        if not isinstance(node, Attribute) or not isinstance(node.obj, Function):
            return None
        method = node.obj
        if method.cls is None or method.is_staticmethod:
            return None
        is_super = (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "super")
        receiver_type = analyzed_value_object(node.value)
        if isinstance(receiver_type, Class) and not method.is_classmethod and not is_super:
            return None
        receiver = "this" if is_super else self.isolated_visit(node.value)
        simple = is_super or isinstance(node.value, ast.Name)
        owner = receiver if simple else "$receiver"
        if method.is_classmethod and isinstance(receiver_type, Instance):
            owner += ".constructor"
        member = "[Symbol.iterator]" if node.attr == "__iter__" else f".{node.attr}"
        source = ("super" if is_super else owner) + member
        bind_source = js_metadata(method.py_func, "bind_source")
        source = bind_source(source, owner, method) if bind_source is not None else f"{source}.bind({owner})"
        # An effectful receiver must be evaluated once, not again for bind().
        return source if simple else f"(($receiver) => {source})({receiver})"

    def isolated_call_arg(self, node, precedence=None):
        return self.isolated_visit(node, precedence)

    def visit_call_arg(self, node):
        self.traverse(node)

    def visit_keyword(self, node):
        self.write(node.arg)
        self.write(": ")
        self.visit_call_arg(node.value)

    def visit_Lambda(self, node):
        with self.require_parens(_Precedence.TEST, node):
            with self.delimit("(", ")"):
                self.traverse(node.args)
            self.write(" => ")
            self.set_precedence(_Precedence.TEST, node.body)
            self.traverse(node.body)

    def visit_Expr(self, node: ast.Expr):
        self.fill()
        self.set_precedence(_Precedence.YIELD, node.value)
        self.traverse(node.value)
        self.write(";")

    def visit_IfExp(self, node: ast.IfExp):
        with self.require_parens(_Precedence.TEST, node):
            self.set_precedence(_Precedence.TEST.next(), node.body, node.test)
            self.traverse(node.test)
            self.write(" ? ")
            self.traverse(node.body)
            self.write(" : ")
            self.set_precedence(_Precedence.TEST, node.orelse)
            self.traverse(node.orelse)

    boolops = {"And": "&&", "Or": "||"}
    boolop_precedence = {"&&": _Precedence.AND, "||": _Precedence.OR}

    def visit_BoolOp(self, node):
        operator = self.boolops[node.op.__class__.__name__]
        operator_precedence = self.boolop_precedence[operator]

        def increasing_level_traverse(value):
            nonlocal operator_precedence
            operator_precedence = operator_precedence.next()
            self.set_precedence(operator_precedence, value)
            self.traverse(value)

        with self.require_parens(operator_precedence, node):
            separator = f" {operator} "
            self.interleave(
                lambda: self.write(separator), increasing_level_traverse, node.values
            )

    def visit_ChainedCompare(self, node):
        names = self.awaited_comparisons.get(node)
        previous = self.comparison_bindings
        self.comparison_bindings = dict(previous)
        for index, temporary in enumerate(node.temporaries):
            self.comparison_bindings[temporary.id] = names[index] if names else temporary.id
        try:
            self.write_chained_comparison(node, names is not None)
        finally:
            self.comparison_bindings = previous

    def write_chained_comparison(self, node, awaited):
        if awaited:
            # Keep awaits in the caller: an async IIFE would add a suspension
            # even when every awaited tail operand was short-circuited.
            self.write("(")
            for index, operand in enumerate(node.operands):
                if index > 1:
                    self.write(" && (")
                self.traverse(node.temporaries[index])
                self.write(" = ")
                self.set_precedence(_Precedence.TEST, operand)
                self.traverse(operand)
                self.write(", ")
                if index:
                    self.traverse(node.comparisons[index - 1])
            self.write(")" * (len(node.operands) - 1))
            return

        def emit_comparison(index):
            temporary = node.temporaries[index + 1]
            self.write("((")
            self.traverse(temporary)
            self.write(") => ")
            self.traverse(node.comparisons[index])
            if index + 1 < len(node.comparisons):
                self.write(" && ")
                emit_comparison(index + 1)
            self.write(")(")
            self.traverse(node.operands[index + 1])
            self.write(")")

        self.write("((")
        self.traverse(node.temporaries[0])
        self.write(") => ")
        emit_comparison(0)
        self.write(")(")
        self.traverse(node.operands[0])
        self.write(")")

    def traverse_iterable(self, node, *, allow_none=False):
        # An abstract Iterable may hide a dict (Map in JS). Keep its source
        # identity and acquire keys only at iteration, evaluating it once.
        function = analyzed_value_object(node.func) if isinstance(node, Call) else None
        receiver = (analyzed_value_type(node.func.value)
                    if isinstance(node, Call) and isinstance(node.func, Attribute) else None)
        builtin_receiver = (isinstance(receiver, TypedDictClass)
                            or isinstance(receiver, Class) and receiver.container.scope.is_builtins
                            and receiver.generic_name == "dict")
        if builtin_receiver and isinstance(function, Function) and function.py_func in (
            _dict.keys, _dict.values, _dict.items,
            _typed_dict.keys, _typed_dict.values, _typed_dict.items,
        ):
            # These resolved builtin calls already acquire a JS iterable. Their
            # abstract return annotation does not require another runtime test.
            # Check both function identity and receiver: union lookup may resolve
            # to its first member's builtin method even when an application arm
            # returns a dict. Mixed/unknown receivers still need acquisition.
            self.traverse(node)
            return
        value_type = analyzed_value_type(node)
        if abstract_iterable(value_type) or any(
            isinstance(member, TypedDictClass) or isinstance(member, Class)
            and member.container.scope.is_builtins and member.generic_name == "dict"
            for member in get_type_members(value_type)
        ):
            # Stream the expression in place so source-map coordinates still
            # track its real generated position (not a temporary buffer).
            prefix, suffix = iterable_source(
                "$pyjsIterable", value_type, allow_none=allow_none
            ).split("$pyjsIterable")
            self.write(prefix)
            if suffix == ".keys()":
                self.set_precedence(_Precedence.ATOM, node)
            self.traverse(node)
            self.write(suffix)
        else:
            self.traverse(node)

    def visit_ListComp(self, node):
        if len(node.generators) > 1 or not isinstance(
            node.generators[0].target, ast.Name
        ):
            self.visit_expanded_comprehension(node, "[]", "push")
            return
        iter_node = node.generators[0]
        self.write("Array.from(")
        self.traverse_iterable(iter_node.iter)
        self.write(")")
        for condition in iter_node.ifs:
            self.write(".filter")
            with self.delimit("(", ")"):
                self.traverse(iter_node.target)
                self.write(" => ")
                self.traverse(condition)
        self.write(".map")
        with self.delimit("(", ")"):
            self.traverse(iter_node.target)
            self.write(" => ")
            self.traverse(node.elt)

    def visit_DictComp(self, node):
        self.visit_expanded_comprehension(node, "new Map()", "set")

    def visit_SetComp(self, node):
        self.visit_expanded_comprehension(node, "new Set()", "add")

    def visit_GeneratorExp(self, node):
        self.write("(($iterator)=>(function*(){")
        self.visit_comprehension_loops(node, outer_iter="$iterator")
        self.write("})())((")
        self.traverse_iterable(node.generators[0].iter)
        self.write(")[Symbol.iterator]())")

    def visit_expanded_comprehension(self, node, initializer, method):
        # The outer source belongs to the enclosing scope, including await;
        # evaluate it there rather than inside this synchronous accumulator.
        self.write(f"(($iterable)=>{{const $result={initializer};")
        self.visit_comprehension_loops(node, method, outer_iter="$iterable")
        self.write("return $result;})(")
        self.traverse_iterable(node.generators[0].iter)
        self.write(")")

    def visit_comprehension_loops(self, node, method=None, outer_iter=None):
        targets = [target for generator in node.generators for target in ast.walk(generator.target)
                   if isinstance(target, ast.Name)]
        bindings = {target.id: target for target in targets}
        shared = len(bindings) != len(targets)
        if shared:
            # Python reuses a comprehension-local binding across clauses. A
            # second `for(const x of [x])` instead shadows its own source with
            # an uninitialized JS binding. Declare shared cells once, inside
            # the comprehension closure and after the outer source evaluation.
            self.write("let ")
            self.interleave(lambda: self.write(","), self.traverse, bindings.values())
            self.write(";")
        condition_counts = []
        for index, generator in enumerate(node.generators):
            self.write("for(" if shared else "for(const ")
            self.traverse(generator.target)
            self.write(" of ")
            if index == 0 and outer_iter is not None:
                self.write(outer_iter)
            else:
                self.traverse_iterable(generator.iter)
            self.write("){")
            for condition in generator.ifs:
                self.write("if(")
                self.traverse(condition)
                self.write("){")
            condition_counts.append(len(generator.ifs))
        self.write("yield " if method is None else f"$result.{method}(")
        if isinstance(node, ast.DictComp):
            self.traverse(node.key)
            self.write(",")
            self.traverse(node.value)
        else:
            self.traverse(node.elt)
        self.write(";" if method is None else ");")
        for condition_count in reversed(condition_counts):
            self.write("}" * (condition_count + 1))

    def visit_Subscript(self, node):
        receiver_obj = (
            node.value.value_obj
            if isinstance(node.value, (Call, Subscript))
            else node.value.obj
        )
        receiver_type = (
            receiver_obj.cls if isinstance(receiver_obj, Instance) else receiver_obj
        )
        negative_index = (
            isinstance(node.slice, UnaryOp)
            and isinstance(node.slice.op, ast.USub)
            and isinstance(node.slice.operand, Constant)
            and isinstance(node.slice.operand.value, int)
        )
        if negative_index and getattr(receiver_type, "generic_name", None) in {
            "list",
            "str",
            "tuple",
        }:
            self.traverse(node.value)
            self.write(".at(")
            self.traverse(node.slice)
            self.write(")")
            return
        super().visit_Subscript(node)

    def prepare_attribute_assignment_value(self, target, value):
        if (isinstance(target, ast.Attribute)
                and not isinstance(target.value, ast.Name)
                and value is not None and not isinstance(value, ast.Constant)):
            # Python evaluates the RHS before resolving the receiver; JavaScript
            # does the reverse. Reads/calls in a compound receiver may observe
            # mutations performed by the RHS, even without a property setter.
            # Shared analysis also creates assignment locals; keep emitter-only
            # temporaries in a separate namespace.
            temporary = self.temporary_name("assignment_rhs")
            self.fill(f"const {temporary} = ")
            self.traverse(value)
            self.write(";")
            return ast.Name(id=temporary)
        return value

    def visit_Assign(self, node):
        assert len(node.targets) == 1
        target = node.targets[0]
        value = self.prepare_attribute_assignment_value(target, node.value)
        self.fill()
        if isinstance(target, (ast.Tuple, ast.List)) and getattr(
            node, "declares_name", False
        ):
            self.write("var ")
        self.set_precedence(_Precedence.TUPLE, target)
        self.traverse(target)
        self.write(" = ")
        self.traverse(value)
        self.write(";")

    def visit_UnpackAssignment(self, node):
        temporary = self.temporary_name("unpack")
        # Snapshot this level before a target mutates the source. Nested
        # unpacking happens at its own turn, after earlier target stores.
        # Tuples (including unpack_starred's fresh result) cannot be mutated.
        snapshot = (not isinstance(node.value, (ast.List, ast.Tuple))
                    and analyzed_value_type(node.value).generic_name != "tuple")
        self.fill(f"const {temporary} = " + ("[..." if snapshot else ""))
        self.traverse(node.value)
        self.write("];" if snapshot else ";")
        for assignment in node.assignments:
            for child in ast.walk(assignment):
                if isinstance(child, UnpackItem):
                    child.temporary = temporary
        self.traverse(node.assignments)

    def visit_UnpackItem(self, node):
        self.write(f"{node.temporary}[{node.index}]")

    def visit_Delete(self, node):
        for target in node.targets:
            self.fill()
            if isinstance(target, ast.Name):
                self.traverse(target)
                self.write(" = undefined;")
            else:
                self.write("delete ")
                self.traverse(target)
                self.write(";")

    def visit_AnnAssign(self, node):
        value = self.prepare_attribute_assignment_value(node.target, node.value)
        self.fill()
        annotation_id = (
            node.annotation.id if isinstance(node.annotation, ast.Name) else None
        )
        is_module_binding = annotation_id in {"__const__", "__module__"}
        if isinstance(node.target, ast.Attribute):
            pass
        elif annotation_id == "__static__":
            self.write("static ")
        elif annotation_id == "__const__":
            self.write("export const " if self.exporter is None else "const ")
        elif annotation_id == "__module__":
            self.write("export let " if self.exporter is None else "let ")
        else:
            target_name = node.target.id if isinstance(node.target, ast.Name) else None
            if (
                self.local_declarations is None
                or target_name not in self.local_declarations
            ):
                self.write("var ")
            if self.local_declarations is not None and target_name is not None:
                self.local_declarations.add(target_name)
        with self.delimit_if(
            "(", ")", not node.simple and isinstance(node.target, ast.Name)
        ):
            if annotation_id == "__static__" and isinstance(node.target, ast.Name):
                self.write(node.target.id)
            else:
                self.traverse(node.target)
        if value is not None:
            self.write(" = ")
            self.traverse(value)
        self.write(";")
        if is_module_binding and self.exporter is not None:
            self.fill(self.exporter(javascript_identifier(node.target.id)))

    def visit_Name(self, node):
        value = getattr(node, "obj", None)
        if node.id in self.comparison_bindings:
            self.write(self.comparison_bindings[node.id])
        elif node.id == "self" and isinstance(value, Instance):
            self.write("this")
        elif getattr(node, "runtime_dependency", None) is not None:
            self.write(getattr(node, "runtime_alias", node.id))
        elif exception_name := self.builtin_exception_name(value):
            self.write(exception_name)
        elif node.id in {"super", "this"} and isinstance(value, Class):
            self.write(node.id)
        else:
            self.write(javascript_identifier(node.id))

    def visit_Attribute(self, node):
        if node is not self.direct_call_target and isinstance(node.ctx, ast.Load):
            source = self.bound_method_source(node)
            if source is not None:
                self.write(source)
                return
        if getattr(node, "module_import_alias", None) is not None:
            self.write(javascript_identifier(node.module_import_alias))
            return
        member = getattr(node, "obj", None)
        receiver = getattr(
            node.value,
            "value_obj",
            getattr(node.value, "obj", None),
        )
        static_method_access = (
            isinstance(receiver, Instance)
            and isinstance(member, Function)
            and member.is_static
        )
        if static_method_access:
            self.traverse(node.value)
            self.write(".constructor.")
            self.write(node.attr)
            return
        class_field_access = (
            isinstance(receiver, Instance)
            and isinstance(member, Instance)
            and (owner := field_owner(member)) is not None
            and (
                member.static_value is not None
                or self.has_static_field_override(member, owner)
            )
        )
        if class_field_access and isinstance(node.ctx, ast.Load):
            self.write("(($instance) => $instance.")
            self.write(node.attr)
            self.write(" === undefined ? $instance.constructor.")
            self.write(node.attr)
            self.write(" : $instance.")
            self.write(node.attr)
            self.write(")(")
            self.traverse(node.value)
            self.write(")")
            return
        if node.attr == "__iter__" and isinstance(member, Function):
            self.traverse(node.value)
            self.write("[Symbol.iterator]")
            return
        super().visit_Attribute(node)

    def has_static_field_override(self, field, cls):
        for subclass in cls.subclasses:
            if not should_include(subclass):
                continue
            override = subclass.find_attrs(field.name, search_bases=False)
            if isinstance(override, Instance) and override.static_value is not None:
                return True
            if self.has_static_field_override(field, subclass):
                return True
        return False

    def visit_Constant(self, node):
        value = node.value
        if isinstance(value, tuple):
            with self.delimit("[", "]"):
                self.items_view(self._write_constant, value)
        elif value is ...:
            self.write("...")
        elif isinstance(node.value, bool):
            self.write(repr(node.value).lower())
        elif isinstance(node.value, type(None)):
            self.write("null")
        else:
            if node.kind == "u":
                self.write("u")
            self._write_constant(node.value)

    def visit_Dict(self, node: ast.Dict):
        if isinstance(getattr(node, "obj", None), TypedDictClass):

            def write_object_item(item):
                key, value = item
                if key is None:
                    self.write("...")
                    self.traverse(value)
                    return
                self.traverse(key)
                self.write(": ")
                self.traverse(value)

            with self.delimit("{", "}"):
                self.interleave(
                    lambda: self.write(", "),
                    write_object_item,
                    zip(node.keys, node.values, strict=True),
                )
            return

        def write_key_value_pair(k, v):
            with self.delimit("[", "]"):
                self.traverse(k)
                self.write(", ")
                self.traverse(v)

        def write_item(item):
            k, v = item
            if k is None:
                self.write("...")
                self.traverse(v)
            else:
                write_key_value_pair(k, v)

        with self.delimit("new Map([", "])"):
            self.interleave(
                lambda: self.write(", "),
                write_item,
                zip(node.keys, node.values, strict=True),
            )

    def visit_Set(self, node: ast.Set):
        with self.delimit("new Set([", "])"):
            self.interleave(lambda: self.write(", "), self.traverse, node.elts)

    def visit_If(self, node):
        self.fill("if ")
        with self.delimit("(", ")"):
            self.traverse(node.test)
        with self.block():
            self.traverse(node.body)
        while (
            node.orelse and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)
        ):
            node = node.orelse[0]
            self.write(" else if ")
            with self.delimit("(", ")"):
                self.traverse(node.test)
            with self.block():
                self.traverse(node.body)
        if node.orelse:
            self.write(" else")
            with self.block():
                self.traverse(node.orelse)

    def loop_else_flag(self, node):
        if not node.orelse or not body_breaks_current_loop(node.body):
            return None
        completed = self.temporary_name("loop_completed")
        self.fill(f"let {completed} = true;")
        return completed

    def write_loop_else(self, node, completed):
        if not node.orelse:
            return
        if completed is None:
            self.traverse(node.orelse)
            return
        self.fill(f"if ({completed})")
        with self.block():
            self.traverse(node.orelse)

    def visit_While(self, node):
        completed = self.loop_else_flag(node)
        self.fill("while ")
        with self.delimit("(", ")"):
            self.traverse(node.test)
        self.loop_else_stack.append(completed)
        try:
            with self.block():
                self.traverse(node.body)
        finally:
            self.loop_else_stack.pop()
        self.write_loop_else(node, completed)

    def visit_Try(self, node: ast.Try):
        if node.orelse and node.finalbody:
            self.fill("try")
            with self.block():
                self._write_try_with_else(node)
            self.write(" finally")
            with self.block():
                self.traverse(node.finalbody)
            return
        if node.orelse:
            self._write_try_with_else(node)
            return
        self.fill("try")
        with self.block():
            self.traverse(node.body)
        if node.handlers:
            self._write_except_handlers(node.handlers)
        if node.finalbody:
            self.write(" finally")
            with self.block():
                self.traverse(node.finalbody)

    def _write_try_with_else(self, node: ast.Try) -> None:
        succeeded = self.temporary_name("try")
        self.fill(f"let {succeeded} = true;")
        self.fill("try")
        with self.block():
            self.traverse(node.body)
        self._write_except_handlers(node.handlers, failed_flag=succeeded)
        self.fill(f"if ({succeeded})")
        with self.block():
            self.traverse(node.orelse)

    def _write_except_handlers(
        self,
        handlers: list[ast.ExceptHandler],
        *,
        failed_flag: str | None = None,
    ) -> None:
        for index, handler in enumerate(handlers):
            if self._is_catch_all(handler):
                handlers = handlers[: index + 1]
                break
        if len(handlers) == 1 and self._is_catch_all(handlers[0]):
            handler = handlers[0]
            name = javascript_identifier(handler.name) if handler.name else "_error"
            self.write(f" catch ({name})")
            with self.block():
                if failed_flag is not None:
                    self.fill(f"{failed_flag} = false;")
                with self.caught_exception(name):
                    self.traverse(handler.body)
            return

        error = self.temporary_name("error")
        self.write(f" catch ({error})")
        with self.block():
            if failed_flag is not None:
                self.fill(f"{failed_flag} = false;")
            has_catch_all = False
            for index, handler in enumerate(handlers):
                catch_all = self._is_catch_all(handler)
                if catch_all:
                    self.write(" else")
                elif index:
                    self.write(" else if (")
                    self._write_exception_test(handler.type, error)
                    self.write(")")
                else:
                    self.fill("if (")
                    self._write_exception_test(handler.type, error)
                    self.write(")")
                with self.block():
                    if handler.name is not None:
                        self.fill(f"let {javascript_identifier(handler.name)} = {error};")
                    with self.caught_exception(error):
                        self.traverse(handler.body)
                if catch_all:
                    has_catch_all = True
                    break
            if not has_catch_all:
                self.write(" else")
                with self.block():
                    self.fill(f"throw {error};")

    @staticmethod
    def _is_catch_all(handler: ast.ExceptHandler) -> bool:
        return handler.type is None or (
            isinstance(handler.type, Name)
            and isinstance(handler.type.obj, Class)
            and handler.type.obj.name == "Exception"
        )

    def _write_exception_test(self, type_node: ast.expr, error: str) -> None:
        types = type_node.elts if isinstance(type_node, ast.Tuple) else [type_node]
        for index, exception_type in enumerate(types):
            if index:
                self.write(" || ")
            self.write(f"{error} instanceof ")
            self.traverse(exception_type)

    def visit_With(self, node: ast.With) -> None:
        item = node.items[0]
        manager = self.temporary_name("manager")
        entered = self.temporary_name("entered")
        caught = self.temporary_name("caught")
        failed = self.temporary_name("failed")
        self.fill(f"const {manager} = ")
        self.traverse(item.context_expr)
        self.write(";")
        self.fill(f"const {entered} = {manager}.__enter__();")
        self.fill(f"let {failed} = false;")
        self.fill("try")
        with self.block():
            if item.optional_vars is not None:
                self.fill("var " if node.declares_target else "")
                self.traverse(item.optional_vars)
                self.write(f" = {entered};")
            self.traverse(node.body)
        self.write(f" catch ({caught})")
        with self.block():
            self.fill(f"{failed} = true;")
            self.fill(f"if (!{manager}.__exit__({caught}.constructor, {caught}, null))")
            with self.block():
                self.fill(f"throw {caught};")
        self.write(" finally")
        with self.block():
            self.fill(f"if (!{failed})")
            with self.block():
                self.fill(f"{manager}.__exit__(null, null, null);")

    def _for_helper(self, fill, node):
        completed = self.loop_else_flag(node)
        self.fill(fill)
        self.set_precedence(_Precedence.TUPLE, node.target)
        with self.delimit("(", ")"):
            self.write("var ")
            if isinstance(node.target, ast.Tuple):
                self.traverse(node.target)
            else:
                self.traverse(node.target)
            self.write(" of ")
            self.traverse_iterable(node.iter)
        self.loop_else_stack.append(completed)
        try:
            with self.block():
                self.traverse(node.body)
        finally:
            self.loop_else_stack.pop()
        self.write_loop_else(node, completed)

    def visit_Break(self, node):
        if self.loop_else_stack and self.loop_else_stack[-1] is not None:
            self.fill(f"{self.loop_else_stack[-1]} = false;")
        super().visit_Break(node)

    def visit_Return(self, node: ast.Return):
        self.fill("return")
        if node.value:
            self.write(" ")
            self.traverse(node.value)
        self.write(";")

    def visit_Tuple(self, node: ast.Tuple):
        with self.delimit("[", "]"):
            self.interleave(lambda: self.write(", "), self.traverse, node.elts)

    def visit_Await(self, node: ast.Await):
        with self.require_parens(_Precedence.AWAIT, node):
            self.write("await ")
            self.set_precedence(_Precedence.ATOM, node.value)
            self.traverse(node.value)

    def visit_Pass(self, node: ast.Pass):
        pass

    def visit_Raise(self, node: ast.Raise):
        self.fill("throw ")
        if node.exc:
            self.traverse(node.exc)
        elif self.exception_stack:
            self.write(self.exception_stack[-1])
        else:
            self.write("new Error('No active exception to reraise')")
        self.write(";")

    unop = {"Invert": "~", "Not": "!", "UAdd": "+", "USub": "-"}

    def visit_UnaryOp(self, node):
        operator = self.unop[node.op.__class__.__name__]
        with self.require_parens(_Precedence.FACTOR, node):
            self.write(operator)
            inline_call = (
                isinstance(node.operand, Call)
                and isinstance(node.operand.func.obj, Function)
                and node.operand.func.obj.inline_decorator
            )
            if inline_call:
                with self.delimit("(", ")"):
                    self.traverse(node.operand)
            else:
                self.set_precedence(_Precedence.FACTOR, node.operand)
                self.traverse(node.operand)

    def visit_Starred(self, node):
        self.write("...")
        self.set_precedence(_Precedence.EXPR, node.value)
        if isinstance(node.ctx, ast.Store):
            self.traverse(node.value)
        else:
            self.traverse_iterable(node.value)

    def visit_JoinedStr(self, node):
        # F-strings are atomic in Python, but become additive expressions here.
        # A method receiver must group the entire concatenation, not its tail.
        if not node.values:
            self.write("''")
        elif len(node.values) == 1:
            self.traverse(node.values[0])
        else:
            with self.require_parens(_Precedence.ARITH, node):
                for i, value in enumerate(node.values):
                    if i:
                        self.write("+")
                    self.traverse(value)


    def visit_FormattedValue(self, node: ast.FormattedValue):
        value = self.isolated_visit(node.value, _Precedence.ATOM)
        spec = constant_format_spec(node.format_spec)
        match = FORMAT_SPEC.fullmatch(spec) if spec is not None else None
        if match is None:
            self.write(value)
            return

        number_type = match.group("type")
        precision = match.group("precision")
        int64_value = is_int64_format(analyzed_numeric_format(node.value))
        if number_type == "d" and int64_value:
            formatted = f"String({value})"
            absolute = "String(value < 0n ? -value : value)"
        elif number_type == "d":
            formatted = f"String(Math.trunc({value}))"
            absolute = "String(Math.abs(Math.trunc(value)))"
        else:
            precision = precision or "6"
            if number_type in {"e", "E"}:
                magnitude = "Math.abs(Number(value))"
                exponential = f"{magnitude}.toExponential({precision})"
                if number_type == "E":
                    exponential = f"({exponential}).toUpperCase()"
                exponential = (
                    f"({exponential}).replace(/([eE][+-])(\\d)$/,"
                    "(_, exponent, digit) => exponent + '0' + digit)"
                )
                infinity = "INF" if number_type == "E" else "inf"
                not_a_number = "NAN" if number_type == "E" else "nan"
                absolute = (
                    f"Number.isNaN({magnitude})?'{not_a_number}':"
                    f"Number.isFinite({magnitude})?{exponential}:'{infinity}'"
                )
                formatted = (
                    "((value)=>{const negative=value<0||Object.is(value,-0);"
                    f"return (negative?'-':'')+({absolute});}})({value})"
                )
            else:
                multiplier = " * 100" if number_type == "%" else ""
                suffix = " + '%'" if number_type == "%" else ""
                formatted = (
                    "((value)=>{const negative=value<0||Object.is(value,-0);"
                    "return (negative?'-':'')+"
                    f"Math.abs(Number(value){multiplier}).toFixed({precision})"
                    f"{suffix};}})({value})"
                )
                absolute_number = "Math.abs(Number(value))"
                if number_type == "%":
                    absolute_number = f"({absolute_number} * 100)"
                absolute = f"{absolute_number}.toFixed({precision}){suffix}"

        width = match.group("width")
        if width is None:
            self.write(formatted)
        elif match.group("zero"):
            self.write(
                "((value) => {const negative=value<0||Object.is(value,-0);"
                "return (negative?'-':'') + "
                f"({absolute}).padStart({width} - (negative?1:0), '0');}})"
                f"({value})"
            )
        else:
            self.write(f"({formatted}).padStart({width}, ' ')")

    def visit_Assert(self, node: ast.Assert):
        self.fill("__pyjsAssert__(")
        self.traverse(node.test)
        if node.msg:
            self.write(", () => ")
            self.traverse(node.msg)
        else:
            self.write(", undefined")
        self.write(", ")
        self.write(node.runtime_alias)
        self.write(");")


class HydrateGenerator(ast.NodeVisitor):
    def __init__(self, func: Function, transpiler: Transpiler):
        self.func = func
        self.transpiler = transpiler
        self.fill = transpiler.fill
        self.write = transpiler.write
        self.elements = set()
        self.self_id_set = False

    def add_self_id(self, self_):
        if not self.self_id_set:
            self.self_id_set = True
            self.fill("const self_id = this.get_data('self-id');")

    def visit_Assign(self, node: ast.Assign):
        reference = hydration_ref_call(node.value)
        if reference is None:
            return

        targets = []
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, Name)
                and target.value.id == "self"
                and issubclass(reference.obj.py_cls, (DOMElement, ProxyElement))
            ):
                assert len(node.targets) == 1
                self.elements.add(target.obj)
                targets.append(target)
        if targets:
            target = targets[0]
            self.add_self_id(target.value)
            self.fill()
            self.transpiler.traverse(target)
            if issubclass(reference.obj.py_cls, DOMElement):
                self.write(f" = document.getElementById(self_id+'-{target.attr}');")
            elif issubclass(reference.obj.py_cls, ProxyElement):
                self.write(
                    " = new "
                    f"{javascript_identifier(reference.obj.name)}()"
                    f"._hydrate(document.getElementById(self_id+'-{target.attr}'));"
                )
            elif issubclass(node.value.obj.py_cls, ContextProxy):
                self.write(f" = document.getElementById(self_id+'-{target.attr}');")

    def visit_Expr(self, node: ast.Expr):
        if isinstance(node.value, ast.Call):
            func = node.value.func
            if (
                isinstance(func, Attribute)
                and func.attr == "__init__"
                and isinstance(func.value, Call)
                and isinstance(func.value.func, Name)
                and func.value.func.id == "super"
            ):
                self.fill("super._hydrate();")
                return
            # TODO: this should probably just only allow addEventListener,
            #       a general customizable solution would be even better
            if isinstance(func, Attribute) and (
                func.value.obj in self.elements or func.attr == "addEventListener"
            ):
                self.transpiler.traverse(node)
