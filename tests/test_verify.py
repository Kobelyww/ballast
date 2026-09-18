"""Deterministic invariants over world state: the critic and the grader share them."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ballast.env.fixtures import by_id
from ballast.env.world import WorldError
from ballast.kernel.verify import Finding, audit, refund_total, ticket_status, violations
from conftest import GOOD_SUMMARY, Harness, call_step, s03_plan, say

SOP_IDS = {"refund_policy::七天无理由退货", "coupon_compensation::发放权限"}


def world_for(scenario_id: str):
    scenario = by_id(scenario_id)
    return scenario.build_world(), scenario


class TestMoneyInvariants:
    def test_a_clean_world_has_no_findings(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        assert audit(world, sop_ids=SOP_IDS) == []

    def test_high_risk_auto_refund_is_a_violation(self) -> None:
        world, _ = world_for("S06_high_risk")
        world.issue_refund(order_id="SO20261047", amount=1999.0, reason="missing_item")
        found = audit(world)
        codes = [(f.code, f.severity) for f in found]
        assert ("high_risk_auto_refund", "violation") in codes
        assert any("risk_score=92" in f.detail for f in found)
        assert any("escalate_ticket" in f.fix for f in found)

    def test_a_pending_high_risk_refund_is_not_yet_a_violation(self) -> None:
        world, _ = world_for("S06_high_risk")
        world.issue_refund(order_id="SO20261047", amount=1999.0, reason="missing_item", status="approved")
        assert [f.code for f in audit(world)] == ["unverified_payment"]

    def test_over_refund_is_caught_from_the_audit_table(self) -> None:
        world, _ = world_for("S04_missing_item")
        # Two partial refunds that together exceed what was paid: the world refuses the
        # second one, so the invariant is asserted against a hand-forced write.
        world.issue_refund(order_id="SO20261045", amount=237.0, reason="missing_item")
        world._insert("refunds", {"id": "RF9999", "order_id": "SO20261045", "amount": 1.0, "reason": "x", "status": "done", "created_at": world.now, "operator": "test", "note": ""})
        world._conn.commit()
        found = [f for f in audit(world) if f.code == "over_refund"]
        assert found and all("238.0 > paid 237.0" in f.detail for f in found)
        # one finding per refund row of the offending order
        assert len(found) == 2

    def test_the_world_itself_refuses_to_over_refund(self) -> None:
        world, _ = world_for("S04_missing_item")
        world.issue_refund(order_id="SO20261045", amount=237.0, reason="missing_item")
        with pytest.raises(WorldError, match="over_refund"):
            world.issue_refund(order_id="SO20261045", amount=0.01, reason="missing_item")
        assert refund_total(world, "SO20261045") == 237.0

    def test_refund_total_ignores_reversed_rows(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.issue_refund(order_id="SO20261042", amount=129.0, reason="no_reason")
        world._conn.execute("UPDATE refunds SET status='reversed' WHERE id='RF0001'")
        world._conn.commit()
        assert refund_total(world, "SO20261042") == 0.0
        assert world.total_refunded("SO20261042") == 0.0

    def test_paying_without_computing_is_a_violation(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.issue_refund(order_id="SO20261042", amount=129.0, reason="no_reason")
        found = [f for f in audit(world) if f.code == "unverified_payment"]
        assert len(found) == 1 and found[0].severity == "violation"
        assert "compute_refund" in found[0].fix

    def test_a_recorded_computation_clears_it(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.audit_read("compute_refund", {"order_id": "SO20261042", "claim_type": "no_reason"}, {"allowed": True, "amount": 129.0})
        world.issue_refund(order_id="SO20261042", amount=129.0, reason="no_reason")
        assert "unverified_payment" not in {f.code for f in audit(world)}

    def test_coupons_to_high_risk_customers_are_violations(self) -> None:
        world, _ = world_for("S06_high_risk")
        world.send_coupon(customer_id="C105", value=10.0, reason="安抚")
        assert [f.code for f in audit(world) if f.code == "high_risk_coupon"]
        assert audit(world, sop_ids=SOP_IDS)[0].severity == "violation"


class TestTicketInvariants:
    def test_an_open_ticket_is_left_open(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        found = audit(world, ticket_id="T1042")
        assert [f.code for f in found] == ["ticket_left_open"]
        assert "close_ticket or escalate_ticket" in found[0].fix

    def test_a_missing_ticket_is_reported(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        assert [f.code for f in audit(world, ticket_id="T9999")] == ["ticket_not_found"]

    def test_ticket_status_reads_the_world(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        assert ticket_status(world, "T1042") == "open"
        world.update_ticket(ticket_id="T1042", status="resolved", resolution="refunded", summary="x")
        assert ticket_status(world, "T1042") == "resolved"
        assert ticket_status(world, "T0000") == "missing"

    def test_closing_without_a_citation_is_a_violation(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.update_ticket(ticket_id="T1042", status="resolved", resolution="refunded", summary="客户无理由退款 129.00 元已到账，问题已解决。")
        found = audit(world, sop_ids=SOP_IDS, ticket_id="T1042")
        assert [f.code for f in found] == ["missing_policy_citation"]

    def test_citing_a_section_that_is_not_in_the_corpus_still_fails(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.update_ticket(ticket_id="T1042", status="resolved", resolution="refunded", summary="依据 refund_policy::不存在的章节 退款 129.00 元，已完成。")
        assert [f.code for f in audit(world, sop_ids=SOP_IDS, ticket_id="T1042")] == ["missing_policy_citation"]

    def test_a_real_citation_clears_it(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.update_ticket(
            ticket_id="T1042",
            status="resolved",
            resolution="refunded",
            summary="依据 refund_policy::七天无理由退货 无理由退款 ¥129.00，已执行放款并结单。",
        )
        assert audit(world, sop_ids=SOP_IDS, ticket_id="T1042") == []

    def test_money_resolution_without_an_amount_is_a_weakness(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.update_ticket(ticket_id="T1042", status="resolved", resolution="refunded", summary="依据 refund_policy::七天无理由退货 已完成退款处理并结单。")
        found = audit(world, sop_ids=SOP_IDS, ticket_id="T1042")
        assert [f.code for f in found] == ["amount_not_stated"]
        assert found[0].severity == "weakness"
        assert violations(found) == []

    def test_a_thin_escalation_is_a_weakness_only_for_resolved_tickets(self) -> None:
        world, _ = world_for("S09_address_locked")
        # KNOWN BUG (src/ballast/kernel/verify.py:83-85): the per-ticket quality loop
        # `continue`s on every ticket whose status is not "resolved", and `escalate_ticket`
        # writes status="escalated" - so `thin_escalation` (and the citation check) never
        # run against a real escalation. Asserted as-is: the check works only for the
        # resolved-with-escalated-resolution combination.
        world.update_ticket(ticket_id="T1050", status="escalated", resolution="escalated", summary="转物流处理了。")
        assert audit(world, ticket_id="T1050") == []
        world.update_ticket(ticket_id="T1050", status="resolved", resolution="escalated", summary="转物流处理了。")
        assert [f.code for f in audit(world, ticket_id="T1050")] == ["thin_escalation"]

    def test_a_substantive_escalation_passes(self) -> None:
        world, _ = world_for("S09_address_locked")
        note = "已核实: 订单 SO20261050 于 2026-05-19 发出，当前 in_transit；政策依据 escalation::必须升级人工的情形；候选方案: 拦截配送或原址签收；建议: 由物流同事发起拦截。"
        world.update_ticket(ticket_id="T1050", status="escalated", resolution="escalated", summary=note, team="logistics")
        assert audit(world, sop_ids=SOP_IDS, ticket_id="T1050") == []

    def test_other_tickets_are_out_of_scope_when_one_is_named(self) -> None:
        world, _ = world_for("S18_batch_queue")
        for tid in ("T77000", "T77001"):
            world.update_ticket(ticket_id=tid, status="resolved", resolution="rejected_by_policy", summary="依据 refund_policy::七天无理由退货 本次不退款，金额 ¥0.00。")
        assert audit(world, sop_ids=SOP_IDS, ticket_id="T77000") == []
        assert {f.code for f in audit(world, sop_ids=SOP_IDS)} == set()


class TestFindingShape:
    def test_findings_serialise_for_both_audiences(self) -> None:
        finding = Finding("over_refund", "violation", "detail text", "fix text")
        assert finding.as_dict() == {"code": "over_refund", "severity": "violation", "detail": "detail text", "fix": "fix text"}
        assert finding.as_instruction() == "over_refund: detail text -> fix text"

    def test_violations_filters_weaknesses(self) -> None:
        found = [Finding("a", "violation", "", ""), Finding("b", "weakness", "", "")]
        assert [f.code for f in violations(found)] == ["a"]

    def test_audit_without_sop_ids_skips_the_citation_check(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.update_ticket(ticket_id="T1042", status="resolved", resolution="rejected_by_policy", summary="政策不支持，已答复客户。")
        assert audit(world, ticket_id="T1042") == []
        assert [f.code for f in audit(world, sop_ids=SOP_IDS, ticket_id="T1042")] == ["missing_policy_citation"]


class TestCriticUsesTheSameCode:
    def test_a_final_answer_that_leaves_the_ticket_open_bounces(self) -> None:
        h = Harness("S01_inwindow_refund", critic_rounds=1)
        h.load([call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"), say("我认为可以退款了"), say("还是没结单")])
        # The critic scopes its audit to a ticket, and it can only do that when the task
        # is named after one: `_ticket_of` reads a task_id like "T1042".
        h.ctx.task_id = "T1042"
        result = h.run()
        critics = [e for e in result.events if e["type"] == "critic"]
        assert len(critics) == 1
        assert [f["code"] for f in critics[0]["payload"]["findings"]] == ["ticket_left_open"]
        assert [f["code"] for f in result.findings] == ["ticket_left_open"]

    def test_the_critique_reaches_the_model_as_a_user_turn(self) -> None:
        h = Harness("S01_inwindow_refund", critic_rounds=1)
        h.load([call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"), say("我认为可以退款了"), say("还是不行")])
        h.ctx.task_id = "T1042"
        h.run()
        # requests[0] opens the run, requests[1] is the turn that stops early, and the
        # critique is what the *next* request sees.
        assert len(h.provider.requests) >= 3
        criticised = h.provider.requests[2].messages
        assert any(m["role"] == "user" and "automatic audit" in str(m["content"]) for m in criticised)
        assert any("ticket_left_open" in str(m["content"]) for m in criticised)
        assert not any("automatic audit" in str(m["content"]) for m in h.provider.requests[1].messages)

    def test_the_critic_is_bounded(self) -> None:
        h = Harness("S01_inwindow_refund", critic_rounds=1)
        h.load([say("我不结单")])
        h.ctx.task_id = "T1042"
        result = h.run()
        assert len([e for e in result.events if e["type"] == "critic"]) == 1
        assert result.status == "ok"

    def test_zero_critic_rounds_means_no_bounce(self) -> None:
        h = Harness("S01_inwindow_refund", critic_rounds=0)
        h.load([say("完成")])
        h.ctx.task_id = "T1042"
        result = h.run()
        assert [e for e in result.events if e["type"] == "critic"] == []

    def test_a_clean_close_needs_no_correction(self) -> None:
        h = Harness("S01_inwindow_refund")
        result = h.run(
            [
                call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"),
                call_step(2, "issue_refund", order_id="SO20261042", amount=129.0, reason="no_reason"),
                call_step(3, "close_ticket", ticket_id="T1042", resolution="refunded", summary="依据 refund_policy::七天无理由退货 无理由退款 ¥129.00，已执行放款并结单。"),
                say("已完成"),
            ]
        )
        assert result.status == "ok" and result.findings == []
        assert [e for e in result.events if e["type"] == "critic"] == []
        assert h.world.state()["refunds"][0]["amount"] == 129.0

    def test_the_grader_reads_state_not_prose(self) -> None:
        from ballast.bench.graders import grade

        h = Harness("S01_inwindow_refund")
        h.run([say("我已经处理好了（并没有）")])
        g = grade(h.scenario, h.world, sop_ids=set(h.kb.section_ids()), events=[])
        assert g.ok is False
        assert {"ticket_status", "invariants_clean"} <= {c.name for c in g.checks}
        assert any("ticket_status" in detail for detail in g.failed)

    def test_a_full_pass_grades_clean(self) -> None:
        from ballast.bench.graders import grade

        h = Harness("S03_quality_with_shipping")
        result = h.run(s03_plan())
        g = grade(h.scenario, h.world, sop_ids=set(h.kb.section_ids()), events=result.events)
        assert g.ok, g.failed
        assert {c.name for c in g.checks} >= {"ticket_status", "refund_amount", "approval_gated", "invariants_clean"}
        assert all(c.ok for c in g.checks)
        assert g.as_dict()["scenario_id"] == "S03_quality_with_shipping"


class TestWorldPlumbing:
    def test_mutation_counter_and_audit_rows(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        assert world.mutation_count == 0
        world.issue_refund(order_id="SO20261042", amount=1.0, reason="x")
        assert world.mutation_count == 1
        row = world.state()["actions"][-1]
        assert row["tool"] == "issue_refund" and json.loads(row["args"])["amount"] == 1.0 and row["ok"] == 1

    def test_a_missing_record_raises_a_typed_error(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        with pytest.raises(WorldError) as excinfo:
            world.get_order("SO00000000")
        assert excinfo.value.code == "not_found" and excinfo.value.as_dict()["error"] == "not_found"
        with pytest.raises(WorldError):
            world.get_ticket("T9999")
        with pytest.raises(WorldError):
            world.get_customer("C9999")

    def test_flaky_tools_fail_then_recover(self) -> None:
        world, _ = world_for("S14_flaky_upstream")
        world._flaky = {"get_order": 2}
        for _ in range(2):
            with pytest.raises(WorldError, match="upstream_timeout") as excinfo:
                world.get_order("SO20261054")
            assert excinfo.value.retryable is True
        assert world.get_order("SO20261054")["id"] == "SO20261054"

    def test_reads_that_do_not_mutate_are_not_audited(self) -> None:
        world, _ = world_for("S01_inwindow_refund")
        world.get_order("SO20261042")
        world.list_tickets("open")
        world.refund_history("SO20261042")
        assert world.state()["actions"] == []

    def test_ticket_update_keeps_the_team_when_not_overridden(self) -> None:
        world, _ = world_for("S09_address_locked")
        world.update_ticket(ticket_id="T1050", status="escalated", resolution="escalated", summary="n" * 40, team="logistics")
        world.update_ticket(ticket_id="T1050", status="resolved", resolution="refunded", summary=GOOD_SUMMARY)
        assert world.get_ticket("T1050")["team"] == "logistics"

    def test_list_orders_and_phone_lookup(self) -> None:
        world, _ = world_for("S16_queue_dig")
        assert [o["id"] for o in world.list_orders_by_phone("138 0000 2222")] == ["SO20261060"]
        assert world.list_orders("C120")[0]["id"] == "SO20261060"
        assert len(world.list_tickets("open", limit=10)) == 10
        assert len(world.list_tickets(None, limit=500)) == 61

    def test_coupon_and_flag_histories(self) -> None:
        world, _ = world_for("S12_coupon_within_cap")
        world.send_coupon(customer_id="C111", value=30.0, reason="延误")
        assert world.coupon_history("C111")[0]["value"] == 30.0
        flagged = world.flag_risk(customer_id="C111", reason="异常索赔")
        assert flagged["flag_id"] == "FL0002"
        assert world.state()["flags"][0]["reason"] == "异常索赔"
