# Changelog

## [0.4.0] - 2026-09-19

A hard-tier ladder of long-horizon batch tasks — and the four defects it caught, one in
the context engine, one in the repeat guard, one in the model stand-in and one in the
grader.

### Added

- **A difficulty ladder instead of a single hard task**: `L12 / L16_fat / L24 / L36 /
  L48` batch decks with pre-resolved decoy tickets that own their own orders and
  customers, so a decoy can no longer be graded as if the agent should have touched it.
- **`ContextEngine.holds_result()`**: answers whether a *usable* (non-offloaded,
  non-folded) copy of a tool result is still in the window. The repeat guard now asks it
  before refusing an identical read, and grants one re-read when nothing survives.
- **Digest-aware evidence in the surrogate**: `saw()` reads the compaction digest
  (`_FOLD_CREDITED_READS`) so a folded *read* is credited, while *effects* never are —
  a summary is evidence you looked, not evidence you paid. A policy that must quote a
  section id it can no longer see now re-fetches it, scoped per ticket.
- **`scripts/plot_crossover.py`** renders `docs/figures/crossover.svg` from stored rows:
  the break-even point, the sign flip by scenario class and the ladder, with no plotting
  dependency and no hand-placed numbers.
- **`FOLD_MARKER`** is exported by the context engine so the digest header cannot drift
  between the writer and its readers.

### Fixed

- **Attribution by evidence**: `kernel/verify.py` now grades only the ticket dispositions
  recorded in the world's action ledger. Batch decks seed resolved decoys as scenery, and
  the invariant sweep was failing both arms for `missing_policy_citation` on summaries no
  run ever wrote.
- **Fault attribution keys on arguments, not tool names.** A run that legitimately calls
  `get_ticket` 24 times was reported as 21 `loop_detected` agent faults; every healthy
  arm now reads 0.
- **The repeat guard no longer asserts something false.** Its message claimed the earlier
  result "is already in your context" after compaction had removed it.
- **Ceilings are asserted honestly in tests**: the cost ceiling is enforced *before* the
  billable call, so the test now allows exactly one in-flight request's price, and the
  wall-clock guard scales with steps instead of pinning a flat 5s to a 48-ticket run.

### Measured

`L16_fat_batch` 5/16 → **16/16**, `L24_batch` 17/24 → **24/24**, `L36_batch` 3/36 →
**36/36** at ¥4.79 against `naive`'s ¥8.06. `L48_batch` remains the hard tier: both arms
stop at the shared ¥6 ceiling, the controlled arm at 39/48 tickets and the naive arm at
37/48. The aggregate `naive`/`ballast` cost ratio is now **1.50 [1.31, 1.58]** — resolved,
where it previously read 1.12 [0.87, 1.25] and could not be called either way — while the
class split still shows the sign flip: 1.51 [1.35, 1.60] on long-horizon tasks against
0.95 [0.94, 0.95] on ordinary short ones.


All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 and the runtime
API may change.

## [0.3.0] - 2026-09-19

A second business domain, and the two things it caught: a deadlock in the new world and
a promotion gate that priced the wrong quantity.

### Added

- **Prompt-injection discipline for tool payloads**: `kernel/injection.py` scans every
  tool result for smuggled instructions (override, amount, skip-procedure,
  exfiltration, false authority), emits `injection_suspected` events, and fences
  *suspected* payloads as declared data. Two new arms — `obedient` (treats record text
  as an order) and `unfenced` (no declaration) — plus three injection tasks. Measured
  over 9 runs: `obedient` passes 3/9, draws 6 guardrail refusals, and no injected
  amount ever reaches the world. Detection is telemetry; the invariant layer is the
  defence, and the README says so plainly.
- **SRE incident management** as a second domain: `env/ops_world.py`,
  `env/incident_policy.py` (paging, change freeze, blast radius, rollback staleness),
  `env/incident_verify.py`, `tools/ops.py`, `env/runbooks/`, `bench/incident_graders.py`
  and `llm/ops_surrogate.py`. 16 tasks. `kernel/`, `context/` and `llm/base.py` were not
  touched; `AgentConfig.invariant_check(world, ctx)` is the one injection point that
  keeps domain knowledge out of the loop.
- **Cross-domain guardrail arms** `ops_unassessed` and `ops_reckless`: 57 and 33 refused
  actions respectively, and zero unauthorised rollbacks during a change freeze.
- **Cross-domain self-improvement**: incident cards now carry the same `TRIGGER:`
  contract and are gated on a 9-task incident holdout (6 cards, 9/9 fixed, 0 regressed,
  p = 0.0039).
- **`ballast approvals resolve` resumes the run** and reports the outcome, instead of
  printing instructions about the library API.

[0.3.0]: https://github.com/Kobelyww/ballast/releases/tag/v0.3.0

## [0.2.0] - 2026-09-19

What a benchmark is for: this release is mostly the story of what the 0.1.0 benchmark
found, and what it now measures that it previously could not.

### Added

- **A second domain**: SRE incident management (`env/ops_world.py`,
  `env/incident_policy.py`, `env/incident_verify.py`, `tools/ops.py`,
  `env/runbooks/`, `bench/incident_graders.py`, `llm/ops_surrogate.py`, 9 tasks).
  Added without touching `kernel/`, `llm/base`, `context/` or `bench/` statistics —
  `AgentConfig.invariant_check` is now injected so the loop is domain-free, and it
  raises rather than silently disabling the critic if you ask for critique without
  supplying invariants.
- **`ops_unassessed` / `ops_reckless` arms**: paging or reverting a frozen deploy
  without a policy assessment is refused every time (0 unauthorised rollbacks).
- **A batch size ladder** (`B04`…`B16`): the same task at 4/6/9/12/16 tickets, so cost
  claims about context control rest on enough paired tasks for a bootstrap interval to
  mean something. 25 tasks total.
- **`## The crossover`** in the generated report: naive-to-ballast prompt-token ratio as
  a function of task length — 0.93× at 4 tickets, 1.06× at 9, 1.24× at 12, 1.49× at 16.
  Context control is a 5–7% loss on short runs and a third off on long ones, and the
  table is computed from stored rows rather than written by hand.
- **`## Where the savings actually come from`**: per-scenario-class paired cost and
  token ratios, with intervals suppressed below five paired tasks.
- **`scripts/mock_openai_server.py`** — a stdlib OpenAI-compatible server, plus 15 tests
  that drive the whole agent loop over a real socket: bearer auth, body shape, tool
  arguments arriving as a JSON string, both vendor spellings of the cached-token field,
  a 429 retried without charging twice, a 403 that is not retried, and cache replay
  costing zero.
- **Pinned runtime state**: confirmed tool effects are mirrored into a
  `[RUN STATE]` block that compaction replaces rather than folds.
- **`tests/test_durable_hitl.py`** — park a run in one process, list and resolve it in
  another, assert the payment lands exactly once and never on a rejection.

### Fixed

- **The promotion gate priced the wrong thing.** Its cost ceiling compared cost *per
  attempt*, so a guardrail-refused-then-stalled baseline (cheap, always wrong) vetoed
  cards that fixed every held-out task — all six incident cards were retired this way,
  including one at p = 0.0039 with 9/9 fixed and 0 regressed. The gate now compares
  cost **per success**, keeps the attempt ratio in the verdict, enforces a hard absolute
  ceiling so an unbounded blow-up still needs sign-off, and reports explicitly when
  cost-per-success is undefined because the baseline never succeeded.
- `close_incident` overwrote the mitigation ledger with its resolution string, so a
  completed acknowledgement and review read as never-done and the close-out was refused
  forever; `get_incident` also left that column unparsed.
- `OpsWorld` deadlocked: `rollback_deploy` read current state while holding a plain
  `Lock`.
- `approvals resolve` printed instructions instead of resuming the run.

### Added (also)

- **Cross-domain self-improvement**: the incidents domain distills cards that the same
  gate evaluates on an expanded 9-task incident holdout (a 2-task slice could never
  reach significance, so the gate could only ever say no). by the tool layer's crash handler, so an
  approval-gated run kept spending instead of parking. This was also failing the two
  long-horizon tasks.
- Compaction folded away the opening user message, leaving an agent holding a digest of
  what it was asked instead of the request. The task message is now pinned.
- The batch policy treated a *rejected* close as a completed one, silently skipping the
  ticket. Only confirmed dispositions count now.
- Skill retrieval mixed a wall-clock recency term into its score, so two identical
  searches returned different orderings. Recency is quantised to whole days; retrieval
  is reproducible, which the project promises in its own name.
- `resume()` crashed on any checkpoint without a pending interrupt, and re-executed the
  parked call it was resuming.
- Repeating a read-only call is now permitted (it is wasteful, not dangerous) while a
  repeated write is blocked — the ceiling is per-effect.
- `ballast run <unknown-id>` raised a bare `StopIteration`.
- The uncontrolled arm was given an infinite context window, which made it unmeasurable
  rather than naive; it now has a realistic 32k serving window.

### Changed

- `S19_batch_twelve` passes on the controlled arm for the first time, at 366k tokens
  against naive's 452k.

## [0.1.0] - 2026-09-19

First release: the runtime, the benchmark, and the claims the benchmark supports.

### Added

- **Agent loop** (`kernel/agent.py`) — ReAct loop with four behaviours implemented
  outside the prompt: budget degradation instead of hard abort, idempotent resume,
  repetition/stall detection, and a deterministic post-run critique pass.
- **Budget control** (`kernel/budget.py`) — cost, step, wall-time and prompt-token
  ceilings checked *before* the billable call; per-run usage ledger so concurrent eval
  runs cannot contaminate each other; cumulative burn-down curves.
- **Context engineering** (`context/engine.py`) — CJK-aware token estimation,
  handle-based offloading of oversized tool results, whole-block compaction with a
  pluggable summariser, and pinning of re-fetched payloads.
- **Tool layer** (`kernel/toolkit.py`) — JSON-Schema inferred from type hints and
  Google-style docstrings; argument coercion and validation with model-facing correction
  messages including did-you-mean suggestions; policy-enforcing mutating tools.
- **Durable execution** (`kernel/checkpoint.py`, `kernel/hitl.py`) — per-step SQLite
  checkpoints, `interrupt` mode that parks a run for a human verdict and resumes it in a
  later process, and an idempotency memo that prevents side-effect replay on resume.
- **Invariants** (`kernel/verify.py`) — deterministic checks (high-risk payment,
  over-refund, unverified payment, missing policy citation) shared by the runtime critic
  and the offline grader.
- **Simulated domain** (`env/`) — after-sales world on SQLite with a frozen clock, fault
  injection and an audit trail; a pure-function policy engine; an SOP corpus with
  citation-shaped section ids; 28 tasks including a train/holdout split.
- **Memory** (`memory/`) — episodic run store; lexical skill library with candidate →
  active → retired lifecycle; trace distiller; statistical promotion gate.
- **Providers** (`llm/`) — stdlib OpenAI-compatible transport with bounded concurrency
  and retry that never re-bills; content-addressed cache; record/replay provider that
  fails loudly on a miss; deterministic offline surrogate policy model.
- **Benchmark** (`bench/`) — 11 runtime arms, paired McNemar and Wilson intervals,
  pass^k reliability, bootstrap cost ratios with Benjamini-Hochberg correction, fault
  attribution by owner (agent / runtime / environment), Pareto frontier, and markdown
  report generation.
- **CLI** — `ballast run|eval|report|arms|trace|approvals|skills`.
- **Documentation** — README with findings and their limits, `docs/ARCHITECTURE.md`,
  regenerated `docs/BENCHMARK.md`, CONTRIBUTING, SECURITY.

[0.2.0]: https://github.com/Kobelyww/ballast/releases/tag/v0.2.0
[0.1.0]: https://github.com/Kobelyww/ballast/releases/tag/v0.1.0
