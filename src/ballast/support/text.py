"""CJK-aware token estimation and content-addressed overflow storage.

Two primitives the context engine is built on:

* an estimator cheap enough to run *before* every request, so the runtime can
  decide whether the prompt is over budget instead of discovering it in a 400;
* a handle-based blob store that keeps oversized tool outputs reachable without
  letting them squat in the transcript forever.

Weights are calibrated against DeepSeek's tokenizer behaviour (roughly one token
per CJK character, ~3.5 ASCII characters per token), which is close enough for
budgeting on any BPE tokenizer without shipping one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CJK_WEIGHT = 1.0
ASCII_DIVISOR = 3.5
MESSAGE_FRAMING_TOKENS = 4


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
    )


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if is_cjk(ch))
    return int(cjk * CJK_WEIGHT + (len(text) - cjk) / ASCII_DIVISOR) + 1


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        total += MESSAGE_FRAMING_TOKENS
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif content is not None:
            total += estimate_tokens(json.dumps(content, ensure_ascii=False))
        for call in msg.get("tool_calls") or []:
            fn = call.get("function", {})
            total += estimate_tokens(str(fn.get("name", "")))
            total += estimate_tokens(str(fn.get("arguments", "")))
        if msg.get("role") == "tool":
            total += estimate_tokens(str(msg.get("name", "")))
    return total


def estimate_request_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> int:
    total = estimate_message_tokens(messages)
    if tools:
        total += estimate_tokens(json.dumps(tools, ensure_ascii=False, sort_keys=True))
    return total


def clip_to_tokens(text: str, budget: int) -> str:
    """Best-effort truncation to `budget` estimated tokens, cutting at a line edge."""
    if estimate_tokens(text) <= budget:
        return text
    approx_chars = int(budget * ASCII_DIVISOR)
    out = text[:approx_chars]
    while out and estimate_tokens(out) > budget:
        out = out[: -max(1, len(out) // 16)]
    edge = out.rfind("\n")
    return out[:edge] if edge > len(out) * 0.6 else out


class ScratchStore:
    """Overflow store for oversized tool results. Handles are stable and re-readable."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else None
        self._mem: dict[str, str] = {}
        self.writes = 0
        self.reads = 0
        self.bytes_stored = 0
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)

    def put(self, label: str, payload: str) -> str:
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)[:40]
        handle = f"scratch://{safe}-{digest}"
        if self.root:
            (self.root / f"{digest}.txt").write_text(payload, encoding="utf-8")
        else:
            self._mem[handle] = payload
        self.writes += 1
        self.bytes_stored += len(payload)
        return handle

    def get(self, handle: str) -> str | None:
        if not handle.startswith("scratch://"):
            return None
        self.reads += 1
        if self.root:
            path = self.root / f"{handle.rsplit('-', 1)[-1]}.txt"
            return path.read_text(encoding="utf-8") if path.exists() else None
        return self._mem.get(handle)

    def stats(self) -> dict[str, int]:
        return {"writes": self.writes, "reads": self.reads, "bytes_stored": self.bytes_stored}
