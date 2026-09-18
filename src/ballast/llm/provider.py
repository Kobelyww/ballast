"""OpenAI-compatible HTTP provider on the standard library only.

No SDK on purpose: the interesting parts — retry that never re-bills a completed
call, bounded in-flight concurrency, and reading the *vendor-specific* usage
fields that decide whether prompt caching paid off — are all things an SDK hides.
Zero dependencies also means the whole eval suite runs in a bare CI container.
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from .base import ChatRequest, ChatResponse, ProviderError, ToolCall, Usage
from .cache import ResponseCache

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        *,
        base_url: str = "https://api.deepseek.com",
        api_key: str = "",
        model: str = "deepseek-chat",
        timeout_s: float = 90.0,
        max_concurrency: int = 6,
        max_attempts: int = 4,
        cache: ResponseCache | None = None,
        temperature: float = 0.0,
        seed: int | None = 7,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("api_key is empty; set BALLAST_LLM_API_KEY or use a surrogate provider")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.cache = cache
        self.temperature = temperature
        self.seed = seed
        self._sem = threading.Semaphore(max(1, max_concurrency))
        self._headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", **(extra_headers or {})}
        self.attempts = 0
        self.retries = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        request.model = request.model or self.model
        if request.temperature is None:
            request.temperature = self.temperature
        if request.seed is None:
            request.seed = self.seed
        key = request.cache_key()
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return hit

        body = self._body(request)
        with self._sem:
            payload = self._post(body)
        parsed = self._parse(payload, model=request.model)
        if self.cache is not None and parsed.finish_reason not in {"content_filter", "error"}:
            self.cache.put(key, parsed, request=request)
        return parsed

    def _body(self, request: ChatRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": False,
        }
        if request.seed is not None:
            body["seed"] = request.seed
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        if request.tools:
            body["tools"] = request.tools
            body["tool_choice"] = request.tool_choice
        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        last: ProviderError | None = None
        for attempt in range(self.max_attempts):
            self.attempts += 1
            if attempt:
                self.retries += 1
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    headers=self._headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    raw = resp.read().decode("utf-8")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    last = ProviderError(f"malformed upstream JSON: {raw[:200]}", retryable=True)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:400]
                except Exception:  # noqa: BLE001 - the status code is what matters
                    pass
                retryable = exc.code in RETRYABLE_STATUS
                last = ProviderError(f"upstream {exc.code}: {detail}", status=exc.code, retryable=retryable)
                if not retryable:
                    raise last from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = ProviderError(f"transport error: {exc}", retryable=True)
            time.sleep(min(8.0, (1.2 * (2**attempt)) * (0.6 + random.random() * 0.8)))
        raise last or ProviderError("exhausted attempts", retryable=True)

    @staticmethod
    def _parse(payload: dict[str, Any], *, model: str = "") -> ChatResponse:
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            fn = item.get("function") or {}
            arguments = fn.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    parsed_args = json.loads(arguments) if arguments.strip() else {}
                except json.JSONDecodeError:
                    parsed_args = {"_raw": arguments}
            else:
                parsed_args = dict(arguments)
            if not isinstance(parsed_args, dict):
                parsed_args = {"_raw": json.dumps(parsed_args, ensure_ascii=False)}
            calls.append(ToolCall(id=item.get("id") or f"call_{len(calls)}", name=fn.get("name", ""), arguments=parsed_args))
        usage_raw = payload.get("usage") or {}
        details = usage_raw.get("prompt_tokens_details") or {}
        cached = int(usage_raw.get("prompt_cache_hit_tokens") or details.get("cached_tokens") or 0)
        usage = Usage(
            input_tokens=int(usage_raw.get("prompt_tokens") or usage_raw.get("input_tokens") or 0),
            output_tokens=int(usage_raw.get("completion_tokens") or usage_raw.get("output_tokens") or 0),
            cached_input_tokens=cached,
            calls=1,
        )
        return ChatResponse(
            content=message.get("content"),
            tool_calls=calls,
            usage=usage,
            finish_reason=choice.get("finish_reason") or "stop",
            raw={"model": payload.get("model", model)},
        )


def deepseek(**kwargs: Any) -> OpenAICompatProvider:
    kwargs.setdefault("base_url", "https://api.deepseek.com")
    kwargs.setdefault("model", "deepseek-chat")
    return OpenAICompatProvider(**kwargs)
