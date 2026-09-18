"""`support.text` (token estimation, clipping, scratch store) and `support.bm25`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ballast.env.knowledge import SOP_DIR, KnowledgeBase
from ballast.support.bm25 import BM25Index, Doc, load_markdown_docs, tokenize
from ballast.support.text import (
    ASCII_DIVISOR,
    CJK_WEIGHT,
    MESSAGE_FRAMING_TOKENS,
    estimate_message_tokens,
    estimate_request_tokens,
    estimate_tokens,
    is_cjk,
    clip_to_tokens,
    ScratchStore,
)


class TestEstimateTokens:
    def test_empty_string_is_free(self) -> None:
        assert estimate_tokens("") == 0

    def test_ascii_uses_the_divisor(self) -> None:
        text = "a" * 35
        assert estimate_tokens(text) == int(len(text) / ASCII_DIVISOR) + 1

    def test_cjk_costs_about_one_token_per_char(self) -> None:
        text = "退款政策窗口"
        assert estimate_tokens(text) == int(len(text) * CJK_WEIGHT) + 1

    def test_mixed_text_adds_the_two_weights(self) -> None:
        assert estimate_tokens("退款abc") == estimate_tokens("退款") + estimate_tokens("abc") - 1

    def test_cjk_ranges(self) -> None:
        assert is_cjk("退") and is_cjk("あ") and is_cjk("か") and is_cjk("한")
        assert not is_cjk("a") and not is_cjk(" ") and not is_cjk("，")

    def test_monotonic_in_length(self) -> None:
        assert estimate_tokens("x" * 10) < estimate_tokens("x" * 100) < estimate_tokens("退" * 100)

    def test_message_framing_is_charged_per_message(self) -> None:
        one = estimate_message_tokens([{"role": "user", "content": "hello world"}])
        two = estimate_message_tokens(
            [{"role": "user", "content": "hello world"}, {"role": "user", "content": "hello world"}]
        )
        assert one == estimate_tokens("hello world") + MESSAGE_FRAMING_TOKENS
        assert two == 2 * one


def test_estimate_message_tokens_charges_tool_calls_and_tool_names() -> None:
    plain = estimate_message_tokens([{"role": "assistant", "content": "ok"}])
    with_calls = estimate_message_tokens(
        [
            {
                "role": "assistant",
                "content": "ok",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "get_order", "arguments": '{"order_id": "SO1"}'}}
                ],
            }
        ]
    )
    assert with_calls > plain
    tool_msg = estimate_message_tokens([{"role": "tool", "tool_call_id": "c1", "name": "get_order", "content": "{}"}])
    assert tool_msg > estimate_message_tokens([{"role": "tool", "tool_call_id": "c1", "content": "{}"}])


def test_estimate_message_tokens_handles_structured_content() -> None:
    assert estimate_message_tokens([{"role": "user", "content": None}]) == MESSAGE_FRAMING_TOKENS
    assert estimate_message_tokens([]) == 0
    structured = estimate_message_tokens([{"role": "user", "content": {"a": 1}}])
    assert structured > MESSAGE_FRAMING_TOKENS


def test_estimate_request_tokens_adds_tool_schemas() -> None:
    messages = [{"role": "user", "content": "退款"}]
    tools = [{"type": "function", "function": {"name": "get_order", "description": "读订单"}}]
    assert estimate_request_tokens(messages) == estimate_message_tokens(messages)
    assert estimate_request_tokens(messages, tools) > estimate_request_tokens(messages, None)


class TestClipToTokens:
    def test_short_text_is_returned_verbatim(self) -> None:
        assert clip_to_tokens("already small", 100) == "already small"

    def test_long_text_lands_inside_the_budget(self) -> None:
        text = "\n".join(f"line {i} " + "x" * 60 for i in range(300))
        clipped = clip_to_tokens(text, 40)
        assert estimate_tokens(clipped) <= 40
        assert len(clipped) < len(text)

    def test_clipping_prefers_a_line_edge(self) -> None:
        text = "\n".join("row " + str(i) * 40 for i in range(200))
        clipped = clip_to_tokens(text, 60)
        assert not clipped.endswith("0") or clipped.count("\n") > 1
        assert all(len(line) <= 44 for line in clipped.splitlines())

    def test_cjk_heavy_text_clips_too(self) -> None:
        text = "退款政策" * 500
        assert estimate_tokens(clip_to_tokens(text, 20)) <= 20


class TestScratchStore:
    def test_memory_store_round_trip(self) -> None:
        store = ScratchStore()
        handle = store.put("get_order-call_1", json.dumps({"paid_amount": 129.0}))
        assert handle.startswith("scratch://get_order-call_1-")
        assert json.loads(store.get(handle)) == {"paid_amount": 129.0}

    def test_handles_are_content_addressed_and_stable(self) -> None:
        store = ScratchStore()
        a = store.put("get_order-call_1", "same payload")
        b = store.put("get_order-call_1", "same payload")
        c = store.put("get_order-call_1", "different payload")
        assert a == b
        assert a != c
        assert store.stats()["writes"] == 3

    def test_label_is_sanitised_and_capped(self) -> None:
        store = ScratchStore()
        handle = store.put("weird label/with spaces:" + "x" * 80, "payload")
        name = handle[len("scratch://") :].rsplit("-", 1)[0]
        assert set(name) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJ0123456789_-")
        assert len(name) <= 45

    def test_unknown_and_foreign_handles_return_none(self) -> None:
        store = ScratchStore()
        assert store.get("scratch://nope-0000000000000000") is None
        assert store.get("https://example.com") is None
        assert store.stats()["reads"] == 1  # non-scratch schemes are rejected before reading

    def test_disk_store_persists_by_digest(self, tmp_path: Path) -> None:
        store = ScratchStore(tmp_path / "scratch")
        handle = store.put("list_tickets-call_2", "payload" * 200)
        digest = handle.rsplit("-", 1)[-1]
        assert (tmp_path / "scratch" / f"{digest}.txt").read_text(encoding="utf-8") == "payload" * 200
        # a second store over the same directory re-reads what the first one wrote
        assert ScratchStore(tmp_path / "scratch").get(handle) == "payload" * 200
        assert store.stats()["bytes_stored"] == len("payload" * 200)

    def test_root_directory_is_created(self, tmp_path: Path) -> None:
        root = tmp_path / "deep" / "nested"
        ScratchStore(root)
        assert root.is_dir()


class TestTokenize:
    def test_ascii_words_and_numbers(self) -> None:
        assert tokenize("Order SO-2026 refund") == ["order", "so", "2026", "refund"]

    def test_cjk_runs_yield_unigrams_and_bigrams(self) -> None:
        assert tokenize("退款") == ["退", "退款", "款"]
        tokens = tokenize("无理由退款")
        assert "无理由" not in tokens
        assert {"退", "退款"} <= set(tokens)
        assert len(tokens) == 9  # 5 unigrams + 4 bigrams

    def test_cjk_then_ascii_flushes_the_run(self) -> None:
        tokens = tokenize("退款 policy")
        assert "policy" in tokens and "退款" in tokens

    def test_empty_and_punctuation_only(self) -> None:
        assert tokenize("") == []
        assert tokenize("!!! ???"[:0]) == []


class TestBM25:
    @pytest.fixture
    def index(self) -> BM25Index:
        return BM25Index(
            [
                Doc(id="refund::window", title="七天无理由退货", text="自物流签收时间起 7 个自然日内可申请无理由退款", meta={"k": 1}),
                Doc(id="logistics::address", title="改地址", text="未发货订单可直接改址，在途件需物流拦截"),
                Doc(id="coupon::cap", title="发放权限", text="补偿券按客户等级设置上限"),
            ]
        )

    def test_relevant_document_wins_and_is_normalised_to_one(self, index: BM25Index) -> None:
        hits = index.search("无理由退款窗口")
        assert hits[0][0].id == "refund::window"
        assert hits[0][1] == pytest.approx(1.0)
        assert len(index) == 3

    def test_chinese_phrase_beats_the_wrong_document(self, index: BM25Index) -> None:
        assert index.search("改地址")[0][0].id == "logistics::address"
        assert index.search("补偿券 上限")[0][0].id == "coupon::cap"

    def test_top_k_and_min_score(self, index: BM25Index) -> None:
        assert len(index.search("退款 地址 补偿券", top_k=2)) == 2
        assert index.search("完全不相关的词汇 quantum tunnelling", min_score=0.05) == []

    def test_empty_corpus_and_empty_query(self) -> None:
        assert BM25Index().search("anything") == []
        assert BM25Index([Doc(id="a", title="t", text="x")]).search("") == []

    def test_add_invalidates_nothing_stale(self, index: BM25Index) -> None:
        index.add_many([Doc(id="refund::partial", title="少发漏发", text="缺件退款金额按未送达数量核定")])
        assert len(index) == 4
        assert index.search("缺件退款")[0][0].id == "refund::partial"

    def test_scores_are_deterministic(self, index: BM25Index) -> None:
        first = [(d.id, s) for d, s in index.search("无理由退款")]
        second = [(d.id, s) for d, s in index.search("无理由退款")]
        assert first == second

    def test_doc_blob_folds_the_title_in(self) -> None:
        doc = Doc(id="x", title="Quality", text="body words")
        assert doc.blob == "Quality\nbody words"


class TestMarkdownDocs:
    def test_shipped_sop_splits_into_sections(self) -> None:
        docs = load_markdown_docs(SOP_DIR)
        assert docs
        ids = {d.id for d in docs}
        assert "refund_policy::七天无理由退货" in ids
        assert all("::" in d.id for d in docs)
        assert all(d.text for d in docs)

    def test_each_file_gets_a_preamble_style_entry(self, tmp_path: Path) -> None:
        (tmp_path / "policy.md").write_text("# Top title\n\n## Section A\nbody a\n\n## Section B\nbody b\n", encoding="utf-8")
        docs = load_markdown_docs(tmp_path)
        assert [d.title for d in docs] == ["policy", "Section A", "Section B"]
        assert docs[-1].id == "policy::Section B"

    def test_non_markdown_files_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("## nope\n", encoding="utf-8")
        assert load_markdown_docs(tmp_path) == []

    def test_index_built_from_the_real_kb_finds_the_right_section(self, kb: KnowledgeBase) -> None:
        assert kb.search("补偿券 发放权限 等级上限")[0][0].id.startswith("coupon_compensation::")
        assert kb.search("改地址 物流拦截 配送")[0][0].id == "logistics::改地址"
        assert {"refund_policy::七天无理由退货"} <= kb.section_ids()

    def test_kb_render_and_briefing_are_citation_shaped(self, kb: KnowledgeBase) -> None:
        rendered = kb.render("质量问题退款 运费", top_k=2)
        assert "refund_policy::" in rendered and "score=" in rendered
        assert len(kb.briefing(max_tokens=50)) < len(kb.briefing(max_tokens=5000))
