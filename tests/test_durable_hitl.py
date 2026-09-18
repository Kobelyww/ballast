"""Durable human-in-the-loop: park a run in one process, finish it in another.

This is the claim most easily faked in an agent framework, so it is tested the way it
would actually be used — a fresh `Checkpointer` over the same database file, a rebuilt
world, and an assertion that the money moved *exactly once* after the verdict.
"""

from __future__ import annotations

import pytest

from ballast.context.engine import ContextPolicy
from ballast.env.fixtures import by_id
from ballast.env.knowledge import KnowledgeBase
from ballast.kernel.agent import Agent, AgentConfig
from ballast.kernel.budget import RunBudget
from ballast.kernel.checkpoint import Checkpointer
from ballast.kernel.events import RunContext
from ballast.kernel.toolkit import Toolkit
from ballast.llm.surrogate import SurrogatePolicy
from ballast.support.text import ScratchStore
from ballast.tools.desk import build_desk_tools

SCENARIO = "S03_quality_with_shipping"  # 459 CNY: above the automatic approval line


def _build(db, *, hitl_mode="interrupt", script=None):
    scenario = by_id(SCENARIO)
    world = scenario.build_world()
    kb = KnowledgeBase.from_dir()
    ctx = RunContext(
        task_id=scenario.id,
        arm="hitl",
        world=world,
        sop=kb,
        hitl_mode=hitl_mode,
        hitl_script=script or {},
        scratch=ScratchStore(),
    )
    config = AgentConfig(
        provider=SurrogatePolicy(),
        toolkit=Toolkit(build_desk_tools(ctx)),
        context=ContextPolicy(),
        budget=RunBudget(max_cost=5.0, max_steps=40, max_prompt_tokens=40_000),
        hitl_mode=hitl_mode,
        hitl_script=script or {},
        checkpointer=Checkpointer(db),
        # These tests are about parking and resuming, not about the critic.
        critic_rounds=0,
    )
    return Agent(config, world=world, kb=kb), ctx, scenario


def test_approval_parks_the_run_with_a_readable_payload(tmp_path):
    agent, ctx, scenario = _build(tmp_path / "runs.db")
    result = agent.run(scenario.brief, task_id=scenario.id, arm="hitl", ctx=ctx)

    assert result.status == "interrupted"
    payload = result.interrupted
    assert payload["kind"] == "approval"
    assert payload["tool"] == "issue_refund"
    assert payload["args"]["amount"] == pytest.approx(459.0)
    # parked, not paid
    assert agent.world.state()["refunds"] == []


def test_a_second_process_can_list_and_resolve_the_pending_run(tmp_path):
    db = tmp_path / "runs.db"
    agent, ctx, scenario = _build(db)
    result = agent.run(scenario.brief, task_id=scenario.id, arm="hitl", ctx=ctx)

    # A different process: only the database file is shared.
    fresh = Checkpointer(db)
    pending = fresh.pending_interrupts()
    assert len(pending) == 1
    assert pending[0]["run_id"] == result.run_id
    assert pending[0]["interrupt"]["tool"] == "issue_refund"

    agent2, ctx2, _ = _build(db)
    resumed = agent2.resume(result.run_id, {"approved": True, "by": "alice"}, ctx=ctx2)

    assert resumed.status == "ok"
    refunds = agent2.world.state()["refunds"]
    assert len(refunds) == 1, "resume must not re-fire a completed side effect"
    assert float(refunds[0]["amount"]) == pytest.approx(459.0)
    assert [t["status"] for t in agent2.world.state()["tickets"]] == ["resolved"]
    assert any(a["payload"].get("resumed") for a in resumed.events if a["type"] == "approval_decision")


def test_a_rejected_verdict_lands_no_money(tmp_path):
    db = tmp_path / "runs.db"
    agent, ctx, scenario = _build(db)
    result = agent.run(scenario.brief, task_id=scenario.id, arm="hitl", ctx=ctx)

    agent2, ctx2, _ = _build(db)
    resumed = agent2.resume(result.run_id, {"approved": False, "by": "bob", "note": "insufficient evidence"}, ctx=ctx2)

    assert agent2.world.state()["refunds"] == []
    assert resumed.status in {"ok", "stalled"}
    assert resumed.guardrail_blocks == 0  # nothing was blocked: the human said no
    tickets = {t["id"]: t for t in agent2.world.state()["tickets"]}
    assert list(tickets.values())[0]["status"] != "open", "a rejected action must still reach a disposition"
