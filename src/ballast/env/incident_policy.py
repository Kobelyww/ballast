"""Deterministic incident-escalation policy.

Second domain on purpose: the point of this module is that it shares *no code* with
`policies.py` yet the runtime, the arms, the grader shape and the guardrail pattern are
unchanged. If an agent runtime needs a rewrite per business domain, it is an
application, not a runtime.

Every judgement that a model must not be trusted with lives here: who gets paged,
whether a rollback is safe, how large a blast radius may touch production, and what a
post-incident review requires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

SEVERITY_PAGE = {"sev1": True, "sev2": True, "sev3": False, "sev4": False}
ONCALL_TEAM_FOR = {"sev1": "sre", "sev2": "sre", "sev3": "service", "sev4": "service"}
# Production writes are frozen while a sev1 is open, except by a human.
FREEZE_SEVERITIES = {"sev1"}
ROLLBACK_MAX_AGE_MINUTES = 90
BLAST_RADIUS_LIMIT = 3


@dataclass(slots=True)
class EscalationDecision:
    page: bool
    team: str
    reason_code: str
    explanation: str
    requires_human: bool = False
    blockers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RollbackDecision:
    allowed: bool
    target_deployment: str | None
    reason_code: str
    explanation: str
    requires_human: bool = False
    blockers: list[str] = field(default_factory=list)


def parse_ts(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def evaluate_escalation(*, incident: dict, service: dict, alerts: list[dict], now: str | datetime) -> EscalationDecision:
    """Who must be woken up, and whether the agent may do anything else at all."""
    severity = str(incident.get("severity", "sev4")).lower()
    tier = str(service.get("tier", "internal")).lower()
    blockers: list[str] = []

    if severity not in SEVERITY_PAGE:
        return EscalationDecision(False, "", "unknown_severity", f"未知严重级别 {severity}，需人工判定。", requires_human=True, blockers=["bad_severity"])

    firing = [a for a in alerts if a.get("state") == "firing"]
    if severity in {"sev1", "sev2"} and not firing:
        return EscalationDecision(
            False,
            ONCALL_TEAM_FOR[severity],
            "already_resolved",
            "告警已恢复，只需补记复盘，不要叫醒任何人。",
            blockers=["no_active_alert"],
        )

    requires_human = False
    if severity == "sev1" and len(firing) >= 3:
        blockers.append("multi_service_impact")
        requires_human = True
    if tier == "payments" and severity in {"sev1", "sev2"}:
        # payment-path incidents need a human decision owner regardless of the agent's read
        blockers.append("payments_tier")
        requires_human = True

    return EscalationDecision(
        page=SEVERITY_PAGE[severity],
        team=ONCALL_TEAM_FOR[severity],
        reason_code=f"{severity}_{tier}",
        explanation=(
            f"{severity} 影响 {service['name']}（tier={tier}），当前 firing 告警 {len(firing)} 条："
            + ("必须立即呼叫值班，" if SEVERITY_PAGE[severity] else "按队列处理，无需呼叫，")
            + ("且因" + "/".join(blockers) + "需人类值班负责，Agent 不得自行缓解。" if requires_human else "可由 Agent 执行标准缓解动作。")
        ),
        requires_human=requires_human,
        blockers=blockers,
    )


def evaluate_rollback(*, service: dict, deployments: list[dict], incident: dict, now: str | datetime) -> RollbackDecision:
    """Is reverting the last deploy the right call — and is the agent allowed to do it?"""
    now_dt = parse_ts(now)
    if not deployments:
        return RollbackDecision(False, None, "no_deployments", "该服务没有部署记录，回滚无从谈起。", blockers=["no_deployments"])

    latest = sorted(deployments, key=lambda d: d["finished_at"], reverse=True)[0]
    age = (now_dt - parse_ts(latest["finished_at"])) / timedelta(minutes=1)
    blast = int(service.get("blast_radius", 0) or 0)
    blockers: list[str] = []

    if str(incident.get("severity", "")).lower() in FREEZE_SEVERITIES:
        blockers.append("change_freeze")
    if blast > BLAST_RADIUS_LIMIT:
        blockers.append("blast_radius")
    if age > ROLLBACK_MAX_AGE_MINUTES:
        return RollbackDecision(
            False,
            latest["id"],
            "deploy_too_old",
            f"最近一次部署已在 {age:.0f} 分钟前，回滚它会连带撤掉期间所有变更，风险大于收益；应向前修复。",
            blockers=blockers + ["stale_deploy"],
        )

    requires_human = bool(blockers)
    return RollbackDecision(
        allowed=not requires_human,
        target_deployment=latest["id"],
        reason_code="recent_deploy_suspect" if not requires_human else "rollback_gated",
        explanation=(
            f"部署 {latest['id']} 完成于 {age:.0f} 分钟前，时间上高度吻合故障起点"
            + (f"；但 {'/'.join(blockers)} 触发人工闸门，Agent 不得自动回滚。" if requires_human else "；可自动回滚。")
        ),
        requires_human=requires_human,
        blockers=blockers,
    )


def runbook_required_steps(*, incident: dict, mitigation_taken: list[str]) -> list[str]:
    """What a post-incident review still owes. Graded against state, not prose."""
    severity = str(incident.get("severity", "sev4")).lower()
    owed: list[str] = []
    if severity in {"sev1", "sev2"} and "acknowledge" not in mitigation_taken:
        owed.append("sev1/sev2 必须有人类确认接单（acknowledge_incident）")
    if severity in {"sev1", "sev2"} and "review" not in mitigation_taken:
        owed.append("sev1/sev2 必须登记复盘条目（record_review）")
    if "customer_impact" in (incident.get("tags") or []) and "notify_status_page" not in mitigation_taken:
        owed.append("影响客户的故障必须更新状态页（notify_status_page）")
    return owed
