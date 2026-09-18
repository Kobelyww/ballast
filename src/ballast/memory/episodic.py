"""Episodic memory: one row per run, holding the trace that made it.

Enough to reconstruct a run after a crash, to diff two arms step by step, and to
let the distiller decide which episodes deserve becoming skills.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, task_id TEXT, arm TEXT, status TEXT, ok INTEGER,
  started_at REAL, finished_at REAL, steps INTEGER, calls INTEGER,
  cost REAL, input_tokens INTEGER, output_tokens INTEGER, cached_tokens INTEGER,
  prompt_tokens INTEGER, compactions INTEGER, offloads INTEGER,
  model TEXT, skills_retrieved TEXT, skills_applied TEXT,
  guardrail_blocks INTEGER, critic_rounds INTEGER, approvals INTEGER,
  summary TEXT, events TEXT, world_state TEXT, error TEXT, findings TEXT
);
CREATE INDEX IF NOT EXISTS runs_task ON runs(task_id, started_at);
"""


@dataclass(slots=True)
class RunRecord:
    run_id: str
    task_id: str = ""
    arm: str = ""
    status: str = "running"
    ok: bool = False
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    steps: int = 0
    calls: int = 0
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    prompt_tokens: int = 0
    compactions: int = 0
    offloads: int = 0
    model: str = ""
    skills_retrieved: list[str] = field(default_factory=list)
    skills_applied: list[str] = field(default_factory=list)
    guardrail_blocks: int = 0
    critic_rounds: int = 0
    approvals: int = 0
    summary: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    world_state: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, str]] = field(default_factory=list)
    error: str = ""


class EpisodeStore:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def save(self, record: RunRecord) -> None:
        row = asdict(record)
        for key in ("skills_retrieved", "skills_applied", "events", "world_state", "findings"):
            row[key] = json.dumps(row[key], ensure_ascii=False)
        cols = ", ".join(row)
        self._conn.execute(
            f"INSERT OR REPLACE INTO runs ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values())
        )
        self._conn.commit()

    def get(self, run_id: str) -> RunRecord | None:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return _hydrate(row) if row else None

    def recent(self, limit: int = 50, *, task_id: str | None = None, arm: str | None = None) -> list[RunRecord]:
        where, params = [], []
        if task_id:
            where.append("task_id=?")
            params.append(task_id)
        if arm:
            where.append("arm=?")
            params.append(arm)
        sql = "SELECT * FROM runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY started_at DESC LIMIT {int(limit)}"
        return [_hydrate(r) for r in self._conn.execute(sql, params).fetchall()]

    def successful(self, task_ids: set[str] | None = None) -> list[RunRecord]:
        rows = self._conn.execute("SELECT * FROM runs WHERE ok=1 ORDER BY started_at DESC").fetchall()
        records = [_hydrate(r) for r in rows]
        return [r for r in records if task_ids is None or r.task_id in task_ids]

    def close(self) -> None:
        self._conn.close()


_JSON_FIELDS = ("skills_retrieved", "skills_applied", "events", "world_state", "findings")


def _hydrate(row: sqlite3.Row) -> RunRecord:
    data = dict(row)
    for key in _JSON_FIELDS:
        data[key] = json.loads(data.get(key) or "null") or [] if key != "world_state" else (json.loads(data.get("world_state") or "null") or {})
    return RunRecord(**data)
