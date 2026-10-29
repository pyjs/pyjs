"""Analyze one source generation in a disposable CPython process."""

import ast
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import json
import linecache
import sys
from pathlib import Path
from types import ModuleType

from pyjs.analysis.analyzer import analyze_module, release_compilation
from pyjs.decorators import configure_js
from pyjs.language.snapshots import collect

ENTRY = "__pyjs_editor_entry__"


class Sources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, root: Path, overlays: dict[str, str], target: Path):
        self.root = root
        self.overlays = overlays
        self.target = target
        self.dependencies = {}
        self.texts = {}

    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None and spec.origin and spec.origin.endswith(".py"):
            filename = Path(spec.origin).resolve()
            if filename.is_relative_to(self.root) and not any(
                part.startswith(".") or part == "external"
                for part in filename.relative_to(self.root).parts
            ):
                spec.loader = self
                return spec
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        filename = str(Path(module.__spec__.origin).resolve())
        source = self.overlays.get(filename)
        if source is None:
            source = Path(filename).read_text(encoding="utf-8")
        self.dependencies[filename] = hashlib.sha256(source.encode()).hexdigest()
        self.texts[filename] = source
        if Path(filename) == self.target:
            if ENTRY in vars(module) or any(
                isinstance(node, ast.Name) and node.id == ENTRY for node in ast.walk(ast.parse(source))
            ):
                raise ValueError(f"Reserved editor entry name: {ENTRY}")
            source += f"\n\ndef {ENTRY}() -> None:\n    pass\n"
        module.__pyjs_source__ = source
        linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
        exec(compile(source, filename, "exec"), vars(module))


def analyze(root: Path, target: Path, overlays: dict[str, str]) -> dict:
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
    sources = Sources(root, overlays, target)
    sys.meta_path.insert(0, sources)
    # Explicitly selected workspace namespace packages take precedence over
    # unrelated installed packages with the same name (for example "tests").
    for depth in range(1, len(parts)):
        parent_name = ".".join(parts[:depth])
        directory = base.joinpath(*parts[:depth])
        if not (directory / "__init__.py").exists() and parent_name not in sys.modules:
            parent = ModuleType(parent_name)
            parent.__path__ = [str(directory)]
            parent.__package__ = parent_name
            parent.__spec__ = importlib.machinery.ModuleSpec(parent_name, loader=None, is_package=True)
            parent.__spec__.submodule_search_locations = parent.__path__
            sys.modules[parent_name] = parent
            if depth > 1 and ".".join(parts[:depth - 1]) in sys.modules:
                setattr(sys.modules[".".join(parts[:depth - 1])], parts[depth - 1], parent)
    module = importlib.import_module(name)
    # The synthetic root selects the module without calling any application function.
    configure_js(getattr(module, ENTRY), enabled=True)
    entry, _ = analyze_module(module, entry_point=getattr(module, ENTRY))
    try:
        modules = collect(entry, root, sources.texts, ENTRY)
        return modules[str(target)] | {"dependencies": sources.dependencies, "modules": modules}
    finally:
        release_compilation(entry)


def main():
    payload = json.loads(sys.stdin.read())
    try:
        result = analyze(Path(payload["root"]), Path(payload["path"]), payload["sources"])
        result["status"] = "ready"
    except BaseException as error:
        # SystemExit from imported code is an analysis failure, not a server shutdown.
        result = {"status": "error", "message": f"{type(error).__name__}: {error}",
                  "symbols": [], "occurrences": [], "dependencies": {}}
    Path(sys.argv[1]).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
