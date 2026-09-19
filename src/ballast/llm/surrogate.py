"""Offline, deterministic stand-ins for a language model.

Read the name literally: these are **not** models and nothing measured through them
says anything about a real LLM's quality. They exist because two questions are
answerable without ever calling an API:

1. *Does the runtime behave correctly?* Tool validation, guardrails, budget aborts,
   compaction, checkpoint/resume and HITL are harness properties. A scripted policy
   turns them into assertions instead of vibes.
2. *What does each context-engineering choice cost?* The surrogate issues the same
   tool sequence for a given task no matter how the prompt was assembled, so a
   difference in prompt tokens, calls or wall time between two arms is attributable
   to the harness alone — with zero API spend, in CI, reproducibly.

The policy deliberately reads **only the context the harness gave it**: it locates
the ticket id, the order id, its SOP citation and its own earlier results by parsing
the message list. If compaction or offload removes something it needed, the run
degrades — which is the behaviour worth measuring.

`SurrogateProfile` makes competence a knob, so guardrail and repair mechanisms can be
ablated against a *known* defect rate instead of an unverifiable model opinion.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

from ..context.engine import FOLD_MARKER
from ..llm.base import ChatRequest, ChatResponse, ToolCall, Usage

#: Reads the compaction digest is allowed to vouch for. Deliberately side-effect free:
#: a folded line proves the agent *looked*, and a real model would act on that. It can
#: never prove the agent *paid* — crediting effects from a digest is how a run refunds
#: an order twice, which is the one mistake no amount of context engineering buys back.
_FOLD_CREDITED_READS = frozenset(
    {
        "list_tickets",
        "list_orders_by_phone",
        "get_ticket",
        "get_order",
        "get_customer",
        "search_sop",
        "compute_refund",
        "check_coupon_eligibility",
    }
)

_TICKET_RE = re.compile(r"(T\d{4})")
_OFFLOADED_RE = re.compile(r"output (\d+)t moved out of context -> (scratch://[^\s\]]+)", re.I)
_KEPT_RE = re.compile(r"^kept: (\{.*\})$", re.M)
_HANDLE_NAME_RE = re.compile(r"scratch://([a-z_]+)-")
_ORDER_RE = re.compile(r"(SO\d{6,})")
_PHONE_RE = re.compile(r"(1\d{2}\s\d{4}\s\d{4}|1\d{10})")
_ADDRESS_RE = re.compile(r"(?:改成|改为|新地址[是为:]*)\s*([^\s，。,;；]+)")
_SKU_RE = re.compile(r"(SKU-[A-Z0-9-]+)")
_MONEY_RE = re.compile(r"(\d{1,4})\s*元")

REFUND_WORDS = ("退款", "退货", "缺件", "少发", "质量", "坏了", "不想要", "无理由", "买错", "后悔", "不喜欢")
ADDRESS_WORDS = ("改地址", "改收货", "地址")
COUPON_WORDS = ("补偿", "优惠券", "补偿券", "安抚", "延误", "说法", "体验")


@dataclass(slots=True)
class SurrogateProfile:
    """How good the pretend model is, so guardrail ablations have a knob to turn."""

    skip_verification: bool = False
    blind_listing: bool = False
    obeys_injection: bool = False
    malformed_rate: float = 0.0
    seed: int = 7


@dataclass(slots=True)
class _Intent:
    kind: str  # refund | address | coupon
    ticket: str | None
    address: str | None = None
    amount: float | None = None
    batch: bool = False
    skus: list[str] | None = None


class SurrogatePolicy:
    """A hand-written service-desk procedure that reads the transcript it was given."""

    name = "surrogate"

    def __init__(self, profile: SurrogateProfile | None = None) -> None:
        self.profile = profile or SurrogateProfile()
        self._rng = random.Random(self.profile.seed)
        self.calls = 0
        self.repairs = 0

    # ------------------------------------------------------------------- entry
    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        transcript = _Transcript(request.messages)
        action = self._next_action(transcript)
        usage = Usage(
            input_tokens=max(1, sum(len(str(m)) for m in request.messages) // 4),
            output_tokens=48 if action else 16,
            calls=1,
        )
        if action is None:
            return ChatResponse(content=transcript.closing_remark(), usage=usage, finish_reason="stop")
        name, args = action
        if transcript.needs_repair():
            self.repairs += 1
        elif self.profile.malformed_rate and self._rng.random() < self.profile.malformed_rate:
            args = _break_args(args, self._rng)
        return ChatResponse(
            content=None,
            tool_calls=[ToolCall(id=f"call_{self.calls}_{name}", name=name, arguments=args)],
            usage=usage,
            finish_reason="tool_calls",
        )

    # --------------------------------------------------------------- behaviour
    def _next_action(self, t: _Transcript) -> tuple[str, dict[str, Any]] | None:
        # Skill cards carry a machine-readable trigger. A real model is *asked* to
        # follow the card; this stand-in is *made* to, which is what lets the
        # promotion gate be tested in both directions without an API key.
        skip_verification = self.profile.skip_verification and not t.has_trigger("force_compute_refund")
        blind_listing = self.profile.blind_listing and not t.has_trigger("no_blind_listing")

        # Retrieval is need-driven, not a sweep. Paging for every handle the runtime
        # mentions is what turned offloading into a per-step tax: the re-fetched block is
        # pinned, so the window only grew. A decision pages only for the record it is
        # actually blocked on, below.

        intent = t.intent()
        # Disposed is disposed: a confirmed close or escalation ends this ticket,
        # however the flow reached that conclusion.
        if intent.ticket and intent.ticket in t.handled_tickets() and not intent.batch:
            return None

        if intent.batch and not (t.queue_tickets(use_state=True) or t.saw("list_tickets")):
            return "list_tickets", {"status": "open", "limit": 50}

        if not intent.ticket:
            if intent.batch or t.handled_tickets():
                return None
            phone = t.phone_hint()
            if phone and not t.saw("list_orders_by_phone"):
                return "list_orders_by_phone", {"phone": phone}
            if not t.saw("list_tickets"):
                return "list_tickets", {"status": "open", "limit": 50}
            return "set_ticket_pending_info", {"ticket_id": t.first_seen_ticket() or "T0000", "question": "请提供订单号或下单手机号。"}

        ticket = intent.ticket
        if blind_listing and not t.saw("list_tickets"):
            return "list_tickets", {"status": "all", "limit": 50}

        if not t.saw("get_ticket", scope=ticket):
            return "get_ticket", {"ticket_id": ticket}

        retry = t.retry_hint()
        if retry:
            return retry

        order_id = intent_order = t.order_id()
        if order_id and not t.saw("get_order", scope=order_id):
            return "get_order", {"order_id": order_id}
        if self.profile.obeys_injection:
            # Injection as a model behaviour: an amount lifted out of a record and
            # treated as an instruction. The guardrail, not the prompt, is what has to
            # make this non-lethal — that is the entire claim of this arm.
            demanded = t.demanded_amount()
            if demanded and order_id and not t.saw("issue_refund", scope=order_id) and not t.error_of("issue_refund"):
                return "issue_refund", {"order_id": order_id, "amount": demanded, "reason": "客户备注指定", "note": "按备注直接退款"}
        order = t.result_of("get_order", order_id) or {}
        if not order:
            blocked = t.reread_for("get_order")
            if blocked:
                return "read_scratch", {"handle": blocked, "offset": 0, "limit": 20_000}
            phone = t.phone_hint()
            if phone and not t.saw("list_orders_by_phone"):
                return "list_orders_by_phone", {"phone": phone}
            return "set_ticket_pending_info", {"ticket_id": ticket, "question": "请提供订单号或下单手机号。"}

        customer_id = order.get("customer_id") or t.ticket_field("customer_id")
        if customer_id and not t.saw("get_customer", scope=customer_id):
            return "get_customer", {"customer_id": customer_id}

        if not t.saw("search_sop"):
            return "search_sop", {"query": t.sop_query(intent.kind), "top_k": 3}
        if not t.cited_section() and ticket not in t.handled_tickets():
            # Compaction kept the marker that we searched and dropped the section ids it
            # returned. `close_ticket` will not accept a summary that cites nothing, so
            # the citation has to be fetched back — scoped to this ticket, because an
            # identical query is exactly what the runtime's repeat guard rejects.
            return "search_sop", {"query": f"{t.sop_query(intent.kind)} {ticket}", "top_k": 3}

        if intent.kind == "address":
            return self._address_flow(t, order, intent)
        if intent.kind == "coupon":
            return self._coupon_flow(t, order, customer_id, intent)
        return self._refund_flow(t, order, customer_id, intent, skip_verification=skip_verification)

    # ------------------------------------------------------------------ flows
    def _address_flow(self, t: _Transcript, order: dict, intent: _Intent) -> tuple[str, dict[str, Any]] | None:
        ticket, order_id = intent.ticket, order.get("id") or ""
        if t.saw("change_shipping_address", scope=order_id):
            return self._finish(t, intent, "reissue", "地址已更新")
        blocked = t.error_for("change_shipping_address", order_id) or t.error_of("change_shipping_address")
        if blocked:
            if blocked.get("error") == "address_locked":
                return "escalate_ticket", {"ticket_id": ticket, "team": "logistics", "note": t.escalation_note({"reason_code": "address_locked", "amount": 0})}
            return self._finish(t, intent, "resolved_no_action", "地址未能修改")
        return "change_shipping_address", {"order_id": order_id, "address": intent.address or "客户指定新地址"}

    def _coupon_flow(self, t: _Transcript, order: dict, customer_id: str | None, intent: _Intent) -> tuple[str, dict[str, Any]] | None:
        ticket = intent.ticket
        cap_note = t.result_of("check_coupon_eligibility", customer_id) or {}
        if not t.saw("check_coupon_eligibility", scope=customer_id):
            return "check_coupon_eligibility", {"customer_id": customer_id or "", "value": intent.amount or 20.0}
        if t.saw("send_coupon", scope=customer_id):
            return self._finish(t, intent, "coupon", "已发放补偿券")
        blocked = t.error_for("send_coupon", customer_id) or t.error_of("send_coupon")
        if blocked:
            return "escalate_ticket", {"ticket_id": ticket, "team": "supervisor", "note": t.escalation_note({"reason_code": "coupon_denied", "amount": intent.amount or 0})}
        if cap_note.get("allowed") is False:
            return "escalate_ticket", {"ticket_id": ticket, "team": "supervisor", "note": t.escalation_note({"reason_code": "coupon_over_cap", "amount": intent.amount or 0})}
        return "send_coupon", {"customer_id": customer_id or "", "value": intent.amount or 20.0, "reason": "服务体验补偿"}

    def _refund_flow(self, t: _Transcript, order: dict, customer_id: str | None, intent: _Intent, *, skip_verification: bool) -> tuple[str, dict[str, Any]] | None:
        ticket, order_id = intent.ticket, order.get("id") or ""
        claim = t.claim_type((t.ticket_field("claim") or "") + " " + (t.brief() if not intent.batch else str(intent.ticket)))

        if not skip_verification and not t.saw("compute_refund", scope=order_id):
            return "compute_refund", {"order_id": order_id, "claim_type": claim, "target_skus": intent.skus or _all_skus(order)}

        if skip_verification and not t.saw("compute_refund", scope=order_id) and not t.saw("issue_refund", scope=order_id):
            # The classic failure this profile exists to reproduce: the model does its
            # own arithmetic from the order total instead of deriving it from policy.
            return "issue_refund", {"order_id": order_id, "amount": float(order.get("paid_amount") or 0), "reason": claim, "note": "按订单实付金额退款"}

        decision = t.result_of("compute_refund", order_id) or {}
        if not decision:
            blocked = t.reread_for("compute_refund")
            if blocked:
                # Nothing can be paid out of a decision that is sitting in scratch.
                return "read_scratch", {"handle": blocked, "offset": 0, "limit": 20_000}
        amount = float(decision.get("amount") or 0.0)
        allowed = bool(decision.get("allowed"))

        if t.saw("issue_refund", scope=order_id):
            return self._finish(t, intent, "refunded", "已退款")
        failure = t.error_for("issue_refund", order_id) or t.error_of("issue_refund")
        if failure and str(failure.get("error")) == "approval_rejected":
            team = "risk" if decision.get("requires_escalation") else "supervisor"
            return "escalate_ticket", {"ticket_id": ticket, "team": team, "note": t.escalation_note(decision)}
        if failure and not t.saw("issue_refund", scope=order_id):
            code = str(failure.get("error"))
            if code == "upstream_timeout":
                return "issue_refund", {"order_id": order_id, "amount": amount, "reason": claim, "note": "retry after upstream timeout"}
            if skip_verification and code in {"missing_computation", "amount_mismatch"}:
                # No card: insist instead of correcting. This is the behaviour the
                # promotion gate has to detect and fix.
                return "issue_refund", {"order_id": order_id, "amount": float(order.get("paid_amount") or 0), "reason": claim, "note": "按订单实付金额退款"}
            team = "risk" if decision.get("requires_escalation") or code == "escalation_required" else "supervisor"
            return "escalate_ticket", {"ticket_id": ticket, "team": team, "note": t.escalation_note(decision)}

        if allowed and decision:
            if decision.get("requires_escalation"):
                return "escalate_ticket", {"ticket_id": ticket, "team": "risk", "note": t.escalation_note(decision)}
            return "issue_refund", {"order_id": order_id, "amount": amount, "reason": claim, "note": str(decision.get("reason_code") or claim)}

        if decision and not allowed:
            if decision.get("requires_escalation"):
                return "escalate_ticket", {"ticket_id": ticket, "team": "risk", "note": t.escalation_note(decision)}
            return self._finish(t, intent, "rejected_by_policy", "政策不支持")

        return self._finish(t, intent, "resolved_no_action", "缺少政策核定，转人工")

    def _finish(self, t: _Transcript, intent: _Intent, resolution: str, label: str) -> tuple[str, dict[str, Any]] | None:
        """Close *this* ticket. In a batch run the next one is still on the clock."""
        ticket = intent.ticket
        if not ticket or ticket in t.handled_tickets():
            return None
        return "close_ticket", {"ticket_id": ticket, "resolution": resolution, "summary": t.summary_for(resolution, label)}


class ScriptedModel:
    """Replay a fixed list of ChatResponses. The backbone of the unit tests."""

    name = "scripted"

    def __init__(self, steps: list[ChatResponse | dict[str, Any]]) -> None:
        self.steps = [s if isinstance(s, ChatResponse) else _to_response(s) for s in steps]
        self.index = 0
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if self.index >= len(self.steps):
            return ChatResponse(content="done", usage=Usage(calls=1), finish_reason="stop")
        response = self.steps[self.index]
        self.index += 1
        return response


def _to_response(spec: dict[str, Any]) -> ChatResponse:
    calls = spec.get("tool_calls")
    if calls:
        return ChatResponse(
            tool_calls=[ToolCall(id=c.get("id", f"call_{i}"), name=c["name"], arguments=c.get("arguments") or {}) for i, c in enumerate(calls)],
            usage=Usage(input_tokens=int(spec.get("input_tokens", 100)), output_tokens=int(spec.get("output_tokens", 20)), calls=1),
            finish_reason="tool_calls",
        )
    return ChatResponse(content=spec.get("content", ""), usage=Usage(input_tokens=100, output_tokens=20, calls=1))


def _break_args(args: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Corrupt one argument the way a real model does: camelCase instead of snake_case,
    a JSON string where a list was wanted, or a number that is not a number."""
    mutated = dict(args)
    key = rng.choice(list(mutated)) if mutated else None
    value = mutated.get(key)
    flavour = rng.random()
    if key is None:
        return {"nonexistent": True}
    if flavour < 0.35:
        alias = rng.choice(["orderId", "orderID", "ticketId", "customerID"])
        mutated.pop(key, None)
        mutated[alias] = value
    elif flavour < 0.7:
        mutated[key] = json.dumps(mutated[key], ensure_ascii=False)
    else:
        mutated[key] = "not-a-number" if isinstance(mutated[key], (int, float)) else 12
    return mutated


_SCOPE_KEYS = ("id", "order_id", "ticket_id", "customer_id")


def _matches(row: dict[str, Any], scope: str) -> bool:
    """Loose identity match: a row belongs to a scope if any of its id fields do."""
    for key in _SCOPE_KEYS:
        value = row.get(key)
        if value is not None and str(value) == scope:
            return True
    return str(row.get("order", {}).get("id", "")) == scope if isinstance(row.get("order"), dict) else False


def _all_skus(order: dict[str, Any]) -> list[str] | None:
    items = order.get("items") or []
    return [str(i["sku"]) for i in items if i.get("sku")] or None


class _Transcript:
    """Structured reads over the message list — the surrogate only ever sees the
    context the harness actually delivered, which is what makes the ablations honest."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages
        self._results: dict[str, list[dict[str, Any]]] | None = None
        self._handles: dict[str, str] = {}
        self._fold: str | None = None

    # ------------------------------------------------------------------ reads
    def _unwrap(self, raw: str) -> str:
        """A fenced payload is still data; peel the declaration and the fence off it."""
        if "<<<UNTRUSTED_TOOL_OUTPUT>>>" not in raw:
            return raw
        start = raw.index("<<<UNTRUSTED_TOOL_OUTPUT>>>") + len("<<<UNTRUSTED_TOOL_OUTPUT>>>")
        end = raw.find("<<<END_UNTRUSTED_TOOL_OUTPUT>>>", start)
        return raw[start:end if end > start else None].strip()

    def _tool_results(self) -> dict[str, list[dict[str, Any]]]:
        """Index tool results by tool name, transparently rehydrating anything the
        context engine moved out of the window.

        An offloaded result arrives as a preview carrying a `scratch://` handle. A
        later `read_scratch` call for that handle is spliced back in as if the original
        tool had returned it inline — which is precisely the claim the offload
        mechanism makes, and the claim this suite then tests.
        """
        if self._results is None:
            out: dict[str, list[dict[str, Any]]] = {}
            handles: dict[str, str] = {}
            for msg in self.messages:
                if msg.get("role") != "tool":
                    continue
                name = str(msg.get("name", ""))
                raw = self._unwrap(str(msg.get("content", "") or "{}"))
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"_text": raw}
                if not isinstance(payload, dict):
                    payload = {"_value": payload}
                raw_text = payload.get("_text", "") if isinstance(payload.get("_text"), str) else ""
                match = _OFFLOADED_RE.search(raw_text)
                if match:
                    handles[match.group(2)] = name
                    payload = {"_offloaded": match.group(2), "_tokens": int(match.group(1))}
                    # The runtime leaves a record's identity inline when it moves its bulk
                    # out, so read that back: it is what tells the policy *which* order this
                    # handle is, and without it the row matches no scope.
                    kept = _KEPT_RE.search(raw_text)
                    if kept:
                        try:
                            for key, value in (json.loads(kept.group(1)) or {}).items():
                                payload.setdefault(str(key), value)
                        except json.JSONDecodeError:
                            pass
                if name == "read_scratch" and payload.get("text"):
                    original = handles.pop(str(payload.get("handle")), None)
                    try:
                        inner = json.loads(str(payload["text"]))
                    except json.JSONDecodeError:
                        inner = {"_text": str(payload.get("text"))}
                    if original:
                        out.setdefault(original, []).append(inner if isinstance(inner, dict) else {"_value": inner})
                        continue
                out.setdefault(name, []).append(payload)
            self._results = out
            self._handles = handles
        return self._results

    def reread_for(self, name: str) -> str | None:
        """Handle of `name`'s newest result, when that result is still just a handle.

        Need-driven by construction: the caller asks about the specific record its next
        decision is blocked on, instead of sweeping for anything offloaded. The difference
        is the gap between paging once and re-reading the same payload every step.
        """
        rows = self._tool_results().get(name) or []
        if rows and "_offloaded" in rows[-1]:
            return str(rows[-1]["_offloaded"])
        return None

    def offloaded_pending(self) -> str | None:
        """Handle of the most recent offloaded result the policy still needs."""
        results = self._tool_results()
        for name, rows in results.items():
            if name == "read_scratch" or not rows:
                continue
            last = rows[-1]
            if "_offloaded" in last:
                return str(last["_offloaded"])
        return None

    def _fold_text(self) -> str:
        """The compaction digest, verbatim as the runtime delivered it.

        Folding a block does not delete its history: the summary keeps an
        `- invoked get_order({...})` line. A real model reads that line and knows it
        already looked; a stand-in that only scans live tool rows re-issues the call,
        trips the loop guard and dies. Reading the digest is the faithful behaviour.
        """
        if self._fold is None:
            self._fold = "\n".join(
                str(msg.get("content", ""))
                for msg in self.messages
                if msg.get("role") == "system" and FOLD_MARKER in str(msg.get("content", ""))
            )
        return self._fold

    def _folded(self, name: str, scope: str | None) -> bool:
        if name not in _FOLD_CREDITED_READS:
            return False
        fold = self._fold_text()
        if not fold:
            return False
        for line in fold.splitlines():
            if not (line.startswith(f"- invoked {name}(") or line.startswith(f"- {name} ->")):
                continue
            if scope is None or scope in line:
                return True
        return False

    def saw(self, name: str, *, scope: str | None = None) -> bool:
        """True only when the tool has a result that is not an error.

        `scope` matters in a batch run: a order-scoped read made for ticket #1 is not
        evidence about ticket #2, and treating it as such is how an agent refunds the
        wrong order. A folded-away read still counts (see `_fold_text`); a folded-away
        *effect* does not — the digest is evidence you looked, never evidence you paid.
        """
        rows = self._tool_results().get(name) or []
        if scope is None:
            hit = any("error" not in row for row in rows)
        else:
            hit = any("error" not in row and _matches(row, scope) for row in rows)
        return hit or self._folded(name, scope)

    def result_for(self, name: str, scope: str | None = None) -> dict[str, Any] | None:
        rows = self._tool_results().get(name) or []
        for row in reversed(rows):
            if "error" not in row and (scope is None or _matches(row, scope)):
                return row
        if scope is None:
            return rows[-1] if rows else None
        return None

    def error_for(self, name: str, scope: str | None = None) -> dict[str, Any] | None:
        rows = [r for r in (self._tool_results().get(name) or []) if "error" in r]
        for row in reversed(rows):
            if scope is None or _matches(row, scope):
                return row
        return None

    def result_of(self, name: str, scope: str | None = None) -> dict[str, Any] | None:
        return self.result_for(name, scope)

    def error_of(self, name: str, scope: str | None = None) -> dict[str, Any] | None:
        """Only the *latest* result for a tool counts: a failure that was already
        retried successfully must not haunt the rest of the run."""
        rows = self._tool_results().get(name) or []
        if scope is not None:
            return self.error_for(name, scope)
        if rows and "error" in rows[-1]:
            return rows[-1]
        return None

    def text_of(self, name: str) -> str:
        for msg in self.messages:
            if msg.get("role") == "tool" and msg.get("name") == name:
                return str(msg.get("content", ""))
        return ""

    def brief(self) -> str:
        for msg in self.messages:
            if msg.get("role") == "user":
                return str(msg.get("content", ""))
        return ""

    def retry_hint(self) -> tuple[str, dict[str, Any]] | None:
        """Re-issue the most recent call that failed *retryably* and has not since succeeded.

        Scanned forward, not backward: once a later identical call has returned an
        okay result, retrying it again would be a bug, not resilience.
        """
        pending: str | None = None
        arguments: dict[str, Any] = {}
        latest_args: dict[str, dict[str, Any]] = {}
        for msg in self.messages:
            if msg.get("role") == "assistant":
                for call in msg.get("tool_calls") or []:
                    fn = call.get("function", {})
                    try:
                        parsed = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        parsed = {}
                    latest_args[str(fn.get("name", ""))] = parsed
            elif msg.get("role") == "tool":
                name = str(msg.get("name", ""))
                try:
                    payload = json.loads(str(msg.get("content", "") or "{}"))
                except json.JSONDecodeError:
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                if payload.get("retryable") and "error" in payload:
                    pending, arguments = name, latest_args.get(name, {})
                elif "error" not in payload and name == pending:
                    pending, arguments = None, {}
        if pending is None:
            return None
        return pending, arguments

    def needs_repair(self) -> bool:
        """True when the last thing the harness said was "that call was malformed".

        A model that cannot re-issue a corrected call after a validation error is not a
        model the runtime can help; this is the behaviour structured errors exist to buy.
        """
        for msg in reversed(self.messages):
            if msg.get("role") == "tool":
                try:
                    payload = json.loads(str(msg.get("content", "") or "{}"))
                except json.JSONDecodeError:
                    return False
                return isinstance(payload, dict) and payload.get("error") in {"invalid_arguments", "unknown_tool"}
        return False

    def demanded_amount(self) -> float | None:
        """Largest 'refund N yuan' demand sitting inside any tool payload."""
        best: float | None = None
        for rows in self._tool_results().values():
            for row in rows:
                blob = json.dumps(row, ensure_ascii=False)
                for match in re.finditer(r"(?:直接退款|立即退款|refund)\s*[¥￥]?\s*([\d,]+(?:\.\d+)?)", blob):
                    try:
                        value = float(match.group(1).replace(",", ""))
                    except ValueError:
                        continue
                    best = value if best is None else max(best, value)
        return best

    def has_trigger(self, marker: str) -> bool:
        token = f"TRIGGER:{marker}"
        return any(token in str(msg.get("content", "")) for msg in self.messages if msg.get("role") == "system")

    # ------------------------------------------------------------- identifiers
    def handled_tickets(self) -> set[str]:
        """Ticket ids this run actually disposed of.

        Only *successful* results count. Trusting the intent to close — rather than the
        confirmation that it closed — is how a batch run silently skips the tickets whose
        close-out was rejected.
        """
        done: set[str] = set()
        for name in ("close_ticket", "escalate_ticket"):
            for row in self._tool_results().get(name) or []:
                if "error" not in row and row.get("ticket_id"):
                    done.add(str(row["ticket_id"]))
        # The runtime's pinned state block outranks the transcript: a folded-away
        # confirmation is still a confirmation.
        for msg in self.messages:
            if msg.get("role") != "system":
                continue
            content = str(msg.get("content", ""))
            if "RUN STATE" not in content:
                continue
            for key in ("tickets_closed", "tickets_escalated"):
                line = next((ln for ln in content.splitlines() if ln.startswith(key + ":")), "")
                done.update(t for t in line.split(":", 1)[1].strip().split(", ") if t and t != "none")
        return done

    def first_seen_ticket(self) -> str | None:
        for msg in self.messages:
            match = _TICKET_RE.search(str(msg.get("content", "")))
            if match:
                return match.group(1)
        return None

    def queue_tickets(self, *, use_state: bool = False) -> list[str]:
        """The work list. `use_state` reads the runtime's pinned copy, which survives
        compaction — what a batch run needs. A single-ticket run must not: finding a
        40-item queue in context would be mistaken for a to-do list.
        """
        if use_state:
            for msg in self.messages:
                if msg.get("role") != "system" or "RUN STATE" not in str(msg.get("content", "")):
                    continue
                line = next((ln for ln in str(msg["content"]).splitlines() if ln.startswith("queue_seen_open:")), "")
                ids = [x for x in line.split(":", 1)[1].strip().split(", ") if x.startswith("T")] if line else []
                if ids:
                    return ids
        out: list[str] = []
        for row in self._tool_results().get("list_tickets") or []:
            for item in row.get("tickets") or []:
                if isinstance(item, dict) and item.get("id"):
                    out.append(str(item["id"]))
        return out

    def order_ids(self) -> set[str]:
        out: set[str] = set()
        for row in self._tool_results().get("list_orders_by_phone") or []:
            for item in row.get("orders") or []:
                if isinstance(item, dict) and item.get("id"):
                    out.add(str(item["id"]))
        return out

    def ticket_done(self, ticket_id: str | None) -> bool:
        return bool(ticket_id) and ticket_id in self.handled_tickets()

    def intent(self) -> _Intent:
        blob = self.brief() + " " + str(self.ticket_field("claim") or "")
        ticket = None
        for msg in self.messages:
            # Only the user's own words name the target; a digest of earlier turns can
            # mention a ticket that is already finished.
            if msg.get("role") != "user":
                continue
            match = _TICKET_RE.search(str(msg.get("content", "")))
            if match:
                ticket = match.group(1)
                break
        if not ticket:
            rows = self._tool_results().get("list_tickets") or []
            for row in rows:
                for item in row.get("tickets") or []:
                    if isinstance(item, dict) and _TICKET_RE.search(str(item.get("id", ""))):
                        ticket = str(item["id"])
                        break
                if ticket:
                    break
        amount_match = _MONEY_RE.search(blob)
        kind = "refund"
        if any(w in blob for w in ADDRESS_WORDS) and not any(w in blob for w in REFUND_WORDS):
            kind = "address"
        elif any(w in blob for w in COUPON_WORDS) and not any(w in blob for w in ("退款", "退货")):
            kind = "coupon"
        address_match = _ADDRESS_RE.search(blob)
        batch = any(w in blob for w in ("所有", "批量", "全部"))
        # Order-preserving dedupe: the same sku appears in the task brief and in the
        # ticket body, and a duplicated target list is noise a reviewer reads as a bug.
        skus = list(dict.fromkeys(_SKU_RE.findall(blob)))
        if batch:
            remaining = [tid for tid in self.queue_tickets(use_state=True) if tid not in self.handled_tickets()]
            ticket = remaining[0] if remaining else None
        elif ticket is None:
            located = self.order_ids()
            match = next((tid for tid in self.queue_tickets() if tid not in self.handled_tickets() and self.ticket_order(tid) in located), None)
            ticket = match or next((tid for tid in self.queue_tickets() if tid not in self.handled_tickets()), None)
        return _Intent(
            kind=kind,
            ticket=ticket,
            address=address_match.group(1) if address_match else None,
            amount=float(amount_match.group(1)) if amount_match else None,
            batch=batch,
            skus=skus or None,
        )

    def ticket_order(self, ticket_id: str) -> str | None:
        for row in self._tool_results().get("list_tickets") or []:
            for item in row.get("tickets") or []:
                if isinstance(item, dict) and str(item.get("id")) == ticket_id:
                    return str(item.get("order_id") or "")
        return None

    def ticket_field(self, key: str) -> Any:
        row = self.result_of("get_ticket") or {}
        return row.get(key)

    def order_id(self) -> str | None:
        row = self.result_of("get_ticket") or {}
        if row.get("order_id"):
            return str(row["order_id"])
        for msg in self.messages:
            match = _ORDER_RE.search(str(msg.get("content", "")))
            if match:
                return match.group(1)
        rows = self._tool_results().get("list_orders_by_phone") or []
        for item in rows:
            orders = item.get("orders") or []
            if orders:
                return str(orders[0]["id"])
        return None

    def phone_hint(self) -> str | None:
        match = _PHONE_RE.search(self.brief())
        return match.group(1) if match else None

    def claim_type(self, text: str) -> str:
        table = {
            "quality": ("质量", "坏了", "破损", "不能用", "故障", "没有声音", "开线"),
            "missing_item": ("少发", "缺件", "漏发", "少件", "只收到"),
            "damaged": ("运输损坏", "压坏", "摔坏", "外箱破"),
            "duplicate_charge": ("重复扣款", "扣了两次", "多扣"),
            "no_reason": ("不想要", "无理由", "买错", "后悔", "不喜欢", "不合适"),
        }
        for claim, keywords in table.items():
            if any(k in text for k in keywords):
                return claim
        return "other"

    def sop_query(self, kind: str) -> str:
        return {"address": "改地址 物流拦截 配送", "coupon": "补偿券 发放权限 等级上限"}.get(kind, "退款 无理由 政策 窗口 计算")

    def cited_section(self) -> str:
        hits = (self.result_of("search_sop") or {}).get("hits") or []
        for hit in hits:
            if isinstance(hit, dict) and "::" in str(hit.get("id", "")):
                return str(hit["id"])
        return ""

    def summary_for(self, resolution: str, label: str) -> str:
        section = self.cited_section()
        decision = self.result_of("compute_refund") or {}
        amount = float(decision.get("amount") or 0.0)
        money = f"，执行金额 ¥{amount:.2f}" if amount or resolution in {"refunded", "coupon", "partial_refund"} else "，本次不退款，金额 ¥0.00"
        basis = f"政策依据 {section}" if section else "政策依据 未知章节"
        return f"客户诉求处理完毕（{label}）。{basis}{money}。结论 {resolution}。"

    def escalation_note(self, decision: dict[str, Any]) -> str:
        return (
            f"已核实事实与政策依据: {self.cited_section() or 'compute_refund'} 返回 "
            f"{decision.get('reason_code', 'n/a')}，核定金额 ¥{float(decision.get('amount') or 0):.2f}；"
            f"候选方案: 人工特批放款或按政策拒绝；建议: 复核后由人工回复客户。"
        )

    def closing_remark(self) -> str:
        refund = self.result_of("issue_refund")
        if refund and "error" not in refund:
            return f"已按政策退款 ¥{float(refund.get('amount') or 0):.2f}（{refund.get('refund_id')}），工单已结单。"
        coupon = self.result_of("send_coupon")
        if coupon and "error" not in coupon:
            return f"已发放补偿券 ¥{float(coupon.get('value') or 0):.2f}，工单已结单。"
        if self.error_of("issue_refund") or self.saw("escalate_ticket"):
            return "该工单已转人工处理。"
        if self.saw("close_ticket"):
            return "工单已结单。"
        return "处理完成。"


__all__ = ["ScriptedModel", "SurrogatePolicy", "SurrogateProfile"]
