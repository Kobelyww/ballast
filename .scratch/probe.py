import json
import pathlib
import shutil
import sys

sys.path.insert(0, "src")

from ballast.context.engine import ContextPolicy
from ballast.env.fixtures import by_id
from ballast.env.knowledge import KnowledgeBase
from ballast.kernel.agent import Agent, AgentConfig
from ballast.kernel.budget import RunBudget
from ballast.kernel.checkpoint import Checkpointer
from ballast.kernel.events import RunContext
from ballast.kernel.toolkit import Toolkit
from ballast.llm.base import ChatResponse, ToolCall, Usage
from ballast.llm.surrogate import ScriptedModel
from ballast.support.text import ScratchStore
from ballast.tools.desk import build_desk_tools


def step(i, name, **args):
    return ChatResponse(
        tool_calls=[ToolCall(id=f"call_{i}", name=name, arguments=args)],
        usage=Usage(input_tokens=500, output_tokens=30, calls=1),
        finish_reason="tool_calls",
    )


SUM = "依据 refund_policy::质量问题退款 核定退款 ¥459.00（含运费 12.00），已执行放款并结单。"


def build(sid, hitl_mode="scripted", hitl_script=None, cp=None, provider=None, **kw):
    s = by_id(sid)
    world = s.build_world()
    kb = KnowledgeBase.from_dir()
    ctx = RunContext(
        task_id=s.id,
        arm="test",
        world=world,
        sop=kb,
        hitl_mode=hitl_mode,
        hitl_script=hitl_script if hitl_script is not None else {"issue_refund": True},
    )
    ctx.scratch = ScratchStore()
    cfg = AgentConfig(
        provider=provider or ScriptedModel([]),
        toolkit=Toolkit(build_desk_tools(ctx)),
        context=ContextPolicy(**kw.pop("context", {})),
        budget=RunBudget(**kw.pop("budget", {})),
        checkpointer=cp,
        **kw,
    )
    return Agent(cfg, world=world, kb=kb), ctx, s, world


plan = [
    step(1, "get_ticket", ticket_id="T1044"),
    step(2, "get_order", order_id="SO20261044"),
    step(3, "get_customer", customer_id="C102"),
    step(4, "search_sop", query="退款 无理由 政策 窗口 计算"),
    step(5, "compute_refund", order_id="SO20261044", claim_type="quality"),
    step(6, "issue_refund", order_id="SO20261044", amount=459.0, reason="quality"),
    step(7, "close_ticket", ticket_id="T1044", resolution="refunded", summary=SUM),
    ChatResponse(content="已完成退款", usage=Usage(input_tokens=500, output_tokens=20, calls=1)),
]

p = pathlib.Path(".scratch/state")
shutil.rmtree(p, ignore_errors=True)
p.mkdir(parents=True)
cp = Checkpointer(p / "runs.db")
ag, ctx, sc, world = build("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, cp=cp, provider=ScriptedModel(plan))
r = ag.run(sc.brief, task_id=sc.id, arm="test", ctx=ctx)
print("events tail:", [(e["type"], e["payload"].get("name"), str(e["payload"].get("code") or e["payload"].get("detail") or "")[:70]) for e in r.events][-6:])
print("steps", r.steps, "cost", round(r.cost, 5))
print("interrupt tool", r.interrupted["tool"], "call_id", r.interrupted.get("call_id"))
st = cp.latest(r.run_id).state
print("state keys", sorted(st))
print("transcript tail:", json.dumps(st["context"]["transcript"][-2:], ensure_ascii=False)[:500])
print("pending_calls", st.get("pending_calls"))
print("idempotent keys", list(st.get("idempotent", {})))
print("usage_history", st.get("usage_history"))
print("budget", st.get("budget"))

print("=== resume approve")
plan2 = [
    step(7, "close_ticket", ticket_id="T1044", resolution="refunded", summary=SUM),
    ChatResponse(content="已结单", usage=Usage(input_tokens=500, output_tokens=20, calls=1)),
]
ag2, ctx2, sc2, world2 = build("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, cp=cp, provider=ScriptedModel(plan2))
ag2.world = world  # resume against the interrupted world
try:
    r2 = ag2.resume(r.run_id, {"approved": True})
    print("resumed status", r2.status, "steps", r2.steps, "refunds", json.dumps(world.state()["refunds"], ensure_ascii=False)[:200])
    print("events tail", [(e["type"], e["payload"].get("name"), e["payload"].get("code")) for e in r2.events][-6:])
    print("error", r2.error[:400])
except Exception as exc:
    print("RESUME RAISED", type(exc).__name__, exc)

print("=== resume reject")
ag3, ctx3, sc3, world3 = build("S03_quality_with_shipping", hitl_mode="interrupt", hitl_script={}, cp=cp, provider=ScriptedModel(plan2))
ag3.world = world3
try:
    r3 = ag3.resume(r.run_id, {"approved": False})
    print("resumed status", r3.status, "steps", r3.steps, "refunds", json.dumps(world3.state()["refunds"], ensure_ascii=False)[:120])
    print("error", r3.error[:300])
except Exception as exc:
    print("RESUME RAISED", type(exc).__name__, exc)
