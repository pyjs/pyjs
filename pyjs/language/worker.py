"""Analyze one source generation in a disposable CPython process."""

import ast
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import io
import json
import linecache
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from pyjs.analysis.analyzer import analyze_module, release_compilation
from pyjs.decorators import configure_js
from pyjs.language.snapshots import collect

ENTRY = "__pyjs_editor_entry__"


class Sources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, root: Path, overlays: dict[str, str], target: Path, journal: Path):
        self.root = root
        self.overlays = overlays
        self.target = target
        self.journal = journal
        self.dependencies = {}
        self.texts = {}

    def find_spec(self, fullname, path=None, target=None):
        leaf = fullname.rsplit(".", 1)[-1]
        namespaces = []
        for directory in path if path is not None else sys.path:
            base = Path(directory).resolve()
            spec = importlib.machinery.PathFinder.find_spec(fullname, [str(base)])
            for filename in (base / leaf / "__init__.py", base / (leaf + ".py")):
                if filename.name != '__init__.py' and spec is not None and spec.loader is not None and spec.submodule_search_locations is not None:
                    break
                if str(filename) in self.overlays and self.allowed(filename):
                    return importlib.util.spec_from_file_location(
                        fullname, filename, loader=self,
                        submodule_search_locations=[str(filename.parent)] if filename.name == '__init__.py' else None,
                    )
            if spec is not None and spec.loader is not None:
                if spec.origin and spec.origin.endswith(".py") and self.allowed(Path(spec.origin).resolve()):
                    spec.loader = self
                    return spec
                return None
            if spec is not None:
                namespaces.extend(spec.submodule_search_locations or ())
            package = base / leaf
            if (self.allowed(package) and str(package) not in namespaces
                    and any(Path(name).is_relative_to(package) for name in self.overlays)):
                namespaces.append(str(package))
        if namespaces:
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = namespaces
            return spec
        return None

    def allowed(self, filename):
        return filename.is_relative_to(self.root) and not any(
            part.startswith(".") or part == "external"
            for part in filename.relative_to(self.root).parts
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        filename = str(Path(module.__spec__.origin).resolve())
        source = self.overlays.get(filename)
        if source is None:
            source = Path(filename).read_text(encoding="utf-8")
        self.dependencies[filename] = hashlib.sha256(source.encode()).hexdigest()
        self.texts[filename] = source
        # Flush before execution so the parent can validate even a killed worker.
        with self.journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps([filename, self.dependencies[filename]]) + "\n")
        # Match Python's physical lines without changing overlay identity.
        source = source.replace('\r\n', '\n').replace('\r', '\n')
        if Path(filename) == self.target:
            if ENTRY in vars(module) or any(
                isinstance(node, ast.Name) and node.id == ENTRY for node in ast.walk(ast.parse(source))
            ):
                raise ValueError(f"Reserved editor entry name: {ENTRY}")
            source += f"\n\ndef {ENTRY}() -> None:\n    pass\n"
        module.__pyjs_source__ = source
        linecache.cache[filename] = (len(source), None, io.StringIO(source).readlines(), filename)
        exec(compile(source, filename, "exec"), vars(module))


def analyze(root: Path, target: Path, overlays: dict[str, str], journal: Path,
            startup_modules: frozenset[str]) -> dict:
    source = overlays[str(target)]
    ast.parse(source, str(target))
    base = root / "src" if target.is_relative_to(root / "src") else root
    parts = list(target.relative_to(base).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or not all(part.isidentifier() for part in parts):
        raise ValueError("Module path must be a Python import path beneath the workspace or src directory")
    name = ".".join(parts)
    sys.path[:0] = [str(base), str(root)]
    sources = Sources(root, overlays, target, journal)
    protected = startup_modules | {'pyjs'}
    # Saved workspace imports can also collide with modules needed to start the worker.
    for prefix, existing in list(sys.modules.items()):
        if ("." in prefix or prefix in protected
                or getattr(getattr(existing, '__spec__', None), 'origin', None) in ('built-in', 'frozen')):
            continue
        spec = sources.find_spec(prefix, [str(base), str(root)])
        if spec is not None and spec.loader is sources and getattr(existing, '__file__', None) != spec.origin:
            for loaded in list(sys.modules):
                if loaded == prefix or loaded.startswith(prefix + "."):
                    del sys.modules[loaded]
    # Bootstrap imports must not claim an explicitly selected workspace identity.
    for filename in overlays:
        file = Path(filename)
        if not file.is_relative_to(base):
            continue
        names = list(file.relative_to(base).with_suffix("").parts)
        if names[-1] == "__init__":
            names.pop()
        for depth in range(1, len(names) + 1):
            prefix = ".".join(names[:depth])
            if names[0] in protected:
                continue
            existing = sys.modules.get(prefix)
            origin = getattr(existing, "__file__", None)
            expected = base.joinpath(*names[:depth])
            if origin and Path(origin).resolve() not in (expected.with_suffix(".py"), expected / "__init__.py"):
                for loaded in list(sys.modules):
                    if loaded == prefix or loaded.startswith(prefix + "."):
                        del sys.modules[loaded]
    sys.meta_path.insert(0, sources)
    # Explicitly selected workspace namespace packages take precedence over
    # unrelated installed packages with the same name (for example "tests").
    for depth in range(1, len(parts)):
        parent_name = ".".join(parts[:depth])
        directory = base.joinpath(*parts[:depth])
        if (not (directory / "__init__.py").exists()
                and str(directory / "__init__.py") not in overlays and parent_name not in sys.modules):
            parent = ModuleType(parent_name)
            parent.__path__ = [str(directory)]
            parent.__package__ = parent_name
            parent.__spec__ = importlib.machinery.ModuleSpec(parent_name, loader=None, is_package=True)
            parent.__spec__.submodule_search_locations = parent.__path__
            sys.modules[parent_name] = parent
            if depth > 1 and ".".join(parts[:depth - 1]) in sys.modules:
                setattr(sys.modules[".".join(parts[:depth - 1])], parts[depth - 1], parent)
    module = importlib.import_module(name)
    if getattr(module, '__file__', None) != str(target) or not hasattr(module, ENTRY):
        raise ValueError('Selected module conflicts with an interpreter startup or compiler module')
    # The synthetic root selects the module without calling any application function.
    configure_js(getattr(module, ENTRY), enabled=True)
    entry, _ = analyze_module(module, entry_point=getattr(module, ENTRY))
    try:
        modules = collect(entry, root, sources.texts, ENTRY)
        return modules[str(target)] | {"dependencies": sources.dependencies, "modules": modules}
    finally:
        release_compilation(entry)


def main(startup_modules: frozenset[str] | None = None):
    if startup_modules is None:
        # Direct -m invocation must use the same pre-compiler import baseline.
        probe = subprocess.run([sys.executable, '-I', '-c',
                                'import sys; print("\\n".join(sys.modules))'],
                               capture_output=True, text=True, check=True)
        startup_modules = frozenset(probe.stdout.splitlines())
    payload = json.loads(sys.stdin.read())
    try:
        result = analyze(Path(payload["root"]), Path(payload["path"]), payload["sources"],
                         Path(sys.argv[1]).with_suffix(".dependencies.jsonl"), startup_modules)
        result["status"] = "ready"
    except BaseException as error:
        # SystemExit from imported code is an analysis failure, not a server shutdown.
        result = {"status": "error", "message": f"{type(error).__name__}: {error}",
                  "symbols": [], "occurrences": [], "dependencies": {}}
    Path(sys.argv[1]).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
