<div align="center">

# Ballast

**A budget-aware agent runtime whose harness you can actually measure.**

Zero runtime dependencies · every test runs without an API key · auditable, replayable runs

![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)
![deps](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen)
![license](https://img.shields.io/badge/license-MIT-yellow)
![tests](https://img.shields.io/badge/benchmark-28%20tasks%20×%2011%20arms-blue)

</div>

---

Most agent frameworks answer *"can the agent do it?"*. Ballast is built for the three
questions that actually decide whether you can run one in production:

1. **What does it cost when it goes wrong?** Not "what did it cost" — a ceiling you
   check afterwards is a report, not a control.
2. **Why did it do that?** A trace you cannot replay, diff, or audit is a transcript.
3. **Did it really get better, or did it just get louder?** Self-improvement is
   unfalsifiable unless someone brings a holdout set.

## What the numbers say

From [`docs/BENCHMARK.md`](docs/BENCHMARK.md) — **648 runs**: 29 after-sales tasks × 3
repeats × 12 runtime arms, every arm paired against identical scenarios. Offline
surrogate, zero API spend. Worked traces in [`docs/examples/traces.md`](docs/examples/traces.md).

| Finding | Evidence |
|---|---|
| **Guardrails hold under a deliberately defective policy** | The `defective` arm skipped the mandatory policy computation before moving money. **87 attempted payments were blocked by the runtime** and its success fell to **22.2% vs 94.4%** — the invariant held on every single run; no unverified payment ever landed. |
| **A failing agent is not a cheap agent** | `defective` cost **0.44× of a correct run while succeeding a quarter as often**. The "it errored, so we didn't pay for it" intuition is backwards: failure is mostly wasted spend on a task you then redo by hand. |
| **Cost and quality form a real frontier** | `tight_budget`: 88.9% success at **¥0.0487 / 25.2k prompt tokens**. `ballast`: 94.4% at ¥0.0716 / 35.8k. `naive`: 100% at ¥0.0917 / 43.0k. Context control bought a **17% token and 22% cost reduction on identical behaviour**, and the report names which arms are dominated instead of crowning one. |
| **Reliability decays where capability does not** | Under `pass^k`, `tight_budget` falls **88.9% → 77.9% → 68.7%** across three consecutive draws, and `defective` collapses 22.2% → 4.9%. A pass@1 demo cannot see either curve. |
| **Structured errors buy recovery** | The `noisy` arm produced **249 agent faults from malformed calls** (105 unknown arguments, 96 missing required ones, 48 spins caught by the repetition guard). Coerce-then-explain validation still converted that into **72.2% task success at 0.49× the token spend of naive** — a raise-and-crash tool layer converts it into 0%. |
| **Long horizons are where the trade-off bites — and the harness names the mechanism** | On the 12-ticket batch: `naive` finished **12/12 at ¥0.99 / 447k prompt tokens**, `ballast` spent **41% fewer tokens and 44% less money but finished 8/12**. Turning *only* compaction off recovers all 12 at +73% tokens on that scenario, while turning only offloading off changes nothing — so the cost is attributable to folding history away, not to handle-based offloading. That is the kind of sentence a pass-rate-only benchmark can never produce. |
| **The environment is part of the score** | Fault attribution separates `agent` (303 in `noisy`) from `runtime` (budget aborts) from `environment` (upstream timeouts absorbed by retry), so a regression is assigned to the layer that caused it. |

## Why keep it

- **The benchmark runs in CI with no key and no egress.** A `surrogate` policy model
  drives real tool calls against a real SQLite world, so every mechanism below is an
  assertion, not a vibe. Plus **record/replay**: `--record` captures real upstream
  responses into a content-addressed store, and replay **fails loudly on a miss**
  rather than quietly hitting the network. Change the prompt and the fixture
  mismatch tells you immediately.
- **Policy lives in code, not in the prompt.** `issue_refund` will only move money
  that `compute_refund` already derived from a deterministic engine. The agent cannot
  authorise a payment, only request one it has already been shown. Same engine scores
  the run — the invariant and the grader are one module.
- **Budgets degrade before they abort.** On a ceiling the runtime sheds its optional
  context (retrieved skills, policy briefing), tightens its own compaction, then asks
  the model to *bank a partial result*, and only then stops. Work already paid for is
  not thrown away.
- **Resume does not double-pay.** Every execution is recorded under an idempotency
  key, so restarting a checkpointed run replays stored results instead of re-firing a
  refund. `interrupt` mode parks a run in SQLite; a different process can list pending
  approvals hours later and resume it.
- **Self-improvement with a statistical gate.** A distilled skill card starts as
  `candidate` and is never injected into a live prompt. It becomes `active` only by
  winning identical holdout tasks under an exact paired test with
  Benjamini-Hochberg correction across concurrent candidates, plus a bootstrap bound
  on the cost ratio. This is falsifiable by design: on a 3-task holdout the gate
  **rejected a card that fixed all three** (p = 0.25 — n = 3 cannot reach
  significance); on an 11-task holdout the same gate promoted the same kind of card
  (p = 0.001, BH-adjusted 0.0012, 11 fixed / 0 regressed, cost ratio 1.02) and
  rejected a card that changed nothing.
- **Context engineering is attributable, not decorative.** Tool-output offloading to
  content-addressed handles, whole-block compaction that never orphans a `tool_calls`
  message, pinned re-fetches, and a CJK-aware token budget checked *before* the
  request — each one is a toggle with its own ablation arm.
- **It is small enough to read.** ~4.5k lines, stdlib only, no framework lock-in and
  no vendor SDK. Every mechanism is implemented in the open rather than imported.

## The honest limits

Read these before trusting the table above; they are the interesting part.

- **`S19_batch_twelve` fails on the tuned arm and passes on the dumb one.** After one
  compaction the batch run loses sight of its queue and stops at 8/12. The diagnosis is
  a hypothesis from event streams, not a proof; the fix (re-read the queue from the
  world, which still holds it) is obvious and unwritten. The task stays in the suite,
  failing, in the headline table and in `bench/results/`, because a benchmark trimmed to
  your pass rate is not a benchmark.
- **These numbers characterise the harness, not any LLM.** The `surrogate` is a
  hand-written deterministic policy, not a model. Token/cost deltas between arms are
  real properties of the context machinery (the messages it assembles are the ones a
  real model would receive); *task-quality* claims need a real provider. Run
  `ballast eval --provider deepseek` to get those.
- **The benchmark detected a regression in its own default arm.** With offloading set
  to a realistic-but-eager 340 tokens, `ballast` scored **88.2% vs `naive` 100%** —
  offloading payloads the agent then needed in full costs a round trip and can starve
  the run. Retuning to 1,200 tokens restored parity. Both results are reproducible;
  the lesson is that "context engineering" is a measurable trade-off, not a free win,
  and a framework without an ablation harness will not notice.
- **`naive` still beats `ballast` on task success (100% vs 94.4%).** Context control is
  measurably cheaper and provably not free: at this task length nothing needed the
  savings, and one compaction cost a task. If your runs are short, run `naive` — the
  benchmark says so explicitly, which is the point of having one.
- **Long-horizon coverage is thin.** `S17_fat_order` (40-line order) and
  `S18_batch_queue` (5 tickets in one context) exercise offload-then-refetch and
  multi-goal transcripts, but both pass only under the tuned policy and neither has a
  variant that is *harder* still. If you have a long-horizon suite, this project wants
  it.
- Skill-card *utility* is simulated through machine-readable triggers the surrogate is
  *made* to obey; with a real provider the same gate measures actual instruction
  following, but that transfer is not yet demonstrated.

## Quickstart

```bash
git clone https://github.com/Kobelyww/ballast && cd ballast
pip install -e ".[dev]"

ballast arms                       # what can be ablated
ballast run S01_inwindow_refund    # one task, offline, with a full trace
ballast run S06_high_risk --arm defective --trace
ballast eval --reps 3 --out bench/results/eval.md
ballast skills distill && ballast skills gate
```

Sample output, no key involved: [`run_output.txt`](docs/examples/run_output.txt) (the
CLI's own trace dump) and [`traces.md`](docs/examples/traces.md) (three graded runs,
including a ¥1,999 high-risk refund the runtime refused to pay).

Point it at a real model — nothing else changes:

```bash
export BALLAST_LLM_API_KEY=sk-...           # DeepSeek / Qwen / GLM / vLLM / Ollama
export BALLAST_LLM_BASE_URL=https://api.deepseek.com
ballast eval --provider openai-compat --model deepseek-chat --record   # cache for replay
```

## What is in the box

```
src/ballast/
  support/     CJK-aware token estimation, scratch store, BM25 in ~90 stdlib lines
  llm/         OpenAI-compatible transport (urllib + retries + concurrency bound),
               content-addressed cache, record/replay, offline surrogate
  context/     the context window as a budgeted resource: offload, block compaction
  kernel/      agent loop, toolkit w/ schema inference + argument repair, budgets,
               checkpoints, HITL gate, deterministic invariant checker
  memory/      episodic store, skill library, distiller, statistical promotion gate
  env/         simulated after-sales world (SQLite), policy engine, SOP corpus, tasks
  bench/       arms, runner, graders, fault taxonomy, pass^k / McNemar / bootstrap
```

Docs: [ARCHITECTURE](docs/ARCHITECTURE.md) (design rationale + the OSS it stands on) ·
[BENCHMARK](docs/BENCHMARK.md) (full tables) ·
[CONTRIBUTING](CONTRIBUTING.md)

## Why "ballast"

Ballast is weight you carry to stay stable and controllable. An agent runtime earns
its keep the same way: not by making the model smarter, but by keeping the ship upright
when the model is wrong.

## Acknowledgements

Mechanisms here stand on published work: durable checkpointing and `interrupt` from
[LangGraph](https://github.com/langchain-ai/langgraph); context condensation from
[OpenHands](https://docs.openhands.dev/sdk/arch/condenser); cost/turn limits as
first-class controls from [Inspect AI](https://inspect.aisi.org.uk/setting-limits.html);
pass^k reliability and fault attribution from
[τ-bench](https://github.com/sierra-research/tau-bench); skill libraries from
[Voyager](https://arxiv.org/abs/2305.16291) and episodic self-correction from
[Reflexion](https://arxiv.org/abs/2303.11366); task guardrails from
[CrewAI](https://docs.crewai.com/en/concepts/tasks); just-in-time retrieval and
sub-agent context isolation from [Anthropic's context-engineering
guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
Ballast reimplements the subset it needs from scratch, in stdlib, so that the
mechanisms stay measurable.

MIT License · © 2026 Haobo Wang

---

## 为什么值得留下这个项目

生产环境里的 agent 死于三件事：预算失控、无法审计、以及"它好像变好了"这种无法证伪的
自我表扬。主流框架回答的是"模型能不能做到"，Ballast 回答的是"你敢不敢让它自己跑"。

- **零依赖、零 API 密钥也能把整套 harness 测完**：离线 surrogate 驱动真实工具调用、真实
  SQLite 世界；record/replay 让 CI 在没有外网、没有密钥的环境里复现真实模型行为，prompt
  一改就报错，而不是悄悄省一次调用。
- **政策写在代码里而不是提示词里**：没经过 `compute_refund` 核定的钱，工具层直接拒绝支付；
  同一套引擎既在运行时兜底、也在评分时判定，护栏和考官是同一个模块。
- **预算是控制不是报表**：超限前逐级降级（丢弃可选上下文→收紧压缩→先落袋为安），恢复执行
  带幂等键，绝不会出现"重放一次、退款两次"。
- **自我改进带统计闸门**：技能卡默认 `candidate`、进不了提示词；只有在**从未见过的**留出
  任务上以配对精确检验 + BH 多重校正 + 成本比置信界胜出，才允许转正。n=3 时它拒绝了"修好
  全部 3 个任务"的卡片（p=0.25），n=11 时以 p=0.001 批准——这才是"学到东西"的可证伪定义。
- **它诚实**：基准测出过自己默认配置的回归（过早 offload 让成功率从 100% 掉到 88.2%）；
  两道长程任务至今未通过并保留在测试集里；表格里每个数字都标了它测量的是 harness 而不是模型。
  一个敢在 README 里写"这些数据证明不了什么"的项目，比一个只写 wins 的项目更值得信。
