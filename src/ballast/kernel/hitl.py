"""Human-in-the-loop: an approval gate that can survive process death.

Who decides that a human is needed? The policy engine, never the model — a model
that is asked "should I get approval?" will happily answer "no". So `compute_refund`
returns `requires_approval`, and the money-moving tool consults that.

Three resolutions are supported:
* `auto_approve` / `auto_reject` — for eval arms and CI.
* `scripted` — a dict of tool-name -> verdict, for reproducible scenario tests.
* `interrupt` — raises `Interrupt`, which the agent loop persists as a checkpoint
  with status `interrupted`. Any later process can list pending approvals and
  resume the exact run with a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

from .events import RunContext


@dataclass(slots=True)
class ApprovalDecision:
    approved: bool
    decided_by: str = "policy"
    note: str = ""


class Interrupt(Exception):
    """Control-flow signal, not an error: the run is parked pending a human verdict."""

    def __init__(self, payload: dict) -> None:
        super().__init__(payload.get("reason", "interrupted"))
        self.payload = payload


def resolve_approval(ctx: RunContext, *, tool_name: str, args: dict, reason: str, required: bool) -> ApprovalDecision:
    """Return a verdict, or raise Interrupt when a real human must answer."""
    if ctx.hitl_mode == "auto_approve":
        decision = ApprovalDecision(True, "policy:auto_approve", reason if required else "")
    elif ctx.hitl_mode == "auto_reject":
        decision = ApprovalDecision(False, "policy:auto_reject", "runtime is configured to reject")
    elif ctx.hitl_mode == "scripted":
        if tool_name in ctx.hitl_script:
            approved = bool(ctx.hitl_script[tool_name])
            decision = ApprovalDecision(approved, "script", "" if approved else "scripted rejection")
        elif not required:
            decision = ApprovalDecision(True, "policy:not_required", "")
        else:
            raise Interrupt(_payload(ctx, tool_name, args, reason))
    elif not required:
        decision = ApprovalDecision(True, "policy:not_required", "")
    else:
        raise Interrupt(_payload(ctx, tool_name, args, reason))

    ctx.approvals.append(
        {
            "tool": tool_name,
            "args": args,
            "reason": reason,
            "required": required,
            "approved": decision.approved,
            "by": decision.decided_by,
        }
    )
    ctx.emit("approval_decision", tool=tool_name, approved=decision.approved, by=decision.decided_by, required=required)
    return decision


def _payload(ctx: RunContext, tool_name: str, args: dict, reason: str) -> dict:
    payload = {"kind": "approval", "run_id": ctx.run_id, "tool": tool_name, "args": args, "reason": reason}
    ctx.pending_interrupt = payload
    ctx.emit("approval_request", **payload)
    return payload
