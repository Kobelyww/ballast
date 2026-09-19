"""Human-in-the-loop approvals, the `Interrupt` control-flow signal, and the guardrails
that decide *who* gets to move money."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ballast.kernel.events import RunContext
from ballast.kernel.hitl import ApprovalDecision, Interrupt, resolve_approval
from ballast.kernel.toolkit import Toolkit
from ballast.tools.desk import build_desk_tools
from conftest import GOOD_SUMMARY, Harness, call_step, s03_plan, say


def verdict(ctx: RunContext, *, tool_name: str = "issue_refund", required: bool = True, args: dict | None = None) -> ApprovalDecision:
    return resolve_approval(ctx, tool_name=tool_name, args=args or {"order_id": "SO1"}, reason="above the approval line", required=required)


class TestVerdicts:
    def test_auto_approve_is_a_policy_decision_not_a_human_one(self) -> None:
        ctx = RunContext(hitl_mode="auto_approve")
        decision = verdict(ctx)
        assert (decision.approved, decision.decided_by) == (True, "policy:auto_approve")
        assert decision.note == "above the approval line"
        assert ctx.approvals[0]["by"] == "policy:auto_approve"

    def test_auto_approve_keeps_an_optional_call_optional(self) -> None:
        assert verdict(RunContext(hitl_mode="auto_approve"), required=False).note == ""

    def test_auto_reject_never_pays(self) -> None:
        ctx = RunContext(hitl_mode="auto_reject")
        decision = verdict(ctx)
        assert decision.approved is False and decision.decided_by == "policy:auto_reject"
        assert ctx.approvals[0]["approved"] is False

    def test_script_answers_per_tool(self) -> None:
        assert verdict(RunContext(hitl_mode="scripted", hitl_script={"issue_refund": True})).decided_by == "script"
        rejected = verdict(RunContext(hitl_mode="scripted", hitl_script={"issue_refund": False}))
        assert (rejected.approved, rejected.note) == (False, "scripted rejection")

    def test_script_without_an_entry_defers_when_not_required(self) -> None:
        decision = verdict(RunContext(hitl_mode="scripted", hitl_script={"send_coupon": True}), required=False)
        assert (decision.approved, decision.decided_by) == (True, "policy:not_required")

    @pytest.mark.parametrize("mode", ["scripted", "interrupt"])
    def test_a_required_call_with_no_verdict_parks_the_run(self, mode: str) -> None:
        ctx = RunContext(hitl_mode=mode, hitl_script={})
        with pytest.raises(Interrupt) as excinfo:
            verdict(ctx, args={"order_id": "SO20261044", "amount": 459.0})
        assert excinfo.value.payload == {
            "kind": "approval",
            "run_id": ctx.run_id,
            "tool": "issue_refund",
            "args": {"order_id": "SO20261044", "amount": 459.0},
            "reason": "above the approval line",
        }
        assert ctx.pending_interrupt == excinfo.value.payload

    def test_interrupt_carries_a_readable_reason(self) -> None:
        ctx = RunContext(hitl_mode="interrupt")
        with pytest.raises(Interrupt, match="a human must sign this payment") as excinfo:
            resolve_approval(ctx, tool_name="issue_refund", args={}, reason="a human must sign this payment", required=True)
        assert str(excinfo.value) == "a human must sign this payment"
        assert ctx.pending_interrupt["reason"] == "a human must sign this payment"
        assert [e.type for e in ctx.events] == ["approval_request"]
        assert ctx.approvals == []  # a parked decision is not a recorded decision

    def test_interrupt_is_control_flow_not_an_error_result(self) -> None:
        # A blanket `except Exception` in the dispatcher would turn this into a
        # `tool_crashed` result and the run would keep spending past the gate.
        harness = Harness("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={})
        result = harness.run(s03_plan())
        assert result.status == "interrupted"
        assert result.interrupted["tool"] == "issue_refund"
        assert harness.world.state()["refunds"] == []
        codes = [e["payload"].get("code") for e in result.events if e["type"] == "tool_result"]
        assert "tool_crashed" not in codes

    def test_an_approval_is_recorded_once_per_decision(self) -> None:
        ctx = RunContext(hitl_mode="auto_approve")
        verdict(ctx)
        verdict(ctx, tool_name="send_coupon", required=False)
        assert [a["tool"] for a in ctx.approvals] == ["issue_refund", "send_coupon"]
        assert [e.type for e in ctx.events] == ["approval_decision", "approval_decision"]
        assert ctx.events[0].payload["by"] == "policy:auto_approve"


class TestDeskGuardrails:
    """The tools refuse to move money the policy engine did not derive."""

    @pytest.fixture
    def kit(self, harness: Any) -> tuple[Toolkit, Harness]:
        h = harness("S01_inwindow_refund")
        return h.config.toolkit, h

    def _content(self, result: Any) -> dict:
        return json.loads(result.content)

    def test_refund_without_a_computation_is_blocked(self, kit: tuple[Toolkit, Harness]) -> None:
        toolkit, h = kit
        result = toolkit.execute("issue_refund", {"order_id": "SO20261042", "amount": 129.0, "reason": "no_reason"})
        assert result.ok is False
        assert self._content(result)["error"] == "missing_computation"
        assert "compute_refund" in self._content(result)["hint"]
        assert h.ctx.guardrail_blocks == 1
        assert h.world.state()["refunds"] == []

    def test_a_policy_denied_refund_cannot_be_talked_into(self, kit: tuple[Toolkit, Harness]) -> None:
        toolkit, h = kit
        toolkit.execute("compute_refund", {"order_id": "SO20261042", "claim_type": "no_reason"})
        # now flip the verdict: the computation is on record, but it said "no"
        h.ctx.computed["SO20261042"] = {**h.ctx.computed["SO20261042"], "allowed": False, "reason_code": "window_closed", "explanation": "窗口已过"}
        result = toolkit.execute("issue_refund", {"order_id": "SO20261042", "amount": 129.0, "reason": "no_reason"})
        assert self._content(result)["error"] == "policy_denied"
        assert "do not retry" in self._content(result)["hint"]

    def test_amount_mismatch_is_refused(self, kit: tuple[Toolkit, Harness]) -> None:
        toolkit, h = kit
        toolkit.execute("compute_refund", {"order_id": "SO20261042", "claim_type": "no_reason"})
        result = toolkit.execute("issue_refund", {"order_id": "SO20261042", "amount": 999.0, "reason": "no_reason"})
        assert self._content(result)["error"] == "amount_mismatch"
        assert "129.0" in self._content(result)["message"]
        assert h.world.state()["refunds"] == []

    def test_high_risk_needs_a_human(self) -> None:
        h = Harness("S06_high_risk")
        h.config.toolkit.execute("compute_refund", {"order_id": "SO20261047", "claim_type": "missing_item"})
        decision = h.config.toolkit.execute("compute_refund", {"order_id": "SO20261047", "claim_type": "missing_item"})
        assert json.loads(decision.content)["requires_escalation"] is True
        result = h.config.toolkit.execute("issue_refund", {"order_id": "SO20261047", "amount": 1999.0, "reason": "missing_item"})
        assert self._content(result)["error"] == "escalation_required"
        assert "risk" in self._content(result)["hint"]
        assert h.world.state()["refunds"] == []

    def test_above_the_approval_line_needs_a_verdict(self) -> None:
        h = Harness("S07_approval_line", hitl_script={"issue_refund": False})
        h.config.toolkit.execute("compute_refund", {"order_id": "SO20261048", "claim_type": "no_reason"})
        result = h.config.toolkit.execute("issue_refund", {"order_id": "SO20261048", "amount": 690.0, "reason": "no_reason"})
        assert result.ok and self._content(result)["error"] == "approval_rejected"
        assert h.world.state()["refunds"] == []
        assert h.ctx.approvals[-1]["approved"] is False

    def test_a_required_approval_is_demanded_before_the_money_moves(self) -> None:
        h = Harness("S07_approval_line", hitl_script={"issue_refund": True})
        h.config.toolkit.execute("compute_refund", {"order_id": "SO20261048", "claim_type": "no_reason"})
        result = h.config.toolkit.execute("issue_refund", {"order_id": "SO20261048", "amount": 690.0, "reason": "no_reason"})
        assert self._content(result)["ok"] is True
        assert h.ctx.approvals[-1]["required"] is True and h.ctx.approvals[-1]["by"] == "script"

    def test_below_the_line_needs_no_one(self) -> None:
        h = Harness("S01_inwindow_refund", hitl_script={})
        h.config.toolkit.execute("compute_refund", {"order_id": "SO20261042", "claim_type": "no_reason"})
        result = h.config.toolkit.execute("issue_refund", {"order_id": "SO20261042", "amount": 129.0, "reason": "no_reason"})
        assert self._content(result)["ok"] is True
        assert h.ctx.approvals[-1]["required"] is False

    def test_coupon_above_the_tier_cap_is_denied(self) -> None:
        h = Harness("S13_coupon_over_cap")
        result = h.config.toolkit.execute("send_coupon", {"customer_id": "C112", "value": 100.0, "reason": "体验补偿"})
        assert self._content(result)["error"] == "coupon_denied"
        assert h.world.state()["coupons"] == [] and h.ctx.guardrail_blocks == 1

    def test_in_cap_coupon_needs_no_approval(self) -> None:
        h = Harness("S12_coupon_within_cap")
        result = h.config.toolkit.execute("send_coupon", {"customer_id": "C111", "value": 30.0, "reason": "延误补偿"})
        assert self._content(result)["ok"] is True
        assert h.world.state()["coupons"][0]["value"] == 30.0

    def test_locked_address_is_referred_to_logistics(self) -> None:
        h = Harness("S09_address_locked")
        result = h.config.toolkit.execute("change_shipping_address", {"order_id": "SO20261050", "address": "广州市天河区B路2号"})
        assert self._content(result)["error"] == "address_locked"
        assert "logistics" in self._content(result)["hint"]
        assert h.ctx.guardrail_blocks == 1

    def test_summary_without_a_citation_is_sent_back(self) -> None:
        h = Harness("S01_inwindow_refund")
        result = h.config.toolkit.execute("close_ticket", {"ticket_id": "T1042", "resolution": "refunded", "summary": "已处理"})
        assert self._content(result)["error"] == "summary_incomplete"
        assert h.world.get_ticket("T1042")["status"] == "open"

    def test_unknown_resolution_and_team_are_rejected(self) -> None:
        h = Harness("S01_inwindow_refund")
        bad_resolution = h.config.toolkit.execute("close_ticket", {"ticket_id": "T1042", "resolution": "maybe", "summary": "x" * 40})
        assert self._content(bad_resolution)["error"] == "bad_resolution"
        bad_team = h.config.toolkit.execute("escalate_ticket", {"ticket_id": "T1042", "team": "marketing", "note": "n" * 40})
        assert self._content(bad_team)["error"] == "bad_team"
        thin = h.config.toolkit.execute("escalate_ticket", {"ticket_id": "T1042", "team": "risk", "note": "short"})
        assert self._content(thin)["error"] == "note_too_short"


class TestInterruptThroughALiveRun:
    def test_the_run_parks_at_the_money_tool(self) -> None:
        h = Harness("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={})
        result = h.run(s03_plan())
        assert result.status == "interrupted"
        payload = result.interrupted
        assert payload["tool"] == "issue_refund"
        assert payload["args"] == {"order_id": "SO20261044", "amount": 459.0, "reason": "quality"}
        # everything up to the gate happened; nothing past it did
        names = [e["payload"].get("name") for e in result.events if e["type"] == "tool_call"]
        assert names[:5] == ["get_ticket", "get_order", "get_customer", "search_sop", "compute_refund"]
        assert "close_ticket" not in names
        assert h.world.state()["refunds"] == []

    def test_an_interrupted_run_is_checkpointed_mid_call(self) -> None:
        from ballast.kernel.checkpoint import Checkpointer

        cp = Checkpointer(":memory:")
        h = Harness("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, checkpointer=cp)
        parked = h.run(s03_plan())
        state = cp.latest(parked.run_id).state
        assert state["status"] == "interrupted"
        assert state["interrupt"]["tool"] == "issue_refund"
        assert state["computed"]["SO20261044"]["amount"] == 459.0
        last = state["context"]["transcript"][-1]
        assert last["role"] == "assistant" and last.get("tool_calls")
        # KNOWN BUG (src/ballast/kernel/agent.py:292-297, 320): the payload is raised
        # from inside the tool call, so it never learns the id of the call it parked on
        # (`call_id` is only stamped on the *next* iteration of the tool-call loop).
        assert "call_id" not in state["interrupt"]

    def test_resume_after_an_approval_replays_nothing_and_the_gate_never_moves(self) -> None:
        from ballast.kernel.checkpoint import Checkpointer

        cp = Checkpointer(":memory:")
        h = Harness("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, checkpointer=cp)
        parked = h.run(s03_plan())
        h.load([call_step(8, "close_ticket", ticket_id="T1044", resolution="refunded", summary=GOOD_SUMMARY), say("已结单")])
        resumed = h.agent.resume(parked.run_id, {"approved": True}, ctx=h.ctx, task=h.scenario.brief)
        assert resumed.status == "ok", resumed.error
        # KNOWN BUG (src/ballast/kernel/agent.py:211-215): the approve branch replays
        # `state["pending_calls"]`, but the checkpoint written on Interrupt (agent.py:320)
        # records no pending_calls, so the approved refund is dropped on the floor while
        # the run goes on to close the ticket as `refunded`.
        assert h.world.state()["refunds"] == []
        assert h.world.get_ticket("T1044")["status"] == "resolved"
        # A parked gate records nothing: `resolve_approval` appends its verdict after
        # the raise, so the audit trail of a run that never resumed is the
        # `approval_request` event, not an approvals row.
        assert h.ctx.approvals == []
        assert [e["type"] for e in parked.events if e["type"].startswith("approval")] == ["approval_request"]

    def test_resume_after_a_rejection_answers_a_call_that_was_never_made(self) -> None:
        from ballast.kernel.checkpoint import Checkpointer

        cp = Checkpointer(":memory:")
        h = Harness("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, checkpointer=cp)
        parked = h.run(s03_plan())
        h.load(
            [
                call_step(9, "escalate_ticket", ticket_id="T1044", team="supervisor", note="人工拒绝了放款，需复核政策核定金额 ¥459.00 与客户诉求。"),
                say("已转人工"),
            ]
        )
        resumed = h.agent.resume(parked.run_id, {"approved": False, "note": "金额需财务复核"}, ctx=h.ctx, task=h.scenario.brief)
        assert h.world.state()["refunds"] == []
        assert resumed.status in {"ok", "stalled"}, resumed.error
        ticket = h.world.get_ticket("T1044")
        assert ticket["status"] == "escalated" and ticket["team"] == "supervisor"
        # KNOWN BUG (src/ballast/kernel/agent.py:195-210): with no `call_id` in the
        # payload, the rejection is injected as a reply to "call_0", which no assistant
        # message ever asked for - a request a real OpenAI-compatible endpoint 400s on.
        transcript = cp.latest(parked.run_id).state["context"]["transcript"]
        asked_for = {c["id"] for m in transcript if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])}
        replies = {m["tool_call_id"] for m in transcript if m.get("role") == "tool"}
        assert "call_0" in replies and "call_0" not in asked_for
        assert "call_6" in asked_for and "call_6" not in replies

    def test_a_read_whose_payload_left_the_window_earns_a_re_read(self) -> None:
        """The repeat guard stops spinning; it must not punish a gap the runtime dug.

        Scope note, measured rather than assumed: this grant fires when *no* usable copy
        of the result is left in the window — which is the offload case (the payload is
        behind a `scratch://` handle) and the tail of a long compaction. It does not fire
        for a read whose newest result is still on screen, and should not: there the
        refusal is correct, because the agent can act on what it can see.
        """
        h = Harness(
            "S01_inwindow_refund",
            context={"token_budget": 4_000, "offload_threshold": 60, "enable_compaction": False},
        )
        args = {"query": "退款 无理由 政策 窗口 计算", "top_k": 3}
        result = h.run([call_step(i, "search_sop", **args) for i in range(1, 13)])
        guard = [e for e in result.events if e["type"] == "loop_guard"]
        assert guard, "the repeat guard is what this run is exercising"
        assert all(e["payload"].get("re_read") for e in guard), [e["payload"] for e in guard]
        assert result.rejected_calls == 0
        assert result.context.get("offloads"), "the payload has to actually leave the window"

    def test_repeated_refund_calls_are_capped_by_the_loop_guard(self) -> None:
        h = Harness("S01_inwindow_refund")
        script: list[Any] = [
            call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"),
        ]
        # Same effect, same arguments, reused ids so the idempotency memo is not what
        # stops the repeat.
        for i in range(2, 12):
            script.append(call_step(i, "issue_refund", order_id="SO20261042", amount=129.0, reason="no_reason"))
        result = h.run(script)
        guard = [e for e in result.events if e["type"] == "loop_guard"]
        assert guard and guard[0]["payload"]["name"] == "issue_refund"
        assert result.rejected_calls >= 1
        assert len(h.world.state()["refunds"]) <= 1
        # The re-read grant is for reads only. An effect whose evidence left the window
        # is exactly the case that must stay refused: "I can't see the earlier refund"
        # is not a licence to make another one.
        assert all("re_read" not in e["payload"] for e in guard)
