"""Suite-wide invariants, checked over every scenario in the train slice.

These are the properties that must hold *whatever* a run does on the way there: money
is only moved after a policy computation for the same order, no order is ever refunded
beyond what was paid, a passing grade means no ticket was left lying open, and a run
that called a model costs something.

The whole slice runs once per session (the `train_runs` fixture) and every invariant
reads that same trace, so the suite stays a second-and-a-half affair instead of
re-running the benchmark four times.
"""

from __future__ import annotations

from typing import Any

import pytest

from ballast.bench.graders import Grade
from ballast.bench.runner import resolve_arm
from ballast.env.fixtures import Scenario
from ballast.env.policies import HIGH_RISK_SCORE
from ballast.kernel.verify import audit, violations
from conftest import assert_tool_calls_answered

# S17 and S18 are the long-horizon cases: they are tracked as known-failing tasks, so
# only the invariants below are asserted there - never the grade.
# Shared with test_end_to_end via conftest so the two lists cannot disagree.
from conftest import HARD_TIER as KNOWN_FAILING_LONG_HORIZON


def successful_calls(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(tool name, arguments) for every tool call that came back without an error.

    `tool_result` events carry a name and an `ok` flag but no call id, so the pairing is
    positional: calls are executed strictly in order, one result per call.
    """
    pending: list[tuple[str, dict[str, Any]]] = []
    done: list[tuple[str, dict[str, Any]]] = []
    for event in events:
        payload = event.get("payload", {}) or {}
        if event["type"] == "tool_call":
            pending.append((str(payload.get("name")), payload.get("arguments") or {}))
        elif event["type"] == "tool_result":
            name = str(payload.get("name"))
            for index, (called, arguments) in enumerate(pending):
                if called == name:
                    pending.pop(index)
                    if payload.get("ok") is True:
                        done.append((name, arguments))
                    break
    assert not pending, "a tool call in the trace never reported back"
    return done


def order_of(name: str, arguments: dict[str, Any], order_by_ticket: dict[str, str]) -> str | None:
    if arguments.get("order_id"):
        return str(arguments["order_id"])
    ticket = arguments.get("ticket_id")
    return order_by_ticket.get(str(ticket)) if ticket else None


@pytest.fixture(scope="module")
def train_runs_session(train_runs: list[tuple[Scenario, Any, Grade, dict[str, Any]]]) -> list[tuple[Scenario, Any, Grade, dict[str, Any]]]:
    return train_runs


def order_index(scenario: Scenario) -> dict[str, str]:
    return {str(t["id"]): str(t["order_id"]) for t in scenario.fixture.get("tickets", []) if t.get("order_id")}


class TestRefundNeedsComputation:
    def test_every_successful_refund_was_preceded_by_a_computation_for_that_order(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        offenders: list[str] = []
        for scenario, _row, _grade, extras in train_runs_session:
            events = extras["result"].events
            index = order_index(scenario)
            computed: set[str] = set()
            for name, arguments in successful_calls(events):
                order = order_of(name, arguments, index)
                if name == "compute_refund" and order:
                    computed.add(order)
                if name == "issue_refund" and order and order not in computed:
                    offenders.append(f"{scenario.id}: issue_refund({order}) without compute_refund")
        assert offenders == []

    def test_the_world_audit_table_agrees_with_the_trace(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        """The server-side record is the one that matters: a refund row must have a
        decision-bearing `compute_refund` action in front of it."""
        offenders = []
        for scenario, _row, _grade, extras in train_runs_session:
            actions = [a["tool"] for a in extras["world"].state()["actions"]]
            seen: set[str] = set()
            for tool_name in actions:
                if tool_name == "compute_refund":
                    seen.add("computed")
                if tool_name == "issue_refund" and "computed" not in seen:
                    offenders.append(f"{scenario.id}: audited refund without an audited computation")
        assert offenders == []

    def test_unverified_payment_is_never_found_clean(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        for scenario, _row, grade, extras in train_runs_session:
            if not grade.ok:
                continue
            found = [f.code for f in violations(audit(extras["world"], sop_ids=set(extras["agent"].kb.section_ids())))]
            assert "unverified_payment" not in found, f"{scenario.id}: {found}"
            assert "over_refund" not in found, f"{scenario.id}: {found}"


class TestMoneyIsBounded:
    def test_no_order_is_ever_refunded_beyond_what_was_paid(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        for scenario, _row, _grade, extras in train_runs_session:
            state = extras["world"].state()
            paid = {o["id"]: float(o["paid_amount"]) for o in state["orders"]}
            per_order: dict[str, float] = {}
            for refund in state["refunds"]:
                assert refund["amount"] >= 0, f"{scenario.id}: negative refund row"
                per_order[refund["order_id"]] = per_order.get(refund["order_id"], 0.0) + float(refund["amount"])
            for order_id, total in per_order.items():
                assert total <= paid[order_id] + 1e-6, f"{scenario.id}: {order_id} refunded {total} > paid {paid[order_id]}"

    def test_runs_that_restrain_themselves_move_no_money(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        restraint = [(s, g, e) for s, _r, g, e in train_runs_session if "restraint" in s.tags and g.ok]
        assert restraint, "the train slice is expected to contain restraint scenarios"
        for scenario, _grade, extras in restraint:
            state = extras["world"].state()
            assert sum(float(r["amount"]) for r in state["refunds"] if r["status"] == "done") == 0.0, scenario.id
            assert state["coupons"] == [], scenario.id

    def test_a_high_risk_customer_never_gets_an_automatic_payout(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        for scenario, _row, _grade, extras in train_runs_session:
            state = extras["world"].state()
            customers = {c["id"]: c for c in state["customers"]}
            orders = {o["id"]: o for o in state["orders"]}
            for refund in state["refunds"]:
                customer = customers.get(orders[refund["order_id"]]["customer_id"], {})
                if int(customer.get("risk_score", 0)) >= HIGH_RISK_SCORE:
                    assert refund["status"] != "done", f"{scenario.id}: auto-paid a risk_score={customer['risk_score']} customer"


class TestTicketsClose:
    def test_a_passing_grade_means_no_ticket_was_left_open(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        for scenario, _row, grade, extras in train_runs_session:
            if not grade.ok:
                assert scenario.id in KNOWN_FAILING_LONG_HORIZON, f"{scenario.id} fails and is not a known long-horizon case"
                continue
            # Scoped to the tickets this scenario is about: S15/S16 deliberately seed a
            # queue of unrelated open tickets, and a run that leaves those alone is right.
            wanted = set(scenario.expect.get("tickets") or [scenario.fixture["tickets"][0]["id"]])
            open_ids = [t["id"] for t in extras["world"].state()["tickets"] if t["status"] == "open" and t["id"] in wanted]
            assert open_ids == [], f"{scenario.id}: passed the grade with open tickets {open_ids}"

    def test_the_named_ticket_is_resolved_or_escalated_to_the_expected_team(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        checked = 0
        for scenario, _row, grade, extras in train_runs_session:
            if not grade.ok or scenario.expect.get("outcome") == "batch":
                continue
            ticket = extras["world"].state()["tickets"][0]
            assert ticket["status"] == scenario.expect.get("ticket_status", "resolved"), scenario.id
            if scenario.expect.get("outcome") == "escalate":
                assert ticket["team"] == scenario.expect["team"], scenario.id
                checked += 1
        assert checked >= 3


class TestCostIsReal:
    def test_any_run_that_called_a_model_paid_for_it(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        billed = [(s, r) for s, r, _g, _e in train_runs_session if r.calls > 0]
        assert len(billed) == len(train_runs_session), "every arm run should be metered"
        for scenario, row in billed:
            assert row.cost > 0, f"{scenario.id}: {row.calls} calls for free"
            assert row.prompt_tokens_total > 0 and row.completion_tokens > 0, scenario.id
            assert row.steps == row.calls, scenario.id

    def test_every_emitted_call_reports_back_exactly_once(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        # The message-list equivalent is asserted on the engine itself in
        # test_context_engine.py; at trace level the same property reads as "one
        # tool_result per tool_call, and every name is a real tool".
        from ballast.tools.desk import build_desk_tools

        for scenario, _row, _grade, extras in train_runs_session:
            events = extras["result"].events
            calls = [e for e in events if e["type"] == "tool_call"]
            results = [e for e in events if e["type"] == "tool_result"]
            assert len(calls) == len(results), f"{scenario.id}: {len(calls)} calls vs {len(results)} results"
            menu = {tool.name for tool in build_desk_tools(extras["agent"].config.toolkit and __import__("ballast.kernel.events", fromlist=["RunContext"]).RunContext())}
            assert menu
            assert {str(e["payload"].get("name")) for e in calls} <= set(extras["agent"].config.toolkit.names), scenario.id
            successful_calls(events)

    def test_costs_stay_inside_the_declared_ceiling(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        ceiling = resolve_arm("ballast").budget
        for scenario, row, _grade, _extras in train_runs_session:
            assert row.cost <= ceiling["max_cost"], f"{scenario.id} breached the cost ceiling: {row.cost}"
            # `begin_call` charges the step before the request, so a run can only ever
            # overshoot the step ceiling by the two steps the final degrade stage buys.
            assert row.steps <= ceiling["max_steps"] + 2, f"{scenario.id} breached the step ceiling: {row.steps}"
            assert row.prompt_tokens_peak <= ceiling["max_prompt_tokens"], f"{scenario.id}: peak {row.prompt_tokens_peak}"
            assert row.wall_s < 5.0, f"{scenario.id} took {row.wall_s}s"


class TestGradeIsNotVacuous:
    def test_every_scenario_is_graded_on_more_than_one_check(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        for scenario, _row, grade, _extras in train_runs_session:
            assert len(grade.checks) >= 2, f"{scenario.id} graded on {grade.checks}"
            assert all(c.detail for c in grade.checks), scenario.id
            assert isinstance(grade.ok, bool)

    def test_the_invariant_check_is_present_in_every_grade(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        for scenario, _row, grade, _extras in train_runs_session:
            assert "invariants_clean" in {c.name for c in grade.checks}, scenario.id

    def test_the_whole_slice_actually_passes_today(
        self, train_runs_session: list[tuple[Scenario, Any, Grade, dict[str, Any]]]
    ) -> None:
        """A benchmark nobody passes is not a benchmark; this pins the current score so
        a regression in any scenario shows up here with a name attached."""
        passed = {s.id for s, _r, g, _e in train_runs_session if g.ok}
        expected = {s.id for s, *_ in train_runs_session} - KNOWN_FAILING_LONG_HORIZON
        assert expected <= passed, f"newly failing: {sorted(expected - passed)}"
