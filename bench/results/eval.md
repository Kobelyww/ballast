_generated 2026-09-19T05:45:32 · provider `surrogate` · 828 runs over 12 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (69/69) | [94.7%, 100.0%] | 0.2365 | 110053 | 13818 | 23.1 | 0 | 0 | 3 |
| `ballast` | 100.0% (69/69) | [94.7%, 100.0%] | 0.1876 | 92941 | 7775 | 23.7 | 6 | 18 | 3 |
| `bloated` | 100.0% (69/69) | [94.7%, 100.0%] | 0.1929 | 95645 | 7775 | 24.3 | 9 | 18 | 3 |
| `defective` | 17.4% (12/69) | [10.2%, 28.0%] | 0.0367 | 19610 | 8279 | 8.9 | 9 | 12 | 117 |
| `hierarchical` | 100.0% (69/69) | [94.7%, 100.0%] | 0.1904 | 94532 | 7847 | 23.7 | 6 | 18 | 3 |
| `no_budget` | 100.0% (69/69) | [94.7%, 100.0%] | 0.1876 | 92941 | 7775 | 23.7 | 6 | 18 | 3 |
| `no_compaction` | 100.0% (69/69) | [94.7%, 100.0%] | 0.2418 | 115379 | 14022 | 23.2 | 6 | 0 | 3 |
| `no_context_control` | 100.0% (69/69) | [94.7%, 100.0%] | 0.2399 | 114578 | 14022 | 23.1 | 0 | 0 | 3 |
| `no_offload` | 100.0% (69/69) | [94.7%, 100.0%] | 0.1861 | 92386 | 7649 | 23.6 | 0 | 15 | 3 |
| `noisy` | 56.5% (39/69) | [44.8%, 67.6%] | 0.0472 | 24259 | 8996 | 10.3 | 12 | 33 | 3 |
| `static_briefing` | 100.0% (69/69) | [94.7%, 100.0%] | 0.1858 | 88993 | 7628 | 23.7 | 6 | 18 | 3 |
| `tight_budget` | 82.6% (57/69) | [72.0%, 89.8%] | 0.1254 | 66714 | 7775 | 21.0 | 6 | 228 | 3 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 100.0% | 100.0% | 100.0% |
| `ballast` | 100.0% | 100.0% | 100.0% |
| `bloated` | 100.0% | 100.0% | 100.0% |
| `defective` | 17.4% | 3.0% | 0.5% |
| `hierarchical` | 100.0% | 100.0% | 100.0% |
| `no_budget` | 100.0% | 100.0% | 100.0% |
| `no_compaction` | 100.0% | 100.0% | 100.0% |
| `no_context_control` | 100.0% | 100.0% | 100.0% |
| `no_offload` | 100.0% | 100.0% | 100.0% |
| `noisy` | 56.5% | 31.9% | 18.1% |
| `static_briefing` | 100.0% | 100.0% | 100.0% |
| `tight_budget` | 82.6% | 68.2% | 56.4% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.2365 | 100.0% | `no_compaction`, `no_context_control` |
| `ballast` | 0.1876 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `hierarchical`, `bloated` |
| `bloated` | 0.1929 | 100.0% | `naive`, `no_compaction`, `no_context_control` |
| `defective` | 0.0367 | 17.4% | — |
| `hierarchical` | 0.1904 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `bloated` |
| `no_budget` | 0.1876 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `hierarchical`, `bloated` |
| `no_compaction` | 0.2418 | 100.0% | — |
| `no_context_control` | 0.2399 | 100.0% | `no_compaction` |
| `no_offload` | 0.1861 | 100.0% | `naive`, `ballast`, `no_compaction`, `no_context_control`, `no_budget`, `hierarchical`, `bloated` |
| `noisy` | 0.0472 | 56.5% | — |
| `static_briefing` | 0.1858 | 100.0% | `naive`, `ballast`, `no_offload`, `no_compaction`, `no_context_control`, `no_budget`, `hierarchical`, `bloated` |
| `tight_budget` | 0.1254 | 82.6% | — |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.26 [1.00, 1.42] |
| `bloated` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.03 [1.01, 1.10] |
| `defective` vs `ballast` | -0.826 | 0/19 | 0.0000 | -2.28 | 0.20 [0.11, 0.47] |
| `hierarchical` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.01 [1.01, 1.02] |
| `no_budget` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.00 [1.00, 1.00] |
| `no_compaction` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.29 [1.05, 1.45] |
| `no_context_control` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.28 [1.02, 1.44] |
| `no_offload` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.99 [0.97, 1.00] |
| `noisy` vs `ballast` | -0.435 | 0/10 | 0.0020 | -1.44 | 0.25 [0.09, 0.78] |
| `static_briefing` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.99 [0.98, 1.00] |
| `tight_budget` vs `ballast` | -0.174 | 0/4 | 0.1250 | -0.86 | 0.67 [0.56, 0.89] |

## Where the savings actually come from

Aggregated over every scenario, the reference arm's cost ratio can hide its own sign. Split by scenario class (tags from `env/fixtures.py`) it usually cannot:

| scenario class | n | mean cost ballast | mean cost naive | naive/ballast cost | naive/ballast prompt tokens |
|---|---:|---:|---:|---|---|
| all scenarios | 23 | 0.1876 | 0.2365 | 1.26 [1.00, 1.42] | 1.18 [0.96, 1.32] |
| class: long_horizon | 7 | 0.5481 | 0.7162 | 1.31 [1.10, 1.48] | 1.23 [1.04, 1.37] |
| class: bloat | 4 | 0.2376 | 0.2876 | 1.21 (n too small) | 1.14 (n too small) |
| class: restraint | 4 | 0.0194 | 0.0184 | 0.95 (n too small) | 0.86 (n too small) |
| class: flaky | 1 | 0.0315 | 0.0300 | 0.95 (n too small) | 0.87 (n too small) |
| class: retrieval | 1 | 0.0986 | 0.0786 | 0.80 (n too small) | 0.87 (n too small) |
| ordinary (no special tag) | 8 | 0.0227 | 0.0217 | 0.95 [0.95, 0.96] | 0.88 [0.87, 0.89] |

_A ratio above 1.00 with a lower bound above 1.00 means the uncontrolled arm is **reliably more expensive** on that class; a CI spanning 1.00 means the suite cannot tell. Read the classes, not just the aggregate._

## Where failures come from

| arm | agent faults | runtime faults | environment faults | top codes |
|---|---:|---:|---:|---|
| `naive` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `ballast` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `bloated` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `defective` | 3 | 0 | 3 | upstream_timeout×3, loop_detected×3 |
| `hierarchical` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `no_budget` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `no_compaction` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `no_context_control` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `no_offload` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `noisy` | 279 | 0 | 3 | unknown_argument×114, missing_required_argument×102, loop_detected×63 |
| `static_briefing` | 126 | 0 | 6 | loop_detected×126, upstream_timeout×6 |
| `tight_budget` | 150 | 12 | 6 | loop_detected×150, budget_exhausted×12, upstream_timeout×6 |

## Per-scenario outcome

| scenario | `naive` | `ballast` | `bloated` | `defective` | `hierarchical` | `no_budget` | `no_compaction` | `no_context_control` | `no_offload` | `noisy` | `static_briefing` | `tight_budget` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B04_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| B06_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| B09_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| B12_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| B16_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| S01_inwindow_refund | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S02_window_closed | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S03_quality_with_shipping | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S04_missing_item | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S05_non_returnable | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S06_high_risk | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S07_approval_line | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S08_address_change | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S09_address_locked | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S10_phone_lookup | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| S12_coupon_within_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S13_coupon_over_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S14_flaky_upstream | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| S15_context_bloat | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S16_queue_dig | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S17_fat_order | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| S18_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| S19_batch_twelve | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
