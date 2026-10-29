"""Disposable, versioned semantic snapshots outside the source tree."""

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path


def cache_directory(root: Path) -> Path:
    engine = hashlib.sha256()
    engine.update(f"{sys.executable}:{sys.version}".encode())
    package = Path(__file__).resolve().parents[1]
    for path in sorted(package.rglob("*.py")):
        engine.update(str(path.relative_to(package)).encode())
        engine.update(path.read_bytes())
    key = hashlib.sha256((str(root) + engine.hexdigest()).encode()).hexdigest()
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "pyjs" / "analysis" / key


class SnapshotStore:
    def __init__(self, directory: Path):
        self.path = directory / "snapshots.sqlite3"
        self.available = True
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with self.connect() as database:
                database.execute("CREATE TABLE IF NOT EXISTS snapshots (path TEXT PRIMARY KEY, data TEXT NOT NULL)")
                database.execute("CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY CHECK (id = 1), value INTEGER NOT NULL)")
                if database.execute("SELECT value FROM revisions WHERE id = 1").fetchone() is None:
                    maximum = max((json.loads(row[0]).get('revision', 0) for row in
                                   database.execute('SELECT data FROM snapshots')), default=0)
                    database.execute('INSERT OR IGNORE INTO revisions VALUES (1, ?)', (maximum,))
        except (OSError, ValueError, TypeError, sqlite3.Error):
            self.available = False

    def connect(self):
        return sqlite3.connect(self.path, timeout=1)

    def next_revision(self, minimum: int) -> int:
        if self.available:
            try:
                with self.connect() as database:
                    database.execute('UPDATE revisions SET value = max(value, ?) + 1 WHERE id = 1', (minimum,))
                    return database.execute('SELECT value FROM revisions WHERE id = 1').fetchone()[0]
            except (OSError, sqlite3.Error):
                # Do not mix local revisions with persisted snapshots after allocation fails.
                self.available = False
        return minimum + 1

    def get(self, path: str) -> dict | None:
        if not self.available:
            return None
        try:
            with self.connect() as database:
                row = database.execute("SELECT data FROM snapshots WHERE path = ?", (path,)).fetchone()
            return json.loads(row[0]) if row else None
        except (OSError, ValueError, sqlite3.Error):
            return None

    def put(self, snapshots: dict[str, dict]) -> None:
        if not self.available:
            return
        try:
            with self.connect() as database:
                database.executemany("INSERT OR REPLACE INTO snapshots VALUES (?, ?)",
                                     ((path, json.dumps(data)) for path, data in snapshots.items()))
        except (OSError, sqlite3.Error):
            pass  # An unwritable cache must not disable live analysis.
