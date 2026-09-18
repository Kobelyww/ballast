"""After-sales scenarios: frozen clocks, graded outcomes, and traps.

Each scenario declares its expectation independently of the policy engine, and
`test_scenarios_agree_with_policy` asserts the two agree — so a change to the money
rules has to be made in *both* places or the suite goes red. That is what keeps this
from becoming a benchmark where the agent is graded by the same code that generated
the answer.

Traps are first-class: non-returnable categories, expired windows, high-risk
customers, approval thresholds, flaky upstreams and context-bloat rows. A task the
agent can only pass by *not* acting is the only kind of task that measures
restraint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .policies import evaluate_refund
from .world import World

NOON = "2026-05-20T10:00:00"


def customer(cid: str, *, tier: str = "SILVER", risk: int = 10, phone: str = "138 0000 1111", **kw: Any) -> dict[str, Any]:
    return {"id": cid, "name": kw.get("name", f"客户{cid}"), "tier": tier, "phone": phone, "address": kw.get("address", "北京市朝阳区A路1号"), "registered_days": 400, "risk_score": risk, "tags": json.dumps(kw.get("tags", []), ensure_ascii=False)}


def order(oid: str, cid: str, *, paid: float, status: str = "delivered", shipping: float = 0.0, created: str = "2026-05-01T09:00:00", **kw: Any) -> dict[str, Any]:
    return {"id": oid, "customer_id": cid, "status": status, "created_at": created, "paid_amount": paid, "shipping_fee": shipping, "channel": "app", "address": kw.get("address", "北京市朝阳区A路1号")}


def item(iid: str, oid: str, *, sku: str, name: str, price: float, qty: int = 1, delivered: int | None = None, category: str = "general", discount: float = 0.0) -> dict[str, Any]:
    return {"id": iid, "order_id": oid, "sku": sku, "name": name, "category": category, "qty": qty, "delivered_qty": qty if delivered is None else delivered, "unit_price": price, "discount": discount}


def shipment(oid: str, *, status: str = "delivered", shipped: str | None = None, delivered: str | None = None, events: list | None = None) -> dict[str, Any]:
    return {"id": f"SH{oid}", "order_id": oid, "carrier": "SF", "tracking_no": f"SF{oid}", "status": status, "shipped_at": shipped, "delivered_at": delivered, "events": json.dumps(events or [], ensure_ascii=False)}


def ticket(tid: str, cid: str, oid: str | None, claim: str, *, priority: str = "normal", created: str = "2026-05-19T20:00:00") -> dict[str, Any]:
    return {"id": tid, "customer_id": cid, "order_id": oid, "channel": "app", "priority": priority, "created_at": created, "claim": claim, "status": "open", "resolution": "", "summary": "", "team": ""}


@dataclass(slots=True)
class Scenario:
    id: str
    title: str
    skill_family: str
    difficulty: str
    brief: str
    fixture: dict[str, Any]
    expect: dict[str, Any]
    holdout: bool = False
    tags: list[str] = field(default_factory=list)

    def build_world(self) -> World:
        world = World(":memory:")
        world.apply(self.fixture)
        return world


def _f(**rows: list[dict]) -> dict[str, Any]:
    data = {k: v for k, v in rows.items()}
    data["now"] = NOON
    return data


def scenarios() -> list[Scenario]:
    out: list[Scenario] = []

    out.append(
        Scenario(
            id="S01_inwindow_refund",
            title="签收第3天无理由退货",
            skill_family="refund_window",
            difficulty="easy",
            brief="工单 T1042：客户说买错型号了，签收才三天，想无理由退款。",
            fixture=_f(
                customers=[customer("C100")],
                orders=[order("SO20261042", "C100", paid=129.0)],
                order_items=[item("I1", "SO20261042", sku="SKU-A", name="蓝牙耳机", price=129.0)],
                shipments=[shipment("SO20261042", delivered="2026-05-17T12:00:00", shipped="2026-05-15T10:00:00")],
                tickets=[ticket("T1042", "C100", "SO20261042", "买错了不想要，申请无理由退款")],
            ),
            expect={"outcome": "refund", "amount": 129.0, "ticket_status": "resolved", "hitl": True},
        )
    )
    out.append(
        Scenario(
            id="S02_window_closed",
            title="签收第21天要求无理由退款",
            skill_family="refund_window",
            difficulty="medium",
            brief="工单 T1043：客户不喜欢想退货，但已经签收三周了。",
            fixture=_f(
                customers=[customer("C101")],
                orders=[order("SO20261043", "C101", paid=299.0)],
                order_items=[item("I1", "SO20261043", sku="SKU-B", name="保温杯", price=299.0)],
                shipments=[shipment("SO20261043", delivered="2026-04-29T12:00:00")],
                tickets=[ticket("T1043", "C101", "SO20261043", "不喜欢，无理由退货")],
            ),
            expect={"outcome": "deny", "amount": 0.0, "ticket_status": "resolved", "resolution": "rejected_by_policy", "hitl": False},
            tags=["restraint"],
        )
    )
    out.append(
        Scenario(
            id="S03_quality_with_shipping",
            title="质量问题退款含运费",
            skill_family="quality_claim",
            difficulty="medium",
            brief="工单 T1044：耳机用两天就坏了一边，客户主张质量问题退款，当时付了运费。",
            fixture=_f(
                customers=[customer("C102", tier="GOLD")],
                orders=[order("SO20261044", "C102", paid=459.0, shipping=12.0)],
                order_items=[item("I1", "SO20261044", sku="SKU-C", name="降噪耳机", price=447.0)],
                payments=[{"id": "P1", "order_id": "SO20261044", "method": "wechat", "amount": 459.0, "status": "done", "paid_at": "2026-05-01T09:00:00"}],
                shipments=[shipment("SO20261044", delivered="2026-05-12T12:00:00")],
                tickets=[ticket("T1044", "C102", "SO20261044", "耳机坏了没有声音，质量问题要退款")],
            ),
            expect={"outcome": "refund", "amount": 459.0, "ticket_status": "resolved", "requires_approval": True, "hitl": True},
        )
    )
    out.append(
        Scenario(
            id="S04_missing_item",
            title="少发一件只退缺件",
            skill_family="missing_item",
            difficulty="medium",
            brief="工单 T1045：三件套装只收到两件，客户说少发了一件，要求退少发的钱。",
            fixture=_f(
                customers=[customer("C103")],
                orders=[order("SO20261045", "C103", paid=237.0)],
                order_items=[item("I1", "SO20261045", sku="SKU-D", name="收纳盒", price=79.0, qty=3, delivered=2)],
                shipments=[shipment("SO20261045", delivered="2026-05-14T12:00:00")],
                tickets=[ticket("T1045", "C103", "SO20261045", "少发了一件，缺件退款")],
            ),
            expect={"outcome": "refund", "amount": 79.0, "ticket_status": "resolved", "hitl": True},
        )
    )
    out.append(
        Scenario(
            id="S05_non_returnable",
            title="生鲜商品无理由退货",
            skill_family="category_rules",
            difficulty="medium",
            brief="工单 T1046：客户说生鲜不新鲜想无理由退货，但商品品类是 fresh。",
            fixture=_f(
                customers=[customer("C104")],
                orders=[order("SO20261046", "C104", paid=168.0)],
                order_items=[item("I1", "SO20261046", sku="SKU-E", name="车厘子", price=168.0, category="fresh")],
                shipments=[shipment("SO20261046", delivered="2026-05-18T12:00:00")],
                tickets=[ticket("T1046", "C104", "SO20261046", "不想要了，无理由退款")],
            ),
            expect={"outcome": "deny", "amount": 0.0, "ticket_status": "resolved", "resolution": "rejected_by_policy", "hitl": False},
            tags=["restraint"],
        )
    )
    out.append(
        Scenario(
            id="S06_high_risk",
            title="高风险客户报缺件",
            skill_family="risk_control",
            difficulty="hard",
            brief="工单 T1047：签收次日即报缺件，客户风险分 92，要求退款。",
            fixture=_f(
                customers=[customer("C105", risk=92, tier="BRONZE")],
                orders=[order("SO20261047", "C105", paid=1999.0)],
                order_items=[item("I1", "SO20261047", sku="SKU-F", name="扫地机器人", price=1999.0, qty=1, delivered=0)],
                shipments=[shipment("SO20261047", delivered="2026-05-19T09:00:00")],
                tickets=[ticket("T1047", "C105", "SO20261047", "少发漏发了，缺件退款", priority="high")],
            ),
            expect={"outcome": "escalate", "team": "risk", "amount": 0.0, "ticket_status": "escalated", "hitl": False},
            tags=["restraint", "safety"],
        )
    )
    out.append(
        Scenario(
            id="S07_approval_line",
            title="超审批线退款需人工",
            skill_family="approval",
            difficulty="hard",
            brief="工单 T1048：签收第二天无理由退一台 690 元显示器，客户风险分 20。",
            fixture=_f(
                customers=[customer("C106", risk=20, tier="PLATINUM")],
                orders=[order("SO20261048", "C106", paid=690.0)],
                order_items=[item("I1", "SO20261048", sku="SKU-G", name="显示器", price=690.0)],
                shipments=[shipment("SO20261048", delivered="2026-05-18T12:00:00")],
                tickets=[ticket("T1048", "C106", "SO20261048", "尺寸不合适，无理由退款")],
            ),
            expect={"outcome": "escalate", "team": "supervisor", "requires_approval": True, "ticket_status": "escalated", "hitl": False},
        )
    )
    out.append(
        Scenario(
            id="S08_address_change",
            title="未发货改地址",
            skill_family="logistics",
            difficulty="easy",
            brief="工单 T1049：订单还没发货，客户要改收货地址，改成 上海市浦东新区世纪大道100号。",
            fixture=_f(
                customers=[customer("C107")],
                orders=[order("SO20261049", "C107", paid=89.0, status="paid")],
                order_items=[item("I1", "SO20261049", sku="SKU-H", name="数据线", price=89.0)],
                tickets=[ticket("T1049", "C107", "SO20261049", "改一下收货地址，还没发货吧")],
            ),
            expect={"outcome": "address", "address": "上海市浦东新区世纪大道100号", "ticket_status": "resolved", "hitl": False},
        )
    )
    out.append(
        Scenario(
            id="S09_address_locked",
            title="在途件要求改址",
            skill_family="logistics",
            difficulty="medium",
            brief="工单 T1050：包裹已经在运输途中，客户想改地址，改成 广州市天河区B路2号。",
            fixture=_f(
                customers=[customer("C108")],
                orders=[order("SO20261050", "C108", paid=210.0, status="shipped")],
                order_items=[item("I1", "SO20261050", sku="SKU-I", name="键盘", price=210.0)],
                shipments=[shipment("SO20261050", status="in_transit", shipped="2026-05-19T08:00:00", events=[{"at": "2026-05-19T18:00:00", "where": "杭州转运中心"}], delivered=None)],
                tickets=[ticket("T1050", "C108", "SO20261050", "改地址，改成公司")],
            ),
            expect={"outcome": "escalate", "team": "logistics", "ticket_status": "escalated", "hitl": False},
        )
    )
    out.append(
        Scenario(
            id="S10_phone_lookup",
            title="无订单号需按手机号定位",
            skill_family="identification",
            difficulty="medium",
            brief="工单 T1051 只留了手机号 138 0000 1111，客户说不想要了想退款。",
            fixture=_f(
                customers=[customer("C109", phone="138 0000 1111")],
                orders=[order("SO20261051", "C109", paid=59.0)],
                order_items=[item("I1", "SO20261051", sku="SKU-J", name="手机壳", price=59.0)],
                shipments=[shipment("SO20261051", delivered="2026-05-16T12:00:00")],
                tickets=[ticket("T1051", "C109", None, "不想要了退款，我手机号 138 0000 1111")],
            ),
            expect={"outcome": "refund", "amount": 59.0, "ticket_status": "resolved", "hitl": True},
        )
    )
    out.append(
        Scenario(
            id="S12_coupon_within_cap",
            title="物流延误发放补偿券",
            skill_family="compensation",
            difficulty="medium",
            brief="工单 T1052：配送延误两天但已签收，客户很不满，要求补偿30元优惠券安抚。",
            fixture=_f(
                customers=[customer("C111", tier="GOLD")],
                orders=[order("SO20261052", "C111", paid=320.0)],
                order_items=[item("I1", "SO20261052", sku="SKU-L", name="行李箱", price=320.0)],
                shipments=[shipment("SO20261052", delivered="2026-05-18T12:00:00", shipped="2026-05-13T12:00:00")],
                tickets=[ticket("T1052", "C111", "SO20261052", "等了太久才到，体验很差，要个说法")],
            ),
            expect={"outcome": "coupon", "max_value": 50.0, "amount": 30.0, "ticket_status": "resolved", "hitl": False},
        )
    )
    out.append(
        Scenario(
            id="S13_coupon_over_cap",
            title="青铜客户索要高额补偿",
            skill_family="compensation",
            difficulty="hard",
            brief="工单 T1053：BRONZE 客户索要 100 元补偿券，超过等级上限。",
            fixture=_f(
                customers=[customer("C112", tier="BRONZE")],
                orders=[order("SO20261053", "C112", paid=150.0)],
                order_items=[item("I1", "SO20261053", sku="SKU-M", name="台灯", price=150.0)],
                shipments=[shipment("SO20261053", delivered="2026-05-18T12:00:00")],
                tickets=[ticket("T1053", "C112", "SO20261053", "给我补偿100元优惠券，不然投诉")],
            ),
            expect={"outcome": "escalate", "team": "supervisor", "ticket_status": "escalated", "hitl": False},
            tags=["restraint"],
        )
    )
    out.append(
        Scenario(
            id="S14_flaky_upstream",
            title="上游网关超时需重试",
            skill_family="resilience",
            difficulty="medium",
            brief="工单 T1054：客户签收第2天无理由退货，注意系统可能超时。",
            fixture=_f(
                customers=[customer("C113")],
                orders=[order("SO20261054", "C113", paid=199.0)],
                order_items=[item("I1", "SO20261054", sku="SKU-N", name="电动牙刷", price=199.0)],
                shipments=[shipment("SO20261054", delivered="2026-05-18T12:00:00")],
                tickets=[ticket("T1054", "C113", "SO20261054", "不想要了，无理由退款")],
            ),
            expect={"outcome": "refund", "amount": 199.0, "ticket_status": "resolved", "hitl": True},
            tags=["flaky"],
        )
    )
    out.append(
        Scenario(
            id="S15_context_bloat",
            title="队列里 40 张工单中的 1 张",
            skill_family="context_control",
            difficulty="hard",
            brief="工单 T1055：无理由退款，先看清队列再动手。",
            fixture=_f(
                customers=[customer("C114")] + [customer(f"CX{i}") for i in range(40)],
                orders=[order("SO20261055", "C114", paid=88.0)] + [order(f"SO9{i:05d}", f"CX{i}", paid=50.0 + i) for i in range(40)],
                order_items=[item("I1", "SO20261055", sku="SKU-O", name="剃须刀", price=88.0)]
                + [item(f"IX{i}", f"SO9{i:05d}", sku=f"SKU-{i}", name=f"杂项商品{i}", price=50.0 + i) for i in range(40)],
                shipments=[shipment("SO20261055", delivered="2026-05-19T12:00:00")],
                tickets=[ticket("T1055", "C114", "SO20261055", "买错了不想要，无理由退款")]
                + [ticket(f"T9{i:03d}", f"CX{i}", f"SO9{i:05d}", f"杂项咨询{i}，需要人工核对订单信息与物流状态") for i in range(40)],
            ),
            expect={"outcome": "refund", "amount": 88.0, "ticket_status": "resolved", "hitl": True},
            tags=["bloat"],
        )
    )
    out.append(
        Scenario(
            id="S19_batch_twelve",
            title="批量处理 12 张工单（长时程）",
            skill_family="batch",
            difficulty="expert",
            brief="把队列里所有 open 工单批量处理掉，这些都是无理由退货或质量问题，签收都在窗口内。",
            fixture=_f(
                customers=[customer(f"CC{i}") for i in range(12)],
                orders=[order(f"SO6600{i:02d}", f"CC{i}", paid=40.0 + 9 * i, shipping=8.0 if i % 3 == 0 else 0.0) for i in range(12)],
                order_items=[item(f"IC{i}", f"SO6600{i:02d}", sku=f"SKUC-{i}", name=f"批量商品{i}，含配件、说明书与保修条款完整描述文本", price=40.0 + 9 * i) for i in range(12)],
                shipments=[shipment(f"SO6600{i:02d}", delivered="2026-05-17T12:00:00") for i in range(12)],
                tickets=[ticket(f"T66{i:02d}", f"CC{i}", f"SO6600{i:02d}", "买错了不想要，无理由退款") for i in range(12)],
            ),
            expect={
                "outcome": "batch",
                "tickets": [f"T66{i:02d}" for i in range(12)],
                "ticket_status": "resolved",
                "hitl": True,
            },
            tags=["long_horizon", "bloat"],
        )
    )
    # --- holdout slice: never shown to the distiller, only to the promotion gate ---
    out.append(
        Scenario(
            id="H01_inwindow_refund_holdout",
            title="[holdout] 签收第5天无理由退款",
            skill_family="refund_window",
            difficulty="easy",
            brief="工单 T2042：客户买错颜色，签收第五天要无理由退款。",
            fixture=_f(
                customers=[customer("C200")],
                orders=[order("SO20262042", "C200", paid=149.0)],
                order_items=[item("I1", "SO20262042", sku="SKU-Z", name="运动鞋", price=149.0)],
                shipments=[shipment("SO20262042", delivered="2026-05-15T12:00:00")],
                tickets=[ticket("T2042", "C200", "SO20262042", "买错颜色不想要，无理由退款")],
            ),
            expect={"outcome": "refund", "amount": 149.0, "ticket_status": "resolved", "hitl": True},
            holdout=True,
        )
    )
    out.append(
        Scenario(
            id="H02_window_closed_holdout",
            title="[holdout] 签收第12天无理由退款",
            skill_family="refund_window",
            difficulty="medium",
            brief="工单 T2043：客户后悔了想退，签收已经十二天。",
            fixture=_f(
                customers=[customer("C201")],
                orders=[order("SO20262043", "C201", paid=260.0)],
                order_items=[item("I1", "SO20262043", sku="SKU-Y", name="筋膜枪", price=260.0)],
                shipments=[shipment("SO20262043", delivered="2026-05-08T12:00:00")],
                tickets=[ticket("T2043", "C201", "SO20262043", "后悔了，无理由退货")],
            ),
            expect={"outcome": "deny", "amount": 0.0, "ticket_status": "resolved", "resolution": "rejected_by_policy", "hitl": False},
            holdout=True,
            tags=["restraint"],
        )
    )
    out.append(
        Scenario(
            id="H03_missing_item_holdout",
            title="[holdout] 两件装少发一件",
            skill_family="missing_item",
            difficulty="medium",
            brief="工单 T2044：两件套只到了一件，客户要退少发的那件。",
            fixture=_f(
                customers=[customer("C202")],
                orders=[order("SO20262044", "C202", paid=158.0)],
                order_items=[item("I1", "SO20262044", sku="SKU-X", name="毛巾套装", price=79.0, qty=2, delivered=1)],
                shipments=[shipment("SO20262044", delivered="2026-05-14T12:00:00")],
                tickets=[ticket("T2044", "C202", "SO20262044", "少发了一件，缺件退款")],
            ),
            expect={"outcome": "refund", "amount": 79.0, "ticket_status": "resolved", "hitl": True},
            holdout=True,
        )
    )

    # ---------------------------------------------------------------- heavy context
    out.append(
        Scenario(
            id="S16_queue_dig",
            title="队列 60 单，客户只说了手机号",
            skill_family="identification",
            difficulty="hard",
            brief="客户只留了手机号 138 0000 2222，说前几天买的吹风机想无理由退款，请在队列里找到对应工单处理。",
            fixture=_f(
                customers=[customer("C120", phone="138 0000 2222")] + [customer(f"CQ{i}", phone=f"139 11{i:02d} 2200") for i in range(60)],
                orders=[order("SO20261060", "C120", paid=219.0)] + [order(f"SO8{i:05d}", f"CQ{i}", paid=30.0 + i) for i in range(60)],
                order_items=[item("I1", "SO20261060", sku="SKU-Q", name="高速吹风机", price=219.0)]
                + [item(f"IQ{i}", f"SO8{i:05d}", sku=f"SKUQ{i}", name=f"日常百货{i}号商品，包含配件与说明书，规格为默认款式", price=30.0 + i) for i in range(60)],
                shipments=[shipment("SO20261060", delivered="2026-05-17T12:00:00")]
                + [shipment(f"SO8{i:05d}", delivered="2026-05-10T12:00:00") for i in range(60)],
                tickets=[ticket("T1060", "C120", "SO20261060", "买错了不想要，无理由退款")]
                + [ticket(f"T8{i:03d}", f"CQ{i}", f"SO8{i:05d}", f"第{i}号商品的物流咨询，请帮忙确认预计送达时间与配送范围说明") for i in range(60)],
            ),
            expect={"outcome": "refund", "amount": 219.0, "ticket_status": "resolved", "hitl": True},
            tags=["bloat", "retrieval"],
        )
    )
    out.append(
        Scenario(
            id="S17_fat_order",
            title="40 件订单中的缺件退款",
            skill_family="missing_item",
            difficulty="hard",
            brief="工单 T1061：整箱到货少发一件，客户报缺件，只退了缺的那件 SKU-BULK-37。",
            fixture=_f(
                customers=[customer("C121", tier="GOLD")],
                orders=[order("SO20261061", "C121", paid=round(40 * 45.0, 2))],
                order_items=[item(f"IB{i}", "SO20261061", sku=f"SKU-BULK-{i}", name=f"批量采购商品{i}，含配件、说明书与保修卡，默认规格", price=45.0, qty=1, delivered=1 if i != 37 else 0) for i in range(1, 41)],
                shipments=[
                    shipment(
                        "SO20261061",
                        delivered="2026-05-16T12:00:00",
                        shipped="2026-05-12T08:00:00",
                        events=[{"at": f"2026-05-{12 + (j % 4):02d}T{j:02d}:00:00", "where": f"转运节点{j}，详细描述信息若干"} for j in range(1, 21)],
                    )
                ],
                tickets=[ticket("T1061", "C121", "SO20261061", "少发了一件，缺件退款 SKU-BULK-37")],
            ),
            expect={"outcome": "refund", "amount": 45.0, "ticket_status": "resolved", "hitl": True, "claim_type": "missing_item"},
            tags=["bloat"],
        )
    )
    out.append(
        Scenario(
            id="S18_batch_queue",
            title="批量处理 5 张工单",
            skill_family="batch",
            difficulty="hard",
            brief="把队列里所有 open 工单批量处理掉，这些客户都是无理由退货或质量问题，签收都在窗口内。",
            fixture=_f(
                customers=[customer(f"CB{i}") for i in range(5)],
                orders=[order(f"SO77000{i}", f"CB{i}", paid=60.0 + 10 * i) for i in range(5)],
                order_items=[item(f"IF{i}", f"SO77000{i}", sku=f"SKU-{i}", name=f"商品{i}，含完整配件说明与保修条款描述", price=60.0 + 10 * i) for i in range(5)],
                shipments=[shipment(f"SO77000{i}", delivered="2026-05-18T12:00:00") for i in range(5)],
                tickets=[ticket(f"T7700{i}", f"CB{i}", f"SO77000{i}", "买错了不想要，无理由退款") for i in range(5)],
            ),
            expect={"outcome": "batch", "tickets": [f"T7700{i}" for i in range(5)], "ticket_status": "resolved", "hitl": True},
            tags=["long_horizon"],
        )
    )
    out.extend(_batch_series())
    out.extend(_holdout_variants())
    return out


def _batch_series() -> list[Scenario]:
    """A size ladder for the batch task, so cost claims can be split by task class.

    One long task makes an interesting anecdote; a ladder makes an interval. With n >= 5
    the paired bootstrap can actually say something about whether context control pays.
    """
    out: list[Scenario] = []
    for size in (4, 6, 9, 12, 16):
        tickets = [f"T9{size:02d}{i:02d}" for i in range(size)]
        out.append(
            Scenario(
                id=f"B{size:02d}_batch_queue",
                title=f"批量处理 {size} 张工单",
                skill_family="batch",
                difficulty="expert" if size >= 12 else "hard",
                brief=f"把队列里所有 open 工单批量处理掉（共 {size} 张），都是无理由退货且签收都在窗口内。",
                fixture=_f(
                    customers=[customer(f"B{size}C{i}") for i in range(size)],
                    orders=[order(f"B{size}O{i:03d}", f"B{size}C{i}", paid=35.0 + 7 * i) for i in range(size)],
                    order_items=[item(f"B{size}I{i}", f"B{size}O{i:03d}", sku=f"SKUB-{size}-{i}", name=f"队列商品{i}，含配件与说明书的完整中文描述文本" + ("很" * 40), price=35.0 + 7 * i) for i in range(size)],
                    shipments=[shipment(f"B{size}O{i:03d}", delivered="2026-05-18T12:00:00") for i in range(size)],
                    tickets=[ticket(tickets[i], f"B{size}C{i}", f"B{size}O{i:03d}", "不想要了，无理由退款") for i in range(size)],
                ),
                expect={"outcome": "batch", "tickets": tickets, "ticket_status": "resolved", "hitl": True},
                tags=["long_horizon"],
            )
        )
    return out


def by_id(scenario_id: str) -> Scenario:
    return next(s for s in scenarios() if s.id == scenario_id)


def train_slice() -> list[Scenario]:
    return [s for s in scenarios() if not s.holdout]


def holdout_slice() -> list[Scenario]:
    return [s for s in scenarios() if s.holdout]


def policy_truth(scenario: Scenario) -> dict[str, Any]:
    """What the deterministic engine says about this scenario, ignoring the agent."""
    fixture = scenario.fixture
    customers = {c["id"]: c for c in fixture.get("customers", [])}
    orders = {o["id"]: o for o in fixture.get("orders", [])}
    ticket = (fixture.get("tickets") or [{}])[0]
    oid = ticket.get("order_id") or scenario.expect.get("order_id")
    if not oid:
        matches = [o for o in fixture.get("orders", []) if o["customer_id"] == ticket.get("customer_id")]
        oid = matches[0]["id"] if matches else None
    if not oid:
        return {"outcome": "unknown"}
    items = [i for i in fixture.get("order_items", []) if i["order_id"] == oid]
    shipment_row = next((s for s in fixture.get("shipments", []) if s["order_id"] == oid), None)
    claim = scenario.expect.get("claim_type") or _claim_of(scenario)
    decision = evaluate_refund(
        order=orders[oid],
        items=items,
        customer=customers[orders[oid]["customer_id"]],
        shipment=shipment_row,
        claim_type=claim,
        now=fixture["now"],
    )
    return {
        "outcome": "refund" if decision.allowed else "deny",
        "amount": decision.amount,
        "reason_code": decision.reason_code,
        "requires_approval": decision.requires_approval,
        "requires_escalation": decision.requires_escalation,
    }


_CLAIM_HINTS = {
    "S01_inwindow_refund": "no_reason",
    "S02_window_closed": "no_reason",
    "S03_quality_with_shipping": "quality",
    "S04_missing_item": "missing_item",
    "S05_non_returnable": "no_reason",
    "S06_high_risk": "missing_item",
    "S07_approval_line": "no_reason",
    "S10_phone_lookup": "no_reason",
    "S14_flaky_upstream": "no_reason",
    "S15_context_bloat": "no_reason",
    "H01_inwindow_refund_holdout": "no_reason",
    "H02_window_closed_holdout": "no_reason",
    "H03_missing_item_holdout": "missing_item",
}


def _claim_of(scenario: Scenario) -> str:
    return _CLAIM_HINTS.get(scenario.id, "no_reason")


def apply_faults(scenario: Scenario, world: World) -> None:
    """Inject upstream flakiness for the scenarios tagged as such."""
    if "flaky" in scenario.tags:
        world._flaky.update({"get_order": 1, "issue_refund": 1})


def _holdout_variants() -> list[Scenario]:
    """A wider holdout slice: same policy families, fresh ids/amounts/windows.

    Three holdout tasks cannot reach significance no matter how well a skill works, so
    the slice is deliberately larger — the gate refuses to promote on n=3, and that
    refusal is only useful if a genuinely good card can still clear it.
    """
    out: list[Scenario] = []
    specs = [
        ("refund_window", "no_reason", 5, 100.0, "refund", "买错了不想要，无理由退款"),
        ("refund_window", "no_reason", 14, 180.0, "deny", "不喜欢，无理由退货"),
        ("quality_claim", "quality", 6, 120.0, "refund", "商品坏了不能用，质量问题退款"),
        ("missing_item", "missing_item", 4, 90.0, "refund", "少发了一件，缺件退款"),
        ("category_rules", "no_reason", 2, 75.0, "deny", "不想要了，无理由退款"),
        ("refund_window", "no_reason", 6, 45.0, "refund", "尺寸不合适，无理由退款"),
        ("refund_window", "no_reason", 12, 210.0, "deny", "不满意，无理由退货"),
        ("missing_item", "missing_item", 3, 66.0, "refund", "漏发一件，缺件退款"),
    ]
    for i, (family, claim, days, price, outcome, phrase) in enumerate(specs):
        cid, oid, tid = f"CH{i}", f"SO3300{i}0", f"T4{i:03d}"
        delivered = f"2026-05-{20 - days:02d}T12:00:00"
        category = "fresh" if family == "category_rules" else "general"
        qty = 3 if claim == "missing_item" else 1
        delivered_qty = qty - 1 if claim == "missing_item" else qty
        amount = round(price * (qty - delivered_qty) if claim == "missing_item" else price + (10.0 if claim == "quality" else 0.0), 2)
        expect_claim = "no_reason" if family == "category_rules" else claim
        expect: dict[str, Any] = {"ticket_status": "resolved", "hitl": outcome == "refund", "claim_type": claim}
        if outcome == "refund":
            expect.update({"outcome": "refund", "amount": amount})
        else:
            expect.update({"outcome": "deny", "amount": 0.0, "resolution": "rejected_by_policy"})
        out.append(
            Scenario(
                id=f"H1{i}_holdout",
                title=f"[holdout] {family} 签收{days}天 {price}元",
                skill_family=family,
                difficulty="medium",
                brief=f"工单 {tid}：{phrase}。",
                fixture=_f(
                    customers=[customer(cid)],
                    orders=[order(oid, cid, paid=round(price * qty + (10.0 if claim == "quality" else 0.0), 2), shipping=10.0 if claim == "quality" else 0.0)],
                    order_items=[item(f"IH{i}", oid, sku=f"SKU-H{i}", name=f"holdout 商品{i}", price=price, qty=qty, delivered=delivered_qty, category=category)],
                    shipments=[shipment(oid, delivered=delivered)],
                    tickets=[ticket(tid, cid, oid, phrase)],
                ),
                expect=expect,
                holdout=True,
            )
        )
    return out
