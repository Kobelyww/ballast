"""Cost metering and hard ceilings: `begin_call` must fire *before* the billable request."""

from __future__ import annotations

import time

import pytest

from ballast.kernel.budget import BudgetExceeded, LedgerEntry, RunBudget, UsageLedger
from ballast.kernel.events import RunContext
from ballast.llm.base import Pricing, Usage

PRICING = Pricing(input_per_m=2.0, cached_per_m=0.5, output_per_m=8.0)


def spend(ledger: UsageLedger, run_id: str, *, prompt: int = 1_000_000, completion: int = 0) -> float:
    return ledger.record(run_id, Usage(input_tokens=prompt, output_tokens=completion, calls=1))


class TestRunBudget:
    def test_defaults_and_serialisation(self) -> None:
        budget = RunBudget()
        assert budget.as_dict() == {"max_cost": 1.2, "max_steps": 24, "max_wall_s": 420.0, "max_prompt_tokens": 24_000}
        assert budget.currency == "CNY"

    def test_round_trip_through_a_dict(self) -> None:
        budget = RunBudget(max_cost=2.5, max_steps=7, max_wall_s=13.0, max_prompt_tokens=999)
        assert RunBudget.from_dict(budget.as_dict()).as_dict() == budget.as_dict()

    def test_from_dict_fills_missing_keys_and_coerces(self) -> None:
        restored = RunBudget.from_dict({"max_cost": "0.5", "max_steps": "3"})
        assert restored.max_cost == 0.5 and restored.max_steps == 3
        assert restored.max_wall_s == 420.0 and restored.max_prompt_tokens == 24_000

    def test_started_at_is_a_monotonic_stamp(self) -> None:
        before = time.monotonic()
        budget = RunBudget()
        assert budget.started_at >= before and budget.max_wall_s > 0


class TestLedgerAccounting:
    def test_empty_run_costs_nothing(self) -> None:
        ledger = UsageLedger(PRICING)
        assert ledger.cost("r") == 0.0
        assert ledger.snapshot("r") == Usage()
        assert ledger.total_prompt_tokens("r") == 0
        assert ledger.entries("r") == []
        assert ledger.step("r") == 0

    def test_cost_is_charged_at_recording_time(self) -> None:
        ledger = UsageLedger(PRICING)
        assert spend(ledger, "r", prompt=1_000_000, completion=500_000) == pytest.approx(6.0)
        assert ledger.cost("r") == pytest.approx(6.0)

    def test_runs_are_isolated(self) -> None:
        ledger = UsageLedger(PRICING)
        spend(ledger, "a", prompt=1_000_000)
        spend(ledger, "b", prompt=2_000_000)
        assert ledger.cost("a") == pytest.approx(2.0) and ledger.cost("b") == pytest.approx(4.0)
        assert ledger.step("a") == 0 and ledger.entries("b")[0].usage.input_tokens == 2_000_000

    def test_snapshot_merges_every_entry(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.record("r", Usage(input_tokens=10, output_tokens=1, cached_input_tokens=4, calls=1))
        ledger.record("r", Usage(input_tokens=20, output_tokens=2, calls=1))
        assert ledger.snapshot("r").as_dict() == {
            "input_tokens": 30,
            "output_tokens": 3,
            "cached_input_tokens": 4,
            "total_tokens": 33,
            "calls": 2,
        }

    def test_cached_input_is_cheaper_than_fresh_input(self) -> None:
        ledger = UsageLedger(PRICING)
        cached = ledger.record("c", Usage(input_tokens=1_000_000, cached_input_tokens=900_000, calls=1))
        fresh = ledger.record("f", Usage(input_tokens=1_000_000, calls=1))
        assert cached < fresh and cached == pytest.approx(fresh * (100_000 / 1_000_000 + 0.9 * 0.25))

    def test_bump_step_is_monotonic(self) -> None:
        ledger = UsageLedger(PRICING)
        assert [ledger.bump_step("r") for _ in range(3)] == [1, 2, 3]
        assert ledger.step("r") == 3

    def test_total_prompt_tokens_is_the_context_engineering_metric(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.record("r", Usage(input_tokens=5_000, calls=1), prompt_tokens=1_200)
        ledger.record("r", Usage(input_tokens=6_000, calls=1), prompt_tokens=900)
        assert ledger.total_prompt_tokens("r") == 2_100
        # ... and it is deliberately not the same thing as billed prompt tokens.
        assert ledger.snapshot("r").input_tokens == 11_000

    def test_cumulative_curve_is_a_burndown(self) -> None:
        ledger = UsageLedger(PRICING)
        for i in range(3):
            ledger.bump_step("r")
            ledger.record("r", Usage(input_tokens=1000 * (i + 1), output_tokens=10, calls=1), prompt_tokens=1000 * (i + 1), cached=i == 2)
        curve = ledger.cumulative("r")
        assert [c["step"] for c in curve] == [1, 2, 3]
        assert curve[-1]["tokens"] == sum(1000 * (i + 1) + 10 for i in range(3))
        assert curve[0]["cost"] < curve[1]["cost"] < curve[2]["cost"]
        assert [c["cached"] for c in curve] == [False, False, True]
        assert curve[2]["prompt_tokens"] == 3000

    def test_forget_drops_everything(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.set_budget("r", RunBudget())
        ledger.record("r", Usage(input_tokens=1, calls=1))
        ledger.bump_step("r")
        ledger.forget("r")
        assert ledger.cost("r") == 0.0 and ledger.step("r") == 0 and ledger.budget("r") is None

    def test_entries_are_copies(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.record("r", Usage(input_tokens=1, calls=1))
        ledger.entries("r").clear()
        assert len(ledger.entries("r")) == 1

    def test_default_pricing_is_used_when_none_given(self) -> None:
        ledger = UsageLedger()
        assert ledger.pricing == Pricing()
        assert ledger.record("r", Usage(input_tokens=1_000_000, calls=1)) == pytest.approx(Pricing().input_per_m)


class TestCeilings:
    def test_steps_are_charged_before_the_request(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.set_budget("r", RunBudget(max_cost=100.0, max_steps=2, max_wall_s=1e6, max_prompt_tokens=1e6))
        assert ledger.begin_call("r") == 1
        assert ledger.begin_call("r") == 2
        with pytest.raises(BudgetExceeded) as excinfo:
            ledger.begin_call("r")
        assert excinfo.value.dimension == "steps"
        assert ledger.step("r") == 2  # the rejected call never consumed a step

    def test_cost_ceiling_blocks_the_next_call_not_the_last_one(self) -> None:
        ledger = UsageLedger(PRICING)
        budget = RunBudget(max_cost=0.01, max_steps=99, max_wall_s=1e6, max_prompt_tokens=1e6)
        ledger.set_budget("r", budget)
        ledger.begin_call("r")
        spend(ledger, "r", prompt=10_000_000)  # 20.0 CNY: far over the ceiling
        with pytest.raises(BudgetExceeded, match="spent .* >= cap") as excinfo:
            ledger.begin_call("r")
        assert excinfo.value.dimension == "cost"

    def test_wall_time_ceiling(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.set_budget("r", RunBudget(max_cost=99.0, max_steps=99, max_wall_s=0.0, max_prompt_tokens=99))
        with pytest.raises(BudgetExceeded) as excinfo:
            ledger.begin_call("r")
        assert excinfo.value.dimension == "wall_time"

    def test_oversized_prompt_is_refused_before_it_is_billed(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.set_budget("r", RunBudget(max_cost=99.0, max_steps=99, max_wall_s=1e6, max_prompt_tokens=1_000))
        assert ledger.begin_call("r", prompt_tokens=1_000) == 1  # at the cap is allowed
        with pytest.raises(BudgetExceeded, match="assembled prompt is 1001 tokens") as excinfo:
            ledger.begin_call("r", prompt_tokens=1_001)
        assert excinfo.value.dimension == "prompt_tokens"

    def test_a_run_without_a_budget_is_unbounded(self) -> None:
        ledger = UsageLedger(PRICING)
        assert [ledger.begin_call("free", prompt_tokens=10**9) for _ in range(3)] == [1, 2, 3]
        assert ledger.budget("free") is None and ledger.cost("free") == 0.0

    def test_check_reports_the_first_violation_only(self) -> None:
        ledger = UsageLedger(PRICING)
        budget = RunBudget(max_cost=0.0, max_steps=0, max_wall_s=0.0, max_prompt_tokens=0)
        ledger.set_budget("r", budget)
        with pytest.raises(BudgetExceeded) as excinfo:
            ledger.check("r", budget)
        assert excinfo.value.dimension == "cost"

    def test_budget_lookup_round_trip(self) -> None:
        ledger = UsageLedger(PRICING)
        budget = RunBudget(max_cost=3.0)
        ledger.set_budget("r", budget)
        assert ledger.budget("r") is budget

    def test_error_message_names_the_dimension(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.set_budget("r", RunBudget(max_steps=0))
        with pytest.raises(BudgetExceeded, match=r"budget exceeded \(steps\): executed 0 steps >= cap 0"):
            ledger.begin_call("r")

    def test_entry_records_its_step(self) -> None:
        ledger = UsageLedger(PRICING)
        ledger.bump_step("r")
        ledger.bump_step("r")
        ledger.record("r", Usage(input_tokens=5, calls=1))
        entry = ledger.entries("r")[0]
        assert isinstance(entry, LedgerEntry) and entry.step == 2


class TestRunContextMetering:
    def test_events_are_stamped_with_the_ledger_step(self) -> None:
        ledger = UsageLedger(PRICING)
        ctx = RunContext(ledger=ledger)
        ledger.bump_step(ctx.run_id)
        ctx.emit("tool_call", name="get_ticket")
        assert ctx.events[-1].step == 1
        assert ctx.steps == 1

    def test_subscribers_see_every_event(self) -> None:
        seen: list[str] = []
        ctx = RunContext(subscribers=[lambda e: seen.append(e.type)])
        ctx.emit("plan", steps=3)
        ctx.emit("final", text="done")
        assert seen == ["plan", "final"]
        assert ctx.as_dicts()[0]["payload"] == {"steps": 3}
        assert ctx.of_type("final")[0].payload["text"] == "done"

    def test_tool_names_reads_the_call_stream(self) -> None:
        ctx = RunContext()
        ctx.emit("tool_call", name="get_ticket")
        ctx.emit("tool_result", name="get_ticket", ok=True)
        ctx.emit("tool_call", name="compute_refund")
        assert ctx.tool_names() == ["get_ticket", "compute_refund"]

    def test_event_serialisation_is_stable(self) -> None:
        ctx = RunContext()
        event = ctx.emit("offload", handle="scratch://x", tokens=12)
        assert event.as_dict()["type"] == "offload"
        assert set(event.as_dict()) == {"type", "step", "ts", "payload"}
        assert round(event.ts, 4) == event.as_dict()["ts"]

    def test_counters_start_at_zero(self) -> None:
        ctx = RunContext()
        assert (ctx.guardrail_blocks, ctx.rejected_calls, ctx.compactions) == (0, 0, 0)
        assert ctx.pending_interrupt is None and ctx.skills_applied == []
        assert len(ctx.run_id) == 12
