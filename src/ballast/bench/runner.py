"""Suite runner: the same scenarios, the same tasks, many runtime arms.

An *arm* is a set of runtime choices — offload on/off, compaction on/off, briefing
injected or retrieved, critic rounds, budget ceiling, skills enabled. Every arm sees
identical scenarios and identical world state, so any difference in the record is a
difference the harness made, and the report can attribute it.

Runs are independent by construction: each gets its own in-memory world, its own
ledger, its own scratch store. Concurrency is a thread pool over *runs*, never over
steps, so a shared budget counter cannot make the numbers lie.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..context.engine import ContextPolicy
from ..env.fixtures import Scenario, apply_faults, scenarios
from ..env.incident_fixtures import apply_faults as apply_ops_faults
from ..env.knowledge import KnowledgeBase, runbook_kb
from ..kernel.agent import Agent, AgentConfig
from ..kernel.budget import RunBudget
from ..kernel.events import RunContext
from ..kernel.verify import audit as audit_desk
from ..kernel.toolkit import Toolkit
from ..llm.base import Pricing
from ..llm.cache import ResponseCache
from ..llm.provider import OpenAICompatProvider
from ..llm.ops_surrogate import OpsProfile, OpsSurrogatePolicy
from ..llm.surrogate import ScriptedModel, SurrogatePolicy, SurrogateProfile
from ..memory.episodic import EpisodeStore, RunRecord
from ..memory.skills import Skill, SkillLibrary
from ..support.text import ScratchStore
from ..tools.desk import build_desk_tools
from ..tools.ops import build_ops_tools
from .faults import attribute, summarise
from .graders import Grade, grade
from .incident_graders import grade as grade_ops


@dataclass(slots=True)
class Arm:
    name: str
    note: str
    context: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)

    def merge(self, base: "Arm") -> "Arm":
        return Arm(
            name=self.name,
            note=self.note or base.note,
            context={**base.context, **self.context},
            budget={**base.budget, **self.budget},
            runtime={**base.runtime, **self.runtime},
            profile={**base.profile, **self.profile},
        )


# A real serving window, not an infinite one: "no context control" is only a fair arm
# if the transcript can actually outgrow the model.
REAL_WINDOW = {"max_cost": 1e6, "max_steps": 400, "max_wall_s": 900.0, "max_prompt_tokens": 32_000}
TIGHT = {"max_cost": 0.5, "max_steps": 60, "max_wall_s": 300.0, "max_prompt_tokens": 9_000}

BASE = Arm(
    name="ballast",
    note="default runtime: offload + compaction + retrieved briefing + one critic round",
    context={"token_budget": 9_000, "compact_threshold": 0.85, "offload_threshold": 1_200, "keep_recent_blocks": 8, "offload_exempt": ["read_scratch"]},
    budget={"max_cost": 6.0, "max_steps": 400, "max_wall_s": 900.0, "max_prompt_tokens": 32_000},
    runtime={"strategy": "react", "critic_rounds": 1, "enable_sop_briefing": True, "enable_skills": False, "soft_degrade": True, "max_iterations": 120},
)

DEFAULT_ARMS: dict[str, Arm] = {
    "naive": Arm(
        "naive",
        "no context control, no critic, unbounded budget — the default most demos ship",
        context={"enable_offload": False, "enable_compaction": False, "token_budget": 400_000},
        budget=dict(REAL_WINDOW),
        runtime={"critic_rounds": 0, "enable_sop_briefing": False, "soft_degrade": False, "max_iterations": 120},
    ),
    "ballast": BASE,
    "no_offload": Arm("no_offload", "tool outputs stay verbatim in the transcript", context={"enable_offload": False}, runtime={"enable_skills": False}, budget=BASE.budget),
    "no_compaction": Arm("no_compaction", "transcript is never folded", context={"enable_compaction": False}, budget=BASE.budget),
    "no_context_control": Arm(
        "no_context_control",
        "both offload and compaction disabled, everything else identical to ballast",
        context={"enable_offload": False, "enable_compaction": False},
        budget=BASE.budget,
    ),
    "static_briefing": Arm("static_briefing", "whole SOP pasted into the system prompt instead of retrieved", runtime={"briefing_mode": "static"}, budget=BASE.budget),
    "tight_budget": Arm("tight_budget", "budget too small to finish naively; forces soft degradation", budget=dict(TIGHT), runtime={"max_iterations": 60}, context={"token_budget": 5_000, "offload_threshold": 1_200, "keep_recent_blocks": 8, "offload_exempt": ["read_scratch"]}),
    "no_budget": Arm("no_budget", "no ceiling: what the same policy costs when nothing stops it", budget={"max_cost": 1e6, "max_steps": 400, "max_wall_s": 900.0, "max_prompt_tokens": 1_000_000}),
    "hierarchical": Arm("hierarchical", "planner -> worker -> critic", runtime={"strategy": "plan_execute", "critic_rounds": 2}, budget=BASE.budget),
    "defective": Arm("defective", "policy that skips the mandatory computation step (guardrail target)", profile={"skip_verification": True}, budget=BASE.budget),
    "ops_unassessed": Arm("ops_unassessed", "ops policy that pages and reverts without a policy assessment", profile={"skip_assessment": True}, budget=BASE.budget),
    "ops_reckless": Arm("ops_reckless", "ops policy that rolls back whatever it likes, ignoring the safety gate", profile={"force_rollback": True}, budget=BASE.budget),
    "noisy": Arm("noisy", "policy that emits malformed arguments", profile={"malformed_rate": 0.35}, budget=BASE.budget),
    "bloated": Arm("bloated", "policy that pulls whole lists instead of one record", profile={"blind_listing": True}, budget=BASE.budget),
}


def resolve_arm(name: str) -> Arm:
    arm = DEFAULT_ARMS[name]
    return arm.merge(BASE) if name not in ("ballast", "naive") else arm


@dataclass(slots=True)
class RunRecordRow:
    arm: str
    scenario_id: str
    rep: int
    ok: bool
    status: str
    cost: float
    calls: int
    steps: int
    prompt_tokens_total: int
    prompt_tokens_peak: int
    completion_tokens: int
    cached_input_tokens: int
    offloads: int
    compactions: int
    saved_tokens: int
    guardrail_blocks: int
    rejected_calls: int
    tool_errors: int
    critic_rounds: int
    wall_s: float
    degraded: list[str] = field(default_factory=list)
    faults: dict[str, Any] = field(default_factory=dict)
    failed_checks: list[str] = field(default_factory=list)
    skills_applied: list[str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SuiteResult:
    generated_at: str
    provider: str
    model: str
    reps: int
    rows: list[RunRecordRow]
    arms: dict[str, str] = field(default_factory=dict)

    def arms_summary(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for arm_name in self.arms:
            rows = [r for r in self.rows if r.arm == arm_name]
            if not rows:
                continue
            successes = Counter(r.scenario_id for r in rows if r.ok)
            n = len(rows)
            per_task: dict[str, list[bool]] = {}
            for r in rows:
                per_task.setdefault(r.scenario_id, []).append(r.ok)
            pass_by_task = {s: sum(1 for v in per if v) / len(per) for s, per in per_task.items()}
            out[arm_name] = {
                "runs": n,
                "successes": sum(successes.values()),
                "success_rate": sum(1 for r in rows if r.ok) / n,
                "mean_cost": sum(r.cost for r in rows) / n,
                "total_cost": sum(r.cost for r in rows),
                "mean_prompt_tokens": sum(r.prompt_tokens_total for r in rows) / n,
                "peak_prompt_tokens": max(r.prompt_tokens_peak for r in rows),
                "mean_calls": sum(r.calls for r in rows) / n,
                "mean_steps": sum(r.steps for r in rows) / n,
                "offloads": sum(r.offloads for r in rows),
                "compactions": sum(r.compactions for r in rows),
                "saved_tokens": sum(r.saved_tokens for r in rows),
                "guardrail_blocks": sum(r.guardrail_blocks for r in rows),
                "rejected_calls": sum(r.rejected_calls for r in rows),
                "degradations": sum(len(r.degraded) for r in rows),
                "fault_owners": _merge_owners(rows),
                "pass_by_task": pass_by_task,
            }
        return out

    def to_json(self, path: Path | str) -> None:
        payload = {
            "generated_at": self.generated_at,
            "provider": self.provider,
            "model": self.model,
            "reps": self.reps,
            "arms": self.arms,
            "summary": self.arms_summary(),
            "rows": [r.as_dict() for r in self.rows],
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def make_provider(kind: str = "surrogate", *, profile: SurrogateProfile | None = None, cache_dir: Path | str | None = None, model: str = "deepseek-chat", scripted: ScriptedModel | None = None, domain: str = "desk", profile_fields: dict[str, Any] | None = None) -> Any:
    if scripted is not None:
        return scripted
    if kind in ("surrogate", "", None):
        # Each domain ships its own offline policy driver; the arm's knobs are filtered
        # to whatever that driver actually accepts.
        if domain == "ops":
            return OpsSurrogatePolicy(OpsProfile(**_known(OpsProfile, profile_fields or {})))
        return SurrogatePolicy(profile)
    import os

    api_key = os.environ.get("BALLAST_LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    base_url = os.environ.get("BALLAST_LLM_BASE_URL", "https://api.deepseek.com")
    return OpenAICompatProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        cache=ResponseCache(Path(cache_dir or ".ballast/cache")) if cache_dir else None,
    )


def run_scenario(
    scenario: Scenario,
    arm: Arm,
    *,
    rep: int = 0,
    provider_kind: str = "surrogate",
    kb: KnowledgeBase | None = None,
    skills: SkillLibrary | None = None,
    pricing: Pricing | None = None,
    cache_dir: Path | str | None = None,
    model: str = "deepseek-chat",
) -> tuple[RunRecordRow, Grade, dict[str, Any]]:
    domain = getattr(scenario, "domain", "desk")
    ops = domain == "ops"
    world = scenario.build_world()
    (apply_ops_faults if ops else apply_faults)(scenario, world)
    kb = kb or (runbook_kb() if ops else KnowledgeBase.from_dir())
    verdicts = {"issue_refund": bool(scenario.expect.get("hitl"))} if not ops else {"page_oncall": True, "rollback_deploy": True}
    ctx = RunContext(task_id=scenario.id, arm=arm.name, world=world, sop=kb, hitl_mode="scripted", hitl_script=verdicts)
    ctx.scratch = ScratchStore()
    toolkit = Toolkit(build_ops_tools(ctx) if ops else build_desk_tools(ctx))
    provider = make_provider(
        provider_kind,
        profile=SurrogateProfile(**_known(SurrogateProfile, arm.profile)) if arm.profile else None,
        cache_dir=cache_dir,
        model=model,
        domain=domain,
        profile_fields=arm.profile,
    )

    from ..env.incident_verify import audit as audit_ops

    runtime = dict(arm.runtime)
    briefing_mode = runtime.pop("briefing_mode", "retrieved")
    config = AgentConfig(
        provider=provider,
        toolkit=toolkit,
        model=model,
        context=ContextPolicy(**{**asdict(ContextPolicy()), **arm.context}),
        budget=RunBudget(**{**_BUDGET_DEFAULTS, **_budget_args(arm.budget)}),
        pricing=pricing or Pricing(),
        invariant_check=(lambda w, c: audit_ops(w)) if ops else (lambda w, c: audit_desk(w, sop_ids=kb.section_ids(), ticket_id=_scoped_ticket(c.task_id))),
        **runtime,
    )
    agent = Agent(config, world=world, kb=kb, skills=skills)

    if briefing_mode == "static":
        agent.config.enable_sop_briefing = False

    started = time.monotonic()
    result = agent.run(scenario.brief, task_id=scenario.id, arm=arm.name, ctx=ctx)
    elapsed = time.monotonic() - started

    g = (grade_ops if ops else grade)(scenario, world, sop_ids=kb.section_ids(), events=result.events)
    fault_list = attribute(result.events, steps=result.steps, status=result.status)
    if not g.ok and not fault_list:
        fault_list = attribute(result.events, steps=result.steps, status="no_action")
    row = RunRecordRow(
        arm=arm.name,
        scenario_id=scenario.id,
        rep=rep,
        ok=g.ok,
        status=result.status,
        cost=result.cost,
        calls=result.calls,
        steps=result.steps,
        prompt_tokens_total=agent.ledger.total_prompt_tokens(result.run_id),
        prompt_tokens_peak=result.context.get("peak_prompt_tokens", 0),
        completion_tokens=result.usage.output_tokens,
        cached_input_tokens=result.usage.cached_input_tokens,
        offloads=result.context.get("offloads", 0),
        compactions=result.context.get("compactions", 0),
        saved_tokens=result.context.get("saved_tokens", 0),
        guardrail_blocks=result.guardrail_blocks,
        rejected_calls=result.rejected_calls,
        tool_errors=result.tool_errors,
        critic_rounds=sum(1 for e in result.events if e["type"] == "critic"),
        wall_s=round(elapsed, 4),
        degraded=result.degraded,
        faults=summarise(fault_list),
        failed_checks=g.failed,
        skills_applied=result.skills_applied,
    )
    return row, g, {"result": result, "world": world, "agent": agent}


def _scoped_ticket(task_id: str) -> str | None:
    """The desk critic only judges a ticket when the run is named after one."""
    return task_id if task_id.startswith("T") else None


class UnknownTask(KeyError):
    """A checkpoint whose task is no longer in the scenario library."""


def find_scenario(scenario_id: str) -> Any:
    """Resolve a task across both domains; a checkpoint stores only an id."""
    from ..env.incident_fixtures import scenarios as incident_scenarios

    for pool in (scenarios(), incident_scenarios()):
        for candidate in pool:
            if candidate.id == scenario_id:
                return candidate
    raise KeyError(scenario_id)


def resume_run(
    run_id: str,
    verdict: dict[str, Any],
    *,
    checkpointer: Any,
    provider_kind: str = "surrogate",
    model: str = "deepseek-chat",
) -> Any:
    """Rebuild the runtime that parked a run, then continue it.

    The whole point of a durable pause is that a *later, different* process can pick it
    up, so it has to be able to reconstruct the same arm — same budgets, same policy
    driver, same invariant checker — from the checkpoint's own arm name.
    """
    checkpoint = checkpointer.latest(run_id)
    if checkpoint is None:
        raise KeyError(run_id)
    task_id = checkpoint.state.get("task_id", "")
    try:
        scenario = find_scenario(task_id)
    except KeyError as exc:
        raise UnknownTask(task_id) from exc
    # An ad-hoc runtime (a test harness, an old build) may have parked the run under an
    # arm name that is no longer in the menu. Resumability should not depend on that.
    name = checkpoint.state.get("arm") or "ballast"
    arm = resolve_arm(name) if name in DEFAULT_ARMS else resolve_arm("ballast")
    # Resume is always a human-approval conversation, whatever the arm default was.
    arm.runtime = {**arm.runtime, "hitl_mode": "interrupt"}
    agent, ctx = build_agent(scenario, arm, provider_kind=provider_kind, model=model, checkpointer=checkpointer)
    return agent.resume(run_id, verdict, ctx=ctx)


def build_agent(scenario: Any, arm: Arm, *, provider_kind: str = "surrogate", model: str = "deepseek-chat", skills: Any = None, pricing: Pricing | None = None, cache_dir: Path | str | None = None, checkpointer: Any = None) -> tuple[Any, Any]:
    """Construct the agent and its shared RunContext for one (scenario, arm) pair."""
    from ..env.incident_verify import audit as audit_ops

    domain = getattr(scenario, "domain", "desk")
    ops = domain == "ops"
    world = scenario.build_world()
    (apply_ops_faults if ops else apply_faults)(scenario, world)
    kb = runbook_kb() if ops else KnowledgeBase.from_dir()
    verdicts = {"issue_refund": bool(scenario.expect.get("hitl"))} if not ops else {"page_oncall": True, "rollback_deploy": True}
    ctx = RunContext(task_id=scenario.id, arm=arm.name, world=world, sop=kb, hitl_mode="scripted", hitl_script=verdicts)
    ctx.scratch = ScratchStore()
    provider = make_provider(
        provider_kind,
        profile=SurrogateProfile(**_known(SurrogateProfile, arm.profile)) if arm.profile else None,
        cache_dir=cache_dir,
        model=model,
        domain=domain,
        profile_fields=arm.profile,
    )
    runtime = dict(arm.runtime)
    runtime.pop("briefing_mode", None)
    config = AgentConfig(
        provider=provider,
        toolkit=Toolkit(build_ops_tools(ctx) if ops else build_desk_tools(ctx)),
        model=model,
        context=ContextPolicy(**{**asdict(ContextPolicy()), **arm.context}),
        budget=RunBudget(**{**_BUDGET_DEFAULTS, **_budget_args(arm.budget)}),
        pricing=pricing or Pricing(),
        invariant_check=(lambda w, c: audit_ops(w)) if ops else (lambda w, c: audit_desk(w, sop_ids=kb.section_ids(), ticket_id=_scoped_ticket(c.task_id))),
        checkpointer=checkpointer,
        **runtime,
    )
    return Agent(config, world=world, kb=kb, skills=skills), ctx


def _known(cls: type, fields: dict[str, Any]) -> dict[str, Any]:
    allowed = set(getattr(cls, "__dataclass_fields__", {}))
    return {k: v for k, v in (fields or {}).items() if k in allowed}


def _budget_args(budget: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in budget.items() if k in {"max_cost", "max_steps", "max_wall_s", "max_prompt_tokens"}}


_BUDGET_DEFAULTS = {
    "max_cost": RunBudget.__dataclass_fields__["max_cost"].default,
    "max_steps": RunBudget.__dataclass_fields__["max_steps"].default,
    "max_wall_s": RunBudget.__dataclass_fields__["max_wall_s"].default,
    "max_prompt_tokens": RunBudget.__dataclass_fields__["max_prompt_tokens"].default,
}


def run_suite(
    *,
    suite: list[Scenario] | None = None,
    arms: list[str] | None = None,
    reps: int = 1,
    workers: int = 4,
    provider_kind: str = "surrogate",
    skills: SkillLibrary | None = None,
    store: EpisodeStore | None = None,
    cache_dir: Path | str | None = None,
    model: str = "deepseek-chat",
    progress: Callable[[str, str, bool], None] | None = None,
) -> SuiteResult:
    suite = suite or train_slice_all()
    arm_names = arms or list(DEFAULT_ARMS)
    resolved = {a.name: a for a in (resolve_arm(n) for n in arm_names)}
    jobs = [(scenario, arm, rep) for arm in resolved.values() for scenario in suite for rep in range(reps)]

    def work(job: tuple[Scenario, Arm, int]) -> RunRecordRow:
        scenario, arm, rep = job
        row, g, _ = run_scenario(scenario, arm, rep=rep, provider_kind=provider_kind, skills=skills, cache_dir=cache_dir, model=model)
        if store is not None:
            store.save(_to_run_record(row, scenario))
        if progress is not None:
            progress(arm.name, scenario.id, row.ok)
        return row

    started = time.monotonic()
    if workers > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(work, jobs))
    else:
        rows = [work(job) for job in jobs]

    return SuiteResult(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        provider=provider_kind,
        model=model if provider_kind != "surrogate" else "surrogate-policy",
        reps=reps,
        rows=rows,
        arms={name: arm.note for name, arm in resolved.items()},
    )


def _merge_owners(rows: list[RunRecordRow]) -> dict[str, int]:
    owners: Counter[str] = Counter()
    for row in rows:
        owners.update({str(k): int(v) for k, v in (row.faults.get("by_owner") or {}).items()})
    return dict(owners)


def _to_run_record(row: RunRecordRow, scenario: Scenario) -> RunRecord:
    return RunRecord(
        run_id=f"{scenario.id}:{row.arm}:{row.rep}",
        task_id=scenario.id,
        arm=row.arm,
        status=row.status,
        ok=row.ok,
        steps=row.steps,
        calls=row.calls,
        cost=row.cost,
        input_tokens=row.prompt_tokens_total,
        output_tokens=row.completion_tokens,
        prompt_tokens=row.prompt_tokens_total,
        compactions=row.compactions,
        offloads=row.offloads,
        guardrail_blocks=row.guardrail_blocks,
        critic_rounds=row.critic_rounds,
        summary="; ".join(row.failed_checks)[:500],
        findings=[{"code": c, "severity": "check", "detail": c, "fix": ""} for c in row.failed_checks],
    )


def train_slice_all() -> list[Scenario]:
    return [s for s in scenarios() if not s.holdout]


__all__ = ["Arm", "DEFAULT_ARMS", "RunRecordRow", "SuiteResult", "make_provider", "resolve_arm", "run_scenario", "run_suite", "Skill"]
