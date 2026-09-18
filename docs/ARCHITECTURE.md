# Architecture

Four rules shaped this codebase. Everything else follows from them.

**1. The dependency budget is zero.** A runtime that needs an SDK, a database service
and a framework DSL cannot be audited by reading it, and its CI cannot run offline.
Standard library only: `sqlite3` for world + checkpoint state, `urllib` for the
OpenAI-compatible transport, hand-rolled BM25 for retrieval, hand-rolled token
estimation for budgeting. `pytest` is the only dev dependency.

**2. The world decides, not the model.** Anything expressible as an invariant over
state is enforced in code: refund windows, tier caps, risk thresholds, approval lines.
`env/policies.py` is pure functions; `kernel/verify.py` audits the resulting state; the
same `audit()` feeds the runtime critic *and* the offline grader. Model prose is never
evidence.

**3. Every mechanism is a toggle with an arm.** Offload, compaction, briefing
retrieval, critic rounds, budget ceilings and skill injection are constructor
arguments, not global behaviour, because a mechanism you cannot turn off is a
mechanism you cannot price.

**4. Offline determinism is a first-class capability, not a test shortcut.** If the
harness can only be exercised against a paid endpoint, nobody regression-tests the
harness.

## Layering

```
                ┌────────────────────────────────────────────┐
  bench/        │ runner (arms) · graders · faults · stats   │  measures
                ├────────────────────────────────────────────┤
  kernel/       │ agent loop · toolkit · budget · hitl ·     │  controls
                │ checkpoint · verify                        │
                ├────────────────────────────────────────────┤
  context/      │ ContextEngine: pin · offload · compact     │  budgets attention
                ├────────────────────────────────────────────┤
  llm/          │ Provider protocol · openai-compat · cache  │  speaks to models
                │ · replay · surrogate                       │
                ├────────────────────────────────────────────┤
  env/          │ World (sqlite) · policies · SOP · fixtures │  is the source of truth
  memory/       │ episodic · skills · distill · promotion    │  remembers across runs
                └────────────────────────────────────────────┘
```

Dependencies point downward only. `llm/` knows nothing about refunds; `env/` knows
nothing about prompts. That separation is what lets the surrogate be swapped for a real
provider without touching agent code, and what lets the same `World` serve a demo run
and a statistical comparison.

## The loop

`kernel/agent.py` is one loop. Per iteration:

1. `ContextEngine.assemble()` produces the message list, compacting first if the
   CJK-aware estimate crosses the policy threshold. The estimate happens *before* the
   request, so the budget check is a control rather than a postmortem.
2. `UsageLedger.begin_call()` charges a step and enforces cost/step/wall/prompt-token
   ceilings. `BudgetExceeded` triggers *degradation*, not abort: shed retrieved skills
   and briefing → tighten compaction → instruct the model to bank a partial result →
   only then stop.
3. `provider.chat()` — cache-aware, concurrency-bound, retries that never re-bill a
   completed call.
4. Tool calls dispatch through `Toolkit`: JSON-Schema inferred from type hints and
   Google-style docstrings, arguments type-checked and coerced, and failures returned
   to the model as readable, actionable corrections rather than raised.
5. `_execute()` is the resume-safety seam: a `(run_id, call_id)` memo replays an
   already-executed call instead of firing the side effect again. A signature counter
   catches verbatim repetition (`repeated_call`) — a model that re-asks an identical
   question is not making progress, and two such steps close the run as `stalled`
   rather than spending the remaining budget.
6. When the model stops, `verify.audit()` checks invariants over world state. Any
   violation is bounced back as a bounded critic turn.
7. State is checkpointed each step: context snapshot, ledger usage, computed policy
   decisions, scratch handles, executed-call memo, pending interrupt.

### Why blocks, not messages, get compacted

OpenAI-compatible APIs reject an `assistant` message carrying `tool_calls` if its
`tool` replies are missing. Compaction therefore groups an assistant call with its
replies and folds or keeps the group whole. `_split_blocks()` exists for exactly this
reason, and `tests/test_context_engine.py` asserts it.

### Why re-fetched data is pinned

`read_scratch` exists to bring data *back*. If the next compaction evicts it, the pair
of mechanisms oscillates and the run burns budget re-reading one payload. Blocks whose
tool is in `offload_exempt` are pinned forward through compaction. This is the single
most instructive bug found by the benchmark: it surfaced as `ballast` scoring 88.2%
against `naive`'s 100%.

## Memory and the promotion gate

`memory/distill.py` turns a *graded-correct* trace into a `candidate` card — the input
is an episode whose grade is known good, so the card records a procedure that worked
rather than a model's retelling. Candidates are excluded from retrieval in live prompts.

`memory/promotion.py` decides their fate on holdout tasks the card was never distilled
from. It requires all of: at least one failure→success pair with no regression; exact
McNemar significance; a bootstrap upper bound on the cost ratio; survival of
Benjamini-Hochberg correction across concurrently evaluated candidates. The
`GateVerdict` keeps the discordant counts, both p-values and the cost interval on the
card, so a retired card is evidence rather than a deleted file.

The gate is deliberately strict enough to reject improvements that "look" convincing:
on an 11-task holdout the same card that promotes at p=0.001 is rejected at p=0.25 on a
3-task holdout, because three tasks cannot distinguish a skill from a coin flip.

## The offline surrogate

`llm/surrogate.py` is a hand-written service-desk procedure with three properties that
make it a legitimate measurement instrument:

- It reads **only the context the harness assembled** — it locates its ticket id, order
  id and SOP citation by parsing the message list. Remove information through
  compaction and the run degrades visibly.
- Its competence is a parameter (`SurrogateProfile`): a named defect rate, so
  guardrails and repair are ablatable against a known-bad policy instead of an
  unverifiable model opinion.
- Skill cards act on it through machine-readable triggers, which makes the
  promote/reject halves of the gate testable. This is a simulation of instruction
  following and is documented as such — with a real provider the same code measures the
  real thing.

## The world

`env/world.py` is SQLite with a frozen clock (`fixture["now"]`), so a 7-day refund
window is reproducible years later. Every mutation writes to an `actions` audit table,
and `compute_refund` writes a *decision-bearing read* — the server-side record that a
policy computation preceded a payment, which is what makes `unverified_payment` checkable
from state alone. Fixtures inject flaky upstreams (`upstream_timeout`, retryable) so
resilience is exercised rather than assumed.

## The measurement layer

`bench/stats.py` holds the inference: Wilson intervals (n=8 should look weak), τ-bench's
pass^k, exact McNemar on discordant pairs, seeded bootstrap for cost ratios, Cohen's h
so a 1/8-vs-2/8 difference is not dressed up as an effect, and BH correction so running
twelve ablations cannot mine a p<0.05. `bench/report.py` renders only from stored rows —
`docs/BENCHMARK.md` is regenerated by CI, which turns a stale claim into a diff.

## What is intentionally not here

No vector store, no embedding requirement (the target providers may not expose one, and
deterministic retrieval is a testing virtue), no graph DSL, no web UI, no observability
backend, no model router. Each is defensible on its own; none is what this project is
for.
