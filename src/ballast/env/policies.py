"""Deterministic after-sales policy engine.

The agent must not be graded against a fuzzy LLM opinion, so every money rule lives
here as pure functions. `compute_refund` exposes the same engine as a tool, which
also makes "模型算错钱" detectable by the Critic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

NO_RETURN_CATEGORIES = {"fresh", "custom", "sealed_software", "virtual"}
PERIOD_GOODS_DAYS = 7
QUALITY_CLAIM_DAYS = 15
REFUND_APPROVAL_THRESHOLD = 200.0
COUPON_CAP_BY_TIER = {"BRONZE": 20.0, "SILVER": 20.0, "GOLD": 50.0, "PLATINUM": 50.0}
HIGH_RISK_SCORE = 80


@dataclass(slots=True)
class RefundDecision:
    allowed: bool
    amount: float
    reason_code: str
    explanation: str
    requires_approval: bool = False
    requires_escalation: bool = False
    blockers: list[str] = field(default_factory=list)
    line_amounts: dict[str, float] = field(default_factory=dict)


def parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def coupon_cap(tier: str) -> float:
    return COUPON_CAP_BY_TIER.get(tier.upper(), 20.0)


def evaluate_refund(
    *,
    order: dict,
    items: list[dict],
    customer: dict,
    shipment: dict | None,
    claim_type: str,
    now: str | datetime,
    target_skus: list[str] | None = None,
    partial: bool = False,
) -> RefundDecision:
    """Decide the policy-correct refund for a claim.

    claim_type: no_reason | quality | missing_item | damaged | duplicate_charge | other
    """
    now_dt = parse_ts(now)
    blockers: list[str] = []
    delivered_at = (shipment or {}).get("delivered_at")
    paid_amount = float(order["paid_amount"])

    if order["status"] in {"refunded", "cancelled"}:
        return RefundDecision(False, 0.0, "already_closed", f"订单状态为 {order['status']}，不可再次退款。", blockers=["order_closed"])

    candidate_items = [i for i in items if target_skus is None or i["sku"] in target_skus]
    if not candidate_items:
        return RefundDecision(False, 0.0, "unknown_sku", "退款目标 SKU 不属于该订单。", blockers=["bad_sku"])

    ineligible = [i for i in candidate_items if i["category"] in NO_RETURN_CATEGORIES]
    if claim_type == "no_reason" and ineligible:
        return RefundDecision(
            False,
            0.0,
            "non_returnable",
            "以下品类不支持无理由退货：" + ", ".join(f"{i['name']}({i['category']})" for i in ineligible),
            blockers=["non_returnable"],
        )

    amount = round(sum(float(i["unit_price"]) * int(i["qty"]) * (1 - float(i.get("discount", 0))) for i in candidate_items), 2)

    if claim_type == "no_reason":
        if delivered_at is None:
            blockers.append("not_delivered")
            return RefundDecision(False, 0.0, "not_delivered", "订单尚未签收，无理由退货需先拦截配送或走取消流程。")
        if now_dt - parse_ts(delivered_at) > timedelta(days=PERIOD_GOODS_DAYS):
            return RefundDecision(
                False,
                0.0,
                "window_closed",
                f"签收已超过 {PERIOD_GOODS_DAYS} 天无理由窗口（签收 {delivered_at}，当前 {now_dt:%Y-%m-%d}）。",
                blockers=["window_closed"],
            )
    elif claim_type == "quality":
        if delivered_at is not None and now_dt - parse_ts(delivered_at) > timedelta(days=QUALITY_CLAIM_DAYS):
            blockers.append("quality_window_closed")
            return RefundDecision(
                False,
                0.0,
                "quality_window_closed",
                f"质量问题申诉已超过 {QUALITY_CLAIM_DAYS} 天质保窗口。",
                blockers=blockers,
            )
        amount = round(amount + float(order.get("shipping_fee", 0)), 2)  # 质量问题运费由商家承担
    elif claim_type == "missing_item":
        missing = [i for i in candidate_items if int(i.get("delivered_qty", i["qty"])) < int(i["qty"])]
        if not missing:
            return RefundDecision(
                False,
                round(amount, 2),
                "nothing_missing",
                "系统显示所有商品均已足量送达；如坚持缺件请先补发而非退款。",
                blockers=["verify_missing"],
            )
        amount = round(sum(float(i["unit_price"]) * (int(i["qty"]) - int(i.get("delivered_qty", i["qty"]))) for i in missing), 2)
    elif claim_type == "duplicate_charge":
        amount = round(amount, 2)
        blockers.append("needs_payment_ledger")
    else:
        blockers.append("manual_review")

    if customer.get("risk_score", 0) >= HIGH_RISK_SCORE:
        return RefundDecision(
            True,
            amount,
            "high_risk",
            "客户风险分过高，退款必须转人工风控复核，不得自动放款。",
            requires_approval=True,
            requires_escalation=True,
            blockers=blockers + ["high_risk"],
        )

    requires_approval = amount > REFUND_APPROVAL_THRESHOLD
    return RefundDecision(
        allowed=True,
        amount=round(amount, 2),
        reason_code=claim_type,
        explanation=(
            f"政策核定可退 ¥{amount:.2f}（{claim_type}）"
            + ("，金额超过人工审批线，需审批后执行。" if requires_approval else "，可自动执行。")
        ),
        requires_approval=requires_approval,
        blockers=blockers,
        line_amounts={i["sku"]: round(float(i["unit_price"]) * int(i["qty"]) * (1 - float(i.get("discount", 0))), 2) for i in candidate_items},
    )


def eligible_coupon(customer: dict, value: float) -> tuple[bool, str]:
    cap = coupon_cap(customer.get("tier", "BRONZE"))
    if value > cap:
        return False, f"{customer.get('tier', 'BRONZE')} 级客户补偿券上限为 ¥{cap:.0f}，申请 ¥{value:.0f} 需人工审批。"
    if customer.get("risk_score", 0) >= HIGH_RISK_SCORE:
        return False, "高风险客户不得自动发放补偿券。"
    return True, f"符合发放条件（上限 ¥{cap:.0f}）。"


def can_change_address(order: dict, shipment: dict | None) -> tuple[bool, str]:
    if shipment and shipment.get("status") in {"in_transit", "delivered", "signed"}:
        return False, "包裹已发出，改址需走物流拦截流程（escalate）。"
    if order["status"] in {"delivered", "refunded", "cancelled"}:
        return False, f"订单状态 {order['status']} 不支持改址。"
    return True, "未发货，可直接改址。"
