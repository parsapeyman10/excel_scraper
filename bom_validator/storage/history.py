"""Local audit trail: every validation run is persisted to SQLite.

This gives the plant a tamper-evident history (file hash + timestamp + result
snapshot), trend charts, and the ability to diff two runs of the same board.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import app_data_dir
from ..models import ValidationReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    source_file   TEXT    NOT NULL,
    source_name   TEXT    NOT NULL,
    source_sha256 TEXT    NOT NULL,
    profile       TEXT    NOT NULL,
    total_lines   INTEGER NOT NULL,
    passed        INTEGER NOT NULL,
    warnings      INTEGER NOT NULL,
    failed        INTEGER NOT NULL,
    not_placed    INTEGER NOT NULL,
    total_required INTEGER NOT NULL,
    total_placed  INTEGER NOT NULL,
    health_score  REAL    NOT NULL,
    duration_ms   REAL    NOT NULL,
    operator      TEXT    DEFAULT '',
    payload       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_sha  ON runs(source_sha256);
CREATE INDEX IF NOT EXISTS idx_runs_name ON runs(source_name);
CREATE INDEX IF NOT EXISTS idx_runs_time ON runs(created_at DESC);

CREATE TABLE IF NOT EXISTS signoffs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    line_key   TEXT    NOT NULL,
    operator   TEXT    NOT NULL DEFAULT '',
    note       TEXT    NOT NULL DEFAULT '',
    signed_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sign_run ON signoffs(run_id);
"""


@dataclass(slots=True)
class RunRecord:
    id: int
    created_at: str
    source_name: str
    source_file: str
    source_sha256: str
    profile: str
    total_lines: int
    passed: int
    warnings: int
    failed: int
    not_placed: int
    total_required: int
    total_placed: int
    health_score: float
    duration_ms: float
    operator: str = ""

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total_lines * 100 if self.total_lines else 0.0


class HistoryStore:
    """Thin, dependency-free SQLite wrapper. Safe to use from any thread."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else app_data_dir() / "history.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def save(self, report: ValidationReport, operator: str = "") -> int:
        s = report.summary
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO runs (created_at, source_file, source_name,
                   source_sha256, profile, total_lines, passed, warnings, failed,
                   not_placed, total_required, total_placed, health_score,
                   duration_ms, operator, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    report.generated_at.isoformat(),
                    report.source_file,
                    Path(report.source_file).name,
                    report.source_sha256,
                    report.profile_name,
                    s.total_lines,
                    s.passed,
                    s.warnings,
                    s.failed,
                    s.not_placed,
                    s.total_required,
                    s.total_placed,
                    s.health_score,
                    report.duration_ms,
                    operator,
                    report.to_json(indent=0),
                ),
            )
            return int(cur.lastrowid or 0)

    def recent(self, limit: int = 100, source_name: str | None = None) -> list[RunRecord]:
        q = (
            "SELECT id,created_at,source_name,source_file,source_sha256,profile,"
            "total_lines,passed,warnings,failed,not_placed,total_required,"
            "total_placed,health_score,duration_ms,operator FROM runs"
        )
        args: tuple[Any, ...] = ()
        if source_name:
            q += " WHERE source_name = ?"
            args = (source_name,)
        q += " ORDER BY id DESC LIMIT ?"
        args += (limit,)
        with self._conn() as c, closing(c.execute(q, args)) as cur:
            return [RunRecord(**dict(r)) for r in cur.fetchall()]

    def payload(self, run_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
            return json.loads(row["payload"]) if row else None

    def delete(self, run_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM runs WHERE id=?", (run_id,))

    def purge(self, keep_last: int = 500) -> int:
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM runs WHERE id NOT IN "
                "(SELECT id FROM runs ORDER BY id DESC LIMIT ?)",
                (keep_last,),
            )
            return cur.rowcount

    def sign_off(self, run_id: int, line_key: str, operator: str, note: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO signoffs (run_id,line_key,operator,note,signed_at) "
                "VALUES (?,?,?,?,?)",
                (
                    run_id,
                    line_key,
                    operator,
                    note,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def signoffs(self, run_id: int) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT line_key,operator,note,signed_at FROM signoffs WHERE run_id=?",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def trend(self, source_name: str, limit: int = 50) -> list[tuple[str, float, float]]:
        """(timestamp, health_score, pass_rate) oldest→newest for charting."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT created_at, health_score, passed, total_lines FROM runs "
                "WHERE source_name=? ORDER BY id DESC LIMIT ?",
                (source_name, limit),
            ).fetchall()
        out = [
            (
                r["created_at"],
                float(r["health_score"]),
                (r["passed"] / r["total_lines"] * 100) if r["total_lines"] else 0.0,
            )
            for r in rows
        ]
        return list(reversed(out))

    def stats(self) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) n, AVG(health_score) avg_health, "
                "SUM(total_lines) lines, MIN(created_at) first, MAX(created_at) last "
                "FROM runs"
            ).fetchone()
            return {
                "runs": row["n"] or 0,
                "avg_health": round(row["avg_health"] or 0.0, 2),
                "lines_checked": row["lines"] or 0,
                "first_run": row["first"],
                "last_run": row["last"],
            }
