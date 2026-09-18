"""Durable execution: checkpoints per step, resume across processes, parked approvals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ballast.kernel.agent import RunResult
from ballast.kernel.budget import RunBudget
from ballast.kernel.checkpoint import Checkpoint, Checkpointer
from ballast.llm.base import Usage
from conftest import GOOD_SUMMARY, Harness, call_step, s03_plan, say


@pytest.fixture
def cp(tmp_path: Path) -> Any:
    checkpointer = Checkpointer(tmp_path / "runs.db")
    yield checkpointer
    checkpointer.close()


class TestCheckpointStore:
    def test_seq_starts_at_one_and_increments(self, cp: Checkpointer) -> None:
        assert cp.save("r1", {"status": "running"}) == 1
        assert cp.save("r1", {"status": "running"}) == 2
        assert cp.writes == 2

    def test_runs_have_independent_cursors(self, cp: Checkpointer) -> None:
        assert cp.save("a", {}) == 1 and cp.save("b", {}) == 1 and cp.save("a", {}) == 2

    def test_latest_returns_the_newest_state(self, cp: Checkpointer) -> None:
        cp.save("r", {"v": 1})
        cp.save("r", {"v": 2})
        latest = cp.latest("r")
        assert isinstance(latest, Checkpoint)
        assert (latest.run_id, latest.seq, latest.state) == ("r", 2, {"v": 2})
        assert latest.ts > 0

    def test_history_is_ordered_and_complete(self, cp: Checkpointer) -> None:
        for i in range(4):
            cp.save("r", {"i": i})
        assert [c.seq for c in cp.history("r")] == [1, 2, 3, 4]
        assert [c.state["i"] for c in cp.history("r")] == [0, 1, 2, 3]

    def test_unknown_runs_are_empty_not_fatal(self, cp: Checkpointer) -> None:
        assert cp.latest("nope") is None
        assert cp.history("nope") == []
        assert cp.pending_interrupts() == []

    def test_state_survives_a_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "runs.db"
        writer = Checkpointer(path)
        writer.save("r", {"context": {"transcript": [{"role": "user", "content": "退款"}]}, "cost": 0.12})
        writer.close()
        reader = Checkpointer(path)
        assert reader.latest("r").state["context"]["transcript"][0]["content"] == "退款"
        assert reader.writes == 0  # a fresh handle has not written anything yet
        assert reader.save("r", {"n": 3}) == 2  # ... but it still knows the cursor

    def test_non_serialisable_state_is_stringified_not_crashed(self, cp: Checkpointer) -> None:
        class Opaque:
            def __str__(self) -> str:
                return "<opaque>"

        cp.save("r", {"obj": Opaque(), "nested": {"path": Path("/tmp/x")}})
        state = cp.latest("r").state
        assert state["obj"] == "<opaque>" and str(state["nested"]["path"]).endswith("x")

    def test_latest_resets_the_cursor_so_two_handles_agree(self, cp: Checkpointer) -> None:
        cp.save("r", {})
        cp.save("r", {})
        assert cp.latest("r").seq == 2
        assert cp.save("r", {}) == 3

    def test_schema_is_idempotent(self, tmp_path: Path) -> None:
        first = Checkpointer(tmp_path / "db.sqlite")
        first.save("r", {"a": 1})
        first.close()
        second = Checkpointer(tmp_path / "db.sqlite")
        assert second.history("r")[0].state == {"a": 1}

    def test_start_seeds_the_run_row(self, cp: Checkpointer) -> None:
        cp.start("r", task_id="S01_inwindow_refund", arm="ballast")
        assert cp.latest("r") is None
        assert cp.pending_interrupts() == []

    def test_finalize_closes_the_run_and_stores_the_result(self, cp: Checkpointer) -> None:
        cp.save("r", {"status": "running"})
        cp.finalize("r", status="ok", result={"cost": 0.03, "steps": 7})
        row = cp._status_row("r")
        assert row["status"] == "ok"
        assert json.loads(row["result"]) == {"cost": 0.03, "steps": 7}

    def test_finalize_without_a_result_leaves_the_column_null(self, cp: Checkpointer) -> None:
        cp.save("r", {"status": "running"})
        cp.finalize("r", status="budget_aborted")
        assert cp._status_row("r")["result"] is None

    def test_interrupted_runs_are_parked_in_order(self, cp: Checkpointer) -> None:
        cp.save("late", {"status": "interrupted", "task_id": "S02", "arm": "ballast", "interrupt": {"tool": "issue_refund", "run_id": "late"}})
        cp.save("early", {"status": "interrupted", "task_id": "S01", "arm": "naive", "interrupt": {"tool": "send_coupon", "run_id": "early"}})
        cp.save("done", {"status": "ok", "task_id": "S03", "arm": "ballast"})
        pending = {row["run_id"]: row for row in cp.pending_interrupts()}
        assert set(pending) == {"early", "late"}  # 'done' never enters the queue
        assert pending["early"]["interrupt"] == {"tool": "send_coupon", "run_id": "early"}
        assert pending["late"]["task_id"] == "S02" and pending["late"]["arm"] == "ballast"

    def test_a_resumed_run_leaves_the_pending_queue(self, cp: Checkpointer) -> None:
        cp.save("r", {"status": "interrupted", "interrupt": {"tool": "issue_refund"}})
        assert len(cp.pending_interrupts()) == 1
        cp.save("r", {"status": "running"})
        assert cp.pending_interrupts() == []

    def test_save_without_state_metadata_erases_the_start_row(self, cp: Checkpointer) -> None:
        cp.start("r", task_id="S08_address_change", arm="tight_budget")
        cp.save("r", {"status": "interrupted", "interrupt": {"tool": "issue_refund"}})
        pending = cp.pending_interrupts()
        # KNOWN BUG (src/ballast/kernel/checkpoint.py:95-100): `save` INSERT OR REPLACEs
        # the whole `runs` row, so anything `start()` recorded but the state dict omits
        # (here task_id and arm; `result` and `started_at` too) is blanked out. The agent
        # loop always passes a state that carries task_id/arm, so eval traffic is fine -
        # the hazard is any caller that checkpoints a bare dict.
        assert pending[0]["task_id"] == "" and pending[0]["arm"] == ""


class TestAgentCheckpointing:
    def test_every_step_is_checkpointed(self, cp: Checkpointer) -> None:
        h = Harness("S01_inwindow_refund", checkpointer=cp)
        result = h.run(
            [
                call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"),
                call_step(2, "issue_refund", order_id="SO20261042", amount=129.0, reason="no_reason"),
                call_step(3, "close_ticket", ticket_id="T1042", resolution="refunded", summary="依据 refund_policy::七天无理由退货 无理由退款 ¥129.00，已执行并结单。"),
                say("完成"),
            ]
        )
        assert result.status == "ok"
        history = cp.history(result.run_id)
        assert [c.state["status"] for c in history] == ["running", "running", "running", "ok"]
        assert history[0].state["task_id"] == "S01_inwindow_refund"
        assert history[-1].state["final_text"] == "完成"
        assert cp._status_row(result.run_id)["status"] == "ok"  # the final save owns the row

    def test_checkpoint_state_is_the_whole_run_not_just_the_transcript(self, cp: Checkpointer) -> None:
        h = Harness("S01_inwindow_refund", checkpointer=cp)
        h.run([call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"), say("停")])
        state = cp.latest(h.ctx.run_id).state
        assert set(state) >= {
            "task_id",
            "arm",
            "task",
            "context",
            "computed",
            "approvals",
            "guardrail_blocks",
            "hitl_script",
            "budget",
            "steps",
            "usage_history",
            "events",
            "idempotent",
        }
        assert state["computed"]["SO20261042"]["amount"] == 129.0
        assert RunBudget.from_dict(state["budget"]).max_cost == RunBudget().max_cost
        assert state["usage_history"][0]["calls"] == 1

    def test_events_are_kept_but_capped(self, cp: Checkpointer) -> None:
        h = Harness("S01_inwindow_refund", checkpointer=cp)
        script = [call_step(i, "get_ticket", ticket_id="T1042") for i in range(1, 30)] + [say("done")]
        h.run(script)
        state = cp.latest(h.ctx.run_id).state
        assert len(state["events"]) <= 40

    def test_pending_calls_are_recorded_for_replay(self, cp: Checkpointer) -> None:
        h = Harness("S01_inwindow_refund", checkpointer=cp)
        h.run([call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"), say("停")])
        # The checkpoint written *after* a step carries the calls that step executed; the
        # closing checkpoint only carries the final text.
        by_status = {c.state["status"]: c.state for c in cp.history(h.ctx.run_id)}
        assert by_status["running"]["pending_calls"] == [
            {"id": "call_1", "name": "compute_refund", "arguments": {"order_id": "SO20261042", "claim_type": "no_reason"}}
        ]
        assert by_status["ok"]["final_text"] == "停"

    def test_a_run_without_a_checkpointer_still_works(self) -> None:
        h = Harness("S01_inwindow_refund")
        h.load([call_step(1, "get_ticket", ticket_id="T1042"), say("x")])
        assert h.run().status == "ok"


class TestResume:
    def test_resume_needs_a_checkpointer(self) -> None:
        h = Harness("S01_inwindow_refund")
        with pytest.raises(RuntimeError, match="requires a checkpointer"):
            h.agent.resume("whatever", {"approved": True})

    def test_resume_needs_a_saved_run(self, cp: Checkpointer) -> None:
        h = Harness("S01_inwindow_refund", checkpointer=cp)
        with pytest.raises(KeyError, match="no checkpoint"):
            h.agent.resume("ghost-run", {"approved": True})

    def test_resume_of_a_run_that_only_paused_continues_without_replay(self, cp: Checkpointer) -> None:
        """Checkpoint/resume is not only for approvals: a run that stopped for any reason
        restarts from its last checkpoint with its cost, steps and policy state intact."""
        h = Harness("S01_inwindow_refund", checkpointer=cp)
        first = h.run([call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"), say("pause")])
        assert cp.latest(first.run_id).state["interrupt"] is None
        actions_before = [a["tool"] for a in h.world.state()["actions"]]

        h.ctx.computed.clear()  # the process died: only the checkpoint knows the computation
        h.load([call_step(2, "issue_refund", order_id="SO20261042", amount=129.0, reason="no_reason"), say("完成")])
        resumed = h.agent.resume(first.run_id, {"approved": True}, ctx=h.ctx, task=h.scenario.brief)
        assert resumed.status == "ok", resumed.error
        assert [r["amount"] for r in h.world.state()["refunds"]] == [129.0]
        assert [a["tool"] for a in h.world.state()["actions"]][: len(actions_before)] == actions_before
        assert resumed.steps > first.steps and resumed.cost > first.cost

    def test_resuming_a_parked_run_restores_counters_and_policy_state(self, cp: Checkpointer) -> None:
        h = Harness("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, checkpointer=cp)
        parked = h.run(s03_plan())
        assert parked.status == "interrupted"
        assert parked.steps >= 6 and parked.cost > 0
        h.ctx.computed.clear()
        h.load([call_step(8, "close_ticket", ticket_id="T1044", resolution="refunded", summary=GOOD_SUMMARY), say("已结单")])
        resumed = h.agent.resume(parked.run_id, {"approved": True}, ctx=h.ctx, task=h.scenario.brief)
        assert resumed.status == "ok", resumed.error
        assert resumed.run_id == parked.run_id
        assert resumed.steps > parked.steps  # the step cursor came back from the checkpoint
        assert resumed.cost >= parked.cost
        assert h.ctx.computed["SO20261044"]["amount"] == 459.0  # the computation survived

    def test_resumed_run_continues_the_same_trace(self, cp: Checkpointer) -> None:
        h = Harness("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, checkpointer=cp)
        parked = h.run(s03_plan())
        h.load([say("已转人工")])
        resumed = h.agent.resume(parked.run_id, {"approved": False, "note": "复核"}, ctx=h.ctx, task=h.scenario.brief)
        types = [e["type"] for e in resumed.events]
        assert types[0] == "run_start" and "approval_request" in types
        assert any(e["payload"].get("resumed") for e in resumed.events if e["type"] == "approval_decision")
        assert isinstance(resumed, RunResult)
        # The verdict is injected as a tool reply, so the model sees the human said no.
        assert any("approval_rejected" in str(m.get("content")) for m in cp.latest(resumed.run_id).state["context"]["transcript"])

    def test_the_idempotency_memo_is_keyed_on_the_run_and_call_id(self, cp: Checkpointer) -> None:
        """A call id already answered under this run replays instead of paying twice."""
        h = Harness("S01_inwindow_refund", checkpointer=cp)
        # Two turns that both use `call_1`: the second one is the replay case.
        h.load(
            [
                call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"),
                call_step(1, "issue_refund", order_id="SO20261042", amount=129.0, reason="no_reason"),
                say("done"),
            ]
        )
        result = h.run()
        replayed = [e for e in result.events if e["type"] == "tool_result" and e["payload"].get("replayed")]
        assert replayed and replayed[0]["payload"]["name"] == "issue_refund"
        assert h.world.state()["refunds"] == []  # the memo returned the old result, no new effect

    def test_resuming_the_parked_call_afterwards_does_move_the_money(self, cp: Checkpointer) -> None:
        h = Harness("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, checkpointer=cp)
        parked = h.run(s03_plan())
        h.load([call_step(6, "issue_refund", order_id="SO20261044", amount=459.0, reason="quality"), say("完成")])
        resumed = h.agent.resume(parked.run_id, {"approved": True}, ctx=h.ctx, task=h.scenario.brief)
        assert resumed.status == "ok", resumed.error
        assert [r["amount"] for r in h.world.state()["refunds"]] == [459.0]
        assert resumed.rejected_calls == 0
