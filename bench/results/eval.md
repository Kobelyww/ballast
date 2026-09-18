_generated 2026-09-19T07:41:14 · provider `surrogate` · 1350 runs over 9 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (150/150) | [97.5%, 100.0%] | 0.1219 | 56615 | 13818 | 15.3 | 0 | 0 | 3 |
| `ballast` | 100.0% (150/150) | [97.5%, 100.0%] | 0.1001 | 49480 | 7775 | 15.5 | 6 | 18 | 3 |
| `defective` | 40.0% (60/150) | [32.5%, 48.0%] | 0.0310 | 15903 | 8279 | 8.8 | 9 | 12 | 183 |
| `no_compaction` | 100.0% (150/150) | [97.5%, 100.0%] | 0.1250 | 59801 | 14022 | 15.3 | 6 | 0 | 3 |
| `no_context_control` | 100.0% (150/150) | [97.5%, 100.0%] | 0.1241 | 59433 | 14022 | 15.3 | 0 | 0 | 3 |
| `noisy` | 80.0% (120/150) | [72.9%, 85.6%] | 0.0392 | 19470 | 8996 | 10.2 | 12 | 33 | 3 |
| `ops_reckless` | 84.0% (126/150) | [77.3%, 89.0%] | 0.1000 | 49452 | 7775 | 15.5 | 6 | 18 | 51 |
| `ops_unassessed` | 68.0% (102/150) | [60.2%, 74.9%] | 0.0962 | 47609 | 7775 | 14.5 | 6 | 18 | 99 |
| `tight_budget` | 92.0% (138/150) | [86.5%, 95.4%] | 0.0714 | 37415 | 7775 | 14.3 | 6 | 228 | 3 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 100.0% | 100.0% | 100.0% |
| `ballast` | 100.0% | 100.0% | 100.0% |
| `defective` | 40.0% | 16.0% | 6.4% |
| `no_compaction` | 100.0% | 100.0% | 100.0% |
| `no_context_control` | 100.0% | 100.0% | 100.0% |
| `noisy` | 80.0% | 64.0% | 51.2% |
| `ops_reckless` | 84.0% | 70.6% | 59.3% |
| `ops_unassessed` | 68.0% | 46.2% | 31.4% |
| `tight_budget` | 92.0% | 84.6% | 77.9% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.1219 | 100.0% | `no_compaction`, `no_context_control` |
| `ballast` | 0.1001 | 100.0% | `naive`, `no_compaction`, `no_context_control` |
| `defective` | 0.0310 | 40.0% | — |
| `no_compaction` | 0.1250 | 100.0% | — |
| `no_context_control` | 0.1241 | 100.0% | `no_compaction` |
| `noisy` | 0.0392 | 80.0% | `ops_unassessed` |
| `ops_reckless` | 0.1000 | 84.0% | — |
| `ops_unassessed` | 0.0962 | 68.0% | — |
| `tight_budget` | 0.0714 | 92.0% | `ops_unassessed`, `ops_reckless` |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.22 [0.98, 1.37] |
| `defective` vs `ballast` | -0.600 | 0/30 | 0.0000 | -1.77 | 0.31 [0.19, 0.66] |
| `no_compaction` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.25 [1.03, 1.40] |
| `no_context_control` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.24 [1.01, 1.39] |
| `noisy` vs `ballast` | -0.200 | 0/10 | 0.0020 | -0.93 | 0.39 [0.20, 0.97] |
| `ops_reckless` vs `ballast` | -0.160 | 0/8 | 0.0078 | -0.82 | 1.00 [1.00, 1.00] |
| `ops_unassessed` vs `ballast` | -0.320 | 0/16 | 0.0000 | -1.20 | 0.96 [0.91, 0.98] |
| `tight_budget` vs `ballast` | -0.080 | 0/4 | 0.1250 | -0.57 | 0.71 [0.61, 0.93] |

## Where the savings actually come from

Aggregated over every scenario, the reference arm's cost ratio can hide its own sign. Split by scenario class (tags from `env/fixtures.py`) it usually cannot:

| scenario class | n | mean cost ballast | mean cost naive | naive/ballast cost | naive/ballast prompt tokens |
|---|---:|---:|---:|---|---|
| all scenarios | 50 | 0.1001 | 0.1219 | 1.22 [0.98, 1.37] | 1.14 [0.94, 1.27] |
| class: long_horizon | 7 | 0.5481 | 0.7162 | 1.31 [1.10, 1.48] | 1.23 [1.04, 1.37] |
| class: bloat | 4 | 0.2376 | 0.2876 | 1.21 (n too small) | 1.14 (n too small) |
| class: restraint | 5 | 0.0194 | 0.0184 | 0.95 [0.94, 0.95] | 0.86 [0.86, 0.87] |
| class: flaky | 1 | 0.0315 | 0.0300 | 0.95 (n too small) | 0.87 (n too small) |
| class: retrieval | 1 | 0.0986 | 0.0786 | 0.80 (n too small) | 0.87 (n too small) |
| ordinary (no special tag) | 34 | 0.0250 | 0.0239 | 0.95 [0.95, 0.96] | 0.89 [0.88, 0.89] |

_A ratio above 1.00 with a lower bound above 1.00 means the uncontrolled arm is **reliably more expensive** on that class; a CI spanning 1.00 means the suite cannot tell. Read the classes, not just the aggregate._

## The crossover

Sorted by task length, the ratio of `naive` to `ballast` prompt tokens is not a constant — it is a curve that crosses 1.00. This is the part a single aggregate number erases.

| task | length (naive prompt tok) | naive/ballast tokens | naive/ballast cost |
|---|---:|---:|---:|
| `B04_batch_queue` | 74,941 | 0.93 | 0.98 |
| `S18_batch_queue` | 102,927 | 0.94 | 0.98 |
| `B06_batch_queue` | 142,169 | 0.95 | 0.98 |
| `B09_batch_queue` | 281,306 | 1.06 | 1.10 ← first task where control pays |
| `S19_batch_twelve` | 452,345 | 1.24 | 1.31 |
| `B12_batch_queue` | 468,913 | 1.23 | 1.31 |
| `B16_batch_queue` | 789,761 | 1.49 | 1.62 |

_Below 1.00 the controlled arm is the more expensive one; above it, cheaper. The overhead is the retrieved policy briefing and skill machinery; the payoff is that a folded transcript is billed on every later call instead of forever._

## Where failures come from

| arm | agent faults | runtime faults | environment faults | top codes |
|---|---:|---:|---:|---|
| `naive` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `ballast` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `defective` | 3 | 0 | 9 | upstream_timeout×9, loop_detected×3 |
| `no_compaction` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `no_context_control` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `noisy` | 444 | 0 | 9 | unknown_argument×180, missing_required_argument×168, loop_detected×96 |
| `ops_reckless` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `ops_unassessed` | 126 | 0 | 9 | loop_detected×126, upstream_timeout×9 |
| `tight_budget` | 150 | 12 | 12 | loop_detected×150, upstream_timeout×12, budget_exhausted×12 |

## Per-scenario outcome

| scenario | `naive` | `ballast` | `defective` | `no_compaction` | `no_context_control` | `noisy` | `ops_reckless` | `ops_unassessed` | `tight_budget` |
|---|---|---|---|---|---|---|---|---|---|
| B04_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| B06_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| B09_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| B12_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| B16_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| H01_inwindow_refund_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H02_window_closed_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H03_missing_item_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H10_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H11_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H12_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H13_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H14_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H15_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H16_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H17_holdout | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| O01_sev1_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O02_sev2_standard_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| O03_stale_deploy_fix_forward | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O04_recovered_no_page | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O05_sev3_queue_only | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| O06_multi_service_human | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O07_flaky_gateway | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH1_holdout_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH2_holdout_stale | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| OH3_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH4_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| OH5_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| OH6_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH7_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH8_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| OH9_holdout | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| S01_inwindow_refund | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S02_window_closed | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S03_quality_with_shipping | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S04_missing_item | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S05_non_returnable | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S06_high_risk | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S07_approval_line | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S08_address_change | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S09_address_locked | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S10_phone_lookup | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| S12_coupon_within_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S13_coupon_over_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S14_flaky_upstream | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| S15_context_bloat | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S16_queue_dig | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S17_fat_order | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| S18_batch_queue | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| S19_batch_twelve | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
