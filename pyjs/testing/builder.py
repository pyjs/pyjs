import contextlib
import hashlib
import importlib
import linecache
import sys
import sysconfig
import types
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyjs.javascript.sourcemap import SourceMap
from pyjs.javascript.transpiler import bundle_with_source_map
from pyjs.testing.assertion_rewriter import TestingExtension
from pyjs.tooling.npm import NpmImport

ENTRYPOINT_MODULE = "__pyjs_test_entrypoint__"
PYJS_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBRARY_ROOTS = tuple({Path(sysconfig.get_path(name)).resolve() for name in ("purelib", "platlib")})


def compute_testing_signature() -> str:
    digest = hashlib.sha256()
    for path in sorted(PYJS_PACKAGE_ROOT.rglob("*.py")):
        digest.update(str(path.relative_to(PYJS_PACKAGE_ROOT)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class SelectedTest:
    nodeid: str
    module_name: str
    function_name: str
    android_dependencies: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "nodeid": self.nodeid,
            "module_name": self.module_name,
            "function_name": self.function_name,
            "android_dependencies": list(self.android_dependencies),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SelectedTest:
        return cls(
            nodeid=payload["nodeid"],
            module_name=payload["module_name"],
            function_name=payload["function_name"],
            android_dependencies=tuple(payload.get("android_dependencies", ())),
        )


@dataclass(frozen=True)
class BrowserBundle:
    javascript: str
    css: str
    source_map: SourceMap = SourceMap()
    npm_imports: tuple[NpmImport, ...] = ()


class BrowserBundleBuilder:
    def __init__(
        self,
        project_root: Path,
        cache_dir: Path,
    ):
        self.project_root = project_root.resolve()
        self.cache_dir = cache_dir.resolve()

    @property
    def entrypoint_path(self) -> Path:
        return self.cache_dir / f"{ENTRYPOINT_MODULE}.py"

    def build(self, selected_tests: list[SelectedTest], run_id: str) -> BrowserBundle:
        source = generate_entrypoint_source(run_id, selected_tests)
        module_names = [selected.module_name for selected in selected_tests]
        extension = TestingExtension(selected_tests)
        with fresh_project_imports(self.project_root, self.cache_dir, run_id, module_names):
            entrypoint = load_entrypoint_module(source, self.entrypoint_path)
            try:
                generated, css = bundle_with_source_map(
                    entrypoint.main,
                    True,
                    (extension,),
                )
            finally:
                sys.modules.pop(ENTRYPOINT_MODULE, None)
                linecache.cache.pop(str(self.entrypoint_path), None)
        source_map = generated.source_map.shifted(2)
        return BrowserBundle(
            generated.javascript,
            css or "",
            source_map,
            generated.npm_imports,
        )


def is_within(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory)
    except OSError, ValueError:
        return False
    return True


def module_is_from_project(module: types.ModuleType, project_root: Path) -> bool:
    paths: list[Path] = []
    if module_file := getattr(module, "__file__", None):
        paths.append(Path(module_file))
    if module_path := getattr(module, "__path__", None):
        paths.extend(Path(path) for path in module_path)
    # The repository root can also be the pytest project root. Keep the compiler
    # modules loaded while replacing only the application and test modules.
    # A project-local virtual environment is not application source: reloading
    # pytest changes Session identity underneath already collected fixtures.
    return any(
        is_within(path, project_root) and not is_within(path, PYJS_PACKAGE_ROOT)
        and not any(is_within(path, library) for library in PYTHON_LIBRARY_ROOTS)
        for path in paths
    )


def clear_project_modules(project_root: Path, module_names: list[str]) -> None:
    importlib.invalidate_caches()
    # Django owns registered model classes for the lifetime of its app registry.
    # Reimporting their modules while compiling a client replaces registry
    # entries but leaves existing model/relationship references stale. Loaded
    # admin autodiscovery modules also own process-lifetime registrations. Do not
    # import or initialize optional Django just to discover this boundary.
    django_apps = sys.modules.get("django.apps")
    registry = getattr(django_apps, "apps", None)
    registered_modules = (
        {model.__module__ for model in registry.get_models(include_auto_created=True)}
        if registry is not None and registry.models_ready else set()
    )
    if registry is not None and registry.models_ready:
        admin_names = tuple(config.name + ".admin" for config in registry.get_app_configs())
        admin_prefixes = tuple(name + "." for name in admin_names)
        registered_modules.update(
            name for name in sys.modules if name in admin_names or name.startswith(admin_prefixes)
        )
    # A cached child must remain attached to its original package ancestry:
    # importing it does not reattach it to a newly imported parent package.
    preserved = set(registered_modules)
    for name in registered_modules:
        parts = name.split(".")
        preserved.update(".".join(parts[:index]) for index in range(1, len(parts)))
    selected_names: set[str] = set()
    for module_name in module_names:
        parts = module_name.split(".")
        selected_names.update(".".join(parts[:index]) for index in range(1, len(parts) + 1))
    # Resolve namespace-package paths before removing any parent. Their lazy
    # __path__ lookup consults sys.modules[parent] after cache invalidation.
    removed = [
        (name, module) for name, module in list(sys.modules.items())
        if name not in preserved and (name in selected_names or (
            module is not None and module_is_from_project(module, project_root)
        ))
    ]
    for name, module in removed:
        sys.modules.pop(name, None)
        parent_name, _, child_name = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        # Retained packages must not expose stale non-model child modules via
        # `from package import child`, which can skip sys.modules entirely.
        if module is not None and parent is not None and vars(parent).get(child_name) is module:
            delattr(parent, child_name)
    for path in list(sys.path_importer_cache):
        if path and is_within(Path(path), project_root):
            sys.path_importer_cache.pop(path, None)


@contextmanager
def fresh_project_imports(
    project_root: Path,
    cache_dir: Path,
    generation: str,
    module_names: list[str],
) -> Iterator[None]:
    """Import a generation without project bytecode or stale client children.

    Registered Django models, loaded admin modules and their package ancestry
    remain process-owned; changing those requires restarting the process.
    """
    clear_project_modules(project_root, module_names)
    project_path = str(project_root)
    sys.path.insert(0, project_path)
    previous_pycache_prefix = sys.pycache_prefix
    previous_dont_write_bytecode = sys.dont_write_bytecode
    # A unique cache prefix prevents a same-size edit within one filesystem timestamp
    # interval from loading the previous generation's valid-looking .pyc file.
    sys.pycache_prefix = str(cache_dir / "import-cache" / generation)
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        clear_project_modules(project_root, module_names)
        sys.dont_write_bytecode = previous_dont_write_bytecode
        sys.pycache_prefix = previous_pycache_prefix
        with contextlib.suppress(ValueError):
            sys.path.remove(project_path)


def load_entrypoint_module(source: str, filename: Path) -> types.ModuleType:
    filename_string = str(filename)
    linecache.cache[filename_string] = (
        len(source),
        None,
        source.splitlines(keepends=True),
        filename_string,
    )
    module = types.ModuleType(ENTRYPOINT_MODULE)
    module.__file__ = filename_string
    module.__package__ = ""
    sys.modules[ENTRYPOINT_MODULE] = module
    try:
        exec(compile(source, filename_string, "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(ENTRYPOINT_MODULE, None)
        linecache.cache.pop(filename_string, None)
        raise
    return module


def generate_entrypoint_source(
    run_id: str,
    selected_tests: list[SelectedTest],
) -> str:
    lines = [
        "from pyjs.testing.client.runtime import BrowserTest, initialize_test_runtime",
        "",
    ]
    for index, selected in enumerate(selected_tests):
        lines.append(
            f"from {selected.module_name} import {selected.function_name} as __pyjs_test_{index}"
        )

    lines.extend(["", "", "def main():", "    selected_tests: list[BrowserTest] = ["])
    for index, selected in enumerate(selected_tests):
        lines.extend(
            [
                "        BrowserTest(",
                f"            {selected.nodeid!r},",
                f"            {selected.module_name!r},",
                f"            {selected.function_name!r},",
                f"            __pyjs_test_{index},",
                "        ),",
            ]
        )
    lines.extend(
        [
            "    ]",
            f"    initialize_test_runtime({run_id!r}, selected_tests)",
            "",
        ]
    )
    return "\n".join(lines)
