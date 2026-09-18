"""The agent loop.

Everything a framework usually spreads across a graph DSL collapses here into one
function plus four behaviours that are *not* in the prompt:

* **budget with degradation** — hitting a ceiling does not raise first. The run
  sheds optional context (skills, SOP briefing), tightens its own compaction, then
  asks the model to bank a partial result, and only then aborts. A hard failure
  throws away work that was already paid for.
* **idempotent resume** — each tool execution is recorded under an idempotency key.
  Resuming a checkpointed run replays stored results instead of firing the side
  effect twice, which is the bug class that turns "durable execution" into
  "durable duplicate refunds".
* **deterministic critique** — after the model stops, world state is audited against
  invariants. Violations come back as a user turn, bounded by critic_rounds.
* **rationale capture** — every step records why it happened, so the trace is
  evidence and not a transcript.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from ..context.engine import ContextEngine, ContextPolicy
from ..llm.base import ChatRequest, ChatResponse, Pricing, Provider, Usage, user_message
from ..support.text import ScratchStore, estimate_request_tokens
from .budget import BudgetExceeded, RunBudget, UsageLedger
from .events import HitlMode, RunContext
from .hitl import Interrupt
from .toolkit import Tool, ToolResult, Toolkit

Strategy = Literal["react", "plan_execute", "reflexion", "hierarchical"]

SYSTEM_TEMPLATE = """You are the after-sales service agent for an e-commerce operator.
You act only through the tools below. Rules:
1. Never invent an order id, customer id or amount. Read it, or ask via set_ticket_pending_info.
2. Before any refund or coupon, the policy computation must exist. Money you did not derive is money you cannot move.
3. Search the SOP before deciding; cite the section id you relied on in the close-out summary.
4. When policy forbids an action, do not retry it. Explain it to the customer and close, or escalate with facts, basis, options and a recommendation.
5. Prefer the narrowest call that answers the question. Do not re-read records you already have.
6. When you are done, reply with a plain-text outcome and no tool call.

Tools:
{tools}"""

PLAN_INSTRUCTION = """First emit a numbered plan as plain text (3-6 steps), then act on it.
Before each tool call, say in one line which plan step it serves. Revise the plan only
when a tool result contradicts it, and say so."""

CRITIC_TEMPLATE = """An automatic audit of the world state found problems with your last attempt:

{findings}

Fix them with tool calls. Do not restate your reasoning; act."""

FINALIZE_INSTRUCTION = """Budget is nearly exhausted. Stop opening new lines of work: bank what you have.
Write a handover summary (what was verified, what remains) and close or escalate the ticket."""


@dataclass(slots=True)
class AgentConfig:
    provider: Provider
    toolkit: Toolkit
    model: str = "deepseek-chat"
    temperature: float = 0.0
    seed: int | None = 7
    max_iterations: int = 16
    strategy: Strategy = "react"
    context: ContextPolicy = field(default_factory=ContextPolicy)
    budget: RunBudget = field(default_factory=RunBudget)
    pricing: Pricing = field(default_factory=Pricing)
    hitl_mode: HitlMode = "auto_approve"
    hitl_script: dict[str, bool] = field(default_factory=dict)
    critic_rounds: int = 1
    enable_sop_briefing: bool = True
    enable_skills: bool = False
    soft_degrade: bool = True
    checkpointer: Any = None
    max_repair_attempts: int = 2


@dataclass(slots=True)
class RunResult:
    run_id: str
    task_id: str
    arm: str
    status: Literal["ok", "budget_aborted", "interrupted", "stalled", "error"]
    final_text: str
    steps: int
    calls: int
    cost: float
    usage: Usage
    context: dict[str, int]
    guardrail_blocks: int
    rejected_calls: int
    tool_errors: int
    findings: list[dict[str, str]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    interrupted: dict[str, Any] | None = None
    error: str = ""
    wall_s: float = 0.0
    degraded: list[str] = field(default_factory=list)
    skills_applied: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "arm": self.arm,
            "status": self.status,
            "final_text": self.final_text,
            "steps": self.steps,
            "calls": self.calls,
            "cost": round(self.cost, 6),
            "usage": self.usage.as_dict(),
            "context": self.context,
            "guardrail_blocks": self.guardrail_blocks,
            "rejected_calls": self.rejected_calls,
            "tool_errors": self.tool_errors,
            "findings": self.findings,
            "interrupted": self.interrupted,
            "error": self.error,
            "wall_s": round(self.wall_s, 3),
            "degraded": self.degraded,
            "skills_applied": self.skills_applied,
        }


class Agent:
    def __init__(self, config: AgentConfig, *, world: Any = None, kb: Any = None, skills: Any = None) -> None:
        self.config = config
        self.ledger = UsageLedger(config.pricing)
        self.world = world
        self.kb = kb
        self.skills = skills

    # -------------------------------------------------------------------- run
    def run(self, task: str, *, task_id: str = "", arm: str = "", scratch: ScratchStore | None = None, ctx: RunContext | None = None) -> RunResult:
        """Run one task. Pass `ctx` to share state with tools built against it —
        guardrail counters and approval records only reach the trace if the tools and
        the loop agree on one RunContext."""
        ctx = ctx or RunContext(task_id=task_id, arm=arm, world=self.world, sop=self.kb, hitl_mode=self.config.hitl_mode, hitl_script=self.config.hitl_script)
        ctx.ledger = self.ledger
        ctx.scratch = scratch or ctx.scratch or ScratchStore()
        ctx.world = ctx.world or self.world
        ctx.sop = ctx.sop or self.kb
        ctx.hitl_mode = ctx.hitl_mode or self.config.hitl_mode
        ctx.run_id = ctx.run_id or uuid.uuid4().hex[:12]
        self.ledger.set_budget(ctx.run_id, self.config.budget)
        engine = ContextEngine(self.config.context, scratch=ctx.scratch)
        engine.pin(self._system_prompt())
        brief = self._briefing(task, ctx)
        engine.pin(brief, slot=len(engine.pins))
        engine.user(task)
        ctx.emit("run_start", task_id=task_id, arm=arm, strategy=self.config.strategy, prompt_tokens=estimate_request_tokens(engine.assemble()))
        return self._loop(ctx, engine, task)

    def resume(self, run_id: str, decision: dict[str, Any], *, task: str = "") -> RunResult:
        """Continue an interrupted run without re-firing any completed side effect."""
        if self.config.checkpointer is None:
            raise RuntimeError("resume requires a checkpointer")
        checkpoint = self.config.checkpointer.latest(run_id)
        if checkpoint is None:
            raise KeyError(f"no checkpoint for run {run_id}")
        state = checkpoint.state
        ctx = RunContext(
            run_id=run_id,
            task_id=state.get("task_id", ""),
            arm=state.get("arm", ""),
            world=self.world,
            sop=self.kb,
            ledger=self.ledger,
            scratch=ScratchStore(),
            hitl_mode=self.config.hitl_mode,
            hitl_script=state.get("hitl_script", {}),
        )
        ctx.computed.update(state.get("computed", {}))
        ctx.approvals.extend(state.get("approvals", []))
        ctx.guardrail_blocks = int(state.get("guardrail_blocks", 0))
        engine = ContextEngine.restore(state.get("context", {}), policy=self.config.context, scratch=ctx.scratch)
        ctx.emit("approval_decision", resumed=True, decision=decision, tool=state.get("interrupt", {}).get("tool"))
        decision_tool = (state.get("interrupt") or {}).get("tool")
        if decision_tool and decision.get("approved") is False:
            engine.tool_result(
                str(state.get("interrupt", {}).get("call_id", "call_0")),
                decision_tool,
                '{"ok": false, "error": "approval_rejected", "message": "a human rejected this action", '
                '"hint": "do not retry it; close the ticket citing the rejection or escalate"}',
            )
        else:
            for call in state.get("pending_calls", []):
                ctx.extra.setdefault("idempotent", {}).__setitem__(
                    f"{run_id}:{call['id']}", self.config.toolkit.execute(call["name"], call["arguments"], call_id=call["id"])
                )
        self.ledger.set_budget(run_id, RunBudget.from_dict(state.get("budget", {})))
        for usage in state.get("usage_history", []):
            self.ledger.record(run_id, Usage(**usage))
        for _ in range(int(state.get("steps", 0))):
            self.ledger.bump_step(run_id)
        ctx.events.extend(state.get("events", []))
        return self._loop(ctx, engine, task or state.get("task", ""))

    # ------------------------------------------------------------------ inner
    def _loop(self, ctx: RunContext, engine: ContextEngine, task: str) -> RunResult:
        cfg = self.config
        degrade_stage = 0
        repair_attempts = 0
        final_text = ""
        status: Literal["ok", "budget_aborted", "interrupted", "stalled", "error"] = "ok"
        stall = 0
        error = ""
        started = time.monotonic()
        plan_emitted = False

        try:
            for _ in range(cfg.max_iterations * 3):
                messages = engine.assemble()
                prompt_tokens = engine.stats.prompt_tokens
                try:
                    step = ctx.ledger.begin_call(ctx.run_id, prompt_tokens=prompt_tokens)
                except BudgetExceeded as exc:
                    if cfg.soft_degrade and degrade_stage < 3:
                        degrade_stage += 1
                        ctx.extra["degrade_stage"] = degrade_stage
                        note = self._degrade(engine, ctx, degrade_stage, exc)
                        if note is not None:
                            continue
                    status = "budget_aborted"
                    ctx.emit("budget_abort", dimension=exc.dimension, detail=exc.detail, banked_steps=ctx.steps)
                    final_text = final_text or self._bank_partial(ctx)
                    break

                if cfg.strategy == "plan_execute" and not plan_emitted and step <= 1:
                    engine.pin(user_message(PLAN_INSTRUCTION), slot=len(engine.pins))
                    plan_emitted = True

                request = ChatRequest(
                    messages=messages,
                    tools=cfg.toolkit.schemas(),
                    model=cfg.model,
                    temperature=cfg.temperature,
                    seed=cfg.seed,
                    tool_choice="auto",
                )
                response = cfg.provider.chat(request)
                ledger_record(self.ledger, ctx.run_id, response, prompt_tokens)
                ctx.emit(
                    "model_call",
                    step=step,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=response.usage.output_tokens,
                    cached=response.cached,
                    rationale=(response.content or "")[:400],
                    requested_tools=[tc.name for tc in response.tool_calls],
                )

                if not response.tool_calls:
                    final_text = response.content or ""
                    verdict = self._critique(ctx, engine, final_text)
                    stall = 0
                    if verdict == "continue":
                        continue
                    break

                engine.assistant(
                    response.content or "",
                    [tc.as_dict() for tc in response.tool_calls],
                )
                repeated_only = True
                for tc in response.tool_calls:
                    if ctx.pending_interrupt is not None:
                        ctx.pending_interrupt["call_id"] = tc.id
                        raise Interrupt(ctx.pending_interrupt)
                    result = self._execute(ctx, tc)
                    if result is None:  # pragma: no cover - guarded by Interrupt
                        raise Interrupt(ctx.pending_interrupt or {"run_id": ctx.run_id})
                    engine.tool_result(tc.id, tc.name, result.content)
                    blocked = bool(result.error) and (result.error or {}).get("error") != "repeated_call"
                    repeated_only = repeated_only and not (result.ok or blocked)
                    if not result.ok:
                        repair_attempts += 1
                # A step where *every* call was already made verbatim means the model is
                # spinning, not repairing. Two of those and the run is closed out.
                stall = 0 if not repeated_only else stall + 1
                if stall >= 2:
                    status = "stalled"
                    ctx.emit("error", reason="stalled", detail=f"{stall} consecutive steps of verbatim repeated calls")
                    final_text = final_text or self._bank_partial(ctx)
                    self._checkpoint(ctx, engine, task, status=status, final_text=final_text)
                    break
                self._checkpoint(ctx, engine, task, status="running", pending_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls])

            else:
                status = "budget_aborted"
                ctx.emit("budget_abort", dimension="iterations", detail=f"max_iterations={cfg.max_iterations}")
                final_text = final_text or self._bank_partial(ctx)
        except Interrupt as exc:
            status = "interrupted"
            self._checkpoint(ctx, engine, task, status="interrupted", interrupt=exc.payload)
            return self._result(ctx, engine, status, final_text, exc.payload, "", started)
        except Exception as exc:  # noqa: BLE001 - a run must always close with evidence
            status = "error"
            import traceback

            error = f"{type(exc).__name__}: {exc}\n" + traceback.format_exc(limit=4)
            ctx.emit("error", detail=str(exc)[:400])
        self._checkpoint(ctx, engine, task, status=status, final_text=final_text)
        return self._result(ctx, engine, status, final_text, None, error, started)

    def _execute(self, ctx: RunContext, tc: Any) -> Any:
        """Dispatch with resume-safety: a call already executed under this run replays."""
        key = f"{ctx.run_id}:{tc.id}"
        memo = ctx.extra.setdefault("idempotent", {})
        if key in memo:
            ctx.emit("tool_result", name=tc.name, replayed=True, call_id=tc.id)
            return memo[key]
        signature = f"{tc.name}|{json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False, default=str)}"
        seen = ctx.extra.setdefault("signatures", {})
        seen[signature] = seen.get(signature, 0) + 1
        if seen[signature] > 2:
            ctx.rejected_calls += 1
            ctx.emit("loop_guard", name=tc.name, times=seen[signature], arguments=tc.arguments)
            return ToolResult(
                name=tc.name,
                ok=False,
                content=json.dumps(
                    {
                        "error": "repeated_call",
                        "message": f"{tc.name} was already called with exactly these arguments {seen[signature] - 1} times",
                        "hint": "the previous result is already in your context; act on it, change your arguments, or escalate. Repeating it will not change it.",
                        "retryable": False,
                    },
                    ensure_ascii=False,
                ),
                error={"error": "repeated_call"},
            )
        ctx.emit("tool_call", name=tc.name, call_id=tc.id, arguments=tc.arguments)
        result = self.config.toolkit.execute(tc.name, tc.arguments, call_id=tc.id)
        if result.validation_problems:
            ctx.rejected_calls += 1
            ctx.emit("tool_rejected", name=tc.name, problems=result.validation_problems)
        if result.error and result.error.get("code") in {
            "missing_computation",
            "policy_denied",
            "amount_mismatch",
            "escalation_required",
            "coupon_denied",
            "address_locked",
            "summary_incomplete",
        }:
            ctx.emit("guardrail_block", name=tc.name, code=result.error.get("code"))
        if not result.ok:
            ctx.emit("tool_result", name=tc.name, ok=False, code=(result.error or {}).get("error"), detail=str((result.error or {}).get("message", ""))[:160])
        else:
            ctx.emit("tool_result", name=tc.name, ok=True, latency_ms=result.latency_ms)
        memo[key] = result
        return result

    def _degrade(self, engine: ContextEngine, ctx: RunContext, stage: int, exc: BudgetExceeded) -> str | None:
        """Shed cost in the order that loses the least judgement. Returns '' when the
        stage changed the context enough to retry the loop immediately."""
        if stage == 1:
            ctx.extra["degraded"] = ctx.extra.get("degraded", []) + ["drop_briefing"]
            engine.pins = [p for p in engine.pins if "[RETRIEVED SKILLS]" not in str(p.get("content", "")) and "[POLICY BRIEFING]" not in str(p.get("content", ""))]
            ctx.emit("compact", reason="budget_degrade", action="drop_briefing", detail=exc.detail)
            return "retry"
        if stage == 2:
            ctx.extra["degraded"] = ctx.extra.get("degraded", []) + ["tighten_compaction"]
            engine.policy.compact_threshold = 0.45
            engine.policy.keep_recent_blocks = 2
            engine._maybe_compact()
            ctx.emit("compact", reason="budget_degrade", action="tighten_compaction")
            return "retry"
        if stage == 3:
            ctx.extra["degraded"] = ctx.extra.get("degraded", []) + ["finalize_early"]
            engine.pin(user_message(FINALIZE_INSTRUCTION), slot=len(engine.pins))
            ctx.emit("compact", reason="budget_degrade", action="finalize_early")
            self.ledger.set_budget(
                ctx.run_id,
                RunBudget(
                    max_cost=exc and float(self.config.budget.max_cost),
                    max_steps=self.ledger.step(ctx.run_id) + 2,
                    max_wall_s=60.0,
                    max_prompt_tokens=self.config.budget.max_prompt_tokens,
                ),
            )
            return "retry"
        return None

    def _critique(self, ctx: RunContext, engine: ContextEngine, final_text: str) -> str:
        from .verify import audit, violations

        if self.world is None or ctx.critic_rounds >= self.config.critic_rounds:
            return "stop"
        found = violations(audit(self.world, sop_ids=self.kb.section_ids() if self.kb else None, ticket_id=_ticket_of(ctx.task_id, final_text)))
        if not found:
            return "stop"
        ctx.critic_rounds += 1
        ctx.emit("critic", findings=[f.as_dict() for f in found], round=ctx.critic_rounds)
        engine.user(CRITIC_TEMPLATE.format(findings="\n".join(f"- {f.as_instruction()}" for f in found[:6])))
        return "continue"

    def _bank_partial(self, ctx: RunContext) -> str:
        return (
            "[partial result banked at budget ceiling]\n"
            + "\n".join(f"- {e.payload.get('name')}" for e in ctx.of_type("tool_call")[-4:])
        )

    def _briefing(self, task: str, ctx: RunContext | None = None) -> str:
        blocks: list[str] = []
        if self.config.enable_sop_briefing and self.kb is not None:
            hits = self.kb.search(task, top_k=2)
            if hits:
                blocks.append("[POLICY BRIEFING]\n" + "\n\n".join(f"[{d.id}]\n{d.text[:600]}" for d, _ in hits))
        if self.config.enable_skills and self.skills is not None:
            matched = self.skills.search(task, top_k=3)
            if matched:
                picked = [s.id for s, _ in matched]
                blocks.append("[RETRIEVED SKILLS]\n" + "\n\n".join(s.render() for s, _ in matched))
                if ctx is not None:
                    ctx.skills_retrieved = picked
                    ctx.skills_applied = picked
                    ctx.emit("skill_retrieved", skill_ids=picked, names=[s.name for s, _ in matched])
        return "\n\n".join(blocks) if blocks else ""

    def _system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(tools=self.config.toolkit.prompt_section())

    def _checkpoint(self, ctx: RunContext, engine: ContextEngine, task: str, **extra: Any) -> None:
        cp = self.config.checkpointer
        if cp is None:
            return
        state = {
            "task_id": ctx.task_id,
            "arm": ctx.arm,
            "task": task,
            "context": engine.snapshot(),
            "computed": ctx.computed,
            "approvals": ctx.approvals,
            "guardrail_blocks": ctx.guardrail_blocks,
            "hitl_script": ctx.hitl_script,
            "budget": self.config.budget.as_dict(),
            "steps": self.ledger.step(ctx.run_id),
            "usage_history": [e.usage.as_dict() | {"cached_input_tokens": e.usage.cached_input_tokens} for e in self.ledger.entries(ctx.run_id)],
            "events": ctx.as_dicts()[-40:],
            "idempotent": {k: v.content for k, v in ctx.extra.get("idempotent", {}).items()},
            "interrupt": ctx.pending_interrupt,
            **extra,
        }
        cp.save(ctx.run_id, state, task_id=ctx.task_id, arm=ctx.arm)

    def _result(self, ctx: RunContext, engine: ContextEngine, status: str, final_text: str, interrupt: dict | None, error: str, started: float) -> RunResult:
        usage = self.ledger.snapshot(ctx.run_id)
        return RunResult(
            run_id=ctx.run_id,
            task_id=ctx.task_id,
            arm=ctx.arm,
            status=status,  # type: ignore[arg-type]
            final_text=final_text,
            steps=self.ledger.step(ctx.run_id),
            calls=usage.calls,
            cost=self.ledger.cost(ctx.run_id),
            usage=usage,
            context=engine.stats.as_dict(),
            guardrail_blocks=ctx.guardrail_blocks,
            rejected_calls=ctx.rejected_calls,
            tool_errors=sum(1 for e in ctx.of_type("tool_result") if e.payload.get("ok") is False),
            findings=[p for e in ctx.of_type("critic") for p in e.payload.get("findings", [])],
            events=ctx.as_dicts(),
            interrupted=interrupt,
            error=error,
            wall_s=time.monotonic() - started,
            degraded=ctx.extra.get("degraded", []),
            skills_applied=ctx.skills_applied,
        )


def ledger_record(ledger: UsageLedger, run_id: str, response: ChatResponse, prompt_tokens: int) -> None:
    ledger.record(run_id, response.usage, prompt_tokens=prompt_tokens, cached=response.cached)


def _ticket_of(task_id: str, _text: str) -> str | None:
    return task_id if task_id.startswith("T") else None
