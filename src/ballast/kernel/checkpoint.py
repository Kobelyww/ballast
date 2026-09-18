"""Durable execution: checkpoint every step, resume across processes, pause for humans.

An agent that cannot be stopped and restarted is an agent you operate by watching it.
This checkpointer persists the *whole* run state (context, ledger counters, world
mutations, scratch handles) after every step, so:

* a crash loses at most one step;
* a human-in-the-loop approval can park a run for hours and resume it from a
  different process;
* an eval can replay a saved run and diff step-by-step behaviour between two arms.

JSON in SQLite, no ORM, no service. The point is the invariant, not the storage.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints(
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, ts REAL NOT NULL,
  state TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, task_id TEXT, arm TEXT, status TEXT,
  started_at REAL, updated_at REAL, last_seq INTEGER, interrupt TEXT, result TEXT
);
"""


@dataclass(slots=True)
class Checkpoint:
    run_id: str
    seq: int
    ts: float
    state: dict[str, Any]


class Checkpointer:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._seqs: dict[str, int] = {}
        self.writes = 0

    # ------------------------------------------------------------- bookkeeping
    def start(self, run_id: str, *, task_id: str = "", arm: str = "") -> None:
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO runs(run_id, task_id, arm, status, started_at, updated_at, last_seq, interrupt, result)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, task_id, arm, "running", now, now, 0, None, None),
        )
        self._conn.commit()

    def _status_row(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def pending_interrupts(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT run_id, task_id, arm, interrupt, updated_at FROM runs WHERE status='interrupted' ORDER BY updated_at"
        ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["interrupt"] = json.loads(data["interrupt"] or "{}")
            out.append(data)
        return out

    def finalize(self, run_id: str, *, status: str, result: dict[str, Any] | None = None) -> None:
        self._conn.execute(
            "UPDATE runs SET status=?, updated_at=?, result=? WHERE run_id=?",
            (status, time.time(), json.dumps(result, ensure_ascii=False, default=str) if result else None, run_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------- checkpoints
    def save(self, run_id: str, state: dict[str, Any], *, task_id: str = "", arm: str = "") -> int:
        seq = self._seqs.get(run_id, 0) + 1
        self._seqs[run_id] = seq
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoints(run_id, seq, ts, state) VALUES (?,?,?,?)",
            (run_id, seq, now, json.dumps(state, ensure_ascii=False, default=str)),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO runs(run_id, task_id, arm, status, started_at, updated_at, last_seq, interrupt, result)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, task_id or state.get("task_id", ""), arm or state.get("arm", ""), state.get("status", "running"), now, now, seq,
             json.dumps(state.get("interrupt"), ensure_ascii=False) if state.get("interrupt") else None, None),
        )
        self._conn.commit()
        self.writes += 1
        return seq

    def latest(self, run_id: str) -> Checkpoint | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)
        ).fetchone()
        if not row:
            return None
        self._seqs[run_id] = int(row["seq"])
        return Checkpoint(run_id=row["run_id"], seq=int(row["seq"]), ts=float(row["ts"]), state=json.loads(row["state"]))

    def history(self, run_id: str) -> list[Checkpoint]:
        rows = self._conn.execute("SELECT * FROM checkpoints WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return [Checkpoint(run_id=r["run_id"], seq=r["seq"], ts=r["ts"], state=json.loads(r["state"])) for r in rows]

    def close(self) -> None:
        self._conn.close()
