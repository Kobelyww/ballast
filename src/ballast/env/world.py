"""Simulated e-commerce after-sales world.

A frozen clock (`fixture['now']`) makes policy windows reproducible, every mutation
is written to an audit table, and graders read world state — never model prose.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(
  id TEXT PRIMARY KEY, name TEXT, tier TEXT, phone TEXT, address TEXT,
  registered_days INTEGER, risk_score INTEGER, tags TEXT
);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY, customer_id TEXT, status TEXT, created_at TEXT,
  paid_amount REAL, shipping_fee REAL, channel TEXT, address TEXT
);
CREATE TABLE IF NOT EXISTS order_items(
  id TEXT PRIMARY KEY, order_id TEXT, sku TEXT, name TEXT, category TEXT,
  qty INTEGER, delivered_qty INTEGER, unit_price REAL, discount REAL
);
CREATE TABLE IF NOT EXISTS shipments(
  id TEXT PRIMARY KEY, order_id TEXT, carrier TEXT, tracking_no TEXT,
  status TEXT, shipped_at TEXT, delivered_at TEXT, events TEXT
);
CREATE TABLE IF NOT EXISTS payments(
  id TEXT PRIMARY KEY, order_id TEXT, method TEXT, amount REAL, status TEXT, paid_at TEXT
);
CREATE TABLE IF NOT EXISTS refunds(
  id TEXT PRIMARY KEY, order_id TEXT, amount REAL, reason TEXT, status TEXT,
  created_at TEXT, operator TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS coupons(
  id TEXT PRIMARY KEY, customer_id TEXT, value REAL, reason TEXT, issued_at TEXT, operator TEXT
);
CREATE TABLE IF NOT EXISTS tickets(
  id TEXT PRIMARY KEY, customer_id TEXT, order_id TEXT, channel TEXT, priority TEXT,
  created_at TEXT, claim TEXT, status TEXT, resolution TEXT, summary TEXT, team TEXT
);
CREATE TABLE IF NOT EXISTS actions(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, tool TEXT, args TEXT, result TEXT, ok INTEGER
);
CREATE TABLE IF NOT EXISTS flags(
  id TEXT PRIMARY KEY, customer_id TEXT, reason TEXT, created_at TEXT
);
"""

DEFAULT_NOW = "2026-05-20T10:00:00"


@dataclass(slots=True)
class WorldError(Exception):
    code: str
    message: str
    retryable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "retryable": self.retryable}


class World:
    """One instance per run. Backed by sqlite (`:memory:` for eval)."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self.now: str = DEFAULT_NOW
        self._flaky: dict[str, int] = {}
        self.mutation_count = 0

    # ---------------------------------------------------------------- lifecycle
    def apply(self, fixture: dict[str, Any]) -> None:
        self.now = fixture.get("now", DEFAULT_NOW)
        self._flaky = dict(fixture.get("flaky_tools", {}))
        with self._lock:
            for table in ("customers", "orders", "order_items", "shipments", "payments", "refunds", "tickets"):
                for row in fixture.get(table, []):
                    self._insert(table, row)
            self._conn.commit()

    def _insert(self, table: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        ph = ", ".join("?" * len(row))
        self._conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({ph})", list(row.values()))

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------- reads
    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def _maybe_flaky(self, tool: str) -> None:
        remaining = self._flaky.get(tool, 0)
        if remaining > 0:
            self._flaky[tool] = remaining - 1
            raise WorldError("upstream_timeout", f"{tool} 调用超时（网关 504），此错误可重试。", retryable=True)

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        self._maybe_flaky("get_customer")
        row = self._one("SELECT * FROM customers WHERE id=?", (customer_id,))
        if not row:
            raise WorldError("not_found", f"客户 {customer_id} 不存在")
        row["tags"] = _json_or(row.get("tags"), [])
        return row

    def get_order(self, order_id: str) -> dict[str, Any]:
        self._maybe_flaky("get_order")
        row = self._one("SELECT * FROM orders WHERE id=?", (order_id,))
        if not row:
            raise WorldError("not_found", f"订单 {order_id} 不存在")
        row["items"] = self._rows("SELECT * FROM order_items WHERE order_id=?", (order_id,))
        row["shipment"] = self._one("SELECT * FROM shipments WHERE order_id=?", (order_id,))
        if row["shipment"]:
            row["shipment"]["events"] = _json_or(row["shipment"].get("events"), [])
        row["payments"] = self._rows("SELECT * FROM payments WHERE order_id=?", (order_id,))
        return row

    def list_orders(self, customer_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM orders WHERE customer_id=? ORDER BY created_at", (customer_id,))

    def list_orders_by_phone(self, phone: str) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT o.* FROM orders o JOIN customers c ON o.customer_id = c.id WHERE c.phone=? ORDER BY o.created_at",
            (phone,),
        )

    def list_tickets(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if status:
            return self._rows("SELECT * FROM tickets WHERE status=? ORDER BY created_at LIMIT ?", (status, limit))
        return self._rows("SELECT * FROM tickets ORDER BY created_at LIMIT ?", (limit,))

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM tickets WHERE id=?", (ticket_id,))
        if not row:
            raise WorldError("not_found", f"工单 {ticket_id} 不存在")
        return row

    def refund_history(self, order_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM refunds WHERE order_id=?", (order_id,))

    def coupon_history(self, customer_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM coupons WHERE customer_id=?", (customer_id,))

    # --------------------------------------------------------------- mutations
    def issue_refund(
        self, *, order_id: str, amount: float, reason: str, operator: str = "agent", status: str = "done", note: str = ""
    ) -> dict[str, Any]:
        self._maybe_flaky("issue_refund")
        order = self.get_order(order_id)
        already = sum(float(r["amount"]) for r in self.refund_history(order_id) if r["status"] in {"done", "approved", "pending"})
        if already + float(amount) > float(order["paid_amount"]) + 1e-6:
            raise WorldError(
                "over_refund",
                f"累计退款 ¥{already + amount:.2f} 超过实付 ¥{order['paid_amount']:.2f}，拒绝执行。",
            )
        rid = f"RF{self.mutation_count + 1:04d}"
        self.mutation_count += 1
        row = {
            "id": rid,
            "order_id": order_id,
            "amount": round(float(amount), 2),
            "reason": reason,
            "status": status,
            "created_at": self.now,
            "operator": operator,
            "note": note,
        }
        with self._lock:
            self._insert("refunds", row)
            if status == "done":
                self._conn.execute("UPDATE orders SET status='refunded' WHERE id=?", (order_id,))
            self._audit("issue_refund", row, {"refund_id": rid}, ok=1)
            self._conn.commit()
        return {"refund_id": rid, "status": status, "amount": row["amount"], "order_id": order_id}

    def send_coupon(self, *, customer_id: str, value: float, reason: str, operator: str = "agent") -> dict[str, Any]:
        self._maybe_flaky("send_coupon")
        cid = f"CP{self.mutation_count + 1:04d}"
        self.mutation_count += 1
        row = {"id": cid, "customer_id": customer_id, "value": round(float(value), 2), "reason": reason, "issued_at": self.now, "operator": operator}
        with self._lock:
            self._insert("coupons", row)
            self._audit("send_coupon", row, {"coupon_id": cid}, ok=1)
            self._conn.commit()
        return {"coupon_id": cid, "value": row["value"], "customer_id": customer_id}

    def change_address(self, *, order_id: str, address: str) -> dict[str, Any]:
        self._maybe_flaky("change_address")
        with self._lock:
            self._conn.execute("UPDATE orders SET address=? WHERE id=?", (address, order_id))
            self._audit("change_address", {"order_id": order_id, "address": address}, {"ok": True}, ok=1)
            self._conn.commit()
        return {"order_id": order_id, "address": address, "updated": True}

    def update_ticket(self, *, ticket_id: str, status: str, resolution: str = "", summary: str = "", team: str = "") -> dict[str, Any]:
        self._maybe_flaky("update_ticket")
        self.get_ticket(ticket_id)
        with self._lock:
            self._conn.execute(
                "UPDATE tickets SET status=?, resolution=?, summary=?, team=COALESCE(NULLIF(?, ''), team) WHERE id=?",
                (status, resolution, summary, team, ticket_id),
            )
            self._audit(
                "update_ticket",
                {"ticket_id": ticket_id, "status": status, "resolution": resolution},
                {"ok": True},
                ok=1,
            )
            self._conn.commit()
        return {"ticket_id": ticket_id, "status": status}

    def flag_risk(self, *, customer_id: str, reason: str) -> dict[str, Any]:
        fid = f"FL{self.mutation_count + 1:04d}"
        self.mutation_count += 1
        with self._lock:
            self._insert("flags", {"id": fid, "customer_id": customer_id, "reason": reason, "created_at": self.now})
            self._audit("flag_risk", {"customer_id": customer_id, "reason": reason}, {"flag_id": fid}, ok=1)
            self._conn.commit()
        return {"flag_id": fid, "customer_id": customer_id}

    def _audit(self, tool: str, args: dict, result: dict, *, ok: int) -> None:
        self._conn.execute(
            "INSERT INTO actions(ts, tool, args, result, ok) VALUES (?,?,?,?,?)",
            (self.now, tool, json.dumps(args, ensure_ascii=False), json.dumps(result, ensure_ascii=False), ok),
        )

    def audit_read(self, tool: str, args: dict, result: dict | None = None) -> None:
        """Record a *decision-bearing* read.

        `compute_refund` returns no state change, but the fact that a policy
        computation happened *before* money moved is exactly what an auditor needs
        from the server side. Without this, "was a refund paid without a computation"
        is only checkable from the client's own transcript.
        """
        with self._lock:
            self._audit(tool, args, result or {"recorded": True}, ok=1)
            self._conn.commit()

    # ------------------------------------------------------------------ state
    def state(self) -> dict[str, Any]:
        return {
            "now": self.now,
            "orders": self._rows("SELECT * FROM orders"),
            "customers": self._rows("SELECT * FROM customers"),
            "refunds": self._rows("SELECT * FROM refunds"),
            "coupons": self._rows("SELECT * FROM coupons"),
            "tickets": self._rows("SELECT * FROM tickets"),
            "flags": self._rows("SELECT * FROM flags"),
            "actions": self._rows("SELECT tool, args, ok FROM actions ORDER BY seq"),
        }

    def total_refunded(self, order_id: str) -> float:
        return sum(float(r["amount"]) for r in self.refund_history(order_id) if r["status"] in {"done", "approved"})


def _json_or(value: Any, default: Any) -> Any:
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return default


@dataclass(slots=True)
class Approval:
    id: str
    tool: str
    args: dict[str, Any]
    reason: str
    decision: str | None = None
    decided_by: str | None = None
    note: str = ""
    created_at: str = DEFAULT_NOW


@dataclass(slots=True)
class ApprovalQueue:
    """Pending human approvals for one run."""

    items: list[Approval] = field(default_factory=list)

    def add(self, approval: Approval) -> Approval:
        self.items.append(approval)
        return approval

    def pending(self) -> list[Approval]:
        return [a for a in self.items if a.decision is None]
