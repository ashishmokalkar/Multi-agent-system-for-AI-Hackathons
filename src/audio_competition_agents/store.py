from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    """Small SQLite event store for inspectable and resumable workflow runs."""

    def __init__(self, database_path: Path):
        self.path = database_path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    objective_json TEXT NOT NULL,
                    budget_json TEXT NOT NULL,
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS configurations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    config_kind TEXT NOT NULL,
                    config_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    population TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    agent TEXT,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_events_run_sequence
                    ON events(run_id, sequence);
                """
            )

    def create_run(self, objective: dict[str, Any], budget: dict[str, Any], mode: str) -> str:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        now = utc_now()
        initial = {"phase": "created", "revision_attempts": 0}
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, now, now, "created", mode, json.dumps(objective), json.dumps(budget), json.dumps(initial)),
            )
        return run_id

    def update_run(self, run_id: str, status: str, state: dict[str, Any]) -> None:
        with self._lock, self.connect() as db:
            changed = db.execute(
                "UPDATE runs SET updated_at=?, status=?, state_json=? WHERE run_id=?",
                (utc_now(), status, json.dumps(state, sort_keys=True), run_id),
            ).rowcount
            if changed != 1:
                raise KeyError(f"unknown run_id: {run_id}")

    def append_message(
        self,
        run_id: str,
        sender: str,
        recipient: str,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO messages(run_id,created_at,sender,recipient,message_type,payload_json) VALUES (?,?,?,?,?,?)",
                (run_id, utc_now(), sender, recipient, message_type, json.dumps(payload, sort_keys=True)),
            )

    def add_configuration(self, run_id: str, kind: str, value: dict[str, Any]) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO configurations(run_id,created_at,config_kind,config_json) VALUES (?,?,?,?)",
                (run_id, utc_now(), kind, json.dumps(value, sort_keys=True)),
            )

    def add_metrics(self, run_id: str, population: str, value: dict[str, Any]) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO metrics(run_id,created_at,population,metrics_json) VALUES (?,?,?,?)",
                (run_id, utc_now(), population, json.dumps(value, sort_keys=True)),
            )

    def add_artifact(self, run_id: str, name: str, uri: str, kind: str, metadata: dict[str, Any] | None = None) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO artifacts(run_id,created_at,name,uri,kind,metadata_json) VALUES (?,?,?,?,?,?)",
                (run_id, utc_now(), name, uri, kind, json.dumps(metadata or {}, sort_keys=True)),
            )

    def append_event(
        self,
        run_id: str,
        event_type: str,
        summary: str,
        *,
        agent: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock, self.connect() as db:
            sequence = int(db.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE run_id=?",
                (run_id,),
            ).fetchone()[0])
            created_at = utc_now()
            db.execute(
                """INSERT INTO events(run_id,sequence,created_at,event_type,agent,summary,payload_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (run_id, sequence, created_at, event_type, agent, summary, json.dumps(payload or {}, sort_keys=True)),
            )
        return {
            "sequence": sequence,
            "created_at": created_at,
            "event_type": event_type,
            "agent": agent,
            "summary": summary,
            "payload": payload or {},
        }

    def list_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT sequence,created_at,event_type,agent,summary,payload_json "
                "FROM events WHERE run_id=? AND sequence>? ORDER BY sequence",
                (run_id, after),
            )
            result = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json"))
                result.append(item)
            return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown run_id: {run_id}")
            result = dict(row)
            for key in ["objective_json", "budget_json", "state_json"]:
                result[key.removesuffix("_json")] = json.loads(result.pop(key))
            result["messages"] = [
                {**dict(message), "payload": json.loads(message["payload_json"])}
                for message in db.execute("SELECT * FROM messages WHERE run_id=? ORDER BY id", (run_id,))
            ]
            for message in result["messages"]:
                message.pop("payload_json")
            result["events"] = self.list_events(run_id)
            return result

    def list_runs(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT run_id,created_at,updated_at,status,mode FROM runs ORDER BY created_at DESC"
            )]
