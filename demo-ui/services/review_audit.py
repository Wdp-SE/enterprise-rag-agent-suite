"""SQLite persistence for anonymous, human-reviewed public demo events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ALLOWED_DECISIONS = {"reviewed", "rejected"}
_MAX_HISTORY_LIMIT = 100


class SQLiteReviewAudit:
    """Append-only, session-filtered audit storage for the public demo UI.

    This repository does not authenticate reviewers or guarantee that an
    ephemeral hosting filesystem survives a deployment restart.
    """

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS review_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('reviewed', 'rejected')),
                    decided_at_utc TEXT NOT NULL,
                    request_fingerprint TEXT,
                    report_json TEXT NOT NULL,
                    persisted_at_utc TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_events_session_time "
                "ON review_events (session_id, decided_at_utc DESC)"
            )

    def record(self, report: dict[str, Any], *, session_id: str) -> dict[str, Any]:
        if not isinstance(report, dict):
            raise ValueError("review report must be an object")
        task_id = report.get("task_id")
        decision = report.get("human_decision")
        decided_at = report.get("decided_at_utc")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id is required")
        if decision not in _ALLOWED_DECISIONS:
            raise ValueError("human_decision must be reviewed or rejected")
        if not isinstance(decided_at, str) or not decided_at.strip():
            raise ValueError("decided_at_utc is required")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id is required")

        event_id = uuid.uuid4().hex
        persisted_at = datetime.now(timezone.utc).isoformat()
        payload = {
            **report,
            "record_scope": "local_demo_sqlite",
            "actor_session_id": session_id,
            "event_id": event_id,
            "persisted_at_utc": persisted_at,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO review_events (
                    event_id, task_id, session_id, decision, decided_at_utc,
                    request_fingerprint, report_json, persisted_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    task_id,
                    session_id,
                    decision,
                    decided_at,
                    report.get("request_fingerprint"),
                    encoded,
                    persisted_at,
                ),
            )
        return payload

    def list_recent(self, *, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id is required")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_HISTORY_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_HISTORY_LIMIT}")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT report_json FROM review_events
                WHERE session_id = ?
                ORDER BY decided_at_utc DESC, rowid DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
