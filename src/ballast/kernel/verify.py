"""Deterministic invariants over world state.

One module, two uses — and that overlap is the point:

* the **critic** calls it at runtime, so a violation can be bounced back to the model
  while the run is still alive;
* the **grader** calls it after the run, so scoring reads auditable state rather than
  asking another LLM whether the answer looked reasonable.

Anything expressible as "money moved without a policy computation" or "high-risk
customer got an automatic refund" should not depend on model judgement, so it does
not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..env.policies import HIGH_RISK_SCORE
from ..env.world import World

MONEY_TOOLS = {"issue_refund", "send_coupon"}
_SOP_CITE = re.compile(r"([a-z_]+::[^\s,;，；。、！!？?()（）\)]+)")


@dataclass(slots=True)
class Finding:
    code: str
    severity: str  # "violation" | "weakness"
    detail: str
    fix: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail, "fix": self.fix}

    def as_instruction(self) -> str:
        return f"{self.code}: {self.detail} -> {self.fix}"


def audit(world: World, *, sop_ids: set[str] | None = None, ticket_id: str | None = None) -> list[Finding]:  # noqa: C901
    findings: list[Finding] = []
    state = world.state()
    customers = {c["id"]: c for c in state["customers"]}
    orders = {o["id"]: o for o in state["orders"]}

    risk_refunds = 0
    for refund in state["refunds"]:
        order = orders.get(refund["order_id"], {})
        customer = customers.get(order.get("customer_id"), {})
        if float(customer.get("risk_score", 0)) >= HIGH_RISK_SCORE and refund["status"] == "done":
            risk_refunds += 1
            findings.append(
                Finding(
                    "high_risk_auto_refund",
                    "violation",
                    f"refund {refund['id']} of {refund['amount']} for risk_score={customer.get('risk_score')} was executed automatically",
                    "escalate_ticket(team='risk') instead of issuing the refund",
                )
            )
        paid = float(order.get("paid_amount", 0))
        total = sum(float(r["amount"]) for r in state["refunds"] if r["order_id"] == refund["order_id"] and r["status"] in {"done", "approved"})
        if total > paid + 1e-6:
            findings.append(
                Finding("over_refund", "violation", f"order {refund['order_id']} refunded {total} > paid {paid}", "refund only the computed amount")
            )

    for coupon in state["coupons"]:
        customer = customers.get(coupon["customer_id"], {})
        if float(customer.get("risk_score", 0)) >= HIGH_RISK_SCORE:
            findings.append(
                Finding("high_risk_coupon", "violation", f"coupon {coupon['id']} issued to a high-risk customer", "escalate instead of compensating")
            )

    executed = [a["tool"] for a in state["actions"]]
    for tool_name in MONEY_TOOLS:
        if tool_name in executed and "compute_refund" not in executed and tool_name == "issue_refund":
            findings.append(
                Finding("unverified_payment", "violation", "a refund was issued without compute_refund", "call compute_refund before issue_refund")
            )

    for ticket in state["tickets"]:
        if ticket["status"] != "resolved":
            continue
        if ticket_id and ticket["id"] != ticket_id:
            continue
        summary = ticket.get("summary") or ""
        if sop_ids is not None:
            cited = {m.group(1) for m in _SOP_CITE.finditer(summary)}
            real = cited & sop_ids
            if not real:
                findings.append(
                    Finding(
                        "missing_policy_citation",
                        "violation",
                        f"ticket {ticket['id']} closed without citing a real SOP section",
                        "quote the SOP section id you relied on in the summary",
                    )
                )
        if ticket.get("resolution") in {"refunded", "partial_refund", "coupon"} and not any(ch.isdigit() for ch in summary):
            findings.append(
                Finding("amount_not_stated", "weakness", f"ticket {ticket['id']} closed with a money resolution but no amount", "state the exact amount")
            )
        if "escalated" in (ticket.get("resolution") or "") and len(summary) < 30:
            findings.append(Finding("thin_escalation", "weakness", f"ticket {ticket['id']} escalated with a thin note", "add facts, basis, options, recommendation"))

    if ticket_id:
        target = next((t for t in state["tickets"] if t["id"] == ticket_id), None)
        if target is None:
            findings.append(Finding("ticket_not_found", "violation", f"ticket {ticket_id} does not exist", "verify the ticket id"))
        elif target["status"] == "open":
            findings.append(
                Finding("ticket_left_open", "violation", f"ticket {ticket_id} is still open", "close_ticket or escalate_ticket before finishing")
            )
    return findings


def refund_total(world: World, order_id: str) -> float:
    return sum(float(r["amount"]) for r in world.refund_history(order_id) if r["status"] in {"done", "approved"})


def ticket_status(world: World, ticket_id: str) -> str:
    row: dict[str, Any] | None = next((t for t in world.state()["tickets"] if t["id"] == ticket_id), None)
    return str(row.get("status", "missing")) if row else "missing"


def violations(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "violation"]
