"""The provider-agnostic chat layer: usage accounting, cache keys, the response cache,
the OpenAI-compatible wire parser, and the replay provider's loud failure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ballast.llm.base import (
    ChatRequest,
    ChatResponse,
    DEEPSEEK_CHAT,
    DEEPSEEK_REASONER,
    Pricing,
    ToolCall,
    Usage,
    system_message,
    tool_message,
    user_message,
)
from ballast.llm.cache import ResponseCache
from ballast.llm.provider import OpenAICompatProvider, RETRYABLE_STATUS, deepseek
from ballast.llm.replay import ReplayMiss, ReplayProvider, load_fixture, response_from_fixture


class TestUsage:
    def test_defaults_are_all_zero(self) -> None:
        u = Usage()
        assert (u.total_tokens, u.uncached_input_tokens, u.calls) == (0, 0, 0)
        assert u.cost(Pricing()) == 0.0

    def test_cost_prices_cached_input_separately(self) -> None:
        u = Usage(input_tokens=1_000_000, cached_input_tokens=400_000, output_tokens=500_000)
        pricing = Pricing(input_per_m=2.0, cached_per_m=0.5, output_per_m=8.0)
        assert u.cost(pricing) == pytest.approx(600_000 / 1e6 * 2.0 + 400_000 / 1e6 * 0.5 + 500_000 / 1e6 * 8.0)

    def test_cached_tokens_cannot_exceed_input(self) -> None:
        u = Usage(input_tokens=100, cached_input_tokens=5_000, output_tokens=0)
        assert u.uncached_input_tokens == 0
        assert u.cost(Pricing(input_per_m=1_000_000.0, cached_per_m=0.0)) == pytest.approx(0.0)

    def test_merge_is_componentwise(self) -> None:
        a = Usage(input_tokens=10, output_tokens=1, cached_input_tokens=4, calls=1)
        b = Usage(input_tokens=7, output_tokens=2, cached_input_tokens=0, calls=3)
        merged = a.merge(b)
        assert merged.as_dict() == {
            "input_tokens": 17,
            "output_tokens": 3,
            "cached_input_tokens": 4,
            "total_tokens": 20,
            "calls": 4,
        }
        assert (a.input_tokens, b.calls) == (10, 3)  # merge does not mutate

    def test_shipped_pricing_profiles(self) -> None:
        assert DEEPSEEK_REASONER.input_per_m == 2 * DEEPSEEK_CHAT.input_per_m
        assert DEEPSEEK_CHAT.currency == "CNY"
        assert DEEPSEEK_CHAT.as_dict()["cached_per_m"] == 0.5


class TestChatRequest:
    def _req(self, **kw) -> ChatRequest:
        base = {
            "messages": [{"role": "user", "content": "退款政策是什么"}],
            "tools": [{"type": "function", "function": {"name": "search_sop"}}],
            "model": "deepseek-chat",
            "temperature": 0.0,
            "seed": 7,
        }
        base.update(kw)
        return ChatRequest(**base)

    def test_same_request_same_key(self) -> None:
        assert self._req().cache_key() == self._req().cache_key()
        assert len(self._req().cache_key()) == 64

    @pytest.mark.parametrize(
        "kw",
        [
            {"model": "deepseek-reasoner"},
            {"temperature": 0.7},
            {"seed": 8},
            {"max_tokens": 128},
            {"tool_choice": "none"},
            {"messages": [{"role": "user", "content": "退款政策是什么?"}]},
            {"tools": []},
        ],
    )
    def test_any_semantic_change_changes_the_key(self, kw: dict) -> None:
        assert self._req().cache_key() != self._req(**kw).cache_key()

    def test_key_is_independent_of_json_member_order(self) -> None:
        a = ChatRequest(messages=[{"role": "user", "content": "x", "name": "n"}])
        b = ChatRequest(messages=[{"name": "n", "role": "user", "content": "x"}])
        assert a.cache_key() == b.cache_key()

    def test_default_fields_are_present(self) -> None:
        req = ChatRequest(messages=[])
        assert req.tools == [] and req.tool_choice == "auto" and req.max_tokens is None


class TestChatResponseAndMessages:
    def test_as_message_omits_tool_calls_when_absent(self) -> None:
        assert ChatResponse(content="done").as_message() == {"role": "assistant", "content": "done"}
        assert ChatResponse().as_message()["content"] == ""

    def test_as_message_serialises_arguments_as_a_json_string(self) -> None:
        msg = ChatResponse(tool_calls=[ToolCall(id="c1", name="get_order", arguments={"order_id": "SO1", "备注": "中文"})]).as_message()
        assert msg["tool_calls"][0]["function"]["name"] == "get_order"
        assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"order_id": "SO1", "备注": "中文"}
        assert "中文" in msg["tool_calls"][0]["function"]["arguments"]  # not \u-escaped

    def test_message_helpers(self) -> None:
        assert tool_message("c1", "get_order", "{}") == {"role": "tool", "tool_call_id": "c1", "name": "get_order", "content": "{}"}
        assert user_message("hi") == {"role": "user", "content": "hi"}
        assert system_message("sys") == {"role": "system", "content": "sys"}


class TestResponseCache:
    def test_round_trip_keeps_content_calls_and_finish_reason(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        original = ChatResponse(
            content="hi",
            tool_calls=[ToolCall(id="c1", name="issue_refund", arguments={"amount": 12.5, "reason": "中文"})],
            usage=Usage(input_tokens=900, output_tokens=30, cached_input_tokens=100, calls=1),
            finish_reason="tool_calls",
        )
        key = ChatRequest(messages=[{"role": "user", "content": "x"}], model="m").cache_key()
        cache.put(key, original)
        hit = cache.get(key)
        assert hit is not None
        assert hit.content == "hi"
        assert hit.finish_reason == "tool_calls"
        assert hit.tool_calls[0].name == "issue_refund"
        assert hit.tool_calls[0].arguments == {"amount": 12.5, "reason": "中文"}
        assert hit.cached is True

    def test_a_hit_reports_zero_tokens_and_exactly_one_call(self, tmp_path: Path) -> None:
        # The replayed call was already billed; charging it again would double-count spend.
        cache = ResponseCache(tmp_path / "cache")
        key = "abcd1234" * 8
        cache.put(
            key,
            ChatResponse(content="x", usage=Usage(input_tokens=4000, output_tokens=200, cached_input_tokens=1000, calls=1)),
        )
        hit = cache.get(key)
        assert hit.usage == Usage(input_tokens=0, output_tokens=0, cached_input_tokens=0, calls=1)
        assert hit.usage.cost(DEEPSEEK_CHAT) == 0.0
        assert cache.stats() == {"hits": 1, "misses": 0}

    def test_misses_are_counted(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        assert cache.get("deadbeef") is None
        assert cache.stats() == {"hits": 0, "misses": 1}

    def test_disabled_cache_stores_nothing(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path / "cache", enabled=False)
        cache.put("k", ChatResponse(content="x"))
        assert cache.get("k") is None
        assert not (tmp_path / "cache").exists()

    def test_namespaced_entries_do_not_collide(self, tmp_path: Path) -> None:
        a = ResponseCache(tmp_path / "c", namespace="arm_a")
        b = ResponseCache(tmp_path / "c", namespace="arm_b")
        a.put("k" * 16, ChatResponse(content="from a"))
        assert a.get("k" * 16).content == "from a"
        assert b.get("k" * 16) is None
        assert a.path_for("k" * 16).name.startswith("arm_a_")

    def test_corrupt_payload_counts_as_a_miss_not_a_crash(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path / "c")
        path = cache.path_for("f" * 16)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        assert cache.get("f" * 16) is None
        assert cache.stats()["misses"] == 1

    def test_write_is_atomic(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path / "c")
        cache.put("e" * 16, ChatResponse(content="v1"))
        cache.put("e" * 16, ChatResponse(content="v2"))
        assert cache.get("e" * 16).content == "v2"
        assert list((tmp_path / "c").glob("*.tmp")) == []


class TestOpenAICompatParse:
    """`_parse` is pure: exercise the wire format without touching a socket."""

    def test_plain_text_answer(self) -> None:
        payload = {
            "model": "deepseek-chat",
            "choices": [{"message": {"role": "assistant", "content": "可以退"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 8, "prompt_tokens_details": {"cached_tokens": 64}},
        }
        resp = OpenAICompatProvider._parse(payload, model="fallback")
        assert resp.content == "可以退"
        assert resp.tool_calls == []
        assert resp.usage == Usage(input_tokens=120, output_tokens=8, cached_input_tokens=64, calls=1)
        assert resp.raw == {"model": "deepseek-chat"}

    def test_vendor_specific_cache_field_wins(self) -> None:
        payload = {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "prompt_cache_hit_tokens": 9, "prompt_tokens_details": {"cached_tokens": 2}},
        }
        assert OpenAICompatProvider._parse(payload).usage.cached_input_tokens == 9

    def test_tool_call_arguments_are_decoded(self) -> None:
        payload = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {"id": "call_9", "function": {"name": "compute_refund", "arguments": '{"order_id": "SO1", "claim_type": "quality"}'}}
                        ],
                    },
                }
            ]
        }
        resp = OpenAICompatProvider._parse(payload)
        assert resp.finish_reason == "tool_calls"
        assert resp.content is None
        assert resp.tool_calls[0].id == "call_9"
        assert resp.tool_calls[0].arguments == {"order_id": "SO1", "claim_type": "quality"}

    @pytest.mark.parametrize(
        "arguments,expected",
        [("", {}), ("   ", {}), ("not json", {"_raw": "not json"}), ('["a","b"]', {"_raw": '["a", "b"]'}), ({"amount": 3}, {"amount": 3})],
    )
    def test_malformed_and_unusual_argument_blobs(self, arguments: object, expected: dict) -> None:
        payload = {"choices": [{"message": {"tool_calls": [{"function": {"name": "t", "arguments": arguments}}]}}]}
        assert OpenAICompatProvider._parse(payload).tool_calls[0].arguments == expected

    def test_synthetic_call_ids_and_empty_payload(self) -> None:
        payload = {"choices": [{"message": {"tool_calls": [{"function": {"name": "a"}}, {"function": {"name": "b"}}]}}]}
        calls = OpenAICompatProvider._parse(payload).tool_calls
        assert [c.id for c in calls] == ["call_0", "call_1"]
        empty = OpenAICompatProvider._parse({})
        assert empty.content is None and empty.finish_reason == "stop" and empty.usage.calls == 1

    def test_snake_case_usage_aliases(self) -> None:
        payload = {"choices": [{"message": {"content": "x"}}], "usage": {"input_tokens": 5, "output_tokens": 6}}
        assert OpenAICompatProvider._parse(payload).usage.total_tokens == 11


class TestProviderConstruction:
    def test_empty_api_key_fails_before_any_request(self) -> None:
        with pytest.raises(Exception, match="api_key is empty"):
            OpenAICompatProvider(api_key="")
        with pytest.raises(Exception):
            deepseek(api_key="")

    def test_deepseek_defaults(self) -> None:
        provider = deepseek(api_key="k")
        assert provider.base_url == "https://api.deepseek.com" and provider.model == "deepseek-chat"
        assert provider.name == "openai_compat" and 429 in RETRYABLE_STATUS and 400 not in RETRYABLE_STATUS

    def test_request_body_shape(self) -> None:
        provider = deepseek(api_key="k", seed=3, temperature=0.0)
        # `_body` reads the request, and `chat()` is what fills request defaults from the
        # provider, so the seed/temperature have to be on the request here.
        req = ChatRequest(messages=[{"role": "user", "content": "x"}], tools=[{"t": 1}], max_tokens=64, model=provider.model, seed=3, temperature=0.0)
        body = provider._body(req)
        assert body["model"] == "deepseek-chat" and body["stream"] is False and body["seed"] == 3
        assert body["tools"] == [{"t": 1}] and body["tool_choice"] == "auto" and body["max_tokens"] == 64
        bare = ChatRequest(messages=[{"role": "user", "content": "x"}], model="m")
        assert "max_tokens" not in provider._body(bare) and "seed" not in provider._body(bare) and "tools" not in provider._body(bare)

    def test_chat_stamps_provider_defaults_on_the_request(self, tmp_path: Path) -> None:
        provider = deepseek(api_key="k", cache=ResponseCache(tmp_path / "c"), seed=11)
        stamped = ChatRequest(messages=[{"role": "user", "content": "x"}], model="deepseek-chat", seed=11)
        provider.cache.put(stamped.cache_key(), ChatResponse(content="cached"))
        bare = ChatRequest(messages=[{"role": "user", "content": "x"}])
        assert provider.chat(bare).content == "cached"  # a hit, so still no network
        assert (bare.model, bare.seed) == ("deepseek-chat", 11)

    def test_provider_temperature_never_reaches_the_wire(self) -> None:
        # KNOWN BUG (src/ballast/llm/provider.py:58): `chat()` only copies
        # `self.temperature` onto the request `if request.temperature is None`, but
        # `ChatRequest.temperature` defaults to 0.0, so the configured provider
        # temperature is dead configuration and every request is sent at 0.0.
        hot = deepseek(api_key="k", temperature=0.9)
        cold = deepseek(api_key="k", temperature=0.1)
        req = ChatRequest(messages=[{"role": "user", "content": "x"}], model="m")
        assert hot._body(req) == cold._body(req)
        assert hot._body(req)["temperature"] == 0.0

    def test_cache_hit_short_circuits_before_the_network(self, tmp_path: Path) -> None:
        provider = deepseek(api_key="k", cache=ResponseCache(tmp_path / "c"))
        req = ChatRequest(messages=[{"role": "user", "content": "x"}], model="deepseek-chat", temperature=0.0, seed=7)
        provider.cache.put(req.cache_key(), ChatResponse(content="cached answer", usage=Usage(input_tokens=99, calls=1)))
        resp = provider.chat(req)  # would raise on a real POST
        assert resp.content == "cached answer" and resp.cached and provider.attempts == 0


class TestReplayProvider:
    def test_replays_a_recorded_response(self, tmp_path: Path) -> None:
        req = ChatRequest(messages=[{"role": "user", "content": "退款"}], tools=[{"type": "function"}], model="m", seed=7)
        ResponseCache(tmp_path).put(req.cache_key(), ChatResponse(content="recorded", tool_calls=[ToolCall(id="c", name="t", arguments={"a": 1})]))
        provider = ReplayProvider(tmp_path)
        out = provider.chat(req)
        assert out.content == "recorded" and out.cached and out.usage.calls == 1 and out.usage.total_tokens == 0
        assert provider.keys() == [req.cache_key()] and len(provider) == 1

    def test_uncached_key_raises_loudly(self, tmp_path: Path) -> None:
        # This is the feature: a stale fixture must fail the build, not quietly
        # hit the network or answer a question nobody asked.
        provider = ReplayProvider(tmp_path)
        req = ChatRequest(messages=[{"role": "user", "content": "changed prompt"}], model="m")
        with pytest.raises(ReplayMiss, match="no recorded response"):
            provider.chat(req)
        assert provider.misses == [req.cache_key()]

    def test_changed_prompt_is_a_miss(self, tmp_path: Path) -> None:
        req = ChatRequest(messages=[{"role": "user", "content": "v1"}], model="m")
        ResponseCache(tmp_path).put(req.cache_key(), ChatResponse(content="v1"))
        provider = ReplayProvider(tmp_path)
        assert provider.chat(ChatRequest(messages=[{"role": "user", "content": "v1"}], model="m")).content == "v1"
        with pytest.raises(ReplayMiss):
            provider.chat(ChatRequest(messages=[{"role": "user", "content": "v2"}], model="m"))

    def test_fixtures_round_trip_through_jsonl(self, tmp_path: Path) -> None:
        req = ChatRequest(messages=[{"role": "user", "content": "x"}], model="m")
        ResponseCache(tmp_path).put(
            req.cache_key(),
            ChatResponse(content="answer", tool_calls=[ToolCall(id="c1", name="t", arguments={"a": 1})], usage=Usage(input_tokens=3, output_tokens=4, calls=1)),
        )
        fixture = tmp_path / "fixture.jsonl"
        count = 0
        for key in ReplayProvider(tmp_path).keys():
            data = json.loads((tmp_path / key[:2] / f"{key}.json").read_text(encoding="utf-8"))
            fixture.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
            count += 1
        assert count == 1
        records = load_fixture(fixture)
        assert len(records) == 1
        restored = response_from_fixture(records[0])
        assert restored.content == "answer" and restored.usage.total_tokens == 7 and restored.tool_calls[0].name == "t"

    def test_export_fixture_is_a_no_op_on_a_real_cache(self, tmp_path: Path) -> None:
        # KNOWN BUG (src/ballast/llm/replay.py:59): `export_fixture` guards with
        # `hasattr(cache, "keys")`, but `ResponseCache` has no `keys()` method (only
        # `ReplayProvider` does), so the loop body never runs and the export is always
        # an empty file with a 0 count. Asserted as-is so the fix shows up as a red test.
        from ballast.llm.replay import export_fixture

        req = ChatRequest(messages=[{"role": "user", "content": "x"}], model="m")
        ResponseCache(tmp_path / "c").put(req.cache_key(), ChatResponse(content="answer"))
        out = tmp_path / "out.jsonl"
        assert export_fixture(tmp_path / "c", out) == 0
        assert out.read_text(encoding="utf-8") == ""
