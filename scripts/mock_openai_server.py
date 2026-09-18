"""A local OpenAI-compatible server, so the real HTTP path is testable without a key.

The provider layer is where this project meets DeepSeek / Qwen / GLM / vLLM / Ollama,
and the parts that matter — the auth header, the request body shape, `tool_calls`
arguments arriving as a JSON *string*, `prompt_cache_hit_tokens` accounting, and a 429
that must be retried without double-billing — are exactly the parts a static parse unit
test cannot prove.

Run it yourself and point a real agent at it, no credentials involved:

    python scripts/mock_openai_server.py --port 8099          # terminal 1
    BALLAST_LLM_API_KEY=mock ballast eval --provider openai-compat \\
        --model mock-chat   # terminal 2

Behaviour is deterministic for a fixed seed, and every request is recorded so tests can
assert what actually went over the wire.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TICKET_RE = re.compile(r"(T\d{4})")

# A hand-written procedure, expressed the way a model would express it: as decisions
# over the messages it was sent. Same shape as llm/surrogate.py, but reached through
# HTTP so the transport, not the policy, is under test.
def decide(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages") or []
    blob = " ".join(str(m.get("content", "")) for m in messages)
    role_names = {str(m.get("name", "")) for m in messages if m.get("role") == "tool"}

    def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": f"call_{name}_{len(role_names)}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}],
        }

    ticket = (TICKET_RE.search(blob) or [None, None])[1] if TICKET_RE.search(blob) else None
    if ticket and "get_ticket" not in role_names:
        return call("get_ticket", {"ticket_id": ticket})
    order = next((m for m in messages if m.get("role") == "tool" and m.get("name") == "get_ticket"), None)
    order_id = None
    if order:
        try:
            order_id = json.loads(order["content"]).get("order_id")
        except (json.JSONDecodeError, AttributeError):
            order_id = None
    if order_id and "get_order" not in role_names:
        return call("get_order", {"order_id": order_id})
    if "search_sop" not in role_names:
        return call("search_sop", {"query": "退款 无理由 政策 窗口", "top_k": 2})
    if order_id and "compute_refund" not in role_names:
        return call("compute_refund", {"order_id": order_id, "claim_type": "no_reason"})
    computed = next((m for m in messages if m.get("role") == "tool" and m.get("name") == "compute_refund"), None)
    decision: dict[str, Any] = {}
    if computed:
        try:
            decision = json.loads(computed["content"])
        except json.JSONDecodeError:
            decision = {}
    amount = float(decision.get("amount") or 0.0)
    if decision.get("allowed") and order_id and "issue_refund" not in role_names:
        return call("issue_refund", {"order_id": order_id, "amount": amount, "reason": "no_reason"})
    if ticket and "close_ticket" not in role_names:
        return call(
            "close_ticket",
            {
                "ticket_id": ticket,
                "resolution": "refunded" if amount else "rejected_by_policy",
                "summary": f"客户诉求处理完毕，政策依据 refund_policy::七天无理由退货，执行金额 ¥{amount:.2f}。",
            },
        )
    return {"role": "assistant", "content": f"完成：核定金额 ¥{amount:.2f}。"}


class Handler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    lock = threading.Lock()
    flaky_left = 1  # one 429 then success, to exercise the retry path

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "invalid json"}})
            return
        with self.lock:
            self.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})

        if self.path != "/chat/completions":
            self._json(404, {"error": {"message": f"no route {self.path}"}})
            return
        if not (self.headers.get("Authorization") or "").startswith("Bearer "):
            self._json(401, {"error": {"message": "missing bearer token"}})
            return
        if type(self).flaky_left > 0:
            with self.lock:
                type(self).flaky_left -= 1
            self._json(429, {"error": {"message": "rate limited"}}, retry_after="0")
            return

        message = decide(body)
        prompt_tokens = sum(len(str(m)) for m in body.get("messages", [])) // 4
        completion_tokens = len(json.dumps(message, ensure_ascii=False)) // 4
        self._json(
            200,
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": body.get("model", "mock-chat"),
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                # Both spellings of the cache field, because vendors disagree about it.
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "prompt_tokens_details": {"cached_tokens": int(prompt_tokens * 0.5)},
                },
            },
        )

    def _json(self, status: int, payload: dict[str, Any], retry_after: str | None = None) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if retry_after is not None:
            self.send_header("Retry-After", retry_after)
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args: Any) -> None:  # silence the default stderr noise
        pass


def serve(port: int = 0, *, shared: bool = False) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the server; returns (server, thread). `server.shutdown()` to stop."""
    if shared:  # keep the 429 budget across tests
        Handler.flaky_left = 0
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def recorded() -> list[dict[str, Any]]:
    with Handler.lock:
        return list(Handler.requests)


def reset() -> None:
    with Handler.lock:
        Handler.requests.clear()
        Handler.flaky_left = 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    Handler.flaky_left = 0
    httpd, _ = serve(args.port)
    print(f"mock OpenAI-compatible server on http://127.0.0.1:{args.port}")
    print(f'try: BALLAST_LLM_API_KEY=mock BALLAST_LLM_BASE_URL=http://127.0.0.1:{args.port} python -m ballast.cli eval --provider openai-compat --model mock-chat')
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        httpd.shutdown()
