"""Context engineering: offload handles, block-safe compaction, pinned re-fetches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ballast.context.engine import ContextEngine, ContextPolicy, extractive_summary
from ballast.support.text import ScratchStore, estimate_message_tokens, estimate_tokens
from conftest import assert_tool_calls_answered, call_step  # noqa: E402  (helper, not a fixture)

BIG = json.dumps(
    {"tickets": [{"id": f"T{i:04d}", "claim": "客户的中文诉求描述，包含订单信息与物流状态说明。" * 6} for i in range(40)]},
    ensure_ascii=False,
)


def make_engine(**policy: Any) -> ContextEngine:
    defaults: dict[str, Any] = {"token_budget": 4_000, "offload_threshold": 120, "preview_chars": 120}
    defaults.update(policy)
    return ContextEngine(ContextPolicy(**defaults), scratch=ScratchStore())


def tool_call_block(index: int, *, name: str = "get_order", tokens_of_noise: int = 300) -> tuple[dict[str, Any], dict[str, Any]]:
    arguments = {"order_id": f"SO{index:06d}", "pad": "x" * tokens_of_noise}
    return (
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": f"call_{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}],
        },
        {"role": "tool", "tool_call_id": f"call_{index}", "name": name, "content": json.dumps({"id": f"SO{index}", "paid_amount": 100 + index, "status": "delivered", "junk": "y" * tokens_of_noise})},
    )


def grow(engine: ContextEngine, blocks: int = 8, **kw: Any) -> None:
    for i in range(blocks):
        assistant, tool = tool_call_block(i, **kw)
        engine.transcript.append(assistant)
        engine.transcript.append(tool)


class TestPolicy:
    def test_defaults_and_serialisation(self) -> None:
        policy = ContextPolicy()
        assert policy.enable_offload and policy.enable_compaction
        assert policy.offload_exempt == ("read_scratch",)
        assert policy.as_dict()["token_budget"] == 12_000
        assert "preview_chars" not in policy.as_dict()

    def test_trigger_point_is_budget_times_threshold(self) -> None:
        assert int(ContextPolicy(token_budget=1000, compact_threshold=0.72).token_budget * ContextPolicy().compact_threshold) == 720


class TestOffload:
    def test_big_results_are_replaced_by_a_handle(self) -> None:
        engine = make_engine()
        content = engine.tool_result("call_1", "list_tickets", BIG)
        assert content.startswith("[output ")
        assert "moved out of context -> scratch://" in content
        assert "read_scratch(handle, offset, limit)" in content
        assert engine.stats.offloads == 1
        assert estimate_tokens(content) < estimate_tokens(BIG) / 5

    def test_the_payload_stays_reachable(self) -> None:
        engine = make_engine()
        content = engine.tool_result("call_1", "list_tickets", BIG)
        handle = content.split("-> ")[1].split("]")[0]
        assert engine.scratch.get(handle) == BIG
        assert handle.startswith("scratch://list_tickets-call_1-")

    def test_head_and_tail_preview_survive(self) -> None:
        engine = make_engine()
        text = "\n".join(f"line-{i}-" + "z" * 40 for i in range(200))
        content = engine.tool_result("call_7", "list_tickets", text)
        assert "line-0-" in content and f"line-{199}-" in content

    def test_small_results_are_left_alone(self) -> None:
        engine = make_engine()
        payload = json.dumps({"order": {"id": "SO1"}})
        assert engine.tool_result("call_1", "get_order", payload) == payload
        assert engine.stats.offloads == 0 and engine.stats.saved_tokens == 0

    def test_saved_tokens_is_the_real_win(self) -> None:
        engine = make_engine()
        before = estimate_tokens(BIG)
        content = engine.tool_result("call_1", "list_tickets", BIG)
        assert engine.stats.saved_tokens == before - estimate_tokens(content) > 1000

    def test_read_scratch_is_exempt_so_the_retrieval_does_not_loop(self) -> None:
        engine = make_engine()
        handle = engine.tool_result("call_1", "list_tickets", BIG).split("-> ")[1].split("]")[0]
        fetched = json.dumps({"handle": handle, "offset": 0, "text": BIG}, ensure_ascii=False)
        content = engine.tool_result("call_2", "read_scratch", fetched)
        assert content == fetched  # verbatim, no second offload
        assert engine.stats.offloads == 1
        assert engine.transcript[-1]["_pin"] is True

    def test_exempt_list_is_configurable(self) -> None:
        engine = make_engine(offload_exempt=())
        engine.tool_result("call_2", "read_scratch", json.dumps({"text": BIG}))
        assert engine.stats.offloads == 1
        assert "_pin" not in engine.transcript[-1]

    def test_disabled_offload_keeps_everything_inline(self) -> None:
        engine = make_engine(enable_offload=False)
        assert engine.tool_result("call_1", "list_tickets", BIG) == BIG
        assert engine.stats.offloads == 0

    def test_offload_message_shape_is_a_valid_tool_reply(self) -> None:
        engine = make_engine()
        engine.user("task")
        engine.assistant("", [{"id": "call_1", "type": "function", "function": {"name": "list_tickets", "arguments": "{}"}}])
        engine.tool_result("call_1", "list_tickets", BIG)
        assert_tool_calls_answered(engine.assemble())
        assert engine.transcript[-1]["tool_call_id"] == "call_1"

    def test_disk_backed_scratch_store_works_too(self, tmp_path: Path) -> None:
        engine = ContextEngine(ContextPolicy(offload_threshold=10), scratch=ScratchStore(tmp_path / "s"))
        content = engine.tool_result("call_1", "list_tickets", BIG)
        handle = content.split("-> ")[1].split("]")[0]
        assert engine.scratch.get(handle) == BIG
        assert list((tmp_path / "s").glob("*.txt"))


class TestCompaction:
    def test_folding_only_happens_past_the_trigger(self) -> None:
        engine = make_engine(token_budget=100_000, compact_threshold=0.72)
        engine.pin("system")
        engine.user("task")
        grow(engine, 6)
        before = engine.stats.compactions
        engine.assemble()
        assert engine.stats.compactions == before and engine.summary is None

    def test_older_blocks_are_folded_into_a_summary(self) -> None:
        engine = make_engine(token_budget=900, compact_threshold=0.5, keep_recent_blocks=2)
        engine.pin("SYSTEM")
        engine.user("任务：处理工单 T1042")
        grow(engine, 8)
        messages = engine.assemble()
        assert engine.stats.compactions >= 1
        assert engine.stats.dropped_blocks >= 2
        assert "[earlier context folded]" in messages[1]["content"]
        assert "任务：处理工单" in engine.summary or "get_order" in engine.summary

    def test_compaction_never_orphans_an_assistant_tool_call(self) -> None:
        engine = make_engine(token_budget=900, compact_threshold=0.5, keep_recent_blocks=2)
        engine.pin("SYSTEM")
        engine.user("task")
        grow(engine, 10)
        for _ in range(4):
            messages = engine.assemble()
            assert_tool_calls_answered(messages)
            grow(engine, 2)
        assert engine.stats.compactions >= 1

    def test_blocks_fold_whole_not_message_by_message(self) -> None:
        engine = make_engine(token_budget=900, compact_threshold=0.5, keep_recent_blocks=2)
        engine.pin("SYSTEM")
        engine.user("task")
        grow(engine, 8)
        engine.assemble()
        roles = [m["role"] for m in engine.transcript]
        assert "system" not in roles
        # whatever survives is a sequence of intact assistant+tool pairs
        assert_tool_calls_answered(engine.assemble())
        assert all(r in {"assistant", "tool", "user"} for r in roles)

    def test_pinned_re_fetch_survives_compaction(self) -> None:
        engine = make_engine(token_budget=900, compact_threshold=0.5, keep_recent_blocks=2)
        engine.pin("SYSTEM")
        engine.user("task")
        grow(engine, 3)
        handle = engine.tool_result("call_off", "list_tickets", BIG).split("-> ")[1].split("]")[0]
        engine.assistant("", [{"id": "call_rs", "type": "function", "function": {"name": "read_scratch", "arguments": json.dumps({"handle": handle})}}])
        engine.tool_result("call_rs", "read_scratch", json.dumps({"handle": handle, "text": BIG}, ensure_ascii=False))
        grow(engine, 6)
        messages = engine.assemble()
        assert engine.stats.compactions >= 1
        pinned = [m for m in engine.transcript if m.get("_pin")]
        assert len(pinned) == 1 and BIG[:60] in pinned[0]["content"]
        assert any("read_scratch" in str(m.get("tool_calls")) for m in messages)
        assert_tool_calls_answered(messages)

    def test_pinned_system_content_is_never_folded_away(self) -> None:
        engine = make_engine(token_budget=900, compact_threshold=0.5, keep_recent_blocks=2)
        engine.pin("POLICY: 必须先 compute_refund 再 issue_refund")
        engine.user("task")
        grow(engine, 8)
        messages = engine.assemble()
        assert any("必须先 compute_refund" in str(m.get("content")) for m in messages)
        assert messages[0]["role"] == "system"

    def test_compaction_is_skipped_when_there_is_nothing_worth_dropping(self) -> None:
        engine = make_engine(token_budget=600, compact_threshold=0.5, keep_recent_blocks=6)
        engine.pin("sys")
        grow(engine, 3)
        engine.assemble()
        assert engine.stats.compactions == 0

    def test_stats_track_the_peak_prompt(self) -> None:
        engine = make_engine(token_budget=900, compact_threshold=0.5, keep_recent_blocks=2)
        engine.pin("sys")
        grow(engine, 8)
        engine.assemble()
        assert engine.stats.peak_prompt_tokens >= engine.stats.prompt_tokens
        assert engine.stats.prompt_tokens == estimate_message_tokens(engine.assemble())
        assert engine.stats.pinned_tokens > 0

    def test_a_custom_summariser_is_used(self) -> None:
        calls: list[int] = []

        def summarizer(messages: list[dict[str, Any]], previous: str | None) -> str:
            calls.append(len(messages))
            return "HAND ROLLED SUMMARY"

        engine = ContextEngine(ContextPolicy(token_budget=900, compact_threshold=0.5, keep_recent_blocks=2, offload_threshold=10**9), summarizer=summarizer)
        engine.pin("sys")
        grow(engine, 8)
        messages = engine.assemble()
        assert calls and engine.summary == "HAND ROLLED SUMMARY"
        assert "HAND ROLLED SUMMARY" in messages[1]["content"]

    def test_disabled_compaction_leaves_the_transcript_growing(self) -> None:
        engine = make_engine(token_budget=600, compact_threshold=0.5, keep_recent_blocks=2, enable_compaction=False)
        engine.pin("sys")
        grow(engine, 6)
        messages = engine.assemble()
        assert engine.stats.compactions == 0
        assert len(engine.transcript) == 12
        assert len(messages) == 13


class TestExtractiveSummary:
    def test_key_facts_survive_and_noise_does_not(self) -> None:
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "get_order", "arguments": '{"order_id": "SO1"}'}}]},
            {"role": "tool", "tool_call_id": "c", "name": "get_order", "content": json.dumps({"id": "SO1", "paid_amount": 129.0, "status": "delivered", "huge": "z" * 500})},
            {"role": "user", "content": "工单 T1042 无理由退款"},
        ]
        summary = extractive_summary(messages)
        assert "get_order" in summary and "129" in summary and "paid_amount" in summary
        assert "z" * 500 not in summary
        assert "- user: 工单 T1042" in summary

    def test_previous_summary_is_carried_forward(self) -> None:
        assert extractive_summary([], "earlier facts").startswith("earlier facts")

    def test_summary_itself_is_capped(self) -> None:
        messages = [{"role": "tool", "name": f"t{i}", "content": json.dumps({"note": "备注" * 200})} for i in range(200)]
        assert estimate_tokens(extractive_summary(messages)) < 1_600

    def test_unparsable_tool_content_is_shortened_not_crashed(self) -> None:
        summary = extractive_summary([{"role": "tool", "name": "x", "content": "not json at all " * 100}])
        assert "x" in summary and "…" in summary


class TestSnapshotRestore:
    def test_round_trip_preserves_state_and_counters(self) -> None:
        engine = make_engine(token_budget=900, compact_threshold=0.5, keep_recent_blocks=2)
        engine.pin("sys")
        engine.user("task")
        grow(engine, 6)
        engine.assemble()
        snapshot = engine.snapshot()
        restored = ContextEngine.restore(snapshot, policy=engine.policy, scratch=ScratchStore())
        assert restored.transcript == engine.transcript
        assert restored.summary == engine.summary
        assert restored.stats.as_dict() == engine.stats.as_dict()
        assert restored.assemble()[0]["content"] == "sys"

    def test_snapshot_is_json_serialisable(self) -> None:
        engine = make_engine()
        engine.user("task")
        engine.tool_result("call_1", "list_tickets", BIG)
        assert json.loads(json.dumps(engine.snapshot(), ensure_ascii=False))["transcript"][0]["name"] == "list_tickets"

    def test_restore_with_empty_data_gets_a_default_pin(self) -> None:
        restored = ContextEngine.restore({})
        assert restored.pins == [{"role": "system", "content": ""}]
        assert restored.assemble() == [{"role": "system", "content": ""}]
        assert restored.summary is None

    def test_restore_ignores_unknown_stat_keys(self) -> None:
        restored = ContextEngine.restore({"stats": {"offloads": 3, "not_a_stat": 9}})
        assert restored.stats.offloads == 3 and "not_a_stat" not in restored.stats.as_dict()


class TestAssembly:
    def test_message_order_is_pins_then_summary_then_transcript(self) -> None:
        engine = make_engine()
        engine.pin("PIN A")
        engine.pin("PIN B", slot=1)
        engine.user("hello")
        messages = engine.assemble()
        assert [m["role"] for m in messages] == ["system", "system", "system", "user"]
        assert messages[1]["content"] == "PIN A" and messages[2]["content"] == "PIN B"

    def test_assistant_and_tool_helpers(self) -> None:
        engine = make_engine()
        engine.assistant("thinking")
        engine.assistant()
        assert engine.transcript == [{"role": "assistant", "content": "thinking"}, {"role": "assistant", "content": ""}]
        engine.add({"role": "user", "content": "raw"})
        assert engine.transcript[-1]["content"] == "raw"

    def test_empty_engine_is_just_a_blank_system_pin(self) -> None:
        engine = ContextEngine()
        assert engine.assemble() == [{"role": "system", "content": ""}]
        assert engine.stats.prompt_tokens == 4

    def test_scripted_call_shape_matches_the_engine(self) -> None:
        response = call_step(3, "compute_refund", order_id="SO1", claim_type="no_reason")
        assert response.tool_calls[0].id == "call_3"
        assert json.loads(response.as_message()["tool_calls"][0]["function"]["arguments"]) == {"order_id": "SO1", "claim_type": "no_reason"}


def test_offload_then_compaction_saves_materially_more_than_compaction_alone() -> None:
    """The claim the benchmark makes about this mechanism, checked in one place."""
    def build(**policy: Any) -> ContextEngine:
        engine = make_engine(token_budget=2_000, compact_threshold=0.6, keep_recent_blocks=3, **policy)
        engine.pin("SYSTEM")
        engine.user("task")
        for i in range(4):
            engine.assistant("", [{"id": f"call_{i}", "type": "function", "function": {"name": "list_tickets", "arguments": "{}"}}])
            engine.tool_result(f"call_{i}", "list_tickets", BIG)
        engine.assemble()
        return engine

    with_offload = build()
    without = build(enable_offload=False)
    assert with_offload.stats.offloads == 4
    assert without.stats.offloads == 0
    assert with_offload.stats.prompt_tokens < without.stats.prompt_tokens
    assert with_offload.stats.saved_tokens > 0
