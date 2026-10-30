"""Whole-module analysis with exact-source caching and versioned results."""

import ast
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import CURSOR_QUERY_SCHEMA
from .diagnostics import error_diagnostics
from .store import SnapshotStore, cache_directory


class AnalysisSession:
    """Analyze through an interpreter containing PyJS and project dependencies.

    The service itself can run elsewhere. A selected interpreter's compiler
    sources and Python runtime determine its persistent cache namespace.
    """

    def __init__(self, root: Path, *, timeout: float = 30, cache_dir: Path | None = None,
                 interpreter: str | Path | None = None):
        self.root = root.resolve()
        self.timeout = timeout
        self.interpreter = os.fspath(interpreter) if interpreter is not None else sys.executable
        if interpreter is not None:
            self.interpreter = os.path.abspath(shutil.which(self.interpreter) or self.interpreter)
        self.cache_dir = cache_dir
        self.documents: dict[str, tuple[int, str]] = {}
        self.cache: dict[str, dict] = {}
        self.store = (SnapshotStore(cache_dir if cache_dir is not None else cache_directory(self.root))
                      if self.interpreter == sys.executable else None)
        self.query_schema = CURSOR_QUERY_SCHEMA if self.interpreter == sys.executable else None
        self.analysis_lock = threading.RLock()
        self.index_state = "idle"
        self.syntax: dict[str, bool] = {}
        self.lock = threading.RLock()
        self.revision = 0
        self.process = None
        self.stopped = False

    def _ensure_runtime(self) -> None:
        if self.store is not None:
            return
        try:
            probe = subprocess.run([
                self.interpreter, '-I', '-c',
                'import json,sys; from pathlib import Path; import pyjs.language as language; '
                'from pyjs.language.store import cache_directory; '
                'print(json.dumps([str(cache_directory(Path(sys.argv[1]))), '
                'getattr(language, "CURSOR_QUERY_SCHEMA", 0)]))', str(self.root),
            ], cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=min(self.timeout, 5), check=True)
            name, query_schema = json.loads(probe.stdout)
            directory = Path(name)
            if not directory.is_absolute():
                raise ValueError('Expected an absolute cache directory')
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ValueError('The selected interpreter needs PyJS with module analysis support') from error
        if self.cache_dir is not None:
            directory = self.cache_dir / directory.name
        self.store = SnapshotStore(directory)
        self.query_schema = query_schema

    def path(self, uri: str) -> Path:
        if not isinstance(uri, str):
            raise ValueError("Expected a local file URI string")
        parsed = urlparse(uri)
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            raise ValueError("Expected a local file URI")
        name = unquote(parsed.path)
        if os.name == "nt" and name.startswith("/"):
            name = name[1:]
        path = Path(name).resolve()
        if not path.is_relative_to(self.root) or path.suffix != ".py":
            raise ValueError("Expected a Python file inside the workspace")
        return path

    def update(self, uri: str, version: int, text: str) -> None:
        if not isinstance(version, int) or isinstance(version, bool) or not isinstance(text, str):
            raise ValueError("Expected integer version and source text")
        path = str(self.path(uri))
        with self.lock:
            previous = self.documents.get(path)
            if previous and (version < previous[0] or (version == previous[0] and text != previous[1])):
                raise ValueError("Document version must increase when its source changes")
            self.documents[path] = (version, text)

    def replace_documents(self, documents: list[dict]) -> None:
        """Atomically replace the editor's open buffers for one source generation."""
        replacement = {}
        for document in documents:
            path = str(self.path(document["uri"]))
            version, text = document["version"], document["text"]
            if not isinstance(version, int) or isinstance(version, bool) or not isinstance(text, str):
                raise ValueError("Expected integer version and source text")
            if path in replacement:
                raise ValueError("Duplicate document URI")
            replacement[path] = (version, text)
        with self.lock:
            self.documents = replacement

    def close(self, uri: str) -> None:
        with self.lock:
            self.documents.pop(str(self.path(uri)), None)


    def cached_snapshot(self, uri: str) -> dict | None:
        path = str(self.path(uri))
        with self.lock:
            version, text = self.documents[path] if path in self.documents else (0, Path(path).read_text(encoding="utf-8"))
            sources = {name: item[1] for name, item in self.documents.items()}
            if not self._valid_sources(sources):
                return None
            self._ensure_runtime()
            cached = self.cache.get(path) or self.store.get(path)
            if (cached and cached.get("sourceHash") == hashlib.sha256(text.encode()).hexdigest()
                    and self._unchanged(cached["dependencies"], sources)):
                self.cache[path] = cached
                self.revision = max(self.revision, cached['revision'])
                return cached | {"uri": uri, "version": version, "schemaVersion": 1,
                                 "cached": True, "diagnostics": []}
        return None

    def _valid_sources(self, sources: dict[str, str]) -> bool:
        for source in sources.values():
            digest = hashlib.sha256(source.encode()).hexdigest()
            if digest not in self.syntax:
                try:
                    ast.parse(source)
                    self.syntax[digest] = True
                except SyntaxError:
                    self.syntax[digest] = False
            if not self.syntax[digest]:
                return False
        return True

    def index_project(self) -> None:
        """Warm the configured application and retain every module it visits."""
        try:
            config = tomllib.loads((self.root / "pyproject.toml").read_text())
            application = config.get("tool", {}).get("pyjs", {}).get("application", "")
            if not isinstance(application, str) or not application:
                return
            module = application.split(":" , 1)[0]
            relative = Path(module) if module.endswith('.py') else Path(*module.split('.'))
            candidates = [base / suffix for base in (self.root, self.root / 'src')
                          for suffix in ([relative] if module.endswith('.py') else
                                         [relative / '__init__.py', relative.with_suffix('.py')])]
            path = next((item.resolve() for item in candidates if item.is_file()), None)
            if path is None or not path.is_relative_to(self.root):
                raise ValueError('Configured application is not a workspace Python module')
            self.index_state = "indexing"
            result = self.snapshot(path.as_uri())
            self.index_state = "ready" if result["status"] == "ready" else result["status"]
        except (OSError, ValueError, RuntimeError):
            self.index_state = "error"

    def snapshot(self, uri: str, *, force: bool = False) -> dict:
        cached = None if force else self.cached_snapshot(uri)
        if cached is not None:
            return cached
        with self.analysis_lock:
            return self._analyze(uri, force=force)

    def completion(self, uri: str, line: int, column: int) -> dict:
        """Query a name using one-based lines and Unicode code-point columns."""
        with self.analysis_lock:
            return self._analyze(uri, force=True, query={'action': 'complete', 'line': line, 'column': column})

    def signatures(self, uri: str, line: int, column: int) -> dict:
        """Query the innermost call at a Unicode code-point source position."""
        with self.analysis_lock:
            return self._analyze(uri, force=True, query={'action': 'signatures', 'line': line, 'column': column})

    def _analyze(self, uri: str, *, force: bool = False, query: dict | None = None) -> dict:
        path = str(self.path(uri))
        with self.lock:
            if self.stopped:
                raise RuntimeError("Analysis session has shut down")
            version, text = self.documents[path] if path in self.documents else (0, Path(path).read_text(encoding="utf-8"))
            sources = {name: item[1] for name, item in self.documents.items()}
            cached = None if force else self.cached_snapshot(uri)
            open_sources = sources.copy()
            sources[path] = text
        result = {"uri": uri, "version": version, "schemaVersion": 1,
                  "sourceHash": hashlib.sha256(text.encode()).hexdigest(), "cached": False,
                  "symbols": [], "occurrences": [], "diagnostics": [], "message": "", "revision": 0}
        if query is not None:
            lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            line, column = query['line'], query['column']
            if (type(line) is not int or type(column) is not int or not 1 <= line <= len(lines)
                    or not 0 <= column <= len(lines[line - 1])):
                raise ValueError('Query position is outside the source buffer')
            result |= {'items': [], 'signatures': [], 'truncated': False, 'line': line, 'column': column}
        if cached is not None:
            return cached
        try:
            # No execution while any open source in this generation is syntactically incomplete.
            for filename, source in sources.items():
                ast.parse(source, filename)
        except SyntaxError as error:
            return result | {"status": "pending", "message": f"Waiting for valid Python: {error}",
                             "diagnostics": error_diagnostics(error)}
        self._ensure_runtime()
        if query is not None and self.query_schema != CURSOR_QUERY_SCHEMA:
            raise ValueError('The selected interpreter needs PyJS with cursor query support')
        with tempfile.TemporaryDirectory(prefix="pyjs-analysis-") as directory:
            output = Path(directory) / "snapshot.json"
            analyzed = {"status": "error", "message": "Analysis worker exited unexpectedly", "dependencies": {}}
            try:
                with (Path(directory) / "stderr.txt").open("wb") as stderr:
                    with self.lock:
                        if self.stopped:
                            raise RuntimeError("Analysis session has shut down")
                        process = subprocess.Popen(
                            [self.interpreter, "-I", "-c",
                             "import sys; startup = frozenset(sys.modules); "
                             "from pyjs.language.worker import main; main(startup)", str(output)],
                            stdin=subprocess.PIPE, text=True, stdout=subprocess.DEVNULL,
                            stderr=stderr, cwd=self.root, start_new_session=os.name != "nt",
                        )
                        self.process = process
                    try:
                        process.communicate(json.dumps({"root": str(self.root), "path": path,
                                                        "sources": sources, "query": query}), timeout=self.timeout)
                    finally:
                        self._terminate(process)
                        with self.lock:
                            self.process = None
                if process.returncode == 0 and output.exists():
                    analyzed = json.loads(output.read_text(encoding="utf-8"))
            except subprocess.TimeoutExpired:
                analyzed['message'] = 'Module analysis timed out'
            journal = output.with_suffix('.dependencies.jsonl')
            if journal.exists():
                for record in journal.read_text(encoding='utf-8').splitlines():
                    try:
                        name, digest = json.loads(record)
                    except ValueError:
                        continue  # A killed worker may leave its final journal record incomplete.
                    analyzed['dependencies'][name] = digest
        with self.lock:
            current = {name: item[1] for name, item in self.documents.items()}
            if (not self._valid_sources(current)
                    or (analyzed['status'] != 'ready' and current != open_sources)
                    or not self._unchanged({path: result["sourceHash"]}, current)
                    or not self._unchanged(analyzed["dependencies"], current)):
                return result | {"status": "superseded", "message": "Dependency changed during analysis"}
            self.revision = self.store.next_revision(self.revision)
            modules = analyzed.pop("modules", {})
            result |= analyzed | {"revision": self.revision}
            if result["status"] == "ready":
                retained = {name: snapshot | {"dependencies": result["dependencies"],
                            "revision": self.revision} for name, snapshot in modules.items()}
                self.cache.update(retained)
                self.store.put(retained)
        return result

    def shutdown(self) -> None:
        with self.lock:
            self.stopped = True
            if self.process is not None:
                self._terminate(self.process)

    @staticmethod
    def _terminate(process) -> None:
        if process.poll() is None:
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()

    @staticmethod
    def _unchanged(dependencies: dict[str, str], sources: dict[str, str]) -> bool:
        try:
            return all(hashlib.sha256((sources[name] if name in sources else Path(name).read_text(encoding="utf-8")).encode()).hexdigest() == digest
                       for name, digest in dependencies.items())
        except (OSError, UnicodeError):
            return False
