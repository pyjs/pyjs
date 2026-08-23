"""Persistent object and event storage for the local Stripe simulator."""

import json
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class SimulatorStore:
    """Small SQLite object and event store shared by simulator requests."""

    def __init__(self, database: str | Path = ":memory:"):
        self.connection = sqlite3.connect(str(database), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS objects (
                    kind TEXT NOT NULL,
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    delivered INTEGER NOT NULL DEFAULT 0,
                    last_status INTEGER,
                    last_error TEXT NOT NULL DEFAULT '',
                    last_attempt_at INTEGER,
                    delivery_state TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS delivery_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    attempted_at INTEGER NOT NULL,
                    signature_mode TEXT NOT NULL,
                    status INTEGER,
                    error TEXT NOT NULL DEFAULT '',
                    delivered INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    path TEXT NOT NULL,
                    key TEXT NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY (path, key)
                );
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            event_columns = {
                row["name"]
                for row in self.connection.execute("PRAGMA table_info(events)")
            }
            for name, definition in {
                "last_status": "INTEGER",
                "last_error": "TEXT NOT NULL DEFAULT ''",
                "last_attempt_at": "INTEGER",
                "delivery_state": "TEXT NOT NULL DEFAULT 'pending'",
            }.items():
                if name not in event_columns:
                    self.connection.execute(
                        f"ALTER TABLE events ADD COLUMN {name} {definition}"
                    )
            self.connection.execute(
                """
                UPDATE events SET delivery_state = CASE
                    WHEN delivered = 1 THEN 'delivered'
                    WHEN attempts > 0 THEN 'failed'
                    ELSE 'pending'
                END
                WHERE delivery_state IS NULL OR delivery_state = 'pending'
                """
            )
        if self.metadata("clock") is None:
            self.set_metadata("clock", str(int(time.time())))
        if self.metadata("delivery_mode") is None:
            self.set_metadata("delivery_mode", "automatic")

    def close(self) -> None:
        self.connection.close()

    def reset(self) -> None:
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM objects")
            self.connection.execute("DELETE FROM events")
            self.connection.execute("DELETE FROM delivery_attempts")
            self.connection.execute("DELETE FROM idempotency")
            self.connection.execute("DELETE FROM metadata")
            self.set_metadata("clock", str(int(time.time())))
            self.set_metadata("delivery_mode", "automatic")

    def metadata(self, key: str) -> str | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_metadata(self, key: str, value: str) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO metadata (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def now(self) -> int:
        return int(self.metadata("clock") or time.time())

    def advance(self, seconds: int) -> int:
        value = self.now() + seconds
        self.set_metadata("clock", str(value))
        return value

    def new_id(self, prefix: str) -> str:
        key = f"counter:{prefix}"
        with self.lock:
            value = int(self.metadata(key) or "0") + 1
            self.set_metadata(key, str(value))
        return f"{prefix}_local_{value:08d}"

    def put(self, kind: str, value: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(value)
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO objects (kind, id, data) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    data = excluded.data
                """,
                (kind, result["id"], json.dumps(result)),
            )
        return result

    def get(self, kind: str, object_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT data FROM objects WHERE kind = ? AND id = ?",
                (kind, object_id),
            ).fetchone()
        return None if row is None else json.loads(row["data"])

    def list(self, kind: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT data FROM objects WHERE kind = ? ORDER BY rowid",
                (kind,),
            ).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def idempotent(self, path: str, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        with self.lock:
            row = self.connection.execute(
                "SELECT data FROM idempotency WHERE path = ? AND key = ?",
                (path, key),
            ).fetchone()
        return None if row is None else json.loads(row["data"])

    def remember(self, path: str, key: str, value: Mapping[str, Any]) -> None:
        if not key:
            return
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO idempotency (path, key, data) VALUES (?, ?, ?)",
                (path, key, json.dumps(dict(value))),
            )

    def add_event(self, event: Mapping[str, Any], *, pending: bool = False) -> None:
        state = "pending" if pending else "not_configured"
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO events (id, type, data, delivery_state)
                VALUES (?, ?, ?, ?)
                """,
                (event["id"], event["type"], json.dumps(dict(event)), state),
            )

    def set_event_state(self, event_id: str, state: str) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE events SET delivery_state = ? WHERE id = ?",
                (state, event_id),
            )

    def event_attempt(
        self,
        event_id: str,
        delivered: bool,
        *,
        signature_mode: str = "valid",
        status: int | None,
        error: str,
    ) -> None:
        attempted_at = int(time.time())
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO delivery_attempts (
                    event_id, attempted_at, signature_mode, status, error, delivered
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    attempted_at,
                    signature_mode,
                    status,
                    error,
                    int(delivered),
                ),
            )
            self.connection.execute(
                """
                UPDATE events
                SET attempts = attempts + 1,
                    delivered = CASE WHEN delivered = 1 THEN 1 ELSE ? END,
                    last_status = ?,
                    last_error = ?,
                    last_attempt_at = ?,
                    delivery_state = CASE
                        WHEN delivered = 1 OR ? = 1 THEN 'delivered'
                        ELSE 'failed'
                    END
                WHERE id = ?
                """,
                (
                    int(delivered),
                    status,
                    error,
                    attempted_at,
                    int(delivered),
                    event_id,
                ),
            )

    def events(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT data, attempts, delivered, last_status, last_error,
                       last_attempt_at, delivery_state
                FROM events ORDER BY rowid
                """
            ).fetchall()
        return [
            {
                **json.loads(row["data"]),
                "delivery_attempts": row["attempts"],
                "delivery_state": row["delivery_state"],
                "delivered": bool(row["delivered"]),
                "last_status": row["last_status"],
                "last_error": row["last_error"],
                "last_attempt_at": row["last_attempt_at"],
            }
            for row in rows
        ]

    def event(self, event_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT data FROM events WHERE id = ?", (event_id,)
            ).fetchone()
        return None if row is None else json.loads(row["data"])

    def delivery_attempts(self, event_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT attempted_at, signature_mode, status, error, delivered
                FROM delivery_attempts WHERE event_id = ? ORDER BY id
                """,
                (event_id,),
            ).fetchall()
        return [dict(row) for row in rows]
