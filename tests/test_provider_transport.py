"""The wire is the risky part, so the wire gets a test.

Everything here exercises `OpenAICompatProvider` against a local HTTP server rather
than a mock object, which is the only way to catch the failures that actually happen
in integration: a missing bearer header, a body the vendor rejects, tool arguments that
arrive as a JSON string, a 429 that must be retried without charging twice, and a
`prompt_cache_hit_tokens` field that silently becomes zero cost.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from ballast.bench.graders import grade
from ballast.context.engine import ContextPolicy
from ballast.env.fixtures import by_id
from ballast.env.knowledge import KnowledgeBase
from ballast.kernel.agent import Agent, AgentConfig
from ballast.kernel.budget import RunBudget
from ballast.kernel.events import RunContext
from ballast.kernel.toolkit import Toolkit
from ballast.llm.base import ChatRequest, ChatResponse, Pricing, ProviderError, Usage
from ballast.llm.cache import ResponseCache
from ballast.llm.provider import OpenAICompatProvider
from ballast.support.text import ScratchStore
from ballast.tools.desk import build_desk_tools

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mock_openai_server  # noqa: E402


@pytest.fixture(scope="module")
def server():
    httpd, _thread = mock_openai_server.serve()
    yield httpd
    httpd.shutdown()


@pytest.fixture
def base_url(server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture(autouse=True)
def _clean(server):
    mock_openai_server.reset()
    yield


def serve_class(handler_cls) -> str:
    """Run a custom handler class on a throwaway loopback port."""
    httpd = mock_openai_server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def provider(base_url: str, **kwargs):
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("model", "mock-chat")
    return OpenAICompatProvider(base_url=base_url, **kwargs)


class TestRequestShape:
    def test_bearer_token_and_body_reach_the_server(self, base_url) -> None:
        response = provider(base_url).chat(ChatRequest(messages=[{"role": "user", "content": "hi"}], model="mock-chat"))
        assert isinstance(response, ChatResponse)
        recorded = mock_openai_server.recorded()
        assert recorded[-1]["path"] == "/chat/completions"
        assert recorded[-1]["auth"] == "Bearer test-key"
        body = recorded[-1]["body"]
        assert body["model"] == "mock-chat"
        assert body["messages"][0]["content"] == "hi"
        assert body["stream"] is False

    def test_sampling_params_are_forwarded_only_when_set(self, base_url) -> None:
        provider(base_url).chat(ChatRequest(messages=[{"role": "user", "content": "x"}], model="m", seed=11, max_tokens=64))
        body = mock_openai_server.recorded()[-1]["body"]
        assert body["seed"] == 11
        assert body["max_tokens"] == 64

    def test_tools_and_tool_choice_travel_together(self, base_url) -> None:
        schema = [{"type": "function", "function": {"name": "get_ticket", "parameters": {}}}]
        provider(base_url).chat(ChatRequest(messages=[{"role": "user", "content": "x"}], tools=schema, model="m"))
        body = mock_openai_server.recorded()[-1]["body"]
        assert body["tools"] == schema and body["tool_choice"] == "auto"

    def test_a_missing_key_is_rejected_before_any_request(self, base_url) -> None:
        with pytest.raises(ProviderError, match="api_key is empty"):
            OpenAICompatProvider(base_url=base_url, api_key="")
        assert mock_openai_server.recorded() == []


class TestResponseParsing:
    def test_tool_arguments_arriving_as_a_json_string_are_parsed(self, base_url) -> None:
        request = ChatRequest(messages=[{"role": "user", "content": "工单 T1042 无理由退款"}], model="m")
        response = provider(base_url).chat(request)
        assert response.tool_calls, "expected the first step to be a tool call"
        assert response.tool_calls[0].name == "get_ticket"
        assert response.tool_calls[0].arguments == {"ticket_id": "T1042"}
        assert response.finish_reason == "tool_calls"

    def test_cached_tokens_are_read_from_either_vendor_spelling(self, base_url) -> None:
        response = provider(base_url).chat(ChatRequest(messages=[{"role": "user", "content": "hi"}], model="m"))
        assert response.usage.input_tokens > 0
        # the server reports cached_tokens as half the prompt, so accounting must see it
        assert 0 < response.usage.cached_input_tokens < response.usage.input_tokens
        pricing = Pricing(input_per_m=100.0, cached_per_m=0.0, output_per_m=0.0)
        assert response.usage.cost(pricing) == pytest.approx(
            response.usage.uncached_input_tokens / 1e6 * 100.0
        )

    def test_malformed_json_arguments_survive_as_raw_text(self, server, base_url) -> None:
        class Broken(mock_openai_server.Handler):
            def do_POST(self):  # noqa: N802
                self._json(
                    200,
                    {
                        "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "function": {"name": "x", "arguments": "{oops"}}]}, "finish_reason": "tool_calls"}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 5},
                    },
                )

        httpd, url = serve_class(Broken)
        try:
            response = provider(url).chat(ChatRequest(messages=[{"role": "user", "content": "x"}], model="m"))
            assert response.tool_calls[0].arguments == {"_raw": "{oops"}, "malformed arguments are kept, not dropped"
        finally:
            httpd.shutdown()


class TestRetriesAndErrors:
    def test_a_429_is_retried_and_charges_once(self, base_url, tmp_path) -> None:
        cache = ResponseCache(tmp_path / "cache")
        p = provider(base_url, cache=cache, max_attempts=3, timeout_s=10)
        mock_openai_server.Handler.flaky_left = 1
        before = len(mock_openai_server.recorded())
        response = p.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}], model="m"))
        assert response.finish_reason in {"stop", "tool_calls"}
        assert len(mock_openai_server.recorded()) == before + 2, "expected exactly one retry"
        assert p.retries == 1 and p.attempts == 2

    def test_a_non_retryable_status_raises_with_the_upstream_detail(self, server, base_url) -> None:
        class Forbidden(mock_openai_server.Handler):
            def do_POST(self):  # noqa: N802
                self._json(403, {"error": {"message": "model not available"}})

        httpd, url = serve_class(Forbidden)
        try:
            with pytest.raises(ProviderError) as excinfo:
                provider(url, max_attempts=4).chat(ChatRequest(messages=[{"role": "user", "content": "x"}], model="m"))
            assert excinfo.value.status == 403
            assert excinfo.value.retryable is False
            assert "model not available" in str(excinfo.value)
        finally:
            httpd.shutdown()

    def test_an_unreachable_base_url_is_a_retryable_transport_error(self) -> None:
        p = OpenAICompatProvider(base_url="http://127.0.0.1:1", api_key="k", max_attempts=2, timeout_s=1.0)
        with pytest.raises(ProviderError) as excinfo:
            p.chat(ChatRequest(messages=[{"role": "user", "content": "x"}], model="m"))
        assert excinfo.value.retryable is True


class TestCacheOnTheWire:
    def test_a_second_identical_call_never_touches_the_socket(self, base_url, tmp_path) -> None:
        p = provider(base_url, cache=ResponseCache(tmp_path / "c"))
        request = ChatRequest(messages=[{"role": "user", "content": "cached please"}], model="m")
        first = p.chat(request)
        calls_after_first = len(mock_openai_server.recorded())
        second = p.chat(request)
        assert second.cached is True
        assert len(mock_openai_server.recorded()) == calls_after_first, "cache hit must not re-request"
        assert second.usage.total_tokens == 0, "a replayed call was already paid for"
        assert first.usage.total_tokens > 0

    def test_changing_the_prompt_invalidates_the_key(self, base_url, tmp_path) -> None:
        p = provider(base_url, cache=ResponseCache(tmp_path / "c"))
        p.chat(ChatRequest(messages=[{"role": "user", "content": "one"}], model="m"))
        before = len(mock_openai_server.recorded())
        p.chat(ChatRequest(messages=[{"role": "user", "content": "two"}], model="m"))
        assert len(mock_openai_server.recorded()) == before + 1


class TestFullAgentOverHttp:
    """The whole loop against a real socket: this is the DeepSeek code path, minus DeepSeek."""

    def _agent(self, base_url, *, scenario_id: str, cache_dir=None):
        scenario = by_id(scenario_id)
        world = scenario.build_world()
        kb = KnowledgeBase.from_dir()
        ctx = RunContext(task_id=scenario.id, arm="http", world=world, sop=kb, hitl_mode="scripted", hitl_script={"issue_refund": bool(scenario.expect.get("hitl"))}, scratch=ScratchStore())
        config = AgentConfig(
            provider=provider(base_url, cache=ResponseCache(cache_dir) if cache_dir else None),
            toolkit=Toolkit(build_desk_tools(ctx)),
            model="mock-chat",
            pricing=Pricing(input_per_m=1000.0, cached_per_m=0.0, output_per_m=1000.0),
            context=ContextPolicy(),
            budget=RunBudget(max_cost=50.0, max_steps=30, max_prompt_tokens=40_000),
            critic_rounds=0,
            enable_sop_briefing=False,
        )
        return Agent(config, world=world, kb=kb), ctx, scenario

    def test_a_run_through_http_grades_clean(self, base_url) -> None:
        scenario_id = "S01_inwindow_refund"
        agent, ctx, scenario = self._agent(base_url, scenario_id=scenario_id)
        result = agent.run(scenario.brief, task_id=scenario.id, arm="http", ctx=ctx)
        assert result.status == "ok", result.error
        graded = grade(scenario, agent.world, sop_ids=agent.kb.section_ids(), events=result.events)
        assert graded.ok, graded.failed
        assert result.usage.input_tokens > 0 and result.cost > 0
        assert any(e["type"] == "tool_call" for e in result.events)

    def test_the_loop_drives_multiple_round_trips_over_http(self, base_url) -> None:
        # The mock double is not a competent policy — it always claims no_reason — so
        # this asserts the transport, not the judgement: a real socket conversation with
        # several tool round trips, structured results coming back, and usage metered.
        mock_openai_server.Handler.flaky_left = 0
        agent, ctx, scenario = self._agent(base_url, scenario_id="S04_missing_item")
        result = agent.run(scenario.brief, task_id=scenario.id, arm="http", ctx=ctx)
        names = [e["payload"]["name"] for e in result.events if e["type"] == "tool_call"]
        assert len(names) >= 4, names
        assert names[0] == "get_ticket" and "compute_refund" in names
        assert result.usage.input_tokens > 0
        # one model call per tool step plus the closing answer
        assert result.usage.calls == len(names) + 1
        assert mock_openai_server.recorded(), "requests should have reached the socket"
        assert all(r["auth"] == "Bearer test-key" for r in mock_openai_server.recorded())
        assert result.steps == len(names) + 1

    def test_prompt_cache_savings_are_visible_in_cost(self, base_url, tmp_path) -> None:
        # Warm the cache once, then replay: same run, identical trace, zero token cost.
        cold, ctx, scenario = self._agent(base_url, scenario_id="S01_inwindow_refund", cache_dir=tmp_path / "c")
        cold_result = cold.run(scenario.brief, task_id=scenario.id, arm="http", ctx=ctx)
        cold_cost = cold_result.cost
        assert cold_cost > 0

        warm_agent, warm_ctx, _ = self._agent(base_url, scenario_id="S01_inwindow_refund", cache_dir=tmp_path / "c")
        warm_result = warm_agent.run(scenario.brief, task_id=scenario.id, arm="http", ctx=warm_ctx)
        assert warm_result.usage.input_tokens == 0, "every call should have been a cache hit"
        assert warm_result.cost == pytest.approx(0.0)
        assert [e["payload"].get("name") for e in warm_result.events if e["type"] == "tool_call"] == [
            e["payload"].get("name") for e in cold_result.events if e["type"] == "tool_call"
        ]

