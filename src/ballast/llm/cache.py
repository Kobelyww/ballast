"""Content-addressed response cache.

Two jobs: keep eval re-runs from re-billing identical requests, and make retries
safe. The key covers model + sampling params + the full message list + tool
schemas, so a hit is a genuinely identical request rather than a fuzzy match.

Cached responses replay with `cached=True` and *zero* usage: the cost of a hit is
the cost of a file read, and accounting that ignored that would overstate spend.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .base import ChatResponse, ToolCall, Usage


class ResponseCache:
    def __init__(self, root: Path | str, *, enabled: bool = True, namespace: str = "") -> None:
        self.root = Path(root)
        self.enabled = enabled
        self.namespace = namespace
        self.hits = 0
        self.misses = 0

    def path_for(self, key: str) -> Path:
        prefix = f"{self.namespace}_" if self.namespace else ""
        return self.root / key[:2] / f"{prefix}{key}.json"

    def get(self, key: str) -> ChatResponse | None:
        if not self.enabled:
            return None
        path = self.path_for(key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.misses += 1
            return None
        self.hits += 1
        return _deserialize(payload)

    def put(self, key: str, response: ChatResponse, *, request: Any = None) -> None:
        if not self.enabled:
            return
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stored_at": time.time(),
            "content": response.content,
            "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls],
            "usage": response.usage.as_dict(),
            "finish_reason": response.finish_reason,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}


def _deserialize(payload: dict[str, Any]) -> ChatResponse:
    usage = payload.get("usage", {})
    return ChatResponse(
        content=payload.get("content"),
        tool_calls=[
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments") or {})
            for tc in payload.get("tool_calls", [])
        ],
        # A replayed call was already paid for; charging it again would double-count.
        usage=Usage(input_tokens=0, output_tokens=0, cached_input_tokens=0, calls=1),
        finish_reason=payload.get("finish_reason", "stop"),
        cached=True,
    )
