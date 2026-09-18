# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 and the runtime
API may change.

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

[0.1.0]: https://github.com/Kobelyww/ballast/releases/tag/v0.1.0
