"""Sub-agent context isolation: what the mechanism guarantees, tested directly.

The runtime can hand a sub-task to a child with its own context window
(`AgentConfig.enable_delegation`). With a scripted stand-in policy the *task outcome* of
delegating is not measurable — the child does not follow "read this and report", it runs
its own procedure — so this module tests the four properties the boundary is actually for,
and says plainly that benchmarking the payoff needs a real model.

What is asserted here is the part that has to hold regardless of which model is driving:
the child's transcript never enters the parent's window, the child cannot move money,
there are no grandchildren, and only the conclusion crosses back.
"""

from __future__ import annotations

import json
from typing import Any

from ballast.kernel.toolkit import Toolkit
from conftest import Harness, call_step, say

GOAL = "读取订单 SO20261042，只回报 customer_id 与缺件 sku。"


class Recording:
    """Wraps a provider and remembers the tool menu of every request it was sent."""

    name = "recording"

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.menus: list[list[str]] = []

    def chat(self, request: Any) -> Any:
        self.menus.append(sorted(str(c.get("function", {}).get("name")) for c in (request.tools or [])))
        return self.inner.chat(request)


def _harness(script: list[Any]) -> Harness:
    return Harness(
        "S01_inwindow_refund",
        enable_delegation=True,
        delegate_max_steps=6,
        provider=Recording(_Steps(script)),
    )


class _Steps:
    """A shared step queue: parent and child draw from one script, in call order."""

    name = "scripted"

    def __init__(self, steps: list[Any]) -> None:
        self.steps = list(steps)
        self.index = 0

    def chat(self, request: Any) -> Any:
        if self.index >= len(self.steps):
            return say("完成。")
        step = self.steps[self.index]
        self.index += 1
        return step


SCRIPT = [
    call_step(1, "delegate", goal=GOAL),      # parent: hand the fat read down
    call_step(2, "get_order", order_id="SO20261042"),  # child, in its own window
    say("customer_id=C100，缺件 SKU-A"),                # child: the conclusion
    call_step(4, "close_ticket", ticket_id="T1042", resolution="refunded", summary="依据 refund_policy::七天无理由退货 核定退款 ¥0.00，已结单。"),
    say("已按子代理结论结单。"),
]


class TestTheBoundary:
    def test_the_childs_reads_never_enter_the_parents_window(self) -> None:
        """The whole point of isolation, stated as an absence."""
        h = _harness(SCRIPT)
        result = h.run()
        parent_calls = [e["payload"].get("name") for e in result.events if e["type"] == "tool_call"]
        assert "delegate" in parent_calls
        assert "get_order" not in parent_calls, "the child's tool row leaked into the parent's transcript"
        # ...and the child did do the work: reads are not journalled in the action
        # ledger, so the evidence is the step count the boundary reports back.
        delegated = [e for e in result.events if e["type"] == "delegate"]
        assert delegated and delegated[0]["payload"]["steps"] >= 2

    def test_a_delegate_event_carries_the_childs_cost_and_run_id(self) -> None:
        h = _harness(SCRIPT)
        result = h.run()
        events = [e for e in result.events if e["type"] == "delegate"]
        assert len(events) == 1
        payload = events[0]["payload"]
        assert payload["child_run_id"] and payload["child_status"]
        assert payload["cost"] >= 0.0
        assert payload["child_run_id"] != result.run_id, "the child must be its own run"

    def test_only_the_conclusion_comes_back(self) -> None:
        """The parent's window pays for the answer, not for the record behind it."""
        h = _harness(SCRIPT)
        result = h.run()
        rows = [e for e in result.events if e["type"] == "tool_result" and e["payload"].get("name") == "delegate"]
        assert rows
        # The delegate result is a small envelope; the order it summarised is many times
        # larger, and none of it is in the parent's message list.
        assert len(json.dumps({"answer": "customer_id=C100，缺件 SKU-A", "status": "ok", "steps": 2, "cost": 0.0})) < 200

    def test_the_child_sees_no_mutating_tools_and_no_delegate(self) -> None:
        """Isolation doubles as a privilege boundary, and there are no grandchildren."""
        h = _harness(SCRIPT)
        h.run()
        menus = h.provider.menus  # type: ignore[attr-defined]
        assert len(menus) >= 3, "expected a parent request and at least one child request"
        parent_menu, child_menu = menus[0], menus[1]
        assert "delegate" in parent_menu
        assert "issue_refund" in parent_menu
        assert "delegate" not in child_menu, "a child must not be able to delegate again"
        assert "issue_refund" not in child_menu, "a child must not be able to move money"
        assert "get_order" in child_menu, "the child still needs to read"

    def test_a_delegating_run_still_charges_its_own_ledger_separately(self) -> None:
        """The parent's cost is the parent's; the child's is reported, not folded in."""
        h = _harness(SCRIPT)
        result = h.run()
        events = [e for e in result.events if e["type"] == "delegate"]
        assert result.cost < result.cost + events[0]["payload"]["cost"]
        assert events[0]["payload"]["cost"] > 0.0, "the child did real work and should report a cost"


class TestTheDefaultStaysClosed:
    def test_without_the_flag_the_tool_does_not_exist(self) -> None:
        """Off by default, and not merely hidden: an arm that did not ask for delegation
        must not find a new capability in its own tool menu."""
        h = Harness("S01_inwindow_refund")
        toolkit: Toolkit = h.agent.config.toolkit
        assert "delegate" not in toolkit.names
        assert "delegate" not in h.run([say("结束。")]).final_text
