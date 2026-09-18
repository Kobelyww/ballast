"""Run-scoped state: the event stream that makes a run auditable.

Every decision-relevant occurrence is an append-only event with a step number, so a
run can be replayed, diffed against another run, or reconstructed after a crash.
The grader reads *world state*, not model prose — this stream is for the humans and
for the distiller that turns episodes into skills.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

EventType = Literal[
    "run_start",
    "skill_retrieved",
    "skill_applied",
    "plan",
    "plan_revised",
    "model_call",
    "model_error",
    "tool_call",
    "tool_result",
    "tool_rejected",
    "loop_guard",
    "guardrail_block",
    "offload",
    "compact",
    "approval_request",
    "approval_decision",
    "critic",
    "reflection",
    "user_turn",
    "budget_abort",
    "final",
    "error",
]

HitlMode = Literal["interrupt", "auto_approve", "auto_reject", "scripted"]


@dataclass(slots=True)
class RunEvent:
    type: EventType
    step: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "step": self.step, "ts": round(self.ts, 4), "payload": self.payload}


@dataclass(slots=True)
class RunContext:
    """Everything a run touches that is not part of the message list."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    arm: str = ""
    events: list[RunEvent] = field(default_factory=list)
    subscribers: list[Callable[[RunEvent], None]] = field(default_factory=list)
    hitl_mode: HitlMode = "auto_approve"
    hitl_script: dict[str, bool] = field(default_factory=dict)
    computed: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    guardrail_blocks: int = 0
    rejected_calls: int = 0
    compactions: int = 0
    saved_tokens: int = 0
    critic_rounds: int = 0
    reflections: int = 0
    skills_retrieved: list[str] = field(default_factory=list)
    skills_applied: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    scratch: Any = None
    world: Any = None
    sop: Any = None
    ledger: Any = None
    pending_interrupt: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def emit(self, type_: EventType, **payload: Any) -> RunEvent:
        step = self.ledger.step(self.run_id) if self.ledger is not None else len(self.events)
        event = RunEvent(type=type_, step=step, payload=payload)
        self.events.append(event)
        for subscriber in self.subscribers:
            subscriber(event)
        return event

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def steps(self) -> int:
        return self.ledger.step(self.run_id) if self.ledger is not None else len(self.events)

    def of_type(self, *types: str) -> list[RunEvent]:
        return [e for e in self.events if e.type in types]

    def tool_names(self) -> list[str]:
        return [str(e.payload.get("name", "")) for e in self.of_type("tool_call")]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [event.as_dict() for event in self.events]
