"""Offline stand-in for an on-call automation policy.

The after-sales surrogate's companion: same discipline — it reads only the context the
harness assembled, and its only knowledge of the world comes from tool results — but
written against a completely different procedure, so a reviewer cannot dismiss it as one
bespoke script.

Deliberately conservative about paging and about changes: it does what the policy
computation told it to do and nothing it invented, which is the behaviour the
guardrails in `tools/ops.py` are designed to make safe.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..llm.base import ChatRequest, ChatResponse, ToolCall, Usage

_INCIDENT_RE = re.compile(r"(INC-\d+)")


@dataclass(slots=True)
class OpsProfile:
    """Knobs for the failure modes the second domain can be ablated against."""

    skip_assessment: bool = False
    force_rollback: bool = False
    malformed_rate: float = 0.0


class OpsSurrogatePolicy:
    name = "ops_surrogate"

    def __init__(self, profile: OpsProfile | None = None) -> None:
        self.profile = profile or OpsProfile()
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        t = _OpsTranscript(request.messages)
        action = self._next(t)
        usage = Usage(input_tokens=max(1, sum(len(str(m)) for m in request.messages) // 4), output_tokens=52 if action else 18, calls=1)
        if action is None:
            return ChatResponse(content=t.closing_remark(), usage=usage, finish_reason="stop")
        name, args = action
        return ChatResponse(content=None, tool_calls=[ToolCall(id=f"call_{self.calls}_{name}", name=name, arguments=args)], usage=usage, finish_reason="tool_calls")

    def _next(self, t: _OpsTranscript) -> tuple[str, dict[str, Any]] | None:
        iid = t.incident_id()
        if not iid:
            return "list_incidents", {"status": "open", "limit": 20}
        if t.closed(iid):
            return None

        if not t.saw("get_incident", iid):
            return "get_incident", {"incident_id": iid}
        incident = t.result_of("get_incident", iid) or {}
        service_id = incident.get("service_id") or ""
        service = incident.get("service") or {}

        if not t.saw("search_runbook"):
            return "search_runbook", {"query": "呼叫 升级 回滚 复盘 要求", "top_k": 3}

        # Same contract as the after-sales driver: a card carries a machine-readable
        # trigger. A model is asked to follow it; this stand-in is made to, which is what
        # lets the promotion gate be tested in both directions with no API key.
        skip_assessment = self.profile.skip_assessment and not t.has_trigger("force_escalation_assessment")
        if not skip_assessment and not t.saw("evaluate_escalation_required", iid):
            return "evaluate_escalation_required", {"incident_id": iid}
        if skip_assessment and not t.saw("evaluate_escalation_required", iid):
            sev = str((t.result_of("get_incident", iid) or {}).get("severity", "sev2")).lower()
            return "page_oncall", {"incident_id": iid, "team": "sre" if sev in {"sev1", "sev2"} else "service", "reason": "自行判断需呼叫"}

        esc = t.result_of("evaluate_escalation_required", iid) or {}
        if esc.get("page") and not t.saw("page_oncall", iid):
            return "page_oncall", {"incident_id": iid, "team": esc.get("team") or "sre", "reason": str(esc.get("reason_code") or "policy")}
        if esc.get("page") and t.error_of("page_oncall", iid):
            return "page_oncall", {"incident_id": iid, "team": esc.get("team") or "sre", "reason": str(esc.get("reason_code") or "policy")}

        has_deploy = bool((incident.get("deployments") or []))
        if has_deploy and service_id and not t.saw("evaluate_rollback_safety", service_id):
            return "evaluate_rollback_safety", {"service_id": service_id, "incident_id": iid}
        roll = t.result_of("evaluate_rollback_safety", service_id) or {}
        target = roll.get("target_deployment")
        if self.profile.force_rollback and not roll.get("allowed") and target and not t.saw("rollback_deploy", service_id):
            # The knob that exists so the change-freeze guardrail has something to stop.
            return "rollback_deploy", {"service_id": service_id, "deployment_id": target, "reason": "坚持回滚最近部署"}
        if roll.get("allowed") and target and not t.saw("rollback_deploy", service_id):
            return "rollback_deploy", {"service_id": service_id, "deployment_id": target, "reason": str(roll.get("reason_code") or "recent deploy")}

        if "customer_impact" in (incident.get("tags") or []) and not t.saw("notify_status_page", iid):
            return "notify_status_page", {"incident_id": iid, "text": f"{service.get('name', service_id)} 当前出现错误率上升，值班已介入并正在处置，我们会持续更新。"}

        if self._owes_ack(incident, esc) and not t.saw("acknowledge_incident", iid):
            return "acknowledge_incident", {"incident_id": iid, "by": "sre-oncall"}

        # The runbook owes a review for anything that woke someone up, and a close-out
        # is refused until it exists — so file it before trying to close.
        if self._owes_review(incident, esc) and not t.saw("record_review", iid):
            return "record_review", {"incident_id": iid, "summary": t.review_text(esc, roll)}

        if t.saw("close_incident", iid) and not t.error_of("close_incident", iid):
            return None
        if t.error_of("close_incident", iid) and t.saw("close_incident", iid):
            return None
        resolution = "rolled_back" if t.saw("rollback_deploy", service_id) else ("mitigated" if esc.get("page") else "resolved_no_action")
        return "close_incident", {"incident_id": iid, "resolution": resolution, "summary": t.review_text(esc, roll)}

    @staticmethod
    def _owes_ack(incident: dict, esc: dict) -> bool:
        # The runbook owes a human owner to anything that wakes someone, and to
        # sev1/sev2 whether or not a page was warranted.
        return str(incident.get("severity", "")).lower() in {"sev1", "sev2"} or bool(esc.get("page"))

    @staticmethod
    def _owes_review(incident: dict, esc: dict) -> bool:
        severity = str(incident.get("severity", "")).lower()
        return severity in {"sev1", "sev2"} or bool(esc.get("page"))


class _OpsTranscript:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages
        self._rows: dict[str, list[tuple[str, dict[str, Any]]]] | None = None
        self.finalise_pending = False

    def _tool_rows(self) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        if self._rows is None:
            out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
            for msg in self.messages:
                if msg.get("role") != "tool":
                    continue
                try:
                    payload = json.loads(str(msg.get("content", "") or "{}"))
                except json.JSONDecodeError:
                    payload = {"_text": str(msg.get("content", ""))}
                if not isinstance(payload, dict):
                    payload = {"_value": payload}
                out.setdefault(str(msg.get("name", "")), []).append((str(msg.get("tool_call_id", "")), payload))
            self._rows = out
        return self._rows

    def _matches(self, payload: dict[str, Any], scope: str | None) -> bool:
        if scope is None:
            return True
        for key in ("incident_id", "service_id", "id"):
            if payload.get(key) is not None and str(payload[key]) == scope:
                return True
        return False

    def saw(self, name: str, scope: str | None = None) -> bool:
        return any("error" not in payload and self._matches(payload, scope) for _, payload in self._tool_rows().get(name) or [])

    def result_of(self, name: str, scope: str | None = None) -> dict[str, Any] | None:
        for _, payload in reversed(self._tool_rows().get(name) or []):
            if "error" not in payload and self._matches(payload, scope):
                return payload
        return None

    def error_of(self, name: str, scope: str | None = None) -> dict[str, Any] | None:
        rows = self._tool_rows().get(name) or []
        if not rows:
            return None
        _, last = rows[-1]
        return last if "error" in last and self._matches(last, scope) else None

    def has_trigger(self, marker: str) -> bool:
        token = f"TRIGGER:{marker}"
        return any(token in str(msg.get("content", "")) for msg in self.messages if msg.get("role") == "system")

    def incident_id(self) -> str | None:
        for msg in self.messages:
            if msg.get("role") != "user":
                continue
            match = _INCIDENT_RE.search(str(msg.get("content", "")))
            if match:
                return match.group(1)
        return None

    def closed(self, iid: str) -> bool:
        row = self.result_of("close_incident", iid)
        return bool(row)

    def cited_section(self) -> str:
        for hit in (self.result_of("search_runbook") or {}).get("hits") or []:
            if isinstance(hit, dict) and "::" in str(hit.get("id", "")):
                return str(hit["id"])
        return ""

    def review_text(self, esc: dict, roll: dict) -> str:
        actions = []
        if esc.get("page"):
            actions.append(f"已呼叫 {esc.get('team')}")
        if roll.get("target_deployment") and roll.get("allowed"):
            actions.append(f"已回滚 {roll['target_deployment']}")
        if not actions:
            actions.append("按政策无需呼叫或变更")
        return f"时间线与处置记录：{'; '.join(actions)}。触发原因与根因待人工确认，依据 runbook 章节 {self.cited_section() or '未检索到'}。"

    def closing_remark(self) -> str:
        page = self.result_of("page_oncall")
        roll = self.result_of("rollback_deploy")
        bits = []
        if page:
            bits.append(f"已呼叫 {page.get('team')}")
        if roll:
            bits.append(f"已回滚 {roll.get('rolled_back')}")
        if self.saw("close_incident"):
            bits.append("故障已关闭")
        return "；".join(bits) or "无需进一步动作。"
