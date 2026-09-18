"""Fault attribution: when a run fails, say who failed and how.

Failures are classified from the event stream, not from a model's summary of what
went wrong, so the taxonomy is reproducible. This is what turns a benchmark score
into something actionable: "arm X lost 4 runs, 3 of them `wrong_argument`, 1 of them
`upstream_timeout` that the retry policy should have absorbed."
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

OWNER_BY_CODE = {
    "invalid_arguments": "agent",
    "unknown_tool": "agent",
    "missing_required_argument": "agent",
    "unknown_argument": "agent",
    "guardrail_block": "agent",
    "policy_denied": "agent",
    "premature_stop": "agent",
    "loop_detected": "agent",
    "budget_exhausted": "runtime",
    "upstream_timeout": "environment",
    "not_found": "environment",
    "tool_crashed": "runtime",
    "no_action_taken": "agent",
    "hallucinated_id": "agent",
}


@dataclass(slots=True)
class Fault:
    code: str
    owner: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "owner": self.owner, "detail": self.detail}


def attribute(events: Sequence[dict[str, Any]], *, steps: int, status: str) -> list[Fault]:
    faults: list[Fault] = []
    seen_calls: Counter[str] = Counter()

    for event in events:
        payload = event.get("payload", {}) or {}
        kind = event.get("type")
        if kind == "tool_rejected":
            for problem in payload.get("problems", []) or []:
                code = problem.split(":", 1)[0].strip()
                faults.append(Fault(code if code in OWNER_BY_CODE else "invalid_arguments", "agent", problem[:200]))
        elif kind == "guardrail_block":
            faults.append(Fault("guardrail_block", "agent", f"{payload.get('name')} blocked ({payload.get('code')})"))
        elif kind == "tool_result" and payload.get("ok") is False:
            code = str(payload.get("code") or "tool_error")
            if code in {"upstream_timeout"}:
                faults.append(Fault("upstream_timeout", "environment", str(payload.get("detail", ""))[:200]))
        elif kind == "tool_call":
            seen_calls[str(payload.get("name"))] += 1
        elif kind == "budget_abort":
            faults.append(Fault("budget_exhausted", "runtime", str(payload.get("detail", ""))[:200]))

    for name, count in seen_calls.items():
        if count >= 4:
            faults.append(Fault("loop_detected", "agent", f"{name} called {count} times"))

    if not seen_calls:
        faults.append(Fault("no_action_taken", "agent", "run produced no tool calls"))
    if status == "budget_aborted" and not any(f.code == "budget_exhausted" for f in faults):
        faults.append(Fault("budget_exhausted", "runtime", f"aborted after {steps} steps"))
    return faults


def summarise(faults: Sequence[Fault]) -> dict[str, Any]:
    by_owner = Counter(f.owner for f in faults)
    by_code = Counter(f.code for f in faults)
    return {"total": len(faults), "by_owner": dict(by_owner), "by_code": dict(by_code.most_common())}
