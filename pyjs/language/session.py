"""Whole-module analysis with exact-source caching and versioned results."""

import ast
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlparse

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
            self.interpreter = os.path.abspath(self.interpreter)
        self.cache_dir = cache_dir
        self.documents: dict[str, tuple[int, str]] = {}
        self.cache: dict[str, dict] = {}
        self.store = (SnapshotStore(cache_dir if cache_dir is not None else cache_directory(self.root))
                      if self.interpreter == sys.executable else None)
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
                'import json,sys; from pathlib import Path; '
                'from pyjs.language.store import cache_directory; '
                'print(json.dumps(str(cache_directory(Path(sys.argv[1])))))', str(self.root),
            ], cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=min(self.timeout, 5), check=True)
            directory = Path(json.loads(probe.stdout))
            if not directory.is_absolute():
                raise ValueError('Expected an absolute cache directory')
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ValueError('The selected interpreter needs PyJS with module analysis support') from error
        if self.cache_dir is not None:
            directory = self.cache_dir / directory.name
        self.store = SnapshotStore(directory)

    def path(self, uri: str) -> Path:
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
                return cached | {"uri": uri, "version": version, "schemaVersion": 1, "cached": True}
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
            relative = Path(*application.split(":" , 1)[0].split(".")).with_suffix(".py")
            path = self.root / relative
            if not path.is_file():
                path = self.root / "src" / relative
            if not path.is_file():
                return
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

    def _analyze(self, uri: str, *, force: bool = False) -> dict:
        path = str(self.path(uri))
        with self.lock:
            if self.stopped:
                raise RuntimeError("Analysis session has shut down")
            version, text = self.documents[path] if path in self.documents else (0, Path(path).read_text(encoding="utf-8"))
            sources = {name: item[1] for name, item in self.documents.items()}
            cached = None if force else self.cached_snapshot(uri)
            sources[path] = text
        result = {"uri": uri, "version": version, "schemaVersion": 1,
                  "sourceHash": hashlib.sha256(text.encode()).hexdigest(), "cached": False,
                  "symbols": [], "occurrences": [], "message": "", "revision": 0}
        if cached is not None:
            return cached
        try:
            # No execution while any open source in this generation is syntactically incomplete.
            for filename, source in sources.items():
                ast.parse(source, filename)
        except SyntaxError as error:
            return result | {"status": "pending", "message": f"Waiting for valid Python: {error}"}
        self._ensure_runtime()
        with tempfile.TemporaryDirectory(prefix="pyjs-analysis-") as directory:
            output = Path(directory) / "snapshot.json"
            try:
                with (Path(directory) / "stderr.txt").open("wb") as stderr:
                    with self.lock:
                        if self.stopped:
                            raise RuntimeError("Analysis session has shut down")
                        process = subprocess.Popen(
                            [self.interpreter, "-I", "-m", "pyjs.language.worker", str(output)],
                            stdin=subprocess.PIPE, text=True, stdout=subprocess.DEVNULL,
                            stderr=stderr, cwd=self.root, start_new_session=os.name != "nt",
                        )
                        self.process = process
                    try:
                        process.communicate(json.dumps({"root": str(self.root), "path": path,
                                                        "sources": sources}), timeout=self.timeout)
                    finally:
                        self._terminate(process)
                        with self.lock:
                            self.process = None
                if process.returncode != 0 or not output.exists():
                    return result | {"status": "error", "message": "Analysis worker exited unexpectedly"}
                analyzed = json.loads(output.read_text(encoding="utf-8"))
            except subprocess.TimeoutExpired:
                return result | {"status": "error", "message": "Module analysis timed out"}
        with self.lock:
            current = {name: item[1] for name, item in self.documents.items()}
            if (not self._valid_sources(current)
                    or not self._unchanged({path: result["sourceHash"]}, current)
                    or not self._unchanged(analyzed["dependencies"], current)):
                return result | {"status": "superseded", "message": "Dependency changed during analysis"}
            self.revision += 1
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
