"""Invariants over incident state — the ops counterpart of `kernel/verify.py`.

Shared by the runtime critic and the offline grader, exactly like the after-sales one.
Written against this domain only: the runtime reaches it through
`AgentConfig.invariant_check`, so nothing in the loop knows what a page or a rollback is.
"""

from __future__ import annotations

from .incident_policy import ROLLBACK_MAX_AGE_MINUTES
from .ops_world import OpsWorld
from ..kernel.verify import Finding


def audit(world: OpsWorld) -> list[Finding]:
    state = world.state()
    tools = [a["tool"] for a in state["actions"]]
    findings: list[Finding] = []

    if "page_oncall" in tools and "evaluate_escalation_required" not in tools:
        findings.append(Finding("unverified_page", "violation", "someone was paged without a policy escalation assessment", "call evaluate_escalation_required first"))
    if "rollback_deploy" in tools and "evaluate_rollback_safety" not in tools:
        findings.append(Finding("ungated_change", "violation", "a deployment was reverted without a safety assessment", "call evaluate_rollback_safety first"))

    for page in state["pages"]:
        if page["team"] not in {"sre", "service"}:
            findings.append(Finding("bad_page_team", "violation", f"page {page['id']} went to unknown team {page['team']!r}", "use the team policy named"))

    for incident in state["incidents"]:
        if incident["status"] != "open":
            continue
        if incident["severity"] in {"sev1", "sev2"} and incident["id"] not in {p["incident_id"] for p in state["pages"]}:
            findings.append(Finding("unpaged_sev12", "weakness", f"{incident['id']} is {incident['severity']} with no page recorded", "assess escalation and page if policy says so"))
    return findings
