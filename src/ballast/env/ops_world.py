"""Simulated SRE incident world.

Same shape as `env/world.py` — frozen clock, SQLite, an audit table, mutations that
refuse unsafe arguments — and deliberately no shared code with it. That is the test of
whether this directory holds a runtime or an application.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from .world import WorldError

SCHEMA = """
CREATE TABLE IF NOT EXISTS services(
  id TEXT PRIMARY KEY, name TEXT, tier TEXT, owner TEXT, blast_radius INTEGER, sli INTEGER
);
CREATE TABLE IF NOT EXISTS incidents(
  id TEXT PRIMARY KEY, service_id TEXT, severity TEXT, title TEXT, opened_at TEXT,
  status TEXT, tags TEXT, mitigation TEXT, resolution TEXT, review TEXT, paged_team TEXT
);
CREATE TABLE IF NOT EXISTS alerts(
  id TEXT PRIMARY KEY, incident_id TEXT, name TEXT, state TEXT, since TEXT, resource TEXT
);
CREATE TABLE IF NOT EXISTS deployments(
  id TEXT PRIMARY KEY, service_id TEXT, version TEXT, finished_at TEXT, author TEXT, canary INTEGER
);
CREATE TABLE IF NOT EXISTS pages(
  id TEXT PRIMARY KEY, incident_id TEXT, team TEXT, at TEXT, acknowledged INTEGER, ack_by TEXT
);
CREATE TABLE IF NOT EXISTS actions(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, tool TEXT, args TEXT, result TEXT, ok INTEGER
);
CREATE TABLE IF NOT EXISTS status_notes(
  id TEXT PRIMARY KEY, incident_id TEXT, text TEXT, at TEXT
);
"""

DEFAULT_NOW = "2026-09-18T03:15:00"


class OpsWorld:
    """One instance per run. Backed by sqlite (`:memory:` for eval)."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Reentrant: a mutation may need to read current state while it holds the
        # lock (`rollback_deploy` resolves its incident), and a plain Lock deadlocks.
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self.now: str = DEFAULT_NOW
        self.mutation_count = 0
        self._flaky: dict[str, int] = {}

    # ---------------------------------------------------------------- lifecycle
    def apply(self, fixture: dict[str, Any]) -> None:
        self.now = fixture.get("now", DEFAULT_NOW)
        self._flaky = dict(fixture.get("flaky_tools", {}))
        with self._lock:
            for table in ("services", "incidents", "alerts", "deployments", "pages", "status_notes"):
                for row in fixture.get(table, []):
                    self._insert(table, row)
            self._conn.commit()

    def _insert(self, table: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        self._conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))

    def _maybe_flaky(self, tool: str) -> None:
        if self._flaky.get(tool, 0) > 0:
            self._flaky[tool] -= 1
            raise WorldError("upstream_timeout", f"{tool} timed out at the gateway (504); retryable", retryable=True)

    def close(self) -> None:
        self._conn.close()

    # -------------------------------------------------------------------- reads
    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def get_incident(self, incident_id: str) -> dict[str, Any]:
        self._maybe_flaky("get_incident")
        row = next((r for r in self._rows("SELECT * FROM incidents WHERE id=?", (incident_id,))), None)
        if not row:
            raise WorldError("not_found", f"incident {incident_id} does not exist")
        row["tags"] = _json_or(row.get("tags"), [])
        # Parsed here as well as in state(): `close_incident` consults the mitigation
        # list to decide whether the runbook is satisfied, so an unparsed string here
        # silently reads as "nothing has been done yet" and refuses a correct close-out.
        row["mitigation"] = _json_or(row.get("mitigation"), [])
        row["service"] = next((s for s in self._rows("SELECT * FROM services WHERE id=?", (row["service_id"],))), {})
        row["alerts"] = self._rows("SELECT * FROM alerts WHERE incident_id=?", (incident_id,))
        row["deployments"] = self._rows("SELECT * FROM deployments WHERE service_id=?", (row["service_id"],))
        return row

    def list_incidents(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if status and status != "all":
            return self._rows("SELECT * FROM incidents WHERE status=? ORDER BY opened_at LIMIT ?", (status, limit))
        return self._rows("SELECT * FROM incidents ORDER BY opened_at LIMIT ?", (limit,))

    def get_service(self, service_id: str) -> dict[str, Any]:
        row = next((r for r in self._rows("SELECT * FROM services WHERE id=?", (service_id,))), None)
        if not row:
            raise WorldError("not_found", f"service {service_id} does not exist")
        return row

    def recent_deployments(self, service_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM deployments WHERE service_id=? ORDER BY finished_at DESC", (service_id,))

    def pages(self, incident_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM pages WHERE incident_id=?", (incident_id,))

    # ---------------------------------------------------------------- mutations
    def page_oncall(self, *, incident_id: str, team: str, reason: str) -> dict[str, Any]:
        self._maybe_flaky("page_oncall")
        self.get_incident(incident_id)
        pid = f"PG{self.mutation_count + 1:04d}"
        self.mutation_count += 1
        with self._lock:
            self._insert("pages", {"id": pid, "incident_id": incident_id, "team": team, "at": self.now, "acknowledged": 0, "ack_by": ""})
            self._conn.execute("UPDATE incidents SET paged_team=? WHERE id=?", (team, incident_id))
            self._audit("page_oncall", {"incident_id": incident_id, "team": team, "reason": reason}, {"page_id": pid})
            self._conn.commit()
        return {"page_id": pid, "team": team, "incident_id": incident_id}

    def acknowledge_incident(self, *, incident_id: str, by: str) -> dict[str, Any]:
        self._maybe_flaky("acknowledge_incident")
        self.get_incident(incident_id)
        with self._lock:
            self._conn.execute("UPDATE pages SET acknowledged=1, ack_by=? WHERE incident_id=?", (by, incident_id))
            self._mark_mitigation(incident_id, "acknowledge")
            self._audit("acknowledge_incident", {"incident_id": incident_id, "by": by}, {"ok": True})
            self._conn.commit()
        return {"incident_id": incident_id, "acknowledged_by": by}

    def rollback_deploy(self, *, service_id: str, deployment_id: str, reason: str) -> dict[str, Any]:
        self._maybe_flaky("rollback_deploy")
        deploy = next((d for d in self.recent_deployments(service_id) if d["id"] == deployment_id), None)
        if deploy is None:
            raise WorldError("not_found", f"deployment {deployment_id} is not a deployment of {service_id}")
        with self._lock:
            self._conn.execute("UPDATE services SET tier=tier WHERE id=?", (service_id,))
            self._mark_mitigation(_incident_for_service(self, service_id), "rollback")
            self._audit("rollback_deploy", {"service_id": service_id, "deployment_id": deployment_id, "reason": reason}, {"rolled_back_to": deploy["version"]})
            self._conn.commit()
        return {"service_id": service_id, "rolled_back": deployment_id, "version": deploy["version"]}

    def notify_status_page(self, *, incident_id: str, text: str) -> dict[str, Any]:
        self._maybe_flaky("notify_status_page")
        self.get_incident(incident_id)
        nid = f"SN{self.mutation_count + 1:04d}"
        self.mutation_count += 1
        with self._lock:
            self._insert("status_notes", {"id": nid, "incident_id": incident_id, "text": text, "at": self.now})
            self._mark_mitigation(incident_id, "notify_status_page")
            self._audit("notify_status_page", {"incident_id": incident_id, "text": text}, {"note_id": nid})
            self._conn.commit()
        return {"note_id": nid, "incident_id": incident_id}

    def record_review(self, *, incident_id: str, summary: str) -> dict[str, Any]:
        self.get_incident(incident_id)
        with self._lock:
            self._conn.execute("UPDATE incidents SET review=? WHERE id=?", (summary, incident_id))
            self._mark_mitigation(incident_id, "review")
            self._audit("record_review", {"incident_id": incident_id, "summary": summary}, {"ok": True})
            self._conn.commit()
        return {"incident_id": incident_id, "recorded": True}

    def close_incident(self, *, incident_id: str, resolution: str, summary: str) -> dict[str, Any]:
        self._maybe_flaky("close_incident")
        self.get_incident(incident_id)
        with self._lock:
            # `mitigation` is the ordered record of what was actually done; closing
            # writes its own column and must not overwrite that evidence.
            # Closing records its own summary; it must not stand in for a review entry,
            # or a skipped post-incident review would grade as completed.
            self._conn.execute("UPDATE incidents SET status='closed', resolution=? WHERE id=?", (resolution, incident_id))
            self._audit("close_incident", {"incident_id": incident_id, "resolution": resolution, "summary": summary}, {"ok": True})
            self._conn.commit()
        return {"incident_id": incident_id, "status": "closed", "resolution": resolution}

    def audit_read(self, tool: str, args: dict, result: dict | None = None) -> None:
        with self._lock:
            self._audit(tool, args, result or {"recorded": True})
            self._conn.commit()

    def _mark_mitigation(self, incident_id: str | None, step: str) -> None:
        if not incident_id:
            return
        row = self._conn.execute("SELECT mitigation FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            return
        steps = _json_or(row["mitigation"], [])
        if step not in steps:
            steps.append(step)
        self._conn.execute("UPDATE incidents SET mitigation=? WHERE id=?", (json.dumps(steps, ensure_ascii=False), incident_id))

    def _audit(self, tool: str, args: dict, result: dict) -> None:
        self._conn.execute(
            "INSERT INTO actions(ts, tool, args, result, ok) VALUES (?,?,?,?,?)",
            (self.now, tool, json.dumps(args, ensure_ascii=False), json.dumps(result, ensure_ascii=False), 1),
        )

    # -------------------------------------------------------------------- state
    def state(self) -> dict[str, Any]:
        incidents = self._rows("SELECT * FROM incidents")
        for row in incidents:
            row["tags"] = _json_or(row.get("tags"), [])
            row["mitigation"] = _json_or(row.get("mitigation"), [])
        return {
            "now": self.now,
            "services": self._rows("SELECT * FROM services"),
            "incidents": incidents,
            "alerts": self._rows("SELECT * FROM alerts"),
            "deployments": self._rows("SELECT * FROM deployments"),
            "pages": self._rows("SELECT * FROM pages"),
            "status_notes": self._rows("SELECT * FROM status_notes"),
            "actions": self._rows("SELECT tool, args, ok FROM actions ORDER BY seq"),
        }


def _incident_for_service(world: OpsWorld, service_id: str) -> str | None:
    open_rows = [i for i in world.state()["incidents"] if i["service_id"] == service_id and i["status"] == "open"]
    return open_rows[0]["id"] if open_rows else None


def _json_or(value: Any, default: Any) -> Any:
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default if isinstance(default, list) else value
