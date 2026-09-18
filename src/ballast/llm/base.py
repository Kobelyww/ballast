"""Provider-agnostic chat layer: the only vocabulary the rest of the runtime speaks.

Wire format is OpenAI-compatible `/chat/completions` because that is the lingua
franca across DeepSeek, Qwen, GLM, vLLM and Ollama. Nothing above this module
imports a vendor SDK.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments, ensure_ascii=False)},
        }


@dataclass(slots=True)
class Usage:
    """`cached_input_tokens` is first-class: prompt-cache hits are priced differently,
    and 'did context reuse actually pay' is a question this project has to answer."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def uncached_input_tokens(self) -> int:
        return max(self.input_tokens - self.cached_input_tokens, 0)

    def cost(self, pricing: "Pricing") -> float:
        return (
            self.uncached_input_tokens / 1e6 * pricing.input_per_m
            + min(self.cached_input_tokens, self.input_tokens) / 1e6 * pricing.cached_per_m
            + self.output_tokens / 1e6 * pricing.output_per_m
        )

    def merge(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cached_input_tokens + other.cached_input_tokens,
            self.calls + other.calls,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.calls,
        }


@dataclass(slots=True)
class Pricing:
    """Per-million-token rates in the model's own billing currency."""

    input_per_m: float = 2.0
    cached_per_m: float = 0.5
    output_per_m: float = 8.0
    currency: str = "CNY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_per_m": self.input_per_m,
            "cached_per_m": self.cached_per_m,
            "output_per_m": self.output_per_m,
            "currency": self.currency,
        }


DEEPSEEK_CHAT = Pricing(input_per_m=2.0, cached_per_m=0.5, output_per_m=8.0, currency="CNY")
DEEPSEEK_REASONER = Pricing(input_per_m=4.0, cached_per_m=1.0, output_per_m=16.0, currency="CNY")


@dataclass(slots=True)
class ChatRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    temperature: float = 0.0
    seed: int | None = None
    max_tokens: int | None = None
    tool_choice: Literal["auto", "none", "required"] = "auto"

    def cache_key(self) -> str:
        payload = json.dumps(
            {
                "m": self.model,
                "t": self.temperature,
                "s": self.seed,
                "x": self.max_tokens,
                "c": self.tool_choice,
                "msgs": self.messages,
                "tools": self.tools,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"
    cached: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def as_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [tc.as_dict() for tc in self.tool_calls]
        return msg


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class Provider(Protocol):
    name: str

    def chat(self, request: ChatRequest) -> ChatResponse: ...


def tool_message(call_id: str, name: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


def user_message(content: str) -> dict[str, Any]:
    return {"role": "user", "content": content}


def system_message(content: str) -> dict[str, Any]:
    return {"role": "system", "content": content}
