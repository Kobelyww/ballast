"""Distillation: a verified trace becomes a candidate skill card.

The input is an episode whose grade is *known good*, so the card records a procedure
that actually worked rather than a model's retelling of what it thinks it did. The
output is always `status="candidate"` — distillation is allowed to be cheap because
promotion is what costs evidence.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from typing import Any

from ..memory.skills import Skill

READ_TOOLS = {"get_ticket", "get_order", "get_customer", "search_sop", "compute_refund", "check_coupon_eligibility", "list_tickets", "list_orders_by_phone"}
FAMILY_TRIGGERS = {
    # Ops families: the failure the guardrail exists to stop is paging or reverting
    # without first asking the policy engine.
    "rollback": ["TRIGGER:force_escalation_assessment"],
    "paging": ["TRIGGER:force_escalation_assessment"],
    "escalation": ["TRIGGER:force_escalation_assessment"],
    "refund_window": ["TRIGGER:force_compute_refund"],
    "missing_item": ["TRIGGER:force_compute_refund"],
    "quality_claim": ["TRIGGER:force_compute_refund"],
    "risk_control": ["TRIGGER:force_compute_refund"],
    "category_rules": ["TRIGGER:force_compute_refund"],
}

PROCEDURE_LABEL = {
    "get_ticket": "读取工单原文，确认诉求与关联订单",
    "list_orders_by_phone": "用手机号定位订单，不要臆造订单号",
    "get_order": "读取订单明细（品类、数量、已送达数量、运费）",
    "get_customer": "读取客户等级与风险分",
    "search_sop": "检索适用的政策章节并记下 section id",
    "compute_refund": "调用 compute_refund 取得核定金额与合规结论",
    "issue_refund": "仅按核定金额执行 issue_refund",
    "send_coupon": "在等级上限内发放补偿券",
    "escalate_ticket": "按政策不可自动执行时，携带事实与依据升级人工",
    "close_ticket": "结单并引用政策章节与确切金额",
    "flag_risk": "记录风控标记",
}

PITFALL_LABEL = {
    "missing_computation": "跳过 compute_refund 直接退款会被护栏拒绝",
    "amount_mismatch": "自行计算的金额与核定金额不一致会被拒绝",
    "policy_denied": "政策禁止时重试退款是无效动作",
    "escalation_required": "高风险客户必须转人工，不能自动放款",
    "summary_incomplete": "结单说明未引用政策章节会被退回",
    "coupon_denied": "补偿券超出等级上限会被拒绝",
}


def topic_terms(text: str, limit: int = 14) -> str:
    """Domain keywords for the card, taken from the task it was distilled on.

    Without these a card is only retrievable by tool-name overlap, and the model's
    own phrasing never looks like a tool name.
    """
    from ..support.bm25 import tokenize

    counts: Counter[str] = Counter()
    for token in tokenize(text):
        if len(token) >= 2 or any("\u4e00" <= ch <= "\u9fff" for ch in token):
            counts[token] += 1
    stop = {"请", "的", "了", "和", "在", "是", "有", "我", "你", "他", "工单", "客户"}
    return " ".join(t for t, _ in counts.most_common(limit * 2) if t not in stop and len(t) >= 2)[:180]


def distill(episode: dict[str, Any], *, family: str = "", task_text: str = "") -> Skill | None:
    """episode = {"events": [...], "scenario_id": ..., "run_id": ..., "guardrails": [...]}"""
    events = episode.get("events") or []
    sequence: "OrderedDict[str, int]" = OrderedDict()
    for event in events:
        if event.get("type") == "tool_call":
            name = str(event.get("payload", {}).get("name", ""))
            if name:
                sequence[name] = sequence.get(name, 0) + 1
    tools = list(sequence)
    if len(tools) < 3:
        return None

    blocked = sorted({str(e["payload"].get("code")) for e in events if e.get("type") == "guardrail_block"})
    cited = next(
        (str(hit) for e in events if e.get("type") == "tool_result" for hit in _sections(e)),
        "",
    )
    kind = "caution" if blocked and all(t in READ_TOOLS for t in tools) else "procedure"
    triggers = FAMILY_TRIGGERS.get(family, [])
    name = f"{family or 'procedure'}: " + " → ".join(tools[:6])
    return Skill(
        name=name[:120],
        kind=kind,  # type: ignore[arg-type]
        family=family,
        when_to_use=" ".join(
            filter(
                None,
                [
                    f"处理 {family} 类售后工单（无理由退款 / 缺件 / 质量问题）时套用：先核定政策再动钱。",
                    f"参考政策章节 {cited}。" if cited else "",
                    *triggers,
                ],
            )
        ),
        procedure=[PROCEDURE_LABEL.get(t, t) + (f"（重复 {sequence[t]} 次，合并为一次）" if sequence[t] > 1 else "") for t in tools],
        tools=tools,
        pitfalls=[PITFALL_LABEL.get(code, code) for code in blocked] or ["不要在缺少政策依据时结单"],
        keywords=" ".join([family, " ".join(tools), topic_terms(task_text or episode.get("task", "") or "")]),
        status="candidate",
        source_run=str(episode.get("run_id", "")),
        evidence={"distilled_from": str(episode.get("scenario_id", "")), "tool_count": len(tools), "guardrails_seen": blocked},
    )


def _sections(event: dict[str, Any]) -> list[str]:
    import json

    payload = event.get("payload", {}) or {}
    content = str(payload.get("content", ""))
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    hits = data.get("hits") if isinstance(data, dict) else None
    return [str(h.get("id")) for h in hits or [] if isinstance(h, dict) and h.get("id")]
