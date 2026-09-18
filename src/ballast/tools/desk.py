"""Service-desk tools bound to one simulated world.

Every tool returns JSON; failures come back as structured, actionable errors rather
than exceptions, because a readable error is a correction the model can act on.

The important property is in `issue_refund`: it will only move money that
`compute_refund` has already derived from the deterministic policy engine. The
model cannot authorise a payment, only request one it has already been shown.
"""

from __future__ import annotations

from typing import Any

from ..env.policies import can_change_address, eligible_coupon, evaluate_refund
from ..env.world import World, WorldError
from ..kernel.events import RunContext
from ..kernel.hitl import Interrupt, resolve_approval
from ..kernel.toolkit import Tool, ToolError, tool

CLAIM_TYPES = ["no_reason", "quality", "missing_item", "damaged", "duplicate_charge", "other"]
RESOLUTIONS = ["refunded", "partial_refund", "coupon", "reissue", "escalated", "resolved_no_action", "rejected_by_policy"]
TEAMS = ["risk", "finance", "logistics", "warehouse", "supervisor"]


def build_desk_tools(ctx: RunContext) -> list[Tool]:
    world: World = ctx.world
    kb = ctx.sop

    @tool
    def list_tickets(status: str = "open", limit: int = 10) -> dict[str, Any]:
        """List open after-sales tickets.

        Args:
            status: open / pending_info / escalated / resolved / all.
            limit: maximum rows to return.
        """
        rows = world.list_tickets(None if status == "all" else status, limit=limit)
        return {"count": len(rows), "tickets": rows}

    @tool
    def get_ticket(ticket_id: str) -> dict[str, Any]:
        """Read one ticket: the customer's own words, channel, priority and linked order.

        Args:
            ticket_id: ticket identifier such as T-1042.
        """
        try:
            return world.get_ticket(ticket_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, hint="call list_tickets to find the real id") from exc

    @tool
    def get_order(order_id: str) -> dict[str, Any]:
        """Read an order: status, amount paid, shipping fee, line items with categories and
        delivered quantities, shipment events and payment rows.

        Args:
            order_id: order identifier such as SO-2026-1042.
        """
        try:
            return world.get_order(order_id)
        except WorldError as exc:
            raise ToolError(
                exc.code,
                exc.message,
                hint="if there is no order id, locate it with list_orders_by_phone; never invent one",
                retryable=exc.retryable,
            ) from exc

    @tool
    def list_orders_by_phone(phone: str) -> dict[str, Any]:
        """Find a customer's orders from their phone number when no order id was given.

        Args:
            phone: customer phone number as typed by the customer.
        """
        rows = world.list_orders_by_phone(phone)
        if not rows:
            raise ToolError("not_found", f"no orders for {phone}", hint="ask the customer to confirm, via set_ticket_pending_info")
        return {"count": len(rows), "orders": rows}

    @tool
    def get_customer(customer_id: str) -> dict[str, Any]:
        """Read a customer profile. Tier caps compensation; risk_score forces manual review.

        Args:
            customer_id: customer identifier.
        """
        try:
            return world.get_customer(customer_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool
    def search_sop(query: str, top_k: int = 3) -> dict[str, Any]:
        """Search the after-sales SOP for the rule that governs this claim. Do this before
        any refund or compensation decision.

        Args:
            query: natural-language policy question, e.g. "7天无理由 窗口 计算".
            top_k: number of sections to return.
        """
        hits = kb.search(query, top_k=top_k) if kb is not None else []
        return {
            "query": query,
            "hits": [{"id": d.id, "title": d.title, "score": round(s, 3), "text": d.text} for d, s in hits]
            or [{"note": "no section matched; retry with different keywords"}],
        }

    @tool
    def compute_refund(order_id: str, claim_type: str, target_skus: list[str] | None = None) -> dict[str, Any]:
        """Derive the policy-correct refund amount and whether it is allowed. Mandatory
        precondition: issue_refund only accepts an amount this tool already approved.

        Args:
            order_id: the order to assess.
            claim_type: which policy branch applies.
            target_skus: SKUs claimed; omit for the whole order.
        """
        try:
            order = world.get_order(order_id)
            customer = world.get_customer(order["customer_id"])
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc
        decision = evaluate_refund(
            order=order,
            items=order["items"],
            customer=customer,
            shipment=order.get("shipment"),
            claim_type=claim_type,
            now=world.now,
            target_skus=target_skus,
        )
        payload = {
            "order_id": order_id,
            "claim_type": claim_type,
            "allowed": decision.allowed,
            "amount": decision.amount,
            "reason_code": decision.reason_code,
            "explanation": decision.explanation,
            "requires_approval": decision.requires_approval,
            "requires_escalation": decision.requires_escalation,
            "blockers": decision.blockers,
            "line_amounts": decision.line_amounts,
        }
        ctx.computed[order_id] = payload
        world.audit_read("compute_refund", {"order_id": order_id, "claim_type": claim_type}, {"allowed": decision.allowed, "amount": decision.amount, "reason_code": decision.reason_code})
        return payload

    @tool
    def check_coupon_eligibility(customer_id: str, value: float) -> dict[str, Any]:
        """Check whether a compensation coupon fits the customer's tier cap.

        Args:
            customer_id: customer identifier.
            value: coupon face value.
        """
        try:
            customer = world.get_customer(customer_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc
        ok, message = eligible_coupon(customer, value)
        issued = sum(float(c["value"]) for c in world.coupon_history(customer_id))
        return {
            "customer_id": customer_id,
            "tier": customer["tier"],
            "value": value,
            "allowed": ok,
            "reason": message,
            "already_issued": issued,
        }

    @tool(mutating=True, tags=["money"])
    def issue_refund(order_id: str, amount: float, reason: str, note: str = "") -> dict[str, Any]:
        """Refund money. The amount must equal compute_refund's output exactly.

        Args:
            order_id: order to refund.
            amount: currency amount, taken from compute_refund.
            reason: claim type that justifies it.
            note: free text for the audit trail.
        """
        computed = ctx.computed.get(order_id)
        if computed is None:
            ctx.guardrail_blocks += 1
            raise ToolError(
                "missing_computation",
                "refund attempted without a policy computation",
                hint=f"call compute_refund(order_id='{order_id}', claim_type=...) first",
            )
        if not computed["allowed"]:
            ctx.guardrail_blocks += 1
            raise ToolError(
                "policy_denied",
                f"policy forbids this refund: {computed['reason_code']} — {computed['explanation']}",
                hint="explain the policy to the customer and close the ticket, or escalate_ticket; do not retry",
            )
        if abs(float(amount) - float(computed["amount"])) > 0.01:
            ctx.guardrail_blocks += 1
            raise ToolError(
                "amount_mismatch",
                f"requested {amount} but policy derived {computed['amount']}",
                hint="use the derived amount, or escalate with the reason you disagree",
            )
        if computed["requires_escalation"]:
            ctx.guardrail_blocks += 1
            raise ToolError("escalation_required", "high-risk customer: refunds require manual risk review", hint="call escalate_ticket(team='risk')")

        decision = resolve_approval(
            ctx,
            tool_name="issue_refund",
            args={"order_id": order_id, "amount": amount, "reason": reason},
            reason=f"refund {amount} ({reason}). {computed['explanation']}",
            required=bool(computed["requires_approval"]),
        )
        if not decision.approved:
            # The scope fields are payload content on purpose: a later step has to be
            # able to tell *which* order was refused, not merely that something was.
            return {
                "ok": False,
                "error": "approval_rejected",
                "order_id": order_id,
                "amount": amount,
                "message": decision.note,
                "hint": "do not retry this refund; close the ticket citing the rejection reason",
            }
        try:
            result = world.issue_refund(order_id=order_id, amount=amount, reason=reason, note=note)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc
        return {"ok": True, **result, "policy_basis": computed["reason_code"]}

    @tool(mutating=True, tags=["money"])
    def send_coupon(customer_id: str, value: float, reason: str) -> dict[str, Any]:
        """Issue a goodwill coupon. Blocked above the tier cap and for high-risk customers.

        Args:
            customer_id: recipient.
            value: face value.
            reason: justification recorded on the coupon.
        """
        try:
            customer = world.get_customer(customer_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc
        ok, message = eligible_coupon(customer, value)
        if not ok:
            ctx.guardrail_blocks += 1
            raise ToolError("coupon_denied", message, hint="lower the value within the cap, or escalate_ticket for an exception")
        decision = resolve_approval(
            ctx, tool_name="send_coupon", args={"customer_id": customer_id, "value": value}, reason=f"coupon {value}: {reason}", required=False
        )
        if not decision.approved:
            return {"ok": False, "error": "approval_rejected", "customer_id": customer_id, "value": value, "message": decision.note, "hint": "close the ticket citing the rejection reason"}
        try:
            return {"ok": True, **world.send_coupon(customer_id=customer_id, value=value, reason=reason)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def change_shipping_address(order_id: str, address: str) -> dict[str, Any]:
        """Change the delivery address. Only possible before dispatch.

        Args:
            order_id: order to amend.
            address: new full address.
        """
        try:
            order = world.get_order(order_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc
        ok, message = can_change_address(order, order.get("shipment"))
        if not ok:
            ctx.guardrail_blocks += 1
            raise ToolError("address_locked", message, hint="escalate_ticket(team='logistics') to intercept the parcel")
        try:
            return {"ok": True, **world.change_address(order_id=order_id, address=address)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def close_ticket(ticket_id: str, resolution: str, summary: str) -> dict[str, Any]:
        """Close the ticket. The summary is quality-checked: it must cite the policy basis.

        Args:
            ticket_id: ticket to close.
            resolution: one of the allowed resolution codes.
            summary: demand, policy basis (cite an SOP section id), action and amount.
        """
        if resolution not in RESOLUTIONS:
            raise ToolError("bad_resolution", f"resolution must be one of {RESOLUTIONS}", hint="pick the code matching what actually happened")
        problems = _check_summary(summary, kb)
        if problems:
            ctx.guardrail_blocks += 1
            raise ToolError("summary_incomplete", "; ".join(problems), hint="rewrite the summary citing an SOP section id and the exact amount")
        try:
            return {"ok": True, **world.update_ticket(ticket_id=ticket_id, status="resolved", resolution=resolution, summary=summary)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def escalate_ticket(ticket_id: str, team: str, note: str) -> dict[str, Any]:
        """Hand off to a human team. The note must be something a human can act on.

        Args:
            ticket_id: ticket to escalate.
            team: owning team.
            note: verified facts, policy basis, options, recommended action.
        """
        if team not in TEAMS:
            raise ToolError("bad_team", f"team must be one of {TEAMS}", hint="choose the team that can actually act")
        if len(note) < 12:
            raise ToolError("note_too_short", "escalation note is not actionable", hint="state facts, policy basis, options and a recommendation")
        try:
            return {"ok": True, **world.update_ticket(ticket_id=ticket_id, status="escalated", resolution="escalated", summary=note, team=team)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def set_ticket_pending_info(ticket_id: str, question: str) -> dict[str, Any]:
        """Park the ticket and ask the customer for the missing detail.

        Args:
            ticket_id: ticket to park.
            question: the exact question to put to the customer.
        """
        try:
            return {"ok": True, **world.update_ticket(ticket_id=ticket_id, status="pending_info", summary=question)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def flag_risk(customer_id: str, reason: str) -> dict[str, Any]:
        """Record a fraud-risk flag. Does not itself block or refund anything.

        Args:
            customer_id: customer to flag.
            reason: observed suspicious pattern.
        """
        try:
            world.get_customer(customer_id)
            return {"ok": True, **world.flag_risk(customer_id=customer_id, reason=reason)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool
    def read_scratch(handle: str, offset: int = 0, limit: int = 2000) -> dict[str, Any]:
        """Re-read a tool output that was moved out of the context window.

        Args:
            handle: a scratch:// handle from a truncated tool result.
            offset: character offset.
            limit: maximum characters to return.
        """
        if ctx.scratch is None:
            raise ToolError("no_scratch", "overflow store is disabled for this run")
        payload = ctx.scratch.get(handle)
        if payload is None:
            raise ToolError("not_found", f"handle {handle} is not readable", hint="check the handle from the truncated result")
        return {"handle": handle, "offset": offset, "text": payload[offset : offset + limit]}

    return [
        list_tickets,
        get_ticket,
        get_order,
        list_orders_by_phone,
        get_customer,
        search_sop,
        compute_refund,
        check_coupon_eligibility,
        issue_refund,
        send_coupon,
        change_shipping_address,
        close_ticket,
        escalate_ticket,
        set_ticket_pending_info,
        flag_risk,
        read_scratch,
    ]


def _check_summary(summary: str, kb: Any) -> list[str]:
    problems: list[str] = []
    if len(summary) < 20:
        problems.append("summary is too short to be actionable")
    cited = _cited_sections(summary, kb)
    if not cited:
        problems.append("summary cites no SOP section id (e.g. refund_policy::7天无理由窗口)")
    if any(w in summary for w in ("退款", "补偿", "coupon", "refund")) and not any(ch.isdigit() for ch in summary):
        problems.append("summary mentions money but states no amount")
    return problems


def _cited_sections(summary: str, kb: Any) -> list[str]:
    if kb is None:
        return []
    known = kb.section_ids()
    return [sid for sid in known if sid in summary]


__all__ = ["build_desk_tools", "Interrupt", "CLAIM_TYPES", "RESOLUTIONS", "TEAMS"]
