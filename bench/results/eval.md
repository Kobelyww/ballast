_generated 2026-09-19T07:13:53 · provider `surrogate` · 1677 runs over 13 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (129/129) | [97.1%, 100.0%] | 0.1375 | 63901 | 13818 | 16.3 | 0 | 0 | 3 |
| `ballast` | 100.0% (129/129) | [97.1%, 100.0%] | 0.1119 | 55402 | 7775 | 16.5 | 6 | 18 | 3 |
| `bloated` | 100.0% (129/129) | [97.1%, 100.0%] | 0.1157 | 57285 | 7775 | 17.2 | 9 | 18 | 3 |
| `defective` | 30.2% (39/129) | [23.0%, 38.6%] | 0.0316 | 16360 | 8279 | 8.7 | 9 | 12 | 183 |
| `hierarchical` | 100.0% (129/129) | [97.1%, 100.0%] | 0.1138 | 56499 | 7847 | 16.5 | 6 | 18 | 3 |
| `no_budget` | 100.0% (129/129) | [97.1%, 100.0%] | 0.1119 | 55402 | 7775 | 16.5 | 6 | 18 | 3 |
| `no_compaction` | 100.0% (129/129) | [97.1%, 100.0%] | 0.1408 | 67404 | 14022 | 16.3 | 6 | 0 | 3 |
| `no_context_control` | 100.0% (129/129) | [97.1%, 100.0%] | 0.1398 | 66975 | 14022 | 16.3 | 0 | 0 | 3 |
| `no_offload` | 100.0% (129/129) | [97.1%, 100.0%] | 0.1111 | 55105 | 7649 | 16.5 | 0 | 15 | 3 |
| `noisy` | 76.7% (99/129) | [68.7%, 83.2%] | 0.0411 | 20507 | 8996 | 10.4 | 12 | 33 | 3 |
| `ops_reckless` | 88.4% (114/129) | [81.7%, 92.8%] | 0.1118 | 55346 | 7775 | 16.5 | 6 | 18 | 33 |
| `ops_unassessed` | 79.1% (102/129) | [71.3%, 85.2%] | 0.1093 | 54162 | 7775 | 15.9 | 6 | 18 | 57 |
| `tight_budget` | 90.7% (117/129) | [84.4%, 94.6%] | 0.0786 | 41374 | 7775 | 15.1 | 6 | 228 | 3 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 100.0% | 100.0% | 100.0% |
| `ballast` | 100.0% | 100.0% | 100.0% |
| `bloated` | 100.0% | 100.0% | 100.0% |
| `defective` | 30.2% | 9.1% | 2.8% |
| `hierarchical` | 100.0% | 100.0% | 100.0% |
| `no_budget` | 100.0% | 100.0% | 100.0% |
| `no_compaction` | 100.0% | 100.0% | 100.0% |
| `no_context_control` | 100.0% | 100.0% | 100.0% |
| `no_offload` | 100.0% | 100.0% | 100.0% |
| `noisy` | 76.7% | 58.9% | 45.2% |
| `ops_reckless` | 88.4% | 78.1% | 69.0% |
| `ops_unassessed` | 79.1% | 62.5% | 49.4% |
| `tight_budget` | 90.7% | 82.3% | 74.6% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.1375 | 100.0% | `no_compaction`, `no_context_control` |
| `ballast` | 0.1119 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `hierarchical`, `bloated` |
| `bloated` | 0.1157 | 100.0% | `naive`, `no_compaction`, `no_context_control` |
| `defective` | 0.0316 | 30.2% | — |
| `hierarchical` | 0.1138 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `bloated` |
| `no_budget` | 0.1119 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `hierarchical`, `bloated` |
| `no_compaction` | 0.1408 | 100.0% | — |
| `no_context_control` | 0.1398 | 100.0% | `no_compaction` |
| `no_offload` | 0.1111 | 100.0% | `naive`, `ballast`, `no_compaction`, `no_context_control`, `no_budget`, `hierarchical`, `bloated`, `ops_reckless` |
| `noisy` | 0.0411 | 76.7% | — |
| `ops_reckless` | 0.1118 | 88.4% | — |
| `ops_unassessed` | 0.1093 | 79.1% | — |
| `tight_budget` | 0.0786 | 90.7% | `ops_unassessed`, `ops_reckless` |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.23 [0.98, 1.38] |
| `bloated` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.03 [1.01, 1.10] |
| `defective` vs `ballast` | -0.698 | 0/30 | 0.0000 | -1.98 | 0.28 [0.17, 0.63] |
| `hierarchical` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.02 [1.01, 1.02] |
| `no_budget` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.00 [1.00, 1.00] |
| `no_compaction` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.26 [1.03, 1.40] |
| `no_context_control` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.25 [1.01, 1.40] |
| `no_offload` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.99 [0.97, 1.00] |
| `noisy` vs `ballast` | -0.233 | 0/10 | 0.0020 | -1.01 | 0.37 [0.17, 0.95] |
| `ops_reckless` vs `ballast` | -0.116 | 0/5 | 0.0625 | -0.70 | 1.00 [1.00, 1.00] |
| `ops_unassessed` vs `ballast` | -0.209 | 0/9 | 0.0039 | -0.95 | 0.98 [0.93, 0.99] |
| `tight_budget` vs `ballast` | -0.093 | 0/4 | 0.1250 | -0.62 | 0.70 [0.60, 0.92] |

## Where the savings actually come from

Aggregated over every scenario, the reference arm's cost ratio can hide its own sign. Split by scenario class (tags from `env/fixtures.py`) it usually cannot:

| scenario class | n | mean cost ballast | mean cost naive | naive/ballast cost | naive/ballast prompt tokens |
|---|---:|---:|---:|---|---|
| all scenarios | 43 | 0.1119 | 0.1375 | 1.23 [0.98, 1.38] | 1.15 [0.94, 1.28] |
| class: long_horizon | 7 | 0.5481 | 0.7162 | 1.31 [1.10, 1.48] | 1.23 [1.04, 1.37] |
| class: bloat | 4 | 0.2376 | 0.2876 | 1.21 (n too small) | 1.14 (n too small) |
| class: restraint | 5 | 0.0194 | 0.0184 | 0.95 [0.94, 0.95] | 0.86 [0.86, 0.87] |
| class: flaky | 1 | 0.0315 | 0.0300 | 0.95 (n too small) | 0.87 (n too small) |
| class: retrieval | 1 | 0.0986 | 0.0786 | 0.80 (n too small) | 0.87 (n too small) |
| ordinary (no special tag) | 27 | 0.0244 | 0.0232 | 0.95 [0.95, 0.96] | 0.88 [0.88, 0.89] |

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
| `bloated` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `defective` | 3 | 0 | 9 | upstream_timeout×9, loop_detected×3 |
| `hierarchical` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `no_budget` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `no_compaction` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `no_context_control` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `no_offload` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `noisy` | 444 | 0 | 9 | unknown_argument×180, missing_required_argument×168, loop_detected×96 |
| `ops_reckless` | 126 | 0 | 12 | loop_detected×126, upstream_timeout×12 |
| `ops_unassessed` | 126 | 0 | 9 | loop_detected×126, upstream_timeout×9 |
| `tight_budget` | 150 | 12 | 12 | loop_detected×150, upstream_timeout×12, budget_exhausted×12 |

## Per-scenario outcome

| scenario | `naive` | `ballast` | `bloated` | `defective` | `hierarchical` | `no_budget` | `no_compaction` | `no_context_control` | `no_offload` | `noisy` | `ops_reckless` | `ops_unassessed` | `tight_budget` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B04_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| B06_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| B09_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| B12_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| B16_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| H01_inwindow_refund_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H02_window_closed_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H03_missing_item_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H10_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H11_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H12_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H13_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H14_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H15_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H16_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| H17_holdout | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| O01_sev1_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O02_sev2_standard_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| O03_stale_deploy_fix_forward | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O04_recovered_no_page | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O05_sev3_queue_only | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| O06_multi_service_human | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| O07_flaky_gateway | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH1_holdout_recent_deploy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| OH2_holdout_stale | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| S01_inwindow_refund | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S02_window_closed | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S03_quality_with_shipping | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S04_missing_item | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S05_non_returnable | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S06_high_risk | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S07_approval_line | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S08_address_change | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S09_address_locked | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S10_phone_lookup | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| S12_coupon_within_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S13_coupon_over_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S14_flaky_upstream | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| S15_context_bloat | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S16_queue_dig | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S17_fat_order | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| S18_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| S19_batch_twelve | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
