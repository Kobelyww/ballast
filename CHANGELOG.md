# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 and the runtime
API may change.

## [0.2.0] - 2026-09-19

What a benchmark is for: this release is mostly the story of what the 0.1.0 benchmark
found, and what it now measures that it previously could not.

### Added

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

- `Interrupt` was being swallowed by the tool layer's crash handler, so an
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
