"""Cost metering and *hard* budget ceilings.

The design claim in one line: a ceiling you check afterwards is a report, not a
control. `begin_call` runs immediately before the next billable request, so the
worst case is bounded at exactly one call of over-spend instead of an unbounded
runaway loop. This is the module that lets `ballast` answer "what does this agent
cost when it goes wrong", which is the question a budget-less framework cannot ask.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..llm.base import Pricing, Usage


class BudgetExceeded(RuntimeError):
    def __init__(self, dimension: str, detail: str) -> None:
        super().__init__(f"budget exceeded ({dimension}): {detail}")
        self.dimension = dimension
        self.detail = detail


@dataclass(slots=True)
class RunBudget:
    max_cost: float = 1.20
    max_steps: int = 24
    max_wall_s: float = 420.0
    max_prompt_tokens: int = 24_000
    started_at: float = field(default_factory=time.monotonic)

    @property
    def currency(self) -> str:
        return "CNY"

    def as_dict(self) -> dict[str, float | int]:
        return {
            "max_cost": self.max_cost,
            "max_steps": self.max_steps,
            "max_wall_s": self.max_wall_s,
            "max_prompt_tokens": self.max_prompt_tokens,
        }

    @staticmethod
    def from_dict(data: dict) -> "RunBudget":
        return RunBudget(
            max_cost=float(data.get("max_cost", 1.20)),
            max_steps=int(data.get("max_steps", 24)),
            max_wall_s=float(data.get("max_wall_s", 420.0)),
            max_prompt_tokens=int(data.get("max_prompt_tokens", 24_000)),
        )


@dataclass(slots=True)
class LedgerEntry:
    usage: Usage
    cost: float
    step: int
    prompt_tokens_planned: int = 0
    cached: bool = False


class UsageLedger:
    """Accumulates usage per run id so concurrent eval runs cannot cross-contaminate."""

    def __init__(self, pricing: Pricing | None = None) -> None:
        self.pricing = pricing or Pricing()
        self._entries: dict[str, list[LedgerEntry]] = {}
        self._steps: dict[str, int] = {}
        self._budgets: dict[str, RunBudget] = {}

    def set_budget(self, run_id: str, budget: RunBudget) -> None:
        self._budgets[run_id] = budget

    def budget(self, run_id: str) -> RunBudget | None:
        return self._budgets.get(run_id)

    def record(self, run_id: str, usage: Usage, *, prompt_tokens: int = 0, cached: bool = False) -> float:
        cost = usage.cost(self.pricing)
        self._entries.setdefault(run_id, []).append(
            LedgerEntry(
                usage=usage,
                cost=cost,
                step=self._steps.get(run_id, 0),
                prompt_tokens_planned=prompt_tokens,
                cached=cached,
            )
        )
        return cost

    def snapshot(self, run_id: str) -> Usage:
        total = Usage()
        for entry in self._entries.get(run_id, []):
            total = total.merge(entry.usage)
        return total

    def cost(self, run_id: str) -> float:
        return sum(entry.cost for entry in self._entries.get(run_id, []))

    def total_prompt_tokens(self, run_id: str) -> int:
        """Sum of prompt tokens over every call: the quantity context engineering moves."""
        return sum(entry.prompt_tokens_planned for entry in self._entries.get(run_id, []))

    def entries(self, run_id: str) -> list[LedgerEntry]:
        return list(self._entries.get(run_id, []))

    def bump_step(self, run_id: str) -> int:
        self._steps[run_id] = self._steps.get(run_id, 0) + 1
        return self._steps[run_id]

    def step(self, run_id: str) -> int:
        return self._steps.get(run_id, 0)

    def check(self, run_id: str, budget: RunBudget) -> None:
        cost = self.cost(run_id)
        if cost >= budget.max_cost:
            raise BudgetExceeded("cost", f"spent {cost:.4f} >= cap {budget.max_cost:.4f}")
        step = self.step(run_id)
        if step >= budget.max_steps:
            raise BudgetExceeded("steps", f"executed {step} steps >= cap {budget.max_steps}")
        elapsed = time.monotonic() - budget.started_at
        if elapsed >= budget.max_wall_s:
            raise BudgetExceeded("wall_time", f"ran {elapsed:.0f}s >= cap {budget.max_wall_s:.0f}s")

    def begin_call(self, run_id: str, *, prompt_tokens: int = 0) -> int:
        """Charge a step, then enforce ceilings — before the request, not after."""
        budget = self._budgets.get(run_id)
        if budget is not None:
            self.check(run_id, budget)
            if prompt_tokens and prompt_tokens > budget.max_prompt_tokens:
                raise BudgetExceeded(
                    "prompt_tokens",
                    f"assembled prompt is {prompt_tokens} tokens >= cap {budget.max_prompt_tokens}",
                )
        return self.bump_step(run_id)

    def cumulative(self, run_id: str) -> list[dict[str, float | int]]:
        """(step, cumulative cost, cumulative tokens) — the burn-down curve the report plots."""
        running_cost = 0.0
        running_tokens = 0
        curve = []
        for entry in self._entries.get(run_id, []):
            running_cost += entry.cost
            running_tokens += entry.usage.total_tokens
            curve.append(
                {
                    "step": entry.step,
                    "cost": round(running_cost, 6),
                    "tokens": running_tokens,
                    "prompt_tokens": entry.usage.input_tokens,
                    "cached": entry.cached,
                }
            )
        return curve

    def forget(self, run_id: str) -> None:
        self._entries.pop(run_id, None)
        self._steps.pop(run_id, None)
        self._budgets.pop(run_id, None)
