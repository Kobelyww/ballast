"""The second domain exists to falsify "this is an application, not a runtime".

Nothing in `kernel/` was changed to admit incidents: the tools, the policy engine, the
world, the grader and the offline policy driver are all new files, and the arms, the
runner and the statistics run them unchanged.
"""

from __future__ import annotations

import pytest

from ballast.bench.fixtures_bridge import load_suite
from ballast.bench.incident_graders import grade
from ballast.bench.runner import resolve_arm, run_scenario
from ballast.env.incident_fixtures import policy_truth, scenarios, train_slice
from ballast.env.incident_policy import evaluate_rollback, runbook_required_steps
from ballast.env.incident_verify import audit
from ballast.env.ops_world import OpsWorld
from ballast.env.knowledge import runbook_kb
from ballast.kernel.toolkit import Toolkit
from ballast.tools.ops import build_ops_tools


def test_the_second_domain_ships_train_and_holdout_slices() -> None:
    assert len(scenarios()) == 9
    assert len(train_slice()) == 7
    assert all(s.domain == "ops" for s in scenarios())


def test_expectations_agree_with_the_incident_policy_engine() -> None:
    # Same discipline as the after-sales suite: an expectation is authored by hand and
    # checked against the engine, so a rule change has to be made in both places.
    for scenario in scenarios():
        truth = policy_truth(scenario)
        if "page" in scenario.expect:
            assert scenario.expect["page"] == truth["page"], scenario.id
        if "rolled_back" in scenario.expect:
            assert scenario.expect["rolled_back"] == truth["rollback_allowed"], scenario.id


class TestRollbackPolicy:
    def _world(self, minutes_ago: int, *, blast: int = 1, severity: str = "sev2") -> OpsWorld:
        from datetime import datetime, timedelta

        now = "2026-09-18T03:15:00"
        finished = (datetime.fromisoformat(now) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
        world = OpsWorld(":memory:")
        world.apply({
            "now": now,
            "services": [{"id": "S1", "name": "svc", "tier": "standard", "owner": "t", "blast_radius": blast, "sli": 99}],
            "incidents": [{"id": "I1", "service_id": "S1", "severity": severity, "title": "x", "opened_at": now, "status": "open", "tags": "[]", "mitigation": "[]", "resolution": "", "review": "", "paged_team": ""}],
            "deployments": [{"id": "D1", "service_id": "S1", "version": "1.0", "finished_at": finished, "author": "ci", "canary": 0}],
        })
        return world

    @pytest.mark.parametrize(
        "minutes,severity,blast,allowed,reason",
        [(20, "sev2", 1, True, "recent_deploy_suspect"), (200, "sev2", 1, False, "deploy_too_old"), (10, "sev1", 1, False, "rollback_gated"), (10, "sev2", 9, False, "rollback_gated")],
    )
    def test_safety_gate(self, minutes, severity, blast, allowed, reason) -> None:
        world = self._world(minutes, blast=blast, severity=severity)
        state = world.state()
        decision = evaluate_rollback(
            service=state["services"][0],
            deployments=state["deployments"],
            incident=state["incidents"][0],
            now=state["now"],
        )
        assert decision.allowed is allowed
        assert decision.reason_code == reason

    def test_a_change_freeze_needs_a_human(self) -> None:
        world = self._world(5, severity="sev1")
        state = world.state()
        decision = evaluate_rollback(service=state["services"][0], deployments=state["deployments"], incident=state["incidents"][0], now=state["now"])
        assert decision.requires_human and "change_freeze" in decision.blockers


class TestRunbookObligations:
    def test_sev1_owes_an_acknowledgement_and_a_review(self) -> None:
        owed = runbook_required_steps(incident={"severity": "sev1", "tags": []}, mitigation_taken=[])
        assert len(owed) == 2

    def test_customer_impact_owes_a_status_note(self) -> None:
        owed = runbook_required_steps(incident={"severity": "sev3", "tags": ["customer_impact"]}, mitigation_taken=["acknowledge", "review"])
        assert any("status" in line for line in owed)


class TestToolsEnforcePolicy:
    def _toolkit(self, scenario_id: str = "O02_sev2_standard_recent_deploy") -> tuple[Toolkit, OpsWorld]:
        from ballast.kernel.events import RunContext

        scenario = next(s for s in scenarios() if s.id == scenario_id)
        world = scenario.build_world()
        ctx = RunContext(world=world, sop=runbook_kb(), hitl_mode="auto_approve", task_id=scenario.id)
        return Toolkit(build_ops_tools(ctx)), world

    def test_rolling_back_without_an_assessment_is_refused(self) -> None:
        toolkit, _world = self._toolkit()
        result = toolkit.execute("rollback_deploy", {"service_id": "SVC-SEARCH", "deployment_id": "D1", "reason": "guess"})
        assert not result.ok and result.error["error"] == "missing_computation"

    def test_paging_without_an_assessment_is_refused(self) -> None:
        toolkit, _world = self._toolkit()
        result = toolkit.execute("page_oncall", {"incident_id": "INC-02", "team": "sre", "reason": "vibes"})
        assert not result.ok and result.error["error"] == "missing_computation"

    def test_a_page_must_go_to_the_team_policy_named(self) -> None:
        toolkit, world = self._toolkit()
        toolkit.execute("evaluate_escalation_required", {"incident_id": "INC-02"})
        result = toolkit.execute("page_oncall", {"incident_id": "INC-02", "team": "payments", "reason": "x"})
        assert not result.ok and result.error["error"] == "team_mismatch"
        assert world.state()["pages"] == []


class TestEndToEnd:
    @pytest.mark.parametrize("scenario", [s.id for s in scenarios()])
    def test_the_controlled_arm_handles_every_incident_task(self, scenario) -> None:
        target = next(s for s in scenarios() if s.id == scenario)
        row, _grade, _extras = run_scenario(target, resolve_arm("ballast"))
        assert row.ok, row.failed_checks

    def test_an_unassessed_policy_is_stopped_by_the_runtime_not_by_grading(self) -> None:
        blocked = 0
        for scenario in train_slice():
            row, _grade, _extras = run_scenario(scenario, resolve_arm("ops_unassessed"))
            blocked += row.guardrail_blocks
        assert blocked >= 7, "every scenario should have had an unverified page refused"

    def test_a_reckless_policy_is_stopped_at_a_change_freeze(self) -> None:
        gated = [s for s in train_slice() if s.fixture["incidents"][0]["severity"] == "sev1" or s.fixture["services"][0]["blast_radius"] > 3]
        assert gated
        for scenario in gated:
            row, _grade, extras = run_scenario(scenario, resolve_arm("ops_reckless"))
            rolled_back = [a for a in extras["world"].state()["actions"] if a["tool"] == "rollback_deploy"]
            assert rolled_back == [], f"{scenario.id}: change freeze did not hold"

    def test_invariants_are_clean_after_a_passing_run(self) -> None:
        for scenario in train_slice():
            row, _grade, extras = run_scenario(scenario, resolve_arm("ballast"))
            assert not [f for f in audit(extras["world"]) if f.severity == "violation"], (scenario.id, [f.code for f in audit(extras["world"])])
            assert row.ok


class TestRunnerIsDomainAgnostic:
    def test_one_runner_handles_both_domains(self) -> None:
        suite = load_suite("all")
        domains = {getattr(s, "domain", "desk") for s in suite}
        assert domains == {"desk", "ops"}
        assert len(suite) == 43  # 34 after-sales tasks + 9 incidents

    def test_the_same_arm_spec_drives_both(self) -> None:
        desk = next(s for s in load_suite("train") if s.id == "S01_inwindow_refund")
        ops = next(s for s in load_suite("ops") if s.id == "O02_sev2_standard_recent_deploy")
        desk_row, _g1, _e1 = run_scenario(desk, resolve_arm("ballast"))
        ops_row, _g2, _e2 = run_scenario(ops, resolve_arm("ballast"))
        assert desk_row.ok and ops_row.ok
        assert desk_row.cost > 0 and ops_row.cost > 0
