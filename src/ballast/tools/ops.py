"""SRE incident tools bound to one simulated world.

The guardrail pattern is copied, not shared: a mutating tool refuses to act on
arguments it cannot re-derive from the deterministic escalation policy. `page_oncall`
requires a prior `evaluate_escalation`; `rollback_deploy` requires a prior
`evaluate_rollback`; a sev1/sev2 *human-gated* mitigation requires an approval.

That is the point of the second domain. If the runtime is real, adding a business
vertical costs tools and a policy — not a new engine.
"""

from __future__ import annotations

from typing import Any

from ..env.incident_policy import (
    evaluate_escalation,
    evaluate_rollback,
    runbook_required_steps,
)
from ..env.ops_world import OpsWorld
from ..env.world import WorldError
from ..kernel.events import RunContext
from ..kernel.hitl import resolve_approval
from ..kernel.toolkit import Tool, ToolError, tool

SEVERITIES = ["sev1", "sev2", "sev3", "sev4"]
RESOLUTIONS = ["mitigated", "rolled_back", "resolved_no_action", "escalated", "false_positive"]


def build_ops_tools(ctx: RunContext) -> list[Tool]:
    world: OpsWorld = ctx.world
    kb = ctx.sop

    @tool
    def list_incidents(status: str = "open", limit: int = 20) -> dict[str, Any]:
        """List incidents on the board.

        Args:
            status: open / closed / all.
            limit: maximum rows.
        """
        rows = world.list_incidents(None if status == "all" else status, limit=limit)
        return {"count": len(rows), "incidents": rows}

    @tool
    def get_incident(incident_id: str) -> dict[str, Any]:
        """Read one incident: severity, affected service with its tier and blast radius,
        firing alerts, and the service's recent deployments.

        Args:
            incident_id: incident identifier such as INC-77.
        """
        try:
            return world.get_incident(incident_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, hint="call list_incidents to find the real id", retryable=exc.retryable) from exc

    @tool
    def get_service(service_id: str) -> dict[str, Any]:
        """Read a service: tier, owning team, blast radius and current SLI percentage.

        Args:
            service_id: service identifier.
        """
        try:
            return world.get_service(service_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool
    def search_runbook(query: str, top_k: int = 3) -> dict[str, Any]:
        """Search the runbook corpus. Consult it before paging or rolling anything back.

        Args:
            query: what you are trying to decide.
            top_k: sections to return.
        """
        hits = kb.search(query, top_k=top_k) if kb is not None else []
        return {
            "query": query,
            "hits": [{"id": d.id, "title": d.title, "score": round(s, 3), "text": d.text} for d, s in hits]
            or [{"note": "no section matched; try different keywords"}],
        }

    @tool
    def evaluate_escalation_required(incident_id: str) -> dict[str, Any]:
        """Derive from policy whether this incident must page anyone, and whether the
        agent may mitigate it at all. Mandatory precondition for page_oncall.

        Args:
            incident_id: the incident to assess.
        """
        try:
            incident = world.get_incident(incident_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc
        decision = evaluate_escalation(
            incident=incident,
            service=incident["service"],
            alerts=incident["alerts"],
            now=world.now,
        )
        payload = {
            "incident_id": incident_id,
            "page": decision.page,
            "team": decision.team,
            "reason_code": decision.reason_code,
            "explanation": decision.explanation,
            "requires_human": decision.requires_human,
            "blockers": decision.blockers,
            "still_owed": runbook_required_steps(incident=incident, mitigation_taken=incident.get("mitigation") or []),
        }
        ctx.computed[incident_id] = payload
        world.audit_read("evaluate_escalation_required", {"incident_id": incident_id}, {"page": decision.page, "team": decision.team})
        return payload

    @tool
    def evaluate_rollback_safety(service_id: str, incident_id: str) -> dict[str, Any]:
        """Derive from policy whether reverting the latest deploy is right and permitted.
        Mandatory precondition for rollback_deploy.

        Args:
            service_id: affected service.
            incident_id: incident the rollback would address.
        """
        try:
            incident = world.get_incident(incident_id)
            service = world.get_service(service_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc
        decision = evaluate_rollback(
            service=service,
            deployments=world.recent_deployments(service_id),
            incident=incident,
            now=world.now,
        )
        payload = {
            "service_id": service_id,
            "incident_id": incident_id,
            "allowed": decision.allowed,
            "target_deployment": decision.target_deployment,
            "reason_code": decision.reason_code,
            "explanation": decision.explanation,
            "requires_human": decision.requires_human,
            "blockers": decision.blockers,
        }
        ctx.computed[f"rollback:{service_id}"] = payload
        world.audit_read("evaluate_rollback_safety", {"service_id": service_id, "incident_id": incident_id}, {"allowed": decision.allowed})
        return payload

    @tool(mutating=True, tags=["paging"])
    def page_oncall(incident_id: str, team: str, reason: str) -> dict[str, Any]:
        """Wake the on-call engineer. Team and necessity must come from policy first.

        Args:
            incident_id: incident justifying the page.
            team: receiving team, from evaluate_escalation_required.
            reason: one-line justification.
        """
        computed = ctx.computed.get(incident_id)
        if computed is None:
            ctx.guardrail_blocks += 1
            raise ToolError("missing_computation", "paged without a policy escalation assessment", hint=f"call evaluate_escalation_required(incident_id='{incident_id}') first")
        if not computed["page"]:
            ctx.guardrail_blocks += 1
            raise ToolError("policy_denied", f"policy says no page: {computed['reason_code']} — {computed['explanation']}", hint="record a review instead of waking people")
        if team != computed["team"]:
            ctx.guardrail_blocks += 1
            raise ToolError("team_mismatch", f"requested team {team} but policy derived {computed['team']}", hint="use the derived team")
        decision = resolve_approval(
            ctx,
            tool_name="page_oncall",
            args={"incident_id": incident_id, "team": team},
            reason=f"page {team} for {incident_id}: {reason}",
            required=bool(computed["requires_human"]),
        )
        if not decision.approved:
            return {"ok": False, "error": "approval_rejected", "incident_id": incident_id, "message": decision.note, "hint": "do not retry; close with the rejection reason"}
        try:
            return {"ok": True, **world.page_oncall(incident_id=incident_id, team=team, reason=reason)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True, tags=["change"])
    def rollback_deploy(service_id: str, deployment_id: str, reason: str) -> dict[str, Any]:
        """Revert a deployment. Only the deployment policy named, and only if permitted.

        Args:
            service_id: service to roll back.
            deployment_id: must equal evaluate_rollback_safety's target_deployment.
            reason: why this is the fix.
        """
        computed = ctx.computed.get(f"rollback:{service_id}")
        if computed is None:
            ctx.guardrail_blocks += 1
            raise ToolError("missing_computation", "rollback attempted without a safety assessment", hint="call evaluate_rollback_safety first")
        if not computed["allowed"]:
            ctx.guardrail_blocks += 1
            raise ToolError("policy_denied", f"rollback not permitted: {computed['reason_code']} — {computed['explanation']}", hint="fix forward, or escalate to the service owner")
        if deployment_id != computed["target_deployment"]:
            ctx.guardrail_blocks += 1
            raise ToolError("deployment_mismatch", f"asked to revert {deployment_id}; policy named {computed['target_deployment']}", hint="revert the named deployment or none")
        decision = resolve_approval(
            ctx,
            tool_name="rollback_deploy",
            args={"service_id": service_id, "deployment_id": deployment_id},
            reason=f"rollback {deployment_id} on {service_id}: {reason}",
            required=bool(computed["requires_human"]),
        )
        if not decision.approved:
            return {"ok": False, "error": "approval_rejected", "service_id": service_id, "message": decision.note, "hint": "fix forward instead of retrying"}
        try:
            return {"ok": True, **world.rollback_deploy(service_id=service_id, deployment_id=deployment_id, reason=reason)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def acknowledge_incident(incident_id: str, by: str) -> dict[str, Any]:
        """Record that a human accepted the incident.

        Args:
            incident_id: incident acknowledged.
            by: name of the engineer who took it.
        """
        try:
            return {"ok": True, **world.acknowledge_incident(incident_id=incident_id, by=by)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def notify_status_page(incident_id: str, text: str) -> dict[str, Any]:
        """Publish a customer-facing status update.

        Args:
            incident_id: incident being described.
            text: the customer-visible note.
        """
        if len(text) < 15:
            ctx.guardrail_blocks += 1
            raise ToolError("text_too_thin", "a status note that short is not actionable for customers", hint="say what is affected, the impact, and what is being done")
        try:
            return {"ok": True, **world.notify_status_page(incident_id=incident_id, text=text)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def record_review(incident_id: str, summary: str) -> dict[str, Any]:
        """File the post-incident review entry.

        Args:
            incident_id: incident reviewed.
            summary: timeline, trigger, mitigation and follow-up, citing a runbook section.
        """
        problems = _check_summary(summary, kb)
        if problems:
            ctx.guardrail_blocks += 1
            raise ToolError("summary_incomplete", "; ".join(problems), hint="cite the runbook section id and name the trigger")
        try:
            return {"ok": True, **world.record_review(incident_id=incident_id, summary=summary)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool(mutating=True)
    def close_incident(incident_id: str, resolution: str, summary: str) -> dict[str, Any]:
        """Close the incident. Refuses while the runbook still owes a step.

        Args:
            incident_id: incident to close.
            resolution: outcome code.
            summary: what happened and what was done.
        """
        if resolution not in RESOLUTIONS:
            raise ToolError("bad_resolution", f"resolution must be one of {RESOLUTIONS}", hint="pick the code matching what actually happened")
        try:
            incident = world.get_incident(incident_id)
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc
        done = _mitigations(incident)
        owed = runbook_required_steps(incident=incident, mitigation_taken=done)
        if owed:
            ctx.guardrail_blocks += 1
            raise ToolError("runbook_incomplete", "; ".join(owed), hint="complete the owed steps, then close")
        problems = _check_summary(summary, kb)
        if problems:
            ctx.guardrail_blocks += 1
            raise ToolError("summary_incomplete", "; ".join(problems), hint="cite a runbook section id in the summary")
        try:
            return {"ok": True, **world.close_incident(incident_id=incident_id, resolution=resolution, summary=summary)}
        except WorldError as exc:
            raise ToolError(exc.code, exc.message, retryable=exc.retryable) from exc

    @tool
    def read_scratch(handle: str, offset: int = 0, limit: int = 20000) -> dict[str, Any]:
        """Re-read a tool output that was moved out of the context window.

        Args:
            handle: a scratch:// handle from a truncated result.
            offset: character offset.
            limit: maximum characters.
        """
        if ctx.scratch is None:
            raise ToolError("no_scratch", "overflow store is disabled for this run")
        payload = ctx.scratch.get(handle)
        if payload is None:
            raise ToolError("not_found", f"handle {handle} is not readable", hint="check the handle from the truncated result")
        return {"handle": handle, "offset": offset, "text": payload[offset : offset + limit]}

    return [
        list_incidents,
        get_incident,
        get_service,
        search_runbook,
        evaluate_escalation_required,
        evaluate_rollback_safety,
        page_oncall,
        acknowledge_incident,
        notify_status_page,
        rollback_deploy,
        record_review,
        close_incident,
        read_scratch,
    ]


def _mitigations(incident: dict[str, Any]) -> list[str]:
    value = incident.get("mitigation")
    return list(value) if isinstance(value, list) else []


def _check_summary(summary: str, kb: Any) -> list[str]:
    problems: list[str] = []
    if len(summary) < 25:
        problems.append("summary too short to serve as a review entry")
    if kb is not None and not any(sid in summary for sid in kb.section_ids()):
        problems.append("summary cites no runbook section id")
    if not any(word in summary for word in ("trigger", "root cause", "触发", "根因", "cause")):
        problems.append("summary states no trigger or root cause")
    return problems


__all__ = ["build_ops_tools", "RESOLUTIONS", "SEVERITIES"]
