# Prior art, and what each one cost us to keep

The README's acknowledgements name the projects this runtime borrows mechanisms from. A
name-list is not grounding: the useful question is *what does each upstream project do,
what did we do differently, and what did the difference cost or buy — measurably, in this
repo*. Every row below points at a file that exists and a test or arm that runs in CI.

Where a row says "we differ", that difference is the contribution. Where it says "same
shape", we are reimplementing in stdlib so the mechanism stays ablatable — which is its own
claim, not a substitute for one.

| Mechanism | Upstream | Their approach | Ballast | Measured here |
| --- | --- | --- | --- | --- |
| Durable checkpointing | [LangGraph](https://github.com/langchain-ai/langgraph) | Checkpointer interface over a graph's super-steps; state is the node frontier | Per-step checkpoints of the *loop* frontier — context engine, ledger, memo — in SQLite (`kernel/checkpoint.py`) | `tests/test_checkpoint.py`; the `resume_run` CLI path |
| Human-in-the-loop as control flow | LangGraph `interrupt` | Pause the graph, surface a payload, resume the same run | `Interrupt` is an exception that must propagate through the tool layer; the run parks in SQLite with the pending call id (`kernel/hitl.py:29`) | `tests/test_durable_hitl.py`. A swallowed `Interrupt` was one of six bugs this suite caught: approval-gated runs kept spending |
| Idempotent effects on resume | — (our addition) | Not a LangGraph concept at that layer | Memo keyed on `(run_id, call_id)` so a replayed step returns the stored result instead of re-firing | `tests/test_durable_hitl.py`; the per-effect repetition ceiling in `kernel/agent.py:_execute` (2 for a write, 8 for a read) |
| Context condensation | [OpenHands](https://docs.openhands.dev/sdk/arch/condenser) | A `Condenser` summarises old events into an `EventBuffer` | Whole-*block* compaction: an assistant `tool_calls` message and its `tool` replies fold together or not at all, because a split transcript is rejected by every OpenAI-compatible endpoint (`context/engine.py:_split_blocks`) | `tests/test_context_engine.py` asserts no orphaned tool replies on every fold |
| Overflow with handles | [Anthropic, just-in-time retrieval](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Move content out, retrieve on demand | Same, plus the contract that a moved-out record keeps its scalar identity inline (`kept: {...}`) — without it the policy re-issues the read and pays for the payload every step | `scripts/offload_sweep.py`; `S20_oversized_manifest`, where the alternative is a request nobody can send |
| Budget as a first-class control | [Inspect AI](https://inspect.aisi.org.uk/setting-limits.html) | `token_limit` / `message_limit` enforced by the evaluator | Charged *before* the billable call, and enforced by degrading rather than aborting: shed briefing → tighten compaction → bank a partial → stop (`kernel/budget.py`, `Agent._degrade`) | `tight_budget` and `no_budget` arms; `tests/test_budget_and_ledger.py` |
| pass^k reliability | [τ-bench](https://github.com/sierra-research/tau-bench) | `p̂^k` from a per-task success rate, assuming independent draws | Two functions: the estimate **and** `pass_k_measured`, which counts tasks passing all of their first k draws. The report prints both, labelled | `tests/test_reliability.py` injects variance at the provider boundary and shows the measured column decay while the surrogate's stays flat |
| Paired significance | τ-bench / standard practice | Aggregate rates and compare | Exact McNemar on discordant pairs per task, BH correction across concurrent candidates, seeded bootstrap on cost ratios, Cohen's h so 1/8-vs-2/8 is not sold as an effect | `bench/stats.py`, `tests/test_stats.py`; every CI row in `docs/BENCHMARK.md` |
| Skill library | [Voyager](https://arxiv.org/abs/2305.16291) | Skills are promoted by succeeding in the environment; retrieval by embedding similarity | `candidate → active → retired`, but promotion needs a *holdout* win under paired significance plus a cost bound. Retrieval is BM25 + jaccard, deliberately no embeddings | `memory/promotion.py`; `make gate` exits 1 if nothing promotes, so the gate is tested in CI |
| Reflexion-style self-correction | [Reflexion](https://arxiv.org/abs/2303.11366) | Verbal self-feedback in the next attempt's prompt | A critic that can only speak through deterministic invariant findings (`kernel/verify.py`), so "the model reflected" is never the evidence | `critic_rounds` per arm; `tests/test_invariants.py` |
| Task guardrails | [CrewAI](https://docs.crewai.com/en/concepts/tasks) | `guardrail` functions as LLM-as-judge validators | Policy-in-code at the tool layer: `issue_refund` can only move money `compute_refund` already derived. The same module grades the run afterwards | `defective` (171 refused payments), `ops_unassessed` (66), `ops_reckless` (34) arms |
| Sub-agent context isolation | Anthropic context-engineering guidance | Give each sub-agent a fresh, narrow window | **Not implemented, and the row is here to say so.** The `hierarchical` arm is `plan_execute` plus a second critic round (`bench/runner.py:100`) — planner, worker and critic share one context engine and one budget. The guidance is right that isolation bounds blast radius; this runtime does not yet provide it | The `hierarchical` row in `docs/BENCHMARK.md`, which is the honest evidence of what we *do* have: 100% success at 1.01× the controlled arm's cost, i.e. planning + an extra critic round buys reliability, not isolation |
| Fault attribution by owner | — (our addition) | Not a convention in the above | `agent` / `runtime` / `environment` owners over a code taxonomy, keyed on `(tool, arguments)` — because by tool name alone a batch run closing 24 tickets read as 21 loops | `bench/faults.py`, "Where failures come from" in every report |

## What this table is for

Two uses, and neither is decoration.

**Review.** If a reviewer knows LangGraph or τ-bench, each row is a checkable claim about a
mechanism they can compare against the original, in a runtime small enough to read.

**Debt.** Rows where we differ are the places a real system will be tested hardest — the
`Interrupt` propagation bug, the identity-less handle, and the estimate-passed-as-measurement
all came from exactly those rows, and all three were found by this repo's own arms rather
than by a reader.

Regenerate the numbers behind the right-hand column with the commands in
[`BENCHMARK.md`](BENCHMARK.md).
