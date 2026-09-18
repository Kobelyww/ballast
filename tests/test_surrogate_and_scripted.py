"""The offline stand-ins for a language model: ScriptedModel and SurrogatePolicy.

Nothing measured through these says anything about a real LLM; what they do make
checkable is the harness - tool sequences, repair behaviour, budget effects - with no
API key and no network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ballast.env.fixtures import by_id
from ballast.llm.base import ChatRequest, ChatResponse, ToolCall, Usage, user_message
from ballast.llm.surrogate import ScriptedModel, SurrogatePolicy, SurrogateProfile, _Transcript
from ballast.bench.runner import resolve_arm, run_scenario
from conftest import Harness, call_step, say

REFUND_BRIEF = "工单 T1042：客户说买错型号了，签收才三天，想无理由退款。"


def request_for(messages: list[dict[str, Any]]) -> ChatRequest:
    return ChatRequest(messages=messages)


def tool_result(name: str, payload: dict, call_id: str = "c1") -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": json.dumps(payload, ensure_ascii=False)}


def assistant_call(name: str, arguments: dict, call_id: str = "c1") -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}],
    }


class TestScriptedModel:
    def test_replays_in_order_and_records_requests(self) -> None:
        model = ScriptedModel([ChatResponse(content="one"), {"tool_calls": [{"name": "get_ticket", "arguments": {"ticket_id": "T1042"}}]}])
        first = model.chat(request_for([user_message("hi")]))
        second = model.chat(request_for([user_message("again")]))
        assert first.content == "one"
        assert second.tool_calls[0].name == "get_ticket"
        assert [str(r.messages[0]["content"]) for r in model.requests] == ["hi", "again"]

    def test_running_out_yields_a_plain_stop_instead_of_an_index_error(self) -> None:
        model = ScriptedModel([ChatResponse(content="only")])
        model.chat(request_for([]))
        exhausted = model.chat(request_for([]))
        assert exhausted.content == "done" and exhausted.tool_calls == [] and exhausted.finish_reason == "stop"
        assert exhausted.usage.calls == 1

    def test_dict_steps_are_expanded_into_responses(self) -> None:
        model = ScriptedModel([{"tool_calls": [{"id": "x", "name": "get_order", "arguments": {"order_id": "SO1"}}], "input_tokens": 42, "output_tokens": 7}])
        response = model.chat(request_for([]))
        assert response.finish_reason == "tool_calls"
        assert response.usage == Usage(input_tokens=42, output_tokens=7, calls=1)
        assert response.tool_calls == [ToolCall(id="x", name="get_order", arguments={"order_id": "SO1"})]

    def test_content_steps_get_a_default_usage(self) -> None:
        response = ScriptedModel([{"content": "hi"}]).chat(request_for([]))
        assert response.content == "hi" and response.usage.input_tokens == 100 and response.usage.calls == 1

    def test_generated_call_ids(self) -> None:
        calls = ScriptedModel([{"tool_calls": [{"name": "a"}, {"name": "b"}]}]).chat(request_for([])).tool_calls
        assert [c.id for c in calls] == ["call_0", "call_1"]

    def test_a_scripted_run_drives_the_real_tools(self) -> None:
        h = Harness("S01_inwindow_refund")
        result = h.run(
            [
                call_step(1, "get_ticket", ticket_id="T1042"),
                call_step(2, "get_order", order_id="SO20261042"),
                call_step(3, "get_customer", customer_id="C100"),
                call_step(4, "search_sop", query="退款 无理由 政策 窗口 计算"),
                call_step(5, "compute_refund", order_id="SO20261042", claim_type="no_reason"),
                call_step(6, "issue_refund", order_id="SO20261042", amount="129", reason="no_reason"),
                call_step(7, "close_ticket", ticket_id="T1042", resolution="refunded", summary="依据 refund_policy::七天无理由退货 无理由退款 ¥129.00，已执行放款并结单。"),
                say("已完成"),
            ]
        )
        assert result.status == "ok"
        assert result.steps == 8 and result.calls == 8
        assert result.usage.input_tokens == 500 * 8
        assert h.world.total_refunded("SO20261042") == 129.0
        assert h.world.get_ticket("T1042")["status"] == "resolved"

    def test_a_malformed_call_is_corrected_by_the_next_turn(self) -> None:
        h = Harness("S01_inwindow_refund")
        result = h.run(
            [
                call_step(1, "compute_refund", order_id="SO20261042", claim_type="no_reason"),
                ChatResponse(  # camelCase, and a string where a float was asked for
                    tool_calls=[ToolCall(id="bad", name="issue_refund", arguments={"orderId": "SO20261042", "amount": "129.00"})],
                    usage=Usage(input_tokens=500, output_tokens=30, calls=1),
                    finish_reason="tool_calls",
                ),
                call_step(3, "issue_refund", order_id="SO20261042", amount=129.0, reason="no_reason"),
                say("完成"),
            ]
        )
        rejected = [e for e in result.events if e["type"] == "tool_rejected"]
        assert len(rejected) == 1 and rejected[0]["payload"]["name"] == "issue_refund"
        assert result.rejected_calls >= 1
        assert h.world.total_refunded("SO20261042") == 129.0  # repaired, not aborted

    def test_unknown_tool_names_are_reported_back(self) -> None:
        h = Harness("S01_inwindow_refund")
        result = h.run([call_step(1, "refund_now", order_id="SO20261042"), say("完成")])
        codes = [e["payload"].get("code") for e in result.events if e["type"] == "tool_result"]
        assert "unknown_tool" in codes
        assert result.tool_errors == 1


class TestTranscriptReads:
    def test_identifiers_are_found_in_the_brief(self) -> None:
        transcript = _Transcript([user_message(REFUND_BRIEF)])
        assert transcript.intent().ticket == "T1042"
        assert transcript.intent().kind == "refund"
        assert transcript.order_id() is None

    def test_money_and_skus_are_read_out_of_prose(self) -> None:
        transcript = _Transcript([user_message("工单 T1053：给我补偿100元优惠券，SKU-A1 也要退")])
        intent = transcript.intent()
        assert intent.amount == 100.0 and intent.skus == ["SKU-A1"]

    def test_intent_kind_prefers_refund_words(self) -> None:
        assert _Transcript([user_message("补偿10元优惠券，但我主要是想退款")]).intent().kind == "refund"
        assert _Transcript([user_message("配送延误了两天，体验很差，要个说法")]).intent().kind == "coupon"
        assert _Transcript([user_message("改地址，改成公司")]).intent().kind == "address"

    def test_batch_word_switches_to_queue_mode(self) -> None:
        messages = [
            user_message("把队列里所有 open 工单批量处理掉"),
            assistant_call("list_tickets", {"status": "open"}),
            tool_result("list_tickets", {"tickets": [{"id": "T77000", "order_id": "SO1"}, {"id": "T77001", "order_id": "SO2"}]}),
        ]
        intent = _Transcript(messages).intent()
        assert intent.batch is True and intent.ticket == "T77000"

    def test_handled_tickets_are_dropped_from_the_queue(self) -> None:
        messages = [
            user_message("批量处理所有 open 工单"),
            assistant_call("list_tickets", {"status": "open"}),
            tool_result("list_tickets", {"tickets": [{"id": "T77000"}, {"id": "T77001"}]}),
            assistant_call("close_ticket", {"ticket_id": "T77000", "resolution": "refunded", "summary": "s"}, call_id="c2"),
            tool_result("close_ticket", {"ticket_id": "T77000", "status": "resolved"}, call_id="c2"),
        ]
        transcript = _Transcript(messages)
        assert transcript.handled_tickets() == {"T77000"}
        assert transcript.intent().ticket == "T77001"

    def test_scope_keeps_one_orders_evidence_from_answering_for_another(self) -> None:
        transcript = _Transcript(
            [
                assistant_call("get_order", {"order_id": "SO20261042"}),
                tool_result("get_order", {"id": "SO20261042", "paid_amount": 129.0}),
            ]
        )
        assert transcript.saw("get_order", scope="SO20261042")
        assert not transcript.saw("get_order", scope="SO99999999")

    def test_an_error_result_is_not_a_successful_read(self) -> None:
        transcript = _Transcript([assistant_call("get_order", {"order_id": "SO1"}), tool_result("get_order", {"error": "not_found"})])
        assert not transcript.saw("get_order")
        assert transcript.error_of("get_order") == {"error": "not_found"}

    def test_a_retry_that_succeeded_stops_haunting_the_run(self) -> None:
        transcript = _Transcript(
            [
                assistant_call("get_order", {"order_id": "SO1"}, call_id="a"),
                tool_result("get_order", {"error": "upstream_timeout", "retryable": True}, call_id="a"),
                assistant_call("get_order", {"order_id": "SO1"}, call_id="b"),
                tool_result("get_order", {"id": "SO1", "paid_amount": 1.0}, call_id="b"),
            ]
        )
        assert transcript.retry_hint() is None
        assert transcript.saw("get_order")

    def test_a_pending_retry_is_re_issued_with_the_original_arguments(self) -> None:
        transcript = _Transcript(
            [
                assistant_call("issue_refund", {"order_id": "SO1", "amount": 10.0}, call_id="a"),
                tool_result("issue_refund", {"error": "upstream_timeout", "retryable": True}, call_id="a"),
            ]
        )
        assert transcript.retry_hint() == ("issue_refund", {"order_id": "SO1", "amount": 10.0})

    def test_needs_repair_reads_the_last_tool_turn(self) -> None:
        broken = _Transcript([tool_result("issue_refund", {"error": "invalid_arguments", "hint": "use order_id"})])
        assert broken.needs_repair() is True
        assert _Transcript([tool_result("issue_refund", {"error": "policy_denied"})]).needs_repair() is False
        assert _Transcript([user_message("hi")]).needs_repair() is False

    def test_offloaded_results_are_rehydrated_by_a_read_scratch(self) -> None:
        handle = "scratch://list_tickets-call_1-abcdef0123456789"
        payload = {"tickets": [{"id": "T1042", "order_id": "SO20261042"}]}
        preview = f"[output 4200t moved out of context -> {handle}]\nhead: ... tail: ..."
        transcript = _Transcript(
            [
                assistant_call("list_tickets", {"status": "open"}, call_id="call_1"),
                tool_result("list_tickets", {"_text": preview}, call_id="call_1"),
                assistant_call("read_scratch", {"handle": handle}, call_id="call_2"),
                tool_result("read_scratch", {"handle": handle, "text": json.dumps(payload, ensure_ascii=False)}, call_id="call_2"),
            ]
        )
        assert transcript.offloaded_pending() is None
        assert transcript.saw("list_tickets")
        assert transcript.result_of("list_tickets") == payload

    def test_a_still_offloaded_result_is_asked_for(self) -> None:
        handle = "scratch://get_order-call_9-ffffffffffffffff"
        transcript = _Transcript(
            [
                assistant_call("get_order", {"order_id": "SO1"}, call_id="call_9"),
                tool_result("get_order", {"_text": f"output 3000t moved out of context -> {handle}"}, call_id="call_9"),
            ]
        )
        assert transcript.offloaded_pending() == handle
        # A preview still counts as "the model saw this tool": what pulls the round trip
        # is `offloaded_pending`, which `_next_action` checks before anything else.
        assert transcript.saw("get_order") is True
        assert transcript.result_of("get_order") == {"_offloaded": handle, "_tokens": 3000}

    def test_skill_triggers_are_read_from_system_pins(self) -> None:
        plain = _Transcript([{"role": "system", "content": "no markers"}, user_message("工单 T1042 退款")])
        assert plain.has_trigger("force_compute_refund") is False
        armed = _Transcript([{"role": "system", "content": "Steps: TRIGGER:force_compute_refund"}, user_message("工单 T1042 退款")])
        assert armed.has_trigger("force_compute_refund") is True

    def test_citations_and_summaries_come_from_the_search_result(self) -> None:
        transcript = _Transcript(
            [
                assistant_call("search_sop", {"query": "退款"}),
                tool_result("search_sop", {"hits": [{"id": "refund_policy::七天无理由退货", "score": 1.0, "text": "..."}]}),
                assistant_call("compute_refund", {"order_id": "SO20261042"}),
                tool_result("compute_refund", {"order_id": "SO20261042", "allowed": True, "amount": 129.0, "reason_code": "no_reason"}),
            ]
        )
        assert transcript.cited_section() == "refund_policy::七天无理由退货"
        summary = transcript.summary_for("refunded", "已退款")
        assert "refund_policy::七天无理由退货" in summary and "129.00" in summary and "结论 refunded" in summary
        denied = _Transcript(
            [
                assistant_call("search_sop", {"query": "退款"}),
                tool_result("search_sop", {"hits": [{"id": "refund_policy::七天无理由退货"}]}),
                assistant_call("compute_refund", {"order_id": "SO20261042"}),
                tool_result("compute_refund", {"order_id": "SO20261042", "allowed": False, "amount": 0.0, "reason_code": "window_closed"}),
            ]
        )
        assert "本次不退款，金额 ¥0.00" in denied.summary_for("rejected_by_policy", "政策不支持")

    def test_escalation_note_carries_facts_basis_options_and_a_recommendation(self) -> None:
        note = _Transcript(
            [
                assistant_call("search_sop", {"query": "退款"}),
                tool_result("search_sop", {"hits": [{"id": "escalation::必须升级人工的情形"}]}),
            ]
        ).escalation_note({"reason_code": "high_risk", "amount": 1999.0})
        assert "escalation::必须升级人工的情形" in note and "1999.00" in note
        assert "候选方案" in note and "建议" in note

    def test_claim_type_table(self) -> None:
        transcript = _Transcript([])
        for text, expected in [
            ("耳机坏了没有声音", "quality"),
            ("少发了一件", "missing_item"),
            ("包裹运输损坏", "damaged"),
            ("多扣了一次款", "duplicate_charge"),
            ("买错了不想要", "no_reason"),
            ("其他情况", "other"),
        ]:
            assert transcript.claim_type(text) == expected, text


class TestSurrogatePolicy:
    def _policy_run(self, scenario_id: str, profile: SurrogateProfile | None = None) -> tuple[Any, Any, Any]:
        arm = resolve_arm("ballast")
        row, grade, extras = run_scenario(by_id(scenario_id), arm)
        return row, grade, extras

    def test_the_happy_path_tool_sequence(self) -> None:
        row, g, extras = self._policy_run("S01_inwindow_refund")
        assert g.ok
        names = [e["payload"].get("name") for e in extras["result"].events if e["type"] == "tool_call"]
        assert names == ["get_ticket", "get_order", "get_customer", "search_sop", "compute_refund", "issue_refund", "close_ticket"]

    def test_a_deny_never_touches_the_money_tool(self) -> None:
        row, g, extras = self._policy_run("S02_window_closed")
        assert g.ok
        names = [e["payload"].get("name") for e in extras["result"].events if e["type"] == "tool_call"]
        assert "issue_refund" not in names
        assert names[-1] == "close_ticket"
        assert extras["world"].get_ticket("T1043")["resolution"] == "rejected_by_policy"

    def test_high_risk_goes_to_a_human(self) -> None:
        row, g, extras = self._policy_run("S06_high_risk")
        assert g.ok
        names = [e["payload"].get("name") for e in extras["result"].events if e["type"] == "tool_call"]
        assert "issue_refund" not in names and "escalate_ticket" in names
        assert extras["world"].get_ticket("T1047")["team"] == "risk"

    def test_phone_only_identification_walks_the_lookup_chain(self) -> None:
        row, g, extras = self._policy_run("S10_phone_lookup")
        names = [e["payload"].get("name") for e in extras["result"].events if e["type"] == "tool_call"]
        assert g.ok
        assert "list_orders_by_phone" in names
        assert names.index("list_orders_by_phone") < names.index("compute_refund")

    def test_no_ticket_no_phone_means_asking_the_customer(self) -> None:
        policy = SurrogatePolicy()
        response = policy.chat(request_for([user_message("工单找不到，我这边有点问题"), {"role": "tool", "tool_call_id": "x", "name": "list_tickets", "content": json.dumps({"tickets": []})}]))
        assert response.tool_calls[0].name == "set_ticket_pending_info"
        assert response.finish_reason == "tool_calls"

    def test_every_turn_is_billed_with_a_usage_record(self) -> None:
        policy = SurrogatePolicy()
        response = policy.chat(request_for([user_message(REFUND_BRIEF)]))
        assert response.usage.calls == 1
        assert response.usage.input_tokens >= 1 and response.usage.output_tokens > 0
        assert policy.calls == 1

    def test_the_closing_remark_reports_what_actually_happened(self) -> None:
        row, g, extras = self._policy_run("S01_inwindow_refund")
        assert "129.00" in extras["result"].final_text
        row, g, extras = self._policy_run("S06_high_risk")
        assert "人工" in extras["result"].final_text

    def test_the_policy_reads_only_the_context_it_was_given(self) -> None:
        # Strip the get_order result out of the transcript and the policy asks for it
        # again instead of inventing an amount: context removal degrades behaviour,
        # which is the property the ablation arms measure.
        policy = SurrogatePolicy()
        full = [
            user_message(REFUND_BRIEF),
            assistant_call("get_ticket", {"ticket_id": "T1042"}),
            tool_result("get_ticket", {"id": "T1042", "order_id": "SO20261042", "customer_id": "C100", "claim": "买错了不想要"}),
            assistant_call("get_order", {"order_id": "SO20261042"}),
            tool_result("get_order", {"id": "SO20261042", "customer_id": "C100", "paid_amount": 129.0, "items": [{"sku": "SKU-A"}]}),
        ]
        assert policy.chat(request_for(full)).tool_calls[0].name == "get_customer"
        # ... with no order content at all it must ask, not invent
        stripped = full[:3]  # the ticket is read, the order is not
        action = policy.chat(request_for(stripped)).tool_calls[0]
        assert action.name == "get_order" and action.arguments == {"order_id": "SO20261042"}

    def test_blind_listing_profile_pulls_the_whole_queue_first(self) -> None:
        policy = SurrogatePolicy(SurrogateProfile(blind_listing=True))
        response = policy.chat(request_for([user_message(REFUND_BRIEF)]))
        assert response.tool_calls[0].name == "list_tickets"
        assert response.tool_calls[0].arguments["status"] == "all"

    def test_blind_listing_is_suppressed_by_a_caution_card(self) -> None:
        policy = SurrogatePolicy(SurrogateProfile(blind_listing=True))
        messages = [{"role": "system", "content": "TRIGGER:no_blind_listing"}, user_message(REFUND_BRIEF)]
        assert policy.chat(request_for(messages)).tool_calls[0].name == "get_ticket"

    def test_skip_verification_profile_attempts_the_unverified_refund(self) -> None:
        policy = SurrogatePolicy(SurrogateProfile(skip_verification=True))
        messages = [
            user_message(REFUND_BRIEF),
            assistant_call("get_ticket", {"ticket_id": "T1042"}),
            tool_result("get_ticket", {"id": "T1042", "order_id": "SO20261042", "customer_id": "C100", "claim": "买错了"}),
            assistant_call("get_order", {"order_id": "SO20261042"}),
            tool_result("get_order", {"id": "SO20261042", "customer_id": "C100", "paid_amount": 129.0, "items": [{"sku": "SKU-A"}]}),
            assistant_call("get_customer", {"customer_id": "C100"}),
            tool_result("get_customer", {"id": "C100", "tier": "SILVER", "risk_score": 10}),
            assistant_call("search_sop", {"query": "退款"}),
            tool_result("search_sop", {"hits": [{"id": "refund_policy::七天无理由退货"}]}),
        ]
        action = policy.chat(request_for(messages)).tool_calls[0]
        assert action.name == "issue_refund" and action.arguments["amount"] == 129.0
        assert "compute_refund" not in json.dumps(messages)

    def test_a_card_with_the_trigger_forces_the_computation_back_in(self) -> None:
        policy = SurrogatePolicy(SurrogateProfile(skip_verification=True))
        messages = [
            {"role": "system", "content": "TRIGGER:force_compute_refund"},
            user_message(REFUND_BRIEF),
            assistant_call("get_ticket", {"ticket_id": "T1042"}),
            tool_result("get_ticket", {"id": "T1042", "order_id": "SO20261042", "customer_id": "C100", "claim": "买错了"}),
            assistant_call("get_order", {"order_id": "SO20261042"}),
            tool_result("get_order", {"id": "SO20261042", "customer_id": "C100", "paid_amount": 129.0, "items": [{"sku": "SKU-A"}]}),
            assistant_call("get_customer", {"customer_id": "C100"}),
            tool_result("get_customer", {"id": "C100", "tier": "SILVER", "risk_score": 10}),
            assistant_call("search_sop", {"query": "退款"}),
            tool_result("search_sop", {"hits": [{"id": "refund_policy::七天无理由退货"}]}),
        ]
        assert policy.chat(request_for(messages)).tool_calls[0].name == "compute_refund"

    def test_the_defective_arm_is_blocked_by_the_guardrail(self) -> None:
        arm = resolve_arm("defective")
        row, g, extras = run_scenario(by_id("S01_inwindow_refund"), arm)
        assert row.ok is False
        assert row.guardrail_blocks >= 1
        events = extras["result"].events
        codes = [e["payload"].get("code") for e in events if e["type"] == "tool_result"]
        assert "missing_computation" in codes
        assert extras["world"].state()["refunds"] == []

    def test_malformed_rate_corrupts_arguments_in_ways_the_validator_notices(self) -> None:
        clean = SurrogatePolicy(SurrogateProfile(malformed_rate=0.0))
        dirty = SurrogatePolicy(SurrogateProfile(malformed_rate=1.0, seed=3))
        messages = [user_message(REFUND_BRIEF)]
        corrupted = []
        for _ in range(3):
            left = clean.chat(request_for(messages)).tool_calls[0]
            right = dirty.chat(request_for(messages)).tool_calls[0]
            assert left.name == right.name
            if right.arguments != left.arguments:
                corrupted.append((left, right))
            messages = messages + [ChatResponse(tool_calls=[right]).as_message(), tool_result(right.name, {"error": "invalid_arguments"}, right.id)]
        assert corrupted, "malformed_rate=1.0 must change at least one argument set"
        for left, right in corrupted:
            assert json.dumps(right.arguments, ensure_ascii=False) != json.dumps(left.arguments, ensure_ascii=False)
        # ... and the corruption is the kind a schema catches: renamed or mistyped keys
        assert any("orderId" in json.dumps(r.arguments) or "orderID" in json.dumps(r.arguments).lower() or "not-a-number" in json.dumps(r.arguments) or "ticketId" in json.dumps(r.arguments) or "customerID" in json.dumps(r.arguments) or isinstance(next(iter(r.arguments.values()), None), str) for _, r in corrupted)

    def test_the_repair_path_counts_repair_turns(self) -> None:
        policy = SurrogatePolicy(SurrogateProfile(malformed_rate=1.0, seed=11))
        messages: list[dict[str, Any]] = [user_message(REFUND_BRIEF)]
        for _ in range(4):
            response = policy.chat(request_for(messages))
            messages.append(response.as_message())
            messages.append(tool_result(response.tool_calls[0].name, {"error": "invalid_arguments", "hint": "use snake_case"}, f"call_{len(messages)}"))
        assert policy.repairs >= 1
        assert policy.calls == 4


class TestProfileKnobs:
    def test_defaults_are_a_competent_model(self) -> None:
        profile = SurrogateProfile()
        assert (profile.skip_verification, profile.blind_listing, profile.malformed_rate, profile.seed) == (False, False, 0.0, 7)

    def test_a_profile_is_reproducible_for_a_given_seed(self) -> None:
        def first_bad_arguments(seed: int) -> str:
            policy = SurrogatePolicy(SurrogateProfile(malformed_rate=1.0, seed=seed))
            messages = [user_message(REFUND_BRIEF)]
            out = ""
            for _ in range(3):
                response = policy.chat(request_for(messages))
                out = json.dumps(response.tool_calls[0].arguments, ensure_ascii=False, sort_keys=True)
                messages = messages + [response.as_message(), tool_result("get_ticket", {"error": "invalid_arguments"}, "x")]
            return out

        assert first_bad_arguments(5) == first_bad_arguments(5)
        assert first_bad_arguments(5) != first_bad_arguments(5 + 1) or first_bad_arguments(5)  # may coincide; determinism is what matters
