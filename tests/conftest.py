"""Shared fixtures and helpers for the ballast test suite.

Two rules the helpers encode:

* every scripted tool call gets a *unique* call id, because the agent loop keys its
  idempotency memo on `(run_id, call_id)` and reusing an id silently replays an
  earlier result instead of executing the new call;
* anything a run touches (scratch store, sqlite databases, cache dirs) lives under
  `tmp_path`, so the suite leaves nothing behind.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ballast.bench.graders import Grade  # noqa: E402
from ballast.bench.runner import resolve_arm, run_scenario  # noqa: E402
from ballast.context.engine import ContextPolicy  # noqa: E402
from ballast.env.fixtures import Scenario, by_id, train_slice  # noqa: E402
from ballast.env.knowledge import KnowledgeBase  # noqa: E402
from ballast.kernel.agent import Agent, AgentConfig, RunResult  # noqa: E402
from ballast.kernel.budget import RunBudget  # noqa: E402
from ballast.kernel.events import RunContext
from ballast.kernel.verify import audit as desk_audit  # noqa: E402


def _ticket(run_ctx: object) -> str | None:
    task_id = str(getattr(run_ctx, "task_id", "") or "")
    return task_id if task_id.startswith("T") else None
from ballast.kernel.toolkit import Toolkit  # noqa: E402
from ballast.llm.base import ChatResponse, ToolCall, Usage  # noqa: E402
from ballast.llm.surrogate import ScriptedModel  # noqa: E402
from ballast.support.text import ScratchStore  # noqa: E402
from ballast.tools.desk import build_desk_tools  # noqa: E402

# A summary that satisfies `close_ticket`'s quality check for the SOP as shipped.
GOOD_SUMMARY = "依据 refund_policy::质量问题退款 核定退款 ¥459.00（含运费 12.00），已执行放款并结单。"


def call_step(index: int, name: str, /, **arguments: Any) -> ChatResponse:
    """One scripted assistant turn that requests exactly one tool call."""
    return ChatResponse(
        tool_calls=[ToolCall(id=f"call_{index}", name=name, arguments=arguments)],
        usage=Usage(input_tokens=500, output_tokens=30, calls=1),
        finish_reason="tool_calls",
    )


def say(text: str) -> ChatResponse:
    """A scripted final, tool-free turn."""
    return ChatResponse(content=text, usage=Usage(input_tokens=500, output_tokens=20, calls=1), finish_reason="stop")


def s03_plan(summary: str = GOOD_SUMMARY, *, amount: float = 459.0, claim: str = "quality") -> list[ChatResponse]:
    """The canonical 'read, compute, pay, close' trace for S03_quality_with_shipping."""
    return [
        call_step(1, "get_ticket", ticket_id="T1044"),
        call_step(2, "get_order", order_id="SO20261044"),
        call_step(3, "get_customer", customer_id="C102"),
        call_step(4, "search_sop", query="退款 无理由 政策 窗口 计算"),
        call_step(5, "compute_refund", order_id="SO20261044", claim_type=claim),
        call_step(6, "issue_refund", order_id="SO20261044", amount=amount, reason=claim),
        call_step(7, "close_ticket", ticket_id="T1044", resolution="refunded", summary=summary),
        say("已完成退款"),
    ]


class Harness:
    """A run_scenario-alike that drives the real desk tools with a ScriptedModel."""

    def __init__(self, scenario: Scenario | str, **config: Any) -> None:
        self.scenario = by_id(scenario) if isinstance(scenario, str) else scenario
        self.world = self.scenario.build_world()
        self.kb = config.pop("kb", None) or KnowledgeBase.from_dir()
        self.scratch: ScratchStore = config.pop("scratch", None) or ScratchStore()
        self.ctx = RunContext(
            task_id=self.scenario.id,
            arm=config.pop("arm", "scripted"),
            world=self.world,
            sop=self.kb,
            hitl_mode=config.pop("hitl_mode", "scripted"),
            hitl_script=config.pop("hitl_script", {"issue_refund": True}),
        )
        self.ctx.scratch = self.scratch
        self.provider: ScriptedModel = config.pop("provider", None) or ScriptedModel([])
        self.config = AgentConfig(
            provider=self.provider,
            toolkit=Toolkit(build_desk_tools(self.ctx)),
            context=ContextPolicy(**config.pop("context", {})),
            budget=RunBudget(**config.pop("budget", {})),
            # This harness is desk-only, so the desk invariants are the default here;
            # production callers wire their own (see bench/runner.run_scenario).
            invariant_check=config.pop("invariant_check", lambda w, run=None: desk_audit(w, sop_ids=self.kb.section_ids(), ticket_id=_ticket(run))),
            **config,
        )
        self.agent = Agent(self.config, world=self.world, kb=self.kb)

    def load(self, script: list[ChatResponse]) -> None:
        """Swap in a new turn script and rewind the replay cursor."""
        self.provider.steps = list(script)
        self.provider.index = 0

    def run(self, script: list[ChatResponse] | None = None) -> RunResult:
        if script is not None:
            self.load(script)
        return self.agent.run(self.scenario.brief, task_id=self.scenario.id, arm=self.ctx.arm, ctx=self.ctx)


_LOCALHOST = {"127.0.0.1", "::1", "localhost"}


def _is_loopback(target: Any) -> bool:
    if isinstance(target, (tuple, list)) and target:
        return str(target[0]) in _LOCALHOST
    if isinstance(target, str):
        host = target.split("://", 1)[-1].split("/")[0].split(":")[0]
        return host in _LOCALHOST
    return False


@pytest.fixture(autouse=True)
def forbid_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ballast's test suite is offline by contract.

    A test that reaches for the internet can bill money or flake, so the syscall is
    blocked for every test rather than trusted to discipline. Loopback stays open: the
    OpenAI-compatible transport is only genuinely tested against a real socket, and
    `scripts/mock_openai_server.py` is that socket. Anything not addressed to
    127.0.0.1 still raises.
    """
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def connect(self: Any, target: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_loopback(target):
            raise AssertionError(f"external network access is forbidden in the ballast test suite (tried {target!r})")
        return real_connect(self, target, *args, **kwargs)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_loopback(address):
            raise AssertionError(f"external network access is forbidden in the ballast test suite (tried {address!r})")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)


@pytest.fixture
def harness() -> Any:
    return Harness


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    return KnowledgeBase.from_dir()


def assert_tool_calls_answered(messages: list[dict[str, Any]]) -> None:
    """Every assistant `tool_calls` message must be followed, immediately, by one tool
    reply per call id. A transcript that breaks this is rejected by every real
    OpenAI-compatible endpoint, so compaction must never produce one."""
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            continue
        needed = {c["id"] for c in msg["tool_calls"]}
        answered: set[str] = set()
        for follow in messages[i + 1 :]:
            if follow.get("role") != "tool":
                break
            answered.add(follow["tool_call_id"])
        assert needed <= answered, f"assistant tool_calls at {i} lost its replies (missing {needed - answered})"
    orphan = [m.get("tool_call_id") for m in messages if m.get("role") == "tool" and not _declared(m, messages)]
    assert not orphan, f"tool replies with no matching call: {orphan}"


def _declared(tool_msg: dict[str, Any], messages: list[dict[str, Any]]) -> bool:
    return any(
        any(call.get("id") == tool_msg.get("tool_call_id") for call in (m.get("tool_calls") or []))
        for m in messages
        if m.get("role") == "assistant"
    )


@pytest.fixture(scope="session")
def train_runs() -> list[tuple[Scenario, Any, Grade, dict[str, Any]]]:
    """The whole train slice under the `ballast` arm, executed once per pytest session."""
    arm = resolve_arm("ballast")
    out = []
    for scenario in train_slice():
        row, grade, extras = run_scenario(scenario, arm)
        out.append((scenario, row, grade, extras))
    return out


#: Tasks the controlled arm is *known* not to finish. The list used to hold
#: S17_fat_order and S18_batch_queue, both of which died with `stalled`; they now pass.
#: What the 12/16/24/36/48-ticket ladder actually exposed was a mismatch inside the
#: harness's own evidence model: compaction folds a tool result but keeps a
#: `- invoked search_sop(...)` line in the digest, so the run knew it had searched and
#: could no longer see the section id it was required to quote. `close_ticket` refused
#: the summary, the repeat guard refused the retry, and the run stopped. Reading the
#: digest for reads (not effects) and re-fetching a citation the agent can no longer see
#: is what fixed it; the grader's habit of charging the run for pre-resolved decoy
#: tickets was a second, separate bug.
#: What remains is L48_batch, where both arms hit the shared ¥6 ceiling: the cheap arm
#: gets 39/48 tickets done, the naive arm 37/48. That is a result to publish, not a
#: cell to delete. Two test modules read this list; it lives here so they cannot drift.
HARD_TIER = {"L48_batch"}
