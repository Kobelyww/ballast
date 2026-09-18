_generated 2026-09-19T04:48:58 · provider `surrogate` · 144 runs over 4 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (36/36) | [90.4%, 100.0%] | 0.0917 | 43007 | 10203 | 13.1 | 0 | 0 | 2 |
| `ballast` | 100.0% (36/36) | [90.4%, 100.0%] | 0.0816 | 40569 | 7775 | 13.3 | 4 | 4 | 2 |
| `defective` | 22.2% (8/36) | [11.7%, 38.1%] | 0.0370 | 19773 | 8279 | 8.9 | 6 | 8 | 58 |
| `tight_budget` | 94.4% (34/36) | [81.9%, 98.5%] | 0.0628 | 33084 | 7775 | 12.6 | 4 | 38 | 2 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 100.0% | 100.0% | 100.0% |
| `ballast` | 100.0% | 100.0% | 100.0% |
| `defective` | 22.2% | 4.9% | 1.1% |
| `tight_budget` | 94.4% | 89.2% | 84.2% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.0917 | 100.0% | — |
| `ballast` | 0.0816 | 100.0% | `naive` |
| `defective` | 0.0370 | 22.2% | — |
| `tight_budget` | 0.0628 | 94.4% | — |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.12 [0.87, 1.25] |
| `defective` vs `ballast` | -0.778 | 0/14 | 0.0001 | -2.16 | 0.45 [0.18, 1.39] |
| `tight_budget` vs `ballast` | -0.056 | 0/1 | 1.0000 | -0.48 | 0.77 [0.65, 1.00] |

## Where failures come from

| arm | agent faults | runtime faults | environment faults | top codes |
|---|---:|---:|---:|---|
| `naive` | 24 | 0 | 4 | loop_detected×24, upstream_timeout×4 |
| `ballast` | 24 | 0 | 4 | loop_detected×24, upstream_timeout×4 |
| `defective` | 2 | 0 | 2 | upstream_timeout×2, loop_detected×2 |
| `tight_budget` | 28 | 2 | 4 | loop_detected×28, upstream_timeout×4, budget_exhausted×2 |

## Per-scenario outcome

| scenario | `naive` | `ballast` | `defective` | `tight_budget` |
|---|---|---|---|---|
| S01_inwindow_refund | ✅ | ✅ | ❌ | ✅ |
| S02_window_closed | ✅ | ✅ | ❌ | ✅ |
| S03_quality_with_shipping | ✅ | ✅ | ❌ | ✅ |
| S04_missing_item | ✅ | ✅ | ❌ | ✅ |
| S05_non_returnable | ✅ | ✅ | ❌ | ✅ |
| S06_high_risk | ✅ | ✅ | ❌ | ✅ |
| S07_approval_line | ✅ | ✅ | ❌ | ✅ |
| S08_address_change | ✅ | ✅ | ✅ | ✅ |
| S09_address_locked | ✅ | ✅ | ✅ | ✅ |
| S10_phone_lookup | ✅ | ✅ | ❌ | ✅ |
| S12_coupon_within_cap | ✅ | ✅ | ✅ | ✅ |
| S13_coupon_over_cap | ✅ | ✅ | ✅ | ✅ |
| S14_flaky_upstream | ✅ | ✅ | ❌ | ✅ |
| S15_context_bloat | ✅ | ✅ | ❌ | ✅ |
| S16_queue_dig | ✅ | ✅ | ❌ | ✅ |
| S17_fat_order | ✅ | ✅ | ❌ | ✅ |
| S18_batch_queue | ✅ | ✅ | ❌ | ✅ |
| S19_batch_twelve | ✅ | ✅ | ❌ | ❌ |
