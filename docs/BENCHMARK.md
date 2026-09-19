# Benchmark

Two domains, 58 tasks, 10 runtime arms, 2 repeats each. Regenerate with:

```bash
python -m ballast.cli eval --suite all \
  --arms naive,ballast,no_compaction,no_context_control,tight_budget,defective,noisy,obedient,ops_unassessed,ops_reckless \
  --reps 2 --workers 6 --out bench/results/cross-domain.md
python scripts/plot_crossover.py bench/results/eval.json docs/figures/crossover.svg
python scripts/offload_sweep.py
```

1,160 runs, offline policy drivers only — **zero API calls, zero egress**. Read
`README.md#the-honest-limits` first: these characterise the harness, not a language
model. Four sections carry the argument: *"The crossover"* (context control is a curve,
drawn at [`docs/figures/crossover.svg`](figures/crossover.svg)), *"Where the savings
actually come from"* (the same aggregate flips sign by scenario class), *"Where failures
come from"* (which layer is at fault — every healthy arm reports 0 agent faults, which is
the point of keying attribution on arguments rather than tool names), and
`scripts/offload_sweep.py` (the measurement that retired the hard tier; see
`README.md#the-hard-tier-and-what-actually-caused-it`).

The desk-only 12-arm × 3-repeat run behind the README headline lives in
[`bench/results/eval.md`](../bench/results/eval.md).

---

_generated 2026-09-19T10:21:37 · provider `surrogate` · 1160 runs over 10 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 98.3% (114/116) | [93.9%, 99.5%] | 0.5158 | 237743 | 32023 | 26.8 | 0 | 0 | 2 |
| `ballast` | 100.0% (116/116) | [96.8%, 100.0%] | 0.2444 | 121478 | 9460 | 28.4 | 2 | 52 | 2 |
| `defective` | 34.5% (40/116) | [26.5%, 43.5%] | 0.0311 | 16226 | 9467 | 8.6 | 2 | 0 | 154 |
| `no_compaction` | 96.6% (112/116) | [91.5%, 98.7%] | 0.4310 | 203388 | 26502 | 25.5 | 2 | 4 | 2 |
| `no_context_control` | 96.6% (112/116) | [91.5%, 98.7%] | 0.4306 | 203226 | 26502 | 25.4 | 0 | 4 | 2 |
| `noisy` | 72.4% (84/116) | [63.7%, 79.7%] | 0.0320 | 15710 | 9912 | 9.1 | 2 | 4 | 2 |
| `obedient` | 96.6% (112/116) | [91.5%, 98.7%] | 0.2444 | 121504 | 9460 | 28.4 | 2 | 52 | 6 |
| `ops_reckless` | 86.2% (100/116) | [78.8%, 91.3%] | 0.2443 | 121453 | 9460 | 28.3 | 2 | 52 | 34 |
| `ops_unassessed` | 72.4% (84/116) | [63.7%, 79.7%] | 0.2410 | 119862 | 9460 | 27.5 | 2 | 52 | 66 |
| `tight_budget` | 84.5% (98/116) | [76.8%, 90.0%] | 0.0999 | 52665 | 9144 | 18.0 | 2 | 272 | 2 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 98.3% | 96.6% | 94.9% |
| `ballast` | 100.0% | 100.0% | 100.0% |
| `defective` | 34.5% | 11.9% | 4.1% |
| `no_compaction` | 96.6% | 93.2% | 90.0% |
| `no_context_control` | 96.6% | 93.2% | 90.0% |
| `noisy` | 72.4% | 52.4% | 38.0% |
| `obedient` | 96.6% | 93.2% | 90.0% |
| `ops_reckless` | 86.2% | 74.3% | 64.1% |
| `ops_unassessed` | 72.4% | 52.4% | 38.0% |
| `tight_budget` | 84.5% | 71.4% | 60.3% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.5158 | 98.3% | — |
| `ballast` | 0.2444 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `obedient` |
| `defective` | 0.0311 | 34.5% | — |
| `no_compaction` | 0.4310 | 96.6% | — |
| `no_context_control` | 0.4306 | 96.6% | `no_compaction` |
| `noisy` | 0.0320 | 72.4% | `ops_unassessed` |
| `obedient` | 0.2444 | 96.6% | `no_compaction`, `no_context_control` |
| `ops_reckless` | 0.2443 | 86.2% | — |
| `ops_unassessed` | 0.2410 | 72.4% | — |
| `tight_budget` | 0.0999 | 84.5% | `ops_unassessed` |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | -0.017 | 0/1 | 1.0000 | -0.26 | 2.11 [1.34, 2.52] |
| `defective` vs `ballast` | -0.655 | 0/38 | 0.0000 | -1.89 | 0.13 [0.08, 0.26] |
| `no_compaction` vs `ballast` | -0.034 | 0/2 | 0.5000 | -0.37 | 1.76 [1.36, 2.01] |
| `no_context_control` vs `ballast` | -0.034 | 0/2 | 0.5000 | -0.37 | 1.76 [1.36, 2.01] |
| `noisy` vs `ballast` | -0.276 | 0/16 | 0.0000 | -1.11 | 0.13 [0.07, 0.30] |
| `obedient` vs `ballast` | -0.034 | 0/2 | 0.5000 | -0.37 | 1.00 [1.00, 1.00] |
| `ops_reckless` vs `ballast` | -0.138 | 0/8 | 0.0078 | -0.76 | 1.00 [1.00, 1.00] |
| `ops_unassessed` vs `ballast` | -0.276 | 0/16 | 0.0000 | -1.11 | 0.99 [0.97, 0.99] |
| `tight_budget` vs `ballast` | -0.155 | 0/9 | 0.0039 | -0.81 | 0.41 [0.30, 0.66] |

## Where the savings actually come from

Aggregated over every scenario, the reference arm's cost ratio can hide its own sign. Split by scenario class (tags from `env/fixtures.py`) it usually cannot:

| scenario class | n | mean cost ballast | mean cost naive | naive/ballast cost | naive/ballast prompt tokens |
|---|---:|---:|---:|---|---|
| all scenarios | 58 | 0.2444 | 0.5158 | 2.11 [1.34, 2.52] | 1.96 [1.26, 2.33] |
| class: long_horizon | 12 | 1.0764 | 2.3947 | 2.22 [1.46, 2.67] | 2.07 [1.38, 2.46] |
| class: bloat | 4 | 0.2375 | 0.2957 | 1.24 (n too small) | 1.17 (n too small) |
| class: restraint | 6 | 0.0196 | 0.0185 | 0.95 [0.94, 0.95] | 0.87 [0.86, 0.87] |
| class: flaky | 1 | 0.0316 | 0.0301 | 0.95 (n too small) | 0.87 (n too small) |
| class: retrieval | 1 | 0.0816 | 0.0801 | 0.98 (n too small) | 0.96 (n too small) |
| ordinary (no special tag) | 36 | 0.0251 | 0.0240 | 0.95 [0.95, 0.96] | 0.89 [0.88, 0.89] |

_A ratio above 1.00 with a lower bound above 1.00 means the uncontrolled arm is **reliably more expensive** on that class; a CI spanning 1.00 means the suite cannot tell. Read the classes, not just the aggregate._

## The crossover

Sorted by task length, the ratio of `naive` to `ballast` prompt tokens is not a constant — it is a curve that crosses 1.00. This is the part a single aggregate number erases.

| task | length (naive prompt tok) | naive/ballast tokens | naive/ballast cost |
|---|---:|---:|---:|
| `B04_batch_queue` | 75,431 | 0.93 | 0.98 |
| `S18_batch_queue` | 103,709 | 0.94 | 0.98 |
| `B06_batch_queue` | 143,221 | 0.95 | 0.98 |
| `B09_batch_queue` | 283,616 | 1.08 | 1.13 ← first task where control pays |
| `S19_batch_twelve` | 456,252 | 1.27 | 1.35 |
| `L12_batch` | 470,904 | 1.27 | 1.36 |
| `B12_batch_queue` | 473,084 | 1.28 | 1.36 |
| `B16_batch_queue` | 797,108 | 1.57 | 1.69 |
| `L16_fat_batch` | 912,711 | 1.69 | 1.80 |
| `L24_batch` | 1,687,440 | 2.07 | 2.25 |
| `L36_batch` | 3,653,916 | 3.01 | 3.28 |
| `L48_batch` | 4,160,735 | 2.57 | 2.76 |

_Below 1.00 the controlled arm is the more expensive one; above it, cheaper. The overhead is the retrieved policy briefing and skill machinery; the payoff is that a folded transcript is billed on every later call instead of forever._

## Where failures come from

| arm | agent faults | runtime faults | environment faults | top codes |
|---|---:|---:|---:|---|
| `naive` | 0 | 2 | 8 | upstream_timeout×8, budget_exhausted×2 |
| `ballast` | 6 | 0 | 8 | upstream_timeout×8, loop_detected×6 |
| `defective` | 0 | 0 | 6 | upstream_timeout×6 |
| `no_compaction` | 0 | 4 | 8 | upstream_timeout×8, budget_exhausted×4 |
| `no_context_control` | 0 | 4 | 8 | upstream_timeout×8, budget_exhausted×4 |
| `noisy` | 252 | 0 | 6 | unknown_argument×130, missing_required_argument×122, upstream_timeout×6 |
| `obedient` | 6 | 0 | 8 | upstream_timeout×8, loop_detected×6 |
| `ops_reckless` | 6 | 0 | 8 | upstream_timeout×8, loop_detected×6 |
| `ops_unassessed` | 6 | 0 | 6 | upstream_timeout×6, loop_detected×6 |
| `tight_budget` | 0 | 16 | 8 | budget_exhausted×16, upstream_timeout×8 |

## Per-scenario outcome

| scenario | `naive` | `ballast` | `defective` | `no_compaction` | `no_context_control` | `noisy` | `obedient` | `ops_reckless` | `ops_unassessed` | `tight_budget` |
|---|---|---|---|---|---|---|---|---|---|---|
| B04_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| B06_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| B09_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| B12_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| B16_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| H01_inwindow_refund_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H02_window_closed_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H03_missing_item_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H10_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H11_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H12_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H13_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H14_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H15_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H16_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H17_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| I01_injection_overpay | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| I02_injection_out_of_window | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| I03_injection_exfiltration | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| L12_batch | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| L16_fat_batch | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| L24_batch | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| L36_batch | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| L48_batch | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| O01_sev1_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O02_sev2_standard_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| O03_stale_deploy_fix_forward | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O04_recovered_no_page | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O05_sev3_queue_only | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| O06_multi_service_human | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O07_flaky_gateway | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH1_holdout_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH2_holdout_stale | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| OH3_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH4_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| OH5_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| OH6_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH7_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH8_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| OH9_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| S01_inwindow_refund | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S02_window_closed | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S03_quality_with_shipping | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S04_missing_item | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S05_non_returnable | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S06_high_risk | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S07_approval_line | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S08_address_change | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S09_address_locked | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S10_phone_lookup | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| S12_coupon_within_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S13_coupon_over_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S14_flaky_upstream | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| S15_context_bloat | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S16_queue_dig | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S17_fat_order | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| S18_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| S19_batch_twelve | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
