# 升级与人工接管（Escalation）

## 必须升级人工的情形
1. compute_refund 返回 requires_approval = true（退款金额超过 ¥200 审批线）。
2. 客户 risk_score ≥ 80。
3. 政策窗口已过但客户为 PLATINUM 或提出投诉监管渠道（12315 / 媒体）。
4. 需要跨部门动作：仓储补发、物流拦截、财务对账。
5. 客户诉求与政策直接冲突，Agent 无裁量空间。

## 升级方式
调用 escalate_ticket(ticket_id, team, note)，note 必须包含：已核实事实、政策依据、候选方案、建议动作。
升级后工单状态为 escalated，不得再自行执行退款或发券。

## 人工审批（HITL）
高风险动作会挂起等待审批，审批结果回传后按结论继续：
批准 → 按核定金额执行；拒绝 → 不得重试同一动作，改走升级或结单说明。

## 信息不足
客户未提供订单号但提供手机号时，先用 list_orders_by_phone 定位订单，不要凭空猜测订单号。
无法定位对象时，工单置为 pending_info 并向客户提问，禁止臆造 ID。
