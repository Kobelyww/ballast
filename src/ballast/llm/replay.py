"""Record-and-replay provider: CI that cannot silently spend money.

`--record` writes every real upstream response to a content-addressed store; the
default CI mode reads from that same store and **raises on a miss** instead of
quietly hitting the network. Two consequences worth having:

* a test that needs an LLM is reproducible in a sandbox with no egress and no key;
* changing the prompt changes the cache key, so a stale fixture fails loudly rather
  than replaying an answer that no longer matches the request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import ChatRequest, ChatResponse, ProviderError, ToolCall, Usage
from .cache import ResponseCache


class ReplayMiss(ProviderError):
    pass


class ReplayProvider:
    """Read-only view over a ResponseCache. Never touches the network."""

    name = "replay"

    def __init__(self, root: Path | str, *, model: str = "replayed") -> None:
        self.cache = ResponseCache(Path(root))
        self.model = model
        self.misses: list[str] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        key = request.cache_key()
        hit = self.cache.get(key)
        if hit is None:
            self.misses.append(key)
            raise ReplayMiss(
                f"no recorded response for request {key[:12]}… "
                f"(prompt changed, or this run was never recorded under {self.cache.root}); "
                "re-record with `ballast eval --record`"
            )
        return hit

    def keys(self) -> list[str]:
        return sorted(p.stem for p in self.cache.root.glob("*/*.json"))

    def __len__(self) -> int:
        return len(self.keys())


def export_fixture(cache_root: Path | str, out: Path | str) -> int:
    """Flatten a cache tree into one reviewable JSONL fixture, sorted by key."""
    cache = ResponseCache(Path(cache_root))
    lines = []
    for key in cache.keys() if hasattr(cache, "keys") else []:
        path = cache.path_for(key)
        lines.append(path.read_text(encoding="utf-8"))
    payload = "\n".join(lines)
    Path(out).write_text(payload, encoding="utf-8")
    return len(lines)


def load_fixture(path: Path | str) -> list[dict[str, Any]]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out


def response_from_fixture(record: dict[str, Any]) -> ChatResponse:
    usage = record.get("usage", {})
    return ChatResponse(
        content=record.get("content"),
        tool_calls=[ToolCall(id=t["id"], name=t["name"], arguments=t.get("arguments") or {}) for t in record.get("tool_calls", [])],
        usage=Usage(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
            calls=1,
        ),
        finish_reason=record.get("finish_reason", "stop"),
    )
